#!/usr/bin/env python3
"""INV-ACCOUNT-09 publication-fault tests against synthetic private fixtures."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / 'tests' / 'test-provider-profile-registration.py'
FIXTURE_SPEC = importlib.util.spec_from_file_location('provider_profile_registration_fixture', FIXTURE_PATH)
fixture = importlib.util.module_from_spec(FIXTURE_SPEC)
sys.modules[FIXTURE_SPEC.name] = fixture
FIXTURE_SPEC.loader.exec_module(fixture)

accounts = fixture.accounts
profiles = fixture.profiles
INPUT = fixture.INPUT


class RegistrationFixtureHelpers:
    """Reuse the existing synthetic HOME, catalog, metadata, and safe-error helpers."""

    setUp = fixture.ProviderProfileContract.setUp
    provider_class = fixture.ProviderProfileContract.provider_class
    provider = fixture.ProviderProfileContract.provider
    write_catalog = fixture.ProviderProfileContract.write_catalog
    write_metadata = fixture.ProviderProfileContract.write_metadata
    registered = fixture.ProviderProfileContract.registered
    refuse = fixture.ProviderProfileContract.refuse
    no_native_reads = fixture.ProviderProfileContract.no_native_reads
    profiles = fixture.ProviderProfileContract.profiles

    def assert_safe_account_error(self, operation):
        with self.assertRaises(accounts.AccountError) as caught:
            operation()
        self.assertNotIn(str(self.home), str(caught.exception))
        self.assertNotIn('synthetic-a', str(caught.exception))
        return caught.exception

    def assert_not_activated(self):
        self.assertFalse((self.profile_root / 'registration.json').exists())
        self.assertEqual(list((self.profile_root / 'codex').iterdir()), [])
        self.assertEqual(list((self.profile_root / 'native-home').iterdir()), [])

    def targets_registration_leaf(self, destination, keyword_args):
        destination_path = Path(os.fsdecode(destination))
        if destination_path.name != 'registration.json':
            return False
        destination_dir_fd = keyword_args.get('dst_dir_fd')
        if destination_path.is_absolute():
            return destination_path == self.profile_root / 'registration.json'
        if destination_dir_fd is None:
            return (Path.cwd() / destination_path) == self.profile_root / 'registration.json'
        root_info = self.profile_root.stat()
        directory_info = os.fstat(destination_dir_fd)
        return (directory_info.st_dev, directory_info.st_ino) == (root_info.st_dev, root_info.st_ino)

    def is_profile_root_fd(self, descriptor):
        try:
            directory_info = os.fstat(descriptor)
            root_info = self.profile_root.stat()
        except OSError:
            return False
        return (directory_info.st_dev, directory_info.st_ino) == (root_info.st_dev, root_info.st_ino)


class ProviderProfilePublicationTests(RegistrationFixtureHelpers, unittest.TestCase):
    def test_catalog_revoked_after_registration_link_fails_and_removes_leaf(self):
        original_link = os.link
        mutated = False

        def link_then_revoke(src, dst, *args, **kwargs):
            nonlocal mutated
            result = original_link(src, dst, *args, **kwargs)
            if not mutated and self.targets_registration_leaf(dst, kwargs):
                mutated = True
                self.write_catalog([fixture.account_row(enabled=False), fixture.account_row('beta')])
            return result

        with patch.object(os, 'link', side_effect=link_then_revoke):
            error = self.assert_safe_account_error(self.registered)

        self.assertTrue(mutated, 'registration leaf publication link was not reached')
        self.assertEqual(error.code, 'account_disabled')
        self.assert_not_activated()

    def test_metadata_replaced_after_registration_link_fails_and_removes_leaf(self):
        original_link = os.link
        replaced = False

        def link_then_replace_metadata(src, dst, *args, **kwargs):
            nonlocal replaced
            result = original_link(src, dst, *args, **kwargs)
            if not replaced and self.targets_registration_leaf(dst, kwargs):
                replaced = True
                replacement = self.metadata_path.with_name('replacement-metadata.json')
                changed = dict(INPUT, expected_native_principal={
                    'kind': 'chatgpt_account_id', 'value': 'synthetic-b'})
                replacement.write_text(json.dumps(changed), encoding='utf-8')
                replacement.chmod(0o600)
                os.replace(replacement, self.metadata_path)
            return result

        with patch.object(os, 'link', side_effect=link_then_replace_metadata):
            self.assert_safe_account_error(self.registered)

        self.assertTrue(replaced, 'registration leaf publication link was not reached')
        self.assert_not_activated()

    def test_postpublication_root_fsync_failure_fails_and_rolls_back_leaf(self):
        original_fsync = os.fsync
        failed = False

        def fail_after_link(descriptor):
            nonlocal failed
            if not failed and self.is_profile_root_fd(descriptor) and (self.profile_root / 'registration.json').exists():
                failed = True
                raise OSError(errno.EIO, 'synthetic post-publication directory fsync failure')
            return original_fsync(descriptor)

        with patch.object(os, 'fsync', side_effect=fail_after_link):
            self.assert_safe_account_error(self.registered)

        self.assertTrue(failed, 'post-publication profile-root fsync was not reached')
        self.assert_not_activated()

if __name__ == '__main__':
    unittest.main()
