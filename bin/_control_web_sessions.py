"""Bounded owner-side session chat and interactive shared App Server transport."""
from contextlib import contextmanager
from collections import OrderedDict
import copy
import ctypes
import fcntl
import functools
import hashlib
import json
import math
import os
import re
import socket
import stat
import struct
import threading
import time
import uuid

from _codex_rc import CodexSessions, PROJECT_RE, canonical

HISTORY_LIMIT = 96 * 1024
RECEIPT_LIMIT = 10000
NAMESPACE_ENTRY_LIMIT = 10002
SUPPORTED_NATIVE_VERSIONS = ('0.160.0', '0.161.0')
READ_METHODS = frozenset({'thread/list', 'thread/read', 'thread/turns/list', 'thread/items/list', 'thread/loaded/list'})
VERSION_TOKEN = r'[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}(?:-[A-Za-z0-9][A-Za-z0-9.-]{0,31})?'


class RPCRejected(RuntimeError):
    """Validated server error; does not prove a message was never accepted."""
    def __init__(self, message, rpc_code=None):
        super().__init__(message)
        self.rpc_code = rpc_code


class _DomainError(Exception):
    def __init__(self, code):
        self.code = code


def _need(condition, code='unavailable'):
    if not condition:
        raise _DomainError(code)


def _budget(deadline):
    # Check before/after bounded IO; kernel calls are not real-time preemptible.
    _need(time.monotonic() < deadline)


def valid_uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def valid_project(value):
    return type(value) is str and PROJECT_RE.fullmatch(value) is not None


def valid_cursor(value):
    return value is None or (type(value) is str and 0 < len(value) <= 4096)


def _identity(value):
    return type(value) is str and 0 < len(value) <= 500


def _attention(thread):
    status = thread.get('status')
    return (type(status) is dict and status.get('type') == 'active'
            and type(status.get('activeFlags')) is list
            and all(type(flag) is str for flag in status['activeFlags'])
            and any(flag in ('waitingOnApproval', 'waitingOnUserInput') for flag in status['activeFlags']))


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('invalid JSON object')
        result[key] = value
    return result


def _operation(method):
    @functools.wraps(method)
    def bounded(self, *args, **kwargs):
        self._local.deadline = time.monotonic() + 55
        self._local.read_context = None
        try:
            result = method(self, *args, **kwargs)
            capture = self._local.read_context
            if capture is not None and method.__name__ not in ('send', 'enqueue', 'cancel_queued', 'send_queued_now', 'rename'):
                _need(self._catalog_context() == capture, 'stale')
            return result
        except _DomainError as error:
            return {'error': error.code}
        except Exception:
            return {'error': 'unavailable'}
    return bounded


