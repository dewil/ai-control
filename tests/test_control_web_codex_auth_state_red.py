"""Synthetic, source-blind RED for the local AuthStateValidator contract.

Every dependency is an in-memory fake. A typed fake value is test data, not TLS,
native ownership, durable storage, or production admission evidence.
"""

import base64
import copy
from collections.abc import Mapping
from contextlib import contextmanager
import importlib
import json
import pathlib
import sys
from types import SimpleNamespace
import unittest
from unittest import mock
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


def synthetic_body(*, flat_only=False, access_serial=1):
    claims = {
        "iss": ISSUER, "aud": CLIENT, "sub": SUBJECT, "iat": 1000,
        "exp": 5000,
    }
    if flat_only:
        claims["https://api.openai.com/auth.chatgpt_account_id"] = WORKSPACE
    else:
        claims["https://api.openai.com/auth"] = {
            "chatgpt_account_id": WORKSPACE,
        }
    return json.dumps({
        "access_token": synthetic_jwt({
            "exp": 5000, "sub": ACCESS_MARKER, "synthetic_serial": access_serial,
        }),
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


class WallClock:
    def __init__(self):
        self.next_value = 1000.0
        self.samples = []

    def __call__(self):
        value = self.next_value
        self.next_value += 1.0
        self.samples.append(value)
        return value


class FakeGuard:
    def __init__(self, events, label, hook=None):
        self.events = events
        self.label = label
        self.hook = hook

    def validate_current(self, *, deadline):
        self.events.append((self.label + ".validate", deadline))
        if self.hook is not None:
            hook, self.hook = self.hook, None
            hook()


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
        self.guard_validate_hook = None
        self.completed_attempts = []

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
            yield FakeGuard(self.events, "source.guard", self.guard_validate_hook)
        finally:
            self.events.append(("source.guard.exit", deadline))

    def finish_confirmed(self, lease, ctx, attempt_id, *, deadline):
        assert lease is self.lease
        self.events.append(("source.finish", attempt_id))
        if self.finish_hook is not None:
            self.finish_hook()
        if self.finish_failure is not None:
            raise self.auth.AuthError(self.finish_failure)
        self.completed_attempts.append(attempt_id)

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
    def __init__(self, auth, events, clock, wall_clock):
        self.auth = auth
        self.events = events
        self.clock = clock
        self.wall_clock = wall_clock
        self.requests = []
        self.before_return_hook = None
        self.body_mode = "nested"
        self.received_wall_override = None
        self.received_walls = []
        self.last_access_token = None
        self.access_tokens = []

    def exchange(self, request, refresh_token, *, deadline):
        assert refresh_token == REFRESH_MARKER
        self.requests.append(request)
        self.events.append(("oauth.exchange", request.attempt_id))
        if self.before_return_hook is not None:
            self.before_return_hook()
        body = synthetic_body(
            flat_only=self.body_mode == "flat_only",
            access_serial=len(self.requests),
        )
        self.last_access_token = json.loads(body)["access_token"]
        self.access_tokens.append(self.last_access_token)
        received_wall = self.wall_clock()
        if self.received_wall_override is not None:
            received_wall = self.received_wall_override
        self.received_walls.append(received_wall)
        return self.auth.TLSExchange(
            request.attempt_id, request.context,
            ISSUER + "/api/accounts/oauth/token", CLIENT, "auth.openai.com",
            True, False, False, 200, body,
            self.clock.now, received_wall,
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
        self.capture_owner = None
        self.callback_failure = None
        self.login_write_hook = None
        self.login_receipt_hook = None
        self.write_refresh_hook = None
        self.expected_access = None
        self.payload_checks = []

    def capture(self, ctx, *, validator_id, deadline):
        self.events.append(("transport.capture", deadline))
        if self.capture_owner is not None and validator_id != self.capture_owner:
            raise self.auth.AuthError("owned_host_unproven")
        self.capture_owner = validator_id
        self.ctx = ctx
        self.channel = self.auth.OwnedChannel(
            ctx, "123e4567-e89b-42d3-a456-426614174001",
            "123e4567-e89b-42d3-a456-426614174002", 1,
        )
        return self.channel

    def validate_current(self, channel, ctx, *, deadline):
        if channel is not self.channel:
            raise self.auth.AuthError("authority_stale")
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
        if channel is not self.channel or self.callback_failure is not None:
            raise self.auth.AuthError(self.callback_failure or "authority_stale")
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
        assert isinstance(payload, Mapping)
        assert set(payload) == {
            "type", "accessToken", "chatgptAccountId", "chatgptPlanType",
        }
        assert payload["type"] == "chatgptAuthTokens"
        assert payload["accessToken"] == self.expected_access()
        assert payload["chatgptAccountId"] == WORKSPACE
        assert payload["chatgptPlanType"] is None
        sent = str(uuid.uuid4())  # Transport owns the JSON-RPC correlation id.
        self.sent_login_ids.append(sent)
        self.events.append(("transport.login", sent))
        if self.login_write_hook is not None:
            self.login_write_hook()
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
        receipt = self.auth.LoginReceipt(
            receipt_channel, sent, response, "chatgptAuthTokens"
        )
        self.events.append(("transport.login.receipt", response))
        if self.login_receipt_hook is not None:
            self.login_receipt_hook()
        return receipt

    def write_refresh(self, channel, callback, payload, *, guard, deadline):
        assert channel is self.channel
        assert isinstance(guard, FakeGuard)
        request_id = self.callback_ids[id(callback)]
        assert isinstance(payload, Mapping)
        assert set(payload) == {
            "accessToken", "chatgptAccountId", "chatgptPlanType",
        }
        assert payload["accessToken"] == self.expected_access()
        assert payload["chatgptAccountId"] == WORKSPACE
        assert payload["chatgptPlanType"] is None
        self.payload_checks.append((request_id, tuple(sorted(payload))))
        self.write_count += 1
        self.events.append(("transport.write_refresh", request_id))
        if self.write_refresh_hook is not None:
            self.write_refresh_hook()
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
        self.wall = WallClock()
        self.events = []
        self.durable_hook = None
        self.exchange_before_hook = None
        self.exchange_after_hook = None
        self.complete_before_hook = None
        self.complete_after_hook = None
        self.publish_before_hook = None
        self.publish_after_hook = None
        self.last_provisional = None
        self.last_final_stamp = None
        self.final_stamp_transform = None
        self.last_authority_lease = None
        self.source = FakeSource(self.auth, self.events)
        self.oauth = FakeOAuth(self.auth, self.events, self.clock, self.wall)
        self.transport = FakeTransport(self.auth, self.events, self.clock)
        self.transport.expected_access = lambda: self.oauth.last_access_token
        authority = self.authority
        events = self.events
        owner = self

        class RecordingCoordinator(self.auth.AuthCoordinator):
            @contextmanager
            def delivery_guard(self, *args, **kwargs):
                with super().delivery_guard(*args, **kwargs) as guard:
                    guard_type = type(guard)
                    original_begin = guard_type.begin_enqueue
                    original_confirm = guard_type.confirm

                    def observed_begin(active_guard, *begin_args, **begin_kwargs):
                        try:
                            result = original_begin(
                                active_guard, *begin_args, **begin_kwargs
                            )
                        except authority.AuthError:
                            events.append(("guard.begin.refused", None))
                            raise
                        events.append(("guard.begin.claimed", None))
                        return result

                    def observed_confirm(active_guard, *confirm_args, **confirm_kwargs):
                        result = original_confirm(
                            active_guard, *confirm_args, **confirm_kwargs
                        )
                        events.append(("guard.confirm", None))
                        return result

                    with mock.patch.object(guard_type, "begin_enqueue", observed_begin), \
                         mock.patch.object(guard_type, "confirm", observed_confirm):
                        yield guard

            def open(self, *args, **kwargs):
                result = super().open(*args, **kwargs)
                owner.last_authority_lease = result
                return result

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
                if owner.publish_before_hook is not None:
                    owner.publish_before_hook()
                result = super().publish_delivery(*args, **kwargs)
                events.append(("coordinator.publish", None))
                owner.last_provisional = result
                if owner.publish_after_hook is not None:
                    owner.publish_after_hook()
                return result

            def _complete_terminal(self, *args, **kwargs):
                if owner.complete_before_hook is not None:
                    owner.complete_before_hook()
                result = super()._complete_terminal(*args, **kwargs)
                events.append(("coordinator.complete", None))
                owner.last_final_stamp = result
                if owner.complete_after_hook is not None:
                    owner.complete_after_hook()
                if owner.final_stamp_transform is not None:
                    return owner.final_stamp_transform(result)
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
            clock=self.clock, wall_clock=self.wall,
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

    def duplicate_strict_stamp(self, real):
        builders = (
            lambda: copy.copy(real),
            lambda: copy.deepcopy(real),
            lambda: type(real)(real.owner_generation, real.credential_generation),
        )
        for build in builders:
            try:
                duplicate = build()
            except (TypeError, ValueError, copy.Error):
                continue
            if duplicate is not real and type(duplicate) is type(real):
                self.assertEqual(duplicate.owner_generation, real.owner_generation)
                self.assertEqual(
                    duplicate.credential_generation, real.credential_generation
                )
                self.stamp_fabrication_route = "distinct same type"
                return duplicate
        # An opaque stamp may refuse construction and return itself on copying.
        # Its visible generation fields still must not authorize a substitute.
        self.stamp_fabrication_route = "field matched substitute"
        return SimpleNamespace(
            owner_generation=real.owner_generation,
            credential_generation=real.credential_generation,
        )

    def test_strict_coordinator_export_is_exact_independent_class(self):
        self.assertIs(self.auth.AuthCoordinator, self.authority.AuthStateCoordinator)
        self.assertIsNot(self.auth.AuthCoordinator, self.authority.AuthCoordinator)
        self.assertFalse(issubclass(
            self.auth.AuthCoordinator, self.authority.AuthCoordinator
        ))
        self.assertIsInstance(self.coordinator, self.auth.AuthCoordinator)

    def test_legacy_coordinator_is_rejected_before_dependency_io(self):
        legacy = self.authority.AuthCoordinator(clock=self.clock)
        try:
            validator = self.auth.AuthStateValidator(
                profile_source=self.source, oauth_client=self.oauth,
                owned_transport=self.transport, coordinator=legacy,
                clock=self.clock, wall_clock=self.wall,
            )
        except self.auth.AuthError as exc:
            self.assertEqual(exc.code, "authority_stale")
        else:
            self.denied(
                "authority_stale",
                lambda: validator.admit(self.ctx, deadline=125.0),
            )
        self.assertEqual(self.events, [])
        self.assertEqual(self.oauth.requests, [])

    def test_legacy_and_fabricated_authority_values_cannot_act_as_strict(self):
        scope = self.authority.AuthScope(reference(), principal())
        legacy = self.authority.AuthCoordinator(clock=self.clock)
        legacy_lease = legacy.open(scope, deadline=125.0)
        strict_lease = self.coordinator.open(scope, deadline=125.0)
        try:
            validator_id = str(uuid.uuid4())
            attempt_id = str(uuid.uuid4())
            reservation = self.coordinator.claim_reservation(
                strict_lease, validator_id, attempt_id, deadline=125.0
            )
            self.coordinator.mark_reservation_durable(
                strict_lease, guard=reservation,
                outcome=self.auth.ReserveOutcome(attempt_id, "reserved"),
            )
            self.denied("authority_stale", lambda: self.coordinator.check(
                legacy_lease, scope, deadline=125.0
            ))
            self.denied("authority_stale", lambda: self.coordinator.check(
                object(), scope, deadline=125.0
            ))
            try:
                copied = copy.copy(strict_lease)
            except (TypeError, ValueError):
                copied = None
            if copied is not None and copied is not strict_lease:
                self.denied("authority_stale", lambda: self.coordinator.check(
                    copied, scope, deadline=125.0
                ))
            try:
                copied_guard = copy.copy(reservation)
            except (TypeError, ValueError):
                copied_guard = None
            if copied_guard is not None and copied_guard is not reservation:
                self.denied("authority_stale", lambda: self.coordinator.begin_exchange(
                    strict_lease, validator_id, guard=copied_guard, deadline=125.0
                ))
            self.denied("authority_stale", lambda: self.coordinator.begin_exchange(
                strict_lease, validator_id, guard=object(), deadline=125.0
            ))
            with legacy.delivery_guard(
                legacy_lease, scope, deadline=125.0
            ) as legacy_guard:
                legacy_guard.begin_enqueue()
                legacy_guard.confirm()
                self.denied("authority_stale", lambda: self.coordinator.begin_exchange(
                    strict_lease, validator_id, guard=legacy_guard, deadline=125.0
                ))
                self.denied("authority_stale", lambda: self.coordinator.publish_delivery(
                    strict_lease, guard=legacy_guard, deadline=125.0
                ))
                legacy_stamp = legacy.publish_delivery(
                    legacy_lease, guard=legacy_guard, deadline=125.0
                )
            with self.assertRaises((self.auth.AuthError, TypeError, ValueError)):
                self.auth.Delivery(
                    str(uuid.uuid4()), self.ctx,
                    self.auth.OwnedChannel(
                        self.ctx,
                        "123e4567-e89b-42d3-a456-426614174001",
                        "123e4567-e89b-42d3-a456-426614174002", 1,
                    ),
                    legacy_stamp,
                )
            fabricated_stamp = type(legacy_stamp)(
                legacy_stamp.owner_generation, legacy_stamp.credential_generation
            )
            with self.assertRaises((self.auth.AuthError, TypeError, ValueError)):
                self.auth.Delivery(
                    str(uuid.uuid4()), self.ctx,
                    self.auth.OwnedChannel(
                        self.ctx,
                        "123e4567-e89b-42d3-a456-426614174001",
                        "123e4567-e89b-42d3-a456-426614174002", 1,
                    ),
                    fabricated_stamp,
                )
        finally:
            self.coordinator.release(strict_lease)
            legacy.release(legacy_lease)

    def test_fabricated_or_field_matched_stamp_cannot_create_delivery(self):
        self.final_stamp_transform = self.duplicate_strict_stamp
        self.denied("refresh_unknown", self.admit)
        self.assertIsNotNone(self.last_final_stamp)
        self.assertIn(
            self.stamp_fabrication_route,
            ("distinct same type", "field matched substitute"),
        )
        self.assertIn("source.finish", self.codes())
        self.assertIn("coordinator.complete", self.codes())
        self.assertEqual(len(self.oauth.requests), 1)

    def test_real_strict_stamp_from_earlier_attempt_cannot_authorize_refresh(self):
        initial = self.admit()
        borrowed = self.last_final_stamp
        self.assertIsNotNone(borrowed)
        callback = self.validator.capture_callback(
            initial, 87,
            {"reason": "unauthorized", "previousAccountId": WORKSPACE},
            deadline=125.0,
        )
        self.final_stamp_transform = lambda actual: borrowed
        self.denied(
            "refresh_unknown",
            lambda: self.validator.refresh(initial, callback, deadline=125.0),
        )
        self.assertIsNot(self.last_final_stamp, borrowed)
        self.assertEqual(self.codes().count("coordinator.complete"), 2)
        self.assertEqual(self.transport.write_count, 1)
        self.denied(
            "authority_stale",
            lambda: self.validator.current(initial, self.ctx, deadline=125.0),
        )

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
            ("transport.login.receipt", "guard.confirm"),
            ("guard.confirm", "coordinator.publish"),
            ("coordinator.publish", "source.finish"),
            ("source.finish", "coordinator.complete"),
        ):
            self.assertLess(names.index(before), names.index(after))
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertGreaterEqual(len(self.wall.samples), 3)
        self.assertLessEqual(
            self.oauth.requests[0].started_wall, self.oauth.received_walls[0]
        )
        self.assertLessEqual(self.oauth.received_walls[0], self.wall.samples[-1])
        self.assertEqual(self.wall.samples, sorted(self.wall.samples))
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

    def test_flat_only_id_workspace_cannot_admit(self):
        self.oauth.body_mode = "flat_only"
        self.denied("auth_response_invalid", self.admit)
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertNotIn("source.rotation", self.codes())
        self.assertNotIn("transport.login", self.codes())

    def test_received_wall_after_actual_evaluation_is_rejected(self):
        self.oauth.received_wall_override = 2000.0
        self.denied("auth_response_invalid", self.admit)
        self.assertEqual(self.oauth.received_walls, [2000.0])
        self.assertLess(max(self.wall.samples), 2000.0)
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertNotIn("source.rotation", self.codes())
        self.assertNotIn("transport.login", self.codes())

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
        self.assertNotIn("coordinator.abandon", self.codes())
        self.assertNotIn("coordinator.durable", self.codes())
        self.assertNotIn("oauth.exchange", self.codes())
        self.assertNotIn("transport.login", self.codes())
        second = self.auth.AuthStateValidator(
            profile_source=self.source, oauth_client=self.oauth,
            owned_transport=FakeTransport(self.auth, self.events, self.clock),
            coordinator=self.coordinator, clock=self.clock,
            wall_clock=self.wall,
        )
        self.denied(
            "authority_stale", lambda: second.admit(self.ctx, deadline=125.0)
        )
        self.assertEqual(self.codes().count("source.reserve"), 1)

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
                second = self.auth.AuthStateValidator(
                    profile_source=self.source, oauth_client=self.oauth,
                    owned_transport=FakeTransport(self.auth, self.events, self.clock),
                    coordinator=self.coordinator, clock=self.clock,
                    wall_clock=self.wall,
                )
                self.denied(
                    "authority_stale",
                    lambda: second.admit(self.ctx, deadline=125.0),
                )
                self.assertEqual(self.codes().count("source.reserve"), 1)
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

    def test_terminal_completion_requires_exact_guard_publication_and_live_f(self):
        scope = self.authority.AuthScope(reference(), principal())
        scope_b = self.authority.AuthScope(reference("beta"), principal())
        lease = self.coordinator.open(scope, deadline=125.0)
        lease_b = self.coordinator.open(scope_b, deadline=125.0)
        validator_id = str(uuid.uuid4())
        attempt_id = str(uuid.uuid4())
        try:
            reservation = self.coordinator.claim_reservation(
                lease, validator_id, attempt_id, deadline=125.0
            )
            self.coordinator.mark_reservation_durable(
                lease, guard=reservation,
                outcome=self.auth.ReserveOutcome(attempt_id, "reserved"),
            )
            self.coordinator.begin_exchange(
                lease, validator_id, guard=reservation, deadline=125.0
            )
            with self.coordinator.delivery_guard(
                lease, scope, deadline=125.0
            ) as guard:
                guard.begin_enqueue(
                    reservation_guard=reservation, deadline=101.0
                )
                guard.confirm()
                provisional = self.coordinator.publish_delivery(
                    lease, guard=guard, deadline=101.0
                )
                self.assertNotIsInstance(provisional, self.authority.AuthorityStamp)
                with self.assertRaises((self.auth.AuthError, TypeError, ValueError)):
                    self.auth.Delivery(
                        str(uuid.uuid4()), self.ctx,
                        self.auth.OwnedChannel(
                            self.ctx,
                            "123e4567-e89b-42d3-a456-426614174001",
                            "123e4567-e89b-42d3-a456-426614174002", 1,
                        ),
                        provisional,
                    )
                self.denied("authority_stale", lambda: self.coordinator._complete_terminal(
                    lease, guard=guard, publication=object(), deadline=101.0
                ))
                with self.coordinator.delivery_guard(
                    lease_b, scope_b, deadline=125.0
                ) as foreign:
                    self.denied("authority_stale", lambda: self.coordinator._complete_terminal(
                        lease, guard=foreign, publication=provisional, deadline=101.0
                    ))
                self.clock.now = 101.01  # F expired; D=125 has not.
                self.denied("authority_stale", lambda: self.coordinator._complete_terminal(
                    lease, guard=guard, publication=provisional, deadline=101.0
                ))
                self.denied("authority_stale", lambda: self.coordinator.check(
                    lease, scope, deadline=125.0
                ))
        finally:
            self.coordinator.release(lease)
            self.coordinator.release(lease_b)

    def test_poison_vs_enqueue_both_orders_preserve_one_claim(self):
        for order in ("poison_first", "begin_first"):
            with self.subTest(order=order):
                self.fresh_fixture()
                scope = self.authority.AuthScope(reference(), principal())
                lease = self.coordinator.open(scope, deadline=125.0)
                validator_id = str(uuid.uuid4())
                attempt_id = str(uuid.uuid4())
                try:
                    reservation = self.coordinator.claim_reservation(
                        lease, validator_id, attempt_id, deadline=125.0
                    )
                    self.coordinator.mark_reservation_durable(
                        lease, guard=reservation,
                        outcome=self.auth.ReserveOutcome(attempt_id, "reserved"),
                    )
                    self.coordinator.begin_exchange(
                        lease, validator_id, guard=reservation, deadline=125.0
                    )
                    with self.coordinator.delivery_guard(
                        lease, scope, deadline=125.0
                    ) as guard:
                        if order == "poison_first":
                            self.coordinator.poison_intent(scope, "refresh_unknown")
                            claimed_before = self.codes().count("guard.begin.claimed")
                            self.denied("authority_stale", lambda: guard.begin_enqueue(
                                reservation_guard=reservation, deadline=101.0
                            ))
                            self.assertIn("guard.begin.refused", self.codes())
                            self.assertEqual(
                                self.codes().count("guard.begin.claimed"),
                                claimed_before,
                            )
                        else:
                            guard.begin_enqueue(
                                reservation_guard=reservation, deadline=101.0
                            )
                            self.coordinator.poison_intent(scope, "refresh_unknown")
                            guard.confirm()  # The claimed effect may report known outcome.
                            self.denied("authority_stale", lambda: self.coordinator.publish_delivery(
                                lease, guard=guard, deadline=101.0
                            ))
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

    def test_quarantine_deadline_failure_cannot_clear_local_poison(self):
        self.source.finish_failure = "refresh_unknown"
        self.source.finish_hook = lambda: setattr(self.clock, "now", 126.0)
        self.source.quarantine_failure = "refresh_busy"
        self.denied("refresh_unknown", self.admit)
        self.clock.now = 100.0  # Fresh caller budget cannot undo prior poison.
        second = self.auth.AuthStateValidator(
            profile_source=self.source, oauth_client=self.oauth,
            owned_transport=FakeTransport(self.auth, self.events, self.clock),
            coordinator=self.coordinator, clock=self.clock,
            wall_clock=self.wall,
        )
        self.denied(
            "authority_stale", lambda: second.admit(self.ctx, deadline=125.0)
        )
        self.assertEqual(len(self.oauth.requests), 1)
        scope_b = self.authority.AuthScope(reference("beta"), principal())
        lease_b = self.coordinator.open(scope_b, deadline=125.0)
        self.coordinator.check(lease_b, scope_b, deadline=125.0)
        self.coordinator.release(lease_b)

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
        self.assertEqual(
            self.transport.payload_checks,
            [(73, ("accessToken", "chatgptAccountId", "chatgptPlanType"))],
        )
        for capability in (callback, refreshed):
            self.assertNotIn(self.oauth.last_access_token, repr(capability))
            self.assertNotIn(REFRESH_MARKER, repr(capability))
            for token_field in ("access_token", "id_token", "refresh_token", "payload"):
                self.assertFalse(hasattr(capability, token_field))
        self.assertEqual(len(self.oauth.requests), 2)
        self.assertNotEqual(self.oauth.access_tokens[0], self.oauth.access_tokens[1])
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

    def test_callback_invalidation_before_claim_is_local_and_sends_nothing(self):
        initial = self.admit()
        callback = self.validator.capture_callback(
            initial, 82,
            {"reason": "unauthorized", "previousAccountId": WORKSPACE},
            deadline=125.0,
        )
        self.transport.callback_failure = "authority_stale"
        before_reserve = self.codes().count("source.reserve")
        self.denied(
            "authority_stale",
            lambda: self.validator.refresh(initial, callback, deadline=125.0),
        )
        self.assertEqual(self.codes().count("source.reserve"), before_reserve)
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertEqual(self.transport.write_count, 0)
        self.validator.current(initial, self.ctx, deadline=125.0)

    def test_callback_invalidation_after_claim_poisons_before_exchange(self):
        initial = self.admit()
        callback = self.validator.capture_callback(
            initial, 83,
            {"reason": "unauthorized", "previousAccountId": WORKSPACE},
            deadline=125.0,
        )
        self.source.reserve_hook = lambda: setattr(
            self.transport, "callback_failure", "authority_stale"
        )
        self.denied(
            "refresh_unknown",
            lambda: self.validator.refresh(initial, callback, deadline=125.0),
        )
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertEqual(self.transport.write_count, 0)

    def test_callback_invalidation_after_exchange_claim_blocks_later_effects(self):
        initial = self.admit()
        callback = self.validator.capture_callback(
            initial, 86,
            {"reason": "unauthorized", "previousAccountId": WORKSPACE},
            deadline=125.0,
        )
        self.oauth.before_return_hook = lambda: setattr(
            self.transport, "callback_failure", "authority_stale"
        )
        self.denied(
            "refresh_unknown",
            lambda: self.validator.refresh(initial, callback, deadline=125.0),
        )
        self.assertEqual(len(self.oauth.requests), 2)  # Initial + one claimed refresh.
        self.assertEqual(self.transport.write_count, 0)
        self.assertEqual(self.codes().count("source.rotation"), 1)

    def test_second_validator_cannot_capture_existing_channel(self):
        self.admit()
        second = self.auth.AuthStateValidator(
            profile_source=self.source, oauth_client=self.oauth,
            owned_transport=self.transport, coordinator=self.coordinator,
            clock=self.clock, wall_clock=self.wall,
        )
        before_read = self.codes().count("source.read")
        self.denied(
            "owned_host_unproven", lambda: second.admit(self.ctx, deadline=125.0)
        )
        self.assertEqual(self.codes().count("source.read"), before_read)
        self.assertEqual(len(self.oauth.requests), 1)

    def test_stale_channel_generation_refuses_current_and_refresh(self):
        initial = self.admit()
        callback = self.validator.capture_callback(
            initial, 84,
            {"reason": "unauthorized", "previousAccountId": WORKSPACE},
            deadline=125.0,
        )
        self.transport.channel = self.auth.OwnedChannel(
            self.ctx,
            "123e4567-e89b-42d3-a456-426614174001",
            "123e4567-e89b-42d3-a456-426614174002", 2,
        )
        self.denied(
            "authority_stale",
            lambda: self.validator.current(initial, self.ctx, deadline=125.0),
        )
        self.denied(
            "authority_stale",
            lambda: self.validator.refresh(initial, callback, deadline=125.0),
        )
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertEqual(self.transport.write_count, 0)

    def test_deadline_during_terminal_finish_refuses_result(self):
        # F is at most guard entry +1s; outer D=125 remains well in the future.
        self.source.finish_hook = lambda: setattr(self.clock, "now", 101.01)
        self.denied("refresh_unknown", self.admit)
        self.assertLess(self.clock.now, 125.0)
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
            self.assertNotIn(value, repr(self.events))
        self.assertNotIn(ACCESS_MARKER, repr(self.ctx))
        self.assertNotIn(REFRESH_MARKER, repr(self.ctx))
        self.assertFalse(hasattr(self.validator, "supported"))

    def test_finish_callback_cannot_reenter_same_account_while_pending(self):
        observations = []
        scope = self.authority.AuthScope(reference(), principal())

        def during_finish():
            lease = self.last_authority_lease

            def enter_guard():
                with self.coordinator.delivery_guard(
                    lease, scope, deadline=100.25
                ):
                    pass

            for call in (
                lambda: self.coordinator.check(lease, scope, deadline=100.25),
                lambda: self.coordinator.open(scope, deadline=100.25),
                enter_guard,
            ):
                with self.assertRaises(self.authority.AuthError) as raised:
                    call()
                observations.append(raised.exception.code)
            before = len(self.oauth.requests)
            second = self.auth.AuthStateValidator(
                profile_source=self.source, oauth_client=self.oauth,
                owned_transport=FakeTransport(self.auth, self.events, self.clock),
                coordinator=self.coordinator, clock=self.clock,
                wall_clock=self.wall,
            )
            with self.assertRaises(self.auth.AuthError) as raised:
                second.admit(self.ctx, deadline=100.25)
            observations.append(raised.exception.code)
            self.assertEqual(len(self.oauth.requests), before)

        self.source.finish_hook = during_finish
        delivery = self.admit()
        self.assertEqual(observations, ["authority_stale"] * 4)
        self.assertIsInstance(delivery, self.auth.Delivery)

    def test_refresh_finish_callback_denies_same_thread_current(self):
        initial = self.admit()
        callback = self.validator.capture_callback(
            initial, 81,
            {"reason": "unauthorized", "previousAccountId": WORKSPACE},
            deadline=125.0,
        )
        observations = []

        def during_refresh_finish():
            with self.assertRaises(self.auth.AuthError) as raised:
                self.validator.current(initial, self.ctx, deadline=100.25)
            observations.append(raised.exception.code)

        self.source.finish_hook = during_refresh_finish
        self.assertIsInstance(
            self.validator.refresh(initial, callback, deadline=125.0),
            self.auth.Delivery,
        )
        self.assertEqual(observations, ["authority_stale"])

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

    def test_reentrant_close_at_pre_enqueue_write_receipt_and_publication(self):
        for stage in (
            "pre_enqueue", "write", "receipt", "publication_before",
            "publication_after",
        ):
            with self.subTest(stage=stage):
                self.fresh_fixture()
                if stage == "pre_enqueue":
                    self.source.guard_validate_hook = self.validator.close
                elif stage == "write":
                    self.transport.login_write_hook = self.validator.close
                elif stage == "receipt":
                    self.transport.login_receipt_hook = self.validator.close
                elif stage == "publication_before":
                    self.publish_before_hook = self.validator.close
                else:
                    self.publish_after_hook = self.validator.close
                self.denied("refresh_unknown", self.admit)
                self.assertNotIn("coordinator.complete", self.codes())
                self.assertEqual(len(self.oauth.requests), 1)
                self.assertLessEqual(self.codes().count("transport.login"), 1)
                if stage == "pre_enqueue":
                    self.assertNotIn("transport.login", self.codes())
                if stage == "publication_after":
                    self.assertIn("coordinator.publish", self.codes())
                    self.assertNotIn("source.finish", self.codes())

    def test_callback_write_close_does_not_create_second_delivery(self):
        initial = self.admit()
        callback = self.validator.capture_callback(
            initial, 85,
            {"reason": "unauthorized", "previousAccountId": WORKSPACE},
            deadline=125.0,
        )
        self.transport.write_refresh_hook = self.validator.close
        self.denied(
            "refresh_unknown",
            lambda: self.validator.refresh(initial, callback, deadline=125.0),
        )
        self.assertEqual(self.transport.write_count, 1)
        self.assertNotIn("coordinator.complete", self.codes()[self.codes().index("transport.write_refresh") + 1:])

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
            coordinator=self.auth.AuthCoordinator(clock=self.clock),
            clock=self.clock, wall_clock=self.wall,
        )
        self.denied(
            "refresh_unknown", lambda: restarted.admit(self.ctx, deadline=125.0)
        )
        self.assertIn("source.pending_restart", self.codes())
        self.assertEqual(len(self.oauth.requests), first_count)

    def test_finish_to_completion_gap_is_not_a_replayable_delivery(self):
        def fail_after_durable_finish():
            raise self.auth.AuthError("refresh_unknown")

        self.complete_before_hook = fail_after_durable_finish
        self.denied("refresh_unknown", self.admit)
        self.assertEqual(len(self.source.completed_attempts), 1)
        self.assertNotIn("coordinator.complete", self.codes())
        first_count = len(self.oauth.requests)

        def completed_gap_open(ctx, *, deadline):
            self.events.append(("source.completed_gap_restart", deadline))
            raise self.auth.AuthError("refresh_unknown")

        self.source.open_selected = completed_gap_open
        restarted = self.auth.AuthStateValidator(
            profile_source=self.source, oauth_client=self.oauth,
            owned_transport=FakeTransport(self.auth, self.events, self.clock),
            coordinator=self.auth.AuthCoordinator(clock=self.clock),
            clock=self.clock, wall_clock=self.wall,
        )
        self.denied(
            "refresh_unknown", lambda: restarted.admit(self.ctx, deadline=125.0)
        )
        self.assertIn("source.completed_gap_restart", self.codes())
        self.assertEqual(len(self.oauth.requests), first_count)


if __name__ == "__main__":
    unittest.main()
