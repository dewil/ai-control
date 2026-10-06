"""Synthetic regression RED for claimed auth-state authority boundaries.

The existing contract fixture supplies only in-memory source, OAuth, and transport
fakes. This module composes its fixture without re-running its contract tests.
"""

import importlib
from dataclasses import replace
from types import MappingProxyType
import unittest
from unittest import mock


fixture = importlib.import_module("test_control_web_codex_auth_state_red")


class AuthStateSourceRegressions(unittest.TestCase):
    setUp = fixture.AuthStateContract.setUp
    fresh_fixture = fixture.AuthStateContract.fresh_fixture
    codes = fixture.AuthStateContract.codes
    denied = fixture.AuthStateContract.denied
    admit = fixture.AuthStateContract.admit

    def assert_claimed_unknown_and_blocked(self):
        self.assertEqual(self.codes().count("coordinator.claim"), 1)
        self.assertEqual(self.codes().count("source.reserve"), 1)
        self.assertNotIn("coordinator.abandon", self.codes())
        self.assertIn("source.quarantine", self.codes())
        before = list(self.events)
        other = self.auth.AuthStateValidator(
            profile_source=self.source, oauth_client=self.oauth,
            owned_transport=fixture.FakeTransport(self.auth, self.events, self.clock),
            coordinator=self.coordinator, clock=self.clock, wall_clock=self.wall,
        )
        self.denied("authority_stale", lambda: other.admit(self.ctx, deadline=125.0))
        self.assertEqual(self.events, before)
        self.assertEqual(self.codes().count("source.reserve"), 1)
        self.assertEqual(len(self.oauth.requests), 1)

    def test_oauth_exception_without_typed_tls_result_is_unknown(self):
        for code in (
            "auth_expired", "auth_unavailable", "auth_response_invalid",
            "identity_mismatch", "refresh_busy",
        ):
            with self.subTest(code=code):
                self.fresh_fixture()

                def no_typed_result(request, refresh_token, *, deadline):
                    self.oauth.requests.append(request)
                    self.events.append(("oauth.exchange", request.attempt_id))
                    try:
                        raise ValueError("invented-private-exception-marker")
                    except ValueError:
                        raise self.auth.AuthError(code)

                self.oauth.exchange = no_typed_result
                with self.assertRaises(self.auth.AuthError) as raised:
                    self.admit()
                self.assertEqual(raised.exception.code, "refresh_unknown")
                self.assertEqual(str(raised.exception), "refresh_unknown")
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)
                self.assertNotIn("invented-private-exception-marker", repr(raised.exception))
                self.assertNotIn("invented-private-exception-marker", str(raised.exception))
                self.assertNotIn("source.rotation", self.codes())
                self.assertNotIn("transport.login", self.codes())
                self.assert_claimed_unknown_and_blocked()

    def test_source_current_close_after_exchange_blocks_rotation(self):
        for boundary in ("source", "transport"):
            with self.subTest(boundary=boundary):
                self.fresh_fixture()
                dependency = self.source if boundary == "source" else self.transport
                original = dependency.validate_current
                closed = []

                def close_after_validation(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if self.oauth.requests and not closed:
                        closed.append(True)
                        self.validator.close()
                    return result

                dependency.validate_current = close_after_validation
                self.denied("refresh_unknown", self.admit)
                self.assertEqual(closed, [True])
                self.assertEqual(len(self.oauth.requests), 1)
                self.assertNotIn("source.rotation", self.codes())
                self.assertNotIn("transport.login", self.codes())
                self.assert_claimed_unknown_and_blocked()

    def test_guard_validation_close_after_publication_blocks_finish(self):
        for boundary in ("source.guard", "transport.guard"):
            with self.subTest(boundary=boundary):
                self.fresh_fixture()
                original = fixture.FakeGuard.validate_current
                closed = []

                def close_after_published(guard, *, deadline):
                    result = original(guard, deadline=deadline)
                    if (guard.label == boundary
                            and "coordinator.publish" in self.codes() and not closed):
                        closed.append(True)
                        self.validator.close()
                    return result

                with mock.patch.object(
                    fixture.FakeGuard, "validate_current", close_after_published
                ):
                    self.denied("refresh_unknown", self.admit)
                self.assertEqual(closed, [True])
                self.assertIn("coordinator.publish", self.codes())
                self.assertNotIn("source.finish", self.codes())
                self.assertNotIn("coordinator.complete", self.codes())
                self.assert_claimed_unknown_and_blocked()

    def test_malformed_negative_tls_envelope_is_not_definitive_rejection(self):
        malformed = (
            ("body_type", {"body": "not response bytes"}),
            ("body_cap", {"body": b"x" * 65537}),
            ("wall_nonfinite", {"received_wall": float("nan")}),
            ("wall_negative", {"received_wall": -1.0}),
            ("wall_after_evaluation", {"received_wall": 2000.0}),
        )
        for status in (400, 401):
            for label, changes in malformed:
                with self.subTest(status=status, malformed=label):
                    self.fresh_fixture()
                    original = self.oauth.exchange

                    def malformed_envelope(*args, **kwargs):
                        response = original(*args, **kwargs)
                        return replace(response, status=status, **changes)

                    self.oauth.exchange = malformed_envelope
                    with self.assertRaises(self.auth.AuthError) as raised:
                        self.admit()
                    self.assertEqual(raised.exception.code, "refresh_unknown")
                    self.assertEqual(len(self.oauth.requests), 1)
                    self.assertNotIn("source.rotation", self.codes())
                    self.assertNotIn("transport.login", self.codes())
                    self.assert_claimed_unknown_and_blocked()

    def test_bounded_non_200_tls_status_is_still_unknown(self):
        for status, body in (
            (400, b'{"error":"invalid_grant"}'),
            (401, b'{"error":"invalid_grant"}'),
            (429, b'{}'),
            (500, b'{}'),
        ):
            with self.subTest(status=status):
                self.fresh_fixture()
                original = self.oauth.exchange

                def negative_envelope(*args, **kwargs):
                    return replace(original(*args, **kwargs), status=status, body=body)

                self.oauth.exchange = negative_envelope
                with self.assertRaises(self.auth.AuthError) as raised:
                    self.admit()
                self.assertEqual(raised.exception.code, "refresh_unknown")
                self.assertEqual(len(self.oauth.requests), 1)
                self.assertNotIn("source.rotation", self.codes())
                self.assertNotIn("transport.login", self.codes())
                self.assert_claimed_unknown_and_blocked()

    def test_mutated_request_deadline_cannot_renew_six_second_exchange(self):
        original = self.oauth.exchange
        original_budget = []

        def renew_public_request_alias(request, refresh_token, *, deadline):
            original_budget.append((deadline, request.deadline))
            object.__setattr__(request, "deadline", 125.0)
            self.clock.now = 107.0
            return original(request, refresh_token, deadline=deadline)

        self.oauth.exchange = renew_public_request_alias
        self.denied("refresh_unknown", self.admit)
        self.assertEqual(original_budget, [(106.0, 106.0)])
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertNotIn("source.rotation", self.codes())
        self.assertNotIn("transport.login", self.codes())
        self.assert_claimed_unknown_and_blocked()

    def test_close_inside_entered_rotation_allows_only_that_commit(self):
        original = self.source.commit_rotation
        entered = []

        def entered_rotation(*args, **kwargs):
            entered.append(True)
            self.validator.close()
            return original(*args, **kwargs)

        self.source.commit_rotation = entered_rotation
        self.denied("refresh_unknown", self.admit)
        self.assertEqual(entered, [True])
        self.assertEqual(self.codes().count("source.rotation"), 1)
        self.assertNotIn("transport.login", self.codes())
        self.assertNotIn("source.finish", self.codes())
        self.assert_claimed_unknown_and_blocked()

    def test_close_inside_entered_finish_allows_finish_without_delivery(self):
        original = self.source.finish_confirmed
        entered = []

        def entered_finish(*args, **kwargs):
            entered.append(True)
            self.validator.close()
            return original(*args, **kwargs)

        self.source.finish_confirmed = entered_finish
        self.denied("refresh_unknown", self.admit)
        self.assertEqual(entered, [True])
        self.assertEqual(self.codes().count("source.finish"), 1)
        self.assertNotIn("coordinator.complete", self.codes())
        self.assert_claimed_unknown_and_blocked()

    def test_mutated_valid_execution_identity_invalidates_current_before_io(self):
        delivery = self.admit()
        before = list(self.events)
        object.__setattr__(self.ctx, "execution_identity", MappingProxyType({
            "kind": "interactive_session",
            "id": "123e4567-e89b-42d3-a456-426614174005",
        }))
        self.denied(
            "authority_stale",
            lambda: self.validator.current(delivery, self.ctx, deadline=125.0),
        )
        self.assertEqual(self.events, before)

    def test_execution_identity_change_during_oauth_blocks_rotation(self):
        changed = []

        def change_context():
            object.__setattr__(self.ctx, "execution_identity", MappingProxyType({
                "kind": "task", "id": "123e4567-e89b-42d3-a456-426614174006",
            }))
            changed.append(True)

        self.oauth.before_return_hook = change_context
        with self.assertRaises(self.auth.AuthError) as raised:
            self.admit()
        self.assertIn(raised.exception.code, ("authority_stale", "refresh_unknown"))
        self.assertEqual(changed, [True])
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertNotIn("source.rotation", self.codes())
        self.assertNotIn("transport.login", self.codes())

    def test_mutated_owned_channel_generation_invalidates_current_before_io(self):
        delivery = self.admit()
        before = list(self.events)
        object.__setattr__(delivery.channel, "transport_generation", 2)
        self.denied(
            "authority_stale",
            lambda: self.validator.current(delivery, self.ctx, deadline=125.0),
        )
        self.assertEqual(self.events, before)

    def test_channel_generation_change_during_oauth_blocks_rotation(self):
        changed = []

        def change_channel():
            object.__setattr__(self.transport.channel, "transport_generation", 2)
            changed.append(True)

        self.oauth.before_return_hook = change_channel
        with self.assertRaises(self.auth.AuthError) as raised:
            self.admit()
        self.assertIn(raised.exception.code, ("authority_stale", "refresh_unknown"))
        self.assertEqual(changed, [True])
        self.assertEqual(len(self.oauth.requests), 1)
        self.assertNotIn("source.rotation", self.codes())
        self.assertNotIn("transport.login", self.codes())

    def test_mutated_callback_time_cannot_renew_original_nine_second_budget(self):
        delivery = self.admit()
        callback = self.validator.capture_callback(
            delivery, 87,
            {"reason": "unauthorized", "previousAccountId": fixture.WORKSPACE},
            deadline=125.0,
        )
        before = list(self.events)
        before_requests = len(self.oauth.requests)
        object.__setattr__(callback, "received_monotonic", 110.0)
        self.clock.now = 110.0  # The captured receipt was at 100, so its F is 109.
        self.denied(
            "authority_stale",
            lambda: self.validator.refresh(delivery, callback, deadline=125.0),
        )
        self.assertEqual(self.events, before)
        self.assertEqual(len(self.oauth.requests), before_requests)
        self.assertEqual(self.transport.write_count, 0)

    def test_mutated_callback_request_id_or_params_refused_before_effects(self):
        for field, value in (
            ("request_id", 88),
            ("params", MappingProxyType({
                "reason": "unauthorized", "previousAccountId": None,
            })),
        ):
            with self.subTest(field=field):
                self.fresh_fixture()
                delivery = self.admit()
                callback = self.validator.capture_callback(
                    delivery, 87,
                    {"reason": "unauthorized", "previousAccountId": fixture.WORKSPACE},
                    deadline=125.0,
                )
                before = list(self.events)
                before_requests = len(self.oauth.requests)
                object.__setattr__(callback, field, value)
                with self.assertRaises(self.auth.AuthError):
                    self.validator.refresh(delivery, callback, deadline=125.0)
                self.assertEqual(self.events, before)
                self.assertEqual(len(self.oauth.requests), before_requests)
                self.assertEqual(self.transport.write_count, 0)

    def test_delivery_cannot_borrow_another_real_stamps_authority(self):
        prior = self.admit()
        later = self.admit()
        self.assertIsNot(prior.stamp, later.stamp)
        before = list(self.events)
        object.__setattr__(later, "stamp", prior.stamp)
        self.denied(
            "authority_stale",
            lambda: self.validator.current(later, self.ctx, deadline=125.0),
        )
        self.assertEqual(self.events, before)


if __name__ == "__main__":
    unittest.main()
