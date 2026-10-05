#!/usr/bin/env python3
"""INV-ACCOUNT-09/10 registration and immutable context contract.

Only private synthetic fixtures are used. These tests never invoke a provider,
read an authentication store, or modify the caller's environment.
"""
import copy
import hashlib
import importlib
import io
import builtins
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
try:
    profiles = importlib.import_module('_control_provider_context')
except ModuleNotFoundError as exc:
    if exc.name != '_control_provider_context':
        raise
    profiles = None
accounts = importlib.import_module('_control_provider_accounts')

INPUT = {
    'schema': 1,
    'adapter_revision': 'codex-managed-chatgpt-file-v1',
    'auth_source': 'managed_chatgpt',
    'credential_store': 'file',
    'expected_native_principal': {'kind': 'chatgpt_account_id', 'value': 'synthetic-a'},
}
REGISTRATION_DTO_KEYS = {'schema', 'provider_id', 'account_id', 'profile_instance_id', 'status', 'reason'}
CONTEXT_REF = {
    'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha',
    'profile_instance_id': '123e4567-e89b-42d3-a456-426614174000',
    'adapter_revision': 'codex-managed-chatgpt-file-v1',
    'registration_snapshot': {'dev': 1, 'ino': 2, 'ctime_ns': 3, 'sha256': '0' * 64},
}


def account_row(account='alpha', **changes):
    value = dict(provider_id='codex', account_id=account, label='Safe ' + account,
                 enabled=True, projects=['fixture'])
    value.update(changes)
    return value


