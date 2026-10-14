"""Patch capture and native stream evidence for the disposable ALP fixture.

The caller must first stop and drain the editing process. Staging uses private
metadata and objects; the source repository's index, objects and refs are never
written. These are evidence seams, not a process sandbox or task executor.
"""
import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid


_CONFIG = (
    'core.hooksPath=/dev/null', 'core.quotePath=true', 'core.fileMode=true',
    'core.autocrlf=false', 'core.safecrlf=false', 'core.symlinks=true',
    'core.fsmonitor=false', 'core.excludesFile=/dev/null',
    'core.attributesFile=/dev/null', 'diff.noprefix=false',
    'diff.mnemonicPrefix=false', 'diff.relative=false',
    'advice.addEmbeddedRepo=false',
)
_DIFF = (
    'diff', '--cached', '--no-ext-diff', '--no-textconv', '--no-color',
    '--no-renames', '--full-index', '--diff-algorithm=myers',
    '--indent-heuristic', '--ignore-submodules=none',
    '--src-prefix=a/', '--dst-prefix=b/',
)


class _CaptureError(Exception):
    pass


def _environment():
    # Do not inherit GIT_*, executable search paths, loader settings or secrets.
    return dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LC_ALL='C', TZ='UTC',
                GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')


def _git(cwd, args, env, *, gitdir=None, base=None):
    argv = ['/usr/bin/git']
    if base is not None:
        argv.append('--attr-source=' + base)
    for setting in _CONFIG:
        argv.extend(('-c', setting))
    if gitdir is not None:
        argv.extend(('--git-dir=' + str(gitdir), '--work-tree=' + str(cwd),
                     '-c', 'core.bare=false'))
    argv.extend(args)
    result = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30, close_fds=True, check=False)
    if result.returncode:
        # Git stderr can contain private paths or configuration. Never export it.
        raise _CaptureError('git_error')
    return result.stdout


def _source(cwd, env):
    entries = _git(cwd, ('config', '--local', '--no-includes', '--null', '--list'), env)
    for entry in entries.split(b'\0'):
        key = entry.split(b'\n', 1)[0].lower()
        if (key.startswith((b'include.', b'includeif.', b'filter.'))
                or key == b'core.attributesfile'
                or key == b'extensions.worktreeconfig'):
            raise _CaptureError('unsafe_git_config')
    common = Path(os.fsdecode(_git(cwd, ('rev-parse', '--git-common-dir'), env).rstrip(b'\n')))
    if not common.is_absolute():
        common = cwd / common
    common = common.resolve(strict=True)
    attributes = common / 'info' / 'attributes'
    if attributes.is_symlink() or (attributes.exists() and attributes.read_bytes()):
        raise _CaptureError('unsafe_attributes')
    objects = (common / 'objects').resolve(strict=True)
    if not objects.is_dir() or '\n' in str(objects) or '\r' in str(objects):
        raise _CaptureError('invalid_repository')
    head = _git(cwd, ('rev-parse', '--verify', 'HEAD'), env).decode('ascii').strip()
    return objects, head


