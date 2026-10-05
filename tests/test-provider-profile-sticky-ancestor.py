#!/usr/bin/env python3
"""INV-ACCOUNT-10 sticky shared and private ancestor snapshot fence."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

FIXTURE_PATH = Path(__file__).resolve().parent / 'test-provider-profile-capture-reference.py'
FIXTURE_SPEC = importlib.util.spec_from_file_location('provider_profile_capture_fixture', FIXTURE_PATH)
fixture = importlib.util.module_from_spec(FIXTURE_SPEC)
sys.modules[FIXTURE_SPEC.name] = fixture
FIXTURE_SPEC.loader.exec_module(fixture)
RegistrationFixtureHelpers = fixture.RegistrationFixtureHelpers


class StatWithTimestampDrift:
    """Stat-shaped view that models only directory mtime/ctime changing."""
    def __init__(self, original):
        self._original = original

    def __getattr__(self, name):
        if name == 'st_mtime_ns':
            return self._original.st_mtime_ns + 1_000_000_000
        if name == 'st_ctime_ns':
            return self._original.st_ctime_ns + 1_000_000_000
        if name == 'st_mtime':
            return self._original.st_mtime + 1
        if name == 'st_ctime':
            return self._original.st_ctime + 1
        return getattr(self._original, name)


def drift_after_first_observation(target):
    """Return an os.stat hook that changes only later timestamp observations."""
    target = Path(target).absolute()
    original_stat = os.stat
    original_lstat = os.lstat
    original_fstat = os.fstat
    target_identity = original_stat(target).st_dev, original_stat(target).st_ino
    observations = 0

    def hook_for(original, fd_based=False):
        def hooked(path, *args, **kwargs):
            nonlocal observations
            result = original(path, *args, **kwargs)
            if fd_based:
                same_path = (result.st_dev, result.st_ino) == target_identity
            else:
                try:
                    same_path = Path(os.fsdecode(path)).absolute() == target
                except (TypeError, ValueError):
                    same_path = False
            if same_path:
                observations += 1
                if observations > 1:
                    return StatWithTimestampDrift(result)
            return result
        return hooked

    return hook_for(original_stat), hook_for(original_lstat), hook_for(original_fstat, fd_based=True), lambda: observations


class ProviderProfileStickyAncestorTests(RegistrationFixtureHelpers, unittest.TestCase):
    def registered_selector(self):
        self.registered()
        return ('codex', 'alpha', 'fixture')

    def test_shared_root_sticky_ancestor_timestamp_change_does_not_reject_profile(self):
        # INV-ACCOUNT-10: a sibling in shared sticky /var/tmp may change its timestamps.
        selector = self.registered_selector()
        sticky_ancestor = Path('/var/tmp')
        info = sticky_ancestor.stat()
        self.assertEqual(info.st_uid, 0)
        self.assertTrue(info.st_mode & 0o1000)
        stat_hook, lstat_hook, fstat_hook, observations = drift_after_first_observation(sticky_ancestor)

        with patch.object(os, 'stat', side_effect=stat_hook), patch.object(os, 'lstat', side_effect=lstat_hook), patch.object(os, 'fstat', side_effect=fstat_hook):
            with self.no_native_reads():
                try:
                    resolved = self.profiles.register(*selector, self.metadata_path)
                except fixture.accounts.AccountError as exc:
                    self.fail(f'INV-ACCOUNT-10: unrelated shared sticky ancestor time drift refused: {exc.code}')

        self.assertGreaterEqual(observations(), 2, 'timestamp drift hook did not cover before/after observations')
        self.assertEqual(resolved['provider_id'], 'codex')
        self.assertEqual(resolved['account_id'], 'alpha')

    def test_private_owned_ancestor_timestamp_change_still_rejects_profile(self):
        # INV-ACCOUNT-10: private-owned ancestry retains its before/after time fence.
        selector = self.registered_selector()
        private_ancestor = Path(self.tmp.name)
        info = private_ancestor.stat()
        self.assertEqual(info.st_uid, os.getuid())
        stat_hook, lstat_hook, fstat_hook, observations = drift_after_first_observation(private_ancestor)

        with patch.object(os, 'stat', side_effect=stat_hook), patch.object(os, 'lstat', side_effect=lstat_hook), patch.object(os, 'fstat', side_effect=fstat_hook):
            with self.no_native_reads():
                self.refuse('profile_unsafe', lambda: self.profiles.register(*selector, self.metadata_path))

        self.assertGreaterEqual(observations(), 2, 'timestamp drift hook did not cover before/after observations')


if __name__ == '__main__':
    unittest.main()
