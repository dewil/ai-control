"""Once-only creation in an explicit configured legacy context, not account admission."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import copy
import ctypes
import functools
import hashlib
import json
import math
import os
import re
import time
from types import MappingProxyType
import uuid

from _control_web_sessions import (RenameStore, SessionChat, _DomainError, _budget,
                                   _need, _pairs, valid_project, valid_uuid)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _safe(method):
    @functools.wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except _DomainError:
            raise
        except Exception:
            raise _DomainError('unavailable') from None
    return call


def _plain(value):
    return {key: _plain(item) if hasattr(item, 'items') else item
            for key, item in value.items()}


def _freeze(value):
    return MappingProxyType({key: _freeze(item) if type(item) is dict else item
                             for key, item in value.items()})


def _hex(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _root(value):
    return (type(value) is str and os.path.isabs(value)
            and os.path.realpath(value) == value)


def _name(stage, project, operation_id):
    kind = {'R': 'configured_create_receipt', 'C': 'configured_create_candidate',
            'A': 'configured_create_accepted'}[stage]
    return _hash({'kind': kind, 'project': project, 'operation_id': operation_id}) + '.json'


def _origin_name(context_id, root, sid):
    return _hash({'kind': 'configured_session_origin', 'context_id': context_id,
                  'root': root, 'sid': sid}) + '.json'


def _digest(record):
    return _hash({key: record[key] for key in
                  ('kind', 'project', 'operation_id', 'context_id', 'root')} |
                 {'context_mode': 'configured', 'provider_id': 'codex'})


def _record(value):
    _need(type(value) is dict and set(value) == {'schema', 'kind', 'project',
          'operation_id', 'context_id', 'root', 'digest', 'status', 'sid', 'created'})
    _need(type(value['schema']) is int and value['schema'] == 1
          and value['kind'] == 'configured_session_create'
          and valid_project(value['project']) and valid_uuid(value['operation_id'])
          and _hex(value['context_id']) and _root(value['root'])
          and _hex(value['digest']) and value['digest'] == _digest(value)
          and value['status'] in ('unknown', 'accepted')
          and (value['sid'] is None or valid_uuid(value['sid']))
          and (value['status'] != 'accepted' or value['sid'] is not None)
          and type(value['created']) is int and value['created'] > 0)
    return value


def _parent(value):
    return (type(value) is dict and set(value) == {'filename', 'dev', 'ino', 'ctime_ns', 'sha256'}
            and type(value['filename']) is str
            and re.fullmatch(r'[0-9a-f]{64}\.json', value['filename']) is not None
            and all(type(value[key]) is int and value[key] >= 0 for key in ('dev', 'ino', 'ctime_ns'))
            and _hex(value['sha256']))


def _origin_valid(value):
    return (type(value) is dict and set(value) == {'schema', 'kind', 'project', 'operation_id',
            'context_id', 'root', 'sid', 'created', 'parent'}
            and type(value['schema']) is int and value['schema'] == 1
            and value['kind'] == 'configured_session_origin'
            and valid_project(value['project']) and valid_uuid(value['operation_id'])
            and _hex(value['context_id']) and _root(value['root']) and valid_uuid(value['sid'])
            and type(value['created']) is int and value['created'] > 0 and _parent(value['parent']))


@dataclass(frozen=True, repr=False)
class ConfiguredCreateReservation:
    record: object = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'record', _freeze(_record(_plain(self.record))))


@dataclass(frozen=True, repr=False)
class ConfiguredLoadedOrigin:
    reservation: ConfiguredCreateReservation = field(repr=False)
    context: object = field(repr=False)
    session: object = field(repr=False)

    def __post_init__(self):
        _need(type(self.reservation) is ConfiguredCreateReservation
              and self.reservation.record['status'] == 'accepted')
        object.__setattr__(self, 'context', _freeze(_plain(self.context)))
        object.__setattr__(self, 'session', _freeze(_plain(self.session)))


@dataclass(frozen=True, repr=False)
class ConfiguredUnavailableHistory(ConfiguredLoadedOrigin):
    needs_native_attention: bool = field(repr=False)

    def __post_init__(self):
        super().__post_init__()
        _need(type(self.needs_native_attention) is bool)


class ConfiguredCreateStore(RenameStore):
    """Immutable stages using the reviewed anchored private namespace primitives."""
    def __init__(self, path, *, clock=None):
        super().__init__(path)
        _need(clock is None or callable(clock), 'invalid_request')
        self.clock = clock if clock is not None else time.time_ns

    @contextmanager
    def locked(self, deadline, create=False):
        try:
            with super().locked(deadline, create) as base:
                yield base
        except _DomainError:
            raise
        except Exception:
            raise _DomainError('unavailable') from None

    def _read(self, base, name, deadline):
        _budget(deadline)
        if base is None:
            return None, None
        self._anchor(base, deadline)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=base)
        except FileNotFoundError:
            return None, None
        try:
            self._check(fd, deadline)
            before = os.fstat(fd)
            _need(before.st_size <= 4096)
            data = os.read(fd, 4097)
            _need(len(data) <= 4096 and os.read(fd, 1) == b'')
            value = json.loads(data.decode('utf-8'), object_pairs_hook=_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            _need(type(value) is dict)
            _need(self._pin(before) == self._pin(os.fstat(fd)) ==
                  self._pin(os.stat(name, dir_fd=base, follow_symlinks=False)))
            self._anchor(base, deadline)
            return value, {'filename': name, 'dev': before.st_dev, 'ino': before.st_ino,
                           'ctime_ns': before.st_ctime_ns,
                           'sha256': hashlib.sha256(data).hexdigest()}
        finally:
            os.close(fd)

    def _publish(self, base, name, value, deadline, fence, post_fence=None):
        data = _json(value)
        _need(base is not None and len(data) <= 4096)
        # SIMPLIFIED: one namespace lock covers stages and the bounded RPC;
        # no message lock is acquired here, avoiding inverse lock ordering.
        self.capacity(base, deadline)
        temp = '.tmp-' + uuid.uuid4().hex
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=base)
        try:
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
            _need(self._pin(os.fstat(fd)) == self._pin(os.stat(temp, dir_fd=base,
                                                             follow_symlinks=False)))
            fence()
            renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
            renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                 ctypes.c_char_p, ctypes.c_uint)
            renameat2.restype = ctypes.c_int
            if renameat2(base, os.fsencode(temp), base, os.fsencode(name), 1):
                code = ctypes.get_errno()
                raise OSError(code, os.strerror(code))
            os.fsync(base)
            self._anchor(base, deadline)
            self._check(fd, deadline)
            _need(self._pin(os.fstat(fd)) == self._pin(os.stat(name, dir_fd=base,
                                                             follow_symlinks=False)))
            actual, _ = self._read(base, name, deadline)
            _need(actual == value)
            (post_fence or fence)()
        finally:
            os.close(fd)
            # A failed publication leaves a counted orphan, never path-unlinks.

    def capacity(self, base, deadline):
        self._anchor(base, deadline)
        count = 0
        with os.scandir(base) as entries:
            for entry in entries:
                _budget(deadline)
                count += 1
                _need(count < 10002 and
                      re.fullmatch(r'(?:[0-9a-f]{64}\.json|\.tmp-[0-9a-f]{32})', entry.name))
                fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=base)
                try:
                    self._check(fd, deadline)
                    _need(self._pin(os.fstat(fd)) ==
                          self._pin(os.stat(entry.name, dir_fd=base, follow_symlinks=False)))
                finally:
                    os.close(fd)
        _need(count < 10000)
        self._anchor(base, deadline)

    @staticmethod
    def _origin_record(record, candidate_commitment):
        return {key: record[key] for key in ('project', 'operation_id', 'context_id',
                'root', 'sid', 'created')} | {'schema': 1, 'kind': 'configured_session_origin',
                                             'parent': candidate_commitment}

    def _chain(self, base, project, operation_id, deadline):
        names = {stage: _name(stage, project, operation_id) for stage in 'RCA'}
        stages = {stage: self._read(base, names[stage], deadline) for stage in 'RCA'}
        r, rp = stages['R']
        c, cp = stages['C']
        a, ap = stages['A']
        if r is None:
            _need(c is None and a is None)
            return None, stages
        _record(r)
        _need(r['project'] == project and r['operation_id'] == operation_id
              and r['status'] == 'unknown' and r['sid'] is None)
        current = r
        if c is not None:
            _need(set(c) == {'schema', 'kind', 'record', 'parent'}
                  and type(c['schema']) is int and c['schema'] == 1
                  and c['kind'] == 'configured_create_candidate'
                  and _parent(c['parent']) and c['parent'] == rp)
            _record(c['record'])
            _need(valid_uuid(c['record']['sid'])
                  and c['record'] == (r | {'sid': c['record']['sid']}))
            current = c['record']
        if a is not None:
            _need(c is not None and set(a) == {'schema', 'kind', 'record', 'parent', 'origin'}
                  and type(a['schema']) is int and a['schema'] == 1
                  and a['kind'] == 'configured_create_accepted'
                  and _parent(a['parent']) and a['parent'] == cp and _parent(a['origin']))
            _record(a['record'])
            _need(a['record'] == (current | {'status': 'accepted'}))
            i, ip = self._read(base, _origin_name(current['context_id'], current['root'],
                                                 current['sid']), deadline)
            _need(_origin_valid(i) and i == self._origin_record(current, cp)
                  and a['origin'] == ip and ip is not None)
            stages['I'] = (i, ip)
            current = a['record']
        # Recheck exact snapshots across the bounded read, including absence.
        for stage, original in stages.items():
            name = names[stage] if stage != 'I' else original[1]['filename']
            _need(self._read(base, name, deadline) == original)
        return ConfiguredCreateReservation(current), stages

    @_safe
    def lookup(self, base, project, operation_id, deadline):
        _need(valid_project(project) and valid_uuid(operation_id), 'invalid_request')
        return self._chain(base, project, operation_id, deadline)[0]

    @_safe
    def reserve(self, base, project, context_id, root, operation_id, deadline):
        _need(valid_project(project) and valid_uuid(operation_id)
              and _hex(context_id) and _root(root), 'invalid_request')
        previous, _ = self._chain(base, project, operation_id, deadline)
        if previous is not None:
            _need(previous.record['root'] == root and previous.record['context_id'] == context_id,
                  'invalid_request')
            return previous
        created = self.clock()
        _need(type(created) is int and created > 0, 'invalid_request')
        record = {'schema': 1, 'kind': 'configured_session_create', 'project': project,
                  'operation_id': operation_id, 'context_id': context_id, 'root': root,
                  'status': 'unknown', 'sid': None, 'created': created}
        record['digest'] = _digest(record)
        _record(record)
        name = _name('R', project, operation_id)
        self._publish(base, name, record, deadline,
                      lambda: _need(self._read(base, name, deadline) == (None, None)),
                      lambda: _need(self._read(base, name, deadline)[0] == record))
        return self.lookup(base, project, operation_id, deadline)

    def _current(self, base, reservation, deadline):
        _need(type(reservation) is ConfiguredCreateReservation, 'invalid_request')
        record = _record(_plain(reservation.record))
        current, stages = self._chain(base, record['project'], record['operation_id'], deadline)
        _need(current is not None)
        comparable = _plain(current.record) | {'status': record['status'], 'sid': record['sid']}
        _need(comparable == record)
        if record['sid'] is not None:
            _need(current.record['sid'] == record['sid'])
        if record['status'] == 'accepted':
            _need(current.record['status'] == 'accepted')
        return current, stages

    @_safe
    def candidate(self, base, reservation, sid, deadline):
        _need(valid_uuid(sid), 'invalid_request')
        current, stages = self._current(base, reservation, deadline)
        if current.record['sid'] is not None:
            _need(current.record['sid'] == sid, 'invalid_request')
            return current
        record = _plain(current.record) | {'sid': sid}
        value = {'schema': 1, 'kind': 'configured_create_candidate', 'record': record,
                 'parent': stages['R'][1]}
        name = _name('C', record['project'], record['operation_id'])
        self._publish(base, name, value, deadline,
                      lambda: self._current(base, current, deadline))
        return self.lookup(base, record['project'], record['operation_id'], deadline)

    @_safe
    def origin(self, base, reservation, deadline):
        current, stages = self._current(base, reservation, deadline)
        record = _plain(current.record)
        _need(record['sid'] is not None, 'invalid_request')
        value = self._origin_record(record, stages['C'][1])
        name = _origin_name(record['context_id'], record['root'], record['sid'])
        existing, _ = self._read(base, name, deadline)
        if existing is not None:
            _need(_origin_valid(existing) and existing == value)
        else:
            self._publish(base, name, value, deadline,
                          lambda: self._current(base, current, deadline))
        return self.lookup(base, record['project'], record['operation_id'], deadline)

    @_safe
    def accept(self, base, reservation, deadline):
        current, stages = self._current(base, reservation, deadline)
        if current.record['status'] == 'accepted':
            return current
        record = _plain(current.record)
        _need(record['sid'] is not None, 'invalid_request')
        name = _origin_name(record['context_id'], record['root'], record['sid'])
        value, commitment = self._read(base, name, deadline)
        _need(value is not None, 'invalid_request')
        _need(_origin_valid(value) and value == self._origin_record(record, stages['C'][1]))
        wrapper = {'schema': 1, 'kind': 'configured_create_accepted',
                   'record': record | {'status': 'accepted'}, 'parent': stages['C'][1],
                   'origin': commitment}
        def fence():
            self._current(base, current, deadline)
            _need(self._read(base, name, deadline) == (value, commitment))
        self._publish(base, _name('A', record['project'], record['operation_id']),
                      wrapper, deadline, fence)
        return self.lookup(base, record['project'], record['operation_id'], deadline)

    @_safe
    def origin_lookup(self, base, context_id, root, sid, deadline):
        _need(_hex(context_id) and _root(root) and valid_uuid(sid), 'invalid_request')
        name = _origin_name(context_id, root, sid)
        value, commitment = self._read(base, name, deadline)
        if value is None:
            return None
        _need(_origin_valid(value) and value['context_id'] == context_id
              and value['root'] == root and value['sid'] == sid)
        current, stages = self._chain(base, value['project'], value['operation_id'], deadline)
        _need(current is not None and current.record['sid'] == sid
              and value == self._origin_record(current.record, stages['C'][1]))
        _need(self._read(base, name, deadline) == (value, commitment))
        return current if current.record['status'] == 'accepted' else None

    @_safe
    def origins(self, base, project, context_id, root, deadline):
        _need(valid_project(project) and _hex(context_id) and _root(root), 'invalid_request')
        if base is None:
            return {'records': (), 'truncated': False}
        self._anchor(base, deadline)
        records, count = [], 0
        with os.scandir(base) as entries:
            for entry in entries:
                _budget(deadline)
                count += 1
                _need(count <= 10002)
                if re.fullmatch(r'\.tmp-[0-9a-f]{32}', entry.name):
                    continue
                _need(re.fullmatch(r'[0-9a-f]{64}\.json', entry.name) is not None)
                value, _ = self._read(base, entry.name, deadline)
                _need(value is not None)
                if (value.get('project'), value.get('context_id'), value.get('root')) != (project, context_id, root):
                    continue
                if value.get('kind') == 'configured_session_create':
                    _record(value)
                    _need(entry.name == _name('R', project, value['operation_id']))
                    continue
                _need(value.get('kind') == 'configured_session_origin')
                _need(valid_uuid(value.get('sid'))
                      and entry.name == _origin_name(context_id, root, value['sid']))
                accepted = self.origin_lookup(base, context_id, root, value['sid'], deadline)
                if accepted is not None:
                    records.append(accepted)
        self._anchor(base, deadline)
        records.sort(key=lambda item: (-item.record['created'], item.record['sid']))
        return {'records': tuple(records[:128]), 'truncated': len(records) > 128}


class ConfiguredSessionCreate:
    def __init__(self, rpc, project_path, project_names, receipt_dir, *, store=None):
        self.rpc, self.project_path, self.project_names = rpc, project_path, project_names
        self.store = store if store is not None else ConfiguredCreateStore(
            os.path.join(os.path.dirname(os.fspath(receipt_dir)), 'web-configured-create-receipts'))
        _need(type(self.store) is ConfiguredCreateStore, 'invalid_request')

    @staticmethod
    def _provider(provider, deadline, *args):
        _budget(deadline)
        bounded = getattr(provider, 'deadline_call', None)
        result = bounded(deadline, *args) if callable(bounded) else provider(*args)
        _budget(deadline)
        return result

    def _root(self, project, deadline):
        _need(valid_project(project), 'invalid_request')
        names = self._provider(self.project_names, deadline)
        _need(type(names) is list and len(names) <= 1000
              and all(valid_project(name) for name in names) and len(set(names)) == len(names))
        _need(project in names, 'forbidden')
        try:
            root = self._provider(self.project_path, deadline, project)
        except PermissionError:
            raise _DomainError('forbidden') from None
        _need(type(root) is str and os.path.isabs(root))
        root = os.path.realpath(root)
        _need(os.path.isdir(root))
        return root

    def _prepare(self, deadline):
        _need(all(callable(getattr(self.rpc, name, None)) for name in
                  ('prepare_context', 'model_context', 'receipt_context', 'call_in_generation')))
        context = copy.deepcopy(self.rpc.prepare_context(timeout=deadline - time.monotonic()))
        _budget(deadline)
        _need(SessionChat._catalog_reason(context) is None)
        _need(self.rpc.receipt_context() == {key: context[key] for key in
              ('schema', 'vendor', 'context_kind', 'context_id')}, 'stale')
        self._unchanged(context, deadline)
        return context

    def _unchanged(self, context, deadline):
        _budget(deadline)
        _need(self.rpc.model_context() == context, 'stale')
        _need(self.rpc.receipt_context() == {key: context[key] for key in
              ('schema', 'vendor', 'context_kind', 'context_id')}, 'stale')

    def _fresh(self, project, root, context, deadline):
        _need(self._root(project, deadline) == root, 'stale')
        self._unchanged(context, deadline)

    def _call(self, method, params, context, deadline):
        self._unchanged(context, deadline)
        result = self.rpc.call_in_generation(method, params,
                    transport_generation=context['transport_generation'],
                    context_generation=context['context_generation'],
                    timeout=deadline - time.monotonic())
        self._unchanged(context, deadline)
        _need(type(result) is dict and len(_json(result)) <= 1024 * 1024)
        return result

    def _proof(self, project, root, sid, context, deadline):
        thread = self._call('thread/read', {'threadId': sid, 'includeTurns': False},
                            context, deadline).get('thread')
        self._thread(thread, root, sid)
        self._fresh(project, root, context, deadline)
        return thread

    @staticmethod
    def _thread(thread, root, sid):
        _need(type(thread) is dict and valid_uuid(thread.get('id'))
              and type(thread.get('cwd')) is str and os.path.isabs(thread['cwd']))
        _need(thread['id'] == sid and os.path.realpath(thread['cwd']) == root, 'stale')

    @staticmethod
    def _session(record, thread):
        from _control_web_broker import redact
        name = thread.get('name')
        _need(name is None or type(name) is str)
        if name is not None:
            name.encode('utf-8')
        return {'sid': record['sid'], 'project': record['project'], 'vendor': 'codex',
                'context_mode': 'configured',
                'title': redact(name)[:500] if name is not None and name.strip() else None}

    @classmethod
    def _overlay_session(cls, record, thread):
        status = thread.get('status')
        updated = thread.get('updatedAt')
        _need(type(status) is dict and type(status.get('type')) is str
              and status['type'] in ('notLoaded', 'idle', 'systemError', 'active')
              and type(updated) in (int, float) and math.isfinite(updated) and updated >= 0)
        row = cls._session(record, thread) | {'status': status['type'], 'updated_at': updated}
        if status['type'] == 'active':
            flags = status.get('activeFlags')
            _need(type(flags) is list and len(flags) <= 2
                  and all(type(flag) is str and flag in ('waitingOnApproval', 'waitingOnUserInput')
                          for flag in flags) and len(flags) == len(set(flags)))
            if flags:
                row['needs_native_attention'] = True
        return row

    @staticmethod
    def _unknown(operation_id):
        return {'operation_id': operation_id, 'status': 'delivery_unknown'}

    def _accepted(self, record, thread):
        return {'operation_id': record['operation_id'], 'status': 'accepted',
                'session': self._session(record, thread)}

    @staticmethod
    def _selectors(project, operation_id, context_mode, provider_id):
        _need(valid_project(project) and valid_uuid(operation_id)
              and context_mode == 'configured' and provider_id == 'codex', 'invalid_request')

    @staticmethod
    def _matching(record, root, context):
        _need(record['root'] == root and record['context_id'] == context['context_id'], 'stale')

    @_safe
    def options(self, project):
        deadline = time.monotonic() + 55
        root = self._root(project, deadline)
        available = False
        try:
            context = self._prepare(deadline)
            self._fresh(project, root, context, deadline)
            available = True
        except _DomainError as error:
            if error.code == 'forbidden':
                raise
        except Exception:
            pass
        return {'schema': 1, 'project': project, 'options': [{
            'context_mode': 'configured', 'provider_id': 'codex',
            'available': available, 'reason': None if available else 'unavailable'}]}

    @_safe
    def create(self, project, operation_id, context_mode, provider_id):
        self._selectors(project, operation_id, context_mode, provider_id)
        deadline = time.monotonic() + 55
        root = self._root(project, deadline)
        context = self._prepare(deadline)
        self._fresh(project, root, context, deadline)
        with self.store.locked(deadline) as base:
            previous = self.store.lookup(base, project, operation_id, deadline)
            if previous is not None:
                self._matching(previous.record, root, context)
                if previous.record['status'] == 'accepted':
                    return self._accepted(previous.record, self._proof(project, root,
                           previous.record['sid'], context, deadline))
                return self._unknown(operation_id)
        reserved = False
        try:
            with self.store.locked(deadline, create=True) as base:
                previous = self.store.lookup(base, project, operation_id, deadline)
                if previous is not None:
                    self._matching(previous.record, root, context)
                    if previous.record['status'] == 'accepted':
                        return self._accepted(previous.record, self._proof(project, root,
                               previous.record['sid'], context, deadline))
                    return self._unknown(operation_id)
                self._fresh(project, root, context, deadline)
                self.store.capacity(base, deadline)
                reserved = True
                reservation = self.store.reserve(base, project, context['context_id'], root,
                                                 operation_id, deadline)
                self._fresh(project, root, context, deadline)
                thread = self._call('thread/start', {'cwd': root}, context, deadline).get('thread')
                _need(type(thread) is dict and valid_uuid(thread.get('id')))
                sid = thread['id']
                self._thread(thread, root, sid)
                self._fresh(project, root, context, deadline)
                reservation = self.store.candidate(base, reservation, sid, deadline)
                _need(sid in self._loaded(context, deadline)[0])
                thread = self._proof(project, root, sid, context, deadline)
                reservation = self.store.origin(base, reservation, deadline)
                reservation = self.store.accept(base, reservation, deadline)
                self._fresh(project, root, context, deadline)
                return self._accepted(reservation.record, thread)
        except Exception:
            if reserved:
                return self._unknown(operation_id)
            raise

    @_safe
    def status(self, project, operation_id, context_mode, provider_id):
        self._selectors(project, operation_id, context_mode, provider_id)
        deadline = time.monotonic() + 55
        root = self._root(project, deadline)
        context = self._prepare(deadline)
        with self.store.locked(deadline) as base:
            record = self.store.lookup(base, project, operation_id, deadline)
            _need(record is not None, 'stale')
            self._matching(record.record, root, context)
            self._fresh(project, root, context, deadline)
            if record.record['sid'] is None:
                return self._unknown(operation_id)
            if record.record['status'] != 'accepted':
                _need(record.record['sid'] in self._loaded(context, deadline)[0])
            thread = self._proof(project, root, record.record['sid'], context, deadline)
            if record.record['status'] != 'accepted':
                record = self.store.origin(base, record, deadline)
                record = self.store.accept(base, record, deadline)
            self._fresh(project, root, context, deadline)
            return self._accepted(record.record, thread)

    def _loaded(self, context, deadline):
        ids, cursors, cursor, complete = set(), set(), None, False
        for _ in range(4):
            params = {'limit': 100}
            if cursor is not None:
                params['cursor'] = cursor
            page = self._call('thread/loaded/list', params, context, deadline)
            _need(set(page) == {'data', 'nextCursor'} and type(page['data']) is list
                  and len(page['data']) <= 100 and all(valid_uuid(sid) for sid in page['data'])
                  and len(set(page['data'])) == len(page['data'])
                  and not ids.intersection(page['data']))
            ids.update(page['data'])
            cursor = page['nextCursor']
            _need(cursor is None or (type(cursor) is str and 0 < len(cursor) <= 4096))
            if cursor is None:
                complete = True
                break
            _need(cursor not in cursors)
            cursors.add(cursor)
        return ids, not complete

    @_safe
    def overlay(self, project):
        deadline = time.monotonic() + 55
        root = self._root(project, deadline)
        context = self._prepare(deadline)
        with self.store.locked(deadline) as base:
            origins = self.store.origins(base, project, context['context_id'], root, deadline)
            if not origins['records']:
                self._fresh(project, root, context, deadline)
                return {'sessions': [], 'truncated': origins['truncated']}
            loaded, truncated = self._loaded(context, deadline)
            sessions = []
            for origin in origins['records']:
                if origin.record['sid'] not in loaded:
                    continue
                thread = self._proof(project, root, origin.record['sid'], context, deadline)
                sessions.append(self._overlay_session(origin.record, thread))
            self._fresh(project, root, context, deadline)
            return {'sessions': sessions, 'truncated': truncated or origins['truncated']}

    def _loaded_origin(self, project, sid, deadline, require_loaded=False):
        _need(valid_uuid(sid), 'invalid_request')
        root = self._root(project, deadline)
        context = self._prepare(deadline)
        with self.store.locked(deadline) as base:
            origin = self.store.origin_lookup(base, context['context_id'], root, sid, deadline)
            if origin is None:
                self._fresh(project, root, context, deadline)
                return None, None
            _need(origin.record['project'] == project, 'stale')
            ids, _ = self._loaded(context, deadline)
            thread = self._proof(project, root, sid, context, deadline)
            _need(self.store.origin_lookup(base, context['context_id'], root, sid, deadline).record
                  == origin.record)
            if sid not in ids:
                _need(not require_loaded)
                # A successful normal thread/read is the persistent metadata
                # proof; the ordinary sender must still validate its resume.
                return None, None
            proof = ConfiguredLoadedOrigin(origin, context, self._session(origin.record, thread))
            return proof, thread

    @_safe
    def loaded_origin(self, project, sid):
        return self._loaded_origin(project, sid, time.monotonic() + 55)[0]

    @_safe
    def unavailable_history(self, project, sid):
        from _control_web_sessions import _attention
        proof, thread = self._loaded_origin(project, sid, time.monotonic() + 55, True)
        if proof is None:
            return None
        return ConfiguredUnavailableHistory(proof.reservation, proof.context, proof.session,
                                             _attention(thread))
