"""Synthetic token-response data checks; no signature, provenance or admission proof."""
import base64
import hashlib
import hmac
import json
import math
import re

from _control_codex_auth_authority import AuthScope, _snapshot


_ISSUER = 'https://auth.openai.com'
_CLIENT = 'app_EMoamEEZ73f0CkXaXp7hrann'
_AUTH = 'https://api.openai.com/auth'
_CODES = ('authority_stale', 'auth_response_invalid', 'identity_mismatch', 'auth_expired')


class TokenResponseError(ValueError):
    def __init__(self, code):
        self.code = code if type(code) is str and code in _CODES else 'auth_response_invalid'
        super().__init__(self.code)


def _require(condition, code='auth_response_invalid'):
    if not condition:
        raise TokenResponseError(code)


def _safe_call(call):
    # Raise outside the decoder's exception handler: even __context__ is empty.
    code = None
    try:
        return call()
    except TokenResponseError as error:
        code = error.code
    except Exception:
        code = 'auth_response_invalid'
    raise TokenResponseError(code)


def _wall(value):
    _require(type(value) in (int, float))
    _require(math.isfinite(value) and value >= 0)
    return value


class ParsedTokenResponse:
    """Read-only minimal data. Retains no raw ID token or verification marker."""
    __slots__ = ('_access_token', '_refresh_token', '_id_expires_at',
                 '_access_expires_at', '_scope_snapshot')

    def __init__(self, access_token, refresh_token, id_expires_at,
                 access_expires_at, scope_snapshot):
        object.__setattr__(self, '_access_token', access_token)
        object.__setattr__(self, '_refresh_token', refresh_token)
        object.__setattr__(self, '_id_expires_at', id_expires_at)
        object.__setattr__(self, '_access_expires_at', access_expires_at)
        object.__setattr__(self, '_scope_snapshot', scope_snapshot)

    def __setattr__(self, name, value):
        raise AttributeError('read-only token response data')

    def __delattr__(self, name):
        raise AttributeError('read-only token response data')

    access_token = property(lambda self: self._access_token)
    refresh_token = property(lambda self: self._refresh_token)
    id_expires_at = property(lambda self: self._id_expires_at)
    access_expires_at = property(lambda self: self._access_expires_at)
    scope_snapshot = property(lambda self: self._scope_snapshot)

    def usable_at(self, wall):
        def check():
            checked = _wall(wall)
            return (self._id_expires_at >= checked + 30
                    and self._access_expires_at >= checked + 30)
        return _safe_call(check)


def _scope(expected):
    try:
        _require(type(expected) is AuthScope, 'authority_stale')
        return _snapshot(expected)
    except Exception:
        raise TokenResponseError('authority_stale') from None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _walk(value, depth=1):
    if type(value) in (dict, list):
        _require(depth <= 16)
        if type(value) is dict:
            for key, child in value.items():
                _walk(key, depth + 1)
                _walk(child, depth + 1)
        else:
            for child in value:
                _walk(child, depth + 1)
    elif type(value) is str:
        _require(not any(0xD800 <= ord(char) <= 0xDFFF for char in value))
    elif type(value) is float:
        _require(math.isfinite(value))


def _json(raw, limit):
    _require(type(raw) is bytes and len(raw) <= limit)
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                       parse_constant=lambda ignored: _require(False))
    _require(type(value) is dict)
    _walk(value)
    return value


def _text(value):
    _require(type(value) is str and value != '')


def _token(value):
    _require(type(value) is str and 1 <= len(value) <= 16384)
    _require(all(33 <= ord(char) <= 126 for char in value))


def _base64(segment):
    _require(type(segment) is str and re.fullmatch(r'[A-Za-z0-9_-]+', segment, flags=re.ASCII) is not None)
    decoded = base64.b64decode(segment + '=' * (-len(segment) % 4), altchars=b'-_', validate=True)
    _require(base64.urlsafe_b64encode(decoded).decode('ascii').rstrip('=') == segment)
    return decoded


def _jwt(token):
    segments = token.split('.')
    _require(len(segments) == 3)
    header = _json(_base64(segments[0]), 2048)
    payload = _json(_base64(segments[1]), 16384)
    _require(len(_base64(segments[2])) > 0)
    _require('alg' in header and set(header) <= {'alg', 'typ', 'kid'})
    _require(type(header['alg']) is str and header['alg'] == 'RS256')
    if 'typ' in header:
        _require(type(header['typ']) is str and header['typ'] == 'JWT')
    if 'kid' in header:
        kid = header['kid']
        _require(type(kid) is str and 1 <= len(kid) <= 256
                 and all(32 <= ord(char) <= 126 for char in kid))
    return payload


