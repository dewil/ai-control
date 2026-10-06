"""Source-blind RED for a synthetic V2 refresh source transaction slot.

The strings here are invented test data. These tests make no provider, auth,
native, account, or server request and never inspect an existing credential.
"""

import fcntl
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


BIN = Path(__file__).resolve().parents[1] / "bin"
MODULE = BIN / "_control_codex_refresh_slot.py"
LINUX = sys.platform.startswith("linux")
ATTEMPT = "123e4567-e89b-42d3-a456-426614174000"
OTHER_ATTEMPT = "123e4567-e89b-42d3-a456-426614174001"
OLD = "invented-old-refresh"
NEW = "invented-new-refresh"


def reference(account="alpha"):
    return {
        "schema": 2,
        "provider_id": "codex",
        "account_id": account,
        "profile_instance_id": "123e4567-e89b-42d3-a456-426614174002",
        "adapter_revision": "codex-chatgpt-external-auth-host-v2",
        "registration_snapshot": {
            "dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "a" * 64,
        },
    }


def principal(subject="synthetic|alice"):
    return {
        "kind": "openid_subject_workspace",
        "issuer": "https://auth.openai.com",
        "subject": subject,
        "workspace_id": "synthetic_workspace",
    }


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


class Clock:
    def __init__(self, value=100.0):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class RefreshSlotPortable(unittest.TestCase):
    def setUp(self):
        # Deliberate assertion FAIL while the new module is absent, never import error.
        self.assertTrue(MODULE.is_file(), f"contract module unavailable: {MODULE.name}")
        sys.path.insert(0, str(BIN))
        self.addCleanup(lambda: sys.path.remove(str(BIN)))
        self.authority = importlib.import_module("_control_codex_auth_authority")
        self.module = importlib.import_module("_control_codex_refresh_slot")
        self.reference = reference()
        self.principal = principal()
        self.scope = self.authority.AuthScope(self.reference, self.principal)
        self.clock = Clock()

    def slot(self, root="/synthetic/new-private-source", scope=None, clock=None):
        return self.module.AnchoredAtomicSecretSlot(
            str(root), self.scope if scope is None else scope,
            clock=self.clock if clock is None else clock,
        )

    def rejects(self, code, call):
        with self.assertRaises(self.authority.AuthError) as caught:
            call()
        error = caught.exception
        self.assertEqual(error.code, code)
        self.assertEqual(str(error), code)
        for forbidden in (OLD, NEW, "synthetic|alice", "/synthetic"):
            self.assertNotIn(forbidden, repr(error))

    def test_constructor_scope_first_and_no_io_or_clock(self):
        with mock.patch("os.open", side_effect=AssertionError("os.open")), \
             mock.patch("builtins.open", side_effect=AssertionError("open")), \
             mock.patch("os.stat", side_effect=AssertionError("stat")):
            selected = self.slot()
            self.assertEqual(self.clock.calls, 0)
            self.rejects("authority_stale", lambda: self.slot(
                root="relative/bad", scope={}))
        self.assertNotIn(OLD, repr(selected))
        self.reference["registration_snapshot"]["sha256"] = "b" * 64
        self.principal["subject"] = "changed"
        self.assertEqual(self.clock.calls, 0)

    def test_path_exactness_and_foreign_scope_precedence(self):
        for path in ("relative", "/a/", "/a//b", "/a/./b", "/a/../b",
                     "/a\x00b", "/a\ud800"):
            self.rejects("authority_stale", lambda p=path: self.slot(root=p))
        selected = self.slot()
        foreign = self.authority.AuthScope(reference("beta"), principal())
        with mock.patch("os.open", side_effect=AssertionError("os.open")):
            self.rejects("authority_stale", lambda: selected.open(
                foreign, deadline=110.0))
            self.rejects("authority_stale", lambda: selected.open(
                {}, deadline=110.0))
        self.assertEqual(self.clock.calls, 0)

    def test_deadline_and_mac_unsupported_before_fs(self):
        selected = self.slot()
        self.rejects("authority_stale", lambda: selected.open(self.scope, deadline=True))
        self.rejects("auth_unavailable", lambda: selected.open(self.scope, deadline=99.0))
        if not LINUX:
            with mock.patch("os.open", side_effect=AssertionError("os.open")):
                self.rejects("auth_unavailable", lambda: selected.open(
                    self.scope, deadline=110.0))


