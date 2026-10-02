#!/usr/bin/env python3
"""Blind CXRUN public controller tests. Native boundaries only; private IO is real."""
import copy
from collections import deque
import socket
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
try:
    runtime_module = importlib.import_module('_codex_task_runtime')
except ModuleNotFoundError as exc:
    if exc.name != '_codex_task_runtime':
        raise
    runtime_module = None

PINS = {
    'codex': '12eb3e81114588aca3b7998f4f19e8997b056aca08e57a7ca7c8a3ec8c652aad',
    'code_mode_host': '37cab1584302611e9936902219640ab5e7a79fcfccd2504c6e85ea8cb97d0e10',
    'bwrap': '01fb705f067bd5365b63d8ad2323a61c8d007733ca5e649437e086f3fb9935d8',
    'rg': 'e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849',
}
BUDGET = {'memory_max_mb': 1024, 'tasks_max': 64, 'cpu_quota_percent': 100}
INC = '0123456789abcdef0123456789abcdef'


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    path.chmod(0o600)


class RuntimeContract(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime_module,
            'INV-CXRUN-02: public Codex TASK controller has no implementation; '
            'static admission and fail-closed native execution are required')
        self.Runtime = runtime_module.CodexTaskRuntime
        self.Error = runtime_module.RuntimeError
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.agent = self.root / 'agents/taskone'
        self.state = self.root / 'private'
        self.project = self.root / 'project'
        self.release = self.root / 'release'
        for directory in (self.agent / 'questions', self.agent / 'inbox/inflight',
                          self.agent / 'inbox/done', self.agent.parent / '.locks',
                          self.state, self.project, self.release):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path in self.root.rglob('*'):
            if path.is_dir():
                path.chmod(0o700)
        for path in (self.agent / '.lock', self.agent / 'done.lock',
                     self.agent / 'questions/.lock', self.agent / 'inbox/.inbox.lock',
                     self.agent.parent / '.locks/new-task-taskone.lock'):
            path.touch(mode=0o600)
        self.git_env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.git_env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                            GIT_TERMINAL_PROMPT='0')
        self.git('init', cwd=self.project)
        self.git('config', 'user.name', 'Fixture', cwd=self.project)
        self.git('config', 'user.email', 'fixture@example.invalid', cwd=self.project)
        (self.project / 'tracked.txt').write_text('baseline\n')
        self.git('add', 'tracked.txt', cwd=self.project)
        self.git('commit', '-m', 'fixture baseline', cwd=self.project)
        self.base = self.git('rev-parse', 'HEAD', cwd=self.project).strip()
        self.git('worktree', 'add', '-b', 'task/taskone-' + INC[:8],
                 str(self.agent / 'work'), cwd=self.project)
        self.control = dict(schema=1, seq=0, incarnation=INC, generation=7,
            desired='running', hold=None, mission_base=self.base,
            acceptance={'status': 'pending'},
            lease={'state': 'active', 'start_attempt_id': 'attempt-1'},
            session_id=None, attention=None, handoff=None,
            codex_state_id=str(uuid.uuid4()))
        save(self.agent / 'control.json', self.control)
        self.spec = dict(engine='codex', type='event', runtime='drain',
                         workspace='worktree', project=str(self.project))
        self.write_spec()
        save(self.agent / 'inbox/inflight/event-1.json', {'key': 'event-1', 'meta': {}})
        self.executable = self.release / 'codex'
        self.companions = {k: str(self.release / k) for k in ('code_mode_host', 'bwrap', 'rg')}
        for path in [self.executable] + [Path(v) for v in self.companions.values()]:
            path.write_text('#!/bin/sh\nexit 93\n')
            path.chmod(0o700)
        self.effects = []
        self.evidence = {'version': '0.160.0', 'hashes': copy.deepcopy(PINS)}

    def git(self, *args, cwd):
        return subprocess.run(['git', *args], cwd=cwd, env=self.git_env,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout

    def write_spec(self):
        save(self.agent / 'spec.yaml', self.spec)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts
                and p.name not in ('control.json',)}

    def native_forbidden(self, *args, **kwargs):
        self.effects.append(('native', args))
        self.fail('Native boundary crossed before validated runtime admission')

    def verify(self, executable, companion_paths, *, deadline):
        self.assertEqual(executable, str(self.executable))
        self.assertEqual(companion_paths, self.companions)
        return copy.deepcopy(self.evidence)

    def make(self, **changes):
        arguments = dict(state_root=str(self.state), executable=str(self.executable),
            companion_paths=copy.deepcopy(self.companions), host_budget=copy.deepcopy(BUDGET),
            adapters={'verify_release': self.verify, 'host_factory': self.native_forbidden,
                      'transport_factory': self.native_forbidden,
                      'verify_child': self.native_forbidden,
                      'read_thread_metadata': self.native_forbidden,
                      'checkpoint': self.native_forbidden, 'heartbeat': lambda *a, **k: None})
        arguments.update(changes)
        return self.Runtime(str(self.agent), **arguments)

    def refusal(self, action):
        before = self.snapshot()
        try:
            result = action()
        except self.Error:
            pass
        else:
            self.assertIn(result['outcome'], ('blocked', 'unknown'))
            for name in ('operation_id', 'thread_id', 'turn_id'):
                self.assertIsNone(result[name])
        self.assertEqual(self.effects, [])
        self.assertEqual(before, self.snapshot(), 'Refusal altered event/worktree/private artifacts')

    # INV-CXRUN-02
    def test_constructor_is_inert_and_does_not_initialize_missing_index(self):
        before = self.snapshot()
        self.make()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.effects, [])
        self.assertEqual(list(self.state.iterdir()), [])

    def test_real_wrong_executable_refuses_before_any_claim(self):
        controller = self.make(adapters={'host_factory': self.native_forbidden,
                                        'transport_factory': self.native_forbidden})
        original = (self.agent / 'control.json').read_bytes()
        with self.assertRaises(self.Error):
            controller.static_preflight(deadline=time.monotonic() + 2)
        self.assertEqual((self.agent / 'control.json').read_bytes(), original)
        self.assertEqual(self.effects, [])

    def test_all_four_release_hash_mismatches_refuse_without_native_effect(self):
        for key in PINS:
            with self.subTest(artifact=key):
                self.evidence['hashes'] = copy.deepcopy(PINS)
                self.evidence['hashes'][key] = '0' * 64
                with self.assertRaises(self.Error):
                    self.make().static_preflight(deadline=time.monotonic() + 2)
                self.assertEqual(self.effects, [])

    def test_release_version_and_incomplete_extra_evidence_refused(self):
        invalid = [{'version': '0.159.0', 'hashes': PINS},
                   {'version': '0.160.0', 'hashes': {'codex': PINS['codex']}},
                   {'version': '0.160.0', 'hashes': PINS, 'config': 'PRIVATE_PAYLOAD'},
                   {'version': '0.160.0', 'hashes': dict(PINS, extra='0' * 64)}]
        for evidence in invalid:
            with self.subTest(evidence=list(evidence)):
                self.evidence = evidence
                with self.assertRaises(self.Error) as caught:
                    self.make().static_preflight(deadline=time.monotonic() + 2)
                self.assertNotIn('PRIVATE_PAYLOAD', str(caught.exception))
                self.assertEqual(self.effects, [])

    def test_budget_boolean_out_of_range_missing_and_extra_refused(self):
        for key, values in {'memory_max_mb': [True, 255, 8193, '1024'],
                            'tasks_max': [False, 15, 257, 64.0],
                            'cpu_quota_percent': [True, 0, 401, None]}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    budget = dict(BUDGET, **{key: value})
                    with self.assertRaises(self.Error):
                        self.make(host_budget=budget).static_preflight(deadline=time.monotonic() + 2)
        for budget in ({}, dict(BUDGET, extra=1)):
            with self.assertRaises(self.Error):
                self.make(host_budget=budget).static_preflight(deadline=time.monotonic() + 2)
        self.assertEqual(self.effects, [])

    def test_unrecognized_adapter_or_noncallable_rejected(self):
        for adapters in ({'send': self.native_forbidden}, {'host_factory': 'module.loader'},
                         {'verify_release': None}):
            with self.subTest(adapters=list(adapters)), self.assertRaises(self.Error):
                self.make(adapters=adapters)
        self.assertEqual(self.effects, [])

    def test_profile_and_unknown_engine_refuse_without_claim(self):
        for key, values in {'engine': ['claude', 'CODEX', 'unknown', True],
                            'type': ['mission'], 'runtime': ['direct', 'handoff'],
                            'workspace': ['shared', 'project']}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    original = self.spec[key]
                    self.spec[key] = value
                    self.write_spec()
                    with self.assertRaises(self.Error):
                        self.make().static_preflight(deadline=time.monotonic() + 2)
                    self.spec[key] = original
        self.assertEqual(self.effects, [])

    def test_missing_engine_does_not_become_codex(self):
        del self.spec['engine']
        self.write_spec()
        with self.assertRaises(self.Error):
            self.make().static_preflight(deadline=time.monotonic() + 2)
        self.assertEqual(self.effects, [])

    def test_executable_symlink_and_writable_artifact_refused(self):
        original = self.executable.read_bytes()
        target = self.release / 'target'
        target.write_bytes(original)
        target.chmod(0o700)
        self.executable.unlink()
        self.executable.symlink_to(target)
        with self.assertRaises(self.Error):
            self.make().static_preflight(deadline=time.monotonic() + 2)
        self.executable.unlink()
        self.executable.write_bytes(original)
        self.executable.chmod(0o722)
        with self.assertRaises(self.Error):
            self.make().static_preflight(deadline=time.monotonic() + 2)
        self.assertEqual(self.effects, [])

    def test_companion_table_requires_exact_canonical_existing_paths(self):
        invalid = [{}, dict(self.companions, extra=str(self.executable)),
                   dict(self.companions, rg='relative'),
                   dict(self.companions, bwrap=str(self.release / 'absent'))]
        for paths in invalid:
            with self.subTest(keys=list(paths)), self.assertRaises(self.Error):
                self.make(companion_paths=paths).static_preflight(deadline=time.monotonic() + 2)
        self.assertEqual(self.effects, [])

    def test_static_errors_do_not_expose_observed_native_evidence(self):
        messages = []
        for secret in ('PRIVATE_PAYLOAD_A', 'PRIVATE_PAYLOAD_B'):
            self.evidence = {'version': secret, 'hashes': copy.deepcopy(PINS)}
            with self.assertRaises(self.Error) as caught:
                self.make().static_preflight(deadline=time.monotonic() + 2)
            messages.append(str(caught.exception))
            self.assertNotIn(secret, messages[-1])
        self.assertEqual(messages[0], messages[1])

    # INV-CXRUN-03 / INV-CXRUN-07
    def publish_registry(self):
        try:
            module = importlib.import_module('_codex_task_store')
        except ModuleNotFoundError as exc:
            if exc.name != '_codex_task_store':
                raise
            self.fail('INV-CXRUN-07: accepted operation store dependency is absent')
        staging = self.agent.parent / '.staging'
        event = json.loads((self.agent / 'inbox/inflight/event-1.json').read_text())
        (self.agent / 'inbox/inflight/event-1.json').unlink()
        self.agent.rename(staging)
        original = copy.deepcopy(self.control)
        creator = copy.deepcopy(self.control)
        creator.pop('codex_state_id')
        creator.update(generation=0, desired='paused',
                       lease={'state': 'none', 'start_attempt_id': None})
        save(staging / 'control.json', creator)
        module.CodexTaskOperationStore.initialize(str(staging), str(self.agent),
            original['codex_state_id'], state_root=str(self.state),
            deadline=time.monotonic() + 2)
        save(staging / 'control.json', original)
        staging.rename(self.agent)
        save(self.agent / 'inbox/inflight/event-1.json', event)
        return module.CodexTaskOperationStore(str(self.agent), state_root=str(self.state))

    def test_empty_complete_registry_barrier_returns_literal_true(self):
        self.publish_registry()
        self.assertIs(self.make().require_drained(deadline=time.monotonic() + 2), True)
        self.assertEqual(self.effects, [])

    def test_reconcile_empty_registry_is_idle_without_bootstrap(self):
        self.publish_registry()
        before = self.snapshot()
        result = self.make().reconcile(deadline=time.monotonic() + 2)
        self.assertEqual(set(result), {'outcome', 'operations', 'reason'})
        self.assertEqual(result['outcome'], 'idle')
        self.assertEqual(result['operations'], [])
        self.assertEqual(self.effects, [])
        self.assertEqual(self.snapshot(), before)

    def test_valid_preflight_is_fresh_evidence_and_never_claims_or_bootstraps(self):
        self.publish_registry()
        before = self.snapshot()
        original = (self.agent / 'control.json').read_bytes()
        controller = self.make()
        result = controller.static_preflight(deadline=time.monotonic() + 2)
        self.assertEqual(result, {'ready': True, 'version': '0.160.0',
            'permission_profile': 'control_task', 'release_hashes': PINS})
        result['release_hashes']['codex'] = '0' * 64
        repeated = controller.static_preflight(deadline=time.monotonic() + 2)
        self.assertEqual(repeated['release_hashes'], PINS)
        self.assertEqual(self.evidence['hashes'], PINS)
        self.assertEqual((self.agent / 'control.json').read_bytes(), original)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.effects, [])

    def test_lost_previously_initialized_index_cannot_be_recreated(self):
        self.publish_registry()
        index = self.state / self.control['codex_state_id'] / 'index.json'
        index.unlink()
        controller = self.make()
        with self.assertRaises(self.Error):
            controller.require_drained(deadline=time.monotonic() + 2)
        self.refusal(lambda: controller.execute('event-1', 7, 'attempt-1',
                                                deadline=time.monotonic() + 2))
        self.assertFalse(index.exists())

    def test_corrupt_registry_blocks_barrier_and_preserves_corruption(self):
        self.publish_registry()
        index = self.state / self.control['codex_state_id'] / 'index.json'
        for raw in ('{"schema":1,"schema":2}', '{"schema":NaN}', '{broken'):
            index.write_text(raw)
            with self.assertRaises(self.Error):
                self.make().require_drained(deadline=time.monotonic() + 2)
            self.assertEqual(index.read_text(), raw)
            self.assertEqual(self.effects, [])

    def discovery_fixture(self, *, config_failure=False, invalid_names=False, second_launch_failure=False, native_mode=None, child_mismatch=None, retained_cell=False):
        from _codex_task_host import HostSnapshot
        from _codex_task_profile import sealed_overrides
        case = self
        hosts = []
        calls = []
        order = []
        thread_id = str(uuid.uuid4())
        native_path = self.root / 'native-sessions/session.jsonl'
        native_path.parent.mkdir(mode=0o700)
        history = []
        checkpoint_calls = []
        from _codex_task_files import CodexTaskFiles
        from _codex_task_bridge import dynamic_tools
        descriptors = CodexTaskFiles.dynamic_tools() + dynamic_tools()
        for descriptor in descriptors:
            descriptor['type'] = 'function'
            descriptor['deferLoading'] = False
        registry = ['apply_patch', 'clock__curr_time', 'task_read', 'task_search', 'task_list', 'task_ask', 'task_done']

        def thread():
            return dict(id=thread_id, cwd=str(case.agent / 'work'), ephemeral=False,
                path=str(native_path), historyMode='legacy', model='inherited-model',
                reasoningEffort=None, status={'type': 'idle'}, turns=copy.deepcopy(history),
                environments=[{'environmentId': 'local', 'cwd': str(case.agent / 'work'),
                               'runtimeWorkspaceRoots': [str(case.agent / 'work')]}])

        class Host:
            def __init__(self, directory, incarnation, cwd, executable, argv_factory, budget):
                self.directory = Path(directory)
                self.incarnation = incarnation
                self.cwd = cwd
                self.executable = executable
                self.argv_factory = argv_factory
                self.budget = copy.deepcopy(budget)
                self.token = str(uuid.uuid4())
                self.unit = 'cctask-' + self.token + '.service'
                self.socket = str(self.directory / 'server.sock')
                self.invocation = uuid.uuid4().hex
                self.phase = 'prepared'
                self.starts = 0
                self.aborts = 0
                self.sock = None

            def journal(self):
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                save(self.directory / 'journal.json', dict(schema=1,
                    task_incarnation=self.incarnation, cwd=self.cwd,
                    executable=self.executable, unit=self.unit, token=self.token,
                    socket=self.socket, phase=self.phase, invocation_id=self.invocation,
                    socket_identity=None))

            def snapshot(self):
                return HostSnapshot(self.unit, self.phase, self.invocation,
                    12345 if self.phase == 'running' else None,
                    self.socket, self.phase == 'running')

            def start(self, *, deadline):
                index = json.loads((case.state / case.control['codex_state_id'] / 'index.json').read_text())
                records = [r for r in index['operations'].values()
                           if r['host_state_dir'] == str(self.directory)]
                case.assertEqual(len(records), 1)
                case.assertIs(records[0]['launch_reserved'], True)
                case.assertEqual(self.budget, BUDGET)
                case.assertEqual(self.incarnation, str(uuid.UUID(hex=INC)))
                self.starts += 1
                case.assertEqual(self.starts, 1)
                argv = self.argv_factory(self.socket, executable=self.executable)
                case.assertEqual(argv[:4], [self.executable, 'app-server', '--listen', 'unix://' + self.socket])
                case.assertFalse(any(x.startswith('model=') or x.startswith('model_reasoning_effort=') for x in argv))
                if second_launch_failure and len(hosts) == 2:
                    self.journal()
                    order.append('uncertain_launch')
                    raise ConnectionError('PRIVATE_NATIVE_ERROR')
                self.phase = 'running'
                self.journal()
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.bind(self.socket)
                case.addCleanup(self.sock.close)
                order.append('host_start')
                return self.snapshot()

            def inspect(self, *, deadline):
                return self.snapshot()

            def abort(self, *, deadline, guard):
                with guard(self.incarnation, deadline=deadline) as permitted:
                    case.assertIs(permitted, True)
                    index = json.loads((case.state / case.control['codex_state_id'] / 'index.json').read_text())
                    record = next(r for r in index['operations'].values()
                                  if r['host_state_dir'] == str(self.directory))
                    projection = json.loads((case.agent / 'inbox/inflight' / (record['event_key'] + '.json')).read_text())
                    case.assertEqual(projection['meta']['codex_operation']['status'], 'revoked')
                    self.aborts += 1
                    if retained_cell and len(hosts) == 2:
                        order.append('retained_cell_not_drained')
                        return self.snapshot()
                    self.phase = 'stopped'
                    self.journal()
                    order.append('host_abort')
                    return self.snapshot()

            def stop(self, *, deadline, quiescent=False):
                case.assertIs(quiescent, True)
                self.phase = 'stopped'
                self.journal()
                order.append('host_stop')
                return self.snapshot()

        def factory(directory, incarnation, cwd, *, executable, argv_factory, budget, clock):
            host = Host(directory, incarnation, cwd, executable, argv_factory, budget)
            hosts.append(host)
            return host

        class Transport:
            def __init__(self):
                self.events = deque()
                self.closed = False

            def call(self, method, params, *, deadline):
                calls.append((method, copy.deepcopy(params)))
                order.append(method)
                if method == 'config/read':
                    case.assertEqual(params, {'cwd': str(case.agent / 'work'), 'includeLayers': False})
                    if config_failure:
                        raise ConnectionError('PRIVATE_NATIVE_ERROR')
                    flat = sealed_overrides(str(case.agent / 'work'), [] if len(hosts) == 1 else ['inventory'])
                    config = {}
                    for key, value in flat.items():
                        node = config
                        parts = key.split('.')
                        for part in parts[:-1]:
                            node = node.setdefault(part, {})
                        node[parts[-1]] = copy.deepcopy(value)
                    config['mcp_servers'] = {'invalid.name' if invalid_names else 'inventory': {'enabled': len(hosts) == 1}}
                    return {'config': config, 'origins': {}, 'layers': None}
                if method == 'initialize':
                    return {'userAgent': 'offline fixture'}
                if native_mode is not None:
                    if method == 'mcpServerStatus/list':
                        return {'data': [{'name': 'inventory', 'runtimeStatus': 'disabled',
                            'tools': {}, 'resources': [], 'resourceTemplates': []}], 'nextCursor': None}
                    if method in ('thread/start', 'thread/resume'):
                        if method == 'thread/start':
                            case.assertEqual(params['dynamicTools'], descriptors)
                            case.assertNotIn('model', params)
                            case.assertNotIn('reasoningEffort', params)
                        else:
                            case.assertNotIn('dynamicTools', params)
                            case.assertNotIn('environments', params)
                            case.assertEqual(params['threadId'], thread_id)
                        return {'thread': thread(), 'cwd': str(case.agent / 'work'),
                            'runtimeWorkspaceRoots': [str(case.agent / 'work')],
                            'model': 'inherited-model', 'reasoningEffort': None,
                            'approvalPolicy': 'on-request', 'approvalsReviewer': 'user',
                            'activePermissionProfile': {'id': 'control_task', 'extends': None},
                            'sandbox': {'type': 'workspaceWrite', 'networkAccess': False,
                                'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True,
                                'writableRoots': [str(case.agent / 'work')]}}
                    if method == 'thread/read':
                        case.assertIs(params['includeTurns'], True)
                        return {'thread': thread()}
                    if method == 'turn/start':
                        case.assertEqual(set(params), {'threadId', 'clientUserMessageId', 'input'})
                        text = params['input'][0]['text']
                        turn_id = str(uuid.uuid4())
                        created = {'id': turn_id, 'itemsView': 'full', 'status': 'completed',
                            'error': None, 'startedAt': 1, 'completedAt': 2, 'durationMs': None,
                            'items': [{'type': 'userMessage', 'id': str(uuid.uuid4()),
                                'clientId': params['clientUserMessageId'],
                                'content': [{'type': 'text', 'text': text, 'textElements': []}]}]}
                        history.append(created)
                        call_id = str(uuid.uuid4())
                        diagnostic = len(hosts) == 2
                        names = registry + (['exec_command'] if native_mode == 'extra_registry' else [])
                        if native_mode == 'final_prose_registry':
                            created['items'].append({'type': 'agentMessage', 'id': str(uuid.uuid4()),
                                'text': json.dumps(sorted(registry)), 'phase': 'final', 'memoryCitation': None})
                        else:
                            self.events.extend([
                                {'method': 'rawResponseItem/completed', 'params': {
                                    'threadId': thread_id, 'turnId': turn_id, 'item': {
                                        'type': 'custom_tool_call', 'call_id': call_id,
                                        'name': 'exec', 'input': 'text(ALL_TOOLS.map(t=>t.name).sort())'}}},
                                {'method': 'rawResponseItem/completed', 'params': {
                                    'threadId': thread_id, 'turnId': turn_id, 'item': {
                                        'type': 'custom_tool_call_output',
                                        'call_id': 'foreign' if native_mode == 'uncorrelated_registry' else call_id,
                                        'output': 'Script completed\nOutput:\n' + json.dumps(sorted(names))}}}])
                        if diagnostic and native_mode == 'bootstrap_dirty':
                            (case.agent / 'work/tracked.txt').write_text('unexpected bootstrap edit\n')
                        if diagnostic and native_mode == 'bootstrap_ask':
                            self.events.append({'id': 7, 'method': 'item/tool/call', 'params': {
                                'threadId': thread_id, 'turnId': turn_id, 'callId': 'bootstrap-ask',
                                'tool': 'task_ask', 'arguments': {'question': 'Forbidden bootstrap question?'},
                                'namespace': None}})
                        self.events.append({'method': 'turn/completed', 'params': {
                            'threadId': thread_id, 'turn': copy.deepcopy(created)}})
                        save(native_path, {'type': 'session_meta', 'payload': {
                            'id': thread_id, 'cwd': str(case.agent / 'work'), 'cli_version': '0.160.0',
                            'history_mode': 'legacy', 'roots': [str(case.agent / 'work')],
                            'dynamic_tools': copy.deepcopy(descriptors)}})
                        order.append('callbacks_queued_before_start_response')
                        return {'turn': copy.deepcopy(created)}
                    if method == 'turn/interrupt':
                        return {}
                case.fail('Discovery performed session/MCP/model RPC: ' + method)

            def bind_operation(self, owned_thread_id, turn_id):
                case.assertIsNotNone(native_mode, 'Threadless discovery acquired callback authority')
                case.assertEqual(owned_thread_id, thread_id)
                order.append('bind_operation')

            def receive(self, *, deadline):
                if self.events:
                    return self.events.popleft()
                raise TimeoutError('offline fixture empty')

            def reply_dynamic(self, *args, **kwargs):
                case.fail('Threadless discovery answered TASK callback')

            def reply_approval(self, *args, **kwargs):
                case.fail('Threadless discovery answered approval')

            def reply_user_input(self, *args, **kwargs):
                case.fail('Threadless discovery answered user input')

            def close(self):
                self.closed = True
                order.append('transport_close')

        def transport_factory(endpoint, *, deadline, clock):
            case.assertEqual(endpoint, hosts[-1].socket)
            return Transport()

        def child(snapshot, companion_paths, *, deadline):
            host = next(h for h in hosts if h.unit == snapshot.unit)
            proof = dict(pid=12346, start_ticks=100, uid=os.getuid(),
                executable=companion_paths['code_mode_host'], sha256=PINS['code_mode_host'],
                control_group='/fixture/owned', invocation_id=host.invocation)
            if child_mismatch is not None and len(hosts) > 1:
                proof[child_mismatch[0]] = child_mismatch[1]
            return proof

        def metadata(path, owned_id, cwd, *, deadline):
            case.assertEqual(path, str(native_path))
            case.assertEqual(owned_id, thread_id)
            case.assertEqual(cwd, str(case.agent / 'work'))
            decoded = json.loads(native_path.read_text())['payload']
            retained = copy.deepcopy(decoded['dynamic_tools'])
            if native_mode == 'descriptor_loss':
                retained.pop()
            if native_mode == 'descriptor_true':
                retained[0]['deferLoading'] = True
            digest = hashlib.sha256(json.dumps(retained, sort_keys=True,
                separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            return dict(id=owned_id, cwd=cwd, cli_version='0.160.0', history_mode='legacy',
                roots=[cwd], dynamic_tools=retained, dynamic_tools_digest=digest)

        def checkpoint(agent_dir, operation_id, event_key, summary, prepared_receipt, *, deadline):
            case.assertEqual(agent_dir, str(case.agent))
            index = json.loads((case.state / case.control['codex_state_id'] / 'index.json').read_text())
            case.assertTrue(all(r['status'] in ('revoked', 'finished') and
                (r['drain_evidence'] is not None or not r['launch_reserved'])
                for r in index['operations'].values()))
            checkpoint_calls.append(copy.deepcopy(prepared_receipt))
            order.append('checkpoint_prepare' if prepared_receipt is None else 'checkpoint_commit')
            head = case.git('rev-parse', 'HEAD', cwd=case.agent / 'work').strip()
            tree = case.git('rev-parse', 'HEAD^{tree}', cwd=case.agent / 'work').strip()
            if prepared_receipt is None:
                return dict(branch='task/taskone-' + INC[:8], parent_sha=head,
                    tree_sha=tree, commit_sha=None, trailer='Codex-Task-Operation: ' + operation_id,
                    intent_trailer=None, no_commit=False)
            receipt = copy.deepcopy(prepared_receipt)
            receipt.update(commit_sha=head, no_commit=True)
            return receipt

        controller = self.make(adapters={'verify_release': self.verify,
            'host_factory': factory, 'transport_factory': transport_factory,
            'verify_child': child, 'read_thread_metadata': metadata if native_mode is not None else self.native_forbidden,
            'checkpoint': checkpoint if native_mode is not None else self.native_forbidden, 'heartbeat': lambda *a, **k: None})
        return controller, hosts, calls, order

    def test_config_discovery_uncertain_reply_never_starts_session_or_retries(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(config_failure=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('unknown', 'blocked'))
        self.assertEqual([m for m, p in calls if m == 'config/read'], ['config/read'])
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].starts, 1)
        before = len(calls)
        controller.reconcile(deadline=time.monotonic() + 2)
        self.assertEqual(len(calls), before)
        self.assertEqual(len(hosts), 1)
        self.assertFalse((self.agent / 'done.json').exists())
        self.assertEqual(list((self.agent / 'questions').glob('*.json')), [])

    def test_invalid_discovery_mcp_name_drains_without_thread_or_catalog(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(invalid_names=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].starts, 1)
        self.assertEqual(hosts[0].aborts, 1)
        self.assertLess(order.index('transport_close'), order.index('host_abort'))
        self.assertTrue(all(m in ('initialize', 'config/read') for m, p in calls))
        index = json.loads((self.state / self.control['codex_state_id'] / 'index.json').read_text())
        self.assertEqual(len(index['operations']), 1)
        record = next(iter(index['operations'].values()))
        self.assertEqual(record['status'], 'revoked')
        self.assertIs(record['start_reserved'], False)
        self.assertIsNone(record['thread_id'])
        self.assertIsNone(record['turn_id'])
        self.assertIs(record['drain_evidence']['drained'], True)
        original = json.loads((self.agent / 'inbox/inflight/event-1.json').read_text())
        self.assertNotIn('codex_operation', original['meta'])

    def test_successful_discovery_archives_revoked_threadless_cancelled_tombstone(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(second_launch_failure=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[0].aborts, 1)
        self.assertEqual(hosts[1].starts, 1)
        self.assertLess(order.index('host_abort'), order.index('uncertain_launch'))
        discovery = list((self.agent / 'inbox/done').glob('codex-config-discovery-*.json'))
        self.assertEqual(len(discovery), 1)
        envelope = json.loads(discovery[0].read_text())
        self.assertEqual(envelope['meta']['internal'], 'codex_config_discovery')
        self.assertEqual(envelope['meta']['purpose'], 'config_discovery')
        self.assertEqual(envelope['meta']['owner_event_key'], 'event-1')
        self.assertEqual(envelope['meta']['history'][-1]['outcome'], 'cancelled')
        projection = envelope['meta']['codex_operation']
        self.assertEqual(projection['status'], 'revoked')
        self.assertIsNone(projection['thread_id'])
        self.assertIsNone(projection['turn_id'])
        self.assertIs(projection['start_reserved'], False)
        index = json.loads((self.state / self.control['codex_state_id'] / 'index.json').read_text())
        record = index['operations'][projection['operation_id']]
        self.assertIsNone(record['terminal_evidence'])
        self.assertIs(record['drain_evidence']['drained'], True)
        self.assertTrue(all(m in ('initialize', 'config/read') for m, p in calls))
        self.assertFalse((self.agent / 'done.json').exists())

    def test_bootstrap_registry_requires_exact_correlated_raw_output(self):
        for mode in ('extra_registry', 'final_prose_registry', 'uncorrelated_registry'):
            with self.subTest(mode=mode):
                # Each execute fixture owns a separate TASK and immutable store binding.
                case = RuntimeContract(methodName='test_constructor_is_inert_and_does_not_initialize_missing_index')
                case.setUp()
                try:
                    case.publish_registry()
                    controller, hosts, calls, order = case.discovery_fixture(native_mode=mode)
                    result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
                    self.assertIn(result['outcome'], ('blocked', 'unknown'))
                    self.assertEqual(len(hosts), 2)
                    self.assertEqual(sum(m == 'turn/start' for m, p in calls), 1)
                    self.assertEqual(sum(m == 'thread/resume' for m, p in calls), 0)
                    self.assertTrue(all(h.phase == 'stopped' for h in hosts))
                    self.assertNotIn('checkpoint_commit', order)
                    self.assertEqual(list((case.agent / 'questions').glob('*.json')), [])
                    self.assertFalse((case.agent / 'done.json').exists())
                finally:
                    case.doCleanups()

    def test_bootstrap_task_ask_never_creates_question_authority(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='bootstrap_ask')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(list((self.agent / 'questions').glob('*.json')), [])
        self.assertFalse((self.agent / 'done.json').exists())
        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[-1].aborts, 1)
        self.assertNotIn('checkpoint_commit', order)

    def test_bootstrap_unexpected_edit_is_preserved_and_refuses_ordinary_turn(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='bootstrap_dirty')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'unexpected bootstrap edit\n')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip(), self.base)
        self.assertEqual(sum(m == 'turn/start' for m, p in calls), 1)
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertNotIn('checkpoint_commit', order)

    def test_child_identity_mismatch_never_grants_task_authority(self):
        for field, value in (('pid', True), ('start_ticks', 0), ('uid', os.getuid() + 1),
                             ('executable', str(self.executable)), ('sha256', '0' * 64),
                             ('invocation_id', 'f' * 32)):
            with self.subTest(field=field):
                case = RuntimeContract(methodName='test_constructor_is_inert_and_does_not_initialize_missing_index')
                case.setUp()
                try:
                    case.publish_registry()
                    controller, hosts, calls, order = case.discovery_fixture(
                        native_mode='normal', child_mismatch=(field, value))
                    result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
                    self.assertIn(result['outcome'], ('blocked', 'unknown'))
                    self.assertLessEqual(sum(m == 'turn/start' for m, p in calls), 1)
                    self.assertNotIn('checkpoint_commit', order)
                    self.assertFalse((case.agent / 'done.json').exists())
                finally:
                    case.doCleanups()

    def test_terminal_registry_turn_with_retained_cell_cannot_checkpoint(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='normal', retained_cell=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[-1].phase, 'running')
        self.assertIn('retained_cell_not_drained', order)
        self.assertNotIn('checkpoint_prepare', order)
        self.assertNotIn('checkpoint_commit', order)
        self.assertEqual(sum(m == 'turn/start' for m, p in calls), 1)
        with self.assertRaises(self.Error):
            controller.require_drained(deadline=time.monotonic() + 2)

    def test_old_attempt_unknown_launch_blocks_current_generation(self):
        store = self.publish_registry()
        old = store.prepare('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        with store.launch_guard(old['operation_id'], deadline=time.monotonic() + 2):
            pass  # Crash after reserved launch and before any trustworthy host journal.
        self.control.update(generation=8, lease={'state': 'active', 'start_attempt_id': 'attempt-2'})
        save(self.agent / 'control.json', self.control)
        save(self.agent / 'inbox/inflight/event-2.json', {'key': 'event-2', 'meta': {}})
        with self.assertRaises(self.Error):
            self.make().require_drained(deadline=time.monotonic() + 2)
        self.refusal(lambda: self.make().execute('event-2', 8, 'attempt-2',
                                                deadline=time.monotonic() + 2))
        index = json.loads((self.state / self.control['codex_state_id'] / 'index.json').read_text())
        self.assertEqual(set(index['operations']), {old['operation_id']})

    def test_idle_reconcile_cannot_create_task_question_or_done_evidence(self):
        self.publish_registry()
        controller = self.make()
        for unused in range(2):
            self.assertEqual(controller.reconcile(deadline=time.monotonic() + 2)['outcome'], 'idle')
        self.assertEqual(list((self.agent / 'questions').glob('*.json')), [])
        self.assertFalse((self.agent / 'done.json').exists())
        self.assertEqual(self.effects, [])

    def test_registry_identity_drift_cannot_authorize_barrier(self):
        self.publish_registry()
        self.control['incarnation'] = 'f' * 32
        save(self.agent / 'control.json', self.control)
        with self.assertRaises(self.Error):
            self.make().require_drained(deadline=time.monotonic() + 2)
        self.assertEqual(self.effects, [])

    def test_registry_symlink_and_hardlink_refuse_without_modifying_target(self):
        self.publish_registry()
        index = self.state / self.control['codex_state_id'] / 'index.json'
        target = self.state / 'sentinel'
        target.write_bytes(index.read_bytes())
        target.chmod(0o600)
        baseline = target.read_bytes()
        index.unlink()
        index.symlink_to(target)
        with self.assertRaises(self.Error):
            self.make().require_drained(deadline=time.monotonic() + 2)
        self.assertEqual(target.read_bytes(), baseline)
        index.unlink()
        os.link(target, index)
        with self.assertRaises(self.Error):
            self.make().require_drained(deadline=time.monotonic() + 2)
        self.assertEqual(target.read_bytes(), baseline)
        self.assertEqual(self.effects, [])

    def test_prepared_not_launched_operation_revokes_without_host_launch(self):
        store = self.publish_registry()
        operation = store.prepare('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        result = self.make().revoke_and_drain('recovery', deadline=time.monotonic() + 2)
        self.assertEqual(result, {'drained': True, 'operations': [operation['operation_id']]})
        self.assertIs(self.make().require_drained(deadline=time.monotonic() + 2), True)
        projection = json.loads((self.agent / 'inbox/inflight/event-1.json').read_text())
        self.assertEqual(projection['meta']['codex_operation']['status'], 'revoked')
        self.assertIsNone(projection['meta']['codex_operation']['thread_id'])
        self.assertIsNone(projection['meta']['codex_operation']['turn_id'])
        self.assertEqual(self.effects, [])

    def test_execute_missing_registry_does_not_initialize_or_send(self):
        self.refusal(lambda: self.make().execute('event-1', 7, 'attempt-1',
                                                deadline=time.monotonic() + 2))
        self.assertEqual(list(self.state.iterdir()), [])

    def test_missing_marker_is_not_implicit_migration(self):
        del self.control['codex_state_id']
        save(self.agent / 'control.json', self.control)
        self.refusal(lambda: self.make().execute('event-1', 7, 'attempt-1',
                                                deadline=time.monotonic() + 2))
        self.assertEqual(list(self.state.iterdir()), [])

    def test_barrier_missing_registry_refuses_even_without_live_lease(self):
        self.control['lease'] = {'state': 'none', 'start_attempt_id': None}
        save(self.agent / 'control.json', self.control)
        with self.assertRaises(self.Error):
            self.make().require_drained(deadline=time.monotonic() + 2)
        self.assertEqual(self.effects, [])

    def test_cancel_missing_registry_cannot_claim_drained(self):
        self.control['desired'] = 'stopped'
        save(self.agent / 'control.json', self.control)
        with self.assertRaises(self.Error):
            self.make().revoke_and_drain('cancel', deadline=time.monotonic() + 2)
        self.assertEqual(self.effects, [])
        self.assertTrue((self.agent / 'work/tracked.txt').exists())

    def test_reconcile_missing_registry_never_restarts_or_initializes(self):
        before = self.snapshot()
        try:
            result = self.make().reconcile(deadline=time.monotonic() + 2)
        except self.Error:
            pass
        else:
            self.assertIn(result['outcome'], ('blocked', 'unknown'))
            self.assertEqual(result['operations'], [])
        self.assertEqual(self.effects, [])
        self.assertEqual(self.snapshot(), before)

    def test_uncertain_refusal_preserves_dirty_private_changes(self):
        dirty = self.agent / 'work/tracked.txt'
        dirty.write_text('valuable unfinished change\n')
        self.refusal(lambda: self.make().execute('event-1', 7, 'attempt-1',
                                                deadline=time.monotonic() + 2))
        self.assertEqual(dirty.read_text(), 'valuable unfinished change\n')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip(), self.base)

    def test_invalid_deadlines_never_cross_native_boundary(self):
        for deadline in (True, None, float('nan'), float('inf'), time.monotonic() - 1):
            with self.subTest(deadline=deadline), self.assertRaises(self.Error):
                self.make().execute('event-1', 7, 'attempt-1', deadline=deadline)
        self.assertEqual(self.effects, [])


if __name__ == '__main__':
    unittest.main()
