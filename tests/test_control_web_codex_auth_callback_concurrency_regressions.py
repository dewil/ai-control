"""Synthetic RED for callback-map selection and caller-budget concurrency."""

import importlib
import threading
import time
import unittest
from unittest import mock


fixture = importlib.import_module("test_control_web_codex_auth_state_red")


class HookClock(fixture.Clock):
    def __init__(self):
        super().__init__()
        self.hook = None

    def __call__(self):
        hook, self.hook = self.hook, None
        if hook is not None:
            hook()
        return super().__call__()


class LiveClock(fixture.Clock):
    def __init__(self):
        self.now = time.monotonic()

    def __call__(self):
        self.now = time.monotonic()
        return self.now


class CallbackConcurrencyRegressions(unittest.TestCase):
    setUp = fixture.AuthStateContract.setUp
    fresh_fixture = fixture.AuthStateContract.fresh_fixture
    codes = fixture.AuthStateContract.codes
    denied = fixture.AuthStateContract.denied
    admit = fixture.AuthStateContract.admit

    def params(self):
        return {"reason": "unauthorized", "previousAccountId": fixture.WORKSPACE}

    def install_distinct_reader(self):
        issued = []

        def capture(channel, request_id, params, *, deadline):
            callback = self.auth.CapturedCallback(
                channel, request_id, params, self.clock.now,
            )
            issued.append(callback)
            self.transport.callback_ids[id(callback)] = request_id
            self.events.append(("transport.callback.capture", request_id))
            return callback

        def validate(callback, channel, *, deadline):
            if not any(item is callback for item in issued) or callback.channel is not channel:
                raise self.auth.AuthError("authority_stale")
            self.events.append(("transport.callback.validate", callback.request_id))

        self.transport.capture_callback = capture
        self.transport.validate_callback = validate
        return issued

    def assert_one_refresh_and_replay(self, initial, callback):
        before_exchange = len(self.oauth.requests)
        before_write = self.transport.write_count
        refreshed = self.validator.refresh(initial, callback, deadline=125.0)
        self.assertIsInstance(refreshed, self.auth.Delivery)
        self.assertIs(
            self.validator.refresh(initial, callback, deadline=125.0), refreshed,
        )
        self.assertEqual(len(self.oauth.requests), before_exchange + 1)
        self.assertEqual(self.transport.write_count, before_write + 1)

    def test_clock_reentry_before_reader_selects_existing_capability_once(self):
        for reader in ("cached", "distinct"):
            with self.subTest(reader=reader):
                with mock.patch.object(fixture, "Clock", HookClock):
                    self.fresh_fixture()
                initial = self.admit()
                issued = self.install_distinct_reader() if reader == "distinct" else None
                nested = []

                def reenter():
                    try:
                        nested.append(self.validator.capture_callback(
                            initial, 106, self.params(), deadline=125.0,
                        ))
                    except self.auth.AuthError as error:
                        nested.append(error.code)

                self.clock.hook = reenter
                try:
                    outer = self.validator.capture_callback(
                        initial, 106, self.params(), deadline=125.0,
                    )
                except self.auth.AuthError as error:
                    outer = error.code
                self.assertEqual(len(nested), 1)
                self.assertIsInstance(outer, self.auth.CapturedCallback)
                if nested[0] != "refresh_busy":
                    self.assertIsInstance(nested[0], self.auth.CapturedCallback)
                    self.assertIs(outer, nested[0])
                self.assertEqual(self.codes().count("transport.callback.capture"), 1)
                if issued is not None:
                    self.assertEqual(len(issued), 1)
                self.assertIs(
                    self.validator.capture_callback(
                        initial, 106, self.params(), deadline=125.0,
                    ), outer,
                )
                self.assertEqual(self.codes().count("transport.callback.capture"), 1)
                self.assert_one_refresh_and_replay(initial, outer)

    def test_clock_reentry_after_reader_sees_pending_without_poisoning_owner(self):
        for reader in ("cached", "distinct"):
            with self.subTest(reader=reader):
                with mock.patch.object(fixture, "Clock", HookClock):
                    self.fresh_fixture()
                initial = self.admit()
                issued = self.install_distinct_reader() if reader == "distinct" else None
                original = self.transport.capture_callback
                nested = []

                def arm_after_reader(*args, **kwargs):
                    callback = original(*args, **kwargs)

                    def reenter():
                        try:
                            nested.append(self.validator.capture_callback(
                                initial, 107, self.params(), deadline=125.0,
                            ))
                        except self.auth.AuthError as error:
                            nested.append(error.code)

                    self.clock.hook = reenter
                    return callback

                self.transport.capture_callback = arm_after_reader
                try:
                    outer = self.validator.capture_callback(
                        initial, 107, self.params(), deadline=125.0,
                    )
                except self.auth.AuthError as error:
                    outer = error.code
                self.assertEqual(nested, ["refresh_busy"])
                self.assertIsInstance(outer, self.auth.CapturedCallback)
                self.assertEqual(self.codes().count("transport.callback.capture"), 1)
                if issued is not None:
                    self.assertEqual(len(issued), 1)
                self.assertIs(
                    self.validator.capture_callback(
                        initial, 107, self.params(), deadline=125.0,
                    ), outer,
                )
                self.assertEqual(self.codes().count("transport.callback.capture"), 1)
                self.assert_one_refresh_and_replay(initial, outer)

    def live_fixture(self):
        with mock.patch.object(fixture, "Clock", LiveClock):
            self.fresh_fixture()
        return self.validator.admit(self.ctx, deadline=self.clock() + 2.0)

    def test_expired_original_finalization_never_promotes_retained_reader_cap(self):
        initial = self.admit()
        original = self.transport.validate_callback
        reached = []

        def expire_after_reader_validation(callback, channel, *, deadline):
            result = original(callback, channel, deadline=deadline)
            reached.append(True)
            self.clock.now = 102.0
            return result

        self.transport.validate_callback = expire_after_reader_validation
        first = None
        try:
            self.validator.capture_callback(
                initial, 111, self.params(), deadline=101.0,
            )
        except self.auth.AuthError as error:
            first = error.code
        self.assertEqual(reached, [True])
        self.assertIn(first, ("refresh_busy", "authority_stale"))
        retained = self.transport.callbacks[(id(self.transport.channel), 111)]
        before = (
            self.codes().count("transport.callback.capture"),
            self.codes().count("source.reserve"), len(self.oauth.requests),
            self.transport.write_count,
        )
        self.denied(
            "refresh_busy",
            lambda: self.validator.capture_callback(
                initial, 111, self.params(), deadline=125.0,
            ),
        )
        with self.assertRaises(self.auth.AuthError):
            self.validator.refresh(initial, retained, deadline=125.0)
        self.assertEqual((
            self.codes().count("transport.callback.capture"),
            self.codes().count("source.reserve"), len(self.oauth.requests),
            self.transport.write_count,
        ), before)

    def start_held_capture(self, initial, request_id):
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        outcome = []
        original = self.transport.capture_callback

        def held_reader(channel, requested_id, params, *, deadline):
            if requested_id == request_id:
                entered.set()
                release.wait(1.5)
            return original(channel, requested_id, params, deadline=deadline)

        self.transport.capture_callback = held_reader

        def capture():
            try:
                outcome.append(self.validator.capture_callback(
                    initial, request_id, self.params(), deadline=self.clock() + 2.0,
                ))
            except Exception as error:
                outcome.append(error)
            finally:
                finished.set()

        worker = threading.Thread(target=capture, daemon=True)
        worker.start()
        return entered, release, finished, outcome, worker

    def test_same_key_waiting_capture_exhausts_own_budget_before_reader_release(self):
        initial = self.live_fixture()
        entered, release, finished_a, outcome_a, worker_a = self.start_held_capture(
            initial, 108,
        )
        finished_b = threading.Event()
        outcome_b = []
        worker_b = None
        try:
            self.assertTrue(entered.wait(0.5), "held reader was not entered")
            before = (
                self.codes().count("transport.callback.capture"),
                self.codes().count("source.reserve"), len(self.oauth.requests),
                self.transport.write_count,
            )

            def duplicate():
                try:
                    outcome_b.append(self.validator.capture_callback(
                        initial, 108, self.params(), deadline=self.clock() + 0.1,
                    ))
                except self.auth.AuthError as error:
                    outcome_b.append(error.code)
                except Exception as error:
                    outcome_b.append(error)
                finally:
                    finished_b.set()

            worker_b = threading.Thread(target=duplicate, daemon=True)
            worker_b.start()
            self.assertTrue(finished_b.wait(0.5), "duplicate waited past caller budget")
            self.assertFalse(release.is_set())
            self.assertEqual(outcome_b, ["refresh_busy"])
            self.assertEqual((
                self.codes().count("transport.callback.capture"),
                self.codes().count("source.reserve"), len(self.oauth.requests),
                self.transport.write_count,
            ), before)
        finally:
            release.set()
            worker_a.join(2.0)
            if worker_b is not None:
                worker_b.join(2.0)
        self.assertFalse(worker_a.is_alive())
        self.assertTrue(finished_a.is_set())
        self.assertEqual(len(outcome_a), 1)
        self.assertIsInstance(outcome_a[0], self.auth.CapturedCallback)

    def test_existing_other_callback_refresh_completes_before_reader_release(self):
        initial = self.live_fixture()
        existing = self.validator.capture_callback(
            initial, 109, self.params(), deadline=self.clock() + 2.0,
        )
        entered, release, finished_a, outcome_a, worker_a = self.start_held_capture(
            initial, 110,
        )
        finished_b = threading.Event()
        outcome_b = []
        worker_b = None
        try:
            self.assertTrue(entered.wait(0.5), "held reader was not entered")
            before = (
                self.codes().count("source.reserve"), len(self.oauth.requests),
                self.transport.write_count,
            )

            def refresh_existing():
                try:
                    outcome_b.append(self.validator.refresh(
                        initial, existing, deadline=self.clock() + 0.1,
                    ))
                except self.auth.AuthError as error:
                    outcome_b.append(error.code)
                except Exception as error:
                    outcome_b.append(error)
                finally:
                    finished_b.set()

            worker_b = threading.Thread(target=refresh_existing, daemon=True)
            worker_b.start()
            self.assertTrue(finished_b.wait(0.5), "refresh waited behind other reader")
            self.assertFalse(release.is_set())
            self.assertEqual(len(outcome_b), 1)
            after = (
                self.codes().count("source.reserve"), len(self.oauth.requests),
                self.transport.write_count,
            )
            if outcome_b[0] == "refresh_busy":
                self.assertEqual(after, before)
            else:
                self.assertIsInstance(outcome_b[0], self.auth.Delivery)
                self.assertEqual(after, tuple(value + 1 for value in before))
        finally:
            release.set()
            worker_a.join(2.0)
            if worker_b is not None:
                worker_b.join(2.0)
        self.assertFalse(worker_a.is_alive())
        self.assertTrue(finished_a.is_set())
        self.assertEqual(len(outcome_a), 1)
        self.assertIsInstance(outcome_a[0], self.auth.CapturedCallback)


if __name__ == "__main__":
    unittest.main()