class ProviderProfileContract(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='provider-profile-registration-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir(mode=0o700)
        self.catalog_path = Path(self.tmp.name) / 'catalog.json'
        self.write_catalog([account_row(), account_row('beta')])
        self.catalog = accounts.ProviderAccounts(self.catalog_path, ['fixture', 'other'])
        self.profile_root = self.home / '.local/share/ai-control/provider-profiles/codex/alpha'
        (self.profile_root / 'codex').mkdir(parents=True, mode=0o700)
        (self.profile_root / 'native-home').mkdir(mode=0o700)
        self.metadata_path = Path(self.tmp.name) / 'operator-metadata.json'
        self.write_metadata(INPUT)
        self._profiles = None

    @property
    def profiles(self):
        if self._profiles is None:
            self._profiles = self.provider()
        return self._profiles

    def provider_class(self):
        self.assertTrue(callable(getattr(profiles, 'ProviderProfiles', None)),
                        'INV-ACCOUNT-09/10: public ProviderProfiles module/API is absent')
        return profiles.ProviderProfiles

    def provider(self):
        return self.provider_class()(self.home, self.catalog, owner_uid=os.getuid())

    def write_catalog(self, rows):
        self.catalog_path.write_text(json.dumps({'schema': 1, 'accounts': rows}), encoding='utf-8')
        self.catalog_path.chmod(0o600)

    def write_metadata(self, value):
        if isinstance(value, bytes):
            self.metadata_path.write_bytes(value)
        elif isinstance(value, str):
            self.metadata_path.write_text(value, encoding='utf-8')
        else:
            self.metadata_path.write_text(json.dumps(value), encoding='utf-8')
        self.metadata_path.chmod(0o600)

    def registered(self):
        return self.profiles.register('codex', 'alpha', 'fixture', self.metadata_path)

    def refuse(self, code, operation):
        with self.assertRaises(accounts.AccountError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(str(self.home), str(caught.exception))
        self.assertNotIn('synthetic-a', str(caught.exception))

    def no_native_reads(self):
        stack = ExitStack()
        native_dirs = (self.profile_root / 'codex', self.profile_root / 'native-home')
        opened_directories = {}
        def guarded(original):
            def opened(file, *args, **kwargs):
                if isinstance(file, (str, bytes, os.PathLike)):
                    path = Path(os.fsdecode(file))
                    if not path.is_absolute() and kwargs.get('dir_fd') in opened_directories:
                        path = opened_directories[kwargs['dir_fd']] / path
                    path = path.absolute()
                    if any(path.is_relative_to(directory) for directory in native_dirs) and not path.is_dir():
                        raise AssertionError('INV-ACCOUNT-10: registration/status read native profile contents')
                result = original(file, *args, **kwargs)
                if original is os_open and isinstance(result, int) and isinstance(file, (str, bytes, os.PathLike)) and path.is_dir():
                    opened_directories[result] = path
                return result
            return opened
        os_open = os.open
        for module, name in ((builtins, 'open'), (io, 'open'), (os, 'open')):
            stack.enter_context(patch.object(module, name, guarded(getattr(module, name))))
        return stack

    def test_persisted_registration_has_exact_input_and_control_measured_objects(self):
        # INV-ACCOUNT-10
        result = self.registered()
        leaf = self.profile_root / 'registration.json'
        value = json.loads(leaf.read_bytes())
        self.assertEqual(set(value), set(INPUT) | {'provider_id', 'account_id', 'profile_instance_id', 'profile_objects'})
        for key, expected in INPUT.items():
            self.assertEqual(value[key], expected)
        self.assertEqual(value['profile_instance_id'], result['profile_instance_id'])
        self.assertEqual(value['provider_id'], 'codex')
        self.assertEqual(value['account_id'], 'alpha')
        self.assertEqual(leaf.stat().st_mode & 0o777, 0o600)
        self.assertEqual(leaf.stat().st_nlink, 1)
        self.assertEqual(set(value['profile_objects']), {'root', 'codex', 'native_home'})
        for key, directory in (('root', self.profile_root), ('codex', self.profile_root / 'codex'),
                               ('native_home', self.profile_root / 'native-home')):
            info = directory.stat()
            self.assertEqual(value['profile_objects'][key], {'dev': info.st_dev, 'ino': info.st_ino})

    def test_register_returns_exact_safe_unverified_dto_without_authentication_reads(self):
        environment = dict(os.environ)
        with self.no_native_reads():
            result = self.registered()
            self.assertEqual(self.profiles.status('codex', 'alpha', 'fixture'), result)
        self.assertEqual(dict(os.environ), environment)
        self.assertEqual(set(result), REGISTRATION_DTO_KEYS)
        self.assertEqual({k: result[k] for k in ('schema', 'provider_id', 'account_id', 'status', 'reason')},
                         {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha',
                          'status': 'runtime_unverified', 'reason': 'native_identity_unproven'})
        identifier = uuid.UUID(result['profile_instance_id'])
        self.assertEqual(identifier.version, 4)
        self.assertEqual(identifier.variant, uuid.RFC_4122)
        self.assertEqual(str(identifier), result['profile_instance_id'])
        for dto in self.catalog.list_accounts('fixture'):
            self.assertEqual(set(dto), {'provider_id', 'account_id', 'label', 'status', 'capabilities'})
            self.assertTrue(dto['capabilities']['create_task'])
            self.assertTrue(all(value is False for key, value in dto['capabilities'].items() if key != 'create_task'))
        self.assertNotIn('synthetic-a', json.dumps(result))
        self.assertFalse((self.profile_root / 'codex/auth.json').exists())

    def test_registration_replay_preserves_uuid_leaf_bytes_inode_and_ctime(self):
        first = self.registered()
        leaf = self.profile_root / 'registration.json'
        before_stat, before_bytes = leaf.stat(), leaf.read_bytes()
        second = self.registered()
        after_stat = leaf.stat()
        self.assertEqual(first['profile_instance_id'], second['profile_instance_id'])
        self.assertEqual(before_bytes, leaf.read_bytes())
        self.assertEqual((before_stat.st_dev, before_stat.st_ino, before_stat.st_ctime_ns),
                         (after_stat.st_dev, after_stat.st_ino, after_stat.st_ctime_ns))

    def test_changed_expectation_is_conflict_and_existing_leaf_is_untouched(self):
        self.registered()
        leaf = self.profile_root / 'registration.json'
        before = (leaf.read_bytes(), leaf.stat().st_ino)
        changed = dict(INPUT, expected_native_principal={'kind': 'chatgpt_account_id', 'value': 'synthetic-b'})
        self.write_metadata(changed)
        self.refuse('profile_conflict', self.registered)
        self.assertEqual((leaf.read_bytes(), leaf.stat().st_ino), before)

    def test_unregistered_status_is_explicit(self):
        self.refuse('profile_unconfigured', lambda: self.profiles.status('codex', 'alpha', 'fixture'))

    def test_disabled_and_forbidden_grants_are_refused_before_profile_access(self):
        self.metadata_path.unlink()
        (self.profile_root / 'codex').chmod(0o777)
        self.write_catalog([account_row(enabled=False)])
        self.refuse('account_disabled', self.registered)
        self.write_catalog([account_row(projects=['other'])])
        self.refuse('account_forbidden', self.registered)

    def test_unknown_project_is_refused_before_profile_access(self):
        self.refuse('project_unknown', lambda: self.profiles.register('codex', 'alpha', 'unknown', self.metadata_path))

    def test_strict_metadata_rejects_duplicate_keys_unknown_fields_and_invalid_json(self):
        for data in ('{"schema":1,"schema":1}', '{',
                     json.dumps(INPUT).replace('"value": "synthetic-a"', '"value": "synthetic-a", "value": "synthetic-b"'),
                     json.dumps(dict(INPUT, schema=True)), json.dumps(dict(INPUT, credential_store=None)),
                     json.dumps(dict(INPUT, auth_source=1)), json.dumps(dict(INPUT, command='x')),
                     json.dumps(dict(INPUT, expected_native_principal=None)),
                     json.dumps(dict(INPUT, expected_native_principal={'kind':'chatgpt_account_id','value':'é'}))):
            with self.subTest(data=data):
                self.write_metadata(data)
                self.refuse('profile_invalid', self.registered)

    def test_metadata_paths_env_and_command_values_are_rejected(self):
        for field, value in (('provider_id', 'codex'), ('account_id', 'beta'),
                             ('profile_instance_id', CONTEXT_REF['profile_instance_id']),
                             ('profile_objects', {}), ('registration_snapshot', {}),
                             ('path', '/tmp/auth'), ('env', {'CODEX_HOME': '/tmp/x'}),
                             ('command', 'codex login'), ('endpoint', 'https://example.invalid')):
            with self.subTest(field=field):
                self.write_metadata(dict(INPUT, **{field: value}))
                self.refuse('profile_invalid', self.registered)

    def test_metadata_file_requires_private_regular_single_link_and_bounded_bytes(self):
        self.metadata_path.chmod(0o644)
        self.refuse('profile_unsafe', self.registered)
        self.metadata_path.chmod(0o600)
        alias = self.metadata_path.with_name('metadata-alias')
        os.link(self.metadata_path, alias)
        self.refuse('profile_unsafe', self.registered)
        alias.unlink()
        self.write_metadata(b' ' * (16 * 1024 + 1))
        self.refuse('profile_invalid', self.registered)

    def test_metadata_symlink_is_refused(self):
        real = self.metadata_path.with_name('real-metadata')
        self.metadata_path.rename(real)
        self.metadata_path.symlink_to(real)
        self.refuse('profile_unsafe', self.registered)

    def test_profile_layout_permissions_symlinks_and_aliases_are_refused(self):
        self.home.chmod(0o770)
        self.refuse('profile_unsafe', self.registered)
        self.home.chmod(0o700)
        wrong_owner = self.provider_class()(self.home, self.catalog, owner_uid=os.getuid() + 1)
        self.refuse('profile_unsafe', lambda: wrong_owner.register('codex', 'alpha', 'fixture', self.metadata_path))
        (self.profile_root / 'codex').chmod(0o755)
        self.refuse('profile_unsafe', self.registered)
        (self.profile_root / 'codex').chmod(0o700)
        (self.profile_root / 'native-home').rmdir()
        (self.profile_root / 'native-home').symlink_to(self.profile_root / 'codex', target_is_directory=True)
        self.refuse('profile_unsafe', self.registered)

    def test_cross_account_profile_directory_alias_is_denied(self):
        # INV-ACCOUNT-09/10: one account cannot reuse another account's directory.
        beta = self.profile_root.parent / 'beta'
        beta.mkdir(mode=0o700)
        (beta / 'native-home').mkdir(mode=0o700)
        (beta / 'codex').symlink_to(self.profile_root / 'codex', target_is_directory=True)
        self.refuse('profile_unsafe', lambda: self.profiles.register('codex', 'beta', 'fixture', self.metadata_path))
        self.assertFalse((beta / 'registration.json').exists())

    def test_existing_registration_leaf_must_be_private_regular_and_unaliased(self):
        self.registered()
        leaf = self.profile_root / 'registration.json'
        leaf.chmod(0o644)
        self.refuse('profile_unsafe', self.registered)
        leaf.chmod(0o600)
        alias = leaf.with_name('registration-alias')
        os.link(leaf, alias)
        self.refuse('profile_unsafe', self.registered)

    def test_validate_context_ref_exact_shape_and_native_integer_hash_uuid_rules(self):
        validate = getattr(profiles, 'validate_context_ref', None)
        self.assertTrue(callable(validate), 'INV-ACCOUNT-10: validate_context_ref public API absent')
        valid = validate(CONTEXT_REF)
        self.assertEqual(valid, CONTEXT_REF)
        self.assertIsNot(valid, CONTEXT_REF)
        invalids = [dict(CONTEXT_REF, extra=True), dict(CONTEXT_REF, schema=True),
                    dict(CONTEXT_REF, profile_instance_id='not-a-uuid'),
                    dict(CONTEXT_REF, registration_snapshot=dict(CONTEXT_REF['registration_snapshot'], dev=True)),
                    dict(CONTEXT_REF, registration_snapshot=dict(CONTEXT_REF['registration_snapshot'], ino=-1)),
                    dict(CONTEXT_REF, registration_snapshot=dict(CONTEXT_REF['registration_snapshot'], sha256='A' * 64))]
        for key in ('dev', 'ino', 'ctime_ns'):
            for bad in (True, False, -1, 1.0, '1', None):
                invalids.append(dict(CONTEXT_REF, registration_snapshot=dict(CONTEXT_REF['registration_snapshot'], **{key: bad})))
        for sha in ('A' * 64, '0' * 63, '0' * 65, 'g' * 64, None):
            invalids.append(dict(CONTEXT_REF, registration_snapshot=dict(CONTEXT_REF['registration_snapshot'], sha256=sha)))
        invalids += [dict(CONTEXT_REF, registration_snapshot={}),
                     dict(CONTEXT_REF, registration_snapshot=dict(CONTEXT_REF['registration_snapshot'], extra=1)),
                     {k: v for k, v in CONTEXT_REF.items() if k != 'registration_snapshot'}]
        for value in invalids:
            with self.subTest(value=value):
                self.refuse('context_invalid', lambda value=value: validate(value))

    def test_context_ref_validation_returns_deep_independent_copy(self):
        validate = getattr(profiles, 'validate_context_ref', None)
        self.assertTrue(callable(validate), 'INV-ACCOUNT-10: validate_context_ref public API absent')
        original = copy.deepcopy(CONTEXT_REF)
        result = validate(original)
        result['registration_snapshot']['dev'] = 99
        self.assertEqual(original, CONTEXT_REF)

    def test_context_cas_rejects_add_remove_change_and_malformed_values(self):
        # INV-ACCOUNT-09/10: CAS accepts whole controls, including old bound/legacy.
        check = getattr(profiles, 'check_context_unchanged', None)
        self.assertTrue(callable(check), 'INV-ACCOUNT-10: check_context_unchanged public API absent')
        binding = {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha'}
        previous = {'provider_binding': binding, 'provider_context': copy.deepcopy(CONTEXT_REF)}
        self.assertIsNone(check(previous, copy.deepcopy(previous)))
        self.assertIsNone(check({}, {}))
        for old in ({}, {'provider_binding': binding}):
            self.refuse('context_immutable', lambda old=old: check(old, dict(old, provider_context=CONTEXT_REF)))
        self.refuse('context_immutable', lambda: check(previous, {'provider_binding': binding}))
        changed = copy.deepcopy(CONTEXT_REF)
        changed['profile_instance_id'] = str(uuid.uuid4())
        self.refuse('context_immutable', lambda: check(previous, dict(previous, provider_context=changed)))
        for malformed in (None, {}, dict(CONTEXT_REF, registration_snapshot={})):
            self.refuse('context_invalid', lambda malformed=malformed: check(
                previous, dict(previous, provider_context=malformed)))
            self.refuse('context_invalid', lambda malformed=malformed: check(
                {'provider_context': malformed}, {'provider_context': malformed}))

    def test_resolve_returns_deep_frozen_context_without_ambient_environment_mutation(self):
        self.registered()
        leaf = self.profile_root / 'registration.json'
        data = leaf.read_bytes()
        st = leaf.stat()
        doc = json.loads(data)
        ref = {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha',
               'profile_instance_id': doc['profile_instance_id'], 'adapter_revision': INPUT['adapter_revision'],
               'registration_snapshot': {'dev': st.st_dev, 'ino': st.st_ino, 'ctime_ns': st.st_ctime_ns,
                                         'sha256': hashlib.sha256(data).hexdigest()}}
        binding = {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha'}
        environment = dict(os.environ)
        with self.no_native_reads():
            ctx = self.profiles.resolve(binding, ref, 'fixture')
        self.assertEqual(dict(os.environ), environment)
        self.assertEqual(ctx.reference, ref)
        # Exact native_home/child_home role assignment awaits contract clarification.
        for attribute in ('native_home', 'child_home'):
            self.assertTrue(Path(getattr(ctx, attribute)).is_relative_to(self.profile_root))
        for variable in ('HOME', 'CODEX_HOME'):
            self.assertTrue(Path(ctx.child_env[variable]).is_relative_to(self.profile_root))
        self.assertEqual(dict(ctx.expected_native_principal), INPUT['expected_native_principal'])
        self.assertNotIn('synthetic-a', repr(ctx.reference))
        with self.assertRaises((TypeError, AttributeError)):
            ctx.reference['account_id'] = 'beta'
        with self.assertRaises((TypeError, AttributeError)):
            ctx.child_env['HOME'] = '/tmp/ambient'
        with self.assertRaises((TypeError, AttributeError)):
            ctx.reference['registration_snapshot']['ino'] = 99
        with self.assertRaises((TypeError, AttributeError)):
            ctx.expected_native_principal['value'] = 'synthetic-b'
        with self.assertRaises((TypeError, AttributeError)):
            ctx.child_home = '/tmp/ambient'
        ref['registration_snapshot']['ino'] = 99
        self.assertNotEqual(ctx.reference['registration_snapshot']['ino'], 99)

    def test_registration_replacement_or_same_uuid_edit_causes_context_drift(self):
        self.registered()
        leaf = self.profile_root / 'registration.json'
        original_bytes = leaf.read_bytes()
        original = json.loads(original_bytes)
        binding = {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha'}
        def reference():
            data = leaf.read_bytes(); info = leaf.stat(); doc = json.loads(data)
            return {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha',
                    'profile_instance_id': doc['profile_instance_id'], 'adapter_revision': INPUT['adapter_revision'],
                    'registration_snapshot': {'dev': info.st_dev, 'ino': info.st_ino,
                                              'ctime_ns': info.st_ctime_ns, 'sha256': hashlib.sha256(data).hexdigest()}}
        before = reference()
        leaf.write_bytes(original_bytes + b'\n')
        self.assertEqual(json.loads(leaf.read_bytes()), original)
        self.refuse('context_drift', lambda: self.profiles.resolve(binding, before, 'fixture'))
        changed = dict(original, expected_native_principal={'kind': 'chatgpt_account_id', 'value': 'synthetic-b'})
        leaf.write_text(json.dumps(changed), encoding='utf-8'); leaf.chmod(0o600)
        self.refuse('context_drift', lambda: self.profiles.resolve(binding, before, 'fixture'))
        replacement = leaf.with_name('replacement.json')
        replacement.write_bytes(original_bytes)
        replacement.chmod(0o600)
        replacement.replace(leaf)
        self.refuse('context_drift', lambda: self.profiles.resolve(binding, before, 'fixture'))

    def test_binding_and_context_must_match_and_legacy_context_is_not_inferred(self):
        self.registered()
        self.refuse('context_missing', lambda: self.profiles.resolve(
            {'schema': 1, 'provider_id': 'codex', 'account_id': 'alpha'}, None, 'fixture'))
        self.refuse('context_invalid', lambda: self.profiles.resolve(
            {'schema': 1, 'provider_id': 'codex', 'account_id': 'beta'}, CONTEXT_REF, 'fixture'))


if __name__ == '__main__':
    unittest.main()
