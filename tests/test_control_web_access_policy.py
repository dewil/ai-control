"""Independent INV-WEB-12 contract tests; synthetic in-memory policy only."""
import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = ('view', 'answer', 'verdict', 'recover')


def load_feature(case):
    path = ROOT / 'bin' / '_control_web_access.py'
    case.assertTrue(path.is_file(), 'Absent public policy module _control_web_access.py')
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def policy_document():
    return {
        'version': 1, 'owner': 'owner',
        'projects': {'control': '/srv/control', 'toolkit': '/srv/toolkit',
                     'same-root': '/srv/control'},
        'users': {
            'owner': {'enabled': True, 'auth_epoch': 1, 'projects': []},
            'reviewer': {'enabled': True, 'auth_epoch': 7, 'projects': ['control']},
            'empty': {'enabled': True, 'auth_epoch': 1, 'projects': []},
            'disabled': {'enabled': False, 'auth_epoch': 1, 'projects': ['control']},
        },
    }


# INV-WEB-12
class WebAccessPolicyContract(unittest.TestCase):
    def setUp(self):
        self.access = load_feature(self)

    def assert_invalid(self, document):
        with self.assertRaises(self.access.PolicyError):
            self.access.validate_policy(document)

    def allowed(self, document, principal='reviewer', name='control',
                path='/srv/control', operation='view'):
        return self.access.authorize(document, principal, name, path, operation)

    def test_valid_document_and_error_base_class(self):
        self.assertTrue(issubclass(self.access.PolicyError, ValueError))
        document = policy_document()
        validated = self.access.validate_policy(document)
        self.assertEqual(validated, document)
        self.assertIs(type(validated), dict)
        self.assertIs(type(validated['users']), dict)
        self.assertIs(type(validated['users']['reviewer']['projects']), list)

    def test_deep_copy_has_no_mutable_aliases_in_either_direction(self):
        document = policy_document()
        expected = copy.deepcopy(document)
        validated = self.access.validate_policy(document)
        self.assertEqual(document, expected)
        for original, cloned in [(document, validated),
                                 (document['projects'], validated['projects']),
                                 (document['users'], validated['users']),
                                 (document['users']['reviewer'], validated['users']['reviewer']),
                                 (document['users']['reviewer']['projects'],
                                  validated['users']['reviewer']['projects'])]:
            self.assertIsNot(original, cloned)
        document['users']['reviewer']['projects'].append('toolkit')
        document['users']['reviewer']['enabled'] = False
        document['projects']['control'] = '/srv/rebound'
        self.assertEqual(validated, expected)
        validated['users']['owner']['projects'].append('control')
        self.assertEqual(document['users']['owner']['projects'], [])

    def test_root_schema_requires_exact_fields_and_types(self):
        for malformed in [None, [], (), 'policy', 1, True]:
            with self.subTest(root_type=type(malformed).__name__):
                self.assert_invalid(malformed)
        for key in ('version', 'owner', 'projects', 'users'):
            document = policy_document()
            del document[key]
            with self.subTest(missing=key):
                self.assert_invalid(document)
        document = policy_document()
        document['role'] = 'admin'
        self.assert_invalid(document)
        for key, values in [('version', [True, False, 0, 2, 1.0, '1', None]),
                            ('owner', [None, [], {}, 1, 'unknown']),
                            ('projects', [None, [], (), 'projects']),
                            ('users', [None, [], (), {}, 'users'])]:
            for value in values:
                with self.subTest(field=key, value=value):
                    document = policy_document()
                    document[key] = value
                    self.assert_invalid(document)

    def test_username_grammar_and_boundaries(self):
        for username in ('a', 'a' + '0' * 31, 'lower_9-name'):
            document = policy_document()
            document['users'][username] = document['users'].pop('reviewer')
            self.assertEqual(self.access.validate_policy(document), document)
        for username in ('', 'A', '9user', '_user', '-user', 'a' * 33,
                         'with space', 'é', 'user\n', 'user.name', 1, None):
            with self.subTest(username=username):
                document = policy_document()
                document['users'][username] = document['users'].pop('reviewer')
                self.assert_invalid(document)

    def test_project_alias_grammar_and_length(self):
        for alias in ('a', 'a' * 128, '工具', 'control team', 'Control'):
            document = policy_document()
            document['projects'][alias] = '/srv/valid'
            document['users']['reviewer']['projects'] = [alias]
            self.assertEqual(self.access.validate_policy(document), document)
            self.assertIs(self.allowed(document, name=alias, path='/srv/valid'), True)
        for alias in ('', 'a' * 129, ' control', 'control ', '*', 'a?', '[a]',
                      'a\x00b', 'a\x1fb', 'a\x7fb', 1, None):
            with self.subTest(alias=alias):
                document = policy_document()
                document['projects'][alias] = '/srv/valid'
                self.assert_invalid(document)

    def test_pinned_root_grammar_and_length(self):
        for path in ('/srv/工具', '/srv/control team', '/srv/.hidden',
                     '/srv/name..suffix', '/' + 'a' * 4095):
            document = policy_document()
            document['projects']['control'] = path
            self.assertEqual(self.access.validate_policy(document), document)
            self.assertIs(self.allowed(document, path=path), True)
        for path in (None, 1, [], '', '/', 'srv/control', '/srv/control/',
                     '/srv/./control', '/srv/../control', '/.', '/..',
                     '/srv//control', '//srv/control', '///srv/control',
                     '/srv/a\x00b', '/srv/a\x1fb', '/srv/a\x7fb',
                     '/' + 'a' * 4096):
            with self.subTest(path=path):
                document = policy_document()
                document['projects']['control'] = path
                self.assert_invalid(document)

    def test_user_records_require_exact_schema(self):
        for record in (None, [], (), 'user', True):
            document = policy_document()
            document['users']['reviewer'] = record
            self.assert_invalid(document)
        for key in ('enabled', 'auth_epoch', 'projects'):
            with self.subTest(missing=key):
                document = policy_document()
                del document['users']['reviewer'][key]
                self.assert_invalid(document)
        for key in ('password', 'password_hash', 'totp', 'role', 'path', 'path_override'):
            with self.subTest(extra=key):
                document = policy_document()
                document['users']['reviewer'][key] = 'synthetic-field-value'
                self.assert_invalid(document)

    def test_exact_builtin_types_reject_subclasses(self):
        class DerivedDict(dict):
            pass

        class DerivedList(list):
            pass

        class DerivedStr(str):
            pass

        class DerivedInt(int):
            pass

        documents = [DerivedDict(policy_document())]
        for key in ('users', 'projects'):
            document = policy_document()
            document[key] = DerivedDict(document[key])
            documents.append(document)
        for key, value in [('owner', DerivedStr('owner')), ('version', DerivedInt(1))]:
            document = policy_document()
            document[key] = value
            documents.append(document)
        for key, value in [('auth_epoch', DerivedInt(1)),
                           ('projects', DerivedList(['control'])),
                           ('projects', [DerivedStr('control')])]:
            document = policy_document()
            document['users']['reviewer'][key] = value
            documents.append(document)
        document = policy_document()
        document['users']['reviewer'] = DerivedDict(document['users']['reviewer'])
        documents.append(document)
        document = policy_document()
        document['users'][DerivedStr('reviewer')] = document['users'].pop('reviewer')
        documents.append(document)
        document = policy_document()
        document['projects'][DerivedStr('control')] = document['projects'].pop('control')
        documents.append(document)
        document = policy_document()
        document['projects']['control'] = DerivedStr('/srv/control')
        documents.append(document)
        document = policy_document()
        document[DerivedStr('version')] = document.pop('version')
        documents.append(document)
        document = policy_document()
        record = document['users']['reviewer']
        record[DerivedStr('enabled')] = record.pop('enabled')
        documents.append(document)
        for index, document in enumerate(documents):
            with self.subTest(case=index):
                self.assert_invalid(document)
                self.assertIs(self.allowed(document, principal='owner'), False)
        for arguments in [dict(principal=DerivedStr('owner')),
                          dict(name=DerivedStr('control'), principal='owner'),
                          dict(path=DerivedStr('/srv/control'), principal='owner'),
                          dict(operation=DerivedStr('view'), principal='owner')]:
            with self.subTest(context=arguments):
                self.assertIs(self.allowed(policy_document(), **arguments), False)
    def test_enabled_epoch_and_grants_types_and_references(self):
        for field, values in [('enabled', [0, 1, 'true', None, []]),
                              ('auth_epoch', [True, False, 0, -1, 2147483648,
                                              1.0, '1', None]),
                              ('projects', [None, 'control', ('control',),
                                            {'control': True}, ['missing'],
                                            ['control', 'control'], [1], [None], [[]]])]:
            for value in values:
                with self.subTest(field=field, value=value):
                    document = policy_document()
                    document['users']['reviewer'][field] = value
                    self.assert_invalid(document)
        document = policy_document()
        document['users']['reviewer']['auth_epoch'] = 2147483647
        self.assertEqual(self.access.validate_policy(document), document)

    def test_owner_must_be_enabled_and_have_empty_grants(self):
        for changes in ({'enabled': False}, {'projects': ['control']}):
            document = policy_document()
            document['users']['owner'].update(changes)
            self.assert_invalid(document)
            self.assertIs(self.allowed(document, principal='owner'), False)
        document = policy_document()
        document['owner'] = 'reviewer'
        self.assert_invalid(document)

    def test_collection_limits_accept_256_and_reject_257(self):
        document = policy_document()
        document['users'] = {'owner': document['users']['owner']}
        for index in range(255):
            document['users'][f'u{index}'] = {
                'enabled': True, 'auth_epoch': 1, 'projects': []}
        self.assertEqual(self.access.validate_policy(document), document)
        document['users']['overflow'] = {'enabled': True, 'auth_epoch': 1, 'projects': []}
        self.assert_invalid(document)
        document = policy_document()
        document['projects'] = {f'p{i}': f'/srv/p{i}' for i in range(256)}
        document['users'] = {key: value for key, value in document['users'].items()
                             if key in ('owner', 'reviewer')}
        document['users']['reviewer']['projects'] = list(document['projects'])
        self.assertEqual(self.access.validate_policy(document), document)
        self.assertIs(self.allowed(document, name='p255', path='/srv/p255'), True)
        document['projects']['overflow'] = '/srv/overflow'
        self.assert_invalid(document)
        document = policy_document()
        document['users']['reviewer']['projects'] = ['control'] * 257
        self.assert_invalid(document)

    def test_empty_project_table_valid_but_delegate_has_no_access(self):
        document = policy_document()
        document['projects'] = {}
        for record in document['users'].values():
            record['projects'] = []
        self.assertEqual(self.access.validate_policy(document), document)
        self.assertIs(self.allowed(document), False)
        self.assertIs(self.allowed(document, principal='owner'), True)

    def test_supported_operations_for_owner_and_explicit_delegate(self):
        for principal in ('owner', 'reviewer'):
            for operation in OPERATIONS:
                with self.subTest(principal=principal, operation=operation):
                    self.assertIs(self.allowed(policy_document(), principal=principal,
                                               operation=operation), True)

    def test_unsupported_operations_fail_for_every_principal(self):
        for principal in ('owner', 'reviewer'):
            for operation in ('cancel', 'start', 'shell', 'approve', 'reject',
                              'accept', 'VIEW', ' view', '', None, 1, [], {}):
                with self.subTest(principal=principal, operation=operation):
                    self.assertIs(self.allowed(policy_document(), principal=principal,
                                               operation=operation), False)

    def test_unknown_disabled_and_empty_principals_fail(self):
        for principal in ('unknown', 'disabled', 'empty', 'Owner', 'REVIEWER',
                          '', None, 1, [], {}):
            for operation in OPERATIONS:
                with self.subTest(principal=principal, operation=operation):
                    self.assertIs(self.allowed(policy_document(), principal=principal,
                                               operation=operation), False)

    def test_project_authorization_matrix_has_no_root_or_prefix_inheritance(self):
        cases = [('control', '/srv/control', True),
                 ('toolkit', '/srv/toolkit', False),
                 ('same-root', '/srv/control', False),
                 ('renamed-control', '/srv/control', False),
                 ('Control', '/srv/control', False),
                 ('control', '/srv/rebound', False),
                 ('control', '/srv/control/subdir', False),
                 ('control', '/srv/control-copy', False),
                 ('control', '/srv', False),
                 ('control', '/SRV/control', False)]
        for name, path, expected in cases:
            for operation in OPERATIONS:
                with self.subTest(name=name, path=path, operation=operation):
                    self.assertIs(self.allowed(policy_document(), name=name, path=path,
                                               operation=operation), expected)

    def test_owner_authorizes_valid_unpinned_project_tuple(self):
        document = policy_document()
        for name, path in [('unregistered', '/srv/unregistered'),
                           ('same-root', '/srv/other'), ('工具 team', '/srv/工具')]:
            for operation in OPERATIONS:
                self.assertIs(self.allowed(document, principal='owner', name=name,
                                           path=path, operation=operation), True)
                self.assertIs(self.allowed(document, name=name, path=path,
                                           operation=operation), False)

    def test_malformed_project_context_denies_owner_too(self):
        cases = [(None, '/srv/control'), ('', '/srv/control'),
                 ([], '/srv/control'), (1, '/srv/control'),
                 (' control', '/srv/control'), ('control ', '/srv/control'),
                 ('*', '/srv/control'), ('a\x00b', '/srv/control'),
                 ('a' * 129, '/srv/control'), ('control', None),
                 ('control', []), ('control', 1), ('control', ''),
                 ('control', '/'), ('control', 'srv/control'),
                 ('control', '/srv/control/'), ('control', '/srv/./control'),
                 ('control', '/srv//control'), ('control', '//srv/control'),
                 ('control', '/srv/../control'), ('control', '/srv/a\x7fb'),
                 ('control', '/' + 'a' * 4096)]
        for name, path in cases:
            for principal in ('owner', 'reviewer'):
                with self.subTest(name=name, path=path, principal=principal):
                    self.assertIs(self.allowed(policy_document(), principal=principal,
                                               name=name, path=path), False)

    def test_invalid_policy_never_becomes_owner_allow(self):
        malformed = [None, [], True, {}, policy_document()]
        malformed[-1]['users']['disabled']['auth_epoch'] = True
        unknown_field = policy_document()
        unknown_field['unexpected'] = 'synthetic-rejected-value'
        malformed.append(unknown_field)
        for document in malformed:
            for principal in ('owner', 'reviewer'):
                for operation in OPERATIONS:
                    self.assertIs(self.allowed(document, principal=principal,
                                               operation=operation), False)

    def test_error_messages_do_not_echo_rejected_document_values(self):
        canary = 'SYNTHETIC-DOCUMENT-CANARY-7d92'
        documents = [canary, {'unknown': canary}]
        for field in ('owner', 'version'):
            document = policy_document()
            document[field] = canary
            documents.append(document)
        document = policy_document()
        document['projects']['control'] = canary
        documents.append(document)
        document = policy_document()
        document['users']['reviewer']['projects'] = [canary]
        documents.append(document)
        document = policy_document()
        document['users']['reviewer']['unexpected'] = canary
        documents.append(document)
        for document in documents:
            with self.subTest(document_shape=type(document).__name__):
                with self.assertRaises(self.access.PolicyError) as caught:
                    self.access.validate_policy(document)
                self.assertNotIn(canary, str(caught.exception))
                self.assertNotIn(canary, repr(caught.exception))
                self.assertNotIn(canary, repr(caught.exception.args))

    def test_authorization_does_not_mutate_or_cache_policy(self):
        document = policy_document()
        before = copy.deepcopy(document)
        self.assertIs(self.allowed(document), True)
        self.assertIs(self.allowed(document, name='toolkit', path='/srv/toolkit'), False)
        self.assertEqual(document, before)
        document['users']['reviewer']['projects'] = ['toolkit']
        self.assertIs(self.allowed(document), False)
        self.assertIs(self.allowed(document, name='toolkit', path='/srv/toolkit'), True)
        document['users']['reviewer']['enabled'] = False
        self.assertIs(self.allowed(document, name='toolkit', path='/srv/toolkit'), False)
        document['users']['reviewer']['enabled'] = True
        document['users']['reviewer']['auth_epoch'] = 2147483647
        self.assertIs(self.allowed(document, name='toolkit', path='/srv/toolkit'), True)
        document['projects']['toolkit'] = '/srv/rebound'
        before = copy.deepcopy(document)
        self.assertIs(self.allowed(document, name='toolkit', path='/srv/toolkit'), False)
        self.assertIs(self.allowed(document, name='toolkit', path='/srv/rebound'), True)
        self.assertEqual(document, before)


if __name__ == '__main__':
    unittest.main()
