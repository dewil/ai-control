"""Private metadata-only create receipts and bindings; never native admission."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import ctypes
import fcntl
import functools
import hashlib
import json
import os
import re
import stat
import time
from types import MappingProxyType
import uuid

from _control_provider_accounts import AccountError
from _control_provider_context import ExecutionContext, validate_context_ref
from _control_web_sessions import RenameStore, _pairs, valid_project, valid_uuid


def _need(condition, code='store_unavailable'):
    if not condition:
        raise AccountError(code)


def _safe(method):
    @functools.wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except AccountError:
            raise
        except Exception:
            raise AccountError('store_unavailable') from None
    return call


def _plain(value):
    if hasattr(value, 'items'):
        return {key: _plain(item) for key, item in value.items()}
    return value


def _freeze(value):
    return MappingProxyType({key: _freeze(item) if type(item) is dict else item
                             for key, item in value.items()})


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _ref(value):
    return validate_context_ref(_plain(value))


def _context(value):
    _need(type(value) is ExecutionContext, 'context_invalid')
    return _ref(value.reference)


def _root(resolver, project):
    _need(valid_project(project), 'invalid_request')
    root = resolver(project)
    _need(type(root) is str and os.path.isabs(root)
          and os.path.realpath(root) == root and os.path.isdir(root), 'stale')
    return root


def _receipt_name(project, operation_id):
    return _stage_name('create_receipt', project, operation_id)


def _stage_name(kind, project, operation_id):
    return _hash({'kind': kind, 'project': project,
                  'operation_id': operation_id}) + '.json'


def _digest(record):
    return _hash({key: record[key] for key in
                  ('kind', 'operation_id', 'project', 'root', 'context_ref')})


def _binding(record):
    sid = record['candidate_sid']
    _need(valid_uuid(sid), 'invalid_request')
    context_key = _hash(record['context_ref'])
    return {'schema': 1, 'kind': 'session_binding',
            'session_ref': _hash({'kind': 'session_binding', 'context_key': context_key, 'sid': sid}),
            'sid': sid, 'project': record['project'], 'root': record['root'],
            'context_ref': record['context_ref'], 'create_operation_id': record['operation_id'],
            'create_digest': record['digest']}


def _validate(record, binding=False):
    keys = ({'schema', 'kind', 'session_ref', 'sid', 'project', 'root', 'context_ref',
             'create_operation_id', 'create_digest'} if binding else
            {'schema', 'kind', 'operation_id', 'digest', 'project', 'root', 'context_ref',
             'candidate_sid', 'status', 'created'})
    _need(type(record) is dict and set(record) == keys)
    _need(type(record['schema']) is int and record['schema'] == 1
          and record['kind'] == ('session_binding' if binding else 'session_create')
          and valid_project(record['project']) and type(record['root']) is str
          and os.path.isabs(record['root']))
    try:
        _need(_ref(record['context_ref']) == record['context_ref'])
    except AccountError:
        raise AccountError('store_unavailable') from None
    if binding:
        _need(valid_uuid(record['sid']) and valid_uuid(record['create_operation_id'])
              and type(record['create_digest']) is str
              and re.fullmatch('[0-9a-f]{64}', record['create_digest']) is not None)
        expected = _hash({'kind': 'session_binding', 'context_key': _hash(record['context_ref']),
                          'sid': record['sid']})
        _need(record['session_ref'] == expected)
    else:
        _need(valid_uuid(record['operation_id']) and record['status'] in ('unknown', 'accepted')
              and type(record['created']) is int and record['created'] > 0
              and (record['candidate_sid'] is None or valid_uuid(record['candidate_sid']))
              and (record['status'] != 'accepted' or record['candidate_sid'] is not None)
              and record['digest'] == _digest(record))
    return record


@dataclass(frozen=True, repr=False)
class CreateReservation:
    record: object = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'record', _freeze(_validate(_plain(self.record))))


@dataclass(frozen=True, repr=False)
class SessionBinding:
    record: object = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'record', _freeze(_validate(_plain(self.record), True)))


class _Files(RenameStore):
    """Reuse reviewed private-root, no-follow, inode and filesystem fences."""
    def read(self, name, deadline):
        try:
            base = self._base(False, deadline)
        except FileNotFoundError:
            return None, None
        try:
            self._anchor(base, deadline)
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=base)
            except FileNotFoundError:
                return None, None
            try:
                self._check(fd, deadline)
                info = os.fstat(fd)
                _need(info.st_size <= 4096)
                data = os.read(fd, 4097)
                _need(len(data) <= 4096 and os.read(fd, 1) == b'')
                record = json.loads(data, object_pairs_hook=_pairs,
                                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                _need(self._pin(info) == self._pin(os.fstat(fd)) ==
                      self._pin(os.stat(name, dir_fd=base, follow_symlinks=False)))
                self._anchor(base, deadline)
                commitment = {'filename': name, 'dev': info.st_dev, 'ino': info.st_ino,
                              'ctime_ns': info.st_ctime_ns,
                              'sha256': hashlib.sha256(data).hexdigest()}
                return record, commitment
            finally:
                os.close(fd)
        finally:
            os.close(base)

    def publish(self, name, record, deadline, fence=lambda: None):
        data = _json(record)
        _need(len(data) <= 4096)
        # One stable directory lock reserves capacity through publication.
        # Fence reads take no namespace locks, so no inverse lock ordering.
        with self.locked(deadline, create=True) as base:
            self._publish(base, name, record, data, deadline, fence)

    def _publish(self, base, name, record, data, deadline, fence):
        temp, fd = '.tmp-' + uuid.uuid4().hex, None
        try:
            self.capacity(base, deadline)
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=base)
            os.fchmod(fd, 0o600)
            view = memoryview(data)
            while view:
                self._check(fd, deadline)
                written = os.write(fd, view)
                _need(written > 0)
                view = view[written:]
            os.fsync(fd)
            self._anchor(base, deadline)
            self._check(fd, deadline)
            _need(self._pin(os.fstat(fd)) == self._pin(os.stat(temp, dir_fd=base, follow_symlinks=False)))
            fence()
            renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
            renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
            renameat2.restype = ctypes.c_int
            if renameat2(base, os.fsencode(temp), base, os.fsencode(name), 1):
                code = ctypes.get_errno()
                raise OSError(code, os.strerror(code))
            os.fsync(base)
            self._anchor(base, deadline)
            self._check(fd, deadline)
            _need(self._pin(os.fstat(fd)) == self._pin(os.stat(name, dir_fd=base, follow_symlinks=False)))
            published, _ = self.read(name, deadline)
            _need(published == record)
            fence()
            self._anchor(base, deadline)
            self._check(fd, deadline)
            _need(self._pin(os.fstat(fd)) == self._pin(os.stat(name, dir_fd=base, follow_symlinks=False)))
        finally:
            if fd is not None:
                os.close(fd)
            # Failed publication leaves a counted private orphan. Pathname
            # cleanup cannot prove ownership after a same-owner path swap.


class _Locks(_Files):
    @contextmanager
    def hold(self, key, deadline):
        base = self._base(True, deadline)
        fd = None
        provisioning = False
        try:
            name = key + '.lock'
            while True:
                self._check(base, deadline, True)
                try:
                    fcntl.flock(base, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    provisioning = True
                    break
                except BlockingIOError:
                    time.sleep(.01)
            self._anchor(base, deadline)
            try:
                os.stat(name, dir_fd=base, follow_symlinks=False)
            except FileNotFoundError:
                count = 0
                with os.scandir(base) as entries:
                    for entry in entries:
                        self._check(base, deadline, True)
                        count += 1
                        _need(count < 10002 and re.fullmatch('[0-9a-f]{64}\\.lock', entry.name))
                _need(count < 10000)
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=base)
            self._check(fd, deadline)
            os.fsync(fd)
            os.fsync(base)
            self._anchor(base, deadline)
            _need(self._pin(os.fstat(fd)) == self._pin(os.stat(name, dir_fd=base, follow_symlinks=False)))
            # Never wait for a leaf while holding the provisioning directory:
            # a writer holding an operation leaf may need a binding leaf next.
            fcntl.flock(base, fcntl.LOCK_UN)
            provisioning = False
            while True:
                self._check(fd, deadline)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(.01)
            self._anchor(base, deadline)
            _need(self._pin(os.fstat(fd)) == self._pin(os.stat(name, dir_fd=base, follow_symlinks=False)))
            yield
        finally:
            if provisioning:
                fcntl.flock(base, fcntl.LOCK_UN)
            if fd is not None:
                os.close(fd)
            os.close(base)


def _deadline():
    return time.monotonic() + 5


def _operation_key(project, operation_id):
    return _hash({'kind': 'create_operation', 'project': project, 'operation_id': operation_id})


def _authority(current, supplied):
    _need(all(current[key] == supplied[key] for key in
              ('schema', 'kind', 'operation_id', 'digest', 'project', 'root', 'context_ref', 'created')),
          'store_conflict')


def _parent(actual, expected):
    _need(type(actual) is dict and set(actual) == {'filename', 'dev', 'ino', 'ctime_ns', 'sha256'}
          and type(actual['filename']) is str
          and re.fullmatch('[0-9a-f]{64}\\.json', actual['filename'])
          and all(type(actual[key]) is int and actual[key] >= 0 for key in ('dev', 'ino', 'ctime_ns'))
          and type(actual['sha256']) is str and re.fullmatch('[0-9a-f]{64}', actual['sha256'])
          and actual == expected)


def _chain(receipts, bindings, project, operation_id, deadline):
    names = [_stage_name(kind, project, operation_id) for kind in
             ('create_receipt', 'create_candidate', 'create_accepted')]
    stages = [receipts.read(name, deadline) for name in names]
    (initial, r_pin), (candidate, c_pin), (accepted, a_pin) = stages
    if initial is None:
        _need(candidate is None and accepted is None)
        return None, {}
    _validate(initial)
    _need(initial['project'] == project and initial['operation_id'] == operation_id
          and initial['candidate_sid'] is None and initial['status'] == 'unknown')
    record, pins = initial, {'R': r_pin}
    if candidate is not None:
        _need(type(candidate) is dict and set(candidate) == {'schema', 'kind', 'record', 'parent'}
              and type(candidate['schema']) is int and candidate['schema'] == 1
              and candidate['kind'] == 'session_create_candidate')
        _parent(candidate['parent'], r_pin)
        record = _validate(candidate['record'])
        _need(valid_uuid(record['candidate_sid']) and record['status'] == 'unknown'
              and record == {**initial, 'candidate_sid': record['candidate_sid']})
        pins['C'] = c_pin
    if accepted is not None:
        _need(candidate is not None and type(accepted) is dict
              and set(accepted) == {'schema', 'kind', 'record', 'parent', 'binding'}
              and type(accepted['schema']) is int and accepted['schema'] == 1
              and accepted['kind'] == 'session_create_accepted')
        _parent(accepted['parent'], c_pin)
        final = _validate(accepted['record'])
        _need(final == {**record, 'status': 'accepted'})
        expected_binding = _binding(record)
        binding, b_pin = bindings.read(expected_binding['session_ref'] + '.json', deadline)
        _need(binding is not None)
        _validate(binding, True)
        _need(binding == expected_binding)
        _parent(accepted['binding'], b_pin)
        record, pins['A'], pins['B'] = final, a_pin, b_pin
    # Stages are immutable for cooperating writers. Recheck exact named
    # snapshots before export to refuse observed external inode/byte drift.
    for name, (_, snapshot) in zip(names, stages):
        _, current = receipts.read(name, deadline)
        _need(current == snapshot)
    if 'B' in pins:
        _, current = bindings.read(pins['B']['filename'], deadline)
        _need(current == pins['B'])
    return record, pins


class SessionBindings:
    @_safe
    def __init__(self, binding_root, lock_root, receipt_root, project_path):
        _need(callable(project_path), 'invalid_request')
        self.files, self.locks = _Files(binding_root), _Locks(lock_root)
        self.receipts, self.project_path = _Files(receipt_root), project_path
        _need(len({self.files.path, self.locks.path, self.receipts.path}) == 3)

    def _receipt(self, supplied, deadline):
        root = _root(self.project_path, supplied['project'])
        _need(root == supplied['root'], 'stale')
        record, pins = _chain(self.receipts, self.files, supplied['project'], supplied['operation_id'], deadline)
        _need(record is not None)
        _validate(record)
        _need(record['root'] == root, 'stale')
        _authority(record, supplied)
        _need(supplied['candidate_sid'] is None or supplied['candidate_sid'] == record['candidate_sid'],
              'store_conflict')
        _need(supplied['status'] != 'accepted' or record['status'] == 'accepted')
        return record, pins

    def _exact_binding(self, record, deadline):
        expected = _binding(record)
        actual, _ = self.files.read(expected['session_ref'] + '.json', deadline)
        _need(actual is not None)
        _validate(actual, True)
        _need(actual == expected)
        return actual

    @_safe
    def publish_candidate(self, reservation):
        _need(type(reservation) is CreateReservation, 'invalid_request')
        supplied = _plain(reservation.record)
        deadline = _deadline()
        with self.locks.hold(_operation_key(supplied['project'], supplied['operation_id']), deadline):
            record, _ = self._receipt(supplied, deadline)
            expected = _binding(record)
            with self.locks.hold(expected['session_ref'], deadline):
                actual, _ = self.files.read(expected['session_ref'] + '.json', deadline)
                if actual is None:
                    _need(record['status'] != 'accepted')
                    self.files.publish(expected['session_ref'] + '.json', expected, deadline,
                                       fence=lambda: self._receipt(record, deadline))
                else:
                    _validate(actual, True)
                    _need(actual == expected, 'store_conflict')
                return SessionBinding(expected)

    @_safe
    def resolve(self, project, session_ref, sid):
        root = _root(self.project_path, project)
        _need(type(session_ref) is str and re.fullmatch('[0-9a-f]{64}', session_ref)
              and valid_uuid(sid), 'invalid_request')
        deadline = _deadline()
        binding, _ = self.files.read(session_ref + '.json', deadline)
        if binding is None:
            return None
        _validate(binding, True)
        _need(binding['session_ref'] == session_ref and binding['sid'] == sid
              and binding['project'] == project)
        _need(binding['root'] == root, 'stale')
        record, _ = _chain(self.receipts, self.files, project, binding['create_operation_id'], deadline)
        _need(record is not None)
        _validate(record)
        _need(record['root'] == root, 'stale')
        _need(record['candidate_sid'] is not None and _binding(record) == binding)
        _need(_root(self.project_path, project) == root, 'stale')
        return SessionBinding(binding) if record['status'] == 'accepted' else None


class CreateStore:
    @_safe
    def __init__(self, receipt_root, bindings, project_path, *, clock=None):
        _need(type(bindings) is SessionBindings and callable(project_path), 'invalid_request')
        self.files = _Files(receipt_root)
        _need(self.files.path == bindings.receipts.path)
        self.bindings, self.project_path = bindings, project_path
        self.clock = time.time_ns if clock is None else clock
        _need(callable(self.clock), 'invalid_request')

    def _lookup(self, reference, project, root, operation_id, deadline):
        record, pins = _chain(self.files, self.bindings.files, project, operation_id, deadline)
        if record is None:
            _need(_root(self.project_path, project) == root, 'stale')
            return None, None
        _validate(record)
        _need(record['project'] == project and record['operation_id'] == operation_id)
        _need(record['root'] == root, 'stale')
        _need(record['context_ref'] == reference, 'store_conflict')
        if record['status'] == 'accepted':
            self.bindings._exact_binding(record, deadline)
        _need(_root(self.project_path, project) == root, 'stale')
        return record, pins

    @_safe
    def lookup(self, context, project, operation_id):
        reference = _context(context)
        _need(valid_uuid(operation_id), 'invalid_request')
        root = _root(self.project_path, project)
        record, _ = self._lookup(reference, project, root, operation_id, _deadline())
        return None if record is None else CreateReservation(record)

    @_safe
    def reserve(self, context, project, operation_id):
        reference = _context(context)
        _need(valid_uuid(operation_id), 'invalid_request')
        root, deadline = _root(self.project_path, project), _deadline()
        with self.bindings.locks.hold(_operation_key(project, operation_id), deadline):
            record, _ = self._lookup(reference, project, root, operation_id, deadline)
            if record is None:
                created = self.clock()
                _need(type(created) is int and created > 0, 'invalid_request')
                record = {'schema': 1, 'kind': 'session_create', 'operation_id': operation_id,
                          'project': project, 'root': root, 'context_ref': reference,
                          'candidate_sid': None, 'status': 'unknown', 'created': created}
                record['digest'] = _digest(record)
                def fence():
                    _need(_root(self.project_path, project) == root, 'stale')
                self.files.publish(_receipt_name(project, operation_id), record, deadline, fence=fence)
            return CreateReservation(record)

    @_safe
    def capture_candidate(self, reservation, sid):
        _need(type(reservation) is CreateReservation and valid_uuid(sid), 'invalid_request')
        supplied, deadline = _plain(reservation.record), _deadline()
        with self.bindings.locks.hold(_operation_key(supplied['project'], supplied['operation_id']), deadline):
            record, pins = self.bindings._receipt(supplied, deadline)
            if record['candidate_sid'] is None:
                record['candidate_sid'] = sid
                stage = {'schema': 1, 'kind': 'session_create_candidate',
                         'record': record, 'parent': pins['R']}
                def fence():
                    _, current = self.bindings._receipt(supplied, deadline)
                    _need(current['R'] == pins['R'])
                self.files.publish(_stage_name('create_candidate', record['project'], record['operation_id']),
                                   stage, deadline, fence=fence)
            else:
                _need(record['candidate_sid'] == sid, 'store_conflict')
                if record['status'] == 'accepted':
                    self.bindings._exact_binding(record, deadline)
            return CreateReservation(record)

    @_safe
    def commit_accepted(self, reservation, binding):
        _need(type(reservation) is CreateReservation and type(binding) is SessionBinding, 'invalid_request')
        supplied, deadline = _plain(reservation.record), _deadline()
        with self.bindings.locks.hold(_operation_key(supplied['project'], supplied['operation_id']), deadline):
            record, pins = self.bindings._receipt(supplied, deadline)
            expected = _binding(record)
            _need(_plain(binding.record) == expected, 'store_conflict')
            with self.bindings.locks.hold(expected['session_ref'], deadline):
                self.bindings._exact_binding(record, deadline)
                if record['status'] != 'accepted':
                    record['status'] = 'accepted'
                    _, binding_pin = self.bindings.files.read(expected['session_ref'] + '.json', deadline)
                    stage = {'schema': 1, 'kind': 'session_create_accepted', 'record': record,
                             'parent': pins['C'], 'binding': binding_pin}
                    def fence():
                        _, current = self.bindings._receipt(supplied, deadline)
                        _need(current['C'] == pins['C'])
                        self.bindings._exact_binding(record, deadline)
                        _, current_binding = self.bindings.files.read(expected['session_ref'] + '.json', deadline)
                        _need(current_binding == binding_pin)
                    self.files.publish(_stage_name('create_accepted', record['project'], record['operation_id']),
                                       stage, deadline, fence=fence)
                return CreateReservation(record)
