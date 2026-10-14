"""Pure validation for the bounded Claude worktree v2 public protocol."""
import hashlib
import json
import re
import uuid


_SUBMIT_FIELDS = {'schema', 'request_id', 'node_id', 'execution_profile_id', 'prompt'}
_RESULT_FIELDS = {'schema', 'executor', 'text', 'text_truncated', 'tests', 'diff',
                  'usage', 'usage_state'}
_DIFF_FIELDS = {'base_sha', 'patch_status', 'patch', 'patch_bytes', 'patch_sha256', 'reasons'}
_TEST_FIELDS = {'test_id', 'status', 'exit_code', 'oracle_sha256'}
_HASH40 = re.compile(r'[0-9a-f]{40}\Z')
_HASH64 = re.compile(r'[0-9a-f]{64}\Z')


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
