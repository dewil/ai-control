"""Synthetic RED for closed callback-capture replay on one owned channel."""

import importlib
import unittest


fixture = importlib.import_module("test_control_web_codex_auth_state_red")


class CallbackCaptureRegressions(unittest.TestCase):
    setUp = fixture.AuthStateContract.setUp
    fresh_fixture = fixture.AuthStateContract.fresh_fixture
    codes = fixture.AuthStateContract.codes
    denied = fixture.AuthStateContract.denied
    admit = fixture.AuthStateContract.admit

    def params(self):
        return {"reason": "unauthorized", "previousAccountId": fixture.WORKSPACE}

    def assert_no_new_effects(self, before):
        self.assertEqual(self.codes().count("source.reserve"), before[0])
        self.assertEqual(len(self.oauth.requests), before[1])
        self.assertEqual(self.transport.write_count, before[2])
        self.assertEqual(self.codes().count("transport.callback.capture"), before[3])

    def effect_counts(self):
        return (
            self.codes().count("source.reserve"), len(self.oauth.requests),
            self.transport.write_count,
            self.codes().count("transport.callback.capture"),
        )

    def rejected_capture(self, mode, delivery, request_id):
        if mode == "future_receipt":
            original = self.transport.capture_callback

            def future_receipt(*args, **kwargs):
                callback = original(*args, **kwargs)
                object.__setattr__(callback, "received_monotonic", 110.0)
                return callback

            self.transport.capture_callback = future_receipt
        else:
            self.transport.callback_failure = "authority_stale"

        self.denied(
            "authority_stale",
            lambda: self.validator.capture_callback(
                delivery, request_id, self.params(), deadline=125.0,
            ),
        )
        captured = self.transport.callbacks[(id(self.transport.channel), request_id)]
        self.assertEqual(self.codes().count("transport.callback.capture"), 1)
        self.assertEqual(self.transport.write_count, 0)
        if mode == "future_receipt":
            self.clock.now = 111.0
        else:
            self.transport.callback_failure = None
        return captured

    def test_future_reader_receipt_failure_cannot_be_reactivated_by_duplicate(self):
        delivery = self.admit()
        self.rejected_capture("future_receipt", delivery, 91)
        before = self.effect_counts()
        self.denied(
            "authority_stale",
            lambda: self.validator.capture_callback(
                delivery, 91, self.params(), deadline=125.0,
            ),
        )
        self.assert_no_new_effects(before)

    def test_transport_validation_failure_cannot_be_reactivated_by_duplicate(self):
        delivery = self.admit()
        self.rejected_capture("transport_failure", delivery, 92)
        before = self.effect_counts()
        self.denied(
            "authority_stale",
            lambda: self.validator.capture_callback(
                delivery, 92, self.params(), deadline=125.0,
            ),
        )
        self.assert_no_new_effects(before)

    def test_retained_fake_capability_from_rejected_capture_cannot_refresh(self):
        for mode, request_id in (("future_receipt", 93), ("transport_failure", 94)):
            with self.subTest(mode=mode):
                self.fresh_fixture()
                delivery = self.admit()
                rejected = self.rejected_capture(mode, delivery, request_id)
                before = self.effect_counts()
                self.denied(
                    "authority_stale",
                    lambda: self.validator.refresh(delivery, rejected, deadline=125.0),
                )
                self.assert_no_new_effects(before)

    def test_successful_duplicate_capture_remains_same_capability(self):
        delivery = self.admit()
        first = self.validator.capture_callback(
            delivery, 95, self.params(), deadline=125.0,
        )
        before = self.effect_counts()
        duplicate = self.validator.capture_callback(
            delivery, 95, self.params(), deadline=125.0,
        )
        self.assertIs(duplicate, first)
        self.assert_no_new_effects(before)


if __name__ == "__main__":
    unittest.main()