class _Receipts:
    """Private immutable receipts and explicit snapshot recovery per root/thread."""
    def __init__(self, path):
        self.path = os.path.abspath(path)

    @staticmethod
    def _check(fd, deadline, directory=False):
        _budget(deadline)
        info = os.fstat(fd)
        _budget(deadline)
        _need((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
              and info.st_uid == os.getuid()
              and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
              and (directory or info.st_nlink == 1))

    @staticmethod
    def _not_git(fd, deadline):
        markers = {}
        for name in ('.git', 'HEAD', 'objects', 'refs'):
            _budget(deadline)
            try:
                markers[name] = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                markers[name] = None
            _budget(deadline)
        # Worktrees use a .git file. Any .git marker refuses storage, without
        # opening it. Bare repositories are recognized by metadata alone.
        _need(markers['.git'] is None)
        _need(not (markers['HEAD'] is not None and stat.S_ISREG(markers['HEAD'].st_mode)
                   and markers['objects'] is not None and stat.S_ISDIR(markers['objects'].st_mode)
                   and markers['refs'] is not None and stat.S_ISDIR(markers['refs'].st_mode)))

    def _base(self, create, deadline):
        _budget(deadline)
        _need(self.path != '/data' and not self.path.startswith('/data/'))
        parts = self.path.split('/')[1:]
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for index, part in enumerate(parts):
                self._not_git(fd, deadline)
                _need(part not in ('', '.', '..'))
                if create and index == len(parts) - 1:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        _budget(deadline)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                _budget(deadline)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                _budget(deadline)
            self._not_git(fd, deadline)
            self._check(fd, deadline, True)
            return fd
        except Exception:
            os.close(fd)
            raise

    @contextmanager
    def namespace(self, root, sid, deadline, create=False):
        base = ns = lock = None
        try:
            try:
                base = self._base(create, deadline)
            except FileNotFoundError:
                if create:
                    raise
                _budget(deadline)
                yield None
                return
            name = hashlib.sha256((root + '\0' + sid).encode('utf-8')).hexdigest()
            if create:
                _budget(deadline)
                try:
                    os.mkdir(name, 0o700, dir_fd=base)
                    _budget(deadline)
                    os.fsync(base)
                except FileExistsError:
                    pass
            _budget(deadline)
            try:
                ns = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
            except FileNotFoundError:
                _budget(deadline)
                yield None
                return
            self._check(ns, deadline, True)
            _budget(deadline)
            lock = os.open('.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=ns)
            self._check(lock, deadline)
            while True:
                _need(time.monotonic() < deadline)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(.01, max(0, deadline - time.monotonic())))
            # Locks live on stable inodes; reject path replacement after waiting.
            info = os.stat(name, dir_fd=base, follow_symlinks=False)
            _budget(deadline)
            opened = os.fstat(ns)
            _need((info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino))
            lock_info = os.stat('.lock', dir_fd=ns, follow_symlinks=False)
            _budget(deadline)
            _need((lock_info.st_dev, lock_info.st_ino) ==
                  (os.fstat(lock).st_dev, os.fstat(lock).st_ino))
            current_base = self._base(False, deadline)
            try:
                _need((os.fstat(current_base).st_dev, os.fstat(current_base).st_ino) ==
                      (os.fstat(base).st_dev, os.fstat(base).st_ino))
            finally:
                os.close(current_base)
            _budget(deadline)
            yield ns
        finally:
            for fd in (lock, ns, base):
                if fd is not None:
                    os.close(fd)

    def read(self, ns, root, sid, mid, deadline, context_id=None):
        _budget(deadline)
        if ns is None:
            return None
        try:
            fd = os.open(mid + '.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=ns)
        except FileNotFoundError:
            _budget(deadline)
            return None
        try:
            self._check(fd, deadline)
            _need(os.fstat(fd).st_size <= 128 * 1024)
            _budget(deadline)
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                data = stream.read(128 * 1024 + 1)
                _budget(deadline)
                _need(len(data) <= 128 * 1024)
                record = json.loads(data, object_pairs_hook=_pairs)
            _budget(deadline)
            _need(type(record) is dict)
            _need(record.get('schema') == 4 or len(data) <= 4096)
            fields = {'root', 'sid', 'message_id', 'digest', 'status', 'turn_id', 'created'}
            if record.get('schema') == 4:
                _need(set(record) == fields | {'schema', 'context_id', 'kind', 'queued_submission_id',
                      'reason', 'expected_turn_id', 'client_id', 'snapshot_text', 'phase'}
                      and type(record['schema']) is int and record['kind'] == 'queue_transfer'
                      and type(record['context_id']) is str and re.fullmatch('[0-9a-f]{64}', record['context_id'])
                      and record['status'] in ('held', 'accepted', 'changed', 'delivery_unknown')
                      and record['reason'] in (None, 'target_changed', 'unavailable', 'conflict')
                      and record['phase'] in ('intent', 'held', 'steer_reserved', 'terminal')
                      and all(_identity(record[key]) for key in ('queued_submission_id', 'expected_turn_id', 'client_id')))
                if context_id is not None:
                    _need(record['context_id'] == context_id, 'invalid_request')
                payload = record['snapshot_text']
                terminal = record['status'] in ('accepted', 'changed')
                _need((payload is None and record['phase'] == 'terminal') if terminal else
                      (type(payload) is str and 0 < len(payload) <= 16000 and bool(payload.strip())
                       and record['phase'] != 'terminal'))
                if payload is not None:
                    payload.encode('utf-8')
                    _need(record['digest'] == SessionChat._queue_digest(record['context_id'], root, sid,
                        'queue_transfer', [record['queued_submission_id'], payload, record['expected_turn_id']]))
            elif record.get('schema') == 3:
                _need(set(record) == fields | {'schema', 'context_id', 'kind',
                      'queued_submission_id', 'reason'} and type(record['schema']) is int
                      and record['kind'] in ('queue_enqueue', 'queue_cancel')
                      and type(record['context_id']) is str
                      and re.fullmatch('[0-9a-f]{64}', record['context_id'])
                      and (record['queued_submission_id'] is None or _identity(record['queued_submission_id']))
                      and record['reason'] in (None, 'conflict', 'unavailable', 'stale', 'unsupported_queue'))
                if context_id is not None:
                    _need(record['context_id'] == context_id, 'invalid_request')
                _need(record['status'] in (('queued', 'accepted', 'delivery_unknown')
                      if record['kind'] == 'queue_enqueue' else ('cancelled', 'changed', 'delivery_unknown')))
                _need(record['kind'] != 'queue_cancel' or _identity(record['queued_submission_id']))
                _need(record['status'] != 'queued' or _identity(record['queued_submission_id']))
            elif 'schema' in record:
                _need(set(record) == fields | {'schema', 'context_id', 'selection'}
                      and type(record['schema']) is int and record['schema'] == 2)
                _need(type(record['context_id']) is str
                      and re.fullmatch('[0-9a-f]{64}', record['context_id']))
                if context_id is not None:
                    _need(record['context_id'] == context_id, 'invalid_request')
                choice = record['selection']
                _need(choice is None or _valid_selection(choice, private=True))
            else:
                _need(set(record) == fields)
            _need(record['root'] == root and record['sid'] == sid and record['message_id'] == mid)
            _need(type(record['digest']) is str and re.fullmatch('[0-9a-f]{64}', record['digest']))
            _need(record.get('schema') in (3, 4) or record['status'] in ('accepted', 'delivery_unknown', 'rejected'))
            _need(record['turn_id'] is None or _identity(record['turn_id']))
            _need(record['status'] != 'accepted' or _identity(record['turn_id']))
            _need(type(record['created']) is int and record['created'] > 0)
            return record
        finally:
            os.close(fd)

    def write(self, ns, record, deadline):
        _budget(deadline)
        data = _json(record)
        _need(len(data) <= (128 * 1024 if record.get('schema') == 4 else 4096))
        temp = '.tmp-' + uuid.uuid4().hex
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=ns)
        try:
            _budget(deadline)
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(data)
                stream.flush()
                _budget(deadline)
                os.fsync(fd)
            _budget(deadline)
            os.replace(temp, record['message_id'] + '.json', src_dir_fd=ns, dst_dir_fd=ns)
            _budget(deadline)
            os.fsync(ns)
            _budget(deadline)
        finally:
            os.close(fd)
            try:
                os.unlink(temp, dir_fd=ns)
            except FileNotFoundError:
                pass

    @staticmethod
    def result(record):
        if record.get('schema') == 4:
            return {key: record[key] for key in ('status', 'message_id', 'queued_submission_id', 'turn_id', 'reason')}
        if record.get('schema') == 3 and record['status'] != 'accepted':
            result = {key: record[key] for key in ('status', 'message_id', 'queued_submission_id')}
            if record['reason'] is not None:
                result['reason'] = record['reason']
            return result
        return {key: record[key] for key in ('status', 'message_id', 'turn_id')}

    def names(self, ns, deadline, reserve=False):
        _budget(deadline)
        if ns is None:
            return []
        names = []
        count = 0
        # SIMPLIFIED: bounded per-thread metadata enumeration; retain all dedup
        # records. A future tombstone/index scheme must preserve UUID protection.
        with os.scandir(ns) as entries:
            while True:
                _budget(deadline)
                try:
                    entry = next(entries)
                except StopIteration:
                    break
                _budget(deadline)
                count += 1
                _need(count <= NAMESPACE_ENTRY_LIMIT)
                if entry.name == '.lock' or entry.name.startswith('.tmp-'):
                    continue
                _need(entry.name.endswith('.json') and valid_uuid(entry.name[:-5]))
                names.append(entry.name[:-5])
                _need(len(names) <= RECEIPT_LIMIT)
        _budget(deadline)
        # A new reserve needs one entry for its atomic-write temporary file.
        # Existing UUID lookup precedes this check, preserving dedup at capacity.
        _need(not reserve or count < NAMESPACE_ENTRY_LIMIT)
        return names

    def recent(self, ns, root, sid, deadline, context_id=None):
        records = [self.read(ns, root, sid, mid, deadline, context_id) for mid in self.names(ns, deadline)]
        _budget(deadline)
        _need(all(record is not None for record in records))
        # Queue rows have their own native projection; cancellation actions are
        # not outgoing chat messages. Keep the existing history receipt schema.
        records = [record for record in records if record.get('kind') not in ('queue_cancel', 'queue_transfer')
                   and record['status'] != 'queued']
        records.sort(key=lambda record: (record['created'], record['message_id']), reverse=True)
        _budget(deadline)
        return [{key: record[key] for key in ('status', 'message_id', 'turn_id')}
                for record in records[:8]]


class RenameStore(_Receipts):
    """Separate digest-only metadata; the private directory is its stable lock."""
    def __init__(self, path):
        self.path = os.fspath(path)
        _need(type(self.path) is str and os.path.isabs(self.path))

    @contextmanager
    def locked(self, deadline, create=False):
        base = None
        try:
            try:
                base = self._base(create, deadline)
            except FileNotFoundError:
                if create:
                    raise
                yield None
                return
            while True:
                _budget(deadline)
                try:
                    fcntl.flock(base, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(.01, max(0, deadline - time.monotonic())))
            current = self._base(False, deadline)
            try:
                _need((os.fstat(current).st_dev, os.fstat(current).st_ino) ==
                      (os.fstat(base).st_dev, os.fstat(base).st_ino))
            finally:
                os.close(current)
            yield base
        finally:
            if base is not None:
                os.close(base)

    @staticmethod
    def _name(context_id, root, sid, operation_id):
        return _context_token({'kind': 'session_rename', 'context_id': context_id,
                               'root': root, 'sid': sid, 'operation_id': operation_id}) + '.json'

    def _anchor(self, base, deadline):
        current = self._base(False, deadline)
        try:
            self._check(base, deadline, True)
            _need((os.fstat(current).st_dev, os.fstat(current).st_ino) ==
                  (os.fstat(base).st_dev, os.fstat(base).st_ino))
        finally:
            os.close(current)

    def lookup(self, base, context_id, root, sid, operation_id, deadline):
        _budget(deadline)
        if base is None:
            return None, None
        self._anchor(base, deadline)
        name = self._name(context_id, root, sid, operation_id)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=base)
        except FileNotFoundError:
            return None, None
        try:
            self._check(fd, deadline)
            before = os.fstat(fd)
            _need(before.st_size <= 4096)
            data = os.read(fd, 4097)
            _budget(deadline)
            _need(len(data) <= 4096 and os.read(fd, 1) == b'')
            record = json.loads(data, object_pairs_hook=_pairs,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            _need(type(record) is dict and set(record) == {
                'schema', 'kind', 'context_id', 'root', 'sid', 'operation_id',
                'digest', 'title_hash', 'status', 'created'})
            _need(type(record['schema']) is int and record['schema'] == 1
                  and record['kind'] == 'session_rename'
                  and record['context_id'] == context_id and record['root'] == root
                  and record['sid'] == sid and record['operation_id'] == operation_id
                  and record['status'] in ('unknown', 'accepted')
                  and type(record['created']) is int and record['created'] > 0
                  and all(type(record[key]) is str and re.fullmatch('[0-9a-f]{64}', record[key])
                          for key in ('context_id', 'digest', 'title_hash')))
            live = os.stat(name, dir_fd=base, follow_symlinks=False)
            _need(self._pin(before) == self._pin(os.fstat(fd)) == self._pin(live))
            return record, before
        finally:
            os.close(fd)

    @staticmethod
    def _pin(info):
        return tuple(getattr(info, key) for key in ('st_dev', 'st_ino', 'st_uid', 'st_mode',
                     'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))

    def publish(self, base, record, deadline, previous=None):
        _budget(deadline)
        data = _json(record)
        _need(len(data) <= 4096)
        name = self._name(record['context_id'], record['root'], record['sid'], record['operation_id'])
        temp = '.tmp-' + uuid.uuid4().hex
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=base)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(data)
            while view:
                _budget(deadline)
                written = os.write(fd, view)
                _need(written > 0)
                view = view[written:]
            os.fsync(fd)
            _budget(deadline)
            self._anchor(base, deadline)
            self._check(fd, deadline)
            _need(self._pin(os.fstat(fd)) == self._pin(os.stat(temp, dir_fd=base, follow_symlinks=False)))
            if previous is None:
                # Linux atomic no-replace keeps the published receipt at nlink=1,
                # including a process crash before directory fsync.
                renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
                renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
                renameat2.restype = ctypes.c_int
                if renameat2(base, os.fsencode(temp), base, os.fsencode(name), 1) != 0:
                    code = ctypes.get_errno()
                    raise OSError(code, os.strerror(code))
            else:
                _need(self._pin(os.stat(name, dir_fd=base, follow_symlinks=False)) == self._pin(previous))
                os.replace(temp, name, src_dir_fd=base, dst_dir_fd=base)
            os.fsync(base)
            self._anchor(base, deadline)
            _budget(deadline)
        finally:
            os.close(fd)
            try:
                os.unlink(temp, dir_fd=base)
            except FileNotFoundError:
                pass

    def capacity(self, base, deadline):
        count = 0
        with os.scandir(base) as entries:
            for entry in entries:
                _budget(deadline)
                count += 1
                _need(count < NAMESPACE_ENTRY_LIMIT)
                if entry.name.startswith('.tmp-'):
                    continue
                _need(re.fullmatch(r'[0-9a-f]{64}\.json', entry.name) is not None)
        _need(count < RECEIPT_LIMIT)


def _valid_selection(value, private=False):
    from _control_web_broker import SECRET_RE
    fields = {'catalog_id', 'model_id', 'effort'} | ({'wire_model'} if private else set())
    return (type(value) is dict and set(value) == fields
            and type(value['catalog_id']) is str
            and re.fullmatch('[0-9a-f]{64}', value['catalog_id']) is not None
            and all(type(value[key]) is str and 0 < len(value[key]) <= 256
                    and not any(ord(char) < 32 or 127 <= ord(char) <= 159
                                or 0xd800 <= ord(char) <= 0xdfff for char in value[key])
                    and SECRET_RE.search(value[key]) is None
                    for key in fields - {'catalog_id'}))


def _receipt_digest(context_id, root, sid, text, selection):
    payload = {'context_id': context_id, 'root': root, 'sid': sid,
               'text': text, 'selection': selection}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _context_token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


class SessionChat:
    def __init__(self, rpc, project_path, project_names, receipt_dir, *,
                 summary_clock=None, summary_wall_clock=None, summary_generation=None,
                 model_context=None, model_clock=None, rename_store=None, configured_creator=None):
        self.rpc, self.project_path, self.project_names = rpc, project_path, project_names
        self.configured_creator = configured_creator
        self.receipts = _Receipts(receipt_dir)
        self.renames = (rename_store if rename_store is not None else
                        RenameStore(os.path.join(os.path.dirname(self.receipts.path), 'web-rename-receipts')))
        _need(all(callable(getattr(self.renames, method, None))
                  for method in ('locked', 'lookup', 'publish', 'capacity')))
        self._local = threading.local()
        self._summary_clock = summary_clock or time.monotonic
        self._summary_wall_clock = summary_wall_clock or time.time
        self._summary_generation = summary_generation or (lambda: rpc.generation if isinstance(rpc, InteractiveRPC) else 0)
        self._summary_lock = threading.Lock()
        self._summary_cache = None
        self._summary_revision = 0
        self._explicit_model_context = model_context is not None
        self._has_model_context = hasattr(rpc, 'model_context')
        self._has_receipt_context = hasattr(rpc, 'receipt_context')
        self._model_context = model_context if model_context is not None else getattr(rpc, 'model_context', lambda: None)
        self._model_clock = model_clock or time.monotonic
        self._model_lock = threading.Lock()
        self._model_cache = OrderedDict()
        self._history_observation = None

    def _configured_call(self, method, *args):
        self._remaining()
        call = getattr(self.configured_creator, method, None)
        _need(callable(call))
        result = call(*args, deadline=self._local.deadline)
        self._remaining()
        if type(result) is dict and 'error' in result:
            _need(False, result['error'] if result['error'] in
                  ('invalid_request', 'forbidden', 'stale', 'unavailable') else 'unavailable')
        return result

    def _configured_identity(self):
        if self.configured_creator is None:
            return None
        identity = self._configured_call('cache_identity')
        context, namespace = dict(identity.context), identity.namespace
        _need(set(context) == {'schema', 'vendor', 'context_kind', 'context_id',
                              'transport_generation', 'context_generation', 'native_version'}
              and self._read_context_reason(context) is None)
        self._capture_read_context(context)
        if namespace is not None:
            namespace = dict(namespace)
            _need(set(namespace) == {'dev', 'ino', 'mtime_ns', 'ctime_ns'}
                  and all(type(v) is int and v >= 0 for v in namespace.values()))
        return (tuple(sorted(context.items())),
                None if namespace is None else tuple(sorted(namespace.items())))

    def _configured_origin(self, method, project, root, sid):
        if self.configured_creator is None:
            return None
        witness = self._configured_call(method, project, sid)
        if witness is None:
            return None
        record, context, session = (dict(witness.reservation.record),
                                    dict(witness.context), dict(witness.session))
        _need(record.get('status') == 'accepted' and record.get('project') == project
              and record.get('root') == root and record.get('sid') == sid
              and valid_uuid(record.get('operation_id'))
              and self._read_context_reason(context) is None
              and record.get('context_id') == context.get('context_id')
              and context == self._catalog_context(), 'stale')
        _need(set(session) == {'sid', 'project', 'vendor', 'context_mode', 'title'}
              and session['sid'] == sid and session['project'] == project
              and session['vendor'] == 'codex' and session['context_mode'] == 'configured'
              and (session['title'] is None or type(session['title']) is str))
        _need(self._root(project) == root, 'stale')
        if method == 'unavailable_history':
            _need(type(witness.needs_native_attention) is bool)
        return witness

    def _configured_overlay(self, project):
        result = self._configured_call('overlay', project)
        _need(type(result) is dict and set(result) == {'sessions', 'truncated'}
              and type(result['sessions']) is list and len(result['sessions']) <= 128
              and type(result['truncated']) is bool)
        seen = set()
        for row in result['sessions']:
            _need(type(row) is dict and set(row) in (
                  {'sid', 'project', 'vendor', 'context_mode', 'title', 'status', 'updated_at'},
                  {'sid', 'project', 'vendor', 'context_mode', 'title', 'status', 'updated_at',
                   'needs_native_attention'})
                  and valid_uuid(row['sid']) and row['sid'] not in seen
                  and row['project'] == project and row['vendor'] == 'codex'
                  and row['context_mode'] == 'configured'
                  and (row['title'] is None or type(row['title']) is str)
                  and row['status'] in ('notLoaded', 'idle', 'systemError', 'active')
                  and type(row['updated_at']) in (int, float)
                  and math.isfinite(row['updated_at']) and row['updated_at'] >= 0
                  and ('needs_native_attention' not in row or row['needs_native_attention'] is True))
            seen.add(row['sid'])
        return result

    def _remaining(self):
        value = self._local.deadline - time.monotonic()
        _need(value > 0)
        return value

    def _capture_read_context(self, context=None):
        prepare = getattr(self.rpc, 'prepare_context', None)
        if not callable(prepare):
            return None
        capture = getattr(self._local, 'read_context', None)
        if capture is None:
            capture = copy.deepcopy(context if context is not None else prepare(timeout=self._remaining()))
            _need(self._read_context_reason(capture) is None)
            self._local.read_context = capture
        _need(context is None or context == capture, 'stale')
        _need(self._catalog_context() == capture, 'stale')
        return capture

    def _rpc(self, method, params):
        remaining = self._remaining()
        capture = self._capture_read_context() if method in READ_METHODS else None
        if capture is not None:
            return self._send_fenced(method, params, capture)
        result = (self.rpc.call(method, params, timeout=remaining)
                  if isinstance(self.rpc, InteractiveRPC) else self.rpc(method, params))
        self._remaining()
        _need(type(result) is dict)
        return result

    def _names(self):
        self._remaining()
        names = self._provider(self.project_names)
        _need(type(names) is list and len(names) <= 1000
              and all(valid_project(name) for name in names) and len(set(names)) == len(names))
        return names

    def _root(self, project):
        _need(valid_project(project), 'invalid_request')
        _need(project in self._names(), 'invalid_request')
        self._remaining()
        root = self._provider(self.project_path, project)
        _need(type(root) is str and os.path.isabs(root))
        root = canonical(root)
        _need(os.path.isdir(root))
        self._remaining()
        return root

    def _provider(self, provider, *args):
        # Real owner resolvers accept a remaining deadline; simple synthetic
        # callables keep the public positional-only injection contract.
        bounded = getattr(provider, 'deadline_call', None)
        return bounded(self._local.deadline, *args) if callable(bounded) else provider(*args)

    def _proof(self, root, sid, method='thread/read'):
        params = {'threadId': sid}
        if method == 'thread/read':
            params['includeTurns'] = False
        elif method == 'thread/resume':
            params['excludeTurns'] = True
        thread = self._rpc(method, params).get('thread')
        _need(type(thread) is dict and valid_uuid(thread.get('id'))
              and type(thread.get('cwd')) is str and os.path.isabs(thread['cwd']))
        _need(thread['id'] == sid and canonical(thread['cwd']) == root, 'stale')
        return thread

    def _catalog_context(self):
        value = self._model_context()
        self._remaining()
        return copy.deepcopy(value)

    def _receipt_context(self):
        fields = ('schema', 'vendor', 'context_kind', 'context_id')
        def model_snapshot(context):
            _need(self._read_context_reason(context) is None
                  and context['vendor'] == 'codex'
                  and (context['native_version'] is None or type(context['native_version']) is str))
            return {key: context[key] for key in fields}
        if self._explicit_model_context:
            return model_snapshot(self._catalog_context())
        if self._has_receipt_context:
            provider = getattr(self.rpc, 'receipt_context')
            _need(callable(provider))
            context = copy.deepcopy(provider())
            self._remaining()
            _need(type(context) is dict and set(context) == set(fields)
                  and type(context['schema']) is int and context['schema'] == 1
                  and context['vendor'] == 'codex' and context['context_kind'] == 'legacy_unbound'
                  and type(context['context_id']) is str
                  and re.fullmatch('[0-9a-f]{64}', context['context_id']))
            if self._has_model_context:
                live = self._catalog_context()
                if live is not None:
                    _need(model_snapshot(live) == context)
            return context
        if self._has_model_context:
            return model_snapshot(self._catalog_context())
        # A trusted plain callable has only server-owned store identity. This
        # compatibility marker grants no model capability or adapter authority.
        identity = {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                    'owner_uid': os.getuid(), 'receipt_root': self.receipts.path}
        return {key: identity[key] for key in fields[:-1]} | {'context_id': _context_token(identity)}

    def _send_selection(self, selection, context):
        _need(self._catalog_reason(context) is None
              and callable(getattr(self.rpc, 'call_in_generation', None)))
        _need(self._catalog_context() == context, 'stale')
        key = tuple(context[field] for field in ('vendor', 'context_kind', 'context_id',
                                                'transport_generation', 'context_generation'))
        with self._model_lock:
            entry = self._model_cache.get(key)
            if entry is None:
                _need(not any(row['dto']['catalog_id'] == selection['catalog_id']
                              for row in self._model_cache.values()), 'stale')
                raise _DomainError('unavailable')
            _need(entry['expires'] > self._model_clock()
                  and entry['dto']['catalog_id'] == selection['catalog_id'], 'stale')
            row = next((row for row in entry['dto']['rows'] if row['id'] == selection['model_id']), None)
            _need(row is not None and selection['effort'] in row['efforts'], 'invalid_request')
            return dict(selection, wire_model=entry['wire_models'][selection['model_id']])

    def _send_fenced(self, method, params, context):
        _need(self._catalog_context() == context, 'stale')
        result = self.rpc.call_in_generation(method, params,
                    transport_generation=context['transport_generation'],
                    context_generation=context['context_generation'], timeout=self._remaining())
        self._remaining()
        _need(self._catalog_context() == context, 'stale')
        _need(type(result) is dict)
        return result

    @staticmethod
    def _read_context_reason(context):
        if (type(context) is not dict or set(context) != {
                'schema', 'vendor', 'context_kind', 'context_id',
                'transport_generation', 'context_generation', 'native_version'}
                or type(context['schema']) is not int or context['schema'] != 1
                or type(context['context_id']) is not str
                or re.fullmatch('[0-9a-f]{64}', context['context_id']) is None
                or any(type(context[key]) is not int or context[key] < 0
                       for key in ('transport_generation', 'context_generation'))
                or type(context['vendor']) is not str
                or context['context_kind'] not in ('legacy_unbound', 'verified_bound', 'unverified_bound')):
            return 'unverified_context'
        if context['vendor'] != 'codex':
            return 'unsupported_vendor'
        # A metadata binding does not authorize shared legacy transport discovery.
        if context['context_kind'] != 'legacy_unbound':
            return 'unverified_context'
        version = context['native_version']
        if version is not None and (type(version) is not str or len(version) > 64 or re.fullmatch(VERSION_TOKEN, version) is None):
            return 'unverified_context'
        return None

    @staticmethod
    def _catalog_reason(context):
        reason = SessionChat._read_context_reason(context)
        if reason is not None:
            return reason
        return None if context['native_version'] in SUPPORTED_NATIVE_VERSIONS else 'unsupported_capability'



    @staticmethod
    def _catalog_unavailable(context, reason):
        context = context if type(context) is dict else {}
        vendor = context.get('vendor')
        kind = context.get('context_kind')
        return {'schema': 1, 'vendor': vendor if vendor in ('codex', 'claude') else None,
                'context_kind': kind if kind in ('legacy_unbound', 'verified_bound', 'unverified_bound') else 'unverified_bound',
                'selection_support': 'unavailable', 'reason': reason,
                'catalog_id': None, 'expires_in_ms': 0, 'rows': []}

    @staticmethod
    def _catalog_row(row):
        from _control_web_broker import SECRET_RE, redact
        def key(value):
            return (type(value) is str and 0 < len(value) <= 256
                    and not any(ord(char) < 32 or 127 <= ord(char) <= 159
                                or 0xd800 <= ord(char) <= 0xdfff for char in value)
                    and SECRET_RE.search(value) is None)
        _need(type(row) is dict and key(row.get('id')) and key(row.get('model')))
        _need(type(row.get('displayName')) is str and len(row['displayName']) <= 500
              and type(row.get('description')) is str
              and type(row.get('isDefault')) is bool and type(row.get('hidden')) is bool)
        supported = row.get('supportedReasoningEfforts')
        _need(type(supported) is list and 0 < len(supported) <= 32)
        efforts = []
        for entry in supported:
            _need(type(entry) is dict and key(entry.get('reasoningEffort'))
                  and type(entry.get('description')) is str)
            efforts.append(entry['reasoningEffort'])
        _need(len(set(efforts)) == len(efforts) and key(row.get('defaultReasoningEffort'))
              and row['defaultReasoningEffort'] in efforts)
        return {'id': row['id'], 'label': redact(row['displayName']), 'efforts': efforts,
                'default_effort': row['defaultReasoningEffort'], 'is_default': row['isDefault']}

    @_operation
    def models(self, project, sid):
        # INV-WSESS-24: fresh root/thread proof also precedes warm-cache reads.
        _need(valid_uuid(sid), 'invalid_request')
        root = self._root(project)
        self._proof(root, sid)
        try:
            context = self._catalog_context()
        except Exception:
            return self._catalog_unavailable(None, 'unverified_context')
        reason = self._catalog_reason(context)
        if reason:
            return self._catalog_unavailable(context, reason)
        fenced = getattr(self.rpc, 'call_in_generation', None)
        if not callable(fenced):
            return self._catalog_unavailable(context, 'unsupported_capability')
        key = tuple(context[field] for field in ('vendor', 'context_kind', 'context_id',
                                                'transport_generation', 'context_generation'))
        with self._model_lock:
            now = self._model_clock()
            for expired in [cache_key for cache_key, entry in self._model_cache.items()
                            if entry['expires'] <= now]:
                del self._model_cache[expired]
            cached = self._model_cache.get(key)
            if cached:
                self._model_cache.move_to_end(key)
                result = copy.deepcopy(cached['dto'])
                result['expires_in_ms'] = max(1, min(60000, int((cached['expires'] - now) * 1000)))
                return result
        try:
            rows, wire_models, ids, wires, cursors = [], {}, set(), set(), set()
            cursor, row_count, byte_count = None, 0, 0
            for _ in range(16):
                params = {'limit': 64, 'includeHidden': False}
                if cursor is not None:
                    params['cursor'] = cursor
                page = fenced('model/list', params,
                              transport_generation=context['transport_generation'],
                              context_generation=context['context_generation'], timeout=self._remaining())
                self._remaining()
                _need(self._catalog_context() == context)
                _need(type(page) is dict and type(page.get('data')) is list)
                byte_count += len(_json(page))
                row_count += len(page['data'])
                _need(byte_count <= 1024 * 1024 and row_count <= 256)
                for native in page['data']:
                    self._remaining()
                    row = self._catalog_row(native)
                    _need(row['id'] not in ids and native['model'] not in wires)
                    ids.add(row['id'])
                    wires.add(native['model'])
                    if not native['hidden']:
                        rows.append(row)
                        wire_models[row['id']] = native['model']
                cursor = page.get('nextCursor')
                _need(valid_cursor(cursor))
                if cursor is None:
                    break
                _need(cursor not in cursors)
                cursors.add(cursor)
            else:
                raise _DomainError('unavailable')
            _need(self._catalog_context() == context)
            if not rows:
                return self._catalog_unavailable(context, 'empty_catalog')
            nonce = uuid.uuid4().hex
            catalog_id = hashlib.sha256(_json([context, rows, nonce])).hexdigest()
            dto = {'schema': 1, 'vendor': context['vendor'], 'context_kind': context['context_kind'],
                   'selection_support': 'available', 'reason': None, 'catalog_id': catalog_id,
                   'expires_in_ms': 60000, 'rows': rows}
            with self._model_lock:
                _need(self._catalog_context() == context)
                self._model_cache[key] = {'dto': copy.deepcopy(dto), 'wire_models': wire_models,
                                          'expires': self._model_clock() + 60}
                self._model_cache.move_to_end(key)
                while len(self._model_cache) > 32:
                    self._model_cache.popitem(last=False)
            return dto
        except Exception:
            return self._catalog_unavailable(context, 'catalog_unavailable')

    def _page(self, sid, cursor, limit=8):
        params = {'threadId': sid, 'itemsView': 'full', 'sortDirection': 'desc', 'limit': limit}
        if cursor is not None:
            params['cursor'] = cursor
        response = self._rpc('thread/turns/list', params)
        _need(type(response.get('data')) is list and len(response['data']) <= limit
              and 'nextCursor' in response and valid_cursor(response['nextCursor']))
        _need(response['nextCursor'] is None or response['nextCursor'] != cursor)
        validated = 0
        for turn in response['data']:
            self._remaining()
            _need(type(turn) is dict and _identity(turn.get('id'))
                  and turn.get('status') in ('completed', 'interrupted', 'failed', 'inProgress')
                  and type(turn.get('items')) is list and len(turn['items']) <= 10000)
            for item in turn['items']:
                validated += 1
                if validated % 256 == 0:
                    self._remaining()
                _need(type(item) is dict and _identity(item.get('id')) and type(item.get('type')) is str)
                if item['type'] == 'userMessage':
                    _need(type(item.get('content')) is list)
                    for content in item['content']:
                        validated += 1
                        if validated % 256 == 0:
                            self._remaining()
                        _need(type(content) is dict and type(content.get('type')) is str)
                        if content['type'] == 'text':
                            _need(type(content.get('text')) is str)
                    if item.get('clientId') is not None:
                        _need(type(item['clientId']) is str)
                elif item['type'] == 'agentMessage':
                    _need(type(item.get('text')) is str)
        self._remaining()
        return response

    def _history_page(self, sid, cursor, limit, context):
        params = {'threadId': sid, 'itemsView': 'notLoaded',
                  'sortDirection': 'desc', 'limit': limit}
        if cursor is not None:
            params['cursor'] = cursor
        response = self._rpc('thread/turns/list', params)
        _need(type(response.get('data')) is list and len(response['data']) <= limit
              and 'nextCursor' in response and valid_cursor(response['nextCursor'])
              and (response['nextCursor'] is None or response['nextCursor'] != cursor))
        _need(self._receipt_context() == context, 'stale')
        turns, turn_ids = [], set()
        for turn in response['data']:
            _need(type(turn) is dict and _identity(turn.get('id'))
                  and turn['id'] not in turn_ids
                  and turn.get('status') in ('completed', 'interrupted', 'failed', 'inProgress')
                  and type(turn.get('items')) is list and not turn['items']
                  and turn.get('itemsView', 'notLoaded') == 'notLoaded')
            turn_ids.add(turn['id'])
            turns.append({key: turn[key] for key in ('id', 'status', 'items', 'startedAt')
                          if key in turn})
        used, truncated, stopped = 0, False, False
        item_ids = set()
        for turn in turns:
            item_cursor, cursors, projected = None, set(), []
            if stopped:
                continue
            for _ in range(4):
                params = {'threadId': sid, 'turnId': turn['id'],
                          'sortDirection': 'desc', 'limit': 32}
                if item_cursor is not None:
                    params['cursor'] = item_cursor
                try:
                    page = self._rpc('thread/items/list', params)
                except RPCRejected:
                    # Only unavailable turn metadata can use the controlled-empty variant.
                    raise _DomainError('unavailable') from None
                _need(self._receipt_context() == context, 'stale')
                _need(type(page.get('data')) is list and len(page['data']) <= 32
                      and 'nextCursor' in page and valid_cursor(page['nextCursor']))
                following = page['nextCursor']
                _need(following is None or following != item_cursor and following not in cursors)
                size = len(_json(page))
                page_projection = []
                for entry in page['data']:
                    self._remaining()
                    _need(type(entry) is dict and {'turnId', 'item'} <= set(entry)
                          <= {'turnId', 'item', 'startedAtMs', 'completedAtMs'}
                          and entry['turnId'] == turn['id'])
                    for timing in ('startedAtMs', 'completedAtMs'):
                        value = entry.get(timing)
                        _need(value is None or type(value) is int
                              and -(2 ** 63) <= value < 2 ** 63)
                    item = entry['item']
                    _need(type(item) is dict and _identity(item.get('id'))
                          and item['id'] not in item_ids and type(item.get('type')) is str)
                    item_ids.add(item['id'])
                    if item['type'] == 'userMessage':
                        _need(type(item.get('content')) is list
                              and (item.get('clientId') is None or type(item['clientId']) is str))
                        content = []
                        for part in item['content']:
                            self._remaining()
                            _need(type(part) is dict and type(part.get('type')) is str)
                            if part['type'] == 'text':
                                _need(type(part.get('text')) is str)
                                content.append({'type': 'text', 'text': part['text']})
                        page_projection.append({'id': item['id'], 'type': item['type'],
                                                'content': content})
                        if valid_uuid(item.get('clientId')):
                            page_projection[-1]['clientId'] = item['clientId']
                    elif item['type'] == 'agentMessage':
                        _need(type(item.get('text')) is str)
                        page_projection.append({'id': item['id'], 'type': item['type'],
                                                'text': item['text']})
                    if item['type'] in ('userMessage', 'agentMessage'):
                        page_projection[-1]['startedAtMs'] = entry.get('startedAtMs')
                entry = item = part = None
                if used + size > 8 * 1024 * 1024:
                    truncated, stopped = True, True
                    break
                used += size
                projected.extend(page_projection)
                # Retain only text projection, not native tool/image payloads.
                page = None
                if following is None:
                    break
                cursors.add(following)
                item_cursor = following
            else:
                truncated = True
            turn['items'] = list(reversed(projected))
        self._remaining()
        return {'data': turns, 'nextCursor': response['nextCursor'], 'truncated': truncated}

    @_operation
    def projects(self):
        names = self._names()
        projects = []
        for name in names:
            try:
                self._remaining()
                root = self._provider(self.project_path, name)
                self._remaining()
                _need(type(root) is str and os.path.isabs(root))
                root = canonical(root)
                _need(os.path.isdir(root))
                self._remaining()
            except Exception:
                # A failing root is local only while the shared operation budget
                # remains. Expiry after a slow resolver still fails globally.
                self._remaining()
                projects.append({'name': name, 'unavailable': True})
            else:
                projects.append({'name': name})
        self._remaining()
        return {'projects': projects}

    @_operation
    def project_summary(self):
        # INV-WSESS-18: only complete allowlisted metadata scans enter cache.
        self._local.deadline = time.monotonic() + 15
        deadline = self._summary_clock() + 15
        def budget():
            _need(self._summary_clock() < deadline)
            self._remaining()
        budget()
        def capture_roots():
            names, roots = self._names(), {}
            for name in names:
                try:
                    budget()
                    root = self._provider(self.project_path, name)
                    _need(type(root) is str and os.path.isabs(root))
                    root = canonical(root)
                    _need(os.path.isdir(root))
                    budget()
                    roots[name] = root
                except Exception:
                    budget()
            return names, roots
        names, roots = capture_roots()
        allowed = tuple(sorted(set(roots.values())))
        def export(cache, state):
            return {'projects': [dict(name=name,
                session_count=cache['values'][roots[name]][0] if cache and name in roots else None,
                last_activity=cache['values'][roots[name]][1] if cache and name in roots else None,
                summary_state=state if name in roots else 'unavailable',
                as_of=cache['as_of'] if cache and name in roots else None) for name in names]}
        _need(self._summary_lock.acquire(timeout=self._remaining()))
        try:
            budget()
            generation = self._summary_generation()
            try:
                origin_identity = self._configured_identity()
            except Exception:
                self._summary_cache = None
                return export(None, 'unknown')
            def cache_key(current_generation):
                return ((allowed, current_generation) if self.configured_creator is None else
                        (allowed, current_generation, origin_identity))
            def final_fence():
                budget()
                _need(capture_roots() == (names, roots), 'stale')
                _need(self._configured_identity() == origin_identity, 'stale')
                budget()
            cached = self._summary_cache
            if cached and cached['key'] != cache_key(generation):
                cached = None
                self._summary_cache = None
            if not allowed:
                return export(None, 'unknown')
            revision = self._summary_revision
            if cached and cached['revision'] == revision and self._summary_clock() - cached['at'] < 30:
                try:
                    final_fence()
                    _need(self._summary_generation() == generation)
                    return export(cached, 'fresh')
                except Exception:
                    self._summary_cache = None
                    return export(None, 'unknown')
            try:
                values = {root: [0, None] for root in allowed}
                identities, cursors = {}, set()
                cursor, scan_generation = None, None
                for _ in range(100):
                    budget()
                    params = dict(cwd=list(allowed), limit=100, sourceKinds=['cli', 'vscode', 'appServer'],
                                  archived=False, sortKey='updated_at', sortDirection='desc')
                    if cursor is not None:
                        params['cursor'] = cursor
                    page = self._rpc('thread/list', params)
                    budget()
                    current_generation = self._summary_generation()
                    # The first call may establish the initial native connection.
                    if scan_generation is None:
                        _need(current_generation == generation or isinstance(self.rpc, InteractiveRPC))
                        if current_generation != generation:
                            cached = None
                        scan_generation = current_generation
                    _need(current_generation == scan_generation)
                    _need(type(page.get('data')) is list and len(page['data']) <= 100
                          and 'nextCursor' in page and valid_cursor(page['nextCursor']))
                    for thread in page['data']:
                        budget()
                        _need(type(thread) is dict and valid_uuid(thread.get('id'))
                              and type(thread.get('cwd')) is str and os.path.isabs(thread['cwd']))
                        root = canonical(thread['cwd'])
                        if root not in values:
                            continue
                        source = thread.get('source')
                        # Native Thread has no archived field; archived:false is
                        # authoritative on the list request. Validate it if supplied.
                        archived = thread.get('archived', False)
                        _need(type(source) in (str, dict) and type(archived) is bool
                              and type(thread.get('status')) is dict
                              and _identity(thread['status'].get('type')))
                        if source not in ('cli', 'vscode', 'appServer') or archived:
                            continue
                        updated = thread.get('updatedAt')
                        _need(type(updated) in (int, float) and math.isfinite(updated) and updated >= 0)
                        metadata = (root, updated)
                        previous = identities.get(thread['id'])
                        if previous is not None:
                            _need(previous == metadata)
                            continue
                        identities[thread['id']] = metadata
                        values[root][0] += 1
                        values[root][1] = updated if values[root][1] is None else max(values[root][1], updated)
                    cursor = page['nextCursor']
                    if cursor is None:
                        break
                    _need(cursor not in cursors)
                    cursors.add(cursor)
                else:
                    raise _DomainError('unavailable')
                if self.configured_creator is not None:
                    overlay_ids = set()
                    for project, root in roots.items():
                        overlay = self._configured_overlay(project)
                        _need(not overlay['truncated'])
                        for row in overlay['sessions']:
                            sid = row['sid']
                            if sid in identities:
                                _need(identities[sid][0] == root, 'stale')
                                continue
                            key = (root, sid)
                            if key in overlay_ids:
                                continue
                            overlay_ids.add(key)
                            values[root][0] += 1
                            updated = row['updated_at']
                            values[root][1] = updated if values[root][1] is None else max(values[root][1], updated)
                final_fence()
                budget()
                _need(self._summary_generation() == scan_generation and self._summary_revision == revision)
                good = dict(key=cache_key(scan_generation), values=values,
                            at=self._summary_clock(), as_of=self._summary_wall_clock(), revision=revision)
                self._summary_cache = good
                return export(good, 'fresh')
            except Exception:
                try:
                    final_fence()
                    _need(self._summary_generation() == generation)
                except Exception:
                    cached = None
                    self._summary_cache = None
                return export(cached, 'stale' if cached else 'unknown')
        finally:
            self._summary_lock.release()

    @_operation
    def list_sessions(self, project, page=0):
        _need(type(page) is int and page >= 0, 'invalid_request')
        root = self._root(project)
        origin_identity = self._configured_identity()
        def checked_rpc(method, params):
            response = self._rpc(method, params)
            _need(type(response.get('data')) is list and 'nextCursor' in response
                  and valid_cursor(response['nextCursor']))
            for thread in response['data']:
                _need(type(thread) is dict and valid_uuid(thread.get('id')))
            return response
        service = CodexSessions(checked_rpc, lambda alias: root)
        if self.configured_creator is None:
            result = service.list_sessions(project, page)
        else:
            native = service._rows(root)
            overlay = self._configured_overlay(project)
            _need(not overlay['truncated'])
            by_sid = {row['sid']: row for row in native}
            for row in overlay['sessions']:
                if row['sid'] not in by_sid:
                    by_sid[row['sid']] = dict(row, title=row['title'] or 'Новая сессия',
                                              mtime=row['updated_at'], _configured=True)
            all_rows = sorted(by_sid.values(), key=lambda row: row['mtime'], reverse=True)
            result = {'rows': all_rows[page * 8:(page + 1) * 8],
                      'has_more': len(all_rows) > (page + 1) * 8}
            _need(self._root(project) == root, 'stale')
        from _control_web_broker import redact
        rows = []
        for row in result['rows']:
            thread = None if row.get('_configured') else self._proof(root, row['sid'])
            _need(type(row['title']) is str and _identity(row['status']))
            export = {'sid': row['sid'], 'title': redact(row['title'])[:500], 'status': redact(row['status'])[:500],
                      'vendor': 'codex'}
            if row.get('needs_native_attention') is True or (thread is not None and _attention(thread)):
                export['needs_native_attention'] = True
            rows.append(export)
        if self.configured_creator is not None:
            _need(self._root(project) == root
                  and self._configured_identity() == origin_identity, 'stale')
        return {'rows': rows, 'has_more': result['has_more']}

    def _settings_capture(self):
        try:
            context = self._catalog_context()
            if self._read_context_reason(context) is not None:
                return None
            started = self._model_clock()
            if type(started) not in (int, float) or not math.isfinite(started):
                return None
            return context, started
        except Exception:
            return None

    def _settings_projection(self, thread, capture):
        if capture is None:
            return None
        from _control_web_broker import valid_session_setting
        try:
            context, started = capture
            if self._catalog_context() != context:
                return None
            now = self._model_clock()
            if type(now) not in (int, float) or not math.isfinite(now):
                return None
            elapsed = now - started
            if not 0 <= elapsed < 15:
                return None
            values = [thread.get(key) for key in ('model', 'reasoningEffort')]
            model, effort = [value if valid_session_setting(value) else None for value in values]
            if model is None and effort is None:
                return None
            age = math.floor(elapsed * 1000)
            return dict(schema=1, source='thread_read', scope='configured_or_persisted',
                        model=model, effort=effort, age_ms=age, expires_in_ms=15000-age)
        except Exception:
            return None

    @_operation
    def history(self, project, sid, cursor=None):
        return self._history(project, sid, cursor)

    def live_snapshot(self, project, sid):
        # Reuse the complete latest projection with one aggregate native budget.
        self._local.deadline = time.monotonic() + 5
        self._local.read_context = None
        try:
            self._capture_read_context()
            context = self._receipt_context()
            native = self._catalog_context() if self._has_model_context or self._explicit_model_context else None
            root = self._root(project)
            history = self._history(project, sid)
            _need(self._root(project) == root and self._receipt_context() == context)
            current = self._catalog_context() if self._has_model_context or self._explicit_model_context else None
            _need(current == native)
            from _control_web_live import owner_result
            identity = dict(root=root, sid=sid, context=context, native=native)
            result = owner_result(dict(schema=1, scope_id=_context_token(identity), history=history))
            self._remaining()
            return result
        except Exception:
            return {'error': 'unavailable'}

    def _history(self, project, sid, cursor=None):
        _need(valid_uuid(sid) and valid_cursor(cursor), 'invalid_request')
        self._capture_read_context()
        context = self._receipt_context()
        native = self._catalog_context()
        root = self._root(project)
        capture = self._settings_capture() if cursor is None else None
        thread = self._proof(root, sid)
        if capture is not None:
            try:
                if self._catalog_context() != capture[0]:
                    capture = None
            except Exception:
                capture = None
        try:
            page = self._history_page(sid, cursor, 4 if cursor is None else 8, context)
        except RPCRejected:
            if cursor is not None:
                raise
            witness = self._configured_origin('unavailable_history', project, root, sid)
            _need(witness is not None)
            _need(self._receipt_context() == context, 'stale')
            with self.receipts.namespace(root, sid, self._local.deadline) as ns:
                recent = self.receipts.recent(ns, root, sid, self._local.deadline, context['context_id'])
            _need(self._root(project) == root and self._catalog_context() == dict(witness.context), 'stale')
            result = {'history_state': 'unavailable', 'reason': 'unavailable', 'recent_sends': recent}
            settings = self._settings_projection(thread, capture)
            if settings is not None:
                result['session_settings'] = settings
            if witness.needs_native_attention:
                result['needs_native_attention'] = True
            return result
        from _control_web_broker import redact
        _need(self._receipt_context() == context, 'stale')
        with self.receipts.namespace(root, sid, self._local.deadline) as ns:
            recent = self.receipts.recent(ns, root, sid, self._local.deadline, context['context_id'])
        turns = [{'id': turn['id'], 'status': turn['status'], 'items': []}
                 for turn in page['data']]
        item_limit = 24 if cursor is None else 128
        eligible, eligible_count, scanned = [], 0, 0
        for turn_index, turn in enumerate(page['data']):
            for item_index in range(len(turn['items']) - 1, -1, -1):
                item = turn['items'][item_index]
                is_eligible = (item['type'] == 'agentMessage'
                               or item['type'] == 'userMessage'
                               and any(part['type'] == 'text' for part in item['content']))
                if is_eligible:
                    eligible_count += 1
                    if len(eligible) < item_limit:
                        eligible.append((turn_index, item_index))
                scanned += 1
                if scanned % 256 == 0:
                    self._remaining()
        self._remaining()
        result = {'turns': turns, 'next_cursor': page['nextCursor'],
                  'truncated': page['truncated'] or eligible_count > item_limit, 'recent_sends': recent}
        if _attention(thread):
            result['needs_native_attention'] = True
        settings = self._settings_projection(thread, capture)
        if settings is not None:
            result['session_settings'] = settings
        # The empty item arrays reserve exact metadata/cursor/receipt bytes.
        # Adding one item replaces [] with [item]; later items add a comma.
        base_size = len(_json(result))
        if settings is not None:
            # Reserve the maximum combined decimal width as snapshot age grows.
            base_size += 9 - len(str(settings['age_ms'])) - len(str(settings['expires_in_ms']))
        self._remaining()
        _need(base_size <= HISTORY_LIMIT)
        used_size = 0
        selected_counts = [0] * len(turns)
        selected = [[] for _ in turns]

        def mark_truncated():
            nonlocal base_size
            if not result['truncated']:
                # JSON false is one byte longer than true.
                result['truncated'] = True
                base_size -= 1

        for candidate_number, (turn_index, item_index) in enumerate(eligible):
            if candidate_number % 8 == 0:
                self._remaining()
            native_turn = page['data'][turn_index]
            native_item = native_turn['items'][item_index]
            timestamp = native_turn.get('startedAt')
            if type(timestamp) is not int or not 0 <= timestamp <= 253402300799:
                timestamp = None
            timing = {'timestamp': timestamp,
                      'time_precision': 'turn' if timestamp is not None else 'unknown'}
            item_started = native_item.get('startedAtMs')
            if type(item_started) is int and 0 <= item_started <= 253402300799999:
                timing = {'timestamp': item_started // 1000, 'time_precision': 'item'}
            if native_item['type'] == 'userMessage':
                raw_text = '\n'.join(part['text'] for part in native_item['content']
                                     if part['type'] == 'text')
                role = 'user'
            else:
                raw_text, role = native_item['text'], 'assistant'
            text = redact(raw_text)
            clipped_to_chars = len(text) > 8000
            text = text[:8000]
            if clipped_to_chars:
                mark_truncated()
            item_truncated = clipped_to_chars
            exported = {'id': native_item['id'], 'role': role,
                        'text': text, 'truncated': item_truncated, **timing}
            correlation = {'client_id': native_item['clientId']} if role == 'user' and valid_uuid(native_item.get('clientId')) else {}
            exported.update(correlation)
            encoded_item_size = len(_json(exported))
            separator_size = 1 if selected_counts[turn_index] else 0
            if base_size + used_size + separator_size + encoded_item_size <= HISTORY_LIMIT:
                selected[turn_index].append((item_index, exported))
                selected_counts[turn_index] += 1
                used_size += separator_size + encoded_item_size
                continue

            mark_truncated()
            # A partially budget-clipped message must lose at least one
            # codepoint when its own text was not previously clipped.
            max_prefix = len(text) - (0 if item_truncated else 1)
            if max_prefix >= 0 and text:
                comma_size = 1 if selected_counts[turn_index] else 0
                remaining = HISTORY_LIMIT - base_size - used_size - comma_size
                low, high, best = 0, max_prefix, -1
                steps = 0
                while low <= high:
                    steps += 1
                    if steps % 3 == 0:
                        self._remaining()
                    middle = (low + high) // 2
                    partial = {'id': native_item['id'], 'role': role,
                               'text': text[:middle], 'truncated': True, **timing, **correlation}
                    if len(_json(partial)) <= remaining:
                        best = middle
                        low = middle + 1
                    else:
                        high = middle - 1
                if best >= 0:
                    partial = {'id': native_item['id'], 'role': role,
                               'text': text[:best], 'truncated': True, **timing, **correlation}
                    selected[turn_index].append((item_index, partial))
                    selected_counts[turn_index] += 1
                    used_size += comma_size + len(_json(partial))
            # Older items have lower priority than a partially clipped one.
            break

        self._remaining()
        for turn, turn_items in zip(turns, selected):
            turn['items'] = [item for _, item in sorted(turn_items, key=lambda entry: entry[0])]
        _need(self._root(project) == root and self._receipt_context() == context, 'stale')
        if settings is not None:
            latest_settings = self._settings_projection(thread, capture)
            if latest_settings is None:
                result.pop('session_settings', None)
            else:
                result['session_settings'] = latest_settings
        encoded_result = _json(result)
        self._remaining()
        _need(len(encoded_result) <= HISTORY_LIMIT)
        _need(self._root(project) == root and self._catalog_context() == native, 'stale')
        self._history_observation = (root, sid, copy.deepcopy(native))
        return result

    @staticmethod
    def _rename_title(title):
        _need(type(title) is str, 'invalid_request')
        try:
            encoded = title.encode('utf-8')
        except UnicodeError:
            raise _DomainError('invalid_request') from None
        _need(len(title) <= 2048 and len(encoded) <= 8192
              and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in title), 'invalid_request')
        title = title.strip()
        _need(1 <= len(title) <= 160 and len(title.encode('utf-8')) <= 1024, 'invalid_request')
        return title

    def _rename_context(self):
        context = self._catalog_context()
        _need(self._catalog_reason(context) is None
              and callable(getattr(self.rpc, 'call_in_generation', None)))
        _need(self._receipt_context() == {key: context[key] for key in
              ('schema', 'vendor', 'context_kind', 'context_id')}, 'stale')
        return context

    def _rename_proof(self, project, root, sid, context):
        thread = self._send_fenced('thread/read', {'threadId': sid, 'includeTurns': False}, context).get('thread')
        _need(type(thread) is dict and valid_uuid(thread.get('id'))
              and type(thread.get('cwd')) is str and os.path.isabs(thread['cwd']))
        _need(thread['id'] == sid and canonical(thread['cwd']) == root
              and self._root(project) == root, 'stale')
        return thread

    @staticmethod
    def _native_name(thread):
        name = thread.get('name')
        _need(type(name) is str and bool(name.strip()))
        try:
            name.encode('utf-8')
        except UnicodeError:
            raise _DomainError('unavailable') from None
        return name

    @staticmethod
    def _rename_result(record, name=None):
        result = {'operation_id': record['operation_id'],
                  'status': 'accepted' if record['status'] == 'accepted' else 'delivery_unknown'}
        if record['status'] == 'accepted':
            from _control_web_broker import redact
            _need(type(name) is str)
            result['title'] = redact(name)[:500]
        return result

    def _rename_replay(self, record, digest, project, root, sid, context):
        _need(record['digest'] == digest, 'invalid_request')
        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
        if record['status'] == 'accepted':
            thread = self._rename_proof(project, root, sid, context)
            return self._rename_result(record, self._native_name(thread))
        return self._rename_result(record)

    @_operation
    def rename(self, project, sid, operation_id, title):
        _need(valid_project(project) and valid_uuid(sid) and valid_uuid(operation_id), 'invalid_request')
        title = self._rename_title(title)
        root = self._root(project)
        self._proof(root, sid)
        context = self._rename_context()
        digest = _context_token({'kind': 'session_rename', 'context_id': context['context_id'],
                                 'root': root, 'sid': sid, 'title': title})
        with self.renames.locked(self._local.deadline) as base:
            record, _ = self.renames.lookup(base, context['context_id'], root, sid, operation_id, self._local.deadline)
            if record is not None:
                return self._rename_replay(record, digest, project, root, sid, context)
        reserved = False
        try:
            with self.renames.locked(self._local.deadline, create=True) as base:
                record, _ = self.renames.lookup(base, context['context_id'], root, sid, operation_id, self._local.deadline)
                if record is not None:
                    return self._rename_replay(record, digest, project, root, sid, context)
                self.renames.capacity(base, self._local.deadline)
                self._rename_proof(project, root, sid, context)
                _need(self._catalog_context() == context, 'stale')
                record = {'schema': 1, 'kind': 'session_rename', 'context_id': context['context_id'],
                          'root': root, 'sid': sid, 'operation_id': operation_id, 'digest': digest,
                          'title_hash': hashlib.sha256(title.encode('utf-8')).hexdigest(),
                          'status': 'unknown', 'created': time.time_ns()}
                # Any uncertainty publishing this reserve forbids another set.
                reserved = True
                self.renames.publish(base, record, self._local.deadline)
                _, before = self.renames.lookup(base, context['context_id'], root, sid, operation_id, self._local.deadline)
                _need(self._root(project) == root, 'stale')
                response = self._send_fenced('thread/name/set', {'threadId': sid, 'name': title}, context)
                _need(response == {})
                thread = self._rename_proof(project, root, sid, context)
                name = self._native_name(thread)
                _need(name == title)
                record['status'] = 'accepted'
                self.renames.publish(base, record, self._local.deadline, before)
                self._summary_revision += 1
                result = self._rename_result(record, name)
            return result
        except Exception:
            if reserved:
                return {'operation_id': operation_id, 'status': 'delivery_unknown'}
            raise

    @_operation
    def rename_status(self, project, sid, operation_id):
        _need(valid_project(project) and valid_uuid(sid) and valid_uuid(operation_id), 'invalid_request')
        root = self._root(project)
        self._proof(root, sid)
        context = self._rename_context()
        with self.renames.locked(self._local.deadline) as base:
            record, before = self.renames.lookup(base, context['context_id'], root, sid, operation_id, self._local.deadline)
            _need(record is not None, 'stale')
            thread = self._rename_proof(project, root, sid, context)
            name = self._native_name(thread)
            if record['status'] == 'unknown' and hashlib.sha256(name.encode('utf-8')).hexdigest() == record['title_hash']:
                record['status'] = 'accepted'
                self.renames.publish(base, record, self._local.deadline, before)
                self._summary_revision += 1
            return self._rename_result(record, name)

    @_operation
    def capabilities(self, project, sid):
        _need(valid_uuid(sid), 'invalid_request')
        root = self._root(project)
        self._proof(root, sid)
        context = self._catalog_context()
        _need(self._read_context_reason(context) is None)
        self._capture_read_context(context)
        version = context['native_version']
        reviewed = version in SUPPORTED_NATIVE_VERSIONS
        operations = {'sessions_read': dict(supported=True, reason=None),
                      'history_read': dict(supported=True, reason=None) if self._history_observation == (root, sid, context) else dict(supported=None, reason='not_observed')}
        for name in ('model_selection', 'send', 'create', 'rename', 'queue'):
            operations[name] = (dict(supported=False, reason='unsupported_native_version') if not reviewed else
                dict(supported=False, reason='unsupported_operation') if name == 'queue' and version == '0.160.0' else
                dict(supported=None, reason='not_observed') if name == 'queue' else dict(supported=True, reason=None))
        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
        return dict(schema=1, native_version=version, version_source='initialize_reported',
                    version_review='unknown' if version is None else 'reviewed' if reviewed else 'unreviewed',
                    read_status='compatible', operations=operations)

    @staticmethod
    def _queue_unavailable():
        return dict(schema=1, vendor='codex', supported=False, reason='unsupported_queue',
                    rows=[], partial=False, send_now_supported=False, active_turn_id=None,
                    send_now_reason='unsupported_queue', recovery=[])

    def _queue_scope(self, project, sid):
        _need(valid_uuid(sid), 'invalid_request')
        root = self._root(project)
        thread = self._proof(root, sid)
        context = self._catalog_context()
        reason = self._catalog_reason(context)
        if reason == 'unverified_context':
            _need(False)
        if reason or context['native_version'] != '0.161.0' or not callable(getattr(self.rpc, 'call_in_generation', None)):
            return root, thread, None
        thread = self._queue_proof(project, root, sid, context)
        return root, thread, context

    def _queue_proof(self, project, root, sid, context, method='thread/read'):
        params = dict(threadId=sid)
        params['excludeTurns' if method == 'thread/resume' else 'includeTurns'] = method == 'thread/resume'
        thread = self._send_fenced(method, params, context).get('thread')
        _need(type(thread) is dict and thread.get('id') == sid and type(thread.get('cwd')) is str
              and os.path.isabs(thread['cwd']) and canonical(thread['cwd']) == root, 'stale')
        status = thread.get('status')
        _need(type(status) is dict and status.get('type') in ('idle', 'active', 'notLoaded', 'systemError'))
        if status['type'] == 'active':
            _need(type(status.get('activeFlags')) is list and all(type(flag) is str for flag in status['activeFlags']))
        _need(method != 'thread/resume' or status['type'] != 'notLoaded', 'stale')
        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
        return thread

    @staticmethod
    def _queue_text(row):
        from _control_web_broker import valid_queue_id
        _need(type(row) is dict and set(row) == {'id', 'clientUserMessageId', 'input'}
              and valid_queue_id(row['id']) and valid_queue_id(row['clientUserMessageId'])
              and type(row['input']) is list and 0 < len(row['input']) <= 256)
        texts = []
        for part in row['input']:
            _need(type(part) is dict and set(part) in ({'type', 'text'}, {'type', 'text', 'text_elements'})
                  and part['type'] == 'text' and type(part['text']) is str
                  and part.get('text_elements', []) == [])
            texts.append(part['text'])
        text = '\n'.join(texts)
        _need(0 < len(text) <= 16000)
        text.encode('utf-8')
        return text

    @staticmethod
    def _queue_digest(context_id, root, sid, kind, value):
        return hashlib.sha256(_json(dict(context_id=context_id, root=root, sid=sid,
                                         kind=kind, value=value))).hexdigest()

    def _queue_listing(self, project, root, sid, context):
        from _control_web_broker import redact, queue_result
        rows, texts, ids, clients, cursors = [], {}, set(), set(), set()
        cursor, partial, total = None, False, 0
        for index in range(4):
            params = dict(threadId=sid, limit=64)
            if cursor is not None:
                params['cursor'] = cursor
            try:
                page = self._send_fenced('thread/queue/list', params, context)
            except RPCRejected as error:
                if error.rpc_code == -32601:
                    raise _DomainError('unsupported_queue') from None
                raise
            _need(set(page) in ({'data'}, {'data', 'nextCursor'})
                  and type(page['data']) is list and len(page['data']) <= 64
                  and valid_cursor(page.get('nextCursor')))
            for row in page['data']:
                text = self._queue_text(row)
                _need(row['id'] not in ids and row['clientUserMessageId'] not in clients, 'conflict')
                ids.add(row['id']); clients.add(row['clientUserMessageId'])
                total += len(text.encode('utf-8'))
                _need(total <= 4 * 1024 * 1024)
                texts[row['id']] = text
                rows.append(dict(queued_submission_id=row['id'], message_id=row['clientUserMessageId'],
                                 text=redact(text), state='queued'))
            cursor = page.get('nextCursor')
            if cursor is None:
                break
            _need(cursor not in cursors, 'conflict'); cursors.add(cursor)
            partial = index == 3
        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
        result = queue_result(dict(schema=1, vendor='codex', supported=True, reason=None,
                     rows=rows, partial=partial, send_now_supported=False))
        _need('error' not in result)
        return result, texts

    @_operation
    def queue(self, project, sid):
        root, _, context = self._queue_scope(project, sid)
        if context is None:
            return self._queue_unavailable()
        try:
            result = self._queue_listing(project, root, sid, context)[0]
            with self.receipts.namespace(root, sid, self._local.deadline) as ns:
                records = self._transfer_records(ns, root, sid)
                recovery = []
                for record in records:
                    if record.get('context_id') != context['context_id']:
                        continue
                    try:
                        self._transfer_reconcile(ns, record, project, root, sid, context)
                    except Exception:
                        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
                    if record['status'] in ('held', 'delivery_unknown'):
                        recovery.append(dict(action_id=record['message_id'], queued_submission_id=record['queued_submission_id'],
                            text=record['snapshot_text'], status=record['status'], reason=record['reason']))
            target_reason = 'inactive_turn'
            try:
                target = self._queue_active_turn(project, root, sid, context)
            except Exception:
                _need(self._root(project) == root and self._catalog_context() == context, 'stale')
                target, target_reason = None, 'unavailable'
            result.update(active_turn_id=target, send_now_supported=target is not None,
                send_now_reason=None if target else target_reason, recovery=recovery)
            from _control_web_broker import queue_result
            _need(self._root(project) == root and self._catalog_context() == context, 'stale')
            return queue_result(result)
        except RPCRejected as error:
            if error.rpc_code == -32601:
                return self._queue_unavailable()
            raise
        except _DomainError as error:
            if error.code == 'unsupported_queue':
                return self._queue_unavailable()
            if error.code == 'conflict':
                raise _DomainError('unavailable') from None
            raise

    def _queue_active_turn(self, project, root, sid, context):
        thread = self._queue_proof(project, root, sid, context)
        if thread['status']['type'] != 'active':
            return None
        page = self._page(sid, None)
        active = [turn['id'] for turn in page['data'] if turn['status'] == 'inProgress']
        _need(len(active) <= 1 and len({turn['id'] for turn in page['data']}) == len(page['data']))
        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
        return active[0] if active else None

    def _transfer_records(self, ns, root, sid):
        records = [self.receipts.read(ns, root, sid, mid, self._local.deadline)
                   for mid in self.receipts.names(ns, self._local.deadline)]
        _need(all(record is not None for record in records))
        return [record for record in records if record.get('kind') == 'queue_transfer']

    def _transfer_finish(self, ns, record, status, turn_id=None, reason=None):
        committed = dict(record, status=status, turn_id=turn_id, reason=reason)
        if status in ('accepted', 'changed'):
            committed.update(snapshot_text=None, phase='terminal')
        self.receipts.write(ns, committed, self._local.deadline)
        record.update(committed)
        # Preserve the original Control enqueue UUID's non-replayable receipt.
        if status == 'accepted' and valid_uuid(record['client_id']):
            original = self.receipts.read(ns, record['root'], record['sid'], record['client_id'],
                                         self._local.deadline, record['context_id'])
            if (original is not None and original.get('kind') == 'queue_enqueue'
                    and original['queued_submission_id'] == record['queued_submission_id']):
                original.update(status='accepted', turn_id=turn_id, reason=None)
                self.receipts.write(ns, original, self._local.deadline)
        return self.receipts.result(record)

    def _transfer_reconcile(self, ns, record, project, root, sid, context):
        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
        if record['status'] in ('accepted', 'changed') or record['phase'] != 'steer_reserved':
            return self.receipts.result(record)
        cursor, seen, matches, conflict = None, set(), [], False
        for _ in range(8):
            page = self._page(sid, cursor)
            for turn in page['data']:
                for item in turn['items']:
                    if item['type'] == 'userMessage' and item.get('clientId') == record['message_id']:
                        parts = item['content']
                        text = '\n'.join(part['text'] for part in parts if part['type'] == 'text')
                        if (turn['id'] != record['expected_turn_id'] or any(part['type'] != 'text' for part in parts)
                                or text != record['snapshot_text']):
                            conflict = True
                        else:
                            matches.append(turn['id'])
            cursor = page['nextCursor']
            if cursor is None:
                break
            _need(cursor not in seen);seen.add(cursor)
        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
        if len(matches) == 1 and not conflict:
            return self._transfer_finish(ns, record, 'accepted', matches[0])
        if conflict or len(matches) > 1:
            return self._transfer_finish(ns, record, 'delivery_unknown', reason='conflict')
        # Neither absence nor a native rejection authorizes another mutation.
        return self.receipts.result(record)

    @_operation
    def send_queued_now(self, project, sid, queued_submission_id, action_id, snapshot_text, expected_turn_id):
        from _control_web_broker import valid_queue_id
        _need(valid_uuid(action_id) and valid_queue_id(queued_submission_id) and valid_queue_id(expected_turn_id)
              and type(snapshot_text) is str and 0 < len(snapshot_text) <= 16000 and bool(snapshot_text.strip()), 'invalid_request')
        snapshot_text.encode('utf-8')
        root, _, context = self._queue_scope(project, sid)
        _need(context is not None, 'unsupported_queue')
        digest = self._queue_digest(context['context_id'], root, sid, 'queue_transfer',
                                    [queued_submission_id, snapshot_text, expected_turn_id])
        with self.receipts.namespace(root, sid, self._local.deadline, create=True) as ns:
            records = self._transfer_records(ns, root, sid)
            record = self.receipts.read(ns, root, sid, action_id, self._local.deadline, context['context_id'])
            if record is not None:
                _need(record.get('kind') == 'queue_transfer' and record['digest'] == digest, 'invalid_request')
                return self._transfer_reconcile(ns, record, project, root, sid, context)
            retained = [row for row in records if row['snapshot_text'] is not None]
            _need(len(retained) < 64 and sum(len(row['snapshot_text'].encode('utf-8')) for row in retained)
                  + len(snapshot_text.encode('utf-8')) <= 4 * 1024 * 1024)
            _need(len(self.receipts.names(ns, self._local.deadline, reserve=True)) < RECEIPT_LIMIT)
            listing, native_texts = self._queue_listing(project, root, sid, context)
            row = next((row for row in listing['rows'] if row['queued_submission_id'] == queued_submission_id), None)
            _need(row is not None, 'stale')
            if valid_uuid(row['message_id']):
                original = self.receipts.read(ns, root, sid, row['message_id'], self._local.deadline, context['context_id'])
                if (original is not None and original.get('kind') == 'queue_enqueue'
                        and original['queued_submission_id'] is None and not listing['partial']
                        and original['digest'] == self._queue_digest(context['context_id'], root, sid,
                            'queue_enqueue', native_texts[queued_submission_id])):
                    original['queued_submission_id'] = queued_submission_id
                    self.receipts.write(ns, original, self._local.deadline)
            record = dict(schema=4, kind='queue_transfer', context_id=context['context_id'], root=root, sid=sid,
                message_id=action_id, digest=digest, status='delivery_unknown', turn_id=None, created=time.time_ns(),
                queued_submission_id=queued_submission_id, expected_turn_id=expected_turn_id, client_id=row['message_id'],
                snapshot_text=snapshot_text, phase='intent', reason=None)
            _need(sum(len(_json(item)) for item in retained) + len(_json(record)) <= 4 * 1024 * 1024)
            # A known changed target is terminal, with no native deletion or payload retention.
            if self._queue_active_turn(project, root, sid, context) != expected_turn_id:
                return self._transfer_finish(ns, record, 'changed', reason='target_changed')
            self.receipts.write(ns, record, self._local.deadline)
            try:
                response = self._send_fenced('thread/queue/delete',
                    dict(threadId=sid, queuedSubmissionId=queued_submission_id), context)
                _need(set(response) == {'deleted'} and type(response['deleted']) is bool)
                if not response['deleted']:
                    return self._transfer_finish(ns, record, 'changed')
                record.update(status='held', phase='held')
                self.receipts.write(ns, record, self._local.deadline)
            except Exception:
                return self.receipts.result(record if record['phase'] == 'intent' else
                    dict(record, status='delivery_unknown'))
            try:
                if self._queue_active_turn(project, root, sid, context) != expected_turn_id:
                    return self._transfer_finish(ns, record, 'held', reason='target_changed')
            except Exception:
                return self._transfer_finish(ns, record, 'held', reason='unavailable')
            # This reservation permanently forbids replay after a crash/ACK loss.
            record.update(status='delivery_unknown', phase='steer_reserved')
            self.receipts.write(ns, record, self._local.deadline)
            try:
                response = self._send_fenced('turn/steer', dict(threadId=sid, expectedTurnId=expected_turn_id,
                    input=[dict(type='text', text=snapshot_text)], clientUserMessageId=action_id), context)
                _need(set(response) == {'turnId'} and response['turnId'] == expected_turn_id)
                return self._transfer_finish(ns, record, 'accepted', expected_turn_id)
            except Exception:
                return self.receipts.result(record)

    def _queue_record(self, context, root, sid, mid, kind, value):
        return dict(schema=3, kind=kind, context_id=context['context_id'], root=root, sid=sid,
                    message_id=mid, digest=self._queue_digest(context['context_id'], root, sid, kind, value),
                    status='delivery_unknown', turn_id=None, created=time.time_ns(), reason=None,
                    queued_submission_id=value if kind == 'queue_cancel' else None)

    def _queue_reconcile(self, ns, record, project, root, sid, context):
        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
        if record['status'] == 'accepted':
            return self.receipts.result(record)
        for mid in self.receipts.names(ns, self._local.deadline):
            cancel = self.receipts.read(ns, root, sid, mid, self._local.deadline)
            if (cancel.get('kind') == 'queue_cancel' and cancel['context_id'] == context['context_id']
                    and cancel['status'] == 'cancelled' and record['queued_submission_id'] is not None
                    and cancel['queued_submission_id'] == record['queued_submission_id']):
                _need(self._root(project) == root and self._catalog_context() == context, 'stale')
                return dict(status='cancelled', message_id=record['message_id'], queued_submission_id=record['queued_submission_id'])
        for transfer in self._transfer_records(ns, root, sid):
            if transfer['context_id'] == context['context_id'] and transfer['client_id'] == record['message_id'] and transfer['queued_submission_id'] == record['queued_submission_id'] and transfer['status'] != 'changed':
                self._transfer_reconcile(ns, transfer, project, root, sid, context)
                if transfer['status'] == 'accepted':
                    record.update(status='accepted', turn_id=transfer['turn_id'], reason=None)
                    self.receipts.write(ns, record, self._local.deadline)
                    return self.receipts.result(record)
                if transfer['status'] == 'held' and transfer['phase'] == 'held':
                    return dict(status='held', message_id=record['message_id'], queued_submission_id=record['queued_submission_id'], turn_id=None, reason=transfer['reason'])
                return dict(status='delivery_unknown', message_id=record['message_id'], queued_submission_id=record['queued_submission_id'])
        matches, conflict, cursor, seen = [], False, None, set()
        for _ in range(8):
            _need(self._catalog_context() == context, 'stale')
            page = self._page(sid, cursor)
            _need(self._catalog_context() == context, 'stale')
            for turn in page['data']:
                for item in turn['items']:
                    if item['type'] == 'userMessage' and item.get('clientId') == record['message_id']:
                        parts = item['content']
                        text = '\n'.join(part['text'] for part in parts if part['type'] == 'text')
                        digest = self._queue_digest(record['context_id'], root, sid, 'queue_enqueue', text)
                        if any(part['type'] != 'text' for part in parts) or digest != record['digest']:
                            conflict = True
                        else:
                            matches.append(turn['id'])
            cursor = page['nextCursor']
            if cursor is None:
                break
            _need(cursor not in seen);seen.add(cursor)
        if len(matches) == 1 and not conflict:
            record.update(status='accepted', turn_id=matches[0], reason=None)
        elif matches or conflict:
            record.update(status='delivery_unknown', reason='conflict')
        else:
            record.update(status='delivery_unknown', reason=None)
            try:
                _need(context['native_version'] == '0.161.0', 'unsupported_queue')
                listing, texts = self._queue_listing(project, root, sid, context)
                rows = [row for row in listing['rows'] if row['message_id'] == record['message_id']]
                if rows:
                    row = rows[0]
                    digest = self._queue_digest(record['context_id'], root, sid, 'queue_enqueue', texts[row['queued_submission_id']])
                    if digest != record['digest']:
                        record.update(status='delivery_unknown', reason='conflict')
                    else:
                        record.update(status='queued', queued_submission_id=row['queued_submission_id'], reason=None)
            except _DomainError as error:
                if error.code == 'stale':
                    raise
                if error.code == 'conflict':
                    record.update(status='delivery_unknown', reason='conflict')
                else:
                    record['reason'] = error.code if error.code == 'unsupported_queue' else 'unavailable'
            except Exception:
                record['reason'] = 'unavailable'
        _need(self._root(project) == root and self._catalog_context() == context, 'stale')
        self.receipts.write(ns, record, self._local.deadline)
        return self.receipts.result(record)

    @_operation
    def enqueue(self, project, sid, message_id, text, selection=None):
        _need(valid_uuid(message_id) and type(text) is str and 0 < len(text) <= 16000 and bool(text.strip()), 'invalid_request')
        text.encode('utf-8')
        _need(selection is None, 'queue_unsupported_selection')
        root, thread, context = self._queue_scope(project, sid)
        _need(context is not None, 'unsupported_queue')
        with self.receipts.namespace(root, sid, self._local.deadline, create=True) as ns:
            record = self.receipts.read(ns, root, sid, message_id, self._local.deadline, context['context_id'])
            digest = self._queue_digest(context['context_id'], root, sid, 'queue_enqueue', text)
            if record is not None:
                _need(record.get('kind') == 'queue_enqueue' and record['digest'] == digest, 'invalid_request')
                return self._queue_reconcile(ns, record, project, root, sid, context)
            _need(len(self.receipts.names(ns, self._local.deadline, reserve=True)) < RECEIPT_LIMIT)
            unloaded = type(thread.get('status')) is dict and thread['status'].get('type') == 'notLoaded'
            if not unloaded:
                try:self._queue_listing(project, root, sid, context)
                except _DomainError as error:raise _DomainError('unavailable' if error.code == 'conflict' else error.code) from None
            record = self._queue_record(context, root, sid, message_id, 'queue_enqueue', text)
            self.receipts.write(ns, record, self._local.deadline)
            try:
                if unloaded:
                    self._queue_proof(project, root, sid, context, 'thread/resume')
                    self._configured_origin('loaded_origin', project, root, sid)
                    self._queue_listing(project, root, sid, context)
                self._queue_proof(project, root, sid, context)
                response = self._send_fenced('thread/queue/add', dict(threadId=sid,
                    input=[dict(type='text', text=text)], clientUserMessageId=message_id), context)
                _need(set(response) == {'queuedSubmission'})
                row = response['queuedSubmission'];queued_text = self._queue_text(row)
                _need(row['clientUserMessageId'] == message_id and queued_text == text)
                record.update(status='queued', queued_submission_id=row['id'], reason=None)
                self.receipts.write(ns, record, self._local.deadline)
                self._summary_revision += 1
                return self.receipts.result(record)
            except Exception:
                return dict(status='delivery_unknown', message_id=message_id, queued_submission_id=None)

    @_operation
    def cancel_queued(self, project, sid, queued_submission_id, action_id):
        _need(_identity(queued_submission_id) and valid_uuid(action_id), 'invalid_request')
        root, _, context = self._queue_scope(project, sid)
        _need(context is not None, 'unsupported_queue')
        with self.receipts.namespace(root, sid, self._local.deadline, create=True) as ns:
            record = self.receipts.read(ns, root, sid, action_id, self._local.deadline, context['context_id'])
            digest = self._queue_digest(context['context_id'], root, sid, 'queue_cancel', queued_submission_id)
            if record is not None:
                _need(record.get('kind') == 'queue_cancel' and record['digest'] == digest, 'invalid_request')
                return self.receipts.result(record)
            try:listing, _ = self._queue_listing(project, root, sid, context)
            except _DomainError as error:raise _DomainError('unavailable' if error.code == 'conflict' else error.code) from None
            _need(any(row['queued_submission_id'] == queued_submission_id for row in listing['rows']), 'stale')
            _need(len(self.receipts.names(ns, self._local.deadline, reserve=True)) < RECEIPT_LIMIT)
            record = self._queue_record(context, root, sid, action_id, 'queue_cancel', queued_submission_id)
            self.receipts.write(ns, record, self._local.deadline)
            try:
                self._queue_proof(project, root, sid, context)
                response = self._send_fenced('thread/queue/delete', dict(threadId=sid, queuedSubmissionId=queued_submission_id), context)
                _need(set(response) == {'deleted'} and type(response['deleted']) is bool)
                record['status'] = 'cancelled' if response['deleted'] else 'changed'
                self.receipts.write(ns, record, self._local.deadline)
                return self.receipts.result(record)
            except Exception:
                return dict(status='delivery_unknown', message_id=action_id, queued_submission_id=queued_submission_id)

    @_operation
    def send(self, project, sid, message_id, text, selection=None):
        _need(valid_uuid(sid) and valid_uuid(message_id) and type(text) is str
              and 0 < len(text) <= 16000 and bool(text.strip()), 'invalid_request')
        _need(selection is None or _valid_selection(selection), 'invalid_request')
        selection = copy.deepcopy(selection)
        context = self._receipt_context()
        model_context = self._catalog_context() if selection is not None else None
        if model_context is not None:
            _need(model_context.get('context_id') == context['context_id'], 'stale')
        root = self._root(project)
        self._proof(root, sid)
        if self._has_model_context or self._explicit_model_context:
            _need(self._catalog_reason(self._catalog_context()) is None)
        _need(self._receipt_context() == context, 'stale')
        # Existing UUID lookup precedes live catalog validation: stored wire
        # mapping is the only authority for an exact replay.
        with self.receipts.namespace(root, sid, self._local.deadline) as ns:
            record = self.receipts.read(ns, root, sid, message_id, self._local.deadline, context['context_id'])
            if record is not None:
                return self._send_replay(record, context, root, sid, text, selection)
        origin = self._configured_origin('loaded_origin', project, root, sid)
        choice = self._send_selection(selection, model_context) if selection is not None else None
        digest = _receipt_digest(context['context_id'], root, sid, text, choice)
        with self.receipts.namespace(root, sid, self._local.deadline, create=True) as ns:
            record = self.receipts.read(ns, root, sid, message_id, self._local.deadline, context['context_id'])
            if record is not None:
                return self._send_replay(record, context, root, sid, text, selection)
            _need(len(self.receipts.names(ns, self._local.deadline, reserve=True)) < RECEIPT_LIMIT)
            if origin is not None:
                fresh_origin = self._configured_origin('loaded_origin', project, root, sid)
                _need(fresh_origin is not None and fresh_origin == origin, 'stale')
            if selection is None and origin is None:
                self._proof(root, sid, 'thread/resume')
            elif selection is not None:
                choice = self._send_selection(selection, model_context)
            _need(self._root(project) == root, 'stale')
            _need(self._receipt_context() == context, 'stale')
            self._remaining()
            record = {'schema': 2, 'context_id': context['context_id'], 'selection': choice,
                      'root': root, 'sid': sid, 'message_id': message_id, 'digest': digest,
                      'status': 'delivery_unknown', 'turn_id': None, 'created': time.time_ns()}
            self.receipts.write(ns, record, self._local.deadline)
            try:
                params = {'threadId': sid, 'input': [{'type': 'text', 'text': text}],
                          'clientUserMessageId': message_id}
                if choice is not None and origin is None:
                    thread = self._send_fenced('thread/resume', {'threadId': sid, 'excludeTurns': True}, model_context).get('thread')
                    _need(type(thread) is dict and thread.get('id') == sid
                          and type(thread.get('cwd')) is str and os.path.isabs(thread['cwd'])
                          and canonical(thread['cwd']) == root, 'stale')
                    _need(self._root(project) == root, 'stale')
                if choice is not None:
                    params.update(model=choice['wire_model'], effort=choice['effort'])
                if origin is not None:
                    _need(self._root(project) == root
                          and self._catalog_context() == dict(origin.context), 'stale')
                    response = self._send_fenced('turn/start', params, dict(origin.context))
                elif choice is not None:
                    response = self._send_fenced('turn/start', params, model_context)
                else:
                    response = self._rpc('turn/start', params)
                turn = response.get('turn')
                _need(type(turn) is dict and _identity(turn.get('id')))
                if origin is not None:
                    _need(self._root(project) == root
                          and self._catalog_context() == dict(origin.context), 'stale')
                record.update(status='accepted', turn_id=turn['id'])
                self._summary_revision += 1
                self.receipts.write(ns, record, self._local.deadline)
            except Exception:
                # Reserve remains durable. Server errors, timeout and failed ACK
                # persistence never authorize automatic turn/start repetition.
                return {'status': 'delivery_unknown', 'message_id': message_id, 'turn_id': None}
            return self.receipts.result(record)

    def _send_replay(self, record, context, root, sid, text, selection):
        _need(record.get('schema') != 3, 'invalid_request')
        if 'schema' not in record:
            _need(selection is None, 'invalid_request')
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        else:
            choice = record['selection']
            public = None if choice is None else {key: choice[key] for key in ('catalog_id', 'model_id', 'effort')}
            _need(public == selection, 'invalid_request')
            digest = _receipt_digest(context['context_id'], root, sid, text, choice)
        _need(record['digest'] == digest, 'invalid_request')
        _need(self._receipt_context() == context, 'stale')
        return self.receipts.result(record)

    @_operation
    def send_status(self, project, sid, message_id):
        _need(valid_uuid(sid) and valid_uuid(message_id), 'invalid_request')
        context = self._receipt_context()
        root = self._root(project)
        self._proof(root, sid)
        _need(self._receipt_context() == context, 'stale')
        with self.receipts.namespace(root, sid, self._local.deadline) as ns:
            record = self.receipts.read(ns, root, sid, message_id, self._local.deadline, context['context_id'])
            _need(record is not None, 'stale')
            if record.get('kind') == 'queue_transfer':
                return self._transfer_reconcile(ns, record, project, root, sid, self._catalog_context())
            if record.get('kind') == 'queue_enqueue':
                return self._queue_reconcile(ns, record, project, root, sid, self._catalog_context())
            if record['status'] != 'delivery_unknown' or record.get('kind') == 'queue_cancel':
                return self.receipts.result(record)
            cursor, seen = None, set()
            for _ in range(8):
                if time.monotonic() >= self._local.deadline:
                    break
                page = self._page(sid, cursor)
                _need(self._receipt_context() == context, 'stale')
                for turn in page['data']:
                    if any(item['type'] == 'userMessage' and item.get('clientId') == message_id
                           for item in turn['items']):
                        record.update(status='accepted', turn_id=turn['id'])
                        self._summary_revision += 1
                        self.receipts.write(ns, record, self._local.deadline)
                        return self.receipts.result(record)
                cursor = page['nextCursor']
                if cursor is None:
                    break
                _need(cursor not in seen)
                seen.add(cursor)
            return self.receipts.result(record)


class InteractiveRPC:
    """One receiver per connection; never responds to native server requests."""
    METHODS = {'initialize', 'thread/read', 'thread/list', 'thread/turns/list', 'thread/items/list', 'thread/resume', 'turn/start', 'model/list', 'thread/name/set', 'thread/start', 'thread/loaded/list', 'thread/queue/list', 'thread/queue/add', 'thread/queue/delete', 'turn/steer'}

    def __init__(self, socket_path, timeout=25):
        if type(socket_path) is not str or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 55:
            raise ValueError('invalid RPC configuration')
        self.socket_path, self.timeout = socket_path, timeout
        self._lock = threading.RLock()
        self._connect_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._ws = None
        self._generation = 0
        self._context_generation = 0
        self._native_version = None
        self._model_context_id = _context_token({'schema': 1, 'vendor': 'codex',
            'context_kind': 'legacy_unbound', 'owner_uid': os.getuid(),
            'socket_alias': os.path.abspath(socket_path)})
        self._pending = {}
        self._closed = False

    @property
    def generation(self):
        with self._lock:
            return self._generation

    def _fail(self, ws, generation):
        with self._lock:
            if self._ws is not ws or self._generation != generation:
                return
            self._ws = None
            self._native_version = None
            for waiter in self._pending.values():
                waiter['error'] = RuntimeError('RPC connection unavailable')
                waiter['event'].set()
            self._pending.clear()
        try:
            ws.close()
        except Exception:
            pass

    def _expire(self, ws, generation):
        # Shutdown the captured owned socket even if dispatch holds _lock. This
        # cannot close a newly connected socket, and wakes a blocked sync send.
        try:
            ws.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._fail(ws, generation)

    def _receive(self, ws, generation):
        try:
            while True:
                value = json.loads(ws.recv(), object_pairs_hook=_pairs)
                if type(value) is not dict:
                    raise ValueError('invalid response')
                # Both callbacks and notifications are observational only.
                if 'method' in value:
                    if 'id' not in value and value['method'] in ('account/updated', 'config/updated'):
                        with self._lock:
                            if self._ws is not ws or self._generation != generation:
                                return
                            self._context_generation += 1
                    continue
                if type(value.get('id')) is not str:
                    continue
                with self._lock:
                    if self._ws is not ws or self._generation != generation:
                        return
                    waiter = self._pending.pop(value['id'], None)
                    if waiter is None:
                        continue
                    error = value.get('error')
                    if ('error' in value and 'result' not in value and type(error) is dict
                            and set(error) in ({'code', 'message'}, {'code', 'message', 'data'})
                            and type(error['code']) is int and type(error['message']) is str):
                        waiter['error'] = RPCRejected('RPC server rejected request (code ' + str(error['code']) + ')', error['code'])
                    elif 'error' not in value and type(value.get('result')) is dict:
                        waiter['result'] = value['result']
                    else:
                        waiter['error'] = RuntimeError('RPC invalid response')
                    waiter['event'].set()
        except Exception:
            self._fail(ws, generation)

    def _method_allowed(self, method):
        if method == 'initialize' or method in READ_METHODS:
            return True
        if method.startswith('thread/queue/') or method == 'turn/steer':
            return self._native_version == '0.161.0'
        return self._native_version in SUPPORTED_NATIVE_VERSIONS

    def _request(self, ws, generation, method, params, deadline, *, context_generation=None):
        waiter = {'event': threading.Event()}
        request_id = str(uuid.uuid4())
        with self._lock:
            if (self._ws is not ws or self._generation != generation or len(self._pending) >= 64
                    or (context_generation is not None and self._context_generation != context_generation)
                    or not self._method_allowed(method)):
                raise RuntimeError('RPC unavailable')
            self._pending[request_id] = waiter
        timer = threading.Timer(max(0, deadline - time.monotonic()), self._expire, args=(ws, generation))
        timer.daemon = True
        timer.start()
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._send_lock.acquire(timeout=max(0, remaining)):
                raise TimeoutError('RPC deadline exceeded')
            try:
                if time.monotonic() >= deadline:
                    raise TimeoutError('RPC deadline exceeded')
                payload = _json({'id': request_id, 'method': method, 'params': params}).decode('utf-8')
                with self._lock:
                    if (self._closed or self._ws is not ws or self._generation != generation
                            or context_generation is not None and self._context_generation != context_generation
                            or not self._method_allowed(method)):
                        raise RuntimeError('RPC generation unavailable')
                    ws.send(payload)
            finally:
                self._send_lock.release()
            if not waiter['event'].wait(max(0, deadline - time.monotonic())):
                raise TimeoutError('RPC deadline exceeded')
            if 'error' in waiter:
                raise waiter['error']
            return waiter['result']
        except RPCRejected:
            raise
        except Exception:
            self._fail(ws, generation)
            raise RuntimeError('RPC operation unavailable') from None
        finally:
            timer.cancel()
            with self._lock:
                self._pending.pop(request_id, None)

    def _socket_target(self, deadline):
        _budget(deadline)
        alias = os.lstat(self.socket_path)
        _budget(deadline)
        if alias.st_uid != os.getuid() or not (stat.S_ISSOCK(alias.st_mode) or stat.S_ISLNK(alias.st_mode)):
            raise ValueError('RPC socket ownership refused')
        target = os.path.realpath(self.socket_path, strict=True)
        _budget(deadline)
        info = os.lstat(target)
        _budget(deadline)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('RPC socket ownership refused')
        return (alias.st_dev, alias.st_ino), target, (info.st_dev, info.st_ino)

    def _connect(self, deadline):
        if not self._connect_lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise RuntimeError('RPC connection unavailable')
        try:
            with self._lock:
                if self._closed:
                    raise RuntimeError('RPC closed')
                if self._ws is not None:
                    return self._ws, self._generation
            from websockets.sync.client import unix_connect
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('RPC connection unavailable')
            ws = None
            try:
                before = self._socket_target(deadline)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('RPC deadline exceeded')
                ws = unix_connect(before[1], uri='ws://localhost', open_timeout=remaining,
                                  close_timeout=1, max_size=4 * 1024 * 1024)
                after = self._socket_target(deadline)
                if before != after:
                    raise ValueError('RPC socket changed')
                _budget(deadline)
                _, peer_uid, _ = struct.unpack('3i', ws.socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                _budget(deadline)
                if peer_uid != os.getuid():
                    raise ValueError('RPC peer ownership refused')
            except Exception:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
                raise RuntimeError('RPC connection unavailable') from None
            with self._lock:
                if self._closed:
                    ws.close()
                    raise RuntimeError('RPC closed')
                self._generation += 1
                generation = self._generation
                self._ws = ws
            threading.Thread(target=self._receive, args=(ws, generation), daemon=True).start()
            try:
                initialized = self._request(ws, generation, 'initialize', {
                    'clientInfo': {'name': 'ai_control_web', 'version': '0.1'},
                    'capabilities': {'experimentalApi': True}}, deadline)
                if not self._send_lock.acquire(timeout=max(0, deadline - time.monotonic())):
                    raise RuntimeError('RPC deadline exceeded')
                timer = threading.Timer(max(0, deadline - time.monotonic()), self._expire, args=(ws, generation))
                timer.daemon = True
                timer.start()
                try:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('RPC deadline exceeded')
                    ws.send('{"method":"initialized"}')
                    hint = initialized.get('userAgent')
                    match = (re.match(r'^[\x20-\x2e\x30-\x7e]{1,128}/(' + VERSION_TOKEN + r') \(', hint)
                             if type(hint) is str and len(hint) <= 4096 else None)
                    version = match.group(1) if match else None
                    with self._lock:
                        if self._ws is not ws or self._generation != generation:
                            raise RuntimeError('RPC initialization unavailable')
                        self._native_version = version
                finally:
                    timer.cancel()
                    self._send_lock.release()
            except Exception:
                self._fail(ws, generation)
                raise RuntimeError('RPC initialization unavailable') from None
            return ws, generation
        finally:
            self._connect_lock.release()

    def prepare_context(self, timeout=None):
        """Initialize the approved owned transport without a native operation."""
        if timeout is not None and (type(timeout) not in (int, float)
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError('RPC deadline refused')
        duration = self.timeout if timeout is None else min(self.timeout, timeout)
        ws, generation = self._connect(time.monotonic() + duration)
        with self._lock:
            if self._closed or self._ws is not ws or self._generation != generation:
                raise RuntimeError('RPC generation unavailable')
            return self.model_context()

    def call(self, method, params, timeout=None):
        if type(method) is not str or method not in self.METHODS or type(params) is not dict:
            raise ValueError('RPC method refused')
        duration = self.timeout if timeout is None else min(self.timeout, timeout)
        if type(duration) not in (float, int) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('RPC deadline refused')
        deadline = time.monotonic() + duration
        ws, generation = self._connect(deadline)
        return self._request(ws, generation, method, params, deadline)

    def receipt_context(self):
        """Stable offline metadata; fresh peer/thread proof still gates IO."""
        return {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                'context_id': self._model_context_id}

    def model_context(self):
        with self._lock:
            if self._closed or self._ws is None:
                return None
            return {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                    'context_id': self._model_context_id,
                    'transport_generation': self._generation,
                    'context_generation': self._context_generation,
                    'native_version': self._native_version}

    def call_in_generation(self, method, params, *, transport_generation, context_generation, timeout=None):
        if type(method) is not str or method not in self.METHODS or type(params) is not dict:
            raise ValueError('RPC method refused')
        duration = self.timeout if timeout is None else min(self.timeout, timeout)
        if type(duration) not in (float, int) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('RPC deadline refused')
        with self._lock:
            if (type(transport_generation) is not int or type(context_generation) is not int
                    or self._closed or self._ws is None or not self._method_allowed(method)
                    or self._generation != transport_generation or self._context_generation != context_generation):
                raise RuntimeError('RPC generation unavailable')
            ws = self._ws
        # No connect/reconnect: the captured socket cannot become a different scope.
        result = self._request(ws, transport_generation, method, params, time.monotonic() + duration,
                               context_generation=context_generation)
        with self._lock:
            if self._ws is not ws or self._generation != transport_generation or self._context_generation != context_generation:
                raise RuntimeError('RPC generation unavailable')
        return result

    def __call__(self, method, params):
        return self.call(method, params)

    def close(self):
        with self._lock:
            self._closed = True
            ws, generation = self._ws, self._generation
        if ws is not None:
            self._fail(ws, generation)
