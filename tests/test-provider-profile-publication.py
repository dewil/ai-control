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

    def test_foreign_leaf_replacement_survives_postpublication_failure(self):
        original_link = os.link
        original_fsync = os.fsync
        replaced = False
        fsync_failed = False
        published_identity = None
        foreign_identity = None
        foreign_bytes = b'synthetic foreign writer registration leaf\n'
        leaf = self.profile_root / 'registration.json'
        foreign_path = self.profile_root / 'foreign-writer-registration.json'

        def link_then_replace(src, dst, *args, **kwargs):
            nonlocal replaced, published_identity, foreign_identity
            result = original_link(src, dst, *args, **kwargs)
            if not replaced and self.targets_registration_leaf(dst, kwargs):
                replaced = True
                published = leaf.stat()
                published_identity = (published.st_dev, published.st_ino)
                foreign_path.write_bytes(foreign_bytes)
                foreign_path.chmod(0o600)
                os.replace(foreign_path, leaf)
                foreign = leaf.stat()
                foreign_identity = (foreign.st_dev, foreign.st_ino)
            return result

        def fail_postpublication_fsync(descriptor):
            nonlocal fsync_failed
            if not fsync_failed and self.is_profile_root_fd(descriptor) and leaf.exists():
                fsync_failed = True
                raise OSError(errno.EIO, 'synthetic one-shot post-publication failure')
            return original_fsync(descriptor)

        with self.no_native_reads():
            with patch.object(os, 'link', side_effect=link_then_replace):
                with patch.object(os, 'fsync', side_effect=fail_postpublication_fsync):
                    self.assert_safe_account_error(self.registered)

        self.assertTrue(replaced, 'registration leaf publication link was not reached')
        self.assertTrue(fsync_failed, 'post-publication root fsync fault was not reached')
        self.assertNotEqual(published_identity, foreign_identity)
        self.assertTrue(leaf.exists())
        self.assertEqual((leaf.stat().st_dev, leaf.stat().st_ino), foreign_identity)
        self.assertEqual(leaf.read_bytes(), foreign_bytes)
        self.assertEqual(list((self.profile_root / 'codex').iterdir()), [])
        self.assertEqual(list((self.profile_root / 'native-home').iterdir()), [])

    def test_persistent_postpublication_root_fsync_failure_is_unknown_unsafe(self):
        original_fsync = os.fsync
        armed = False
        failures = 0
        leaf = self.profile_root / 'registration.json'

        def fail_root_fsyncs_after_publication(descriptor):
            nonlocal armed, failures
            if self.is_profile_root_fd(descriptor):
                if leaf.exists():
                    armed = True
                if armed:
                    failures += 1
                    raise OSError(errno.EIO, 'synthetic persistent directory sync failure')
            return original_fsync(descriptor)

        with self.no_native_reads():
            with patch.object(os, 'fsync', side_effect=fail_root_fsyncs_after_publication):
                error = self.assert_safe_account_error(self.registered)

        self.assertTrue(armed, 'post-publication profile-root fsync was not reached')
        self.assertGreaterEqual(failures, 1)
        self.assertEqual(error.code, 'profile_unsafe')
        self.assertEqual(list((self.profile_root / 'codex').iterdir()), [])
        self.assertEqual(list((self.profile_root / 'native-home').iterdir()), [])

if __name__ == '__main__':
    unittest.main()
