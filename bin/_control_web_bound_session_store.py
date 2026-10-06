"""Immutable R+G reservations only; receipts never authorize native dispatch."""
from contextlib import contextmanager
import ctypes
import fcntl
from functools import wraps
import hashlib
import json
import math
import os
import stat
import sys
import threading
import time
import uuid

from _control_provider_accounts import AccountError
import _control_web_bound_session_records as dto


_CODES = ('context_invalid', 'context_drift', 'invalid_request', 'store_unavailable')


def _need(condition, code='store_unavailable'):
    if not condition:
        raise AccountError(code)


def _safe(method):
    @wraps(method)
    def call(*args, **kwargs):
        code = None
        try:
            return method(*args, **kwargs)
        except dto.BoundRecordError as error:
            code = error.code
        except AccountError as error:
            code = error.code if error.code in _CODES else 'store_unavailable'
        except Exception:
            code = 'store_unavailable'
        raise AccountError(code)
    return call


def _pin(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_nlink, info.st_ctime_ns, info.st_size)


def _directory_pin(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result)
        result[key] = value
    return result


def _json_types(value, depth=1):
    _need(depth <= 16)
    if type(value) is dict:
        for key, child in value.items():
            _json_types(key, depth + 1)
            _json_types(child, depth + 1)
    elif type(value) is list:
        for child in value:
            _json_types(child, depth + 1)
    elif type(value) is str:
        _need(not any(0xD800 <= ord(char) <= 0xDFFF for char in value))
    elif type(value) is float:
        _need(math.isfinite(value))


def _r_name(record):
    key = dto._digest({field: record[field] for field in
                       ('context_ref', 'project', 'root', 'operation_id')})
    return 'BC-' + key + '.R.json'


def _g_name(session):
    return 'BG-S-' + session + '.json'


class _Base:
    __slots__ = ()


class _Held:
    def __init__(self, chain, uid, deadline, rename):
        self.chain = chain
        self.uid = uid
        self.deadline = deadline
        self.rename = rename
        self.thread = threading.current_thread()
        self.active = True
        self.locked = False

    @property
    def directory(self):
        return self.chain[-1][1]