def canonical_patch(worktree, base_sha):
    """Return the frozen six-field canonical-patch-v1 DTO, with full metrics.

    Errors yield unavailable without exception text or a fabricated artifact.
    Only trusted SHA-1 fixture repositories are supported by this profile.
    """
    result = dict(base_sha=base_sha, patch_status='unavailable', patch=None,
                  patch_bytes=None, patch_sha256=None, reasons=[])
    try:
        if type(base_sha) is not str or re.fullmatch(r'[0-9a-f]{40}', base_sha) is None:
            raise _CaptureError('invalid_base')
        cwd = Path(worktree).resolve(strict=True)
        env = _environment()
        objects, head = _source(cwd, env)
        reasons = [] if head == base_sha else ['head_moved']
        # Scratch lives outside the editable tree; no project files are excluded.
        with tempfile.TemporaryDirectory(prefix='control-canonical-', dir='/var/tmp') as scratch:
            gitdir = Path(scratch) / 'git'
            _git(cwd, ('init', '--bare', '--template=', str(gitdir)), env)
            (gitdir / 'objects' / 'info' / 'alternates').write_bytes(os.fsencode(objects) + b'\n')
            env['GIT_INDEX_FILE'] = str(Path(scratch) / 'index')
            _git(cwd, ('read-tree', base_sha), env, gitdir=gitdir, base=base_sha)
            _git(cwd, ('add', '--all', '--force', '--', '.'), env, gitdir=gitdir, base=base_sha)
            raw = _git(cwd, (*_DIFF, '--raw', '-z', base_sha, '--'), env,
                       gitdir=gitdir, base=base_sha)
            numstat = _git(cwd, (*_DIFF, '--numstat', '-z', base_sha, '--'), env,
                           gitdir=gitdir, base=base_sha)
            patch = _git(cwd, (*_DIFF, '--patch', '-U3', base_sha, '--'), env,
                         gitdir=gitdir, base=base_sha)
        records = raw.split(b'\0')
        for index in range(0, len(records) - 1, 2):
            metadata = records[index].split()
            for mode in (metadata[0][1:], metadata[1]):
                if mode not in (b'000000', b'100644', b'100755'):
                    kind = {b'120000': 'symlink', b'160000': 'submodule'}.get(
                        mode, 'mode_' + mode.decode('ascii'))
                    reasons.append('unsupported_' + kind)
        if any(record.startswith(b'-\t-\t') for record in numstat.split(b'\0')):
            reasons.append('unsupported_binary')
        try:
            text = patch.decode('utf-8')
        except UnicodeDecodeError:
            text = None
            reasons.append('unsupported_non_utf8')
        if b'\r' in patch:
            reasons.append('unsupported_cr')
        status = ('unsupported' if reasons else 'oversize' if len(patch) > 32768
                  else 'ok' if raw else 'empty')
        result.update(patch_status=status,
                      patch=text if status in ('ok', 'empty') else None,
                      patch_bytes=len(patch), patch_sha256=hashlib.sha256(patch).hexdigest(),
                      reasons=sorted(set(reasons)))
    except _CaptureError as error:
        result['reasons'] = [str(error)]
    except (OSError, ValueError, TypeError, UnicodeError, IndexError,
            subprocess.SubprocessError):
        result['reasons'] = ['capture_error']
    return result


def _native_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate native field')
        result[key] = value
    return result


def _native_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite native number')
    return number


def _native_constant(value):
    raise ValueError('invalid native constant')


def decode_native_stream(lines, expected_session_uuid, expected_model):
    """Project bounded native JSON lines into session/model/turn evidence.

    This does not prove process exit, account identity or execution isolation.
    Limits count original bytes, including any supplied line separators; no
    bytes are stripped or silently truncated before accounting.
    """
    evidence = dict(binding='unknown', model=None, successful_turn=False,
                    effort_state='requested_unverified')
    try:
        if (type(expected_session_uuid) is not str
                or str(uuid.UUID(expected_session_uuid)) != expected_session_uuid
                or type(expected_model) is not str or not expected_model):
            return evidence
        total = 0
        init = result = None
        conflict = False
        for raw in lines:
            if type(raw) is not bytes:
                return evidence
            total += len(raw)
            if len(raw) > 1048576 or total > 4194304:
                return evidence
            record = json.loads(raw.decode('utf-8'), object_pairs_hook=_native_object,
                                parse_float=_native_float, parse_constant=_native_constant)
            # Escaped lone surrogates are invalid UTF-8 evidence too.
            json.dumps(record, ensure_ascii=False).encode('utf-8')
            if type(record) is not dict or type(record.get('type')) is not str:
                return evidence
            if record['type'] == 'system' and record.get('subtype') == 'init':
                projection = (record.get('session_id'), record.get('model'))
                if any(type(value) is not str for value in projection):
                    return evidence
                if result is not None:
                    conflict = True
                if init is None:
                    init = projection
                elif init != projection:
                    conflict = True
            elif record['type'] == 'result':
                projection = (record.get('session_id'), record.get('subtype'),
                              record.get('is_error'))
                if (type(projection[0]) is not str or type(projection[1]) is not str
                        or type(projection[2]) is not bool):
                    return evidence
                if init is None:
                    conflict = True
                if result is None:
                    result = projection
                elif result != projection:
                    conflict = True
            # Irrelevant valid records and extra envelope fields have no
            # session/model/turn authority, including rate_limit_event.
        if init is not None and type(init[1]) is str:
            evidence['model'] = init[1]
        if (not conflict and init is not None and result is not None
                and init[0] == result[0] == expected_session_uuid):
            evidence['binding'] = 'verified'
            evidence['successful_turn'] = (init[1] == expected_model
                                           and result[1] == 'success'
                                           and result[2] is False)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        # Never publish raw native lines, parser exception strings or tokens.
        pass
    return evidence


