"""Immutable unarchive receipts; no native or session admission effects."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import math
import os
import threading
import time
from types import MappingProxyType

from _control_web_configured_create import ConfiguredCreateStore, _json, _safe
from _control_web_sessions import _DomainError, RenameStore, _budget, _need, valid_uuid


_FIELDS = {'schema', 'kind', 'context_id', 'root', 'sid', 'operation_id',
           'action', 'confirmation', 'digest', 'created', 'status'}


def _deadline(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, ValueError):
        valid = False
    _need(valid, 'invalid_request')
    _budget(value)


def _hex(value):
    return (type(value) is str and len(value) == 64
            and all(char in '0123456789abcdef' for char in value))


def _root(value):
    return (type(value) is str and os.path.isabs(value)
            and os.path.normpath(value) == value
            and not value.startswith('//')
            and all(not (ord(char) < 32 or 127 <= ord(char) <= 159
                         or 0xD800 <= ord(char) <= 0xDFFF) for char in value)
            and len(value.encode('utf-8')) <= 4096)


def _tuple(context_id, root, sid, operation_id, code='invalid_request'):
    _need(_hex(context_id) and _root(root) and valid_uuid(sid)
          and valid_uuid(operation_id), code)


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _key(context_id, root, sid, operation_id):
    return _hash({'kind': 'session_lifecycle_key', 'context_id': context_id,
                  'root': root, 'sid': sid, 'operation_id': operation_id})


def _name(record, stage):
    return 'L-' + _key(*(record[key] for key in
                         ('context_id', 'root', 'sid', 'operation_id'))) + '.' + stage + '.json'


def _digest(record):
    return _hash({key: record[key] for key in
                  ('kind', 'context_id', 'root', 'sid', 'action', 'confirmation')})


def _record(value, code='invalid_request'):
    _need(type(value) in (dict, MappingProxyType) and set(value) == _FIELDS, code)
    record = dict(value)
    _tuple(*(record[key] for key in ('context_id', 'root', 'sid', 'operation_id')), code=code)
    _need(type(record['schema']) is int and record['schema'] == 1
          and all(type(record[key]) is str for key in ('kind', 'action', 'confirmation', 'status'))
          and record['kind'] == 'session_lifecycle'
          and record['action'] == 'unarchive' and record['confirmation'] == 'restore_target'
          and type(record['created']) is int and 0 < record['created'] < 2**63
          and record['status'] in ('unknown', 'accepted') and _hex(record['digest']), code)
    _need(record['digest'] == _digest(record) and len(_json(record)) <= 4096, code)
    return record


def _parent(value, record, code='invalid_request'):
    _need(type(value) in (dict, MappingProxyType)
          and set(value) == {'filename', 'dev', 'ino', 'ctime_ns', 'sha256'}, code)
    parent = dict(value)
    _need(type(parent['filename']) is str and parent['filename'] == _name(record, 'R')
          and all(type(parent[key]) is int for key in ('dev', 'ino', 'ctime_ns'))
          and parent['dev'] >= 0 and parent['ino'] > 0 and parent['ctime_ns'] > 0
          and _hex(parent['sha256']), code)
    return parent


@dataclass(frozen=True, repr=False)
class LifecycleReservation:
    record: object = field(repr=False)
    r_parent: object = field(repr=False)

    def __post_init__(self):
        record = _record(self.record)
        parent = None if self.r_parent is None else _parent(self.r_parent, record)
        _need(parent is not None or record['status'] == 'unknown', 'invalid_request')
        object.__setattr__(self, 'record', MappingProxyType(record))
        object.__setattr__(self, 'r_parent', None if parent is None else MappingProxyType(parent))


@dataclass(frozen=True, repr=False)
class PreparedLifecycle(LifecycleReservation):
    r_parent: object = field(default=None, repr=False)

    def __post_init__(self):
        super().__post_init__()
        _need(self.r_parent is None and self.record['status'] == 'unknown', 'invalid_request')


class _NamespaceHandle:
    """Identity only: directory descriptor and lock lifetime stay store-owned."""
    __slots__ = ()


class LifecycleStore(RenameStore):
    """Reuse anchored private FS and immutable publication, with lifecycle schemas."""
    _read = ConfiguredCreateStore._read
    _publish = ConfiguredCreateStore._publish

    def __init__(self, path, *, clock=None):
        try:
            path = os.fspath(path)
        except TypeError:
            raise _DomainError('invalid_request') from None
        _need(type(path) is str and os.path.isabs(path)
              and (clock is None or callable(clock)), 'invalid_request')
        super().__init__(path)
        self.clock = time.time_ns if clock is None else clock
        self._active = {}

    @contextmanager
    def locked(self, deadline, create=False):
        _deadline(deadline)
        _need(type(create) is bool, 'invalid_request')
        try:
            with super().locked(deadline, create=create) as base:
                handle = None
                if base is not None:
                    info = os.fstat(base)
                    handle = _NamespaceHandle()
                    self._active[handle] = (base, threading.get_ident(), info.st_dev, info.st_ino)
                try:
                    yield handle
                finally:
                    if handle is not None:
                        self._active.pop(handle, None)
        except _DomainError:
            raise
        except Exception:
            raise _DomainError('unavailable') from None

    def _held(self, base, deadline):
        _deadline(deadline)
        _need(type(base) is _NamespaceHandle and base in self._active)
        fd, owner, dev, ino = self._active[base]
        _need(owner == threading.get_ident())
        info = os.fstat(fd)
        _need((dev, ino) == (info.st_dev, info.st_ino))
        self._anchor(fd, deadline)
        return fd

    @_safe
    def capacity(self, base, deadline):
        # Private publication primitive receives the store-owned FD, never a caller FD.
        _need(type(base) is int and any(
            state[0] == base and state[1] == threading.get_ident()
            for state in self._active.values()))
        self._anchor(base, deadline)
        # SIMPLIFIED: one held namespace flock covers all stages and capacity.
        # Count every orphan/unknown entry; no cleanup or per-operation lock order.
        count = 0
        with os.scandir(base) as entries:
            for entry in entries:
                _budget(deadline)
                count += 1
                _need(count < 10000)
                fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=base)
                try:
                    self._check(fd, deadline)
                    before = os.fstat(fd)
                    _need(before.st_size <= 4096 and self._pin(before) ==
                          self._pin(os.stat(entry.name, dir_fd=base, follow_symlinks=False)))
                finally:
                    os.close(fd)
        self._anchor(base, deadline)

    def _chain(self, base, context_id, root, sid, operation_id, deadline):
        base = self._held(base, deadline)
        key = _key(context_id, root, sid, operation_id)
        r_name, a_name = 'L-' + key + '.R.json', 'L-' + key + '.A.json'
        r_value, r_parent = self._read(base, r_name, deadline)
        a_value, a_parent = self._read(base, a_name, deadline)
        if r_value is None:
            _need(a_value is None)
            return None
        record = _record(r_value, 'unavailable')
        _need(record['status'] == 'unknown'
              and (record['context_id'], record['root'], record['sid'], record['operation_id'])
              == (context_id, root, sid, operation_id))
        _parent(r_parent, record, 'unavailable')
        if a_value is not None:
            _need(set(a_value) == {'schema', 'kind', 'record', 'parent'}
                  and type(a_value['schema']) is int and a_value['schema'] == 1
                  and a_value['kind'] == 'session_lifecycle_accepted')
            accepted = _record(a_value['record'], 'unavailable')
            parent = _parent(a_value['parent'], record, 'unavailable')
            _need(accepted == record | {'status': 'accepted'} and parent == r_parent)
            record = accepted
        _need(self._read(base, r_name, deadline) == (r_value, r_parent)
              and self._read(base, a_name, deadline) == (a_value, a_parent))
        return LifecycleReservation(record, r_parent)

    @_safe
    def lookup(self, base, context_id, root, sid, operation_id, deadline):
        _deadline(deadline)
        _tuple(context_id, root, sid, operation_id)
        if base is None:
            return None
        return self._chain(base, context_id, root, sid, operation_id, deadline)

    @_safe
    def prepare_reservation(self, context_id, root, sid, operation_id, action,
                            confirmation, deadline):
        _deadline(deadline)
        _tuple(context_id, root, sid, operation_id)
        _need(type(action) is str and action == 'unarchive'
              and type(confirmation) is str and confirmation == 'restore_target', 'invalid_request')
        try:
            created = self.clock()
        except Exception:
            raise _DomainError('invalid_request') from None
        _deadline(deadline)
        _need(type(created) is int and 0 < created < 2**63, 'invalid_request')
        record = {'schema': 1, 'kind': 'session_lifecycle', 'context_id': context_id,
                  'root': root, 'sid': sid, 'operation_id': operation_id,
                  'action': action, 'confirmation': confirmation, 'created': created,
                  'status': 'unknown'}
        record['digest'] = _digest(record)
        return PreparedLifecycle(record)

    @_safe
    def publish_reservation(self, base, prepared, deadline):
        self._held(base, deadline)
        _need(type(prepared) is PreparedLifecycle, 'invalid_request')
        record = _record(prepared.record)
        identity = tuple(record[key] for key in ('context_id', 'root', 'sid', 'operation_id'))
        previous = self.lookup(base, *identity, deadline)
        if previous is not None:
            _need(previous.record['digest'] == record['digest'], 'invalid_request')
            return previous
        def absent():
            _need(self.lookup(base, *identity, deadline) is None)
        def published():
            current = self.lookup(base, *identity, deadline)
            _need(current is not None and dict(current.record) == record)
        self._publish(self._held(base, deadline), _name(record, 'R'), record,
                      deadline, absent, published)
        return self.lookup(base, *identity, deadline)

    @_safe
    def reserve(self, base, context_id, root, sid, operation_id, action, confirmation, deadline):
        _deadline(deadline)
        _tuple(context_id, root, sid, operation_id)
        _need(type(action) is str and action == 'unarchive'
              and type(confirmation) is str and confirmation == 'restore_target', 'invalid_request')
        previous = self.lookup(base, context_id, root, sid, operation_id, deadline)
        if previous is not None:
            return previous
        prepared = self.prepare_reservation(context_id, root, sid, operation_id,
                                             action, confirmation, deadline)
        return self.publish_reservation(base, prepared, deadline)

    def _current(self, base, reservation, deadline):
        self._held(base, deadline)
        _need(type(reservation) is LifecycleReservation and reservation.r_parent is not None,
              'invalid_request')
        record = _record(reservation.record)
        current = self.lookup(base, *(record[key] for key in
                              ('context_id', 'root', 'sid', 'operation_id')), deadline)
        _need(current is not None and current.r_parent == reservation.r_parent
              and (dict(current.record) | {'status': record['status']}) == record)
        _need(record['status'] != 'accepted' or current.record['status'] == 'accepted')
        return current

    @_safe
    def accept(self, base, reservation, deadline):
        current = self._current(base, reservation, deadline)
        if current.record['status'] == 'accepted':
            return current
        record = dict(current.record)
        identity = tuple(record[key] for key in ('context_id', 'root', 'sid', 'operation_id'))
        value = {'schema': 1, 'kind': 'session_lifecycle_accepted',
                 'record': record | {'status': 'accepted'}, 'parent': dict(current.r_parent)}
        self._publish(self._held(base, deadline), _name(record, 'A'), value, deadline,
                      lambda: self._current(base, current, deadline))
        return self.lookup(base, *identity, deadline)
