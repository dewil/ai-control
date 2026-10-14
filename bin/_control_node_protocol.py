"""Pure validation for the bounded Claude worktree v2 public protocol."""
import hashlib
import json
import re
import uuid
from datetime import datetime


_SUBMIT_FIELDS = {'schema', 'request_id', 'node_id', 'execution_profile_id', 'prompt'}
_RESULT_FIELDS = {'schema', 'executor', 'text', 'text_truncated', 'tests', 'diff',
                  'usage', 'usage_state'}
_DIFF_FIELDS = {'base_sha', 'patch_status', 'patch', 'patch_bytes', 'patch_sha256', 'reasons'}
_TEST_FIELDS = {'test_id', 'status', 'exit_code', 'oracle_sha256'}
_HASH40 = re.compile(r'[0-9a-f]{40}\Z')
_HASH64 = re.compile(r'[0-9a-f]{64}\Z')
_IDENTIFIER = re.compile(r'[A-Za-z0-9_.:-]{1,80}\Z')
_BINDING_FIELDS = {'task_id', 'attempt_id', 'node_id', 'execution_profile_id',
                   'profile_revision', 'provider', 'requested_model', 'requested_effort',
                   'account_ref', 'workspace_ref', 'base_sha', 'worktree_ref',
                   'requested_session_uuid'}
_PROFILE_FIELDS = (_BINDING_FIELDS - {'task_id', 'attempt_id', 'node_id', 'worktree_ref',
                                    'requested_session_uuid'}) | {
    'executor_target', 'test_id', 'oracle_sha256', 'account_attestation'}
_ENVELOPE_FIELDS = {'message_id', 'task_id', 'correlation_id', 'source', 'target',
                    'kind', 'created_at', 'payload'}
_EVENT_FIELDS = {'schema', 'sequence', 'binding', 'session_verification',
                 'observed_session_uuid', 'native_model', 'effort_state', 'result', 'reason'}
_UTC_TIME = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z')


def _require(condition):
    if not condition:
        raise ValueError('invalid v2 protocol value')


def _utf8(value):
    _require(type(value) is str)
    try:
        return value.encode('utf-8')
    except UnicodeError:
        raise ValueError('invalid v2 protocol value') from None


def _hash(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


def _uuid(value):
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _identifier(value):
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def validate_submit_v2(value):
    """Return an exact valid request, or raise ValueError without modifying it."""
    _require(type(value) is dict and set(value) == _SUBMIT_FIELDS)
    _require(type(value['schema']) is int and value['schema'] == 2)
    request_id = value['request_id']
    _require(type(request_id) is str)
    try:
        _require(str(uuid.UUID(request_id)) == request_id)
    except (ValueError, AttributeError):
        raise ValueError('invalid v2 protocol value') from None
    _require(type(value['node_id']) is str and value['node_id'] == 'alp')
    _require(type(value['execution_profile_id']) is str and
             value['execution_profile_id'] == 'alp-claude-worktree-v1')
    prompt = _utf8(value['prompt'])
    _require(1 <= len(prompt) <= 32768 and b'\0' not in prompt)
    return value


def _validate_diff(value):
    _require(type(value) is dict and set(value) == _DIFF_FIELDS)
    _require(_hash(value['base_sha'], _HASH40))
    status = value['patch_status']
    _require(type(status) is str and status in
             ('ok', 'empty', 'oversize', 'unsupported', 'unavailable'))
    reasons = value['reasons']
    _require(type(reasons) is list)
    for reason in reasons:
        _require(bool(_utf8(reason)))
    _require(reasons == sorted(set(reasons)))
    patch, size, digest = value['patch'], value['patch_bytes'], value['patch_sha256']
    if status == 'unavailable':
        _require(patch is None and size is None and digest is None)
        return
    _require(type(size) is int and 0 <= size <= 2**63 - 1)
    _require(_hash(digest, _HASH64))
    if status in ('ok', 'empty'):
        raw = _utf8(patch)
        _require(len(raw) == size and size <= 32768 and b'\r' not in raw)
        _require(hashlib.sha256(raw).hexdigest() == digest and reasons == [])
        _require(size > 0 if status == 'ok' else size == 0)
    else:
        _require(patch is None)
        if status == 'oversize':
            _require(size > 32768 or 'result_budget' in reasons)
        else:
            _require(bool(reasons))


def _validate_test(value):
    _require(type(value) is dict and set(value) == _TEST_FIELDS)
    _require(bool(_utf8(value['test_id'])))
    _require(_hash(value['oracle_sha256'], _HASH64))
    status, exit_code = value['status'], value['exit_code']
    _require(type(status) is str and status in
             ('passed', 'failed', 'error', 'timeout', 'notrun', 'unknown'))
    _require(exit_code is None or
             (type(exit_code) is int and -(2**31) <= exit_code < 2**31))
    if status == 'passed':
        _require(exit_code == 0)
    elif status == 'failed':
        _require(exit_code is not None and exit_code != 0)
    elif status == 'notrun':
        _require(exit_code is None)


def validate_result_v2(value):
    """Validate the sealed bounded result, including complete patch bytes/hash.

    Capture, truncation and oracle execution belong to the supervisor. This
    function never manufactures evidence or changes a caller's result.
    """
    _require(type(value) is dict and set(value) == _RESULT_FIELDS)
    _require(type(value['schema']) is int and value['schema'] == 2)
    _require(type(value['executor']) is str and value['executor'] == 'claude')
    _require(len(_utf8(value['text'])) <= 8192)
    _require(type(value['text_truncated']) is bool)
    _require(value['usage'] is None and type(value['usage_state']) is str and
             value['usage_state'] == 'unknown')
    tests = value['tests']
    _require(type(tests) is list and len(tests) <= 16)
    for test in tests:
        _validate_test(test)
    _validate_diff(value['diff'])
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('invalid v2 protocol value') from None
    _require(len(encoded) <= 60000)
    return value


def validate_binding_v2(value):
    """Validate immutable server-owned binding references, never local paths."""
    _require(type(value) is dict and set(value) == _BINDING_FIELDS)
    for key in ('task_id', 'attempt_id', 'requested_session_uuid'):
        _require(_uuid(value[key]))
    for key in ('account_ref', 'workspace_ref', 'worktree_ref', 'requested_model',
                'requested_effort'):
        _require(_identifier(value[key]))
    _require(type(value['profile_revision']) is int and
             0 <= value['profile_revision'] <= 2**63 - 1)
    _require(value['node_id'] == 'alp' and value['provider'] == 'claude' and
             value['execution_profile_id'] == 'alp-claude-worktree-v1')
    _require(_hash(value['base_sha'], _HASH40))
    canonical_v2(value)
    return value


def validate_profile_snapshot_v2(value):
    """Validate an internal snapshot supplied by a trusted profile resolver.

    Production resolvers must reject synthetic provenance. Accepting it here
    enables explicitly injected isolated resolvers without an environment bypass.
    """
    _require(type(value) is dict and set(value) == _PROFILE_FIELDS)
    placeholder = '00000000-0000-4000-8000-000000000000'
    binding = {key: value[key] for key in _PROFILE_FIELDS & _BINDING_FIELDS}
    binding.update(task_id=placeholder, attempt_id=placeholder, node_id='alp',
                   worktree_ref=placeholder, requested_session_uuid=placeholder)
    validate_binding_v2(binding)
    _require(value['executor_target'] == 'claude-alp-worktree-1')
    _require(_identifier(value['test_id']) and _hash(value['oracle_sha256'], _HASH64))
    attestation = value['account_attestation']
    _require(type(attestation) is dict and set(attestation) == {'status', 'provenance'})
    _require(type(attestation['status']) is str and attestation['status'] in ('verified', 'unknown'))
    _require(type(attestation['provenance']) is str and
             attestation['provenance'] in ('synthetic', 'owner_verified'))
    canonical_v2(value)
    return value


def canonical_v2(value):
    """Encode strict bounded JSON without floats or Unicode normalization."""
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        _require(depth <= 32)
        if type(item) is dict:
            for key, child in item.items():
                _utf8(key)
                stack.append((child, depth + 1))
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            _utf8(item)
        elif type(item) is int:
            _require(-(2**63) <= item <= 2**63 - 1)
        else:
            _require(item is None or type(item) is bool)
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result)
        result[key] = value
    return result


