"""Blind synthetic RED for the coordinator's account-wide poison intent."""

import importlib
import pathlib
import sys
import threading
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"


def scope_data(account="alpha"):
    return (
        {
            "schema": 2,
            "provider_id": "codex",
            "account_id": account,
            "profile_instance_id": "123e4567-e89b-42d3-a456-426614174000",
            "adapter_revision": "codex-chatgpt-external-auth-host-v2",
            "registration_snapshot": {
                "dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "a" * 64,
            },
        },
        {
            "kind": "openid_subject_workspace",
            "issuer": "https://auth.openai.com",
            "subject": "auth0|synthetic-alice",
            "workspace_id": "workspace_1",
        },
    )


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class PoisonIntentContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue((BIN / "_control_codex_auth_authority.py").is_file())
        sys.path.insert(0, str(BIN))
        self.addCleanup(lambda: sys.path.remove(str(BIN)))
        self.auth = importlib.import_module("_control_codex_auth_authority")
        self.clock = Clock()
        self.coordinator = self.auth.AuthCoordinator(clock=self.clock)
        self.scope = self.auth.AuthScope(*scope_data())

    def poison(self):
        method = getattr(self.coordinator, "poison_intent", None)
        self.assertTrue(callable(method), "AuthCoordinator.poison_intent is required")
        method(self.scope, "refresh_unknown")

    def denied(self, call):
        with self.assertRaises(self.auth.AuthError) as raised:
            call()
        self.assertEqual(raised.exception.code, "authority_stale")
        self.assertEqual(str(raised.exception), "authority_stale")

    def poison_on_other_thread_while_guard_held(self):
        errors = []
        finished = threading.Event()

        def worker():
            try:
                self.poison()
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.assertTrue(
            finished.wait(1.0),
            "poison_intent waited for a held delivery/state guard",
        )
        thread.join(1.0)
        if errors:
            raise errors[0]

    def test_poison_first_prevents_begin_and_denies_second_validator(self):
        lease = self.coordinator.open(self.scope, deadline=110.0)
        try:
            with self.coordinator.delivery_guard(
                lease, self.scope, deadline=110.0
            ) as guard:
                self.poison_on_other_thread_while_guard_held()
                self.denied(guard.begin_enqueue)
                self.denied(lambda: self.coordinator.check(
                    lease, self.scope, deadline=110.0
                ))
        finally:
            self.coordinator.release(lease)
        self.denied(lambda: self.coordinator.open(self.scope, deadline=110.0))

    def test_begin_first_claims_once_but_later_poison_blocks_publication(self):
        lease = self.coordinator.open(self.scope, deadline=110.0)
        try:
            with self.coordinator.delivery_guard(
                lease, self.scope, deadline=110.0
            ) as guard:
                guard.begin_enqueue()  # The one claimed external effect is local only.
                guard.confirm()  # Synthetic known outcome; no native transport.
                self.poison_on_other_thread_while_guard_held()
                self.denied(lambda: self.coordinator.publish_delivery(
                    lease, guard=guard, deadline=110.0
                ))
        finally:
            self.coordinator.release(lease)
        self.denied(lambda: self.coordinator.open(self.scope, deadline=110.0))

    def test_poison_ignores_expired_operation_deadline_and_is_account_scoped(self):
        lease = self.coordinator.open(self.scope, deadline=110.0)
        self.clock.value = 111.0
        self.poison()  # No deadline argument, clock renewal, or state guard.
        self.coordinator.release(lease)
        self.denied(lambda: self.coordinator.open(self.scope, deadline=120.0))
        other = self.auth.AuthScope(*scope_data("beta"))
        other_lease = self.coordinator.open(other, deadline=120.0)
        self.coordinator.check(other_lease, other, deadline=120.0)
        self.coordinator.release(other_lease)


if __name__ == "__main__":
    unittest.main()
