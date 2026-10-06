"""Source-blind RED for expiry after final callback authority validation."""

import importlib
import unittest


fixture = importlib.import_module("test_control_web_codex_auth_state_red")


class CallbackFinalizationDeadlineRegressions(unittest.TestCase):
    setUp = fixture.AuthStateContract.setUp
    fresh_fixture = fixture.AuthStateContract.fresh_fixture
    codes = fixture.AuthStateContract.codes
    admit = fixture.AuthStateContract.admit

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
            return error.code

    def test_final_validation_expiry_cannot_accept_or_revive_reader_capability(self):
        delivery = self.admit()  # Admission completes before installing the hook.
        params = {"reason": "unauthorized", "previousAccountId": fixture.WORKSPACE}
        original = self.coordinator._check_stamp
        checks = []
        expired = []

        def expire_after_final_validation(*args, **kwargs):
            result = original(*args, **kwargs)
            checks.append(tuple(self.codes()))
            # An isolated fixture audit observes five checks during capture;
            # the last two follow completed reader capture and validation.
            if len(checks) == 5 and not expired:
                self.assertEqual(self.codes().count("transport.callback.capture"), 1)
                self.assertEqual(self.codes().count("transport.callback.validate"), 1)
                self.assertEqual(self.clock.now, 100.0)
                self.clock.now = 102.0
                expired.append(True)
            return result

        self.coordinator._check_stamp = expire_after_final_validation
        first = self.outcome(lambda: self.validator.capture_callback(
            delivery, 120, params, deadline=101.0,
        ))
        self.assertEqual(expired, [True])
        self.assertEqual(len(checks), 5)
        retained = self.transport.callbacks[(id(self.transport.channel), 120)]
        before = self.effect_counts()
        self.assertEqual(before, (1, 1, 1, 0))

        # A later caller's budget must never accept this expired identity or
        # authorize the alias that the injected reader retained.
        duplicate = self.outcome(lambda: self.validator.capture_callback(
            delivery, 120, params, deadline=125.0,
        ))
        refreshed = self.outcome(lambda: self.validator.refresh(
            delivery, retained, deadline=125.0,
        ))
        for operation, result in (
            ("original capture", first), ("later duplicate", duplicate),
            ("reader-retained refresh", refreshed),
        ):
            with self.subTest(operation=operation):
                self.assertIn(
                    result, ("refresh_busy", "authority_stale"),
                    "expired capture identity must remain permanently non-accepted",
                )
        self.assertEqual(self.effect_counts(), before)


if __name__ == "__main__":
    unittest.main()
