#!/usr/bin/env python3
"""Public provider profile CLI contract; synthetic private HOME only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
import uuid

HERE = Path(__file__).resolve().parent
loader = importlib.util.spec_from_file_location(
    'provider_binding_fixture', HERE / 'test-provider-account-binding.py')
binding = importlib.util.module_from_spec(loader)
loader.loader.exec_module(binding)


class ProviderProfileCLI(unittest.TestCase):
    run_cmd = binding.BindingCLI.run_cmd
    git = binding.BindingCLI.git
    catalog_write = binding.BindingCLI.catalog_write
    spec = binding.BindingCLI.spec
    no_launch = binding.BindingCLI.no_launch

    def setUp(self):
        binding.BindingCLI.setUp(self)
        self.rows = [dict(provider_id='codex', account_id=account,
                          label='Safe ' + account, enabled=True, projects=['fixture'])
                     for account in ('profile-a', 'profile-b')]
        self.catalog_write()
        self.profile_root = self.home / '.local/share/ai-control/provider-profiles/codex'
        self.profile_root.mkdir(parents=True, mode=0o700)

    def profile_dirs(self, account='profile-a'):
        root = self.profile_root / account
        codex = root / 'codex'
        native_home = root / 'native-home'
        for path in (root, codex, native_home):
            path.mkdir(mode=0o700)
        return root, codex, native_home

    def metadata(self, value='synthetic-a', **changes):
        document = dict(schema=1, adapter_revision='codex-managed-chatgpt-file-v1',
                        auth_source='managed_chatgpt', credential_store='file',
                        expected_native_principal=dict(kind='chatgpt_account_id', value=value))
        document.update(changes)
        path = self.root / 'registration-metadata.json'
        path.write_text(json.dumps(document, separators=(',', ':')))
        path.chmod(0o600)
        return path

    def register(self, account='profile-a', metadata=None, extra=()):
        return self.run_cmd('ai-rc', 'accounts', 'profile', 'register',
                            '--provider', 'codex', '--account', account,
                            '--project', 'fixture', '--metadata', metadata or self.metadata(),
                            '--json', *extra)

    def profile_status(self, account='profile-a', extra=()):
        return self.run_cmd('ai-rc', 'accounts', 'profile', 'status',
                            '--provider', 'codex', '--account', account,
                            '--project', 'fixture', '--json', *extra)

    def codex_spec(self, name, **changes):
        return self.spec(name, engine='codex', **changes)

    def create_codex(self, name='profile-task', account='profile-a', **changes):
        return self.run_cmd('ai-rc', 'agent', 'create', name, '--spec',
                            self.codex_spec(name, **changes), '--provider', 'codex',
                            '--account', account)

    def public_document(self, result):
        raw = result.stdout.strip() or result.stderr.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self.fail('Expected safe JSON public response, got: ' + raw[:240])

    def snapshot(self):
        result = binding.BindingCLI.snapshot(self)
        for path in self.profile_root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                result[str(path.relative_to(self.root))] = path.read_bytes()
        return result

    def test_register_and_status_return_exact_safe_unverified_dto(self):
        self.profile_dirs()
        metadata = self.metadata()
        registered = self.register(metadata=metadata)
        self.assertEqual(registered.returncode, 0, registered.stderr)
        document = self.public_document(registered)
        self.assertEqual(set(document), {'schema', 'provider_id', 'account_id',
                                        'profile_instance_id', 'status', 'reason'})
        self.assertEqual(document['schema'], 1)
        self.assertEqual(document['provider_id'], 'codex')
        self.assertEqual(document['account_id'], 'profile-a')
        instance = uuid.UUID(document['profile_instance_id'])
        self.assertEqual(instance.version, 4)
        self.assertEqual(document['status'], 'runtime_unverified')
        self.assertEqual(document['reason'], 'native_identity_unproven')
        status = self.profile_status()
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(self.public_document(status), document)
        public = registered.stdout + registered.stderr + status.stdout + status.stderr
        self.assertNotIn('synthetic-a', public)
        self.assertNotIn(str(self.home), public)
        self.assertFalse(self.effects.exists())

    def test_accounts_list_keeps_old_safe_projection_without_registration_details(self):
        self.profile_dirs()
        before = self.run_cmd('ai-rc', 'accounts', 'list', '--project', 'fixture', '--json')
        self.assertEqual(before.returncode, 0, before.stderr)
        before_document = json.loads(before.stdout)
        registered = self.register(metadata=self.metadata())
        self.assertEqual(registered.returncode, 0, registered.stderr)
        listed = self.run_cmd('ai-rc', 'accounts', 'list', '--project', 'fixture', '--json')
        self.assertEqual(listed.returncode, 0, listed.stderr)
        document = json.loads(listed.stdout)
        self.assertEqual(document, before_document)
        self.assertNotIn('synthetic-a', listed.stdout)
        self.assertNotIn(str(self.home), listed.stdout)
        self.assertFalse(self.effects.exists())

    def test_metadata_schema_rejects_unknown_duplicate_null_and_wrong_types_before_leaf(self):
        self.profile_dirs()
        documents = [
            '{"schema":1,"schema":1,"adapter_revision":"codex-managed-chatgpt-file-v1",'
            '"auth_source":"managed_chatgpt","credential_store":"file",'
            '"expected_native_principal":{"kind":"chatgpt_account_id","value":"synthetic-a"}}',
            json.dumps(dict(schema=1, adapter_revision='codex-managed-chatgpt-file-v1',
                            auth_source='managed_chatgpt', credential_store='file',
                            expected_native_principal={'kind': 'chatgpt_account_id', 'value': None})),
            json.dumps(dict(schema=True, adapter_revision='codex-managed-chatgpt-file-v1',
                            auth_source='managed_chatgpt', credential_store='file',
                            expected_native_principal={'kind': 'chatgpt_account_id', 'value': 'synthetic-a'})),
            json.dumps(dict(schema=1, adapter_revision='codex-managed-chatgpt-file-v1',
                            auth_source='managed_chatgpt', credential_store='file',
                            expected_native_principal={'kind': 'chatgpt_account_id', 'value': 'synthetic-a'},
                            endpoint='https://invalid.example')),
        ]
        for raw in documents:
            with self.subTest(raw=raw[:80]):
                metadata = self.root / 'bad-metadata.json'
                metadata.write_text(raw)
                metadata.chmod(0o600)
                before = self.snapshot()
                result = self.register(metadata=metadata)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                error = self.public_document(result)
                self.assertEqual(error, {'schema': 1, 'error': {'code': 'profile_invalid'}})
                self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.effects.exists())

    def test_metadata_must_be_private_regular_single_link_and_no_follow(self):
        self.profile_dirs()
        original = self.metadata()
        aliases = self.root / 'metadata-hardlink.json'
        os.link(original, aliases)
        linked = self.register(metadata=aliases)
        self.assertEqual(linked.returncode, 2, linked.stdout + linked.stderr)
        self.assertEqual(self.public_document(linked),
                         {'schema': 1, 'error': {'code': 'profile_unsafe'}})
        unsafe_mode = self.metadata()
        unsafe_mode.chmod(0o644)
        mode_result = self.register(metadata=unsafe_mode)
        self.assertEqual(mode_result.returncode, 2, mode_result.stdout + mode_result.stderr)
        self.assertEqual(self.public_document(mode_result),
                         {'schema': 1, 'error': {'code': 'profile_unsafe'}})
        target = self.metadata()
        symlink = self.root / 'metadata-symlink.json'
        symlink.symlink_to(target)
        link_result = self.register(metadata=symlink)
        self.assertEqual(link_result.returncode, 2, link_result.stdout + link_result.stderr)
        self.assertEqual(self.public_document(link_result),
                         {'schema': 1, 'error': {'code': 'profile_unsafe'}})
        self.assertFalse((self.profile_root / 'profile-a' / 'registration.json').exists())
        self.assertFalse(self.effects.exists())

    def test_unknown_and_repeated_selectors_are_refused_without_effects(self):
        self.profile_dirs()
        metadata = self.metadata()
        bad = [
            self.register(metadata=metadata, extra=('--unknown', 'x')),
            self.register(metadata=metadata, extra=('--provider', 'codex')),
            self.profile_status(extra=('--unknown', 'x')),
            self.profile_status(extra=('--provider', 'codex')),
        ]
        for result in bad:
            with self.subTest(argv=result.args):
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(self.snapshot(), {})
        self.assertFalse(self.effects.exists())

    def test_register_requires_fresh_enabled_project_grant_and_existing_profile_dirs(self):
        metadata = self.metadata()
        self.profile_dirs()
        for rows, account, expected in (
                ([dict(self.rows[0], enabled=False)], 'profile-a', 'account_disabled'),
                ([dict(self.rows[0], projects=['other'])], 'profile-a', 'account_forbidden'),
                ([], 'profile-a', 'account_unknown')):
            with self.subTest(expected=expected):
                self.rows = rows
                self.catalog_write()
                result = self.register(account, metadata)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(self.public_document(result),
                                 {'schema': 1, 'error': {'code': expected}})
                self.assertFalse((self.profile_root / account / 'registration.json').exists())
        self.rows = [dict(provider_id='codex', account_id='profile-a', label='Safe profile-a',
                          enabled=True, projects=['fixture'])]
        self.catalog_write()
        shutil.rmtree(self.profile_root / 'profile-a')
        result = self.register(metadata=metadata)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.public_document(result),
                         {'schema': 1, 'error': {'code': 'profile_unconfigured'}})
        self.assertFalse(self.effects.exists())

    def test_exact_repeat_is_idempotent_and_changed_expectation_conflicts(self):
        root, codex, native_home = self.profile_dirs()
        metadata = self.metadata()
        first = self.register(metadata=metadata)
        self.assertEqual(first.returncode, 0, first.stderr)
        dto = self.public_document(first)
        registration = root / 'registration.json'
        original_bytes = registration.read_bytes()
        original_stat = registration.stat()
        repeated = self.register(metadata=metadata)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(self.public_document(repeated), dto)
        after_stat = registration.stat()
        self.assertEqual(registration.read_bytes(), original_bytes)
        self.assertEqual((after_stat.st_dev, after_stat.st_ino, after_stat.st_ctime_ns),
                         (original_stat.st_dev, original_stat.st_ino, original_stat.st_ctime_ns))
        saved = json.loads(original_bytes)
        self.assertEqual(set(saved), {'schema', 'adapter_revision', 'auth_source',
                                      'credential_store', 'expected_native_principal',
                                      'provider_id', 'account_id', 'profile_instance_id',
                                      'profile_objects'})
        self.assertEqual(saved['expected_native_principal'],
                         {'kind': 'chatgpt_account_id', 'value': 'synthetic-a'})
        self.assertEqual(saved['provider_id'], 'codex')
        self.assertEqual(saved['account_id'], 'profile-a')
        self.assertEqual(uuid.UUID(saved['profile_instance_id']).version, 4)
        self.assertEqual(saved['profile_objects'], {
            'root': {'dev': root.stat().st_dev, 'ino': root.stat().st_ino},
            'codex': {'dev': codex.stat().st_dev, 'ino': codex.stat().st_ino},
            'native_home': {'dev': native_home.stat().st_dev, 'ino': native_home.stat().st_ino}})
        conflict = self.register(metadata=self.metadata('synthetic-b'))
        self.assertEqual(conflict.returncode, 2, conflict.stdout + conflict.stderr)
        self.assertEqual(self.public_document(conflict),
                         {'schema': 1, 'error': {'code': 'profile_conflict'}})
        self.assertEqual(registration.read_bytes(), original_bytes)
        self.assertFalse(self.effects.exists())

    def test_unregistered_explicit_create_is_paused_without_guessed_context_and_legacy_stays_unbound(self):
        result = self.create_codex()
        self.assertEqual(result.returncode, 0, result.stderr)
        control_path = self.agents / 'profile-task' / 'control.json'
        control = json.loads(control_path.read_text())
        self.assertEqual(control['provider_binding'],
                         {'schema': 1, 'provider_id': 'codex', 'account_id': 'profile-a'})
        self.assertEqual(control['desired'], 'paused')
        self.assertNotIn('provider_context', control)
        legacy = self.run_cmd('ai-rc', 'agent', 'create', 'legacy-task', '--spec',
                              self.spec('legacy-task'))
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        legacy_control = json.loads((self.agents / 'legacy-task' / 'control.json').read_text())
        self.assertNotIn('provider_binding', legacy_control)
        self.assertNotIn('provider_context', legacy_control)
        self.assertFalse(self.effects.exists())

    def test_registered_create_persists_exact_immutable_context_reference_and_stays_paused(self):
        root, codex, native_home = self.profile_dirs()
        metadata = self.metadata()
        registered = self.register(metadata=metadata)
        self.assertEqual(registered.returncode, 0, registered.stderr)
        registration_path = root / 'registration.json'
        registration_bytes = registration_path.read_bytes()
        registration = json.loads(registration_bytes)
        created = self.create_codex()
        self.assertEqual(created.returncode, 0, created.stderr)
        control_path = self.agents / 'profile-task' / 'control.json'
        control_bytes = control_path.read_bytes()
        control = json.loads(control_bytes)
        self.assertEqual(control['provider_binding'],
                         {'schema': 1, 'provider_id': 'codex', 'account_id': 'profile-a'})
        reference = control['provider_context']
        self.assertEqual(set(reference), {'schema', 'provider_id', 'account_id',
                                          'profile_instance_id', 'adapter_revision',
                                          'registration_snapshot'})
        self.assertEqual(reference['schema'], 1)
        self.assertEqual(reference['provider_id'], 'codex')
        self.assertEqual(reference['account_id'], 'profile-a')
        self.assertEqual(reference['profile_instance_id'], registration['profile_instance_id'])
        self.assertEqual(reference['adapter_revision'], 'codex-managed-chatgpt-file-v1')
        info = registration_path.stat()
        snapshot = reference['registration_snapshot']
        self.assertEqual(set(snapshot), {'dev', 'ino', 'ctime_ns', 'sha256'})
        self.assertEqual((snapshot['dev'], snapshot['ino'], snapshot['ctime_ns']),
                         (info.st_dev, info.st_ino, info.st_ctime_ns))
        self.assertEqual(snapshot['sha256'], hashlib.sha256(registration_bytes).hexdigest())
        self.assertEqual(control['desired'], 'paused')
        self.assertIn('runtime_unverified', created.stdout + created.stderr)
        self.assertEqual(control_path.read_bytes(), control_bytes)
        self.assertFalse(self.effects.exists())
        self.no_launch()


if __name__ == '__main__':
    unittest.main()
