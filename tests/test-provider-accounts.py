#!/usr/bin/env python3
"""Independent INV-ACCOUNT catalog/binding contract; synthetic private files only."""
import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
try:
    accounts = importlib.import_module('_control_provider_accounts')
except ModuleNotFoundError as exc:
    if exc.name != '_control_provider_accounts':
        raise
    accounts = None
CAPABILITIES = {'create_task', 'session_messages', 'images', 'files', 'questions', 'events'}

def row(account='alpha', **changes):
    result = dict(provider_id='claude', account_id=account, label='Safe ' + account,
                  enabled=True, projects=['fixture'])
    result.update(changes)
    return result

class AccountContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(accounts, 'ProviderAccounts', None)),
            'INV-ACCOUNT-01: accepted account catalog public boundary absent')
        self.assertTrue(callable(getattr(accounts, 'validate_binding', None)),
            'INV-ACCOUNT-03: immutable binding validator absent')
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='provider-account-contract-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'accounts.json'
        self.write([row(), row('beta')])
        self.reader = accounts.ProviderAccounts(self.path, ['fixture', 'other'])

    def write(self, rows):
        self.path.write_text(json.dumps(dict(schema=1, accounts=rows)))
        self.path.chmod(0o600)

    def refusal(self, code, operation):
        with self.assertRaises(accounts.AccountError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(str(self.path), str(caught.exception))
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', str(caught.exception))

    def test_two_accounts_safe_projection_and_fixed_nonexecution_capabilities(self):
        values = self.reader.list_accounts('fixture')
        self.assertEqual([v['account_id'] for v in values], ['alpha', 'beta'])
        for value in values:
            self.assertEqual(set(value), {'provider_id', 'account_id', 'label', 'status', 'capabilities'})
            self.assertEqual(value['status'], 'runtime_unverified')
            self.assertEqual(set(value['capabilities']), CAPABILITIES)
            self.assertIs(value['capabilities']['create_task'], True)
            self.assertTrue(all(v is False for k, v in value['capabilities'].items() if k != 'create_task'))
        self.assertEqual(self.reader.resolve('claude', 'alpha', 'fixture'), values[0])

    def test_fresh_label_and_permission_snapshot_without_identity_change(self):
        before = self.reader.resolve('claude', 'alpha', 'fixture')
        self.write([row(label='Changed safe label'), row('beta', projects=['other'])])
        self.assertEqual(self.reader.resolve('claude', 'alpha', 'fixture')['label'], 'Changed safe label')
        self.assertEqual(before['account_id'], 'alpha')
        self.assertEqual([v['account_id'] for v in self.reader.list_accounts('fixture')], ['alpha'])
        self.refusal('account_forbidden', lambda: self.reader.resolve('claude', 'beta', 'fixture'))

    def test_disabled_listed_but_resolve_refused(self):
        self.write([row(enabled=False)])
        value = self.reader.list_accounts('fixture')[0]
        self.assertEqual(value['status'], 'disabled')
        self.assertIs(value['capabilities']['create_task'], False)
        self.refusal('account_disabled', lambda: self.reader.resolve('claude', 'alpha', 'fixture'))

    def test_wildcard_only_and_unknown_project_refusal(self):
        self.write([row(projects=['*'])])
        self.assertEqual(len(self.reader.list_accounts('other')), 1)
        self.refusal('project_unknown', lambda: self.reader.list_accounts('unregistered'))
        for projects in ([], ['*', 'fixture'], ['fixture', 'fixture'], ['unregistered']):
            with self.subTest(projects=projects):
                self.write([row(projects=projects)])
                self.refusal('catalog_invalid', lambda: self.reader.list_accounts('fixture'))

    def test_missing_catalog_is_explicit_unconfigured(self):
        self.path.unlink()
        self.refusal('catalog_unconfigured', lambda: self.reader.list_accounts('fixture'))

    def test_duplicate_account_across_providers_and_unknown_provider_refuse(self):
        self.write([row(), row(provider_id='codex')])
        self.refusal('catalog_invalid', lambda: self.reader.list_accounts('fixture'))
        self.write([row(provider_id='unsupported')])
        self.refusal('unsupported_provider', lambda: self.reader.list_accounts('fixture'))

    def test_plain_ascii_ids_and_safe_labels(self):
        for changes in ({'account_id': '../alpha'}, {'account_id': 'Alpha'}, {'account_id': 'a'*65},
                        {'account_id': 'аlpha'}, {'label': ''}, {'label': 'x'*81},
                        {'label': 'text\x00'}, {'label': 'text\u0085'}, {'label': '\u202espoof'},
                        {'label': '/tmp/SYNTHETIC_PRIVATE_MARKER/auth.json'}):
            with self.subTest(changes=changes):
                self.write([row(**changes)])
                self.refusal('catalog_invalid', lambda: self.reader.list_accounts('fixture'))

    def test_strict_json_types_keys_duplicates_and_size(self):
        documents = ['{"schema":1,"schema":1,"accounts":[]}', '{invalid',
            '{"schema":1,"accounts":[],"command":"SYNTHETIC_PRIVATE_MARKER"}',
            '{"schema":true,"accounts":[]}', '{"schema":1,"accounts":NaN}',
            ' '*262145]
        for document in documents:
            with self.subTest(document=document[:50]):
                self.path.write_text(document)
                self.refusal('catalog_invalid', lambda: self.reader.list_accounts('fixture'))
        for changes in ({'enabled': 1}, {'projects': 'fixture'}, {'env': {}}, {'capabilities': {'events': True}}):
            with self.subTest(changes=changes):
                self.write([row(**changes)])
                self.refusal('catalog_invalid', lambda: self.reader.list_accounts('fixture'))

    def test_private_file_no_symlink_hardlink_or_unsafe_ancestor(self):
        self.path.chmod(0o644)
        self.refusal('catalog_unsafe', lambda: self.reader.list_accounts('fixture'))
        self.path.chmod(0o600)
        extra = self.path.with_name('alias')
        os.link(self.path, extra)
        self.refusal('catalog_unsafe', lambda: self.reader.list_accounts('fixture'))
        extra.unlink()
        self.path.rename(extra)
        self.path.symlink_to(extra)
        self.refusal('catalog_unsafe', lambda: self.reader.list_accounts('fixture'))
        self.path.unlink(); extra.rename(self.path)
        self.path.parent.chmod(0o770)
        self.refusal('catalog_unsafe', lambda: self.reader.list_accounts('fixture'))
        self.path.parent.chmod(0o700)

    def test_owner_and_catalog_account_count_bounds(self):
        wrong_owner = accounts.ProviderAccounts(self.path, ['fixture'], owner_uid=os.getuid()+1)
        self.refusal('catalog_unsafe', lambda: wrong_owner.list_accounts('fixture'))
        self.write([row('a'+str(i)) for i in range(257)])
        self.refusal('catalog_invalid', lambda: self.reader.list_accounts('fixture'))

    def test_unknown_account_and_forbidden_resolution_do_not_leak_label(self):
        self.refusal('account_unknown', lambda: self.reader.resolve('claude', 'missing', 'fixture'))
        self.write([row(label='SYNTHETIC_PRIVATE_MARKER', projects=['other'])])
        self.refusal('account_forbidden', lambda: self.reader.resolve('claude', 'alpha', 'fixture'))

    def test_binding_exact_clone_and_immutable_control_field(self):
        binding = dict(schema=1, provider_id='claude', account_id='alpha')
        validated = accounts.validate_binding(binding)
        self.assertEqual(validated, binding)
        self.assertIsNot(validated, binding)
        previous = dict(incarnation='1'*32, provider_binding=binding)
        self.assertIsNone(accounts.check_binding_unchanged(previous, copy.deepcopy(previous)))
        self.assertIsNone(accounts.check_binding_unchanged({}, {}))
        for candidate in ({}, dict(provider_binding=dict(binding, account_id='beta')),
                          dict(provider_binding=dict(binding, provider_id='codex'))):
            with self.subTest(candidate=candidate):
                self.refusal('binding_immutable', lambda: accounts.check_binding_unchanged(previous, candidate))
        self.refusal('binding_immutable', lambda: accounts.check_binding_unchanged({}, previous))

    def test_malformed_binding_is_not_legacy(self):
        for binding in (None, {}, {'schema': True, 'provider_id':'claude', 'account_id':'alpha'},
                        {'schema':1,'provider_id':'claude','account_id':'../alpha'},
                        {'schema':1,'provider_id':'claude','account_id':'alpha','label':'extra'}):
            with self.subTest(binding=binding):
                self.refusal('invalid_binding', lambda: accounts.validate_binding(binding))
                self.refusal('invalid_binding', lambda: accounts.check_binding_unchanged(
                    dict(provider_binding=binding), dict(provider_binding=binding)))

if __name__ == '__main__':
    unittest.main()
