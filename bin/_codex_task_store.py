"""Private TASK operation registry and durable native effect fences."""
import fcntl
import importlib.machinery
import importlib.util
import json
import math
import os
import re
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from _codex_task_bridge import TaskBinding


class StoreError(Exception):
    pass


def require(value):
    if not value:
        raise StoreError('TASK operation store refused')


def plain(value):
    if type(value) is dict:
        require(all(type(k) is str for k in value))
        for v in value.values():
            plain(v)
    elif type(value) is list:
        for v in value:
            plain(v)
    else:
        require(value is None or type(value) in (str, bool, int) or
                (type(value) is float and math.isfinite(value)))


def clone(value):
    plain(value)
    return json.loads(json.dumps(value, allow_nan=False))


def canonical_uuid(value, version=None):
    require(type(value) is str)
    parsed = uuid.UUID(value)
    require(str(parsed) == value and (version is None or parsed.version == version))
    return value


def text(value, basename=False):
    require(type(value) is str and value == value.strip() and 0 < len(value.encode()) <= 256
            and not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in value))
    if basename:
        require(value not in ('.', '..') and '/' not in value and '\\' not in value)
    return value


def hex32(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{32}', value))
    return value


_loader = importlib.machinery.SourceFileLoader('_store_control_io',
    os.path.join(os.path.dirname(__file__), 'claude-agent-io'))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
_control_io = importlib.util.module_from_spec(_spec)
_loader.exec_module(_control_io)


class _Publication:
    def __init__(self, store, context, operation_id, deadline):
        self.store, self.context, self.operation_id, self.deadline = store, context, operation_id, deadline
        self.thread = threading.get_ident()
        self.live = True
        self.used = False

    def activate(self, thread_id, turn_id):
        try:
            require(self.live and not self.used and threading.get_ident() == self.thread)
            self.used = True
            text(thread_id)
            text(turn_id)
            s, ctx = self.store, self.context
            s._check(ctx, self.deadline)
            op = ctx['index']['operations'][self.operation_id]
            s._authority(ctx, op)
            require(op['status'] == 'prepared' and op['start_reserved'] and op['thread_id'] == thread_id)
            s._consistent(ctx)
            op.update(status='active', turn_id=turn_id)
            s._write_index(ctx, self.deadline)
            s._write_op(ctx, op, self.deadline)
            s._check(ctx, self.deadline)
            return clone(op)
        except Exception:
            raise StoreError('Operation publication refused') from None


class CodexTaskOperationStore:
    def __init__(self, agent_dir, *, state_root, clock=time.monotonic):
        self.agent_dir, self.state_root, self.clock = agent_dir, state_root, clock

    def _budget(self, deadline):
        require(type(deadline) in (int, float) and math.isfinite(deadline)
                and self.clock() < deadline)
        return deadline - self.clock()

    @staticmethod
    def _path(path):
        require(type(path) is str and os.path.isabs(path) and os.path.normpath(path) == path
                and os.path.realpath(path) == path)

    def _pin(self, path, pins, *, private=True, directory=True, spec=False):
        self._path(path)
        st = os.lstat(path)
        mode = stat.S_IMODE(st.st_mode)
        if directory:
            require(stat.S_ISDIR(st.st_mode))
            if private:
                require(st.st_uid == os.getuid() and mode == 0o700)
            else:
                require(st.st_uid in (0, os.getuid()) and
                        (not mode & 0o022 or (st.st_uid == 0 and mode & stat.S_ISVTX)))
        else:
            require(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and st.st_nlink == 1
                    and (not mode & 0o022 if spec else mode == 0o600))
        if directory:
            for i, (oldpath, oldfd, oldprivate, olddir, oldspec) in enumerate(pins):
                if olddir and oldpath == path:
                    opened = os.fstat(oldfd)
                    require((st.st_dev, st.st_ino) == (opened.st_dev, opened.st_ino))
                    pins[i] = (path, oldfd, private or oldprivate, True, False)
                    return oldfd
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if directory:
            flags |= os.O_DIRECTORY
        fd = os.open(path, flags)
        opened = os.fstat(fd)
        try:
            require((st.st_dev, st.st_ino) == (opened.st_dev, opened.st_ino))
        except Exception:
            os.close(fd)
            raise
        pins.append((path, fd, private, directory, spec))
        return fd

    def _ancestors(self, path, pins):
        self._path(path)
        current = '/'
        self._pin(current, pins, private=False)
        for part in path.strip('/').split('/'):
            current = os.path.join(current, part)
            self._pin(current, pins, private=False)

    def _check(self, ctx, deadline):
        self._budget(deadline)
        for path, fd, private, directory, spec in ctx['pins']:
            self._path(path)
            st, opened = os.lstat(path), os.fstat(fd)
            require((st.st_dev, st.st_ino) == (opened.st_dev, opened.st_ino))
            mode = stat.S_IMODE(st.st_mode)
            if directory:
                require(stat.S_ISDIR(st.st_mode))
                if private:
                    require(st.st_uid == os.getuid() and mode == 0o700)
                else:
                    require(st.st_uid in (0, os.getuid()) and
                            (not mode & 0o022 or (st.st_uid == 0 and mode & stat.S_ISVTX)))
            else:
                require(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and st.st_nlink == 1
                        and (not mode & 0o022 if spec else mode == 0o600))
        for path, expected in ctx.get('files', {}).items():
            self._path(path)
            info = os.lstat(path)
            require(self._stamp(info) == expected)
        self._budget(deadline)

    @staticmethod
    def _stamp(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _read(self, path, ctx, deadline):
        self._budget(deadline)
        fd = self._pin(path, ctx['pins'], directory=False)
        st = os.fstat(fd)
        require(st.st_size <= 1024 * 1024)
        raw = os.read(fd, 1024 * 1024 + 1)
        require(len(raw) <= 1024 * 1024)
        def pairs(items):
            value = {}
            for k, v in items:
                require(k not in value)
                value[k] = v
            return value
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False))
        plain(value)
        require(type(value) is dict)
        self._budget(deadline)
        require(self._stamp(os.fstat(fd)) == self._stamp(st)
                and self._stamp(os.lstat(path)) == self._stamp(st))
        ctx.setdefault('files', {})[path] = self._stamp(st)
        # Atomic writes replace data files; retain directory/lock pins, not obsolete data FDs.
        ctx['pins'].pop()
        os.close(fd)
        return value

    def _write(self, path, value, ctx, deadline):
        self._check(ctx, deadline)
        plain(value)
        payload = json.dumps(value, allow_nan=False, sort_keys=True).encode()
        require(len(payload) <= 1024 * 1024)
        if os.path.lexists(path):
            fd = self._pin(path, ctx['pins'], directory=False)
            ctx['pins'].pop()
            os.close(fd)
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.store-', dir=os.path.dirname(path))
            with os.fdopen(fd, 'wb') as out:
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
            self._check(ctx, deadline)
            os.replace(temporary, path)
            temporary = None
            ctx.setdefault('files', {})[path] = self._stamp(os.lstat(path))
            parent = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            self._check(ctx, deadline)
        finally:
            if temporary is not None:
                os.unlink(temporary)

    def _lock(self, path, ctx):
        fd = self._pin(path, ctx['pins'], directory=False)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _control(value):
        plain(value)
        require(not _control_io.validate_control(value))
        require(type(value.get('schema')) is int and value['schema'] == 1
                and type(value.get('seq')) is int and type(value.get('generation')) is int)
        hex32(value.get('incarnation'))
        require(type(value.get('mission_base')) is str
                and re.fullmatch('[0-9a-fA-F]{40}', value['mission_base']))

    def _spec(self, ctx, deadline):
        path = self.agent_dir + '/spec.yaml'
        fd = self._pin(path, ctx['pins'], directory=False, spec=True)
        st = os.fstat(fd)
        ctx.setdefault('files', {})[path] = self._stamp(st)
        require(st.st_size <= 1024 * 1024)
        result = subprocess.run(['yq', '-o=json', '-I=0', '.', path], capture_output=True,
                                timeout=self._budget(deadline))
        require(result.returncode == 0 and len(result.stdout) <= 1024 * 1024)
        def pairs(items):
            value = {}
            for k, v in items:
                require(k not in value)
                value[k] = v
            return value
        value = json.loads(result.stdout, object_pairs_hook=pairs)
        plain(value)
        require(type(value) is dict and all(value.get(k) == v for k, v in
                dict(engine='codex', type='event', runtime='drain', workspace='worktree').items()))
        self._path(value.get('project'))
        require(os.path.isdir(value['project']))
        self._check(ctx, deadline)

    @classmethod
    def initialize(cls, staging_agent_dir, final_agent_dir, state_id, *, state_root,
                   clock=time.monotonic, deadline):
        s = cls(staging_agent_dir, state_root=state_root, clock=clock)
        ctx = {'pins': []}
        try:
            s._budget(deadline)
            canonical_uuid(state_id)
            s._path(final_agent_dir)
            require(not os.path.lexists(final_agent_dir))
            require(os.path.dirname(final_agent_dir) == os.path.dirname(staging_agent_dir)
                    and os.path.basename(os.path.dirname(final_agent_dir)) == 'agents'
                    and re.fullmatch('[a-z][a-z0-9-]{0,30}[a-z0-9]', os.path.basename(final_agent_dir)))
            s._layout(ctx, staging_agent_dir)
            for path in (staging_agent_dir + '/.lock', staging_agent_dir + '/inbox/.inbox.lock'):
                s._pin(path, ctx['pins'], directory=False)
            require(os.path.commonpath((state_root, staging_agent_dir)) not in (state_root, staging_agent_dir))
            require(os.path.commonpath((state_root, final_agent_dir)) not in (state_root, final_agent_dir))
            s._ancestors(state_root, ctx['pins'])
            s._pin(state_root, ctx['pins'])
            control = s._read(staging_agent_dir + '/control.json', ctx, deadline)
            s._control(control)
            require('codex_state_id' not in control and control['generation'] == 0
                    and control['desired'] == 'paused' and control['lease']['state'] == 'none'
                    and control['lease'].get('start_attempt_id') is None)
            for entry in os.listdir(staging_agent_dir + '/inbox'):
                if entry == '.inbox.lock':
                    continue
                directory = staging_agent_dir + '/inbox/' + entry
                s._pin(directory, ctx['pins'])
                require(not os.listdir(directory))
            s._spec(ctx, deadline)
            target = os.path.join(state_root, state_id)
            os.mkdir(target, 0o700)
            s._pin(target, ctx['pins'])
            lock = os.open(target + '/store.lock', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fsync(lock)
            os.close(lock)
            s._write(target + '/index.json', dict(schema=1, state_id=state_id,
                agent_dir=final_agent_dir, task_incarnation=control['incarnation'], operations={}), ctx, deadline)
            for path in (target, state_root):
                fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            s._check(ctx, deadline)
            return state_id
        except Exception:
            raise StoreError('Operation registry initialization refused') from None
        finally:
            for _, fd, *_ in reversed(ctx['pins']):
                os.close(fd)

    def _layout(self, ctx, agent):
        self._ancestors(os.path.dirname(agent), ctx['pins'])
        require(os.path.basename(os.path.dirname(agent)) == 'agents')
        for path in (agent, agent + '/inbox', agent + '/inbox/inflight'):
            self._pin(path, ctx['pins'])

    @contextmanager
    def _context(self, deadline, *, locked=False):
        ctx = {'pins': [], 'envelopes': {}}
        try:
            self._budget(deadline)
            self._layout(ctx, self.agent_dir)
            self._ancestors(self.state_root, ctx['pins'])
            self._pin(self.state_root, ctx['pins'])
            require(os.path.commonpath((self.agent_dir, self.state_root)) not in
                    (self.agent_dir, self.state_root))
            if not locked:
                self._lock(self.agent_dir + '/.lock', ctx)
                self._lock(self.agent_dir + '/inbox/.inbox.lock', ctx)
            else:
                self._pin(self.agent_dir + '/.lock', ctx['pins'], directory=False)
                self._pin(self.agent_dir + '/inbox/.inbox.lock', ctx['pins'], directory=False)
            control = self._read(self.agent_dir + '/control.json', ctx, deadline)
            self._control(control)
            state_id = canonical_uuid(control.get('codex_state_id'))
            ctx['control'] = control
            ctx['dir'] = os.path.join(self.state_root, state_id)
            self._pin(ctx['dir'], ctx['pins'])
            self._lock(ctx['dir'] + '/store.lock', ctx)
            self._spec(ctx, deadline)
            index = self._read(ctx['dir'] + '/index.json', ctx, deadline)
            self._validate_index(index, control, state_id, ctx, deadline)
            ctx['index'] = index
            self._check(ctx, deadline)
            yield ctx
            self._check(ctx, deadline)
        except Exception:
            raise StoreError('TASK operation store refused') from None
        finally:
            for _, fd, *_ in reversed(ctx['pins']):
                os.close(fd)

    def _validate_index(self, index, control, state_id, ctx, deadline):
        require(set(index) == {'schema', 'state_id', 'agent_dir', 'task_incarnation', 'operations'})
        require(type(index['schema']) is int and index['schema'] == 1 and index['state_id'] == state_id
                and index['agent_dir'] == self.agent_dir and index['task_incarnation'] == control['incarnation'])
        require(type(index['operations']) is dict and len(index['operations']) <= 256)
        events = set()
        for opid, op in index['operations'].items():
            canonical_uuid(opid)
            require(type(op) is dict and set(op) == {'schema', 'operation_id', 'task_incarnation',
                'generation', 'attempt_id', 'event_key', 'status', 'thread_id', 'turn_id',
                'start_reserved', 'launch_reserved', 'host_state_dir', 'drain_evidence', 'terminal_evidence'})
            require(type(op['schema']) is int and op['schema'] == 1 and op['operation_id'] == opid
                    and op['task_incarnation'] == index['task_incarnation']
                    and type(op['generation']) is int and op['generation'] >= 1
                    and op['status'] in ('prepared', 'active', 'revoked', 'finished')
                    and type(op['launch_reserved']) is bool and type(op['start_reserved']) is bool)
            text(op['attempt_id'], True)
            text(op['event_key'], True)
            require(op['event_key'] not in events)
            events.add(op['event_key'])
            for key in ('thread_id', 'turn_id'):
                if op[key] is not None:
                    text(op[key])
            require(op['turn_id'] is None or op['thread_id'] is not None)
            if op['status'] in ('active', 'finished'):
                require(op['start_reserved'] and op['thread_id'] is not None and op['turn_id'] is not None)
            expected = ctx['dir'] + '/operations/' + opid + '/host'
            require(op['host_state_dir'] == expected)
            for evidence in ('drain_evidence', 'terminal_evidence'):
                if op[evidence] is not None:
                    plain(op[evidence])
                    require(type(op[evidence]) is dict and len(json.dumps(op[evidence]).encode()) <= 65536)
            if op['drain_evidence'] is not None:
                self._drain_receipt(ctx, op, op['drain_evidence'], deadline)
            terminal = op['terminal_evidence']
            if terminal is not None:
                require(set(terminal) == {'operation_id', 'task_incarnation', 'thread_id',
                    'turn_id', 'terminal', 'terminal_proven', 'quiescent'})
                require(all(terminal[k] == op[k] for k in
                    ('operation_id', 'task_incarnation', 'thread_id', 'turn_id'))
                    and terminal['terminal'] in ('completed', 'failed', 'interrupted')
                    and terminal['terminal_proven'] is True and terminal['quiescent'] is True
                    and op['drain_evidence'] is not None)
            require(op['status'] != 'finished' or terminal is not None)
            self._budget(deadline)

    def _envelope(self, ctx, op, deadline):
        event = op['event_key']
        if event not in ctx['envelopes']:
            path = self.agent_dir + '/inbox/inflight/' + event + '.json'
            if not os.path.lexists(path):
                require(op['status'] in ('finished', 'revoked'))
                self._drain_gate(ctx, op, deadline)
                self._pin(self.agent_dir + '/inbox/done', ctx['pins'])
                path = self.agent_dir + '/inbox/done/' + event + '.json'
                value = self._read(path, ctx, deadline)
                require(value.get('key') == event and type(value.get('meta')) is dict
                        and value['meta'].get('codex_operation') == op)
                history = value['meta'].get('history')
                require(type(history) is list and history and type(history[-1]) is dict)
                outcome = history[-1].get('outcome')
                require(type(outcome) is str and outcome in ('ok', 'asked', 'cancelled'))
                require(op['status'] != 'revoked' or outcome == 'cancelled'
                        or op['terminal_evidence'] is not None)
            else:
                value = self._read(path, ctx, deadline)
                require(value.get('key') == event and type(value.get('meta')) is dict)
            ctx.setdefault('envelope_paths', {})[event] = path
            ctx['envelopes'][event] = value
        return ctx['envelopes'][event]

    def _consistent(self, ctx):
        for op in ctx['index']['operations'].values():
            env = ctx['envelopes'].get(op['event_key'])
            require(env is not None and env['meta'].get('codex_operation') == op)

    def _load_envelopes(self, ctx, deadline):
        for op in ctx['index']['operations'].values():
            self._envelope(ctx, op, deadline)

    def _authority(self, ctx, op):
        control = ctx['control']
        require(control['desired'] == 'running' and control.get('hold') is None
                and control['generation'] == op['generation']
                and control['lease']['state'] == 'active'
                and control['lease'].get('start_attempt_id') == op['attempt_id']
                and control['acceptance']['status'] in ('pending', 'revise'))

    def _operation(self, ctx, operation_id):
        canonical_uuid(operation_id)
        require(operation_id in ctx['index']['operations'])
        return ctx['index']['operations'][operation_id]

    def _write_index(self, ctx, deadline):
        self._write(ctx['dir'] + '/index.json', ctx['index'], ctx, deadline)

    def _write_op(self, ctx, op, deadline):
        env = self._envelope(ctx, op, deadline)
        require(ctx['envelope_paths'][op['event_key']] ==
                self.agent_dir + '/inbox/inflight/' + op['event_key'] + '.json')
        env['meta']['codex_operation'] = clone(op)
        self._write(self.agent_dir + '/inbox/inflight/' + op['event_key'] + '.json', env, ctx, deadline)

    def prepare(self, event_key, generation, attempt_id, *, deadline):
        try:
            text(event_key, True)
            text(attempt_id, True)
            require(type(generation) is int and generation >= 1)
            with self._context(deadline) as ctx:
                self._load_envelopes(ctx, deadline)
                self._consistent(ctx)
                operations = ctx['index']['operations']
                require(len(operations) < 256 and not any(op['event_key'] == event_key
                        for op in operations.values()))
                for old in operations.values():
                    if (old['generation'], old['attempt_id']) != (generation, attempt_id):
                        self._drain_gate(ctx, old, deadline)
                    require(not (old['start_reserved'] and old['status'] == 'prepared'))
                opid = str(uuid.uuid4())
                require(opid not in operations)
                op = dict(schema=1, operation_id=opid, task_incarnation=ctx['index']['task_incarnation'],
                    generation=generation, attempt_id=attempt_id, event_key=event_key, status='prepared',
                    thread_id=None, turn_id=None, start_reserved=False, launch_reserved=False,
                    host_state_dir=ctx['dir'] + '/operations/' + opid + '/host',
                    drain_evidence=None, terminal_evidence=None)
                self._authority(ctx, op)
                env = self._envelope(ctx, op, deadline)
                require('codex_operation' not in env['meta'])
                for directory in (ctx['dir'] + '/operations', ctx['dir'] + '/operations/' + opid,
                                  op['host_state_dir']):
                    if not os.path.lexists(directory):
                        os.mkdir(directory, 0o700)
                    self._pin(directory, ctx['pins'])
                    parent_fd = os.open(os.path.dirname(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(parent_fd)
                    finally:
                        os.close(parent_fd)
                operations[opid] = op
                self._write_index(ctx, deadline)
                self._write_op(ctx, op, deadline)
                return clone(op)
        except Exception:
            raise StoreError('Operation preparation refused') from None

    def record_thread(self, operation_id, thread_id, *, deadline):
        try:
            text(thread_id)
            with self._context(deadline) as ctx:
                op = self._operation(ctx, operation_id)
                self._authority(ctx, op)
                require(op['status'] == 'prepared' and not op['start_reserved']
                        and op['thread_id'] in (None, thread_id))
                env = self._envelope(ctx, op, deadline)['meta'].get('codex_operation')
                old = clone(op)
                old['thread_id'] = None
                require(env == op or (op['thread_id'] == thread_id and env == old))
                op['thread_id'] = thread_id
                self._write_index(ctx, deadline)
                self._write_op(ctx, op, deadline)
                return clone(op)
        except Exception:
            raise StoreError('Thread publication refused') from None

    @contextmanager
    def _reservation(self, operation_id, deadline, field):
        handle = None
        try:
            with self._context(deadline) as ctx:
                self._load_envelopes(ctx, deadline)
                self._consistent(ctx)
                op = self._operation(ctx, operation_id)
                self._authority(ctx, op)
                require(op['status'] == 'prepared' and not op[field])
                if field == 'start_reserved':
                    require(op['thread_id'] is not None)
                else:
                    require(not op['start_reserved'])
                op[field] = True
                self._write_index(ctx, deadline)
                self._write_op(ctx, op, deadline)
                self._check(ctx, deadline)
                if field == 'start_reserved':
                    handle = _Publication(self, ctx, operation_id, deadline)
                    yield handle
                else:
                    yield True
        except Exception:
            raise StoreError('Native effect reservation refused') from None
        finally:
            if handle is not None:
                handle.live = False

    def launch_guard(self, operation_id, *, deadline):
        return self._reservation(operation_id, deadline, 'launch_reserved')

    def reserve_start(self, operation_id, *, deadline):
        return self._reservation(operation_id, deadline, 'start_reserved')

    def revoke(self, *, deadline):
        with self._context(deadline) as ctx:
            self._load_envelopes(ctx, deadline)
            result = []
            for op in ctx['index']['operations'].values():
                envop = self._envelope(ctx, op, deadline)['meta'].get('codex_operation')
                if envop is not None:
                    require(type(envop) is dict and all(envop.get(k) == op[k] for k in
                            ('schema', 'operation_id', 'task_incarnation', 'generation', 'attempt_id', 'event_key', 'host_state_dir')))
                require(envop is None or envop.get('status') != 'finished' or op['status'] == 'finished')
                if op['status'] not in ('finished', 'revoked') or envop != op:
                    require(op['status'] != 'finished')
                    op['status'] = 'revoked'
                    self._write_op(ctx, op, deadline)
                    self._write_index(ctx, deadline)
                if op['drain_evidence'] is None:
                    result.append(clone(op))
            return result

    @contextmanager
    def revoked_guard(self, operation_id, task_incarnation, *, deadline):
        with self._context(deadline) as ctx:
            canonical_uuid(task_incarnation)
            require(task_incarnation == str(uuid.UUID(hex=ctx['index']['task_incarnation'])))
            op = self._operation(ctx, operation_id)
            require(op['status'] == 'revoked')
            require(self._envelope(ctx, op, deadline)['meta'].get('codex_operation') == op)
            yield True

    @contextmanager
    def guard_locked(self, binding, operation_id, *, deadline):
        with self._context(deadline, locked=True) as ctx:
            require(type(binding) is TaskBinding)
            for field in ('task_incarnation', 'event_key', 'agent_dir', 'thread_id', 'turn_id'):
                require(type(getattr(binding, field)) is str)
            op = self._operation(ctx, operation_id)
            self._authority(ctx, op)
            require(op['status'] == 'active' and binding.agent_dir == self.agent_dir
                    and binding.task_incarnation == op['task_incarnation']
                    and binding.event_key == op['event_key'] and binding.thread_id == op['thread_id']
                    and binding.turn_id == op['turn_id'])
            require(self._envelope(ctx, op, deadline)['meta'].get('codex_operation') == op)
            yield True

    def _journal(self, ctx, op, deadline):
        host = op['host_state_dir']
        for path in (ctx['dir'] + '/operations', os.path.dirname(host), host):
            self._pin(path, ctx['pins'])
        journal = self._read(host + '/journal.json', ctx, deadline)
        require(set(journal) == {'schema', 'task_incarnation', 'cwd', 'executable', 'unit',
                                'token', 'socket', 'phase', 'invocation_id', 'socket_identity'})
        require(type(journal['schema']) is int and journal['schema'] == 1
                and journal['task_incarnation'] == str(uuid.UUID(hex=op['task_incarnation']))
                and journal['cwd'] == self.agent_dir + '/work'
                and journal['socket'] == host + '/server.sock' and journal['phase'] == 'stopped')
        canonical_uuid(journal['token'], 4)
        unit = journal['unit']
        require(type(unit) is str and unit.startswith('cctask-') and unit.endswith('.service'))
        canonical_uuid(unit[7:-8], 4)
        hex32(journal['invocation_id'])
        self._path(journal['executable'])
        require(stat.S_ISREG(os.lstat(journal['executable']).st_mode))
        identity = journal['socket_identity']
        def inode(v):
            require(type(v) is list and len(v) == 2 and all(type(x) is int and x >= 0 for x in v))
        if identity is not None:
            if type(identity) is list:
                inode(identity)
            else:
                require(type(identity) is dict and set(identity) == {'link', 'target_path', 'target'})
                inode(identity['link'])
                inode(identity['target'])
                self._path(identity['target_path'])
        return journal

    def _drain_receipt(self, ctx, op, evidence, deadline):
        plain(evidence)
        require(type(evidence) is dict and set(evidence) == {'operation_id', 'task_incarnation',
                'host_state_dir', 'phase', 'unit', 'token', 'invocation_id', 'drained'})
        require(evidence['operation_id'] == op['operation_id'] and evidence['task_incarnation'] == op['task_incarnation']
                and evidence['host_state_dir'] == op['host_state_dir'] and evidence['phase'] == 'stopped'
                and evidence['drained'] is True)
        journal = self._journal(ctx, op, deadline)
        require(all(evidence[k] == journal[k] for k in ('unit', 'token', 'invocation_id')))

    def record_drained(self, operation_id, evidence, *, deadline):
        try:
            evidence = clone(evidence)
            with self._context(deadline) as ctx:
                op = self._operation(ctx, operation_id)
                self._drain_receipt(ctx, op, evidence, deadline)
                envop = self._envelope(ctx, op, deadline)['meta'].get('codex_operation')
                require(op['drain_evidence'] in (None, evidence))
                if op['drain_evidence'] == evidence:
                    if envop != op:
                        previous = clone(op)
                        previous['drain_evidence'] = None
                        require(envop == previous)
                        self._write_op(ctx, op, deadline)
                    return clone(op)
                require(envop == op)
                op['drain_evidence'] = evidence
                # Drain receipt changes no callback authority; keep envelope projection exact.
                self._write_index(ctx, deadline)
                self._write_op(ctx, op, deadline)
                return clone(op)
        except Exception:
            raise StoreError('Owned host drain receipt refused') from None

    def _drain_gate(self, ctx, op, deadline):
        host = op['host_state_dir']
        for path in (ctx['dir'] + '/operations', os.path.dirname(host), host):
            self._pin(path, ctx['pins'])
        if op['drain_evidence'] is not None:
            self._drain_receipt(ctx, op, op['drain_evidence'], deadline)
        else:
            require(op['status'] in ('prepared', 'revoked') and not op['launch_reserved']
                    and not op['start_reserved'] and not os.path.lexists(op['host_state_dir'] + '/journal.json'))

    def require_drained(self, *, deadline):
        with self._context(deadline) as ctx:
            self._load_envelopes(ctx, deadline)
            self._consistent(ctx)
            for op in ctx['index']['operations'].values():
                self._drain_gate(ctx, op, deadline)
            return True

    def finish(self, operation_id, evidence, *, deadline):
        try:
            evidence = clone(evidence)
            with self._context(deadline) as ctx:
                op = self._operation(ctx, operation_id)
                require(type(evidence) is dict and set(evidence) == {'operation_id', 'task_incarnation',
                    'thread_id', 'turn_id', 'terminal', 'terminal_proven', 'quiescent'})
                require(all(evidence[k] == op[k] for k in ('operation_id', 'task_incarnation', 'thread_id', 'turn_id'))
                        and op['thread_id'] is not None and op['turn_id'] is not None
                        and evidence['terminal'] in ('completed', 'failed', 'interrupted')
                        and evidence['terminal_proven'] is True and evidence['quiescent'] is True
                        and op['drain_evidence'] is not None)
                self._drain_gate(ctx, op, deadline)
                require(op['terminal_evidence'] in (None, evidence))
                envop = self._envelope(ctx, op, deadline)['meta'].get('codex_operation')
                target = clone(op)
                target.update(status='finished', terminal_evidence=evidence)
                require(envop == op or envop == target)
                require(op['status'] in ('active', 'revoked', 'finished'))
                if op == target and envop == target:
                    return clone(op)
                self._write_op(ctx, target, deadline)
                ctx['index']['operations'][operation_id] = target
                self._write_index(ctx, deadline)
                return clone(target)
        except Exception:
            raise StoreError('Operation finish refused') from None

    def snapshot(self, *, deadline):
        with self._context(deadline) as ctx:
            partial = False
            for op in ctx['index']['operations'].values():
                env = self._envelope(ctx, op, deadline)
                partial |= env['meta'].get('codex_operation') != op
            result = clone(ctx['index'])
            result['reconciliation_required'] = bool(partial)
            return result
