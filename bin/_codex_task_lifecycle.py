"""Offline-injectable native Codex turn evidence; never authorizes cleanup.

The caller must exclusively own a pre-existing materialized task thread.
A durable uncertain intent forbids retry even when no native turn is found.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Protocol
from uuid import UUID


class LifecycleError(Exception):
    """Safe local lifecycle diagnostic."""


class LifecycleConflict(LifecycleError):
    pass


class JournalError(LifecycleError):
    pass


class ProtocolError(LifecycleError):
    pass


class _DeadlineError(LifecycleError):
    pass


@dataclass(frozen=True)
class TaskThread:
    task_incarnation: str
    thread_id: str
    cwd: str


@dataclass(frozen=True)
class LifecycleSnapshot:
    operation_id: str
    phase: str
    thread_id: str
    turn_id: str | None
    reason: str | None
    model: str | None
    reasoning_effort: str | None
    final_text: str | None
    terminal_proven: bool


class NativeTransport(Protocol):
    def call(self, method: str, params: dict, *, deadline: float) -> dict: ...
    def receive(self, *, deadline: float) -> dict: ...


TERMINAL = {'completed', 'failed', 'interrupted'}
PHASES = TERMINAL | {'prepared', 'uncertain', 'running', 'waiting_approval', 'stopping', 'unknown'}
APPROVALS = {'item/commandExecution/requestApproval', 'item/fileChange/requestApproval',
             'item/permissions/requestApproval'}


def _uuid(value, *, operation=False):
    try:
        parsed = UUID(value) if isinstance(value, str) else None
        if parsed is None or str(parsed) != value or (operation and parsed.version != 4):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise LifecycleError('Invalid operation UUID' if operation else 'Invalid thread UUID') from None
    return value


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class CodexTaskLifecycle:
    def __init__(self, journal_dir: Path, thread: TaskThread,
                 transport: NativeTransport, *, clock=time.monotonic):
        if not isinstance(thread, TaskThread):
            raise LifecycleError('Invalid task identity')
        _uuid(thread.thread_id)
        if not isinstance(thread.task_incarnation, str) or not thread.task_incarnation:
            raise LifecycleError('Invalid task incarnation')
        if (not isinstance(thread.cwd, str) or not os.path.isabs(thread.cwd)
                or os.path.realpath(thread.cwd) != thread.cwd or not os.path.isdir(thread.cwd)):
            raise LifecycleError('Invalid canonical task directory')
        self.thread = thread
        self.directory = Path(os.path.abspath(journal_dir))
        self.transport = transport
        self.clock = clock
        self.identity = {'engine': 'codex', 'task_incarnation': thread.task_incarnation,
                         'thread_id': thread.thread_id, 'cwd': thread.cwd}
        self._safe_directory()

    def _safe_directory(self):
        # Check all components, including absent directories before mkdir.
        for path in (self.directory, *self.directory.parents):
            if path.is_symlink():
                raise JournalError('Journal path contains a symlink')
        try:
            if os.path.commonpath((str(self.directory), self.thread.cwd)) == self.thread.cwd:
                raise JournalError('Journal must be outside the task directory')
            if self.directory.exists():
                mode = self.directory.stat()
                if not stat.S_ISDIR(mode.st_mode) or mode.st_uid != os.getuid() or mode.st_mode & 0o022:
                    raise JournalError('Unsafe journal directory')
        except OSError:
            raise JournalError('Journal directory validation failed') from None

    def _deadline(self, deadline):
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise LifecycleError('Invalid deadline')
        if self.clock() >= deadline:
            raise _DeadlineError('Lifecycle deadline exceeded')

    def _make_directory(self):
        missing = []
        path = self.directory
        while not path.exists():
            missing.append(path)
            path = path.parent
        for path in reversed(missing):
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                if path.is_symlink() or not path.is_dir():
                    raise JournalError('Unsafe journal directory') from None
        # Persist ancestors on every acquisition. A previous failed fsync can
        # leave a newly created entry visible in cache, so existence is not
        # evidence that the entry is already durable.
        for parent in self.directory.parents:
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)

    @contextmanager
    def _locked(self, deadline):
        self._deadline(deadline)
        self._safe_directory()
        lock = None
        try:
            self._make_directory()
            self._safe_directory()
            lock = os.open(self.directory / '.lifecycle.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise JournalError('Unsafe journal lock')
            wall_deadline = time.monotonic() + max(0, deadline - self.clock())
            while True:
                self._deadline(deadline)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= wall_deadline:
                        raise LifecycleError('Journal lock deadline exceeded')
                    time.sleep(0.005)
        except OSError:
            if lock is not None:
                os.close(lock)
            raise JournalError('Journal lock failed') from None
        except BaseException:
            if lock is not None:
                os.close(lock)
            raise
        try:
            yield
        finally:
            os.close(lock)

    def _path(self, operation):
        return self.directory / (_uuid(operation, operation=True) + '.json')

    def _validate_record(self, record, operation):
        try:
            if (not isinstance(record, dict) or type(record.get('version')) is not int or record.get('version') != 1
                    or record.get('operation_id') != operation
                    or not isinstance(record.get('text'), str)
                    or record.get('text_hash') != _digest(record['text'])
                    or record.get('phase') not in PHASES
                    or not isinstance(record.get('baseline_ids'), list)
                    or any(not isinstance(x, str) or not x for x in record['baseline_ids'])
                    or len(set(record['baseline_ids'])) != len(record['baseline_ids'])
                    or type(record.get('interrupt_intent')) is not bool):
                raise ValueError
            required = {'version', 'operation_id', 'identity', 'text', 'text_hash', 'baseline_ids',
                        'phase', 'turn_id', 'interrupt_intent', 'terminal_receipt', 'reason',
                        'model', 'reasoning_effort', 'final_text'}
            if set(record) != required:
                raise ValueError
            identity = record.get('identity')
            if (not isinstance(identity, dict) or set(identity) != set(self.identity)
                    or identity.get('engine') != 'codex'
                    or any(not isinstance(value, str) or not value for value in identity.values())):
                raise ValueError
            if identity != self.identity:
                raise LifecycleConflict('Journal task identity differs')
            for key in ('turn_id', 'model', 'reasoning_effort', 'reason', 'final_text'):
                value = record.get(key)
                if value is not None and (not isinstance(value, str) or (key != 'final_text' and not value)):
                    raise ValueError
            if record.get('turn_id') in record['baseline_ids']:
                raise ValueError
            receipt = record.get('terminal_receipt')
            if receipt is not None:
                if (not isinstance(receipt, dict) or receipt.get('thread_id') != self.thread.thread_id
                        or receipt.get('turn_id') != record.get('turn_id')
                        or not receipt.get('turn_id') or receipt.get('status') not in TERMINAL):
                    raise ValueError
            if record['phase'] in {'prepared', 'uncertain'} and (
                    record['turn_id'] is not None or receipt is not None or record['interrupt_intent']):
                raise ValueError
            if record['phase'] in {'running', 'waiting_approval', 'stopping'} and receipt is not None:
                raise ValueError
            if record['phase'] in TERMINAL and (receipt is None or receipt['status'] != record['phase']):
                raise ValueError
            if record['phase'] in {'running', 'waiting_approval', 'stopping'} and not record.get('turn_id'):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise JournalError('Corrupt or incompatible lifecycle journal') from None
        return record

    def _load(self, operation):
        path = self._path(operation)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'r', encoding='utf-8') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                    raise JournalError('Unsafe journal record')
                record = json.load(source)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, UnicodeError):
            raise JournalError('Lifecycle journal read failed') from None
        return self._validate_record(record, operation)

    def _records(self):
        records = []
        for path in sorted(self.directory.glob('*.json')):
            try:
                _uuid(path.stem, operation=True)
            except LifecycleError:
                raise JournalError('Invalid lifecycle journal filename') from None
            record = self._load(path.stem)
            if record is None:
                raise JournalError('Lifecycle journal disappeared')
            records.append(record)
        return records

    def _write(self, record):
        self._validate_record(record, record['operation_id'])
        temp = None
        try:
            fd, temp = tempfile.mkstemp(prefix='.lifecycle-', dir=self.directory)
            with os.fdopen(fd, 'w', encoding='utf-8') as target:
                json.dump(record, target, ensure_ascii=False, sort_keys=True)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp, self._path(record['operation_id']))
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except (OSError, ValueError, UnicodeError):
            raise JournalError('Lifecycle journal write failed') from None
        finally:
            if temp is not None:
                try:
                    os.unlink(temp)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    @staticmethod
    def _snapshot(record):
        return LifecycleSnapshot(record['operation_id'], record['phase'], record['identity']['thread_id'],
                                 record.get('turn_id'), record.get('reason'), record.get('model'),
                                 record.get('reasoning_effort'), record.get('final_text'),
                                 record['phase'] in TERMINAL and record.get('terminal_receipt') is not None)

    def _required(self, operation):
        record = self._load(operation)
        if record is None:
            raise LifecycleError('Operation is not prepared')
        return record

    def _rpc(self, method, params, deadline):
        self._deadline(deadline)
        if method not in {'thread/read', 'turn/start', 'turn/interrupt'}:
            raise ProtocolError('Forbidden lifecycle RPC')
        try:
            result = self.transport.call(method, params, deadline=deadline)
        except Exception as error:
            raise ProtocolError('Native transport ' + type(error).__name__) from None
        self._deadline(deadline)
        if not isinstance(result, dict):
            raise ProtocolError('Invalid native response')
        return result

    def _read(self, deadline):
        result = self._rpc('thread/read', {'threadId': self.thread.thread_id, 'includeTurns': True}, deadline)
        thread = result.get('thread')
        if not isinstance(thread, dict):
            raise ProtocolError('Missing native thread')
        if (thread.get('id') != self.thread.thread_id or thread.get('cwd') != self.thread.cwd
                or not os.path.isdir(self.thread.cwd) or os.path.realpath(self.thread.cwd) != self.thread.cwd):
            raise ProtocolError('Native thread identity mismatch')
        if (thread.get('ephemeral') is not False or not isinstance(thread.get('path'), str)
                or not os.path.isabs(thread['path']) or thread.get('historyMode', 'legacy') != 'legacy'):
            raise ProtocolError('Native thread is not materialized legacy history')
        turns = thread.get('turns')
        if not isinstance(turns, list) or not turns:
            raise ProtocolError('Native history is missing')
        status = thread.get('status')
        if not isinstance(status, dict) or not isinstance(status.get('type'), str) or status.get('type') not in {'idle', 'active'}:
            raise ProtocolError('Unknown native thread status')
        ids = set()
        for turn in turns:
            self._validate_turn(turn)
            if turn['id'] in ids:
                raise ProtocolError('Duplicate native turn identity')
            ids.add(turn['id'])
        if not any(turn['status'] in TERMINAL for turn in turns):
            raise ProtocolError('Native materializing turn is missing')
        for key in ('model', 'reasoningEffort'):
            value = thread.get(key)
            if value is not None and not isinstance(value, str):
                raise ProtocolError('Invalid native configuration metadata')
        return thread

    @staticmethod
    def _validate_turn(turn):
        if (not isinstance(turn, dict) or not isinstance(turn.get('id'), str) or not turn['id']
                or not isinstance(turn.get('status'), str) or turn.get('status') not in TERMINAL | {'inProgress'}
                or turn.get('itemsView', 'full') != 'full'
                or not isinstance(turn.get('items'), list) or not turn['items']):
            raise ProtocolError('Incomplete or unknown native turn')
        for item in turn['items']:
            if not isinstance(item, dict) or not isinstance(item.get('type'), str):
                raise ProtocolError('Invalid native item')
            if item['type'] == 'userMessage':
                if not isinstance(item.get('content'), list) or not item['content']:
                    raise ProtocolError('Invalid native user message')
                if any(not isinstance(part, dict) or not isinstance(part.get('type'), str) for part in item['content']):
                    raise ProtocolError('Invalid native user content')
                if item.get('clientId') is not None and not isinstance(item['clientId'], str):
                    raise ProtocolError('Invalid native correlation marker')
            if item['type'] == 'agentMessage' and not isinstance(item.get('text'), str):
                raise ProtocolError('Invalid native agent message')

    @staticmethod
    def _active(thread):
        return [turn['id'] for turn in thread['turns'] if turn['status'] == 'inProgress']

    @staticmethod
    def _metadata(record, thread):
        for api_key, key in (('model', 'model'), ('reasoningEffort', 'reasoning_effort')):
            value = thread.get(api_key)
            if value:
                previous = record.get(key)
                if previous and previous != value:
                    raise ProtocolError('Native configuration changed')
                record[key] = value

    @staticmethod
    def _correlate(record, turns):
        matches = []
        for turn in turns:
            for item in turn['items']:
                if item['type'] == 'userMessage' and item.get('clientId') == record['operation_id']:
                    content = item['content']
                    if (len(content) != 1 or content[0].get('type') != 'text'
                            or content[0].get('text') != record['text']):
                        raise ProtocolError('Native correlated text mismatch')
                    matches.append(turn)
        if len(matches) != 1:
            raise ProtocolError('Native correlation missing or ambiguous')
        turn = matches[0]
        if turn['id'] in record['baseline_ids'] or (record.get('turn_id') and record['turn_id'] != turn['id']):
            raise ProtocolError('Native correlated turn identity mismatch')
        return turn

    def _unknown(self, record, reason):
        record.update(phase='unknown', reason=reason, final_text=None)
        self._write(record)
        return self._snapshot(record)

    def _apply_turn(self, record, turn):
        receipt = record.get('terminal_receipt')
        if receipt is not None and (receipt['turn_id'] != turn['id'] or receipt['status'] != turn['status']):
            raise ProtocolError('Native terminal receipt mismatch')
        record['turn_id'] = turn['id']
        record['reason'] = None
        if turn['status'] == 'inProgress':
            record['phase'] = 'stopping' if record['interrupt_intent'] else 'running'
            record['final_text'] = None
        else:
            record['phase'] = turn['status']
            record['terminal_receipt'] = {'thread_id': self.thread.thread_id, 'turn_id': turn['id'],
                                          'status': turn['status']}
            final = [item['text'] for item in turn['items']
                     if item['type'] == 'agentMessage' and item.get('phase') in (None, 'final')]
            record['final_text'] = '\n'.join(final) if final else None

    def _reconcile(self, record, deadline):
        try:
            thread = self._read(deadline)
            self._metadata(record, thread)
            if record['phase'] == 'prepared':
                if self._active(thread) or thread['status']['type'] != 'idle':
                    raise ProtocolError('Native thread is not idle')
                if [t['id'] for t in thread['turns']] != record['baseline_ids']:
                    raise ProtocolError('Native prepared history changed')
            else:
                turn = self._correlate(record, thread['turns'])
                self._apply_turn(record, turn)
            self._write(record)
            return self._snapshot(record)
        except (ProtocolError, LifecycleError) as error:
            if isinstance(error, JournalError):
                raise
            if isinstance(error, _DeadlineError) and record['phase'] == 'prepared':
                return self._snapshot(record)
            return self._unknown(record, str(error))

    def prepare(self, operation_id, text, *, deadline):
        _uuid(operation_id, operation=True)
        if not isinstance(text, str) or not text:
            raise LifecycleError('Invalid submission text')
        with self._locked(deadline):
            record = self._load(operation_id)
            if record is not None:
                if record['text'] != text:
                    raise LifecycleConflict('Operation text is immutable')
                return self._reconcile(record, deadline)
            records = self._records()
            if any(r['phase'] not in TERMINAL for r in records):
                raise LifecycleConflict('Unresolved operation exists')
            thread = self._read(deadline)
            if self._active(thread) or thread['status']['type'] != 'idle':
                raise LifecycleConflict('Native thread is not idle')
            record = dict(version=1, operation_id=operation_id, identity=self.identity.copy(), text=text,
                          text_hash=_digest(text), baseline_ids=[t['id'] for t in thread['turns']],
                          phase='prepared', turn_id=None, interrupt_intent=False, terminal_receipt=None,
                          reason=None, model=None, reasoning_effort=None, final_text=None)
            self._metadata(record, thread)
            self._write(record)
            return self._snapshot(record)

    def submit(self, operation_id, *, deadline):
        with self._locked(deadline):
            record = self._required(operation_id)
            if record['phase'] != 'prepared':
                return self._reconcile(record, deadline)
            thread = self._read(deadline)
            try:
                self._metadata(record, thread)
                if (self._active(thread) or thread['status']['type'] != 'idle'
                        or [t['id'] for t in thread['turns']] != record['baseline_ids']):
                    raise ProtocolError('Native prepared history changed')
            except ProtocolError as error:
                return self._unknown(record, str(error))
            self._deadline(deadline)
            record['phase'] = 'uncertain'
            self._write(record)  # FR-CXTASK-LIFE-02/03: may-send truth precedes every byte.
            try:
                result = self._rpc('turn/start', {'threadId': self.thread.thread_id,
                                   'clientUserMessageId': operation_id,
                                   'input': [{'type': 'text', 'text': record['text']}]}, deadline)
                turn = result.get('turn')
                self._validate_turn(turn)
                turn = self._correlate(record, [turn])
                self._apply_turn(record, turn)
            except LifecycleError as error:
                return self._unknown(record, str(error))
            self._write(record)
            return self._snapshot(record)

    def reconcile(self, operation_id, *, deadline):
        with self._locked(deadline):
            return self._reconcile(self._required(operation_id), deadline)

    def observe(self, operation_id, *, deadline):
        with self._locked(deadline):
            record = self._required(operation_id)
            snapshot = self._reconcile(record, deadline)
            if snapshot.terminal_proven or not snapshot.turn_id or snapshot.phase == 'unknown':
                return snapshot
            waiting = False
            # An event-count bound also protects against a transport/fake clock
            # that produces an endless stream without advancing time.
            for _ in range(128):
                try:
                    self._deadline(deadline)
                    event = self.transport.receive(deadline=deadline)
                except Exception:
                    break
                if not isinstance(event, dict):
                    continue
                params = event.get('params')
                if not isinstance(params, dict) or params.get('threadId') != self.thread.thread_id:
                    continue
                method = event.get('method')
                if not isinstance(method, str):
                    continue
                if method in APPROVALS and params.get('turnId') == record['turn_id']:
                    waiting = True
                    break
                turn = params.get('turn')
                if method == 'turn/completed' and isinstance(turn, dict) and turn.get('id') == record['turn_id']:
                    break
                # No response is sent, including for malformed/unknown requests.
            snapshot = self._reconcile(record, deadline)
            if waiting and snapshot.phase == 'running':
                record['phase'] = 'waiting_approval'
                record['reason'] = 'Native approval pending'
                self._write(record)
                snapshot = self._snapshot(record)
            return snapshot

    def interrupt(self, operation_id, *, deadline):
        with self._locked(deadline):
            record = self._required(operation_id)
            snapshot = self._reconcile(record, deadline)
            if snapshot.terminal_proven or snapshot.phase not in {'running', 'stopping', 'waiting_approval'}:
                return snapshot
            try:
                thread = self._read(deadline)
                self._metadata(record, thread)
                turn = self._correlate(record, thread['turns'])
                if self._active(thread) != [record['turn_id']] or turn['status'] != 'inProgress':
                    raise ProtocolError('Native active turn conflict')
            except LifecycleError as error:
                return self._unknown(record, str(error))
            record.update(interrupt_intent=True, phase='stopping', reason=None)
            self._write(record)  # FR-CXTASK-LIFE-07: stop intent precedes interrupt.
            try:
                self._rpc('turn/interrupt', {'threadId': self.thread.thread_id,
                                           'turnId': record['turn_id']}, deadline)
            except LifecycleError as error:
                return self._unknown(record, str(error))
            return self._reconcile(record, deadline)

    def inspect_thread(self, *, deadline):
        with self._locked(deadline):
            records = self._records()
            unresolved = [r['operation_id'] for r in records if r['phase'] not in TERMINAL]
            try:
                thread = self._read(deadline)
                for record in records:
                    self._metadata(record, thread)
                return {'identity_valid': True, 'active_turn_ids': self._active(thread),
                        'unresolved_operation_ids': unresolved, 'reason': None}
            except LifecycleError as error:
                return {'identity_valid': False, 'active_turn_ids': [],
                        'unresolved_operation_ids': unresolved, 'reason': str(error)}