_DEPENDENCIES = ContextVar('control_runner_test_dependencies', default=None)


@contextmanager
def _test_dependencies(process_factory, clock):
    """Scoped raw-process DI; never selected through profiles or wire input."""
    token = _DEPENDENCIES.set((process_factory, clock))
    try:
        yield
    finally:
        _DEPENDENCIES.reset(token)


def _owned_drain(observation, token):
    return (type(observation) is dict and observation.get('launch_token') == token
            and type(observation.get('pid')) is int and observation['pid'] > 0
            and type(observation.get('start_identity')) is str and bool(observation['start_identity'])
            and observation.get('ownership_verified') is True
            and observation.get('alive') is False
            and observation.get('descendants_alive') is False)


class _ProcessCapture:
    """One bounded I/O/ownership observation per supervisor pump cycle."""
    def __init__(self, handle, launch, clock, total_limit):
        self.handle, self.launch, self.clock = handle, launch, clock
        self.total_limit = total_limit
        self.stdout = bytearray()
        self.total = 0
        self.eof = set()
        self.timed_out = self.capture_error = False
        self.done = False
        self.drained = False
        self.observation = None
        self.exit_code = None

    def step(self):
        if self.done:
            return False
        deadline = self.launch['deadline']
        if self.clock() < deadline and not self.capture_error:
            chunks = self.handle.read(min(8192, max(1, self.total_limit + 1 - self.total)),
                                      min(deadline, self.clock() + 0.25))
            for stream, chunk in chunks:
                if stream not in ('stdout', 'stderr') or type(chunk) is not bytes:
                    self.capture_error = True
                    break
                if not chunk:
                    self.eof.add(stream)
                    continue
                self.total += len(chunk)
                if self.total > self.total_limit:
                    self.capture_error = True
                    break
                if stream == 'stdout':
                    self.stdout.extend(chunk)
        self.exit_code = self.handle.poll()
        if self.exit_code is not None and (type(self.exit_code) is not int
                                          or not -(2**31) <= self.exit_code < 2**31):
            self.exit_code = None
            self.capture_error = True
        self.observation = self.handle.observe()
        self.drained = _owned_drain(self.observation, self.launch['launch_token'])
        if self.clock() >= deadline or self.capture_error:
            self.timed_out = self.clock() >= deadline and not self.capture_error
            self.handle.stop(deadline)
            self.exit_code = self.handle.poll()
            self.observation = self.handle.observe()
            self.drained = _owned_drain(self.observation, self.launch['launch_token'])
            self.done = True
        elif self.exit_code is not None and self.drained and len(self.eof) == 2:
            self.done = True
        return True


def _oracle_hash(path, worktree):
    path = Path(path).resolve(strict=True)
    if path.is_relative_to(Path(worktree).resolve(strict=True)):
        raise ValueError('oracle is inside editable workspace')
    with open(path, 'rb') as source:
        return hashlib.sha256(source.read()).hexdigest()


