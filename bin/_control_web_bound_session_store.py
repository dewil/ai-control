"""Immutable bound-session history; receipts confer no native authority."""
from contextlib import contextmanager
import ctypes
import fcntl
from functools import wraps
import hashlib
import json
import math
import os
import re
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


class _Budget:
    def __init__(self):
        self.remaining = math.inf


def _safe(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        local = getattr(self, '_budgets', None)
        stack = None
        if local is not None:
            stack = getattr(local, 'stack', None)
            if stack is None:
                stack = local.stack = []
            stack.append(_Budget())
        code = None
        try:
            return method(self, *args, **kwargs)
        except dto.BoundRecordError as error:
            code = error.code
        except AccountError as error:
            code = error.code if error.code in _CODES else 'store_unavailable'
        except Exception:
            code = 'store_unavailable'
        finally:
            if stack is not None:
                stack.pop()
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


def _stage_name(record, role):
    return _r_name(record).replace('.R.json', '.' + role + '.json')


def _i_session(session):
    return 'BI-S-' + session + '.json'


def _i_native(record):
    return 'BI-N-' + dto._digest({key: record[key] for key in
                                 ('context_ref', 'root', 'sid')}) + '.json'


def _stop_name(record, role):
    key = dto._digest({field: record[field] for field in
                       ('context_ref', 'root', 'session_ref', 'operation_id')})
    return 'BS-' + key + '.' + role + '.json'


def _sid(value):
    _need(type(value) is str, 'invalid_request')
    try:
        valid = str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    _need(valid, 'invalid_request')


class _Base:
    __slots__ = ()


class _Held:
    def __init__(self, chain, uid, deadline, rename, remaining):
        self.chain = chain
        self.uid = uid
        self.deadline = deadline
        self.rename = rename
        self.remaining = remaining
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
        self._budgets = threading.local()

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
        stack = getattr(self._budgets, 'stack', ())
        if stack:
            stack[-1].remaining = min(stack[-1].remaining, remaining)
            remaining = stack[-1].remaining
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

    def _chain_fences(self, chain, uid, *, namespace=False):
        for index, (name, fd, original) in enumerate(chain):
            current = self._dir_info(fd, uid, namespace=namespace and index == len(chain) - 1)
            _need(_directory_pin(current) == original)
            named = (os.stat('/', follow_symlinks=False) if index == 0 else
                     os.stat(name, dir_fd=chain[index - 1][1], follow_symlinks=False))
            _need(_directory_pin(named) == original)

    def _anchors(self, held):
        _need(held.active and held.thread is threading.current_thread())
        self._chain_fences(held.chain, held.uid, namespace=True)

    def _tick(self, base, deadline):
        held = self._base(base)
        _need(type(deadline) in (int, float), 'invalid_request')
        _need(deadline <= held.deadline, 'invalid_request')
        held.remaining = min(held.remaining, self._remaining(deadline))
        _need(self._base(base) is held)
        self._anchors(held)
        return held

    def _terminal_window(self, base, deadline):
        held = self._tick(base, deadline)
        # The injected callback is authoritative here, and is never called again
        # inside this window. Its retained budget is charged by trusted elapsed time.
        start = time.monotonic_ns()
        budget = int(held.remaining) * 1_000_000_000 + int((held.remaining % 1) * 1_000_000_000)
        _need(budget > 0)
        return held, start, budget

    def _window_check(self, base, window):
        held, start, budget = window
        left = budget - (time.monotonic_ns() - start)
        _need(left > 0 and self._base(base) is held)
        self._anchors(held)
        left = budget - (time.monotonic_ns() - start)
        _need(left > 0)
        return left

    def _finish_window(self, base, window):
        left = self._window_check(base, window) / 1_000_000_000
        held = window[0]
        held.remaining = min(held.remaining, left)
        stack = getattr(self._budgets, 'stack', ())
        if stack:
            stack[-1].remaining = min(stack[-1].remaining, left)

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
                        remaining = self._remaining(deadline)
                        start = time.monotonic_ns()
                        self._chain_fences(chain, uid)
                        # Recheck absence under the freshly fenced parent, with
                        # no clock callback between this witness and None.
                        try:
                            os.stat(name, dir_fd=parent, follow_symlinks=False)
                        except FileNotFoundError:
                            pass
                        else:
                            _need(False)
                        _need((time.monotonic_ns() - start) / 1_000_000_000 < remaining)
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
            held = _Held(chain, uid, deadline, rename,
                         getattr(self._budgets, 'stack')[-1].remaining)
            self._anchors(held)
            remaining = self._remaining(deadline)
            held.remaining = min(held.remaining, remaining)
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
            held.remaining = min(held.remaining, self._remaining(deadline))
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

    def _listing(self, base, deadline, limit=10000, *, window=None):
        if window is None:
            held = self._tick(base, deadline)
        else:
            self._window_check(base, window)
            held = window[0]
        # Consume at most the first over-cap witness; transient publication
        # may additionally count the owned temporary leaf.
        limit = min(limit, 10002)
        epoch = os.fstat(held.directory)
        original = (epoch.st_mtime_ns, epoch.st_ctime_ns, epoch.st_size)
        names = []
        with os.scandir(held.directory) as entries:
            for entry in entries:
                _need(len(names) < limit)
                if window is None:
                    self._tick(base, deadline)
                else:
                    self._window_check(base, window)
                name = entry.name
                names.append(name)
        if window is None:
            self._tick(base, deadline)
        else:
            self._window_check(base, window)
        current = os.fstat(held.directory)
        _need((current.st_mtime_ns, current.st_ctime_ns, current.st_size) == original)
        return names

    def _entries(self, base, deadline):
        return self._listing(base, deadline)

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

    def _final_fences(self, base, pins, deadline, *, window, pair=()):
        self._window_check(base, window)
        held = window[0]
        # Bound descriptor use even for a namespace containing thousands of Gs.
        # Keep an explicit final R/G pair together after the historical pass.
        groups = [pins[offset:offset + 2] for offset in range(0, len(pins), 2)]
        if pair:
            groups.append(pair)
        for group in groups:
            self._window_check(base, window)
            opened = []
            try:
                for pin in group:
                    opened.append((pin, *self._fence_leaf(held, pin)))
                self._window_check(base, window)
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

    def _validate_stage(self, name, value):
        """Strict syntax for every recognized stage, independent of its owner."""
        if name.startswith('BC-'):
            _need(re.fullmatch(r'BC-[0-9a-f]{64}\.[RCA]\.json', name) is not None)
            role = name[-6]
            if role == 'R':
                dto.PreparedBoundCreate(value)
                _need(name == _r_name(value))
            elif role == 'C':
                dto._keys(value, 'schema kind r_parent g_parent sid')
                _need(type(value['schema']) is int and value['schema'] == 1
                      and value['kind'] == 'bound_session_candidate')
                dto._commitment(value['r_parent'], expected=name.replace('.C.json', '.R.json'))
                dto._commitment(value['g_parent'], pattern=r'BG-S-[0-9a-f-]{36}\.json')
                _sid(value['sid'])
            else:
                dto._keys(value, 'schema kind parents')
                _need(type(value['schema']) is int and value['schema'] == 1
                      and value['kind'] == 'bound_session_accepted')
                dto._keys(value['parents'], 'R G C I_session I_native')
                for parent in value['parents'].values():
                    dto._commitment(parent, pattern=r'(BC-[0-9a-f]{64}\.[RC]\.json|BG-S-[0-9a-f-]{36}\.json|BI-S-[0-9a-f-]{36}\.json|BI-N-[0-9a-f]{64}\.json)')
        elif name.startswith('BG-'):
            self._g(value, name)
        elif name.startswith('BI-'):
            dto._keys(value, 'schema kind context_ref project root session_ref operation_id sid r_parent g_parent c_parent')
            _need(type(value['schema']) is int and value['schema'] == 1
                  and value['kind'] == 'bound_session_origin')
            dto._reference(value['context_ref'])
            dto._match(value['project'], r'[a-zA-Z0-9_-]{1,32}')
            dto._root(value['root'])
            dto._uuid(value['session_ref'])
            dto._uuid(value['operation_id'])
            _sid(value['sid'])
            _need(name in (_i_session(value['session_ref']), _i_native(value)))
            dto._commitment(value['r_parent'], expected=_r_name(value))
            dto._commitment(value['g_parent'], expected=_g_name(value['session_ref']))
            dto._commitment(value['c_parent'], expected=_stage_name(value, 'C'))
        elif name.startswith('BS-'):
            _need(re.fullmatch(r'BS-[0-9a-f]{64}\.[ST]\.json', name) is not None)
            if name.endswith('.S.json'):
                dto.PreparedBoundStop(value)
                _need(name == _stop_name(value, 'S'))
            else:
                dto._keys(value, 'schema kind s_parent')
                _need(type(value['schema']) is int and value['schema'] == 1
                      and value['kind'] == 'bound_session_stopped')
                dto._commitment(value['s_parent'], expected=name.replace('.T.json', '.S.json'))

    def _history(self, base, deadline):
        names = self._entries(base, deadline)
        history = {}
        try:
            for name in names:
                if name.startswith(('BC-', 'BG-', 'BI-', 'BS-')):
                    value, pin = self._read(base, name, deadline)
                    _need(value is not None)
                    self._validate_stage(name, value)
                    history[name] = (value, pin)
            # Parents are exact current bytes/inodes, never syntax authority.
            def parent(claim):
                observed = history.get(claim['filename'])
                _need(observed is not None and observed[1] == claim)
                return observed[0]
            for name, (value, pin) in history.items():
                if name.startswith('BG-'):
                    r = parent(value['r_parent'])
                    _need(all(value[key] == r[key] for key in
                              ('context_ref', 'project', 'root', 'session_ref', 'operation_id')))
                elif name.endswith('.C.json'):
                    r = parent(value['r_parent'])
                    g = parent(value['g_parent'])
                    _need(value['g_parent']['filename'] == _g_name(r['session_ref'])
                          and g['r_parent'] == value['r_parent'])
                elif name.startswith('BI-'):
                    r = parent(value['r_parent'])
                    g = parent(value['g_parent'])
                    c = parent(value['c_parent'])
                    _need(all(value[key] == r[key] for key in
                              ('context_ref', 'project', 'root', 'session_ref', 'operation_id'))
                          and g['r_parent'] == value['r_parent']
                          and c['r_parent'] == value['r_parent']
                          and c['g_parent'] == value['g_parent'] and c['sid'] == value['sid'])
                    counterpart = history.get(_i_native(value) if name.startswith('BI-S-')
                                              else _i_session(value['session_ref']))
                    if counterpart is not None:
                        _need(counterpart[0] == value and counterpart[1]['sha256'] == pin['sha256'])
                elif name.endswith('.A.json'):
                    parents = value['parents']
                    r = parent(parents['R'])
                    _need(name == _stage_name(r, 'A'))
                    fresh = self._create_chain(r, history)
                    _need(all(fresh.parents[role] is not None for role in
                              ('R', 'G', 'C', 'I_session', 'I_native')))
                    _need(parents == {role: dto._capture(fresh.parents[role]) for role in parents})
                elif name.endswith('.S.json'):
                    a = parent(value['origin_parent'])
                    r = parent(a['parents']['R'])
                    _need(all(value[key] == r[key] for key in ('context_ref', 'root', 'session_ref')))
                elif name.endswith('.T.json'):
                    parent(value['s_parent'])
        except Exception:
            raise AccountError('store_unavailable') from None
        _need(set(self._entries(base, deadline)) == set(names))
        return history, names

    def _create_chain(self, record, history):
        r = history.get(_r_name(record))
        g = history.get(_g_name(record['session_ref']))
        _need(r is not None and r[0] == record and g is not None
              and g[0]['r_parent'] == r[1])
        c = history.get(_stage_name(record, 'C'))
        locator = history.get(_i_session(record['session_ref']))
        native = None
        if c is not None:
            identity = dict(record, sid=c[0]['sid'])
            native = history.get(_i_native(identity))
        _need(locator is None or c is not None)
        a = history.get(_stage_name(record, 'A'))
        parents = dict(R=r[1], G=g[1], C=None if c is None else c[1],
                       I_session=None if locator is None else locator[1],
                       I_native=None if native is None else native[1],
                       A=None if a is None else a[1])
        return dto.BoundCreateReceipt(record, 'unknown' if a is None else 'accepted', parents)

    def _return(self, base, deadline, snapshot, value, *, absent=()):
        history, names = snapshot
        pins = tuple(pin for _, pin in history.values())
        window = self._terminal_window(base, deadline)
        _need(set(self._listing(base, deadline, window=window)) == set(names))
        pair = () if value is None else tuple(dto._capture(pin) for pin in value.parents.values()
                                             if pin is not None)
        if type(value) is dto.BoundStopReceipt:
            a = history[value.record['origin_parent']['filename']]
            pair = tuple(a[0]['parents'].values()) + (a[1],) + pair
        self._final_fences(base, pins, deadline, window=window, pair=pair)
        _need(set(self._listing(base, deadline, window=window)) == set(names))
        for name in absent:
            try:
                os.stat(name, dir_fd=window[0].directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                _need(False)
        self._finish_window(base, window)
        return value

    def _lookup(self, base, reference, project, root, operation, deadline, history):
        observed, names = history
        identity = dict(context_ref=reference, project=project, root=root, operation_id=operation)
        name = _r_name(identity)
        matched = [value for filename, (value, _) in observed.items()
                   if filename.startswith('BG-') and all(value[key] == item for key, item in identity.items())]
        _need(len(matched) <= 1)
        r = observed.get(name)
        if r is None:
            _need(not matched)
            return self._return(base, deadline, history, None, absent=(name,))
        _need(len(matched) == 1 and all(r[0][key] == item for key, item in identity.items()))
        return self._return(base, deadline, history, self._create_chain(r[0], observed))

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

    def _publish_leaf(self, base, name, record, deadline, *, parents=(), absent=(), names=(), raw=None):
        raw = dto._canonical(record) if raw is None else raw
        _need(len(raw) <= 4096)
        held = self._tick(base, deadline)
        _need(len(self._entries(base, deadline)) < 10000)
        temp = '.tmp-' + uuid.uuid4().hex
        fd = None
        try:
            self._tick(base, deadline)
            _need(set(self._listing(base, deadline)) == set(names))
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=held.directory)
            os.fchmod(fd, 0o600)
            view = memoryview(raw)
            while view:
                self._tick(base, deadline)
                written = os.write(fd, view)
                _need(written > 0)
                view = view[written:]
            window = self._terminal_window(base, deadline)
            self._window_check(base, window)
            os.fsync(fd)
            self._window_check(base, window)
            _need(set(self._listing(base, deadline, 10002, window=window)) == set(names) | {temp})
            info = self._leaf_info(fd, held.uid)
            _need(_pin(info) == _pin(os.stat(temp, dir_fd=held.directory, follow_symlinks=False)))
            temporary = dict(filename=temp, dev=info.st_dev, ino=info.st_ino,
                             ctime_ns=info.st_ctime_ns, sha256=hashlib.sha256(raw).hexdigest())
            self._final_fences(base, parents, deadline, window=window, pair=(temporary,))
            for missing in absent:
                try:
                    os.stat(missing, dir_fd=held.directory, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    _need(False)
            self._window_check(base, window)
            _need(held.rename(held.directory, temp.encode('utf-8'),
                              held.directory, name.encode('utf-8'), 1) == 0)
            os.fsync(held.directory)
            self._window_check(base, window)
            _need(_pin(self._leaf_info(fd, held.uid)) == _pin(os.stat(name, dir_fd=held.directory, follow_symlinks=False)))
            expected = set(names) | {name}
            _need(set(self._listing(base, deadline, window=window)) == expected)
            self._finish_window(base, window)
        finally:
            if fd is not None:
                os.close(fd)
        stored, pin = self._read(base, name, deadline)
        _need(stored == record)
        return pin

    @_safe
    def publish_create(self, base, context_ref, prepared, deadline):
        reference = self._context(context_ref)
        _need(type(prepared) is dto.PreparedBoundCreate, 'invalid_request')
        checked = self._codec._value(prepared, False, reference)
        record = dto._capture(checked.record)
        self._base(base, absent=True)
        _need(base is not None)
        self._platform()
        self._tick(base, deadline)
        history = self._history(base, deadline)
        previous = self._lookup(base, reference, record['project'], record['root'], record['operation_id'], deadline, history)
        if previous is not None:
            _need(dto._capture(previous.record) == record)
            return previous
        global_history, names = history
        _need(_g_name(record['session_ref']) not in global_history
              and _i_session(record['session_ref']) not in global_history)
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
        self._publish_leaf(base, _g_name(record['session_ref']), g, deadline, parents=historical_pins + (r_pin,),
                           names=tuple(names) + (_r_name(record),))
        final = self._lookup(base, reference, record['project'], record['root'],
                             record['operation_id'], deadline, self._history(base, deadline))
        _need(final is not None and dto._capture(final.record) == record)
        return final

    def _checked_receipt(self, reference, value, stop=False):
        expected = dto.BoundStopReceipt if stop else dto.BoundCreateReceipt
        _need(type(value) is expected, 'invalid_request')
        return self._codec._value(value, stop, reference)

    def _claim(self, supplied, observed):
        _need(observed is not None and dto._capture(supplied.record) == dto._capture(observed.record))
        for role, pin in supplied.parents.items():
            if pin is not None:
                _need(dto._capture(pin) == dto._capture(observed.parents[role]))
        if supplied.status == 'accepted':
            _need(observed.status == 'accepted')
        return observed

    def _locator(self, base, reference, root, session, deadline):
        """Context and root precede any parent interpretation or global scan."""
        value, pin = self._read(base, _i_session(session), deadline)
        if value is not None:
            try:
                captured = dto._reference(value.get('context_ref'))
            except Exception:
                raise AccountError('store_unavailable') from None
            _need(captured == reference, 'context_drift')
            _need(value.get('root') == root and value.get('session_ref') == session, 'context_drift')
        return value, pin

    def _current_create(self, base, reference, receipt, deadline):
        record = receipt.record
        self._base(base, absent=True)
        _need(base is not None)
        self._platform()
        self._tick(base, deadline)
        self._locator(base, reference, record['root'], record['session_ref'], deadline)
        snapshot = self._history(base, deadline)
        observed = self._lookup(base, reference, record['project'], record['root'],
                                record['operation_id'], deadline, snapshot)
        return self._claim(receipt, observed), snapshot

    def _write_stage(self, base, name, record, deadline, snapshot, *, absent=(), raw=None):
        history, names = snapshot
        _need(name not in history and name not in names)
        return self._publish_leaf(base, name, record, deadline,
                                  parents=tuple(pin for _, pin in history.values()),
                                  absent=absent, names=names, raw=raw)

    @_safe
    def capture_candidate(self, base, context_ref, receipt, sid, deadline):
        reference = self._context(context_ref)
        checked = self._checked_receipt(reference, receipt)
        _sid(sid)
        current, snapshot = self._current_create(base, reference, checked, deadline)
        history = snapshot[0]
        name = _stage_name(current.record, 'C')
        candidate = dict(schema=1, kind='bound_session_candidate',
                         r_parent=dto._capture(current.parents['R']),
                         g_parent=dto._capture(current.parents['G']), sid=sid)
        if current.parents['C'] is not None:
            _need(history[name][0] == candidate)
            return current
        _need(current.status == 'unknown'
              and all(current.parents[role] is None for role in ('I_session', 'I_native', 'A')))
        self._write_stage(base, name, candidate, deadline, snapshot)
        return self._current_create(base, reference, checked, deadline)[0]

    @_safe
    def publish_origin(self, base, context_ref, receipt, deadline):
        reference = self._context(context_ref)
        checked = self._checked_receipt(reference, receipt)
        current, snapshot = self._current_create(base, reference, checked, deadline)
        _need(current.parents['C'] is not None)
        c = snapshot[0][_stage_name(current.record, 'C')][0]
        origin = {key: current.record[key] for key in
                  ('context_ref', 'project', 'root', 'session_ref', 'operation_id')}
        origin = dto._capture(origin)
        origin.update(schema=1, kind='bound_session_origin', sid=c['sid'],
                      r_parent=dto._capture(current.parents['R']),
                      g_parent=dto._capture(current.parents['G']),
                      c_parent=dto._capture(current.parents['C']))
        # Check both locators before the first write. One-I recovery is allowed
        # only with this exact freshly committed chain and no authoritative A.
        for role, name in (('I_session', _i_session(origin['session_ref'])),
                           ('I_native', _i_native(origin))):
            item = snapshot[0].get(name)
            _need(item is None or item[0] == origin)
        # Preserve strict noncanonical JSON bytes when reconciling a single
        # matching I: the two immutable locator leaves must be byte-identical.
        raw = None
        if (current.parents['I_session'] is None) != (current.parents['I_native'] is None):
            pin = current.parents['I_session'] or current.parents['I_native']
            held = self._tick(base, deadline)
            fd, _, raw = self._fence_leaf(held, dto._capture(pin))
            os.close(fd)
        for role, name in (('I_session', _i_session(origin['session_ref'])),
                           ('I_native', _i_native(origin))):
            if current.parents[role] is None:
                _need(current.status == 'unknown' and current.parents['A'] is None)
                self._write_stage(base, name, origin, deadline, snapshot,
                                  absent=(_stage_name(current.record, 'A'),), raw=raw)
                current, snapshot = self._current_create(base, reference, checked, deadline)
        return current

    @_safe
    def accept_create(self, base, context_ref, receipt, deadline):
        reference = self._context(context_ref)
        checked = self._checked_receipt(reference, receipt)
        current, snapshot = self._current_create(base, reference, checked, deadline)
        _need(all(current.parents[role] is not None for role in
                  ('R', 'G', 'C', 'I_session', 'I_native')))
        if current.status == 'accepted':
            return current
        record = dict(schema=1, kind='bound_session_accepted',
                      parents={role: dto._capture(current.parents[role]) for role in
                               ('R', 'G', 'C', 'I_session', 'I_native')})
        self._write_stage(base, _stage_name(current.record, 'A'), record, deadline, snapshot)
        return self._current_create(base, reference, checked, deadline)[0]

    @_safe
    def lookup_origin(self, base, context_ref, root, session_ref, deadline):
        reference = self._context(context_ref)
        held = self._base(base, absent=True)
        dto._root(root)
        dto._uuid(session_ref)
        self._platform()
        self._remaining(deadline)
        if held is None:
            return None
        locator, _ = self._locator(base, reference, root, session_ref, deadline)
        snapshot = self._history(base, deadline)
        if locator is None:
            return self._return(base, deadline, snapshot, None, absent=(_i_session(session_ref),))
        return self._lookup(base, reference, locator['project'], root,
                            locator['operation_id'], deadline, snapshot)

    @_safe
    def prepare_stop(self, context_ref, origin, operation_id, host_id, invocation_id, deadline):
        reference = self._context(context_ref)
        checked = self._checked_receipt(reference, origin)
        _need(checked.status == 'accepted', 'invalid_request')
        dto._uuid(operation_id)
        dto._uuid(host_id)
        dto._hex(invocation_id, 32)
        self._remaining(deadline)
        try:
            created = self._clock()
        except Exception:
            raise AccountError('invalid_request') from None
        dto._integer(created, 1, 2**63 - 1)
        self._remaining(deadline)
        # Host association and once-only drain belong to the caller's journal.
        return self._codec.prepare_stop(reference, checked, operation_id, host_id,
                                        invocation_id, created)

    def _stop_chain(self, identity, history):
        s = history.get(_stop_name(identity, 'S'))
        t = history.get(_stop_name(identity, 'T'))
        if s is None:
            _need(t is None)
            return None
        _need(all(s[0][key] == identity[key] for key in
                  ('context_ref', 'root', 'session_ref', 'operation_id')))
        return dto.BoundStopReceipt(s[0], 'unknown' if t is None else 'accepted',
                                     dict(S=s[1], T=None if t is None else t[1]))

    def _current_stop(self, base, reference, record, deadline):
        self._base(base, absent=True)
        _need(base is not None)
        self._platform()
        self._tick(base, deadline)
        self._locator(base, reference, record['root'], record['session_ref'], deadline)
        snapshot = self._history(base, deadline)
        return self._stop_chain(record, snapshot[0]), snapshot

    def _stop_origin(self, record, history):
        locator = history.get(_i_session(record['session_ref']))
        _need(locator is not None)
        r = history.get(_r_name(locator[0]))
        _need(r is not None)
        origin = self._create_chain(r[0], history)
        _need(origin.status == 'accepted'
              and all(origin.record[key] == record[key] for key in ('context_ref', 'root', 'session_ref'))
              and dto._capture(origin.parents['A']) == record['origin_parent'])

    @_safe
    def publish_stop(self, base, context_ref, prepared, deadline):
        reference = self._context(context_ref)
        _need(type(prepared) is dto.PreparedBoundStop, 'invalid_request')
        checked = self._codec._value(prepared, True, reference)
        record = dto._capture(checked.record)
        current, snapshot = self._current_stop(base, reference, record, deadline)
        self._stop_origin(record, snapshot[0])
        if current is not None:
            _need(dto._capture(current.record) == record)
            return self._return(base, deadline, snapshot, current)
        self._write_stage(base, _stop_name(record, 'S'), record, deadline, snapshot,
                          absent=(_stop_name(record, 'T'),))
        current, snapshot = self._current_stop(base, reference, record, deadline)
        _need(current is not None)
        self._stop_origin(record, snapshot[0])
        return self._return(base, deadline, snapshot, current)

    @_safe
    def lookup_stop(self, base, context_ref, root, session_ref, operation_id, deadline):
        reference = self._context(context_ref)
        held = self._base(base, absent=True)
        dto._root(root)
        dto._uuid(session_ref)
        dto._uuid(operation_id)
        self._platform()
        self._remaining(deadline)
        if held is None:
            return None
        record = dict(context_ref=reference, root=root, session_ref=session_ref,
                      operation_id=operation_id)
        current, snapshot = self._current_stop(base, reference, record, deadline)
        if current is not None:
            self._stop_origin(dto._capture(current.record), snapshot[0])
        return self._return(base, deadline, snapshot, current,
                            absent=() if current is not None else
                            (_stop_name(record, 'S'), _stop_name(record, 'T')))

    @_safe
    def accept_stop(self, base, context_ref, receipt, deadline):
        reference = self._context(context_ref)
        checked = self._checked_receipt(reference, receipt, True)
        record = dto._capture(checked.record)
        current, snapshot = self._current_stop(base, reference, record, deadline)
        current = self._claim(checked, current)
        self._stop_origin(record, snapshot[0])
        if current.status == 'accepted':
            return self._return(base, deadline, snapshot, current)
        terminal = dict(schema=1, kind='bound_session_stopped',
                        s_parent=dto._capture(current.parents['S']))
        self._write_stage(base, _stop_name(record, 'T'), terminal, deadline, snapshot)
        current, snapshot = self._current_stop(base, reference, record, deadline)
        current = self._claim(checked, current)
        self._stop_origin(record, snapshot[0])
        return self._return(base, deadline, snapshot, current)