def _decode_envelope(raw):
    _require(type(raw) is bytes and len(raw) <= 129024)
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _require(canonical_v2(value) == raw)
        _require(type(value) is dict and set(value) == _ENVELOPE_FIELDS)
        for key in ('message_id', 'task_id', 'correlation_id'):
            _require(_uuid(value[key]))
        _require(value['task_id'] == value['correlation_id'])
        _require(_identifier(value['source']) and _identifier(value['target']))
        stamp = value['created_at']
        _require(type(stamp) is str and _UTC_TIME.fullmatch(stamp) is not None)
        datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        _require(type(value['payload']) is dict)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('invalid v2 envelope') from None


def decode_command_v2(raw):
    """Decode the exact canonical durable v2 submit command."""
    value = _decode_envelope(raw)
    _require(value['source'] == 'control-web' and value['target'] == 'claude-alp-worktree-1'
             and value['kind'] == 'submit')
    payload = value['payload']
    _require(set(payload) == {'schema', 'operation', 'request', 'binding'})
    _require(type(payload['schema']) is int and payload['schema'] == 2 and
             payload['operation'] == 'submit')
    request = validate_submit_v2(payload['request'])
    binding = validate_binding_v2(payload['binding'])
    _require(request['request_id'] == binding['task_id'] == value['task_id'])
    _require(request['node_id'] == binding['node_id'] and
             request['execution_profile_id'] == binding['execution_profile_id'])
    return value


def decode_event_v2(raw):
    """Decode canonical event evidence; task-specific conflicts remain Store decisions."""
    value = _decode_envelope(raw)
    _require(value['source'] == 'claude-alp-worktree-1' and value['target'] == 'control-web')
    payload = value['payload']
    _require(set(payload) == _EVENT_FIELDS)
    _require(type(payload['schema']) is int and payload['schema'] == 2)
    binding = validate_binding_v2(payload['binding'])
    _require(binding['task_id'] == value['task_id'])
    sequence, kind = payload['sequence'], value['kind']
    _require(type(sequence) is int and 0 <= sequence <= 3)
    kinds = (('queued',), ('accepted',), ('running',),
             ('completed', 'failed', 'needs_attention'))
    _require(type(kind) is str and kind in kinds[sequence])
    expected_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
        'ai-control:node-event:v2:%s:%s:%s' % (value['task_id'], binding['attempt_id'], sequence)))
    _require(value['message_id'] == expected_id)
    verification = payload['session_verification']
    _require(type(verification) is str and verification in ('pending', 'verified', 'unknown'))
    observed, model = payload['observed_session_uuid'], payload['native_model']
    _require(observed is None or _uuid(observed))
    _require(model is None or _identifier(model))
    if verification == 'verified':
        _require(observed is not None and model is not None)
    _require(payload['effort_state'] == 'requested_unverified')
    _require(payload['reason'] is None or _identifier(payload['reason']))
    result = payload['result']
    if result is not None:
        _require(sequence == 3)
        validate_result_v2(result)
    if kind == 'completed':
        _require(result is not None)
    return value
