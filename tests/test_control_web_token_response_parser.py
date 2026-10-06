"""Source-blind synthetic RED tests for the frozen token-response data contract.

The invented JWT signature bytes below are structural fixtures, not signatures.
Parse success is never treated as authentication, TLS evidence, or admission.
"""

import base64
import copy
import hashlib
import importlib
import json
import math
from pathlib import Path
from unittest import TestCase, main, mock
import sys


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
MODULE = BIN / "_control_codex_token_response.py"
CLIENT = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"
AUTH = "https://api.openai.com/auth"
ACCESS = "synthetic-access-secret"
REFRESH = "synthetic-refresh-secret"
ID = "synthetic-id-secret"
START, END, EVAL = 1000, 1001, 1002


def reference():
    return {
        "schema": 2,
        "provider_id": "codex",
        "account_id": "synthetic_alpha",
        "profile_instance_id": "123e4567-e89b-42d3-a456-426614174000",
        "adapter_revision": "codex-chatgpt-external-auth-host-v2",
        "registration_snapshot": {
            "dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "a" * 64,
        },
    }


def principal():
    return {
        "kind": "openid_subject_workspace",
        "issuer": ISSUER,
        "subject": "synthetic|alice",
        "workspace_id": "synthetic_workspace",
    }


def b64(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def compact(header, payload, signature=b"invented-signature"):
    def encode(value):
        if isinstance(value, bytes):
            return b64(value)
        return b64(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
    return ".".join((encode(header), encode(payload), b64(signature)))


def claims():
    ident = {
        "iss": ISSUER, "aud": CLIENT, "sub": "synthetic|alice",
        "iat": 1000, "exp": 2000,
        AUTH: {"chatgpt_account_id": "synthetic_workspace"},
    }
    access = {"exp": 2000, AUTH: {"chatgpt_account_id": "synthetic_workspace"}}
    return ident, access


def response(*, ident=None, access=None, id_header=None, access_header=None,
             id_token=None, access_token=None, extra=None):
    default_id, default_access = claims()
    ident = default_id if ident is None else ident
    access = default_access if access is None else access
    id_token = id_token or compact(id_header or {"alg": "RS256", "typ": "JWT"}, ident)
    access_token = access_token or compact(access_header or {"alg": "RS256"}, access)
    body = {"access_token": access_token, "id_token": id_token}
    if extra:
        body.update(extra)
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()


class TokenResponseContract(TestCase):
    def setUp(self):
        # A missing implementation is one explicit RED assertion, never ImportError/skip.
        self.assertTrue(MODULE.is_file(), f"contract module unavailable: {MODULE.name}")
        sys.path.insert(0, str(BIN))
        self.addCleanup(lambda: sys.path.remove(str(BIN)))
        self.authority = importlib.import_module("_control_codex_auth_authority")
        self.parser = importlib.import_module("_control_codex_token_response")
        self.ref = reference()
        self.principal = principal()
        self.scope = self.authority.AuthScope(self.ref, self.principal)

    def parse(self, body=None, *, status=200, expected=None, start=START,
              end=END, evaluation=EVAL):
        return self.parser.parse_token_response(
            status, response() if body is None else body,
            self.scope if expected is None else expected,
            request_start_wall=start, response_end_wall=end,
            evaluation_wall=evaluation,
        )

    def rejects(self, code, body=None, **kwargs):
        with self.assertRaises(self.parser.TokenResponseError) as caught:
            self.parse(body, **kwargs)
        error = caught.exception
        self.assertEqual(error.code, code)
        self.assertEqual(str(error), code)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        for secret in (ACCESS, REFRESH, ID, "synthetic|alice"):
            self.assertNotIn(secret, repr(error))

    def test_valid_data_is_minimized_frozen_and_has_no_admission_marker(self):
        ident, access = claims()
        token = compact({"alg": "RS256"}, ident)
        bearer = compact({"alg": "RS256"}, access)
        result = self.parse(response(id_token=token, access_token=bearer,
                                     extra={"refresh_token": REFRESH,
                                            "token_type": "Bearer", "expires_in": 600,
                                            "scope": "openid profile"}))
        self.assertEqual(result.access_token, bearer)
        self.assertEqual(result.refresh_token, REFRESH)
        self.assertEqual(result.id_expires_at, 2000)
        self.assertEqual(result.access_expires_at, 2000)
        self.assertIsInstance(result.scope_snapshot, tuple)
        self.assertTrue(result.usable_at(1970))
        self.assertFalse(result.usable_at(1971))
        self.assertFalse(hasattr(result, "__dict__"))
        self.assertFalse(any(hasattr(result, name) for name in
                             ("id_token", "claims", "verified", "admitted", "to_dict")))
        for secret in (token, bearer, REFRESH, "synthetic|alice"):
            self.assertNotIn(secret, repr(result))
        with self.assertRaises((AttributeError, TypeError)):
            result.access_token = "changed"
        self.ref["registration_snapshot"]["sha256"] = "b" * 64
        self.principal["subject"] = "changed"
        self.assertEqual(result.access_token, bearer)
        self.assertTrue(result.usable_at(1970))

    def test_no_refresh_is_none_and_errors_are_closed(self):
        self.assertIsNone(self.parse().refresh_token)
        err = self.parser.TokenResponseError("secret arbitrary diagnostic")
        self.assertEqual(err.code, "auth_response_invalid")
        self.assertEqual(str(err), "auth_response_invalid")
        self.assertNotIn("secret", repr(err))

    def test_scope_and_scalar_stages_precede_body(self):
        self.rejects("authority_stale", b"not json", expected={})
        for values in ((True, END, EVAL), (math.nan, END, EVAL),
                       (START, START - 1, EVAL), (START, END, END - 1),
                       (-1, END, EVAL), (START, math.inf, EVAL)):
            with self.subTest(values=values):
                self.rejects("auth_response_invalid", b"not json", start=values[0],
                             end=values[1], evaluation=values[2])
        self.rejects("auth_response_invalid", b"not json", status=True)
        self.rejects("auth_response_invalid", b"not json", status=401)

    def test_envelope_exactness_utf8_duplicates_depth_and_limits(self):
        good = json.loads(response())
        bad_bodies = [
            "{}", "[]", "NaN", '{"access_token":"a","access_token":"b"}',
            json.dumps({**good, "unexpected": 1}),
            json.dumps({**good, "refresh_token": None}),
            json.dumps({**good, "access_token": ""}),
            json.dumps({**good, "id_token": 7}),
            json.dumps({**good, "token_type": "bearer"}),
            json.dumps({**good, "expires_in": True}),
            json.dumps({**good, "expires_in": 0}),
            json.dumps({**good, "expires_in": 86401}),
            json.dumps({**good, "scope": "openid  profile"}),
            json.dumps({**good, "scope": " openid"}),
            json.dumps({**good, "scope": "openid\nprofile"}),
            json.dumps({**good, "refresh_token": "has space"}),
            json.dumps({**good, "refresh_token": "x" * 16385}),
            json.dumps({**good, "scope": "x" * 4097}),
            json.dumps({**good, "scope": "\ud800"}),
        ]
        for raw in bad_bodies:
            with self.subTest(raw=raw[:60]):
                self.rejects("auth_response_invalid", raw.encode())
        for raw in (b"\xff", b"x" * 65537, "{}".encode("utf-16")):
            self.rejects("auth_response_invalid", raw)
        self.rejects("auth_response_invalid", "{}")

    def test_jwt_structure_canonical_base64_headers_and_nested_json(self):
        ident, access = claims()
        deep = 0
        for _ in range(17):
            deep = [deep]
        malformed = (
            "opaque-access", "a.b", "a.b.c.d", "a.b.",
            compact({"alg": "none"}, access),
            compact({"alg": "HS256"}, access),
            compact({"alg": "RS256", "kid": "\n"}, access),
            compact({"alg": "RS256", "x": 1}, access),
            compact(b'{"alg":"RS256","alg":"RS256"}', access),
            compact({"alg": "RS256"}, b'{"exp":2000,"exp":2000}'),
            compact({"alg": "RS256"}, {"exp": 2000, "other": float("nan")}),
            compact({"alg": "RS256"}, b'{"exp":2000,"other":"\\ud800"}'),
            compact({"alg": "RS256"}, b'{"exp":2000,"other":{"a":1,"a":2}}'),
            compact({"alg": "RS256"}, {"exp": 2000, "other": [0] * 16385}),
            compact({"alg": "RS256"}, {"exp": 2000, "other": deep}),
            compact({"alg": "RS256", "kid": "x" * 257}, access),
            compact({"alg": "RS256", "kid": "x" * 2049}, access),
        )
        for token in malformed:
            with self.subTest(token=token[:32]):
                self.rejects("auth_response_invalid", response(access_token=token))
        self.rejects("auth_response_invalid", response(id_token="opaque-id"))
        self.rejects("auth_response_invalid", response(
            id_token=compact({"alg": "RS256"}, ident, signature=b"")))
        self.rejects("auth_response_invalid", response(
            id_token=compact({"alg": "RS256", "typ": "not-JWT"}, ident)))
        # Noncanonical trailing bits: `Zh` decodes like `Zg`, but is forbidden.
        canonical = compact({"alg": "RS256"}, access).split(".")
        canonical[2] = "Zh"
        self.rejects("auth_response_invalid", response(access_token=".".join(canonical)))

    def test_claim_type_failures_dominate_identity_mismatch(self):
        ident, access = claims()
        ident["sub"] = "another-synthetic-person"
        for mutate in (
            lambda i, a: i.update(exp=True),
            lambda i, a: i.update(aud=[]),
            lambda i, a: i.update(azp=5),
            lambda i, a: i.pop("iss"),
            lambda i, a: i.pop(AUTH),
            lambda i, a: i.update({AUTH: {"chatgpt_account_id": 5}}),
            lambda i, a: a.update(exp="2000"),
            lambda i, a: a.update({AUTH: {"chatgpt_account_id": None}}),
            lambda i, a: a.update(iat=True),
        ):
            i, a = copy.deepcopy(ident), copy.deepcopy(access)
            mutate(i, a)
            self.rejects("auth_response_invalid", response(ident=i, access=a))

    def test_well_typed_identity_mismatches(self):
        mutators = (
            lambda i, a: i.update(iss="https://example.invalid"),
            lambda i, a: i.update(aud="different-client"),
            lambda i, a: i.update(aud=[CLIENT, "other-client"]),
            lambda i, a: i.update(sub="another-synthetic-person"),
            lambda i, a: i.update(azp="different-client"),
            lambda i, a: i.update({AUTH: {"chatgpt_account_id": "other_workspace"}}),
            lambda i, a: a.update({AUTH: {"chatgpt_account_id": "other_workspace"}}),
        )
        for mutate in mutators:
            i, a = claims()
            mutate(i, a)
            self.rejects("identity_mismatch", response(ident=i, access=a))

    def test_optional_at_hash_binds_exact_returned_access_token(self):
        ident, access = claims()
        bearer = compact({"alg": "RS256"}, access)
        ident["at_hash"] = b64(hashlib.sha256(bearer.encode("ascii")).digest()[:16])
        self.parse(response(ident=ident, access_token=bearer))
        ident["at_hash"] = b64(b"0" * 16)
        self.rejects("identity_mismatch", response(ident=ident, access_token=bearer))
        ident["at_hash"] = "not/canonical="
        self.rejects("auth_response_invalid", response(ident=ident))

    def test_singleton_audience_and_uninterpreted_access_claims(self):
        ident, access = claims()
        ident["aud"] = [CLIENT]
        access["iss"] = "opaque-access-issuer"
        access["sub"] = "opaque-access-subject"
        access["iat"] = 1
        self.parse(response(ident=ident, access=access))
        access["iat"] = 0
        self.rejects("auth_response_invalid", response(ident=ident, access=access))

    def test_time_bounds_lifetime_and_precedence(self):
        ident, access = claims()
        ident["iat"] = 939
        self.rejects("auth_response_invalid", response(ident=ident))
        ident, access = claims()
        ident["iat"] = 1062
        self.rejects("auth_response_invalid", response(ident=ident))
        ident, access = claims()
        ident["exp"] = END + 86401
        self.rejects("auth_response_invalid", response(ident=ident))
        ident, access = claims()
        access["exp"] = END + 86401
        self.rejects("auth_response_invalid", response(ident=ident, access=access))
        ident, access = claims()
        ident["exp"] = EVAL + 29
        self.rejects("auth_expired", response(ident=ident))
        ident, access = claims()
        access["exp"] = EVAL + 29
        self.rejects("auth_expired", response(ident=ident, access=access))
        ident, access = claims()
        ident["sub"] = "other"
        ident["exp"] = EVAL + 29
        self.rejects("identity_mismatch", response(ident=ident))
        for wall in (True, math.nan, -1, "1000"):
            with self.assertRaises(self.parser.TokenResponseError) as caught:
                self.parse().usable_at(wall)
            self.assertEqual(caught.exception.code, "auth_response_invalid")

    def test_parser_never_samples_clock_or_io(self):
        with mock.patch("builtins.open", side_effect=AssertionError("open")), \
             mock.patch("os.open", side_effect=AssertionError("os.open")), \
             mock.patch("time.time", side_effect=AssertionError("time")), \
             mock.patch("time.time_ns", side_effect=AssertionError("time_ns")), \
             mock.patch("time.monotonic", side_effect=AssertionError("monotonic")):
            result = self.parse()
            self.assertTrue(result.usable_at(EVAL))


if __name__ == "__main__":
    main()