def _positive(value):
    _require(type(value) is int and 1 <= value <= 2**63 - 1)


def _claim_types(ident, access):
    _require({'iss', 'aud', 'sub', 'iat', 'exp', _AUTH} <= set(ident))
    for key in ('iss', 'sub'):
        _text(ident[key])
    aud = ident['aud']
    if type(aud) is list:
        _require(len(aud) > 0)
        for member in aud:
            _text(member)
    else:
        _text(aud)
    for key in ('iat', 'exp'):
        _positive(ident[key])
    namespace = ident[_AUTH]
    _require(type(namespace) is dict and 'chatgpt_account_id' in namespace)
    _text(namespace['chatgpt_account_id'])
    if 'azp' in ident:
        _text(ident['azp'])
    if 'at_hash' in ident:
        _require(len(_base64(ident['at_hash'])) == 16)
    _require('exp' in access)
    _positive(access['exp'])
    if 'iat' in access:
        _positive(access['iat'])
    if _AUTH in access:
        _require(type(access[_AUTH]) is dict)
        if 'chatgpt_account_id' in access[_AUTH]:
            _text(access[_AUTH]['chatgpt_account_id'])


def _envelope(body):
    envelope = _json(body, 65536)
    _require({'access_token', 'id_token'} <= set(envelope)
             and set(envelope) <= {'access_token', 'id_token', 'refresh_token',
                                   'token_type', 'expires_in', 'scope'})
    for key in ('access_token', 'id_token', 'refresh_token'):
        if key in envelope:
            _token(envelope[key])
    if 'token_type' in envelope:
        _require(type(envelope['token_type']) is str and envelope['token_type'] == 'Bearer')
    if 'expires_in' in envelope:
        _require(type(envelope['expires_in']) is int and 1 <= envelope['expires_in'] <= 86400)
    if 'scope' in envelope:
        scope = envelope['scope']
        _require(type(scope) is str and 1 <= len(scope) <= 4096
                 and re.fullmatch(r'[A-Za-z0-9_:/.-]+(?: [A-Za-z0-9_:/.-]+)*', scope, flags=re.ASCII) is not None)
    return envelope


def _parse(status, body, expected, start, end, evaluation):
    captured = _scope(expected)
    _wall(start)
    _wall(end)
    _wall(evaluation)
    _require(start <= end <= evaluation)
    _require(type(status) is int and status == 200)
    envelope = _envelope(body)
    ident = _jwt(envelope['id_token'])
    access = _jwt(envelope['access_token'])
    _claim_types(ident, access)
    principal = dict(captured[-1])
    _require(ident['iss'] == _ISSUER and ident['aud'] in (_CLIENT, [_CLIENT])
             and ident['sub'] == principal['subject']
             and ident[_AUTH]['chatgpt_account_id'] == principal['workspace_id'], 'identity_mismatch')
    if 'azp' in ident:
        _require(ident['azp'] == _CLIENT, 'identity_mismatch')
    if _AUTH in access and 'chatgpt_account_id' in access[_AUTH]:
        _require(access[_AUTH]['chatgpt_account_id'] == principal['workspace_id'], 'identity_mismatch')
    if 'at_hash' in ident:
        actual = base64.urlsafe_b64encode(hashlib.sha256(envelope['access_token'].encode('ascii')).digest()[:16]).decode('ascii').rstrip('=')
        _require(hmac.compare_digest(ident['at_hash'], actual), 'identity_mismatch')
    _require(start - 60 <= ident['iat'] <= end + 60 and ident['exp'] > ident['iat'])
    _require(ident['exp'] <= end + 86400 and access['exp'] <= end + 86400)
    _require(ident['exp'] >= evaluation + 30 and access['exp'] >= evaluation + 30, 'auth_expired')
    return ParsedTokenResponse(envelope['access_token'], envelope.get('refresh_token'),
                               ident['exp'], access['exp'], captured)


def parse_token_response(status, body, expected, *, request_start_wall,
                         response_end_wall, evaluation_wall):
    return _safe_call(lambda: _parse(status, body, expected, request_start_wall,
                                     response_end_wall, evaluation_wall))