@unittest.skipUnless(LINUX, "requires actual Linux openat/flock/atomic replace")
class LinuxRefreshSlot(RefreshSlotPortable):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-refresh-slot-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir(mode=0o700)
        self.source = self.root / "refresh-source.json"
        self.head = self.root / "refresh-attempt.json"
        self.lock = self.root / ".refresh-slot.lock"
        self.provision()
        self.selected = self.slot(self.root)

    def provision(self):
        write_private(self.source, encoded({
            "schema": 1, "reference": self.reference,
            "generation": 1, "refresh_token": OLD,
        }))
        write_private(self.head, encoded({
            "schema": 1, "reference": self.reference,
            "generation": 1, "state": "ready",
        }))

    def open(self, selected=None, scope=None, deadline=110.0):
        return (self.selected if selected is None else selected).open(
            self.scope if scope is None else scope, deadline=deadline)

    def read(self, lease, selected=None, scope=None):
        return (self.selected if selected is None else selected).read_refresh(
            lease, self.scope if scope is None else scope, deadline=110.0)

    def reserve(self, lease, attempt=ATTEMPT, selected=None, scope=None):
        return (self.selected if selected is None else selected).reserve_attempt(
            lease, self.scope if scope is None else scope, attempt, deadline=110.0)

    def rotate(self, lease, token=NEW, attempt=ATTEMPT, selected=None, scope=None):
        return (self.selected if selected is None else selected).commit_rotation(
            lease, self.scope if scope is None else scope, attempt, token, deadline=110.0)

    def finish(self, lease, attempt=ATTEMPT, selected=None, scope=None):
        return (self.selected if selected is None else selected).finish_confirmed(
            lease, self.scope if scope is None else scope, attempt, deadline=110.0)

    def close(self, lease, selected=None):
        return (self.selected if selected is None else selected).close(lease)

    def replace_source(self, token, generation=1):
        path = self.root / "synthetic-temp-source"
        write_private(path, encoded({"schema": 1, "reference": self.reference,
                                     "generation": generation,
                                     "refresh_token": token}))
        os.replace(path, self.source)

    def test_ready_to_pending_rotation_completed_is_durable_and_private(self):
        lease = self.open()
        self.addCleanup(lambda: self.close(lease))
        self.assertFalse(hasattr(lease, "fileno"))
        self.assertFalse(hasattr(lease, "fd"))
        self.assertFalse(hasattr(lease, "__dict__"))
        self.assertNotIn(OLD, repr(lease))
        self.assertEqual(self.read(lease), OLD)
        self.assertEqual(self.read(lease), OLD)
        original_source_ino = self.source.stat().st_ino
        original_head_ino = self.head.stat().st_ino
        self.reserve(lease)
        pending = json.loads(self.head.read_bytes())
        self.assertEqual(pending, {"schema": 1, "reference": self.reference,
                                   "generation": 1, "attempt_id": ATTEMPT,
                                   "state": "pending"})
        self.assertNotEqual(self.head.stat().st_ino, original_head_ino)
        self.assertNotIn(OLD, self.head.read_text())
        self.assertNotIn(NEW, self.head.read_text())
        self.rotate(lease)
        self.assertNotEqual(self.source.stat().st_ino, original_source_ino)
        self.assertEqual(json.loads(self.source.read_bytes()), {
            "schema": 1, "reference": self.reference,
            "generation": 2, "refresh_token": NEW,
        })
        self.finish(lease)
        self.assertEqual(json.loads(self.head.read_bytes()), {
            "schema": 1, "reference": self.reference,
            "attempt_id": ATTEMPT, "initial_generation": 1,
            "final_generation": 2, "state": "completed",
        })
        with self.assertRaises(self.authority.AuthError) as caught:
            self.read(lease)
        self.assertIn(caught.exception.code, ("authority_stale", "refresh_unknown"))
        self.close(lease)
        next_lease = self.open()
        self.assertEqual(self.read(next_lease), NEW)
        self.close(next_lease)
        for path in (self.source, self.head, self.lock):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)

    def test_no_rotation_completes_at_same_generation(self):
        lease = self.open()
        self.assertEqual(self.read(lease), OLD)
        self.reserve(lease)
        self.finish(lease)
        self.close(lease)
        self.assertEqual(json.loads(self.head.read_bytes())["final_generation"], 1)
        next_lease = self.open()
        self.assertEqual(self.read(next_lease), OLD)
        self.close(next_lease)

    def test_pending_missing_and_corrupt_head_deny_startup_without_secret(self):
        lease = self.open()
        self.read(lease)
        self.reserve(lease)
        self.close(lease)
        self.rejects("refresh_unknown", lambda: self.open())
        self.head.unlink()
        self.rejects("refresh_unknown", lambda: self.open())
        write_private(self.head, b'{"schema":1,"schema":1}')
        self.rejects("refresh_unknown", lambda: self.open())
        self.assertEqual(json.loads(self.source.read_bytes())["refresh_token"], OLD)

    def test_false_terminal_and_source_generation_type_cannot_open(self):
        self.head.unlink()
        write_private(self.head, encoded({
            "schema": 1, "reference": self.reference,
            "attempt_id": ATTEMPT, "initial_generation": 1,
            "final_generation": 2, "state": "completed",
        }))
        self.rejects("refresh_unknown", lambda: self.open())
        self.head.unlink()
        write_private(self.head, encoded({
            "schema": 1, "reference": self.reference,
            "generation": 1, "state": "ready",
        }))
        self.source.unlink()
        write_private(self.source, encoded({
            "schema": 1, "reference": self.reference,
            "generation": True, "refresh_token": OLD,
        }))
        self.rejects("unsupported_auth_profile", lambda: self.open())

    def test_source_missing_wrong_schema_and_symlink_denied(self):
        self.source.unlink()
        self.rejects("unsupported_auth_profile", lambda: self.open())
        write_private(self.source, b'{"schema":1,"schema":1}')
        self.rejects("unsupported_auth_profile", lambda: self.open())
        self.source.unlink()
        elsewhere = self.root / "other-private"
        write_private(elsewhere, encoded({"schema": 1, "reference": self.reference,
                                          "generation": 1, "refresh_token": OLD}))
        os.symlink(elsewhere, self.source)
        self.rejects("unsupported_auth_profile", lambda: self.open())

    def test_maximally_escaped_token_fits_updated_byte_cap_but_oversize_denies(self):
        self.source.unlink()
        invented_escaped = '"' * 16384
        valid = encoded({"schema": 1, "reference": self.reference,
                         "generation": 1, "refresh_token": invented_escaped})
        self.assertLessEqual(len(valid), 65536)
        self.assertGreater(len(valid), 32768)
        write_private(self.source, valid)
        lease = self.open()
        self.assertEqual(self.read(lease), invented_escaped)
        self.close(lease)
        self.source.unlink()
        write_private(self.source, valid + b" " * (65537 - len(valid)))
        self.rejects("unsupported_auth_profile", lambda: self.open())

    def test_first_read_pin_rejects_same_generation_token_and_inode_drift(self):
        lease = self.open()
        self.assertEqual(self.read(lease), OLD)
        self.replace_source("invented-external-token")
        self.rejects("authority_stale", lambda: self.read(lease))
        self.rejects("authority_stale", lambda: self.reserve(lease))
        self.close(lease)

    def test_valid_pending_owner_drift_is_unknown_but_foreign_scope_is_stale_first(self):
        lease = self.open()
        self.read(lease)
        self.reserve(lease)
        self.replace_source("invented-external-token")
        foreign = self.authority.AuthScope(reference("beta"), principal())
        self.rejects("authority_stale", lambda: self.rotate(
            lease, scope=foreign))
        self.rejects("refresh_unknown", lambda: self.rotate(lease))
        self.rejects("refresh_unknown", lambda: self.finish(lease))
        self.close(lease)
        self.rejects("refresh_unknown", lambda: self.open())

    def test_invalid_attempt_and_token_code_changes_after_reserve(self):
        lease = self.open()
        self.read(lease)
        self.rejects("authority_stale", lambda: self.reserve(lease, attempt="bad"))
        self.reserve(lease)
        self.rejects("refresh_unknown", lambda: self.rotate(
            lease, token="bad token"))
        self.rejects("refresh_unknown", lambda: self.finish(lease))
        self.close(lease)

    def test_pending_deadline_error_poison_follows_scope_precedence(self):
        lease = self.open()
        self.read(lease)
        self.reserve(lease)
        foreign = self.authority.AuthScope(reference("beta"), principal())
        self.rejects("authority_stale", lambda: self.selected.finish_confirmed(
            lease, foreign, ATTEMPT, deadline=99.0))
        self.rejects("refresh_unknown", lambda: self.selected.finish_confirmed(
            lease, self.scope, ATTEMPT, deadline=99.0))
        self.rejects("refresh_unknown", lambda: self.finish(lease))
        self.close(lease)
        self.rejects("refresh_unknown", lambda: self.open())

    def test_no_first_read_no_reservation_and_thread_lease_refuses(self):
        lease = self.open()
        self.rejects("authority_stale", lambda: self.reserve(lease))
        codes = []
        def other_thread():
            try:
                self.read(lease)
            except self.authority.AuthError as error:
                codes.append(error.code)
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(codes, ["authority_stale"])
        self.close(lease)
        self.close(lease)
        self.rejects("authority_stale", lambda: self.read(lease))

    def test_external_flock_busy_and_different_root_independent(self):
        write_private(self.lock, b"")
        fd = os.open(self.lock, os.O_RDONLY)
        self.addCleanup(lambda: os.close(fd))
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(lambda: fcntl.flock(fd, fcntl.LOCK_UN))
        real_slot = self.slot(self.root, clock=time.monotonic)
        self.rejects("refresh_busy", lambda: real_slot.open(
            self.scope, deadline=time.monotonic() + 0.2))
        other_root = Path(self.temp.name) / "other-source"
        other_root.mkdir(mode=0o700)
        other_ref = reference("beta")
        other_scope = self.authority.AuthScope(other_ref, principal("synthetic|bob"))
        write_private(other_root / "refresh-source.json", encoded({
            "schema": 1, "reference": other_ref, "generation": 1,
            "refresh_token": "invented-beta-refresh",
        }))
        write_private(other_root / "refresh-attempt.json", encoded({
            "schema": 1, "reference": other_ref, "generation": 1, "state": "ready",
        }))
        other_slot = self.slot(other_root, scope=other_scope)
        other_lease = other_slot.open(other_scope, deadline=110.0)
        self.assertEqual(other_slot.read_refresh(
            other_lease, other_scope, deadline=110.0), "invented-beta-refresh")
        other_slot.close(other_lease)

    def test_same_root_second_object_cannot_bypass_held_lease(self):
        first = self.open()
        self.addCleanup(lambda: self.close(first))
        second = self.slot(self.root, clock=time.monotonic)
        outcome = []
        def contender():
            try:
                lease = second.open(self.scope, deadline=time.monotonic() + 0.2)
                outcome.append("entered")
                second.close(lease)
            except self.authority.AuthError as error:
                outcome.append(error.code)
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, ["refresh_busy"])

    def test_capacity_counts_orphans_before_lock_creation(self):
        for index in range(9998):
            write_private(self.root / f"orphan-{index:05d}", b"x")
        self.assertEqual(len(list(self.root.iterdir())), 10000)
        self.rejects("auth_unavailable", lambda: self.open())
        self.assertFalse(self.lock.exists())
        self.assertEqual(len(list(self.root.iterdir())), 10000)

    def test_ambiguous_post_reservation_replace_poison_and_pending_restart(self):
        lease = self.open()
        self.read(lease)
        self.reserve(lease)
        original_replace = os.replace
        def replace_then_fail(*args, **kwargs):
            original_replace(*args, **kwargs)
            raise OSError("invented fsync/replace uncertainty")
        with mock.patch("os.replace", side_effect=replace_then_fail):
            self.rejects("refresh_unknown", lambda: self.rotate(lease))
        self.rejects("refresh_unknown", lambda: self.finish(lease))
        self.close(lease)
        self.rejects("refresh_unknown", lambda: self.open())

    def test_root_replacement_after_open_never_exposes_token(self):
        lease = self.open()
        moved = Path(self.temp.name) / "moved-source"
        os.rename(self.root, moved)
        self.root.mkdir(mode=0o700)
        with self.assertRaises(self.authority.AuthError) as caught:
            self.read(lease)
        self.assertIn(caught.exception.code, ("authority_stale", "auth_unavailable"))
        self.close(lease)
        self.assertFalse(self.source.exists())


if __name__ == "__main__":
    unittest.main()
