"""Source-blind RED for callback close and exhausted finalization budgets."""

import importlib
import unittest


fixture = importlib.import_module("test_control_web_codex_auth_state_red")


class CallbackCloseDeadlineRegressions(unittest.TestCase):
    setUp = fixture.AuthStateContract.setUp
    fresh_fixture = fixture.AuthStateContract.fresh_fixture
    codes = fixture.AuthStateContract.codes
    admit = fixture.AuthStateContract.admit

    def params(self):
        return {"reason": "unauthorized", "previousAccountId": fixture.WORKSPACE}

    def effect_counts(self):
        return (
            self.codes().count("transport.callback.capture"),
            self.codes().count("source.reserve"), len(self.oauth.requests),
            self.transport.write_count,
        )

    def outcome(self, call):
        try:
            return call()
        except self.auth.AuthError as error:
            return error

    def assert_replays_closed_without_effects(self, delivery, request_id):
        retained = self.transport.callbacks[(id(self.transport.channel), request_id)]
        before = self.effect_counts()
        for operation, call in (
            ("duplicate", lambda: self.validator.capture_callback(
                delivery, request_id, self.params(), deadline=125.0,
            )),
            ("reader-retained refresh", lambda: self.validator.refresh(
                delivery, retained, deadline=125.0,
            )),
        ):
            with self.subTest(operation=operation):
                self.assertIsInstance(self.outcome(call), self.auth.AuthError)
                self.assertEqual(self.effect_counts(), before)

    def test_close_from_finalization_clock_prevents_callback_acceptance(self):
        delivery = self.admit()
        original_check = self.coordinator._check_stamp
        original_clock = self.validator._clock
        checks = []
        closed = []

        def close_once_then_sample():
            if not closed:
                closed.append(True)
                self.validator.close()
            return original_clock()

        def arm_close_after_final_check(*args, **kwargs):
            result = original_check(*args, **kwargs)
            checks.append(True)
            # The isolated reader audit observes five successful capture checks;
            # the fifth follows reader validation and precedes finalization.
            if len(checks) == 5:
                self.assertEqual(self.codes().count("transport.callback.validate"), 1)
                self.validator._clock = close_once_then_sample
            return result

        self.coordinator._check_stamp = arm_close_after_final_check
        first = self.outcome(lambda: self.validator.capture_callback(
            delivery, 121, self.params(), deadline=101.0,
        ))
        self.assertEqual(closed, [True])
        self.assertEqual(self.clock.now, 100.0)
        self.assertEqual(self.effect_counts(), (1, 1, 1, 0))
        with self.subTest(operation="original capture after close"):
            self.assertIsInstance(first, self.auth.AuthError)
        self.assert_replays_closed_without_effects(delivery, 121)
        before = self.effect_counts()
        self.validator.close()
        self.validator.close()
        self.assertEqual(self.effect_counts(), before)
        self.assertEqual(closed, [True])

    def test_expired_worker_stops_before_additional_final_validation(self):
        delivery = self.admit()
        original_check = self.coordinator._check_stamp
        checks = []
        expired = []

        def expire_after_reader_check(*args, **kwargs):
            result = original_check(*args, **kwargs)
            checks.append(True)
            # In the same audit, check four is the first post-reader check.
            if len(checks) == 4 and not expired:
                self.assertEqual(self.codes().count("transport.callback.validate"), 1)
                self.assertEqual(self.clock.now, 100.0)
                self.clock.now = 102.0
                expired.append(True)
            return result

        self.coordinator._check_stamp = expire_after_reader_check
        first = self.outcome(lambda: self.validator.capture_callback(
            delivery, 122, self.params(), deadline=101.0,
        ))
        self.assertEqual(expired, [True])
        self.assertIsInstance(first, self.auth.AuthError)
        self.assertEqual(first.code, "refresh_busy")
        self.assertEqual(self.effect_counts(), (1, 1, 1, 0))
        with self.subTest(operation="no final validation after expiry"):
            self.assertEqual(len(checks), 4)
        self.assert_replays_closed_without_effects(delivery, 122)


if __name__ == "__main__":
    unittest.main()
