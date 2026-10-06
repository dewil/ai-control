#!/usr/bin/env python3
"""Synthetic public contract tests for task/profile publication serialization."""
import copy
import importlib
import inspect
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
try:
    profiles_module = importlib.import_module("_control_provider_context")
except ModuleNotFoundError as exc:
    if exc.name != "_control_provider_context":
        raise
    profiles_module = None
accounts = importlib.import_module("_control_provider_accounts")

PROJECT = "fixture"
BINDING = {"schema": 1, "provider_id": "codex", "account_id": "alpha"}
INPUT = {
    "schema": 1,
    "adapter_revision": "codex-managed-chatgpt-file-v1",
    "auth_source": "managed_chatgpt",
    "credential_store": "file",
    "expected_native_principal": {"kind": "chatgpt_account_id", "value": "synthetic-a"},
}
SAMPLE_REF = {
    "schema": 1,
    "provider_id": "codex",
    "account_id": "alpha",
    "profile_instance_id": "123e4567-e89b-42d3-a456-426614174000",
    "adapter_revision": "codex-managed-chatgpt-file-v1",
    "registration_snapshot": {"dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "0" * 64},
}


def account_row(**changes):
    value = {"provider_id": "codex", "account_id": "alpha", "label": "Safe alpha",
             "enabled": True, "projects": [PROJECT]}
    value.update(changes)
    return value


class TaskPublicationGuard(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix="provider-task-publication-guard-", dir="/var/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.home = self.base / "home"
        self.home.mkdir(mode=0o700)
        self.catalog_path = self.base / "catalog.json"
        self.write_catalog([account_row()])
        self.catalog = accounts.ProviderAccounts(self.catalog_path, [PROJECT, "other"])
        self.profile_root = self.home / ".local/share/ai-control/provider-profiles/codex/alpha"
        (self.profile_root / "codex").mkdir(parents=True, mode=0o700)
        (self.profile_root / "native-home").mkdir(mode=0o700)
        self.metadata_path = self.base / "metadata.json"
        self.write_metadata()
        self._profiles = None
        self.binding = copy.deepcopy(BINDING)
        self.published = []

    def write_catalog(self, rows):
        self.catalog_path.write_text(json.dumps({"schema": 1, "accounts": rows}, separators=(",", ":")), encoding="utf-8")
        self.catalog_path.chmod(0o600)

    def write_metadata(self, value=None):
        self.metadata_path.write_text(json.dumps(INPUT if value is None else value,
                                                 separators=(",", ":")), encoding="utf-8")
        self.metadata_path.chmod(0o600)

    @property
    def profiles(self):
        if self._profiles is None:
            cls = getattr(profiles_module, "ProviderProfiles", None)
            self.assertTrue(callable(cls), "Public ProviderProfiles API is required")
            signature = inspect.signature(cls).parameters
            self.assertIn("owner_home", signature)
            self.assertIn("accounts", signature)
            self.assertIn("owner_uid", signature)
            self._profiles = cls(self.home, self.catalog, owner_uid=os.getuid())
        return self._profiles

    def require_method(self, target, name, parameters=()):
        method = getattr(target, name, None)
        self.assertTrue(callable(method), f"Public method {name} is required")
        actual = inspect.signature(method).parameters
        for parameter in parameters:
            self.assertIn(parameter, actual, f"{name} must accept {parameter}")
        return method

    def guard(self, context_ref):
        method = self.require_method(self.profiles, "task_publication_guard",
                                     ("binding", "context_ref", "project"))
        return method(self.binding, context_ref, PROJECT)

    def register(self):
        method = self.require_method(self.profiles, "register",
                                     ("provider_id", "account_id", "project", "metadata_path"))
        return method("codex", "alpha", PROJECT, self.metadata_path)

    def capture(self):
        method = self.require_method(self.profiles, "capture_reference", ("binding", "project"))
        return method(self.binding, PROJECT)

    def registered_reference(self):
        result = self.register()
        self.assertEqual(result["status"], "runtime_unverified")
        reference = self.capture()
        self.assertEqual(reference["provider_id"], "codex")
        self.assertEqual(reference["account_id"], "alpha")
        return reference

    def registration_path(self):
        return self.profile_root / "registration.json"

    def refuse(self, code, context_ref):
        entered = []
        with self.assertRaises(accounts.AccountError) as caught:
            with self.guard(context_ref):
                entered.append("atomic TASK publication")
                self.published.append("atomic TASK publication")
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(entered, [], "refused guard must not enter publisher body")
        self.assertEqual(self.published, [])

    def lock_paths(self):
        directory = self.home / ".local/share/ai-control/provider-profile-locks"
        return directory, directory / "publication.lock"

    def tree_snapshot(self, root):
        result = {}
        for path in [root, *root.rglob("*")]:
            info = path.lstat()
            value = (stat.S_IMODE(info.st_mode), info.st_uid, info.st_dev, info.st_ino,
                     info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)
            if stat.S_ISREG(info.st_mode):
                value += (path.read_bytes(),)
            result[str(path.relative_to(root)) if path != root else "."] = value
        return result

    def test_registration_writer_waits_until_absent_context_publication_body_exits(self):
        started = threading.Event()
        finished = threading.Event()
        outcome = []
        def register_worker():
            started.set()
            try:
                outcome.append(self.register())
            except BaseException as error:
                outcome.append(error)
            finally:
                finished.set()
        worker = threading.Thread(target=register_worker, daemon=True)
        guard = self.guard(None)
        try:
            with guard:
                self.published.append("atomic TASK rename")
                worker.start()
                self.assertTrue(started.wait(1), "registration worker did not start")
                self.assertFalse(finished.wait(0.2),
                                 "global profile registration must block through the guarded publication body")
                self.assertFalse(self.registration_path().exists(),
                                 "registration must not appear between absent-check and simulated TASK rename")
            self.assertTrue(finished.wait(3), "registration should continue after publication guard exits")
            worker.join(1)
        finally:
            if worker.is_alive():
                worker.join(3)
        self.assertEqual(len(outcome), 1)
        self.assertNotIsInstance(outcome[0], BaseException)
        self.assertEqual(outcome[0]["status"], "runtime_unverified")
        self.assertTrue(self.registration_path().is_file())

    def test_registration_before_guard_turns_captured_absence_into_context_drift(self):
        self.assertFalse(self.registration_path().exists())
        self.register()
        before = self.registration_path().read_bytes()
        self.refuse("context_drift", None)
        self.assertEqual(self.registration_path().read_bytes(), before)

    def test_replaced_present_registration_refuses_publication_without_touching_replacement(self):
        reference = self.registered_reference()
        leaf = self.registration_path()
        leaf.write_bytes(leaf.read_bytes() + b"\n")
        leaf.chmod(0o600)
        before_bytes = leaf.read_bytes()
        before_stat = leaf.stat()
        self.refuse("context_drift", reference)
        after_stat = leaf.stat()
        self.assertEqual(leaf.read_bytes(), before_bytes)
        self.assertEqual((after_stat.st_dev, after_stat.st_ino, after_stat.st_ctime_ns),
                         (before_stat.st_dev, before_stat.st_ino, before_stat.st_ctime_ns))

    def test_fresh_grant_and_exact_context_validation_refuse_before_publication_body(self):
        reference = self.registered_reference()
        leaf = self.registration_path()
        original = (leaf.read_bytes(), leaf.stat().st_ino)
        self.write_catalog([account_row(projects=["other"])])
        self.refuse("account_forbidden", reference)
        self.write_catalog([account_row()])
        malformed = copy.deepcopy(reference)
        malformed["registration_snapshot"]["dev"] = True
        self.refuse("context_invalid", malformed)
        self.assertEqual((leaf.read_bytes(), leaf.stat().st_ino), original)

    def test_guard_creates_private_stable_owner_lock_and_refuses_unsafe_lock_paths(self):
        lock_dir, lock_path = self.lock_paths()
        with self.guard(None):
            self.published.append("atomic TASK rename")
            dir_stat = lock_dir.stat()
            lock_stat = lock_path.lstat()
            self.assertTrue(stat.S_ISDIR(dir_stat.st_mode))
            self.assertEqual(stat.S_IMODE(dir_stat.st_mode), 0o700)
            self.assertEqual(dir_stat.st_uid, os.getuid())
            self.assertTrue(stat.S_ISREG(lock_stat.st_mode))
            self.assertEqual(stat.S_IMODE(lock_stat.st_mode), 0o600)
            self.assertEqual(lock_stat.st_uid, os.getuid())
            self.assertEqual(lock_stat.st_nlink, 1)
        self.published.clear()
        stable_inode = (lock_path.lstat().st_dev, lock_path.lstat().st_ino)
        with self.guard(None):
            self.published.append("second simulated rename")
        self.assertEqual((lock_path.lstat().st_dev, lock_path.lstat().st_ino), stable_inode,
                         "cooperating operations retain the same lock inode")
        self.published.clear()

        lock_path.chmod(0o644)
        unsafe_file = (lock_path.lstat().st_dev, lock_path.lstat().st_ino, lock_path.read_bytes())
        self.refuse("profile_unsafe", None)
        self.assertEqual((lock_path.lstat().st_dev, lock_path.lstat().st_ino, lock_path.read_bytes()), unsafe_file)
        lock_path.chmod(0o600)

        lock_dir.chmod(0o755)
        unsafe_directory = (lock_dir.stat().st_dev, lock_dir.stat().st_ino,
                            stat.S_IMODE(lock_dir.stat().st_mode))
        self.refuse("profile_unsafe", None)
        self.assertEqual((lock_dir.stat().st_dev, lock_dir.stat().st_ino,
                          stat.S_IMODE(lock_dir.stat().st_mode)), unsafe_directory)
        lock_dir.chmod(0o700)

        alias = lock_dir / "second-link"
        os.link(lock_path, alias)
        linked = (lock_path.lstat().st_dev, lock_path.lstat().st_ino, lock_path.lstat().st_nlink)
        self.refuse("profile_unsafe", None)
        self.assertEqual((lock_path.lstat().st_dev, lock_path.lstat().st_ino, lock_path.lstat().st_nlink), linked)
        alias.unlink()

        target = self.home / "lock-target"
        target.write_text("synthetic lock target", encoding="utf-8")
        target.chmod(0o600)
        lock_path.unlink()
        lock_path.symlink_to(target)
        target_before = target.read_bytes()
        self.refuse("profile_unsafe", None)
        self.assertTrue(lock_path.is_symlink(), "guard must not follow, unlink, or replace a symlink lock")
        self.assertEqual(target.read_bytes(), target_before)
        self.assertEqual(lock_path.resolve(), target.resolve())

    def test_status_capture_and_resolve_do_not_create_publication_lock_or_other_writes(self):
        provider = self.profiles
        lock_dir, lock_path = self.lock_paths()
        before_catalog = (self.catalog_path.read_bytes(), self.catalog_path.stat().st_ino,
                         self.catalog_path.stat().st_mtime_ns)
        before_tree = self.tree_snapshot(self.home)
        status = self.require_method(provider, "status", ("provider_id", "account_id", "project"))
        capture = self.require_method(provider, "capture_reference", ("binding", "project"))
        resolve = self.require_method(provider, "resolve", ("binding", "context_ref", "project"))
        for operation in (lambda: status("codex", "alpha", PROJECT),
                          lambda: capture(self.binding, PROJECT),
                          lambda: resolve(self.binding, SAMPLE_REF, PROJECT)):
            with self.assertRaises(accounts.AccountError):
                operation()
        self.assertFalse(lock_dir.exists())
        self.assertFalse(lock_path.exists())
        self.assertEqual(self.tree_snapshot(self.home), before_tree)
        self.assertEqual((self.catalog_path.read_bytes(), self.catalog_path.stat().st_ino,
                          self.catalog_path.stat().st_mtime_ns), before_catalog)
        self.assertFalse(self.registration_path().exists())


if __name__ == "__main__":
    unittest.main()
