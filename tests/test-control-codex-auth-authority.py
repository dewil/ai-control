"""Source-blind RED tests for the local auth authority contract."""

import copy
import importlib
import math
import pathlib
import sys
import threading
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "_control_codex_auth_authority.py"


def reference(account="alpha", *, instance="123e4567-e89b-42d3-a456-426614174000"):
    return {
        "schema": 2,
        "provider_id": "codex",
        "account_id": account,
        "profile_instance_id": instance,
        "adapter_revision": "codex-chatgpt-external-auth-host-v2",
        "registration_snapshot": {
            "dev": 1,
            "ino": 2,
            "ctime_ns": 3,
            "sha256": "a" * 64,
        },
    }


def principal(subject="auth0|alice"):
    return {
        "kind": "openid_subject_workspace",
        "issuer": "https://auth.openai.com",
        "subject": subject,
        "workspace_id": "workspace_1",
    }


class MutableClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


class AuthorityContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), f"contract module unavailable: {MODULE.name}")
        sys.path.insert(0, str(MODULE.parent))
        self.addCleanup(lambda: sys.path.remove(str(MODULE.parent)))
        self.auth = importlib.import_module("_control_codex_auth_authority")
        self.clock = MutableClock()
        self.coordinator = self.auth.AuthCoordinator(clock=self.clock)
        self.scope_a = self.auth.AuthScope(reference(), principal())

    def error(self, code, call):
        with self.assertRaises(self.auth.AuthError) as raised:
            call()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(str(raised.exception), code)

    def open_a(self):
        return self.coordinator.open(self.scope_a, deadline=110.0)

    def publish(self, lease, scope=None):
        with self.coordinator.delivery_guard(
            lease, scope or self.scope_a, deadline=110.0
        ) as guard:
            guard.begin_enqueue()
            guard.confirm()
            return self.coordinator.publish_delivery(
                lease, guard=guard, deadline=110.0
            )

    def test_error_codes_are_closed_and_safe(self):
        error = self.auth.AuthError("arbitrary secret text")
        self.assertEqual(error.code, "authority_stale")
        self.assertEqual(str(error), "authority_stale")
        self.assertEqual(str(self.auth.AuthError("refresh_busy")), "refresh_busy")

    def test_scope_exact_schema_and_numeric_validation(self):
        invalid = []
        for key, value in [("schema", True), ("schema", 3), ("provider_id", "other"),
                           ("account_id", "Bad"), ("profile_instance_id", "not-a-uuid")]:
            item = reference()
            item[key] = value
            invalid.append((item, principal()))
        for key, value in [("dev", True), ("ino", 0), ("ctime_ns", -1),
                           ("sha256", "a" * 63)]:
            item = reference()
            item["registration_snapshot"][key] = value
            invalid.append((item, principal()))
        item = reference()
        item["extra"] = 1
        invalid.append((item, principal()))
        item = reference()
        item["registration_snapshot"]["extra"] = 1
        invalid.append((item, principal()))
        for ref, who in invalid:
            with self.subTest(ref=ref):
                self.error("authority_stale", lambda: self.auth.AuthScope(ref, who))

    def test_principal_exact_schema_and_full_identity(self):
        changes = [
            ("kind", "other"), ("issuer", "https://example.test"),
            ("subject", ""), ("subject", "a\n"), ("workspace_id", "bad space"),
        ]
        for key, value in changes:
            who = principal()
            who[key] = value
            with self.subTest(key=key, value=value):
                self.error("authority_stale", lambda: self.auth.AuthScope(reference(), who))
        who = principal()
        who["extra"] = "secret"
        self.error("authority_stale", lambda: self.auth.AuthScope(reference(), who))

    def test_scope_deep_copies_inputs_and_hides_private_values(self):
        ref, who = reference(), principal()
        scope = self.auth.AuthScope(ref, who)
        ref["registration_snapshot"]["sha256"] = "b" * 64
        who["subject"] = "auth0|mallory"
        lease = self.coordinator.open(scope, deadline=110.0)
        try:
            fresh = self.auth.AuthScope(reference(), principal())
            self.coordinator.check(lease, fresh, deadline=110.0)
            self.assertNotIn("auth0|alice", repr(scope))
            self.assertNotIn("workspace_1", repr(scope))
            self.assertNotIn("123e4567", repr(scope))
        finally:
            self.coordinator.release(lease)

    def test_same_account_changed_reference_or_principal_never_rebinds(self):
        lease = self.open_a()
        self.coordinator.release(lease)
        changed_ref = self.auth.AuthScope(
            reference(instance="123e4567-e89b-42d3-a456-426614174001"), principal()
        )
        changed_person = self.auth.AuthScope(reference(), principal("auth0|bob"))
        for scope in (changed_ref, changed_person):
            self.error("authority_stale", lambda: self.coordinator.open(scope, deadline=110.0))
        again = self.open_a()
        self.coordinator.release(again)

    def test_distinct_accounts_and_equal_workspace_are_independent(self):
        scope_b = self.auth.AuthScope(reference("beta"), principal())
        lease_a = self.open_a()
        lease_b = self.coordinator.open(scope_b, deadline=110.0)
        try:
            stamp_a = self.publish(lease_a)
            stamp_b = self.publish(lease_b, scope_b)
            self.assertEqual((stamp_a.owner_generation, stamp_a.credential_generation), (1, 1))
            self.assertEqual((stamp_b.owner_generation, stamp_b.credential_generation), (1, 1))
            self.coordinator.quarantine(lease_a, "refresh_unknown", deadline=110.0)
            self.error("authority_stale", lambda: self.coordinator.check(lease_a, self.scope_a, deadline=110.0))
            self.coordinator.check(lease_b, scope_b, deadline=110.0)
            self.assertEqual(self.publish(lease_b, scope_b).credential_generation, 2)
        finally:
            self.coordinator.release(lease_a)
            self.coordinator.release(lease_b)

    def test_deadlines_reject_nonfinite_bool_and_expiry(self):
        for deadline in (True, False, float("nan"), float("inf"), -math.inf, 100.0, 99.0):
            with self.subTest(deadline=deadline):
                self.error("authority_stale", lambda: self.coordinator.open(self.scope_a, deadline=deadline))

    def test_lease_release_is_idempotent_and_released_check_fails(self):
        lease = self.open_a()
        self.coordinator.release(lease)
        self.coordinator.release(lease)
        self.error("authority_stale", lambda: self.coordinator.check(lease, self.scope_a, deadline=110.0))

    def test_foreign_and_copied_capabilities_cannot_act(self):
        lease = self.open_a()
        other = self.auth.AuthCoordinator(clock=self.clock)
        try:
            self.error("authority_stale", lambda: other.check(lease, self.scope_a, deadline=110.0))
            self.error("authority_stale", lambda: other.release(lease))
            try:
                clone = copy.copy(lease)
            except Exception:
                clone = None
            if clone is not None:
                self.error("authority_stale", lambda: self.coordinator.check(clone, self.scope_a, deadline=110.0))
        finally:
            self.coordinator.release(lease)

    def test_cross_thread_lease_and_guard_use_rejected(self):
        lease = self.open_a()
        results = []
        done = threading.Event()

        def misuse():
            try:
                self.coordinator.check(lease, self.scope_a, deadline=110.0)
            except self.auth.AuthError as exc:
                results.append(exc.code)
            try:
                with self.coordinator.delivery_guard(lease, self.scope_a, deadline=110.0) as guard:
                    guard.begin_enqueue()
            except self.auth.AuthError as exc:
                results.append(exc.code)
            done.set()

        thread = threading.Thread(target=misuse)
        thread.start()
        self.assertTrue(done.wait(2))
        thread.join(2)
        self.assertEqual(results, ["authority_stale", "authority_stale"])
        self.coordinator.release(lease)

    def test_guard_requires_begin_then_confirm_and_single_publication(self):
        lease = self.open_a()
        try:
            with self.coordinator.delivery_guard(lease, self.scope_a, deadline=110.0) as guard:
                self.error("authority_stale", lambda: guard.confirm())
                self.error("authority_stale", lambda: self.coordinator.publish_delivery(lease, guard=guard, deadline=110.0))
                guard.begin_enqueue()
                self.error("authority_stale", lambda: guard.begin_enqueue())
                self.error("authority_stale", lambda: self.coordinator.publish_delivery(lease, guard=guard, deadline=110.0))
                guard.confirm()
                self.error("authority_stale", lambda: guard.confirm())
                first = self.coordinator.publish_delivery(lease, guard=guard, deadline=110.0)
                self.assertEqual((first.owner_generation, first.credential_generation), (1, 1))
                self.error("authority_stale", lambda: self.coordinator.publish_delivery(lease, guard=guard, deadline=110.0))
            self.error("authority_stale", lambda: self.coordinator.publish_delivery(lease, guard=guard, deadline=110.0))
            self.assertEqual(self.publish(lease).credential_generation, 2)
        finally:
            self.coordinator.release(lease)

    def test_foreign_guard_cannot_publish_another_accounts_stamp(self):
        scope_b = self.auth.AuthScope(reference("beta"), principal())
        lease_a = self.open_a()
        lease_b = self.coordinator.open(scope_b, deadline=110.0)
        try:
            with self.coordinator.delivery_guard(lease_a, self.scope_a, deadline=110.0) as guard:
                guard.begin_enqueue()
                guard.confirm()
                self.error("authority_stale", lambda: self.coordinator.publish_delivery(
                    lease_b, guard=guard, deadline=110.0
                ))
                self.assertEqual(self.coordinator.publish_delivery(
                    lease_a, guard=guard, deadline=110.0
                ).credential_generation, 1)
            self.assertEqual(self.publish(lease_b, scope_b).credential_generation, 1)
        finally:
            self.coordinator.release(lease_a)
            self.coordinator.release(lease_b)

    def test_release_inside_guard_refuses_before_unlock(self):
        lease = self.open_a()
        with self.coordinator.delivery_guard(lease, self.scope_a, deadline=110.0) as guard:
            self.error("authority_stale", lambda: self.coordinator.release(lease))
            guard.begin_enqueue()
            guard.confirm()
            self.assertEqual(self.coordinator.publish_delivery(lease, guard=guard, deadline=110.0).credential_generation, 1)
        self.coordinator.release(lease)

    def test_reentrant_quarantine_invalidates_guard_without_stamp(self):
        for stage in ("before_begin", "after_begin", "after_confirm"):
            with self.subTest(stage=stage):
                clock = MutableClock()
                coordinator = self.auth.AuthCoordinator(clock=clock)
                lease = coordinator.open(self.scope_a, deadline=110.0)
                with coordinator.delivery_guard(lease, self.scope_a, deadline=110.0) as guard:
                    if stage != "before_begin":
                        guard.begin_enqueue()
                    if stage == "after_confirm":
                        guard.confirm()
                    coordinator.quarantine(lease, "refresh_unknown", deadline=110.0)
                    self.error("authority_stale", lambda: coordinator.publish_delivery(lease, guard=guard, deadline=110.0))
                    if stage == "before_begin":
                        self.error("authority_stale", lambda: guard.begin_enqueue())
                    elif stage == "after_begin":
                        self.error("authority_stale", lambda: guard.confirm())
                coordinator.release(lease)
                self.error("authority_stale", lambda: coordinator.open(self.scope_a, deadline=110.0))

    def test_invalid_quarantine_code_has_no_effect_and_repeat_is_idempotent(self):
        lease = self.open_a()
        self.error("authority_stale", lambda: self.coordinator.quarantine(lease, "secret", deadline=110.0))
        self.coordinator.check(lease, self.scope_a, deadline=110.0)
        self.coordinator.quarantine(lease, "refresh_unknown", deadline=110.0)
        self.coordinator.quarantine(lease, "auth_expired", deadline=110.0)
        self.coordinator.release(lease)
        self.error("authority_stale", lambda: self.coordinator.open(self.scope_a, deadline=110.0))

    def test_released_lease_may_quarantine_once(self):
        lease = self.open_a()
        self.coordinator.release(lease)
        self.coordinator.quarantine(lease, "refresh_unknown", deadline=110.0)
        self.error("authority_stale", lambda: self.coordinator.open(self.scope_a, deadline=110.0))

    def test_guard_window_expires_without_publication_or_auto_quarantine(self):
        lease = self.open_a()
        with self.coordinator.delivery_guard(lease, self.scope_a, deadline=110.0) as guard:
            guard.begin_enqueue()
            guard.confirm()
            self.clock.value = 101.0
            self.error("authority_stale", lambda: self.coordinator.publish_delivery(lease, guard=guard, deadline=110.0))
        self.coordinator.check(lease, self.scope_a, deadline=110.0)
        self.coordinator.release(lease)

    def test_guard_rejects_expired_deadline_and_changed_scope(self):
        lease = self.open_a()
        changed = self.auth.AuthScope(reference(), principal("auth0|bob"))
        try:
            self.error("authority_stale", lambda: self.coordinator.delivery_guard(
                lease, changed, deadline=110.0
            ).__enter__())
            with self.coordinator.delivery_guard(lease, self.scope_a, deadline=100.25) as guard:
                guard.begin_enqueue()
                guard.confirm()
                self.error("authority_stale", lambda: self.coordinator.publish_delivery(
                    lease, guard=guard, deadline=100.5
                ))
            self.coordinator.check(lease, self.scope_a, deadline=110.0)
        finally:
            self.coordinator.release(lease)

    def test_account_a_held_refresh_lock_does_not_block_b(self):
        coordinator = self.auth.AuthCoordinator()
        scope_a = self.auth.AuthScope(reference(), principal())
        scope_b = self.auth.AuthScope(reference("beta"), principal())
        acquired = threading.Event()
        release_a = threading.Event()
        finished = threading.Event()
        outcomes = []

        def hold_a():
            lease = coordinator.open(scope_a, deadline=time.monotonic() + 2)
            acquired.set()
            try:
                release_a.wait(2)
            finally:
                coordinator.release(lease)

        def use_b():
            lease = coordinator.open(scope_b, deadline=time.monotonic() + 1)
            try:
                coordinator.check(lease, scope_b, deadline=time.monotonic() + 1)
                outcomes.append("B progressed")
            finally:
                coordinator.release(lease)
                finished.set()

        worker_a = threading.Thread(target=hold_a)
        worker_b = threading.Thread(target=use_b)
        worker_a.start()
        self.assertTrue(acquired.wait(2))
        worker_b.start()
        self.assertTrue(finished.wait(1), "B blocked behind A's held refresh lease")
        release_a.set()
        worker_a.join(2)
        worker_b.join(2)
        self.assertEqual(outcomes, ["B progressed"])

    def test_same_account_bounded_refresh_busy(self):
        coordinator = self.auth.AuthCoordinator()
        scope = self.auth.AuthScope(reference(), principal())
        acquired = threading.Event()
        release = threading.Event()

        def hold():
            lease = coordinator.open(scope, deadline=time.monotonic() + 2)
            acquired.set()
            try:
                release.wait(2)
            finally:
                coordinator.release(lease)

        worker = threading.Thread(target=hold)
        worker.start()
        self.assertTrue(acquired.wait(2))
        try:
            self.error("refresh_busy", lambda: coordinator.open(scope, deadline=time.monotonic() + 0.05))
        finally:
            release.set()
            worker.join(2)


if __name__ == "__main__":
    unittest.main()
