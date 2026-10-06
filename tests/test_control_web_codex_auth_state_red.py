"""Synthetic, source-blind RED for the local AuthStateValidator contract.

Every dependency is an in-memory fake. A typed fake value is test data, not TLS,
native ownership, durable storage, or production admission evidence.
"""

import base64
from contextlib import contextmanager
import importlib
import json
import pathlib
import sys
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "_control_codex_auth.py"
ISSUER = "https://auth.openai.com"
CLIENT = "app_EMoamEEZ73f0CkXaXp7hrann"
WORKSPACE = "workspace_1"
SUBJECT = "auth0|invented-test-subject"
ACCESS_MARKER = "invented-access-material-for-unit-test"
REFRESH_MARKER = "invented-refresh-material-for-unit-test"


def encoded(value):
    raw = json.dumps(value, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def synthetic_jwt(claims):
    return encoded({"alg": "RS256", "typ": "JWT"}) + "." + encoded(claims) + ".c2ln"


def synthetic_body():
    claims = {
        "iss": ISSUER, "aud": CLIENT, "sub": SUBJECT, "iat": 1000,
        "exp": 5000,
        "https://api.openai.com/auth.chatgpt_account_id": WORKSPACE,
    }
    return json.dumps({
        "access_token": synthetic_jwt({"exp": 5000, "sub": ACCESS_MARKER}),
        "id_token": synthetic_jwt(claims),
        "refresh_token": REFRESH_MARKER,
        "token_type": "Bearer", "expires_in": 3600,
    }, separators=(",", ":")).encode("ascii")


def reference(account="alpha"):
    return {
        "schema": 2, "provider_id": "codex", "account_id": account,
        "profile_instance_id": "123e4567-e89b-42d3-a456-426614174000",
        "adapter_revision": "codex-chatgpt-external-auth-host-v2",
        "registration_snapshot": {
            "dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "a" * 64,
        },
    }


def principal():
    return {
        "kind": "openid_subject_workspace", "issuer": ISSUER,
        "subject": SUBJECT, "workspace_id": WORKSPACE,
    }


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeGuard:
    def __init__(self, events, label):
        self.events = events
        self.label = label

    def validate_current(self, *, deadline):
        self.events.append((self.label + ".validate", deadline))


class FakeSource:
    def __init__(self, auth, events):
        self.auth = auth
        self.events = events
        self.lease = object()
        self.reserve_hook = None
        self.finish_hook = None
        self.reserve_failure = None
        self.reserve_mode = "reserved"
        self.finish_failure = None
        self.quarantine_failure = None
        self.close_hook = None

    def open_selected(self, ctx, *, deadline):
        self.events.append(("source.open", deadline))
        return self.lease

    def validate_current(self, ctx, lease, *, deadline):
        assert lease is self.lease
        self.events.append(("source.validate", deadline))

    def read_refresh(self, lease, *, deadline):
        assert lease is self.lease
        self.events.append(("source.read", deadline))
        return REFRESH_MARKER

    def reserve_attempt(self, lease, ctx, attempt_id, *, deadline):
        assert lease is self.lease
        self.events.append(("source.reserve", attempt_id))
        if self.reserve_hook is not None:
            self.reserve_hook()
        if self.reserve_failure is not None:
            raise self.auth.AuthError(self.reserve_failure)
        if self.reserve_mode == "malformed":
            return {"attempt_id": attempt_id, "disposition": "reserved"}
        if self.reserve_mode == "wrong_id":
            return self.auth.ReserveOutcome(str(uuid.uuid4()), "reserved")
        if self.reserve_mode == "wrong_disposition":
            return self.auth.ReserveOutcome(attempt_id, "invalid")
        if self.reserve_mode == "not_written":
            self.events.append(("source.no_replace_attempt", attempt_id))
        if self.reserve_mode == "unknown":
            self.events.append(("source.rename_then_dir_fsync_uncertain", attempt_id))
        return self.auth.ReserveOutcome(attempt_id, self.reserve_mode)

    def commit_rotation(self, lease, ctx, attempt_id, new_refresh_token, *, deadline):
        assert lease is self.lease
        assert new_refresh_token == REFRESH_MARKER
        self.events.append(("source.rotation", attempt_id))

    @contextmanager
    def delivery_guard(self, ctx, lease, *, deadline):
        assert lease is self.lease
        self.events.append(("source.guard.enter", deadline))
        try:
            yield FakeGuard(self.events, "source.guard")
        finally:
            self.events.append(("source.guard.exit", deadline))

    def finish_confirmed(self, lease, ctx, attempt_id, *, deadline):
        assert lease is self.lease
        self.events.append(("source.finish", attempt_id))
        if self.finish_hook is not None:
            self.finish_hook()
        if self.finish_failure is not None:
            raise self.auth.AuthError(self.finish_failure)

    def quarantine_unknown(self, lease, ctx, attempt_id, code, *, deadline):
        assert lease is self.lease
        self.events.append(("source.quarantine", code))
        if self.quarantine_failure is not None:
            raise self.auth.AuthError(self.quarantine_failure)

    def close_selected(self, lease):
        assert lease is self.lease
        self.events.append(("source.close", None))
        if self.close_hook is not None:
            hook, self.close_hook = self.close_hook, None
            hook()


class FakeOAuth:
    def __init__(self, auth, events, clock):
        self.auth = auth
        self.events = events
        self.clock = clock
        self.requests = []
        self.before_return_hook = None

    def exchange(self, request, refresh_token, *, deadline):
        assert refresh_token == REFRESH_MARKER
        self.requests.append(request)
        self.events.append(("oauth.exchange", request.attempt_id))
        if self.before_return_hook is not None:
            self.before_return_hook()
        return self.auth.TLSExchange(
            request.attempt_id, request.context,
            ISSUER + "/api/accounts/oauth/token", CLIENT, "auth.openai.com",
            True, False, False, 200, synthetic_body(),
            self.clock.now, 1001.0,
        )


class FakeTransport:
    def __init__(self, auth, events, clock):
        self.auth = auth
        self.events = events
        self.clock = clock
        self.receipt_mode = "valid"
        self.write_mode = "valid"
        self.sent_login_ids = []
        self.prior_login_id = str(uuid.uuid4())
        self.write_count = 0
        self.channel = None
        self.ctx = None
        self.callbacks = {}
        self.callback_ids = {}

    def capture(self, ctx, *, validator_id, deadline):
        self.events.append(("transport.capture", deadline))
        self.ctx = ctx
        self.channel = self.auth.OwnedChannel(
            ctx, "123e4567-e89b-42d3-a456-426614174001",
            "123e4567-e89b-42d3-a456-426614174002", 1,
        )
        return self.channel

    def validate_current(self, channel, ctx, *, deadline):
        assert channel is self.channel
        self.events.append(("transport.validate", deadline))

    def capture_callback(self, channel, request_id, params, *, deadline):
        assert channel is self.channel
        key = (id(channel), request_id)
        if key not in self.callbacks:
            self.callbacks[key] = self.auth.CapturedCallback(
                channel, request_id, params, self.clock.now
            )
            self.callback_ids[id(self.callbacks[key])] = request_id
        self.events.append(("transport.callback.capture", request_id))
        return self.callbacks[key]

    def validate_callback(self, callback, channel, *, deadline):
        assert channel is self.channel
        request_id = self.callback_ids[id(callback)]
        assert callback is self.callbacks[(id(channel), request_id)]
        self.events.append(("transport.callback.validate", request_id))

    @contextmanager
    def delivery_guard(self, channel, ctx, *, source_guard, deadline):
        assert channel is self.channel
        assert isinstance(source_guard, FakeGuard)
        self.events.append(("transport.guard.enter", deadline))
        try:
            yield FakeGuard(self.events, "transport.guard")
        finally:
            self.events.append(("transport.guard.exit", deadline))

    def login(self, channel, payload, *, guard, deadline):
        assert channel is self.channel
        assert isinstance(guard, FakeGuard)
        sent = str(uuid.uuid4())  # Transport owns the JSON-RPC correlation id.
        self.sent_login_ids.append(sent)
        self.events.append(("transport.login", sent))
        if self.receipt_mode in ("duplicate", "late"):
            raise self.auth.AuthError("refresh_unknown")
        response = sent
        receipt_channel = channel
        if self.receipt_mode == "mismatched":
            response = str(uuid.uuid4())
        elif self.receipt_mode == "stale":
            response = self.prior_login_id
        elif self.receipt_mode == "malformed":
            sent = "not-a-uuid"
            response = sent
        elif self.receipt_mode == "wrong_channel":
            receipt_channel = self.auth.OwnedChannel(
                self.ctx,
                "123e4567-e89b-42d3-a456-426614174001",
                "123e4567-e89b-42d3-a456-426614174003", 2,
            )
        return self.auth.LoginReceipt(
            receipt_channel, sent, response, "chatgptAuthTokens"
        )

    def write_refresh(self, channel, callback, *, guard, deadline):
        assert channel is self.channel
        assert isinstance(guard, FakeGuard)
        request_id = self.callback_ids[id(callback)]
        self.write_count += 1
        self.events.append(("transport.write_refresh", request_id))
        accepted = 64 if self.write_mode == "valid" else 63
        return self.auth.WriteReceipt(channel, request_id, 64, accepted)


class AuthStateContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), "AuthStateValidator module is absent")
        sys.path.insert(0, str(MODULE.parent))
        self.addCleanup(lambda: sys.path.remove(str(MODULE.parent)))
        self.auth = importlib.import_module("_control_codex_auth")
        self.authority = importlib.import_module("_control_codex_auth_authority")
        self.fresh_fixture()

    def fresh_fixture(self):
        self.clock = Clock()
        self.events = []
        self.durable_hook = None
        self.exchange_before_hook = None
        self.exchange_after_hook = None
        self.complete_before_hook = None
        self.complete_after_hook = None
        self.source = FakeSource(self.auth, self.events)
        self.oauth = FakeOAuth(self.auth, self.events, self.clock)
        self.transport = FakeTransport(self.auth, self.events, self.clock)
        authority = self.authority
        events = self.events
        owner = self

        class RecordingCoordinator(authority.AuthCoordinator):
            def claim_reservation(self, *args, **kwargs):
                events.append(("coordinator.claim", None))
                return super().claim_reservation(*args, **kwargs)

            def mark_reservation_durable(self, *args, **kwargs):
                result = super().mark_reservation_durable(*args, **kwargs)
                events.append(("coordinator.durable", None))
                if owner.durable_hook is not None:
                    owner.durable_hook()
                return result

            def abandon_reservation(self, *args, **kwargs):
                result = super().abandon_reservation(*args, **kwargs)
                events.append(("coordinator.abandon", None))
                return result

            def begin_exchange(self, *args, **kwargs):
                if owner.exchange_before_hook is not None:
                    owner.exchange_before_hook()
                result = super().begin_exchange(*args, **kwargs)
                events.append(("coordinator.exchange_claim", None))
                if owner.exchange_after_hook is not None:
                    owner.exchange_after_hook()
                return result

            def publish_delivery(self, *args, **kwargs):
                result = super().publish_delivery(*args, **kwargs)
                events.append(("coordinator.publish", None))
                return result

            def _complete_terminal(self, *args, **kwargs):
                if owner.complete_before_hook is not None:
                    owner.complete_before_hook()
                result = super()._complete_terminal(*args, **kwargs)
                events.append(("coordinator.complete", None))
                if owner.complete_after_hook is not None:
                    owner.complete_after_hook()
                return result

        self.coordinator = RecordingCoordinator(clock=self.clock)
        self.ctx = self.auth.AuthContext(
            reference(), principal(),
            {"kind": "interactive_session",
             "id": "123e4567-e89b-42d3-a456-426614174004"},
        )
        self.validator = self.auth.AuthStateValidator(
            profile_source=self.source, oauth_client=self.oauth,
            owned_transport=self.transport, coordinator=self.coordinator,
            clock=self.clock, wall_clock=lambda: 1000.0,
        )

    def codes(self):
        return [name for name, _ in self.events]

    def denied(self, code, call):
        with self.assertRaises(self.auth.AuthError) as raised:
            call()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(str(raised.exception), code)

    def admit(self):
        return self.validator.admit(self.ctx, deadline=125.0)

    def test_success_reserves_before_exchange_and_finishes_before_delivery(self):
        delivery = self.admit()
        names = self.codes()
        for before, after in (
            ("source.read", "coordinator.claim"),
            ("coordinator.claim", "source.reserve"),
            ("source.reserve", "coordinator.durable"),
            ("coordinator.durable", "coordinator.exchange_claim"),
            ("coordinator.exchange_claim", "oauth.exchange"),
            ("oauth.exchange", "source.rotation"),
            ("source.rotation", "transport.login"),
            ("transport.login", "coordinator.publish"),
            ("coordinator.publish", "source.finish"),
            ("source.finish", "coordinator.complete"),
        ):
            self.assertLess(names.index(before), names.index(after))
        self.assertEqual(len(self.oauth.requests), 1)
        attempt = self.oauth.requests[0].attempt_id
        self.assertRegex(attempt, r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        self.assertEqual(next(value for name, value in self.events if name == "source.reserve"), attempt)
        self.assertEqual(next(value for name, value in self.events if name == "source.finish"), attempt)
        sent = self.transport.sent_login_ids[0]
        self.assertNotEqual(sent, attempt)
        self.assertRegex(sent, r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        self.assertIsInstance(delivery, self.auth.Delivery)
        self.validator.current(delivery, self.ctx, deadline=125.0)
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertEqual(names.count("source.read"), 1)
        for value in (ACCESS_MARKER, REFRESH_MARKER, SUBJECT):
            self.assertNotIn(value, repr(delivery))

    def test_preclaim_close_has_no_reserve_or_exchange(self):
        original = self.source.read_refresh

        def close_before_claim(lease, *, deadline):
            result = original(lease, deadline=deadline)
            self.validator.close()
            return result

        self.source.read_refresh = close_before_claim
        self.denied("authority_stale", self.admit)
        self.assertNotIn("source.reserve", self.codes())
        self.assertNotIn("oauth.exchange", self.codes())
        self.assertNotIn("transport.login", self.codes())

    def test_close_during_reserve_poison_first_prevents_exchange(self):
        self.source.reserve_hook = self.validator.close
        self.denied("refresh_unknown", self.admit)
        self.assertIn("source.reserve", self.codes())
        self.assertNotIn("oauth.exchange", self.codes())
        self.assertNotIn("transport.login", self.codes())

    def test_close_after_durable_reserve_prevents_oauth(self):
        self.durable_hook = self.validator.close
        self.denied("refresh_unknown", self.admit)
        self.assertIn("coordinator.durable", self.codes())
        self.assertNotIn("oauth.exchange", self.codes())
        self.assertNotIn("transport.login", self.codes())

    def test_close_first_at_begin_exchange_prevents_oauth(self):
        self.exchange_before_hook = self.validator.close
        self.denied("refresh_unknown", self.admit)
        self.assertIn("coordinator.durable", self.codes())
        self.assertNotIn("coordinator.exchange_claim", self.codes())
        self.assertNotIn("oauth.exchange", self.codes())
        self.assertNotIn("source.rotation", self.codes())

    def test_exchange_claim_first_allows_only_one_bounded_exchange(self):
        self.exchange_after_hook = self.validator.close
        self.denied("refresh_unknown", self.admit)
        self.assertIn("coordinator.exchange_claim", self.codes())
        self.assertEqual(self.codes().count("oauth.exchange"), 1)
        self.assertNotIn("source.rotation", self.codes())
        self.assertNotIn("transport.login", self.codes())

    def test_uncertain_reservation_never_exchanges_or_retries(self):
        self.source.reserve_failure = "refresh_unknown"
        self.denied("refresh_unknown", self.admit)
        self.assertEqual(self.codes().count("source.reserve"), 1)
        self.assertNotIn("oauth.exchange", self.codes())
        self.assertNotIn("transport.login", self.codes())

    def test_matching_not_written_abandons_without_oauth_or_poison(self):
        self.source.reserve_mode = "not_written"
        self.denied("refresh_busy", self.admit)
        self.assertIn("source.no_replace_attempt", self.codes())
        self.assertIn("coordinator.abandon", self.codes())
        self.assertNotIn("oauth.exchange", self.codes())
        self.assertNotIn("source.quarantine", self.codes())
        self.source.reserve_mode = "reserved"
        self.assertIsInstance(self.admit(), self.auth.Delivery)
        self.assertEqual(len(self.oauth.requests), 1)

    def test_not_written_loses_to_close_and_cannot_clear_poison(self):
        self.source.reserve_mode = "not_written"
        self.source.reserve_hook = self.validator.close
        self.denied("refresh_unknown", self.admit)
        self.assertIn("source.no_replace_attempt", self.codes())
        self.assertNotIn("coordinator.abandon", self.codes())
        self.assertNotIn("oauth.exchange", self.codes())

    def test_rename_then_dir_fsync_unknown_poison_without_oauth(self):
        self.source.reserve_mode = "unknown"
        self.denied("refresh_unknown", self.admit)
        self.assertIn("source.rename_then_dir_fsync_uncertain", self.codes())
        self.assertNotIn("coordinator.abandon", self.codes())
        self.assertNotIn("coordinator.durable", self.codes())
        self.assertNotIn("oauth.exchange", self.codes())

    def test_bad_reserve_outcomes_and_exceptions_never_start_oauth(self):
        for mode in ("wrong_id", "wrong_disposition", "malformed", "exception"):
            with self.subTest(mode=mode):
                self.fresh_fixture()
                if mode == "exception":
                    self.source.reserve_failure = "refresh_busy"
                else:
                    self.source.reserve_mode = mode
                self.denied("refresh_unknown", self.admit)
                self.assertEqual(self.codes().count("source.reserve"), 1)
                self.assertNotIn("coordinator.abandon", self.codes())
                self.assertNotIn("coordinator.durable", self.codes())
                self.assertNotIn("oauth.exchange", self.codes())

    def test_begin_requires_exact_live_durable_reservation_guard(self):
        scope_a = self.authority.AuthScope(reference(), principal())
        scope_b = self.authority.AuthScope(reference("beta"), principal())
        lease_a = self.coordinator.open(scope_a, deadline=125.0)
        lease_b = self.coordinator.open(scope_b, deadline=125.0)
        try:
            validator_id = str(uuid.uuid4())
            pending_id = str(uuid.uuid4())
            pending = self.coordinator.claim_reservation(
                lease_a, validator_id, pending_id, deadline=125.0
            )
            self.denied("authority_stale", lambda: self.coordinator.mark_reservation_durable(
                lease_a, guard=pending,
                outcome=self.auth.ReserveOutcome(pending_id, "not_written"),
            ))
            self.denied("authority_stale", lambda: self.coordinator.abandon_reservation(
                lease_a, guard=pending,
                outcome=self.auth.ReserveOutcome(pending_id, "reserved"),
            ))
            self.denied("authority_stale", lambda: self.coordinator.mark_reservation_durable(
                lease_a, guard=pending,
                outcome=self.auth.ReserveOutcome(str(uuid.uuid4()), "reserved"),
            ))
            self.denied("authority_stale", lambda: self.coordinator.begin_exchange(
                lease_a, validator_id, guard=pending, deadline=125.0
            ))
            with self.coordinator.delivery_guard(
                lease_a, scope_a, deadline=125.0
            ) as guard:
                self.denied("authority_stale", lambda: guard.begin_enqueue(
                    reservation_guard=pending, deadline=125.0
                ))
            self.coordinator.abandon_reservation(
                lease_a, guard=pending,
                outcome=self.auth.ReserveOutcome(pending_id, "not_written"),
            )
            self.denied("authority_stale", lambda: self.coordinator.begin_exchange(
                lease_a, validator_id, guard=pending, deadline=125.0
            ))
            with self.coordinator.delivery_guard(
                lease_a, scope_a, deadline=125.0
            ) as guard:
                self.denied("authority_stale", lambda: guard.begin_enqueue(
                    reservation_guard=pending, deadline=125.0
                ))
            foreign_validator = str(uuid.uuid4())
            foreign_id = str(uuid.uuid4())
            foreign = self.coordinator.claim_reservation(
                lease_b, foreign_validator, foreign_id, deadline=125.0
            )
            self.coordinator.mark_reservation_durable(
                lease_b, guard=foreign,
                outcome=self.auth.ReserveOutcome(foreign_id, "reserved"),
            )
            self.denied("authority_stale", lambda: self.coordinator.begin_exchange(
                lease_a, validator_id, guard=foreign, deadline=125.0
            ))
            with self.coordinator.delivery_guard(
                lease_a, scope_a, deadline=125.0
            ) as guard:
                self.denied("authority_stale", lambda: guard.begin_enqueue(
                    reservation_guard=foreign, deadline=125.0
                ))
            self.assertNotIn("transport.login", self.codes())
        finally:
            self.coordinator.release(lease_a)
            self.coordinator.release(lease_b)

    def test_expired_durable_guard_cannot_claim_exchange(self):
        scope = self.authority.AuthScope(reference(), principal())
        lease = self.coordinator.open(scope, deadline=125.0)
        validator_id = str(uuid.uuid4())
        attempt_id = str(uuid.uuid4())
        try:
            guard = self.coordinator.claim_reservation(
                lease, validator_id, attempt_id, deadline=125.0
            )
            self.coordinator.mark_reservation_durable(
                lease, guard=guard,
                outcome=self.auth.ReserveOutcome(attempt_id, "reserved"),
            )
            self.clock.now = 126.0
            self.denied("authority_stale", lambda: self.coordinator.begin_exchange(
                lease, validator_id, guard=guard, deadline=125.0
            ))
            self.assertNotIn("oauth.exchange", self.codes())
        finally:
            self.coordinator.release(lease)

    def test_finish_failure_after_known_receipt_never_returns_delivery(self):
        self.source.finish_failure = "refresh_unknown"
        self.denied("refresh_unknown", self.admit)
        names = self.codes()
        self.assertLess(names.index("transport.login"), names.index("source.finish"))
        self.assertLess(names.index("coordinator.publish"), names.index("source.finish"))
        self.assertNotIn("coordinator.complete", names)
        self.assertIn("source.quarantine", names)
        self.assertEqual(len(self.transport.sent_login_ids), 1)
        self.assertEqual(len(self.oauth.requests), 1)
        self.denied("authority_stale", self.admit)
        self.assertEqual(len(self.oauth.requests), 1)

    def test_bad_login_receipt_is_unknown_with_no_retry(self):
        for mode in ("malformed", "mismatched", "stale", "wrong_channel", "duplicate", "late"):
            with self.subTest(mode=mode):
                self.fresh_fixture()
                self.transport.receipt_mode = mode
                self.denied("refresh_unknown", self.admit)
                self.assertEqual(len(self.transport.sent_login_ids), 1)
                self.assertEqual(len(self.oauth.requests), 1)
                self.assertNotIn("source.finish", self.codes())

    def test_callback_duplicate_capture_and_completed_replay_have_one_write(self):
        initial = self.admit()
        params = {"reason": "unauthorized", "previousAccountId": WORKSPACE}
        callback = self.validator.capture_callback(
            initial, 73, params, deadline=125.0
        )
        duplicate = self.validator.capture_callback(
            initial, 73, params, deadline=125.0
        )
        self.assertIs(duplicate, callback)
        refreshed = self.validator.refresh(initial, callback, deadline=125.0)
        self.assertIsInstance(refreshed, self.auth.Delivery)
        self.assertIs(
            self.validator.refresh(initial, callback, deadline=125.0), refreshed
        )
        self.assertEqual(self.transport.write_count, 1)
        self.assertEqual(len(self.oauth.requests), 2)
        self.assertNotEqual(self.oauth.requests[0].attempt_id,
                            self.oauth.requests[1].attempt_id)

    def test_partial_callback_write_is_unknown_and_never_replayed(self):
        initial = self.admit()
        callback = self.validator.capture_callback(
            initial, "callback-73",
            {"reason": "unauthorized", "previousAccountId": None},
            deadline=125.0,
        )
        self.transport.write_mode = "partial"
        self.denied(
            "refresh_unknown",
            lambda: self.validator.refresh(initial, callback, deadline=125.0),
        )
        self.assertEqual(self.transport.write_count, 1)
        self.denied(
            "refresh_unknown",
            lambda: self.validator.refresh(initial, callback, deadline=125.0),
        )
        self.assertEqual(self.transport.write_count, 1)

    def test_late_captured_callback_never_exchanges_or_writes(self):
        initial = self.admit()
        callback = self.validator.capture_callback(
            initial, 74,
            {"reason": "unauthorized", "previousAccountId": WORKSPACE},
            deadline=125.0,
        )
        self.clock.now = 109.01
        self.denied(
            "authority_stale",
            lambda: self.validator.refresh(initial, callback, deadline=125.0),
        )
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertEqual(self.transport.write_count, 0)

    def test_deadline_during_terminal_finish_refuses_result(self):
        self.source.finish_hook = lambda: setattr(self.clock, "now", 126.0)
        self.denied("refresh_unknown", self.admit)
        self.assertEqual(len(self.transport.sent_login_ids), 1)
        self.assertIn("source.finish", self.codes())
        self.assertNotIn("coordinator.complete", self.codes())
        self.assertNotIn("source.finish", self.codes()[self.codes().index("source.finish") + 1:])

    def test_forged_callback_and_delivery_cannot_bypass_provenance(self):
        initial = self.admit()
        forged = self.auth.CapturedCallback(
            self.transport.channel, 75,
            {"reason": "unauthorized", "previousAccountId": WORKSPACE},
            self.clock.now,
        )
        self.denied(
            "authority_stale",
            lambda: self.validator.refresh(initial, forged, deadline=125.0),
        )
        self.assertEqual(len(self.oauth.requests), 1)
        with self.assertRaises((self.auth.AuthError, TypeError, ValueError)):
            self.auth.Delivery(
                str(uuid.uuid4()), self.ctx, self.transport.channel, object()
            )

    def test_bad_context_rejected_before_any_dependency_io(self):
        with self.assertRaises(self.auth.AuthError):
            self.auth.AuthContext(
                reference(), principal(),
                {"kind": "interactive_session", "id": "not-a-uuid"},
            )
        self.assertEqual(self.events, [])

    def test_token_material_is_absent_from_errors_and_repr(self):
        self.source.finish_failure = "refresh_unknown"
        with self.assertRaises(self.auth.AuthError) as raised:
            self.admit()
        exposed = repr(raised.exception) + str(raised.exception)
        for value in (ACCESS_MARKER, REFRESH_MARKER, SUBJECT):
            self.assertNotIn(value, exposed)
        self.assertNotIn(ACCESS_MARKER, repr(self.ctx))
        self.assertNotIn(REFRESH_MARKER, repr(self.ctx))

    def test_finish_callback_cannot_reenter_same_account_while_pending(self):
        observations = []
        scope = self.authority.AuthScope(reference(), principal())

        def during_finish():
            with self.assertRaises(self.authority.AuthError) as raised:
                self.coordinator.open(scope, deadline=100.25)
            observations.append(raised.exception.code)

        self.source.finish_hook = during_finish
        delivery = self.admit()
        self.assertEqual(observations, ["authority_stale"])
        self.assertIsInstance(delivery, self.auth.Delivery)

    def test_other_account_is_independent_during_terminal_pending(self):
        observations = []
        scope_b = self.authority.AuthScope(reference("beta"), principal())

        def during_finish():
            lease_b = self.coordinator.open(scope_b, deadline=100.25)
            try:
                self.coordinator.check(lease_b, scope_b, deadline=100.25)
                observations.append("B current")
            finally:
                self.coordinator.release(lease_b)

        self.source.finish_hook = during_finish
        self.assertIsInstance(self.admit(), self.auth.Delivery)
        self.assertEqual(observations, ["B current"])

    def test_close_during_finish_blocks_terminal_completion_and_return(self):
        self.source.finish_hook = self.validator.close
        self.denied("refresh_unknown", self.admit)
        self.assertEqual(self.codes().count("transport.login"), 1)
        self.assertEqual(self.codes().count("source.finish"), 1)
        self.assertIn("source.quarantine", self.codes())
        self.assertEqual(len(self.oauth.requests), 1)

    def test_close_first_at_terminal_completion_refuses_delivery(self):
        self.complete_before_hook = self.validator.close
        self.denied("refresh_unknown", self.admit)
        self.assertIn("source.finish", self.codes())
        self.assertNotIn("coordinator.complete", self.codes())

    def test_terminal_completion_first_survives_later_close(self):
        self.complete_after_hook = self.validator.close
        delivery = self.admit()
        self.assertIsInstance(delivery, self.auth.Delivery)
        self.assertIn("coordinator.complete", self.codes())
        self.denied(
            "authority_stale",
            lambda: self.validator.current(delivery, self.ctx, deadline=125.0),
        )

    def test_cleanup_close_after_completion_does_not_undo_delivery(self):
        self.source.close_hook = self.validator.close
        delivery = self.admit()
        self.assertIsInstance(delivery, self.auth.Delivery)
        self.assertEqual(self.codes().count("source.finish"), 1)
        self.denied(
            "authority_stale",
            lambda: self.validator.current(delivery, self.ctx, deadline=125.0),
        )

    def test_crash_before_finish_cannot_replay_pending_attempt(self):
        # A fake restart is a new validator against the same pending source state.
        # The source refuses selection rather than manufacturing a new OAuth attempt.
        self.source.finish_failure = "refresh_unknown"
        self.denied("refresh_unknown", self.admit)
        first_count = len(self.oauth.requests)

        def pending_open(ctx, *, deadline):
            self.events.append(("source.pending_restart", deadline))
            raise self.auth.AuthError("refresh_unknown")

        self.source.open_selected = pending_open
        restarted = self.auth.AuthStateValidator(
            profile_source=self.source, oauth_client=self.oauth,
            owned_transport=self.transport,
            coordinator=self.authority.AuthCoordinator(clock=self.clock),
            clock=self.clock, wall_clock=lambda: 1000.0,
        )
        self.denied(
            "refresh_unknown", lambda: restarted.admit(self.ctx, deadline=125.0)
        )
        self.assertIn("source.pending_restart", self.codes())
        self.assertEqual(len(self.oauth.requests), first_count)


if __name__ == "__main__":
    unittest.main()
