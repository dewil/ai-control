"""Private, local refresh-source transaction; no provider or native authority.

Only an explicitly provisioned new source with a durable journal can be opened.
Pending and uncertain transactions remain blocked; nothing removes their journal.
The integrating host owns response validation, delivery and account quarantine.
"""

import fcntl
import json
import math
import os
import re
import stat
import sys
import threading
import time
import uuid

from _control_codex_auth_authority import AuthError, AuthScope, _snapshot


_SOURCE = 'refresh-source.json'
_HEAD = 'refresh-attempt.json'
_LOCK = '.refresh-slot.lock'
_MAX_GENERATION = 2**63 - 1
_REGISTRY_GUARD = threading.Lock()
_ROOT_LOCKS = {}


def _fail(code):
    raise AuthError(code) from None


def _capture(scope):
    return _snapshot(scope)


def _reference(captured):
    return dict(schema=captured[0], provider_id=captured[1],
                account_id=captured[2], profile_instance_id=captured[3],
                adapter_revision=captured[4],
                registration_snapshot=dict(captured[5]))


def _root(value):
    if type(value) is not str or not value.startswith('/'):
        _fail('authority_stale')
    try:
        good = (len(value.encode('utf-8')) <= 4096
                and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
                and (value == '/' or all(part not in ('', '.', '..')
                                         for part in value[1:].split('/'))))
    except Exception:
        good = False
    if not good:
        _fail('authority_stale')
    return value


def _numeric(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except Exception:
        return False


def _attempt(value):
    return (type(value) is str and re.fullmatch(
        r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',
        value, flags=re.ASCII) is not None)


def _token(value):
    return (type(value) is str and 1 <= len(value) <= 16384
            and all(33 <= ord(char) <= 126 for char in value))


def _generation(value):
    return type(value) is int and 1 <= value <= _MAX_GENERATION


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid)


def _leaf_identity(info):
    return _identity(info) + (info.st_nlink, info.st_ctime_ns)


def _private(info):
    return (stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.geteuid() and info.st_nlink == 1)


def _encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _constant(value):
    raise ValueError()


def _json(data):
    value = json.loads(data.decode('utf-8'), object_pairs_hook=_pairs,
                       parse_constant=_constant)
    # Canonical encoding also rejects surrogate text and trailing/extra whitespace.
    if type(value) is not dict or _encode(value) != data:
        raise ValueError()
    return value


class SlotLease:
    __slots__ = ()


class _Record:
    __slots__ = ('thread', 'active', 'poisoned', 'done', 'chain', 'lock_fd',
                 'lock_identity', 'mutex', 'deadline', 'generation', 'head',
                 'pin', 'pending', 'attempt', 'initial_generation', 'rotated')

    def __init__(self, deadline):
        self.thread = threading.current_thread()
        self.active = True
        self.poisoned = False
        self.done = False
        self.chain = []
        self.lock_fd = None
        self.lock_identity = None
        self.mutex = None
        self.deadline = deadline
        self.generation = None
        self.head = None
        self.pin = None
        self.pending = False
        self.attempt = None
        self.initial_generation = None
        self.rotated = False