class _OracleAttempt:
    def __init__(self, profile, worktree, deadline, factory, clock):
        self.profile, self.worktree, self.clock = profile, worktree, clock
        self.record = dict(test_id=profile['test_id'], status='notrun', exit_code=None,
                           oracle_sha256=profile['oracle_sha256'])
        self.capture = None
        self.done = False
        self.drained = True  # No launch has been attempted yet.
        if clock() >= deadline:
            self.done = True
            return
        try:
            if _oracle_hash(profile['oracle_path'], worktree) != profile['oracle_sha256']:
                raise ValueError('oracle pin mismatch')
        except (OSError, ValueError, TypeError):
            self.record['status'] = 'error'
            self.done = True
            return
        if factory is None:
            # A production kernel launcher is held pending independent K1 RED.
            # Missing executable capability cannot manufacture a test verdict.
            self.record['status'] = 'notrun'
            self.done = True
            return
        launch = dict(kind='oracle', launch_token=str(uuid.uuid4()),
                      argv=('/usr/bin/python3', '-I', profile['oracle_path'],
                            '--worktree', worktree, '--sandbox', 'bwrap'),
                      cwd=worktree, env={'LC_ALL': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'},
                      deadline=min(deadline, clock() + 60),
                      capture_limits={'total_bytes': 65536},
                      isolation={'sandbox': 'bwrap', 'network': False, 'host_write': False})
        self.drained = False
        try:
            handle = factory.spawn(launch)
        except OSError:
            self.record['status'] = 'unknown'
            self.done = True
            return
        self.capture = _ProcessCapture(handle, launch, clock, 65536)

    def step(self):
        if self.done:
            return False
        self.capture.step()
        if not self.capture.done:
            return True
        capture = self.capture
        self.drained = capture.drained
        self.record['exit_code'] = capture.exit_code
        status = 'error'
        if not capture.drained:
            status = 'unknown'
        elif capture.timed_out:
            status = 'timeout'
        elif not capture.capture_error and capture.observation.get('containment_verified') is True:
            try:
                if _oracle_hash(self.profile['oracle_path'], self.worktree) != self.profile['oracle_sha256']:
                    raise ValueError('oracle changed')
                lines = bytes(capture.stdout).decode('utf-8').strip().splitlines()
                if len(lines) != 1:
                    raise ValueError('oracle record count')
                report = json.loads(lines[0], object_pairs_hook=_native_object,
                                    parse_constant=_native_constant)
                total, failed = report.get('cases_total'), report.get('cases_failed')
                if (report.get('test_id') != self.profile['test_id']
                        or report.get('oracle_sha256_self') != self.profile['oracle_sha256']
                        or report.get('sandbox') != 'bwrap'
                        or type(total) is not int or total != self.profile.get('expected_cases', 413)
                        or type(failed) is not int or not 0 <= failed <= total):
                    raise ValueError('oracle evidence mismatch')
                if report.get('status') == 'pass' and failed == 0 and capture.exit_code == 0:
                    status = 'passed'
                elif report.get('status') == 'fail' and failed > 0 and capture.exit_code == 1:
                    status = 'failed'
            except (OSError, ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
                pass
        self.record['status'] = status
        self.done = True
        return True


def run_oracle(profile, worktree, deadline):
    """Derive the exact public test record from actual injected process evidence."""
    dependencies = _DEPENDENCIES.get()
    factory, clock = dependencies if dependencies is not None else (None, time.monotonic)
    attempt = _OracleAttempt(profile, worktree, deadline, factory, clock)
    while not attempt.done:
        attempt.step()
    return attempt.record


_PROFILE_KEYS = ('execution_profile_id', 'profile_revision', 'provider',
                 'requested_model', 'requested_effort', 'account_ref', 'workspace_ref',
                 'base_sha', 'executor_target', 'test_id', 'oracle_sha256', 'account_attestation')


def _private_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _legacy_result(stdout):
    """Keep the largest UTF-8 text prefix inside the actual v1 JSON budget."""
    text = stdout.decode('utf-8', errors='replace')
    result = dict(text=text, executor='codex')
    if len(_private_json(result).encode('utf-8')) <= 60000:
        return result
    result['output_truncated'] = True
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        result['text'] = text[:middle]
        if len(_private_json(result).encode('utf-8')) <= 60000:
            low = middle
        else:
            high = middle - 1
    result['text'] = text[:low]
    return result


class Runner:
    """Durable single-slot supervisor over the injected raw-process interface.

    This class does not implement the held production kernel launcher. Its
    factory is supplied by the owner, and synthetic observations are never a
    claim of real kernel containment or a live allocated account attestation.
    """
    def __init__(self, state_dir, profile_resolver, process_factory, clock):
        from _control_node_protocol import canonical_v2, decode_command_v2
        self._canonical, self._decode_command = canonical_v2, decode_command_v2
        self.resolver, self.factory, self.clock = profile_resolver, process_factory, clock
        directory = Path(state_dir)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
            raise ValueError('invalid private runner directory')
        self._lock = os.open(directory / 'owner.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        path = directory / 'runner.sqlite'
        if path.is_symlink():
            raise ValueError('invalid runner database')
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS tasks(
                admission_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE, wire BLOB NOT NULL, body TEXT NOT NULL,
                document TEXT NOT NULL, slot INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS outbox(
                position INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL UNIQUE, task_id TEXT NOT NULL,
                wire BLOB NOT NULL, acked INTEGER NOT NULL DEFAULT 0);
        ''')
        self._test_fault_hook = None
        self._mutex = threading.RLock()
        self._lock_depth = 0
        self._captures = {}
        self._oracles = {}

    @contextmanager
    def _transaction(self):
        with self._mutex:
            if self._lock_depth == 0:
                fcntl.flock(self._lock, fcntl.LOCK_EX)
            self._lock_depth += 1
            try:
                with self.db:
                    yield
            finally:
                self._lock_depth -= 1
                if self._lock_depth == 0:
                    fcntl.flock(self._lock, fcntl.LOCK_UN)

    def _task(self, task_id):
        row = self.db.execute('SELECT document FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        return json.loads(row['document']) if row else None

    def _save(self, task):
        receipt = task['receipt']
        self.db.execute('UPDATE tasks SET document=?,slot=? WHERE task_id=?',
                        (_private_json(task), int(receipt['slot_held']), receipt['task_id']))

    def private_receipt(self, task_id):
        task = self._task(task_id)
        return task['receipt'] if task else None

    def _fault(self, label, task):
        if self._test_fault_hook is not None:
            self._test_fault_hook(label, json.loads(_private_json(task['receipt'])))

    def _event(self, task, sequence, kind, result=None, reason=None):
        binding, receipt = task['binding'], task['receipt']
        task_id = receipt['task_id']
        if task['version'] == 2:
            message_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                'ai-control:node-event:v2:%s:%s:%s' % (task_id, binding['attempt_id'], sequence)))
            verification = receipt['session_verification']
            payload = dict(schema=2, sequence=sequence, binding=binding,
                           session_verification=verification,
                           observed_session_uuid=binding['requested_session_uuid'] if verification == 'verified' else None,
                           native_model=task.get('native_model'), effort_state='requested_unverified',
                           result=result, reason=reason)
            source = 'claude-alp-worktree-1'
        else:
            source = 'codex-ai-dev-1'
            message_id = uuid.uuid5(uuid.NAMESPACE_URL, source + ':' + task_id + ':' + kind).hex
            if kind == 'completed':
                payload = result
            elif kind == 'failed':
                legacy_reason = {'prepare_timeout': 'timeout', 'timeout': 'timeout',
                                 'output_limit': 'output_limit', 'executor_exit': 'executor_exit',
                                 'local_executor_error': 'local_executor_error'}.get(reason, 'local_executor_error')
                payload = {'reason': legacy_reason}
            elif kind == 'needs_attention':
                payload = {'reason': 'interrupted; outcome unknown; automatic retry disabled'}
            else:
                payload = {}
        value = dict(message_id=message_id, task_id=task_id, correlation_id=task_id,
                     source=source, target='control-web', kind=kind,
                     created_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'), payload=payload)
        wire = self._canonical(value)
        if len(wire) > 129024:
            raise ValueError('runner event exceeds wire budget')
        if task['version'] == 1 and kind in ('completed', 'failed', 'needs_attention'):
            # Validate with the receiving Store before sealing/releasing a
            # legacy terminal. A durable outbox must contain consumable bytes.
            from _control_node_tasks import NodeTaskStore
            NodeTaskStore._event(wire)
        self.db.execute('INSERT OR IGNORE INTO outbox(message_id,task_id,wire) VALUES(?,?,?)',
                        (message_id, task_id, wire))

    def submit(self, raw):
        from _control_node_protocol import validate_profile_snapshot_v2
        task_id = None
        try:
            if type(raw) is not bytes or len(raw) > 129024:
                raise ValueError()
            command = json.loads(raw.decode('utf-8'), object_pairs_hook=_native_object,
                                 parse_constant=_native_constant)
            task_id = command.get('task_id')
            if type(task_id) is not str or str(uuid.UUID(task_id)) != task_id:
                raise ValueError()
            version = 2 if command.get('payload', {}).get('schema') == 2 else 1
            if version == 2:
                command = self._decode_command(raw)
                binding = command['payload']['binding']
                profile_id = binding['execution_profile_id']
                prompt = command['payload']['request']['prompt']
            else:
                fields = {'message_id', 'task_id', 'correlation_id', 'source', 'target', 'kind', 'created_at', 'payload'}
                if (set(command) != fields or command['source'] != 'control-web'
                        or command['target'] != 'codex-ai-dev-1' or command['kind'] != 'submit'
                        or command['correlation_id'] != task_id or set(command['payload']) != {'prompt'}):
                    raise ValueError()
                for key in ('message_id', 'task_id', 'correlation_id', 'source', 'target'):
                    if (type(command[key]) is not str
                            or re.fullmatch(r'[A-Za-z0-9_-]{1,80}', command[key]) is None):
                        raise ValueError()
                stamp = datetime.fromisoformat(command['created_at'].replace('Z', '+00:00'))
                if stamp.tzinfo is None:
                    raise ValueError()
                prompt = command['payload']['prompt']
                if type(prompt) is not str or not 1 <= len(prompt.encode()) <= 32768 or '\0' in prompt:
                    raise ValueError()
                profile_id = 'codex-readonly-audit'
            with self._transaction():
                old = self.db.execute('SELECT body FROM tasks WHERE task_id=?', (task_id,)).fetchone()
                body = hashlib.sha256(raw).hexdigest()
                if old:
                    return dict(outcome='duplicate' if old['body'] == body else 'conflict', task_id=task_id)
                profile = json.loads(_private_json(self.resolver(profile_id)))
                if not Path(profile['cli_path']).is_absolute():
                    raise ValueError()
                if version == 2:
                    snapshot = validate_profile_snapshot_v2({key: profile[key] for key in _PROFILE_KEYS})
                    if snapshot['account_attestation']['status'] != 'verified':
                        return dict(outcome='profile_unverified', task_id=task_id)
                    if any(binding[key] != snapshot[key] for key in binding.keys() & snapshot.keys()):
                        return dict(outcome='profile_unverified', task_id=task_id)
                else:
                    binding = dict(task_id=task_id, attempt_id=str(uuid.uuid4()),
                                   requested_session_uuid=str(uuid.uuid4()), execution_profile_id=profile_id,
                                   profile_revision=profile.get('profile_revision', 0),
                                   account_ref=profile.get('account_ref'), workspace_ref=profile.get('workspace_ref'),
                                   base_sha=profile.get('base_sha'))
                count = self.db.execute('SELECT count(*) FROM tasks').fetchone()[0]
                outstanding = sum(not json.loads(row[0])['receipt']['result_committed']
                                  or json.loads(row[0])['receipt']['slot_held']
                                  for row in self.db.execute('SELECT document FROM tasks'))
                if count >= 1000 or outstanding >= 32:
                    return dict(outcome='capacity', task_id=task_id)
                receipt = {key: binding[key] for key in ('task_id', 'attempt_id', 'execution_profile_id',
                           'profile_revision', 'account_ref', 'workspace_ref', 'base_sha', 'requested_session_uuid')}
                receipt.update(state='waiting_slot', session_verification='pending', claim_count=0,
                               worktree_count=0, spawn_count=0, counts_known=True, slot_held=False,
                               launch_intent_committed=False, process=None, drain_confirmed=None, result_committed=False)
                task = dict(version=version, binding=binding, profile=profile, receipt=receipt, prompt=prompt)
                self.db.execute('INSERT INTO tasks(task_id,wire,body,document) VALUES(?,?,?,?)',
                                (task_id, raw, body, _private_json(task)))
                self._event(task, 0, 'queued' if version == 2 else 'accepted')
            self._fault('after_admission_commit', task)
            return dict(outcome='admitted', task_id=task_id)
        except (ValueError, TypeError, KeyError, UnicodeError, AttributeError, RecursionError):
            return dict(outcome='invalid', task_id=task_id)

    def drain_events(self):
        return [bytes(row[0]) for row in self.db.execute('SELECT wire FROM outbox WHERE acked=0 ORDER BY position')]

    def _test_puback(self, message_id, sequence=1):
        if type(sequence) is not int or not 1 <= sequence <= 2**63 - 1:
            raise ValueError('invalid publication acknowledgement')
        row = self.db.execute('SELECT task_id FROM outbox WHERE message_id=? AND acked=0', (message_id,)).fetchone()
        if row:
            self._fault('before_puback', self._task(row['task_id']))
            with self._transaction():
                self.db.execute('UPDATE outbox SET acked=1 WHERE message_id=?', (message_id,))

    def recover(self):
        with self._transaction():
            for row in self.db.execute('SELECT task_id FROM tasks WHERE slot=1').fetchall():
                task = self._task(row['task_id'])
                if not task['receipt']['result_committed']:
                    task['receipt'].update(state='held_unknown', drain_confirmed=False)
                    if task['receipt']['launch_intent_committed'] and not task['receipt']['spawn_count']:
                        task['receipt'].update(counts_known=False, spawn_count=None)
                    self._save(task)

    def _hold(self, task, drained=False):
        task['receipt'].update(state='held_unknown', slot_held=True, drain_confirmed=drained)
        with self._transaction():
            self._save(task)

    def _seal(self, task, kind, result=None, reason=None):
        receipt = task['receipt']
        receipt.update(state=kind, result_committed=True)
        with self._transaction():
            self._event(task, 3, kind, result, reason)
            self._save(task)
        self._fault('after_result_commit', task)
        # Release follows the durable terminal/result/outbox transaction.
        receipt['slot_held'] = False
        with self._transaction():
            self._save(task)

    def _result(self, task, test):
        from _control_node_protocol import validate_result_v2
        diff = canonical_patch(task['worktree'], task['binding']['base_sha'])
        original = task.get('summary', '')
        text = original.encode('utf-8')[:8192].decode('utf-8', errors='ignore')
        result = dict(schema=2, executor='claude', text=text, text_truncated=text != original,
                      tests=[test], diff=diff, usage=None, usage_state='unknown')
        if len(self._canonical(result)) > 60000:
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                result.update(text=text[:middle], text_truncated=True)
                if len(self._canonical(result)) <= 60000:
                    low = middle
                else:
                    high = middle - 1
            result.update(text=text[:low], text_truncated=True)
        return validate_result_v2(result)

    def step(self):
        # Keep the owner lock through launch, not only through database writes.
        with self._transaction():
            return self._step()

    def _step(self):
        # Selection and claim are serialized across owner instances.
        with self._transaction():
            row = self.db.execute('SELECT task_id FROM tasks WHERE slot=1 ORDER BY admission_seq LIMIT 1').fetchone()
            if row is None:
                row = self.db.execute('SELECT task_id FROM tasks ORDER BY admission_seq').fetchall()
                task = next((self._task(r[0]) for r in row if self._task(r[0])['receipt']['state'] == 'waiting_slot'), None)
                if task is None:
                    return False
                task['receipt'].update(state='claimed', claim_count=1, slot_held=True)
                task.update(overall_deadline=self.clock() + 1080, prepare_deadline=self.clock() + 30)
                self._event(task, 1, 'accepted')
                self._save(task)
                claimed = True
            else:
                task = self._task(row['task_id'])
                claimed = False
        if claimed:
            self._fault('after_claim_commit', task)
            return True
        receipt, profile = task['receipt'], task['profile']
        task_id, state = receipt['task_id'], receipt['state']
        if state == 'held_unknown':
            return False
        if receipt['result_committed']:
            receipt['slot_held'] = False
            with self._transaction():
                self._save(task)
            return True
        if state in ('claimed', 'prepared', 'launch_intent'):
            if self.clock() >= min(task['prepare_deadline'], task['overall_deadline']):
                if receipt['launch_intent_committed']:
                    receipt.update(counts_known=False, spawn_count=None)
                    self._hold(task)
                    return True
                receipt.update(drain_confirmed=True)
                self._seal(task, 'failed', reason='prepare_timeout')
                return True
            if state == 'claimed':
                root = Path(profile['worktree_root'])
                root.mkdir(mode=0o700, parents=True, exist_ok=True)
                worktree = root / task['binding'].get('worktree_ref', receipt['attempt_id'])
                _git(Path(profile['repo_path']), ('worktree', 'add', '--detach', str(worktree), receipt['base_sha']), _environment())
                task['worktree'] = str(worktree)
                receipt.update(state='prepared', worktree_count=1)
                with self._transaction():
                    self._save(task)
                self._fault('after_worktree_create', task)
                return True
            if state == 'prepared':
                receipt.update(state='launch_intent', launch_intent_committed=True)
                task['launch_token'] = str(uuid.uuid4())
                with self._transaction():
                    self._save(task)
                self._fault('after_launch_intent_commit', task)
                return True
            kind = 'claude' if task['version'] == 2 else 'codex'
            argv = ((profile['cli_path'], '-p', '--output-format', 'stream-json',
                     '--verbose', '--session-id', receipt['requested_session_uuid'],
                     '--model', task['binding']['requested_model'], '--effort', task['binding']['requested_effort'],
                     '--', task['prompt']) if kind == 'claude' else
                    (profile['cli_path'], 'exec', '-s', 'read-only', '--', task['prompt']))
            launch = dict(kind=kind, launch_token=task['launch_token'], argv=argv,
                          cwd=task['worktree'], env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                          deadline=min(task['overall_deadline'], self.clock() + 900),
                          capture_limits={'total_bytes': 4194304},
                          isolation={'execution_profile_id': receipt['execution_profile_id']})
            try:
                handle = self.factory.spawn(launch)
            except OSError:
                receipt.update(counts_known=False, spawn_count=None)
                self._hold(task)
                return True
            capture = _ProcessCapture(handle, launch, self.clock, 4194304)
            self._captures[task_id] = capture
            receipt.update(state='cli', spawn_count=1, process=handle.observe(), drain_confirmed=False)
            with self._transaction():
                self._save(task)
            self._fault('after_spawn', task)
            return True
        if state == 'cli':
            capture = self._captures.get(task_id)
            if capture is None:
                self._hold(task)
                return True
            capture.step()
            receipt['process'] = capture.observation
            if not capture.done:
                with self._transaction():
                    self._save(task)
                return True
            if not capture.drained:
                self._hold(task)
                return True
            receipt['drain_confirmed'] = True
            if task['version'] == 1:
                self._seal(task, 'completed' if capture.exit_code == 0 else 'failed',
                           _legacy_result(bytes(capture.stdout))
                           if capture.exit_code == 0 else None,
                           None if capture.exit_code == 0 else 'executor_exit')
                return True
            native = decode_native_stream(bytes(capture.stdout).splitlines(keepends=True),
                                          receipt['requested_session_uuid'], task['binding']['requested_model'])
            receipt['session_verification'] = native['binding']
            task['native_model'] = native['model']
            if native['binding'] != 'verified':
                self._hold(task, drained=True)
                return True
            for line in bytes(capture.stdout).splitlines():
                record = json.loads(line)
                if record.get('type') == 'result' and type(record.get('result')) is str:
                    task['summary'] = record['result']
            if (not native['successful_turn'] or capture.exit_code != 0 or capture.capture_error
                    or capture.timed_out or capture.observation.get('containment_verified') is not True):
                self._seal(task, 'failed', reason='native_turn_failed')
                return True
            receipt['state'] = 'oracle_ready'
            with self._transaction():
                self._event(task, 2, 'running')
                self._save(task)
            return True
        if state == 'oracle_ready':
            oracle = _OracleAttempt(profile, task['worktree'], task['overall_deadline'], self.factory, self.clock)
            self._oracles[task_id] = oracle
            receipt['state'] = 'oracle'
            with self._transaction():
                self._save(task)
            return True
        if state == 'oracle':
            oracle = self._oracles.get(task_id)
            if oracle is None:
                self._hold(task)
                return True
            oracle.step()
            if not oracle.done:
                return True
            if not oracle.drained:
                self._hold(task)
                return True
            receipt['drain_confirmed'] = True
            result = self._result(task, oracle.record)
            kind = ('needs_attention' if result['diff']['patch_status'] not in ('ok', 'empty')
                    else 'completed' if oracle.record['status'] == 'passed' else 'failed')
            self._seal(task, kind, result)
            return True
        return False
