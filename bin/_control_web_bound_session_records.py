"""Pure bound-session syntax DTOs. Accepted receipts confer no disk/host authority."""
from dataclasses import dataclass
from functools import wraps
import hashlib
import json
import re
from collections.abc import Mapping


class BoundRecordError(ValueError):
    def __init__(self, code):
        self.code = code if type(code) is str and code in ('context_invalid', 'context_drift', 'invalid_request') else 'invalid_request'
        super().__init__(self.code)


def _safe(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except BoundRecordError:
            raise
        except Exception:
            raise BoundRecordError('invalid_request') from None
    return invoke


def _require(condition, code='invalid_request'):
    if not condition:
        raise BoundRecordError(code)


@dataclass(frozen=True, slots=True, repr=False, init=False, eq=False)
class _FrozenMap(Mapping):
    _items: tuple

    def __init__(self, captured):
        object.__setattr__(self, '_items', tuple(
            (key, _freeze(value)) for key, value in captured.items()))

    def __getitem__(self, key):
        return _owned_values(self)[key]

    def __iter__(self):
        return iter(_owned_values(self))

    def __len__(self):
        return len(_owned_values(self))


def _owned_values(value, code='invalid_request'):
    # Inspect fixed primitive slots before invoking any retained object method.
    try:
        items = object.__getattribute__(value, '_items')
    except AttributeError:
        raise BoundRecordError(code) from None
    _require(type(items) is tuple, code)
    result = {}
    for pair in items:
        _require(type(pair) is tuple and len(pair) == 2, code)
        key, child = pair
        _require(type(key) is str and key not in result, code)
        _require(type(child) in (str, int, type(None), _FrozenMap), code)
        if type(child) is _FrozenMap:
            _owned_values(child, code)
        result[key] = child
    return result


def _mapping(value, code='invalid_request'):
    _require(type(value) in (dict, _FrozenMap), code)
    captured = dict.copy(value) if type(value) is dict else _owned_values(value, code)
    _require(all(type(key) is str for key in captured), code)
    return captured


def _capture(value, code='invalid_request'):
    if type(value) in (dict, _FrozenMap):
        shallow = _mapping(value, code)
        return {key: _capture(child, code) for key, child in shallow.items()}
    _require(type(value) in (str, int, type(None)), code)
    return value


def _keys(value, keys, code='invalid_request'):
    _mapping(value, code)
    _require(set(value) == set(keys.split()), code)


def _match(value, pattern, code='invalid_request'):
    _require(type(value) is str and re.fullmatch(pattern, value, flags=re.ASCII) is not None, code)


def _integer(value, minimum, maximum=None, code='invalid_request'):
    _require(type(value) is int and value >= minimum and (maximum is None or value <= maximum), code)


def _uuid(value, code='invalid_request'):
    _match(value, r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', code)


def _hex(value, count=64, code='invalid_request'):
    _match(value, '[0-9a-f]{%d}' % count, code)


def _reference(value):
    code = 'context_invalid'
    value = _capture(value, code)
    _keys(value, 'schema provider_id account_id profile_instance_id adapter_revision registration_snapshot', code)
    _require(type(value['schema']) is int and value['schema'] == 2, code)
    for key, expected in (('provider_id', 'codex'), ('adapter_revision', 'codex-chatgpt-external-auth-host-v2')):
        _require(type(value[key]) is str and value[key] == expected, code)
    _match(value['account_id'], r'[a-z][a-z0-9_-]{0,63}', code)
    _uuid(value['profile_instance_id'], code)
    snapshot = value['registration_snapshot']
    _keys(snapshot, 'dev ino ctime_ns sha256', code)
    for key, minimum in (('dev', 0), ('ino', 1), ('ctime_ns', 1)):
        _integer(snapshot[key], minimum, code=code)
    _hex(snapshot['sha256'], code=code)
    result = dict(value)
    result['registration_snapshot'] = dict(snapshot)
    return result


def _root(value):
    _require(type(value) is str and value.startswith('/'))
    _require(all(ord(char) >= 32 and not 127 <= ord(char) <= 159 and not 0xD800 <= ord(char) <= 0xDFFF for char in value))
    _require(len(value.encode('utf-8')) <= 4096)
    if value != '/':
        _require(all(segment not in ('', '.', '..') for segment in value[1:].split('/')))


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _freeze(value):
    if type(value) is dict:
        return _FrozenMap(value)
    return value


def _commitment(value, expected=None, pattern=None):
    value = _capture(value)
    _keys(value, 'filename dev ino ctime_ns sha256')
    filename = value['filename']
    _require(type(filename) is str)
    if expected is not None:
        _require(filename == expected)
    else:
        _match(filename, pattern)
    for key, minimum in (('dev', 0), ('ino', 1), ('ctime_ns', 1)):
        _integer(value[key], minimum)
    _hex(value['sha256'])
    return dict(value)


def _record(value, stop, expected_ref=None):
    value = _mapping(value)
    _require('context_ref' in value)
    # Unsupported nested mapping representations are record-shape errors.
    _require(type(value['context_ref']) in (dict, _FrozenMap))
    ref = _reference(value['context_ref'])
    if expected_ref is not None:
        _require(ref == expected_ref, 'context_drift')
    value['context_ref'] = ref
    value = _capture(value)
    common = 'schema kind context_ref root session_ref operation_id created digest'
    _keys(value, common + (' host_id invocation_id origin_parent' if stop else ' project'))
    _require(type(value['schema']) is int and value['schema'] == 1)
    kind = 'bound_session_stop' if stop else 'bound_session_create'
    _require(type(value['kind']) is str and value['kind'] == kind)
    _root(value['root'])
    _uuid(value['session_ref'])
    _uuid(value['operation_id'])
    _integer(value['created'], 1, 2**63 - 1)
    _hex(value['digest'])
    result = dict(value)
    result['context_ref'] = ref
    if stop:
        _uuid(value['host_id'])
        _hex(value['invocation_id'], 32)
        result['origin_parent'] = _commitment(value['origin_parent'], pattern=r'BC-[0-9a-f]{64}\.A\.json')
    else:
        _match(value['project'], r'[a-zA-Z0-9_-]{1,32}')
    without_digest = dict(result)
    del without_digest['digest']
    _require(_digest(without_digest) == result['digest'])
    _require(len(_canonical(result)) <= 4096)
    return result


def _parents(record, status, parents, stop):
    _require(type(status) is str and status in ('unknown', 'accepted'))
    roles = ('S', 'T') if stop else ('R', 'G', 'C', 'I_session', 'I_native', 'A')
    parents = _capture(parents)
    _keys(parents, ' '.join(roles))
    fields = ('context_ref', 'root', 'session_ref', 'operation_id') if stop else ('context_ref', 'project', 'root', 'operation_id')
    key = _digest({field: record[field] for field in fields})
    session = record['session_ref']
    filenames = ({role: f'BS-{key}.{role}.json' for role in roles} if stop else {
        'R': f'BC-{key}.R.json', 'G': f'BG-S-{session}.json',
        'C': f'BC-{key}.C.json', 'I_session': f'BI-S-{session}.json',
        'A': f'BC-{key}.A.json'})
    result = {}
    for role in roles:
        value = parents[role]
        if value is None:
            result[role] = None
        elif role == 'I_native':
            result[role] = _commitment(value, pattern=r'BI-N-[0-9a-f]{64}\.json')
        else:
            result[role] = _commitment(value, expected=filenames[role])
    _require(result[roles[0]] is not None)
    if status == 'accepted':
        _require(all(value is not None for value in result.values()))
    elif stop:
        _require(result['T'] is None)
    else:
        _require(result['A'] is None)
        if result['G'] is None:
            _require(all(result[role] is None for role in ('C', 'I_session', 'I_native', 'A')))
        if result['C'] is None:
            _require(result['I_session'] is None and result['I_native'] is None)
    return result


@dataclass(frozen=True, slots=True, repr=False, init=False)
class PreparedBoundCreate:
    record: object

    @_safe
    def __init__(self, record):
        object.__setattr__(self, 'record', _freeze(_record(record, False)))


@dataclass(frozen=True, slots=True, repr=False, init=False)
class PreparedBoundStop:
    record: object

    @_safe
    def __init__(self, record):
        object.__setattr__(self, 'record', _freeze(_record(record, True)))


@dataclass(frozen=True, slots=True, repr=False, init=False)
class BoundCreateReceipt:
    record: object
    status: str
    parents: object

    @_safe
    def __init__(self, record, status, parents):
        captured = _record(record, False)
        captured_parents = _parents(captured, status, parents, False)
        object.__setattr__(self, 'record', _freeze(captured))
        object.__setattr__(self, 'status', status)
        object.__setattr__(self, 'parents', _freeze(captured_parents))


@dataclass(frozen=True, slots=True, repr=False, init=False)
class BoundStopReceipt:
    record: object
    status: str
    parents: object

    @_safe
    def __init__(self, record, status, parents):
        captured = _record(record, True)
        captured_parents = _parents(captured, status, parents, True)
        object.__setattr__(self, 'record', _freeze(captured))
        object.__setattr__(self, 'status', status)
        object.__setattr__(self, 'parents', _freeze(captured_parents))


@dataclass(frozen=True, slots=True, repr=False, init=False)
class BoundRecordCodec:
    _context_ref: object

    @_safe
    def __init__(self, context_ref):
        object.__setattr__(self, '_context_ref', _freeze(_reference(context_ref)))

    def _context(self, context_ref):
        captured = _reference(context_ref)
        _require(captured == _reference(self._context_ref), 'context_drift')
        return captured

    def _value(self, value, stop, ref):
        classes = (PreparedBoundStop, BoundStopReceipt) if stop else (PreparedBoundCreate, BoundCreateReceipt)
        _require(type(value) in classes)
        record = _record(value.record, stop, ref)
        if type(value) is classes[1]:
            return classes[1](record, value.status, value.parents)
        return classes[0](record)

    @_safe
    def prepare_create(self, context_ref, project, root, session_ref, operation_id, created_ns):
        ref = self._context(context_ref)
        # Validate plain inputs before canonical encoding can touch them.
        _match(project, r'[a-zA-Z0-9_-]{1,32}')
        _root(root)
        _uuid(session_ref)
        _uuid(operation_id)
        _integer(created_ns, 1, 2**63 - 1)
        record = dict(schema=1, kind='bound_session_create', context_ref=ref,
                      project=project, root=root, session_ref=session_ref,
                      operation_id=operation_id, created=created_ns)
        record['digest'] = _digest(record)
        return PreparedBoundCreate(record)

    @_safe
    def prepare_stop(self, context_ref, origin, operation_id, host_id, invocation_id, created_ns):
        ref = self._context(context_ref)
        _require(type(origin) is BoundCreateReceipt)
        captured = self._value(origin, False, ref)
        _require(captured.status == 'accepted')
        _uuid(operation_id)
        _uuid(host_id)
        _hex(invocation_id, 32)
        _integer(created_ns, 1, 2**63 - 1)
        record = dict(schema=1, kind='bound_session_stop', context_ref=ref,
                      root=captured.record['root'], session_ref=captured.record['session_ref'],
                      operation_id=operation_id, host_id=host_id, invocation_id=invocation_id,
                      created=created_ns, origin_parent=dict(captured.parents['A']))
        record['digest'] = _digest(record)
        return PreparedBoundStop(record)

    @_safe
    def validate_create(self, context_ref, value, *, project, root, session_ref, operation_id):
        ref = self._context(context_ref)
        captured = self._value(value, False, ref)
        _match(project, r'[a-zA-Z0-9_-]{1,32}')
        self._expected(captured.record, root, session_ref, operation_id)
        _require(captured.record['project'] == project)
        return captured

    @_safe
    def validate_stop(self, context_ref, value, *, root, session_ref, operation_id):
        ref = self._context(context_ref)
        captured = self._value(value, True, ref)
        self._expected(captured.record, root, session_ref, operation_id)
        return captured

    def _expected(self, record, root, session_ref, operation_id):
        _root(root)
        _uuid(session_ref)
        _uuid(operation_id)
        _require(record['root'] == root and record['session_ref'] == session_ref
                 and record['operation_id'] == operation_id)
