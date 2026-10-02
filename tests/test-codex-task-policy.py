"""Independent acceptance tests for CXTASK-POLICY's public contract."""
import copy
import importlib.util
import pathlib
import tempfile
import unittest
import uuid
from unittest import mock

SPEC = importlib.util.spec_from_file_location('codex_task_policy', pathlib.Path(__file__).resolve().parents[1] / 'bin' / '_codex_task_policy.py')
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class TaskPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = str(pathlib.Path(self.tmp.name).resolve())
        self.response = {
            'thread': {'id': str(uuid.uuid4()), 'cwd': self.cwd, 'ephemeral': False},
            'cwd': self.cwd, 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user',
            'model': 'private-model-marker', 'reasoningEffort': 'high',
            'sandbox': {'type': 'workspaceWrite', 'networkAccess': False,
                        'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True,
                        'writableRoots': [self.cwd]},
            'runtimeWorkspaceRoots': [self.cwd],
        }
        self.pages = [{'data': [], 'nextCursor': None}]

    def validate(self, response=None, pages=None):
        return policy.validate_task_policy(self.response if response is None else response,
                                           self.cwd, self.pages if pages is None else pages)

    def row(self, name='private-server-marker'):
        return {'name': name, 'runtimeStatus': 'disabled', 'tools': {},
                'resources': [], 'resourceTemplates': []}

    def reject(self, response=None, pages=None):
        with self.assertRaises(policy.TaskPolicyError) as caught:
            self.validate(response, pages)
        # FR-CXTASK-POLICY-05: diagnostics never echo input payloads.
        message = str(caught.exception)
        for secret in (self.cwd, 'private-server-marker', 'private-model-marker',
                       'private-tool-marker', 'private-config-marker'):
            self.assertNotIn(secret, message)

    def test_import_has_no_runtime_effects(self):
        # FR-CXTASK-POLICY-05: import cannot launch hosts or connect to RPC.
        module = importlib.util.module_from_spec(SPEC)
        with mock.patch('subprocess.Popen', side_effect=AssertionError('process started')), \
             mock.patch('subprocess.run', side_effect=AssertionError('process started')), \
             mock.patch('socket.socket', side_effect=AssertionError('RPC connection')), \
             mock.patch('os.mkdir', side_effect=AssertionError('directory created')):
            SPEC.loader.exec_module(module)

    def test_host_command_and_no_side_effects(self):
        # FR-CXTASK-POLICY-01,05
        socket = str(pathlib.Path(self.cwd) / 'nested' / 'task.sock')
        with mock.patch('subprocess.Popen', side_effect=AssertionError('process started')), \
             mock.patch('subprocess.run', side_effect=AssertionError('process started')):
            args = policy.host_argv(socket, executable='custom-codex')
        self.assertEqual(args[0], 'custom-codex')
        self.assertIn('app-server', args)
        index = args.index('--listen')
        self.assertEqual(args[index + 1], 'unix://' + socket)
        for key in ('features.plugins', 'features.remote_plugin', 'features.apps'):
            self.assertIn(key + '=false', args)
        self.assertFalse(pathlib.Path(socket).parent.exists())
        for arg in args:
            self.assertNotIn('daemon', arg)
            self.assertNotIn('model', arg)
            self.assertNotIn('effort', arg)

    def test_invalid_socket_and_cwd(self):
        # FR-CXTASK-POLICY-01
        file = pathlib.Path(self.cwd) / 'existing'
        file.touch()
        link = pathlib.Path(self.cwd) / 'link'
        link.symlink_to(file)
        for socket in ('relative.sock', '', str(file), str(link)):
            with self.subTest(socket=socket), self.assertRaises(policy.TaskPolicyError):
                policy.host_argv(socket)
        directory_link = pathlib.Path(self.cwd) / 'dirlink'
        directory_link.symlink_to(self.cwd, target_is_directory=True)
        for cwd in ('relative', '', self.cwd + '/absent', str(file), str(directory_link), self.cwd + '/.'):
            with self.subTest(cwd=cwd), self.assertRaises(policy.TaskPolicyError):
                policy.task_thread_params(cwd, [])

    def test_thread_params_and_immutability(self):
        # FR-CXTASK-POLICY-02
        names = ['alpha', 'Beta_2-x']
        original = names[:]
        params = policy.task_thread_params(self.cwd, names)
        self.assertEqual(names, original)
        for key, value in {'cwd': self.cwd, 'runtimeWorkspaceRoots': [self.cwd],
                           'ephemeral': False, 'sandbox': 'workspace-write',
                           'approvalPolicy': 'on-request', 'environments': []}.items():
            self.assertEqual(params[key], value)
        config = params['config']
        for key in ('features.plugins', 'features.remote_plugin', 'features.apps',
                    'sandbox_workspace_write.network_access'):
            self.assertIs(config[key], False)
        for key in ('sandbox_workspace_write.exclude_tmpdir_env_var',
                    'sandbox_workspace_write.exclude_slash_tmp'):
            self.assertIs(config[key], True)
        for name in names:
            self.assertIs(config['mcp_servers.' + name + '.enabled'], False)
        for key in list(params) + list(config):
            self.assertNotIn('model', key.lower())
            self.assertNotIn('effort', key.lower())
        for names in (['duplicate', 'duplicate'], ['bad.name'], ['quote"'], [''], ['x y'], ['x\n'], [None]):
            with self.subTest(names=names), self.assertRaises(policy.TaskPolicyError):
                policy.task_thread_params(self.cwd, names)

    def test_metadata_and_defaults(self):
        # FR-CXTASK-POLICY-03,05
        before = copy.deepcopy((self.response, self.pages))
        result = self.validate()
        self.assertEqual(result, {'thread_id': self.response['thread']['id'],
                                 'model': 'private-model-marker', 'reasoning_effort': 'high'})
        self.assertEqual((self.response, self.pages), before)
        self.response['reasoningEffort'] = None
        self.response['runtimeWorkspaceRoots'] = []
        del self.response['sandbox']['networkAccess']
        del self.response['sandbox']['writableRoots']
        self.assertIsNone(self.validate()['reasoning_effort'])

    def test_policy_rejections(self):
        # FR-CXTASK-POLICY-03: includes observed native readOnly.
        changes = [('sandbox', {'type': 'readOnly'}),
                   ('sandbox', {'type': 'dangerFullAccess'}),
                   ('approvalPolicy', 'never'), ('approvalsReviewer', 'auto'),
                   ('cwd', '/private-config-marker'), ('model', ''),
                   ('reasoningEffort', 3), ('runtimeWorkspaceRoots', ['/']),
                   ('runtimeWorkspaceRoots', None)]
        for key, value in changes:
            response = copy.deepcopy(self.response)
            response[key] = value
            with self.subTest(key=key, value=value):
                self.reject(response)
        for key in ('cwd', 'approvalPolicy', 'approvalsReviewer', 'model', 'reasoningEffort', 'runtimeWorkspaceRoots', 'sandbox', 'thread'):
            response = copy.deepcopy(self.response)
            del response[key]
            with self.subTest(missing=key):
                self.reject(response)
        for key, value in (('id', 'not-a-uuid'), ('id', self.response['thread']['id'].upper()),
                           ('cwd', '/'), ('ephemeral', True), ('ephemeral', None)):
            response = copy.deepcopy(self.response)
            response['thread'][key] = value
            self.reject(response)
        for key, value in (('networkAccess', True), ('networkAccess', None),
                           ('excludeTmpdirEnvVar', False), ('excludeSlashTmp', False),
                           ('writableRoots', None), ('type', None)):
            response = copy.deepcopy(self.response)
            response['sandbox'][key] = value
            self.reject(response)
        for key in ('excludeTmpdirEnvVar', 'excludeSlashTmp'):
            response = copy.deepcopy(self.response)
            del response['sandbox'][key]
            self.reject(response)

    def test_write_roots_containment_and_canonical(self):
        # FR-CXTASK-POLICY-03
        child = pathlib.Path(self.cwd) / 'child'
        child.mkdir()
        self.response['sandbox']['writableRoots'] = [str(child)]
        self.validate()
        link = pathlib.Path(self.cwd) / 'alias'
        link.symlink_to(child, target_is_directory=True)
        for root in ('/', self.cwd + '-sibling', str(link), str(child) + '/..', 'relative'):
            self.response['sandbox']['writableRoots'] = [root]
            with self.subTest(root=root):
                self.reject()

    def test_disabled_catalog_and_false_assurance(self):
        # FR-CXTASK-POLICY-04
        row = self.row()
        self.pages[0]['data'] = [row]
        self.validate()
        for status in ('failed', 'starting', 'notStarted', 'unknown', None, 'enabled'):
            row['runtimeStatus'] = status
            self.reject()
        del row['runtimeStatus']
        self.reject()
        for key, value in (('tools', {'private-tool-marker': {}}), ('resources', [{}]),
                           ('resourceTemplates', [{}]), ('pluginId', 'private-config-marker'),
                           ('toolsError', 'private-tool-marker'), ('tools', [])):
            row = self.row()
            row[key] = value
            self.reject(pages=[{'data': [row], 'nextCursor': None}])
        for key in ('name', 'tools', 'resources', 'resourceTemplates'):
            row = self.row()
            del row[key]
            self.reject(pages=[{'data': [row], 'nextCursor': None}])

    def test_catalog_pagination_corruption(self):
        # FR-CXTASK-POLICY-04
        valid = [{'data': [self.row('a')], 'nextCursor': 'cursor'},
                 {'data': [self.row('b')], 'nextCursor': None}]
        self.validate(pages=valid)
        bad = [[], [{'data': [], 'nextCursor': 'unfinished'}],
               [{'data': [], 'nextCursor': None}, {'data': [], 'nextCursor': None}],
               [{'data': [], 'nextCursor': ''}, {'data': [], 'nextCursor': None}],
               [{'data': [], 'nextCursor': 'same'}, {'data': [], 'nextCursor': 'same'}, {'data': [], 'nextCursor': None}],
               [{'data': [self.row()], 'nextCursor': 'x'}, {'data': [self.row()], 'nextCursor': None}],
               [{'data': { }, 'nextCursor': None}], [{'data': []}],
               [{'data': [None], 'nextCursor': None}], [{'data': [], 'nextCursor': 1}],
               [{'data': [], 'nextCursor': str(i)} for i in range(100)] + [{'data': [], 'nextCursor': None}]]
        for pages in bad:
            with self.subTest(pages=pages):
                self.reject(pages=pages)


if __name__ == '__main__':
    unittest.main()
