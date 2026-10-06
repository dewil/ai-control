#!/usr/bin/env python3
"""INV-ACCOUNT-09 capture-reference contract using synthetic private fixtures."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / 'tests' / 'test-provider-profile-registration.py'
FIXTURE_SPEC = importlib.util.spec_from_file_location('provider_profile_registration_fixture', FIXTURE_PATH)
fixture = importlib.util.module_from_spec(FIXTURE_SPEC)
sys.modules[FIXTURE_SPEC.name] = fixture
FIXTURE_SPEC.loader.exec_module(fixture)

accounts = fixture.accounts
INPUT = fixture.INPUT


class RegistrationFixtureHelpers:
    """Reuse the existing synthetic HOME, catalog, registration, and error helpers."""

    setUp = fixture.ProviderProfileContract.setUp
    provider_class = fixture.ProviderProfileContract.provider_class
    provider = fixture.ProviderProfileContract.provider
    write_catalog = fixture.ProviderProfileContract.write_catalog
    write_metadata = fixture.ProviderProfileContract.write_metadata
    registered = fixture.ProviderProfileContract.registered
    refuse = fixture.ProviderProfileContract.refuse
    no_native_reads = fixture.ProviderProfileContract.no_native_reads
    profiles = fixture.ProviderProfileContract.profiles

    def capture_method(self):
        capture = getattr(self.profiles, 'capture_reference', None)
        self.assertTrue(callable(capture),
                        'INV-ACCOUNT-09: ProviderProfiles.capture_reference public API is absent')
        return capture


class ProviderProfileCaptureReferenceTests(RegistrationFixtureHelpers, unittest.TestCase):
    def test_capture_returns_exact_independent_reference_without_effects_or_native_reads(self):
        self.registered()
        leaf = self.profile_root / 'registration.json'
        leaf_bytes = leaf.read_bytes()
        leaf_stat = leaf.stat()
        registration = json.loads(leaf_bytes)
        expected = {
            'schema': 1,
            'provider_id': 'codex',
            'account_id': 'alpha',
            'profile_instance_id': registration['profile_instance_id'],
            'adapter_revision': INPUT['adapter_revision'],
            'registration_snapshot': {
                'dev': leaf_stat.st_dev,
                'ino': leaf_stat.st_ino,
                'ctime_ns': leaf_stat.st_ctime_ns,
                'sha256': hashlib.sha256(leaf_bytes).hexdigest(),
            },
        }
        catalog_bytes = self.catalog_path.read_bytes()
        metadata_bytes = self.metadata_path.read_bytes()
        environment = dict(os.environ)
        directory_stats = {
            path: (path.stat().st_dev, path.stat().st_ino, path.stat().st_ctime_ns)
            for path in (self.profile_root, self.profile_root / 'codex', self.profile_root / 'native-home')
        }
        capture = self.capture_method()
        binding = {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha'}

        with self.no_native_reads():
            first = capture(binding, 'fixture')
            second = capture(binding, 'fixture')

        self.assertIs(type(first), dict)
        self.assertIs(type(first['registration_snapshot']), dict)
        self.assertEqual(set(first), set(expected))
        self.assertEqual(set(first['registration_snapshot']), {'dev', 'ino', 'ctime_ns', 'sha256'})
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertIsNot(first, second)
        self.assertIsNot(first['registration_snapshot'], second['registration_snapshot'])
        first['registration_snapshot']['ino'] += 1
        self.assertEqual(second, expected)
        self.assertEqual(leaf.read_bytes(), leaf_bytes)
        self.assertEqual((leaf.stat().st_dev, leaf.stat().st_ino, leaf.stat().st_ctime_ns),
                         (leaf_stat.st_dev, leaf_stat.st_ino, leaf_stat.st_ctime_ns))
        self.assertEqual(self.catalog_path.read_bytes(), catalog_bytes)
        self.assertEqual(self.metadata_path.read_bytes(), metadata_bytes)
        self.assertEqual(dict(os.environ), environment)
        self.assertEqual({path: (path.stat().st_dev, path.stat().st_ino, path.stat().st_ctime_ns)
                          for path in directory_stats}, directory_stats)

    def test_capture_missing_registration_and_fresh_forbidden_grant_precedence(self):
        capture = self.capture_method()
        binding = {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha'}

        with self.no_native_reads():
            self.refuse('profile_unconfigured', lambda: capture(binding, 'fixture'))

        # A fresh forbidden grant must take precedence even when no registration exists.
        self.write_catalog([fixture.account_row(projects=['other']), fixture.account_row('beta')])
        with self.no_native_reads():
            self.refuse('account_forbidden', lambda: capture(binding, 'fixture'))

    def test_captured_reference_rejects_same_bytes_replacement_and_whitespace_edit(self):
        self.registered()
        capture = self.capture_method()
        binding = {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha'}
        leaf = self.profile_root / 'registration.json'
        original_bytes = leaf.read_bytes()
        original_document = json.loads(original_bytes)
        original_stat = leaf.stat()

        with self.no_native_reads():
            captured = capture(binding, 'fixture')
        replacement = Path(self.tmp.name) / 'same-bytes-registration.json'
        replacement.write_bytes(original_bytes)
        replacement.chmod(0o600)
        replacement_stat = replacement.stat()
        self.assertNotEqual((replacement_stat.st_dev, replacement_stat.st_ino),
                            (original_stat.st_dev, original_stat.st_ino))
        os.replace(replacement, leaf)
        self.assertEqual(leaf.read_bytes(), original_bytes)
        self.assertNotEqual(leaf.stat().st_ino, original_stat.st_ino)
        with self.no_native_reads():
            self.refuse('context_drift', lambda: self.profiles.resolve(binding, captured, 'fixture'))

        fresh_capture = capture(binding, 'fixture')
        leaf.write_bytes(original_bytes + b' \n')
        leaf.chmod(0o600)
        self.assertEqual(json.loads(leaf.read_bytes()), original_document)
        with self.no_native_reads():
            self.refuse('context_drift', lambda: self.profiles.resolve(binding, fresh_capture, 'fixture'))


if __name__ == '__main__':
    unittest.main()
