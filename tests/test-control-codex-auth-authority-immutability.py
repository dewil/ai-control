"""Blind fault RED for immutable local authority capture and safe validation."""

import importlib
import pathlib
import sys
import types
import unittest
from collections.abc import Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "_control_codex_auth_authority.py"


def reference():
    return {
        "schema": 2,
        "provider_id": "codex",
        "account_id": "alpha",
        "profile_instance_id": "123e4567-e89b-42d3-a456-426614174000",
        "adapter_revision": "codex-chatgpt-external-auth-host-v2",
        "registration_snapshot": {
            "dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "a" * 64,
        },
    }


def principal(subject="auth0|alice"):
    return {
        "kind": "openid_subject_workspace",
        "issuer": "https://auth.openai.com",
        "subject": subject,
        "workspace_id": "workspace_1",
    }


class TriggerClock:
    def __init__(self):
        self.action = None
        self.triggered = False

    def __call__(self):
        action = self.action
        if action is not None:
            self.action = None  # quarantine also samples this clock
            self.triggered = True
            action()
        return 100.0


class HostileValue:
    def __eq__(self, other):
        raise RuntimeError("fixture-marker")


class HostileKey:
    def __hash__(self):
        return hash("provider_id")

    def __eq__(self, other):
        raise RuntimeError("fixture-marker")


class HostileReference(Mapping):
    def __init__(self):
        self.data = reference()
        self.hostile_key = HostileKey()

    def __iter__(self):
        yield from self.data
        yield self.hostile_key

    def __len__(self):
        return len(self.data) + 1

    def __getitem__(self, key):
        if key is self.hostile_key:
            return "extra"
        return self.data[key]


class FaultRed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert MODULE.is_file(), f"frozen module unavailable: {MODULE.name}"
        sys.path.insert(0, str(MODULE.parent))
        cls.auth = importlib.import_module("_control_codex_auth_authority")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(MODULE.parent))

    def assert_stale(self, call):
        try:
            result = call()
        except Exception as exc:
            self.assertIsInstance(exc, self.auth.AuthError)
            self.assertEqual(exc.code, "authority_stale")
            self.assertEqual(str(exc), "authority_stale")
            self.assertNotIn("fixture-marker", repr(exc))
        else:
            self.fail(f"authority action unexpectedly succeeded: {type(result).__name__}")

    def mutated_dict_scope(self):
        clock = TriggerClock()
        coordinator = self.auth.AuthCoordinator(clock=clock)
        scope = self.auth.AuthScope(reference(), principal())
        lease = coordinator.open(scope, deadline=110.0)
        attrs = getattr(scope, "__dict__", None)
        if attrs is None or "_principal" not in attrs:
            coordinator.release(lease)
            self.skipTest("scope has no ordinary _principal dictionary alias")
        attrs["_principal"] = types.MappingProxyType(principal("auth0|bob"))
        return coordinator, scope, lease

    def test_mutating_exposed_scope_dict_cannot_rebind_captured_account(self):
        coordinator, scope, lease = self.mutated_dict_scope()
        try:
            self.assert_stale(lambda: coordinator.check(lease, scope, deadline=110.0))
        finally:
            coordinator.release(lease)

    def test_mutated_scope_cannot_publish_fresh_stamp(self):
        coordinator, scope, lease = self.mutated_dict_scope()
        try:
            def attempt_publication():
                with coordinator.delivery_guard(lease, scope, deadline=110.0) as guard:
                    guard.begin_enqueue()
                    guard.confirm()
                    return coordinator.publish_delivery(lease, guard=guard, deadline=110.0)

            self.assert_stale(attempt_publication)
        finally:
            coordinator.release(lease)

    def test_new_bob_scope_cannot_claim_mutated_alice_capture(self):
        coordinator, _, lease = self.mutated_dict_scope()
        coordinator.release(lease)
        bob = self.auth.AuthScope(reference(), principal("auth0|bob"))
        self.assert_stale(lambda: coordinator.open(bob, deadline=110.0))

    def test_privileged_scope_alias_change_cannot_rebind_snapshot(self):
        clock = TriggerClock()
        coordinator = self.auth.AuthCoordinator(clock=clock)
        scope = self.auth.AuthScope(reference(), principal())
        lease = coordinator.open(scope, deadline=110.0)
        try:
            try:
                object.__setattr__(scope, "_principal", types.MappingProxyType(principal("auth0|bob")))
            except (AttributeError, TypeError):
                self.skipTest("scope has no replaceable private principal slot")
            self.assert_stale(lambda: coordinator.check(lease, scope, deadline=110.0))
        finally:
            coordinator.release(lease)
        bob = self.auth.AuthScope(reference(), principal("auth0|bob"))
        self.assert_stale(lambda: coordinator.open(bob, deadline=110.0))

    def test_hostile_provider_value_returns_closed_error(self):
        ref = reference()
        ref["provider_id"] = HostileValue()
        self.assert_stale(lambda: self.auth.AuthScope(ref, principal()))

    def test_hostile_nonstr_mapping_key_returns_closed_error(self):
        self.assert_stale(lambda: self.auth.AuthScope(HostileReference(), principal()))

    def test_reentrant_clock_quarantine_blocks_begin_confirm_and_publish(self):
        for stage in ("begin", "confirm", "publish"):
            with self.subTest(stage=stage):
                clock = TriggerClock()
                coordinator = self.auth.AuthCoordinator(clock=clock)
                scope = self.auth.AuthScope(reference(), principal())
                lease = coordinator.open(scope, deadline=110.0)
                try:
                    with coordinator.delivery_guard(lease, scope, deadline=110.0) as guard:
                        if stage != "begin":
                            guard.begin_enqueue()
                        if stage == "publish":
                            guard.confirm()
                        clock.action = lambda: coordinator.quarantine(
                            lease, "refresh_unknown", deadline=110.0
                        )
                        if stage == "begin":
                            self.assert_stale(guard.begin_enqueue)
                        elif stage == "confirm":
                            self.assert_stale(guard.confirm)
                        else:
                            self.assert_stale(lambda: coordinator.publish_delivery(
                                lease, guard=guard, deadline=110.0
                            ))
                        self.assertTrue(clock.triggered, "method failed without sampling armed clock")
                finally:
                    coordinator.release(lease)
                self.assert_stale(lambda: coordinator.open(scope, deadline=110.0))


if __name__ == "__main__":
    unittest.main()