class BoundSessionStore:
    @_safe
    def __init__(self, path, context_ref, *, clock=None, monotonic_clock=None):
        captured = dto._reference(context_ref)
        self._codec = dto.BoundRecordCodec(captured)
        self._reference = dto._freeze(captured)
        dto._root(path)
        self._path = path
        self._clock = time.time_ns if clock is None else clock
        self._monotonic = time.monotonic if monotonic_clock is None else monotonic_clock
        _need(callable(self._clock) and callable(self._monotonic), 'invalid_request')
        self._bases = {}
        self._registry_lock = threading.Lock()

    def _context(self, reference):
        captured = dto._reference(reference)
        _need(captured == dto._reference(self._reference), 'context_drift')
        return captured

    def _base(self, base, *, absent=False):
        if base is None and absent:
            return None
        _need(type(base) is _Base, 'invalid_request')
        with self._registry_lock:
            held = self._bases.get(base)
        _need(held is not None and held.active
              and held.thread is threading.current_thread(), 'invalid_request')
        return held

    def _remaining(self, deadline):
        _need(type(deadline) in (int, float), 'invalid_request')
        try:
            finite = math.isfinite(deadline)
        except (OverflowError, ValueError):
            finite = False
        _need(finite, 'invalid_request')
        try:
            now = self._monotonic()
        except Exception:
            raise AccountError('store_unavailable') from None
        _need(type(now) in (int, float))
        try:
            remaining = deadline - now
            valid = math.isfinite(now) and math.isfinite(remaining) and remaining > 0
        except (OverflowError, ValueError):
            valid = False
        _need(valid)
        return remaining

    def _platform(self):
        _need(sys.platform.startswith('linux'))
        rename = ctypes.CDLL(None, use_errno=True).renameat2
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        return rename

    def _dir_info(self, fd, uid, *, namespace=False):
        info = os.fstat(fd)
        _need(stat.S_ISDIR(info.st_mode))
        if namespace:
            _need(info.st_uid == uid and stat.S_IMODE(info.st_mode) == 0o700)
        else:
            _need(info.st_uid in (0, uid))
            _need(not info.st_mode & 0o022
                  or (info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)))
        return info

    def _anchors(self, held):
        _need(held.active and held.thread is threading.current_thread())
        chain = held.chain
        for index, (name, fd, original) in enumerate(chain):
            current = self._dir_info(fd, held.uid, namespace=index == len(chain) - 1)
            _need(_directory_pin(current) == original)
            named = (os.stat('/', follow_symlinks=False) if index == 0 else
                     os.stat(name, dir_fd=chain[index - 1][1], follow_symlinks=False))
            _need(_directory_pin(named) == original)

    def _tick(self, base, deadline):
        held = self._base(base)
        _need(type(deadline) in (int, float), 'invalid_request')
        _need(deadline <= held.deadline, 'invalid_request')
        self._remaining(deadline)
        _need(self._base(base) is held)
        self._anchors(held)
        return held

    def _close(self, held):
        held.active = False
        failed = False
        try:
            if held.locked:
                fcntl.flock(held.directory, fcntl.LOCK_UN)
        except OSError:
            failed = True
        finally:
            held.locked = False
            for _, fd, _ in reversed(held.chain):
                try:
                    os.close(fd)
                except OSError:
                    failed = True
        _need(not failed)

    @_safe
    def _enter(self, reference, deadline, create):
        self._context(reference)
        _need(type(create) is bool, 'invalid_request')
        rename = self._platform()
        self._remaining(deadline)
        uid = os.getuid()
        chain = []
        held = None
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            chain.append(('/', fd, _directory_pin(os.fstat(fd))))
            self._dir_info(fd, uid)
            parts = self._path[1:].split('/') if self._path != '/' else []
            for index, name in enumerate(parts):
                self._remaining(deadline)
                parent = chain[-1][1]
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                except FileNotFoundError:
                    if index != len(parts) - 1:
                        raise
                    if not create:
                        for _, owned, _ in reversed(chain):
                            os.close(owned)
                        return None, None
                    # Validate every held ancestor after the clock callback.
                    for offset, (part, owned, original) in enumerate(chain):
                        _need(_directory_pin(self._dir_info(owned, uid)) == original)
                        named = os.stat('/', follow_symlinks=False) if offset == 0 else os.stat(part, dir_fd=chain[offset - 1][1], follow_symlinks=False)
                        _need(_directory_pin(named) == original)
                    os.mkdir(name, 0o700, dir_fd=parent)
                    os.fsync(parent)
                    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                chain.append((name, fd, _directory_pin(os.fstat(fd))))
                self._dir_info(fd, uid, namespace=index == len(parts) - 1)
            held = _Held(chain, uid, deadline, rename)
            self._anchors(held)
            remaining = self._remaining(deadline)
            stop = time.monotonic() + min(remaining, 1.0)
            while True:
                self._remaining(deadline)
                self._anchors(held)
                try:
                    fcntl.flock(held.directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held.locked = True
                    break
                except BlockingIOError:
                    _need(time.monotonic() < stop)
                    time.sleep(min(0.01, max(0, stop - time.monotonic())))
            self._remaining(deadline)
            self._anchors(held)
            base = _Base()
            with self._registry_lock:
                self._bases[base] = held
            return base, held
        except BaseException:
            if held is not None:
                self._close(held)
            else:
                for _, fd, _ in reversed(chain):
                    os.close(fd)
            raise

    @contextmanager
    def locked(self, context_ref, deadline, create=False):
        base, held = self._enter(context_ref, deadline, create)
        try:
            yield base
        finally:
            if held is not None:
                with self._registry_lock:
                    self._bases.pop(base, None)
                self._close(held)

    @_safe
    def prepare_create(self, context_ref, project, root, session_ref, operation_id, deadline):
        reference = self._context(context_ref)
        dto._match(project, r'[a-zA-Z0-9_-]{1,32}')
        dto._root(root)
        dto._uuid(session_ref)
        dto._uuid(operation_id)
        self._remaining(deadline)
        try:
            created = self._clock()
        except Exception:
            raise AccountError('invalid_request') from None
        dto._integer(created, 1, 2**63 - 1)
        self._remaining(deadline)
        return self._codec.prepare_create(reference, project, root, session_ref, operation_id, created)

    def _listing(self, held, limit=10000):
        names = os.listdir(held.directory)
        _need(len(names) <= limit)
        for name in names:
            _need(not name.startswith(('BI-', 'BS-'))
                  and not (name.startswith('BC-') and ('.C' in name or '.A' in name)))
        return names

    def _entries(self, base, deadline):
        held = self._tick(base, deadline)
        names = self._listing(held)
        self._anchors(held)
        return names

    def _leaf_info(self, fd, uid):
        info = os.fstat(fd)
        _need(stat.S_ISREG(info.st_mode) and info.st_uid == uid
              and stat.S_IMODE(info.st_mode) == 0o600
              and info.st_nlink == 1 and info.st_size <= 4096)
        return info

    def _read(self, base, name, deadline):
        held = self._tick(base, deadline)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=held.directory)
        except FileNotFoundError:
            return None, None
        try:
            info = self._leaf_info(fd, held.uid)
            raw = os.read(fd, 4097)
            _need(len(raw) <= 4096 and os.read(fd, 1) == b'')
            value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                               parse_constant=lambda ignored: _need(False))
            _need(type(value) is dict)
            _json_types(value)
            self._tick(base, deadline)
            _need(_pin(info) == _pin(self._leaf_info(fd, held.uid))
                  == _pin(os.stat(name, dir_fd=held.directory, follow_symlinks=False)))
            os.lseek(fd, 0, os.SEEK_SET)
            _need(os.read(fd, 4097) == raw and os.read(fd, 1) == b'')
            _need(_pin(info) == _pin(os.fstat(fd))
                  == _pin(os.stat(name, dir_fd=held.directory, follow_symlinks=False)))
            self._anchors(held)
            commitment = dict(filename=name, dev=info.st_dev, ino=info.st_ino,
                              ctime_ns=info.st_ctime_ns, sha256=hashlib.sha256(raw).hexdigest())
            return value, commitment
        finally:
            os.close(fd)

    def _fence_leaf(self, held, commitment):
        """Fresh held/name byte fence without callbacks in the final section."""
        name = commitment['filename']
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=held.directory)
        try:
            info = self._leaf_info(fd, held.uid)
            raw = os.read(fd, 4097)
            _need(len(raw) <= 4096 and os.read(fd, 1) == b'')
            current = dict(filename=name, dev=info.st_dev, ino=info.st_ino,
                           ctime_ns=info.st_ctime_ns, sha256=hashlib.sha256(raw).hexdigest())
            _need(current == commitment)
            _need(_pin(info) == _pin(self._leaf_info(fd, held.uid))
                  == _pin(os.stat(name, dir_fd=held.directory, follow_symlinks=False)))
            return fd, info, raw
        except BaseException:
            os.close(fd)
            raise

    def _final_fences(self, base, pins):
        held = self._base(base)
        # Bound descriptor use even for a namespace containing thousands of Gs.
        # The first R/G pair remains held together during its final byte check.
        for offset in range(0, len(pins), 2):
            opened = []
            try:
                for pin in pins[offset:offset + 2]:
                    opened.append((pin, *self._fence_leaf(held, pin)))
                for pin, fd, info, raw in opened:
                    os.lseek(fd, 0, os.SEEK_SET)
                    _need(os.read(fd, 4097) == raw and os.read(fd, 1) == b'')
                    _need(_pin(info) == _pin(self._leaf_info(fd, held.uid))
                          == _pin(os.stat(pin['filename'], dir_fd=held.directory, follow_symlinks=False)))
                self._anchors(held)
            finally:
                for _, fd, _, _ in opened:
                    os.close(fd)
        self._anchors(held)

    def _g(self, record, name):
        dto._keys(record, 'schema kind context_ref project root session_ref operation_id r_parent')
        _need(type(record['schema']) is int and record['schema'] == 1
              and type(record['kind']) is str and record['kind'] == 'bound_session_reservation')
        dto._reference(record['context_ref'])
        dto._match(record['project'], r'[a-zA-Z0-9_-]{1,32}')
        dto._root(record['root'])
        dto._uuid(record['session_ref'])
        dto._uuid(record['operation_id'])
        _need(name == _g_name(record['session_ref']))
        dto._commitment(record['r_parent'], expected=_r_name(record))

    def _history(self, base, deadline):
        names = self._entries(base, deadline)
        history = {}
        try:
            for name in names:
                if name.startswith('BG-S-'):
                    value, pin = self._read(base, name, deadline)
                    _need(value is not None)
                    self._g(value, name)
                    history[name] = (value, pin)
        except Exception:
            raise AccountError('store_unavailable') from None
        _need(set(self._entries(base, deadline)) == set(names))
        return history, names

    def _lookup(self, base, reference, project, root, operation, deadline, history):
        history, names = history
        identity = dict(context_ref=reference, project=project, root=root, operation_id=operation)
        name = _r_name(identity)
        matched = [(record, pin) for record, pin in history.values()
                   if all(record[key] == value for key, value in identity.items())]
        _need(len(matched) <= 1)
        record, r_pin = self._read(base, name, deadline)
        if record is None:
            _need(not matched)
            self._entries(base, deadline)
            held = self._tick(base, deadline)
            _need(set(self._listing(held)) == set(names))
            self._final_fences(base, tuple(pin for _, pin in history.values()))
            return None
        _need(len(matched) == 1)
        g, g_pin = matched[0]
        try:
            _need(g['r_parent'] == r_pin)
            prepared = dto.PreparedBoundCreate(record)
            _need(record['session_ref'] == g['session_ref'])
            checked = self._codec.validate_create(reference, prepared, project=project,
                        root=root, session_ref=g['session_ref'], operation_id=operation)
            parents = dict(R=r_pin, G=g_pin, C=None, I_session=None, I_native=None, A=None)
            receipt = dto.BoundCreateReceipt(checked.record, 'unknown', parents)
            self._entries(base, deadline)
            held = self._tick(base, deadline)
            _need(set(self._listing(held)) == set(names))
            self._final_fences(base, (r_pin, g_pin) + tuple(pin for _, pin in history.values()))
            return receipt
        except Exception:
            raise AccountError('store_unavailable') from None

    @_safe
    def lookup_create(self, base, context_ref, project, root, operation_id, deadline):
        reference = self._context(context_ref)
        held = self._base(base, absent=True)
        dto._match(project, r'[a-zA-Z0-9_-]{1,32}')
        dto._root(root)
        dto._uuid(operation_id)
        self._platform()
        self._remaining(deadline)
        if held is None:
            return None
        self._base(base)
        self._anchors(held)
        history = self._history(base, deadline)
        return self._lookup(base, reference, project, root, operation_id, deadline, history)

    def _publish_leaf(self, base, name, record, deadline, *, parents=(), absent=(), names=()):
        raw = dto._canonical(record)
        _need(len(raw) <= 4096)
        held = self._tick(base, deadline)
        _need(len(self._entries(base, deadline)) <= 10000)
        temp = '.tmp-' + uuid.uuid4().hex
        fd = None
        try:
            self._tick(base, deadline)
            _need(set(self._listing(held)) == set(names))
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=held.directory)
            os.fchmod(fd, 0o600)
            view = memoryview(raw)
            while view:
                self._tick(base, deadline)
                written = os.write(fd, view)
                _need(written > 0)
                view = view[written:]
            self._tick(base, deadline)
            os.fsync(fd)
            self._tick(base, deadline)
            _need(set(self._listing(held, 10002)) == set(names) | {temp})
            info = self._leaf_info(fd, held.uid)
            _need(_pin(info) == _pin(os.stat(temp, dir_fd=held.directory, follow_symlinks=False)))
            # No callbacks between final anchor/cap/leaf fences and NOREPLACE.
            self._anchors(held)
            self._final_fences(base, parents)
            for missing in absent:
                try:
                    os.stat(missing, dir_fd=held.directory, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    _need(False)
            _need(held.rename(held.directory, temp.encode('utf-8'),
                              held.directory, name.encode('utf-8'), 1) == 0)
            os.fsync(held.directory)
            self._tick(base, deadline)
            _need(_pin(self._leaf_info(fd, held.uid)) == _pin(os.stat(name, dir_fd=held.directory, follow_symlinks=False)))
            self._entries(base, deadline)
        finally:
            if fd is not None:
                os.close(fd)
        stored, pin = self._read(base, name, deadline)
        _need(stored == record)
        return pin

    @_safe
    def publish_create(self, base, context_ref, prepared, deadline):
        reference = self._context(context_ref)
        self._base(base, absent=True)
        _need(base is not None)
        _need(type(prepared) is dto.PreparedBoundCreate, 'invalid_request')
        checked = self._codec._value(prepared, False, reference)
        record = dto._capture(checked.record)
        self._platform()
        self._tick(base, deadline)
        history = self._history(base, deadline)
        previous = self._lookup(base, reference, record['project'], record['root'], record['operation_id'], deadline, history)
        if previous is not None:
            _need(dto._capture(previous.record) == record)
            return previous
        global_history, names = history
        _need(_g_name(record['session_ref']) not in global_history)
        _need(len(self._entries(base, deadline)) <= 9998)
        historical_pins = tuple(pin for _, pin in global_history.values())
        r_pin = self._publish_leaf(base, _r_name(record), record, deadline,
                                   absent=(_g_name(record['session_ref']),),
                                   parents=historical_pins, names=names)
        g = {key: record[key] for key in ('context_ref', 'project', 'root', 'session_ref', 'operation_id')}
        g.update(schema=1, kind='bound_session_reservation', r_parent=r_pin)
        # A callback cannot silently change R between reservation stages.
        _, fresh_r = self._read(base, _r_name(record), deadline)
        _need(fresh_r == r_pin)
        self._publish_leaf(base, _g_name(record['session_ref']), g, deadline, parents=(r_pin,) + historical_pins,
                           names=tuple(names) + (_r_name(record),))
        final = self._lookup(base, reference, record['project'], record['root'],
                             record['operation_id'], deadline, self._history(base, deadline))
        _need(final is not None and dto._capture(final.record) == record)
        return final
