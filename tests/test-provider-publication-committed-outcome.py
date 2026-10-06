#!/usr/bin/env python3
"""Synthetic post-publication outcome tests from the public provider spec."""
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
profiles_module = importlib.import_module("_control_provider_context")
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


class PublicationCommittedOutcome(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix="provider-publication-commit-", dir="/var/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.home = self.base / "home"
        self.home.mkdir(mode=0o700)
        self.profile_root = self.home / ".local/share/ai-control/provider-profiles/codex/alpha"
        (self.profile_root / "codex").mkdir(parents=True, mode=0o700)
        (self.profile_root / "native-home").mkdir(mode=0o700)
        self.catalog_path = self.base / "catalog.json"
        self.catalog_path.write_text(json.dumps({"schema": 1, "accounts": [
            {"provider_id": "codex", "account_id": "alpha", "label": "Synthetic alpha",
             "enabled": True, "projects": [PROJECT]}
        ]}, separators=(",", ":")), encoding="utf-8")
        self.catalog_path.chmod(0o600)
        self.catalog = accounts.ProviderAccounts(self.catalog_path, [PROJECT])
        self.metadata_path = self.base / "metadata.json"
        self.metadata_path.write_text(json.dumps(INPUT, separators=(",", ":")), encoding="utf-8")
        self.metadata_path.chmod(0o600)
        cls = getattr(profiles_module, "ProviderProfiles", None)
        self.assertTrue(callable(cls), "Public ProviderProfiles API is required")
        params = inspect.signature(cls).parameters
        self.assertIn("owner_home", params)
        self.assertIn("accounts", params)
        self.assertIn("owner_uid", params)
        self.profiles = cls(self.home, self.catalog, owner_uid=os.getuid())
        self.binding = dict(BINDING)

    def require_method(self, target, name, parameters=()):
        method = getattr(target, name, None)
        self.assertTrue(callable(method), "Public method " + name + " is required")
        actual = inspect.signature(method).parameters
        for parameter in parameters:
            self.assertIn(parameter, actual, name + " must accept " + parameter)
        return method

    def publication_guard(self):
        return self.require_method(self.profiles, "task_publication_guard",
                                   ("binding", "context_ref", "project"))(
                                       self.binding, None, PROJECT)

    def register(self):
        return self.require_method(self.profiles, "register",
                                   ("provider_id", "account_id", "project", "metadata_path"))(
                                       "codex", "alpha", PROJECT, self.metadata_path)

    def install_after_rename_hook(self, target, action):
        """Run action only after a successful atomic rename to target."""
        fired = threading.Event()
        real_replace = os.replace
        real_rename = os.rename

        def wraps(real):
            def rename(source, destination, *args, **kwargs):
                result = real(source, destination, *args, **kwargs)
                if Path(destination) == target:
                    fired.set()
                    action()
                return result
            return rename

        stack = [patch.object(profiles_module.os, "replace", wraps(real_replace)),
                 patch.object(profiles_module.os, "rename", wraps(real_rename))]
        for item in stack:
            item.start()
            self.addCleanup(item.stop)
        return fired

    def test_task_rename_is_committed_even_if_postbody_ancestry_changes(self):
        """The TASK rename is the public linearization point; later checks cannot undo outcome."""
        registry = self.home / "tasks"
        registry.mkdir(mode=0o700)
        staged = registry / "task.stage"
        final = registry / "TASK.md"
        staged.write_text("synthetic committed task\n", encoding="utf-8")
        staged.chmod(0o600)
        unrelated = self.home / "entry-created-after-commit"
        fired = self.install_after_rename_hook(
            final, lambda: unrelated.write_text("synthetic unrelated entry\n", encoding="utf-8"))

        caught = None
        try:
            with self.publication_guard():
                os.replace(staged, final)
        except BaseException as error:
            caught = error

        self.assertTrue(fired.is_set(), "fault must occur after atomic TASK rename")
        self.assertIsNone(caught, "a post-rename guard check must not report a committed TASK as unpublished")
        self.assertTrue(final.is_file(), "the committed TASK remains published")
        self.assertEqual(final.read_text(encoding="utf-8"), "synthetic committed task\n")
        self.assertTrue(unrelated.is_file())

    def test_registration_postpublication_validation_failure_rolls_back_owned_leaf(self):
        """A registration validation error after its leaf rename must not leave that leaf behind."""
        leaf = self.profile_root / "registration.json"
        unrelated = self.home / "entry-created-after-registration-commit"
        fired = threading.Event()
        real_fsync = os.fsync

        def fsync_after_leaf(fd):
            result = real_fsync(fd)
            if leaf.is_file() and not fired.is_set():
                fired.set()
                unrelated.write_text("synthetic unrelated entry\n", encoding="utf-8")
            return result

        fsync_patch = patch.object(profiles_module.os, "fsync", fsync_after_leaf)
        fsync_patch.start()
        self.addCleanup(fsync_patch.stop)
        caught = None
        try:
            self.register()
        except BaseException as error:
            caught = error

        self.assertTrue(fired.is_set(), "fault must occur after atomic registration leaf publication")
        self.assertIsInstance(caught, accounts.AccountError,
                              "post-publication validation should report the detected ordinary drift")
        self.assertFalse(leaf.exists(), "ordinary registration failure must roll back its own leaf")
        self.assertTrue(unrelated.is_file(), "rollback must preserve the unrelated injected entry")


if __name__ == "__main__":
    unittest.main()