class AnchoredAtomicSecretSlot:
    """Configuration only until open; leases are local opaque ownership tokens."""

    __slots__ = ('_scope', '_reference', '_root', '_clock', '_leases', '_guard')

    def __init__(self, root, scope, *, clock=time.monotonic):
        self._scope = _capture(scope)
        self._reference = _reference(self._scope)
        self._root = _root(root)
        if not callable(clock):
            _fail('authority_stale')
        self._clock = clock
        self._leases = {}
        self._guard = threading.Lock()

    def _scope_first(self, scope):
        if _capture(scope) != self._scope:
            _fail('authority_stale')

    def _record(self, lease, *, closed=False):
        if type(lease) is not SlotLease:
            _fail('authority_stale')
        with self._guard:
            record = self._leases.get(lease)
        if (record is None or record.thread is not threading.current_thread()
                or (not closed and (not record.active or record.done))):
            _fail('authority_stale')
        return record

    def _error(self, record, code):
        if record is not None and record.pending:
            record.poisoned = True
            _fail('refresh_unknown')
        _fail(code)

    def _remaining(self, deadline, record=None):
        if not _numeric(deadline):
            self._error(record, 'authority_stale')
        if record is not None and deadline > record.deadline:
            self._error(record, 'authority_stale')
        try:
            now = self._clock()
        except Exception:
            self._error(record, 'auth_unavailable')
        if record is not None:
            if (not record.active or record.done
                    or record.thread is not threading.current_thread()):
                self._error(record, 'authority_stale')
            if record.poisoned:
                _fail('refresh_unknown')
        if not _numeric(now) or not _numeric(deadline - now) or deadline <= now:
            self._error(record, 'auth_unavailable')
        if record is not None and record.chain:
            self._fence(record)
        return deadline - now

    def _owned(self, lease, scope, deadline):
        self._scope_first(scope)
        record = self._record(lease)
        if record.poisoned:
            _fail('refresh_unknown')
        self._remaining(deadline, record)
        return record

    def _fence(self, record):
        try:
            for parent, name, fd, identity in record.chain:
                if _identity(os.fstat(fd)) != identity:
                    self._error(record, 'authority_stale')
                current = (os.stat(name, dir_fd=parent, follow_symlinks=False)
                           if parent is not None else
                           os.stat('/', follow_symlinks=False))
                if _identity(current) != identity:
                    self._error(record, 'authority_stale')
            if record.lock_fd is not None:
                current = os.stat(_LOCK, dir_fd=record.chain[-1][2],
                                  follow_symlinks=False)
                held = os.fstat(record.lock_fd)
                if (not _private(current) or not _private(held)
                        or _leaf_identity(current) != record.lock_identity
                        or _leaf_identity(held) != record.lock_identity):
                    self._error(record, 'authority_stale')
        except AuthError:
            raise
        except Exception:
            self._error(record, 'authority_stale')

    def _anchor(self, record):
        parent = None
        names = ['/'] + ([] if self._root == '/' else self._root[1:].split('/'))
        for index, name in enumerate(names):
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                         | os.O_CLOEXEC, dir_fd=parent)
            try:
                info = os.fstat(fd)
            except BaseException:
                os.close(fd)
                raise
            record.chain.append((parent, name, fd, _identity(info)))
            final = index == len(names) - 1
            mode = stat.S_IMODE(info.st_mode)
            if final:
                okay = info.st_uid == os.geteuid() and mode == 0o700
            else:
                okay = (info.st_uid in (0, os.geteuid())
                        and (not mode & 0o022 or
                             (info.st_uid == 0 and mode & stat.S_ISVTX)))
            if not okay:
                _fail('auth_unavailable')
            parent = fd
        self._fence(record)

    def _capacity(self, record, *, creation=False):
        count = 0
        with os.scandir(record.chain[-1][2]) as entries:
            for _ in entries:
                count += 1
                if count > (9999 if creation else 10000):
                    self._error(record, 'auth_unavailable')

    def _leaf(self, record, name, error):
        self._fence(record)
        fd = None
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                         | os.O_NONBLOCK, dir_fd=record.chain[-1][2])
            before = os.fstat(fd)
            if not _private(before) or before.st_size > 65536:
                self._error(record, error)
            chunks = []
            total = 0
            while True:
                chunk = os.read(fd, min(8192, 65537 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > 65536:
                    self._error(record, error)
                chunks.append(chunk)
            after = os.fstat(fd)
            named = os.stat(name, dir_fd=record.chain[-1][2],
                            follow_symlinks=False)
            identity = _leaf_identity(before)
            if (not _private(after) or not _private(named)
                    or _leaf_identity(after) != identity
                    or _leaf_identity(named) != identity):
                self._error(record, 'authority_stale')
            data = b''.join(chunks)
            value = _json(data)
            self._fence(record)
            return value, (data, identity)
        except AuthError:
            raise
        except Exception:
            self._error(record, error)
        finally:
            if fd is not None:
                os.close(fd)

    def _source(self, record):
        value, pin = self._leaf(record, _SOURCE, 'unsupported_auth_profile')
        if (value.keys() != {'schema', 'reference', 'generation', 'refresh_token'}
                or type(value['schema']) is not int or value['schema'] != 1
                or not _generation(value['generation'])
                or not _token(value['refresh_token'])):
            self._error(record, 'unsupported_auth_profile')
        try:
            source_scope = _capture(AuthScope(value['reference'], dict(self._scope[6])))
        except Exception:
            self._error(record, 'unsupported_auth_profile')
        # Valid but foreign reference is drift, distinct from malformed source.
        if source_scope != self._scope:
            self._error(record, 'authority_stale')
        if record.generation is not None and value['generation'] != record.generation:
            self._error(record, 'authority_stale')
        if record.pin is not None and pin != record.pin:
            self._error(record, 'authority_stale')
        return value, pin

    def _head(self, record, *, startup=False):
        value, pin = self._leaf(record, _HEAD, 'refresh_unknown')
        good = (type(value.get('schema')) is int and value.get('schema') == 1
                and _encode(value.get('reference')) == _encode(self._reference))
        state = value.get('state')
        if type(state) is not str:
            good = False
        elif state == 'ready':
            good = (good and value.keys() == {'schema', 'reference', 'generation', 'state'}
                    and type(value.get('generation')) is int
                    and value['generation'] == 1)
        elif state == 'pending':
            good = (good and value.keys() == {'schema', 'reference', 'generation',
                                             'attempt_id', 'state'}
                    and _generation(value.get('generation'))
                    and _attempt(value.get('attempt_id')))
        elif state == 'completed':
            initial, final = value.get('initial_generation'), value.get('final_generation')
            good = (good and value.keys() == {'schema', 'reference', 'attempt_id',
                                             'initial_generation', 'final_generation', 'state'}
                    and _attempt(value.get('attempt_id')) and _generation(initial)
                    and _generation(final) and final in (initial, initial + 1))
        else:
            good = False
        if not good or (startup and state == 'pending'):
            self._error(record, 'refresh_unknown')
        if record.head is not None and pin != record.head:
            self._error(record, 'refresh_unknown')
        return value, pin

    def _release(self, record):
        # Do not mutate files, retry writes, or reclaim retained temp orphans.
        record.active = False
        failed = False
        if record.lock_fd is not None:
            try:
                fcntl.flock(record.lock_fd, fcntl.LOCK_UN)
            except Exception:
                failed = True
            finally:
                try:
                    os.close(record.lock_fd)
                except Exception:
                    failed = True
                record.lock_fd = None
        for _, _, fd, _ in reversed(record.chain):
            try:
                os.close(fd)
            except Exception:
                failed = True
        record.chain = []
        record.pin = None
        record.head = None
        if record.mutex is not None:
            record.mutex.release()
            record.mutex = None
        return not failed

    def open(self, scope, *, deadline):
        self._scope_first(scope)
        remaining = self._remaining(deadline)
        if not sys.platform.startswith('linux'):
            _fail('auth_unavailable')
        record = _Record(deadline)
        try:
            self._anchor(record)
            remaining = self._remaining(deadline, record)
            root_info = os.fstat(record.chain[-1][2])
            key = (root_info.st_dev, root_info.st_ino)
            with _REGISTRY_GUARD:
                mutex = _ROOT_LOCKS.setdefault(key, threading.Lock())
            real_end = time.monotonic() + min(remaining, 0.5)
            if not mutex.acquire(timeout=max(0, real_end - time.monotonic())):
                _fail('refresh_busy')
            record.mutex = mutex
            self._remaining(deadline, record)
            self._capacity(record)
            root_fd = record.chain[-1][2]
            try:
                fd = os.open(_LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
                             | os.O_NONBLOCK, dir_fd=root_fd)
            except FileNotFoundError:
                self._capacity(record, creation=True)
                self._remaining(deadline, record)
                self._fence(record)
                try:
                    fd = os.open(_LOCK, os.O_RDWR | os.O_CREAT | os.O_EXCL
                                 | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
                except FileExistsError:
                    fd = os.open(_LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
                                 | os.O_NONBLOCK, dir_fd=root_fd)
                else:
                    record.lock_fd = fd
                    os.fsync(root_fd)
                    self._capacity(record)
            record.lock_fd = fd
            info = os.fstat(fd)
            if not _private(info):
                _fail('auth_unavailable')
            record.lock_identity = _leaf_identity(info)
            self._fence(record)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= real_end:
                        _fail('refresh_busy')
                    self._remaining(deadline, record)
                    time.sleep(min(0.01, max(0, real_end - time.monotonic())))
            self._remaining(deadline, record)
            head, head_pin = self._head(record, startup=True)
            source, _ = self._source(record)
            expected = (head['generation'] if head['state'] == 'ready'
                        else head['final_generation'])
            if source['generation'] != expected:
                _fail('refresh_unknown')
            record.generation = source['generation']
            record.initial_generation = source['generation']
            record.head = head_pin
            self._remaining(deadline, record)
            self._head(record, startup=True)
            self._source(record)
            lease = SlotLease()
            with self._guard:
                self._leases[lease] = record
            return lease
        except AuthError:
            self._release(record)
            raise
        except Exception:
            self._release(record)
            _fail('auth_unavailable')

    def read_refresh(self, lease, scope, *, deadline):
        record = self._owned(lease, scope, deadline)
        if record.pending:
            self._error(record, 'authority_stale')
        self._head(record, startup=True)
        value, pin = self._source(record)
        self._remaining(deadline, record)
        self._head(record, startup=True)
        final_value, final_pin = self._source(record)
        if final_pin != pin:
            self._error(record, 'authority_stale')
        record.pin = final_pin
        return final_value['refresh_token']

    def _replace(self, record, name, value, deadline):
        fd = None
        try:
            self._remaining(deadline, record)
            self._capacity(record, creation=True)
            self._remaining(deadline, record)
            self._head(record)
            self._source(record)
            self._fence(record)
            temporary = '.refresh-slot-temp-' + uuid.uuid4().hex
            root_fd = record.chain[-1][2]
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
            self._capacity(record)
            data = _encode(value)
            offset = 0
            while offset < len(data):
                written = os.write(fd, data[offset:])
                if written <= 0:
                    raise OSError()
                offset += written
            os.fsync(fd)
            info = os.fstat(fd)
            if not _private(info):
                self._error(record, 'auth_unavailable')
            self._remaining(deadline, record)
            # Clock callbacks can execute arbitrary cooperating code: refence all
            # captured leaves after the callback, with no callback until replace.
            self._head(record)
            self._source(record)
            self._fence(record)
            temp_info = os.stat(temporary, dir_fd=root_fd, follow_symlinks=False)
            if _leaf_identity(temp_info) != _leaf_identity(info):
                self._error(record, 'authority_stale')
            os.replace(temporary, name, src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.fsync(root_fd)
            self._fence(record)
            self._capacity(record)
            published, pin = self._leaf(record, name, 'refresh_unknown')
            if pin[0] != data or pin[1] != _leaf_identity(os.fstat(fd)):
                self._error(record, 'refresh_unknown')
            return published, pin
        except AuthError:
            record.poisoned = True
            _fail('refresh_unknown')
        except Exception:
            record.poisoned = True
            _fail('refresh_unknown')
        finally:
            if fd is not None:
                os.close(fd)

    def reserve_attempt(self, lease, scope, attempt_id, *, deadline):
        record = self._owned(lease, scope, deadline)
        if record.pending or record.pin is None or not _attempt(attempt_id):
            self._error(record, 'authority_stale')
        self._head(record, startup=True)
        self._source(record)
        self._capacity(record, creation=True)
        self._remaining(deadline, record)
        self._head(record, startup=True)
        self._source(record)
        record.pending = True
        record.attempt = attempt_id
        value = dict(schema=1, reference=self._reference, generation=record.generation,
                     attempt_id=attempt_id, state='pending')
        _, pin = self._replace(record, _HEAD, value, deadline)
        record.head = pin
        self._remaining(deadline, record)
        self._head(record)
        self._source(record)

    def _pending(self, record, attempt_id):
        if (not record.pending or not _attempt(attempt_id)
                or attempt_id != record.attempt):
            self._error(record, 'authority_stale')
        head, _ = self._head(record)
        if (head['state'] != 'pending' or head['attempt_id'] != attempt_id
                or head['generation'] != record.initial_generation):
            self._error(record, 'refresh_unknown')
        self._source(record)

    def commit_rotation(self, lease, scope, attempt_id, new_token, *, deadline):
        record = self._owned(lease, scope, deadline)
        self._pending(record, attempt_id)
        if record.rotated or not _token(new_token) or record.generation >= _MAX_GENERATION:
            self._error(record, 'authority_stale')
        value = dict(schema=1, reference=self._reference,
                     generation=record.generation + 1, refresh_token=new_token)
        _, pin = self._replace(record, _SOURCE, value, deadline)
        record.generation += 1
        record.pin = pin
        record.rotated = True
        self._remaining(deadline, record)
        self._pending(record, attempt_id)

    def finish_confirmed(self, lease, scope, attempt_id, *, deadline):
        record = self._owned(lease, scope, deadline)
        self._pending(record, attempt_id)
        value = dict(schema=1, reference=self._reference, attempt_id=attempt_id,
                     initial_generation=record.initial_generation,
                     final_generation=record.generation, state='completed')
        _, pin = self._replace(record, _HEAD, value, deadline)
        record.head = pin
        self._remaining(deadline, record)
        self._head(record)
        self._source(record)
        record.done = True

    def close(self, lease):
        record = self._record(lease, closed=True)
        if record.active:
            if not self._release(record):
                self._error(record, 'auth_unavailable')
