#!/usr/bin/env python3
"""Blind CXRUN public controller tests. Native boundaries only; private IO is real."""
import copy
from collections import deque
import socket
import hashlib
import fcntl
import shutil
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
        self.build_fixture()

    def build_fixture(self):
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
                          self.state, self.project, self.release, self.root / 'spool/taskone'):
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
                         workspace='worktree', project=str(self.project), goal='Inspect own tracked fixture file')
        self.write_spec()
        save(self.agent / 'inbox/inflight/event-1.json', {'key': 'event-1', 'meta': {}})
        self.executable = self.release / 'codex'
        self.companions = {k: str(self.release / k) for k in ('code_mode_host', 'bwrap', 'rg')}
        for path in [self.executable] + [Path(v) for v in self.companions.values()]:
            path.write_text('#!/bin/sh\nexit 93\n')
            path.chmod(0o700)
        self.executor = (self.agent / 'inbox/.executor.lock').open('a+')
        os.chmod(self.agent / 'inbox/.executor.lock', 0o600)
        fcntl.flock(self.executor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(self.executor.close)
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
        original_control = json.loads((self.agent / 'control.json').read_text())
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
        after_control = json.loads((self.agent / 'control.json').read_text())
        for field in ('incarnation', 'generation', 'desired', 'lease', 'acceptance'):
            self.assertEqual(after_control[field], original_control[field])

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

    def test_constructor_copies_adapter_table_without_later_caller_authority(self):
        self.publish_registry()
        adapters = {'verify_release': self.verify, 'host_factory': self.native_forbidden,
                    'transport_factory': self.native_forbidden}
        controller = self.make(adapters=adapters)
        adapters['verify_release'] = lambda *a, **kw: {'version': 'malicious', 'hashes': {}}
        adapters['new_executor'] = self.native_forbidden
        result = controller.static_preflight(deadline=time.monotonic() + 2)
        self.assertEqual(result['release_hashes'], PINS)
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
        # Creator runs before the runner acquires its executor lock.
        self.executor.close()
        (self.agent / 'inbox/.executor.lock').unlink()
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
        self.executor = (self.agent / 'inbox/.executor.lock').open('a+')
        os.chmod(self.agent / 'inbox/.executor.lock', 0o600)
        fcntl.flock(self.executor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(self.executor.close)
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

    def discovery_fixture(self, *, config_failure=False, invalid_names=False, second_launch_failure=False, native_mode=None, child_mismatch=None, retained_cell=False, default_checkpoint=False, human_decision=None, approval_state=None, checkpoint_crash=False, readiness_mode=None, readiness_drift=None, bootstrap_publication_fault=False):
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
        approval_replies = []
        waiting_heartbeats = []
        transports = []
        answered = set()
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
                self.socket_identity = None
                self.socket_ready = readiness_mode is None or bool(hosts)
                self.waiting_socket = not self.socket_ready
                self.inspections = 0

            def journal(self):
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                save(self.directory / 'journal.json', dict(schema=1,
                    task_incarnation=self.incarnation, cwd=self.cwd,
                    executable=self.executable, unit=self.unit, token=self.token,
                    socket=self.socket, phase=self.phase, invocation_id=self.invocation,
                    socket_identity=copy.deepcopy(self.socket_identity)))

            def snapshot(self):
                return HostSnapshot(self.unit, self.phase, self.invocation,
                    12345 if self.phase == 'running' else None,
                    self.socket, self.phase == 'running' and self.socket_ready,
                    control_group='/fixture/owned' if self.phase == 'running' else None)

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
                socket_tmp = tempfile.TemporaryDirectory(prefix='cx-sock-', dir='/tmp')
                case.addCleanup(socket_tmp.cleanup)
                target = Path(socket_tmp.name) / 'server.sock'
                self.sock.bind(str(target))
                case.addCleanup(self.sock.close)
                Path(self.socket).symlink_to(target)
                link_stat = Path(self.socket).lstat()
                target_stat = target.stat()
                self.socket_identity = {'link': [link_stat.st_dev, link_stat.st_ino],
                    'target_path': str(target), 'target': [target_stat.st_dev, target_stat.st_ino]}
                self.journal()
                order.append('host_start')
                return self.snapshot()

            def inspect(self, *, deadline):
                self.inspections += 1
                if self.phase == 'running' and self.waiting_socket:
                    case.assertGreater(deadline, time.monotonic())
                    index_root = case.state / case.control['codex_state_id']
                    for path in (case.agent / '.lock', case.agent / 'inbox/.inbox.lock', index_root / 'store.lock'):
                        with path.open('r+') as other:
                            with case.assertRaises(BlockingIOError):
                                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    order.append('socket_wait_inspect')
                    if readiness_mode == 'never':
                        return self.snapshot()
                    self.socket_ready = True
                    self.waiting_socket = False
                    if readiness_mode == 'drift':
                        values = dict(unit=self.unit, phase='running', invocation_id=self.invocation,
                            main_pid=12345, socket=self.socket, socket_ready=True, control_group='/fixture/owned')
                        values[readiness_drift[0]] = readiness_drift[1]
                        order.append('socket_wait_identity_drift')
                        return HostSnapshot(**values)
                    order.append('socket_ready')
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
                    if self.sock is not None:
                        self.sock.close()
                    self.journal()
                    order.append('host_abort')
                    if bootstrap_publication_fault and len(hosts) == 2:
                        blocker = case.state / case.control['codex_state_id'] / 'admission.json'
                        if not blocker.exists():
                            blocker.mkdir(mode=0o700)
                            order.append('admission_publication_blocked')
                    return self.snapshot()

            def stop(self, *, deadline, quiescent=False):
                case.assertIs(quiescent, True)
                self.phase = 'stopped'
                if self.sock is not None:
                    self.sock.close()
                self.journal()
                order.append('host_stop')
                return self.snapshot()

        def factory(directory, incarnation, cwd, *, executable, argv_factory, budget, clock):
            for existing in hosts:
                if str(existing.directory) == directory:
                    return existing
            host = Host(directory, incarnation, cwd, executable, argv_factory, budget)
            hosts.append(host)
            return host

        class Transport:
            def __init__(self):
                self.events = deque()
                self.closed = False
                self.bound = None
                self.replies = []

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
                        if native_mode == 'lost_start' and history:
                            raise ConnectionError('PRIVATE_HISTORY_UNAVAILABLE')
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
                        names = registry + (['exec_command'] if native_mode == 'extra_registry' or (not diagnostic and native_mode == 'ordinary_registry_extra') else [])
                        if native_mode == 'final_prose_registry' or (not diagnostic and native_mode == 'ordinary_registry_missing'):
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
                                        'call_id': 'foreign' if native_mode == 'uncorrelated_registry' or (not diagnostic and native_mode == 'ordinary_registry_uncorrelated') else call_id,
                                        'output': 'Script completed\nOutput:\n' + json.dumps(sorted(names))}}}])
                        if not diagnostic and native_mode in ('ordinary_registry_extra', 'ordinary_registry_missing', 'ordinary_registry_uncorrelated'):
                            self.events.append({'id': 0, 'method': 'item/tool/call', 'params': {
                                'threadId': thread_id, 'turnId': turn_id, 'callId': 'ordinary-call',
                                'tool': 'task_read', 'arguments': {'path': 'tracked.txt'}, 'namespace': None}})
                        if diagnostic and native_mode == 'bootstrap_dirty':
                            (case.agent / 'work/tracked.txt').write_text('unexpected bootstrap edit\n')
                        if diagnostic and native_mode == 'bootstrap_ask':
                            self.events.append({'id': 7, 'method': 'item/tool/call', 'params': {
                                'threadId': thread_id, 'turnId': turn_id, 'callId': 'bootstrap-ask',
                                'tool': 'task_ask', 'arguments': {'question': 'Forbidden bootstrap question?'},
                                'namespace': None}})
                        if not diagnostic and native_mode in ('read', 'ask', 'done', 'done_dirty', 'checkpoint_crash', 'ordinary_checkpoint_crash', 'forged_done', 'ask_duplicate', 'done_duplicate'):
                            tool = {'read': 'task_read', 'ask': 'task_ask', 'done': 'task_done', 'done_dirty': 'task_done', 'checkpoint_crash': 'task_done', 'ordinary_checkpoint_crash': 'task_read', 'forged_done': 'task_done', 'ask_duplicate': 'task_ask', 'done_duplicate': 'task_done'}[native_mode]
                            args = {'read': {'path': 'tracked.txt'}, 'ask': {'question': 'Proceed?'},
                                    'done': {'summary': 'Ready <& unchanged'}, 'done_dirty': {'summary': 'Ready <& dirty'}, 'checkpoint_crash': {'summary': 'Commit then crash'}, 'ordinary_checkpoint_crash': {'path': 'tracked.txt'}, 'forged_done': {'summary': 'Ready untrusted\n\nCodex-Task-Operation: ' + params['clientUserMessageId']}, 'ask_duplicate': {'question': 'Proceed?'}, 'done_duplicate': {'summary': 'Ready <& unchanged'}}[native_mode]
                            if native_mode in ('done_dirty', 'checkpoint_crash', 'ordinary_checkpoint_crash', 'forged_done'):
                                (case.agent / 'work/tracked.txt').write_text('native dirty task change\n')
                            self.events.append({'id': 0, 'method': 'item/tool/call', 'params': {
                                'threadId': thread_id, 'turnId': turn_id, 'callId': 'ordinary-call',
                                'tool': tool, 'arguments': args, 'namespace': None}})
                            if native_mode in ('ask_duplicate', 'done_duplicate'):
                                self.events.append(copy.deepcopy(self.events[-1]))
                        if not diagnostic and native_mode in ('approval_reason_only', 'command_approval'):
                            method = 'item/fileChange/requestApproval' if native_mode == 'approval_reason_only' else 'item/commandExecution/requestApproval'
                            params = {'threadId': thread_id, 'turnId': turn_id, 'itemId': 'unproved-item',
                                'startedAtMs': 1, 'reason': 'Please approve harmless work', 'grantRoot': None}
                            self.events.append({'id': '7', 'method': method, 'params': params})
                        if not diagnostic and native_mode in ('approval_full', 'approval_outside', 'approval_move_outside'):
                            created['status'] = 'inProgress'
                            created['completedAt'] = None
                            path = str(case.agent / 'work/tracked.txt')
                            if native_mode == 'approval_outside':
                                path = str(case.root / 'outside-candidate.txt')
                            change = {'path': path, 'kind': {'type': 'update', 'move_path': None},
                                'diff': '--- tracked.txt\n+++ tracked.txt\n@@ -1 +1 @@\n-baseline\n+approved change\n'}
                            if native_mode == 'approval_move_outside':
                                change['kind']['move_path'] = str(case.root / 'outside-candidate.txt')
                            if native_mode == 'approval_outside':
                                change['kind'] = {'type': 'add'}
                                change['diff'] = '+outside fixture candidate\n'
                            self.events.extend([
                                {'id': 7, 'method': 'item/fileChange/requestApproval', 'params': {
                                    'threadId': thread_id, 'turnId': turn_id, 'itemId': 'full-item',
                                    'startedAtMs': 1, 'reason': 'UNTRUSTED_NATIVE_REASON', 'grantRoot': None}},
                                {'method': 'item/started', 'params': {'threadId': thread_id, 'turnId': turn_id,
                                    'item': {'id': 'full-item', 'type': 'fileChange',
                                        'changes': [change], 'status': 'inProgress'}}}])
                            if approval_state in ('resolved', 'typed_other'):
                                self.events.append({'method': 'serverRequest/resolved', 'params': {
                                    'threadId': thread_id, 'requestId': 7 if approval_state == 'resolved' else '7'}})
                            if approval_state == 'changed':
                                self.events.append({'id': 7, 'method': 'item/fileChange/requestApproval', 'params': {
                                    'threadId': thread_id, 'turnId': turn_id, 'itemId': 'full-item',
                                    'startedAtMs': 1, 'reason': 'CHANGED_UNTRUSTED_REASON', 'grantRoot': None}})
                        if created['status'] == 'completed':
                            self.events.append({'method': 'turn/completed', 'params': {
                                'threadId': thread_id, 'turn': copy.deepcopy(created)}})
                        save(native_path, {'type': 'session_meta', 'payload': {
                            'id': thread_id, 'cwd': str(case.agent / 'work'), 'cli_version': '0.160.0',
                            'history_mode': 'legacy', 'roots': [str(case.agent / 'work')],
                            'dynamic_tools': copy.deepcopy(descriptors)}})
                        order.append('callbacks_queued_before_start_response')
                        if native_mode == 'lost_start':
                            raise ConnectionError('PRIVATE_START_REPLY_LOST')
                        return {'turn': copy.deepcopy(created)}
                    if method == 'turn/interrupt':
                        return {}
                case.fail('Discovery performed session/MCP/model RPC: ' + method)

            def bind_operation(self, owned_thread_id, turn_id):
                case.assertIsNotNone(native_mode, 'Threadless discovery acquired callback authority')
                case.assertEqual(owned_thread_id, thread_id)
                self.bound = (owned_thread_id, turn_id)
                order.append('bind_operation')

            def receive(self, *, deadline):
                if self.events:
                    return self.events.popleft()
                raise TimeoutError('offline fixture empty')

            def reply_dynamic(self, request_id, result, *, thread_id, turn_id, call_id, deadline):
                case.assertEqual(self.bound, (thread_id, turn_id))
                case.assertIs(type(request_id), int)
                case.assertEqual(request_id, 0)
                case.assertEqual(call_id, 'ordinary-call')
                index_path = case.state / case.control['codex_state_id']
                index = json.loads((index_path / 'index.json').read_text())
                active = [r for r in index['operations'].values() if r['status'] == 'active']
                case.assertEqual(len(active), 1)
                case.assertEqual(active[0]['event_key'], getattr(case, 'expected_event_key', 'event-1'))
                # A reply is a guarded effect, not merely a callback result computation.
                locks = [case.agent / 'questions/.lock', case.agent / 'done.lock',
                    case.agent.parent / '.locks/new-task-taskone.lock', case.agent / '.lock',
                    case.agent / 'inbox/.inbox.lock', index_path / 'store.lock']
                for path in locks:
                    with path.open('r+') as other:
                        with case.assertRaises(BlockingIOError):
                            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if native_mode in ('ask', 'ask_duplicate'):
                    case.assertEqual(len(list((case.agent / 'questions').glob('*.json'))), 1)
                if native_mode in ('done', 'done_dirty', 'checkpoint_crash', 'done_duplicate', 'forged_done'):
                    case.assertFalse((case.agent / 'done.json').exists())
                    operation = active[0]['operation_id']
                    intent = json.loads((index_path / 'operations' / operation / 'completion.json').read_text())
                    case.assertEqual(intent['phase'], 'requested')
                case.assertEqual(self.replies, [])
                self.replies.append((request_id, copy.deepcopy(result)))
                order.append('reply_dynamic')

            def reply_approval(self, request_id, result, *, method, thread_id, turn_id, item_id, deadline):
                case.assertIn(native_mode, ('approval_full', 'approval_outside', 'approval_move_outside'))
                case.assertEqual(self.bound, (thread_id, turn_id))
                case.assertIs(type(request_id), int)
                case.assertEqual(request_id, 7)
                case.assertEqual(item_id, 'full-item')
                case.assertEqual(method, 'item/fileChange/requestApproval')
                case.assertIsNotNone(human_decision, 'Approval sent without human answer')
                case.assertEqual(result, {'decision': human_decision})
                if native_mode != 'approval_full':
                    case.assertNotEqual(result['decision'], 'accept')
                case.assertEqual(len(answered), 1)
                case.assertEqual(approval_replies, [])
                if approval_state in ('resolved', 'changed'):
                    raise RuntimeError('Captured native request is no longer replyable')
                index_path = case.state / case.control['codex_state_id']
                records = json.loads((index_path / 'index.json').read_text())['operations'].values()
                case.assertEqual(len([r for r in records if r['status'] == 'active' and
                    r['thread_id'] == thread_id and r['turn_id'] == turn_id]), 1)
                for path in (case.agent / 'questions/.lock', case.agent / 'done.lock',
                             case.agent.parent / '.locks/new-task-taskone.lock', case.agent / '.lock',
                             case.agent / 'inbox/.inbox.lock', index_path / 'store.lock'):
                    with path.open('r+') as other:
                        with case.assertRaises(BlockingIOError):
                            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                approval_replies.append((request_id, copy.deepcopy(result)))
                order.append('reply_approval')
                if approval_state == 'uncertain':
                    self.closed = True
                    raise ConnectionError('PRIVATE_UNCERTAIN_SEND')
                if result['decision'] == 'accept':
                    if approval_state in ('patch_changed', 'second_started'):
                        (case.root / 'outside-candidate.txt').write_text('native updated scope accepted\n')
                    else:
                        (case.agent / 'work/tracked.txt').write_text('approved change\n')
                history[-1].update(status='completed', completedAt=2)
                self.events.append({'method': 'turn/completed', 'params': {
                    'threadId': thread_id, 'turn': copy.deepcopy(history[-1])}})

            def reply_user_input(self, *args, **kwargs):
                case.fail('Threadless discovery answered user input')

            def close(self):
                self.closed = True
                order.append('transport_close')

        def transport_factory(endpoint, *, deadline, clock):
            case.assertEqual(endpoint, hosts[-1].socket)
            case.assertTrue(hosts[-1].socket_ready, 'Controller connected before native socket readiness')
            client = Transport()
            transports.append(client)
            return client

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
            completion = case.state / case.control['codex_state_id'] / 'operations' / operation_id / 'completion.json'
            digest = json.loads(completion.read_text())['request_digest'] if completion.exists() else hashlib.sha256(summary.encode()).hexdigest()
            if checkpoint_crash and (completion.exists() or event_key == 'event-1'):
                from _agent_worktree import git_run
                private_index = completion.parent / 'checkpoint.index'
                if prepared_receipt is None:
                    path = Path(case.git('rev-parse', '--git-path', 'index', cwd=case.agent / 'work').strip())
                    if not path.is_absolute():
                        path = case.agent / 'work' / path
                    shutil.copyfile(path, private_index)
                    private_index.chmod(0o600)
                    for args in (['read-tree', 'HEAD'], ['add', '--all']):
                        git_run(args, str(case.agent / 'work'), str(case.project),
                            index_file=str(private_index), deadline=deadline)
                    tree = git_run(['write-tree'], str(case.agent / 'work'), str(case.project),
                        index_file=str(private_index), deadline=deadline).stdout.strip()
                    return dict(branch='task/taskone-' + INC[:8], parent_sha=head,
                        tree_sha=tree, commit_sha=None, trailer='Codex-Task-Operation: ' + operation_id,
                        intent_trailer='Codex-Task-Intent: ' + digest, no_commit=False)
                if completion.exists():
                    case.assertEqual(json.loads(completion.read_text())['checkpoint'], prepared_receipt)
                case.assertIsNone(prepared_receipt['commit_sha'])
                git_run(['commit', '--no-gpg-sign', '-m', 'Isolated TASK checkpoint',
                    '-m', prepared_receipt['trailer'], '-m', prepared_receipt['intent_trailer']],
                    str(case.agent / 'work'), str(case.project),
                    index_file=str(private_index), deadline=deadline)
                order.append('actual_commit_before_controller_crash')
                raise ConnectionError('PRIVATE_COMMIT_CRASH')
            if prepared_receipt is None:
                return dict(branch='task/taskone-' + INC[:8], parent_sha=head,
                    tree_sha=tree, commit_sha=None, trailer='Codex-Task-Operation: ' + operation_id,
                    intent_trailer='Codex-Task-Intent: ' + digest, no_commit=False)
            receipt = copy.deepcopy(prepared_receipt)
            receipt.update(commit_sha=head, no_commit=True)
            return receipt

        def heartbeat(agent_dir, generation, attempt_id, phase, iteration_started_at, *, deadline):
            case.assertEqual(agent_dir, str(case.agent))
            case.assertEqual((generation, attempt_id), (7, 'attempt-1'))
            case.assertIn(phase, ('running', 'waiting_input', 'draining', 'blocked'))
            if phase != 'waiting_input':
                return None
            waiting_heartbeats.append(iteration_started_at)
            questions = list((case.agent / 'questions').glob('*.json'))
            if human_decision is None or answered or not questions:
                return None
            question = json.loads(questions[0].read_text())
            case.assertEqual(question['kind'], 'permission')
            rendered = json.dumps(question, ensure_ascii=False)
            case.assertIn('tracked.txt' if native_mode == 'approval_full' else 'outside-candidate.txt', rendered)
            case.assertNotIn('Claude', rendered)
            environment = case.git_env.copy()
            environment.update(CLAUDE_AGENTS_DIR=str(case.agent.parent),
                CLAUDE_AGENT_SPOOL_BASE=str(case.root / 'spool'),
                CLAUDE_AGENT_GENERATION='7', CLAUDE_AGENT_ATTEMPT='attempt-1')
            executable = Path(__file__).resolve().parents[1] / 'bin/claude-agent-answer'
            if native_mode == 'approval_outside':
                case.assertEqual(question['native_callback']['allowed_decisions'], ['reject'])
                before_question = questions[0].read_bytes()
                spool = case.root / 'spool/taskone'
                before_spool = {path.name: path.read_bytes() for path in spool.glob('*.json')}
                denied = subprocess.run([str(executable), str(case.agent), '--qid', question['qid'],
                    '--approve', '--by', 'fixture-programmatic-operator'], env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, timeout=1)
                case.assertNotEqual(denied.returncode, 0, 'Outside native question accepted a programmatic approve')
                case.assertEqual(questions[0].read_bytes(), before_question)
                case.assertEqual({path.name: path.read_bytes() for path in spool.glob('*.json')}, before_spool)
                order.append('outside_programmatic_approve_refused')
            if approval_state == 'receipt_blocked':
                index = json.loads((case.state / case.control['codex_state_id'] / 'index.json').read_text())
                record = next(r for r in index['operations'].values() if r['event_key'] == 'event-1')
                blocker = Path(record['host_state_dir']).parent / ('approval-' + question['qid'] + '.json')
                blocker.mkdir(mode=0o700)
                order.append('confirmed_receipt_target_blocked')
            command = [str(executable), str(case.agent), '--qid', question['qid'],
                '--approve' if human_decision == 'accept' else '--reject', '--by', 'fixture-operator']
            completed = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1)
            case.assertEqual(completed.returncode, 0, 'Genuine isolated answer writer rejected fixture')
            stored = json.loads(questions[0].read_text())
            case.assertEqual(stored['decision'], 'approve' if human_decision == 'accept' else 'reject')
            case.assertEqual(stored['answered_by'], 'fixture-operator')
            answered.add(question['qid'])
            order.append('genuine_human_answer')
            if approval_state == 'patch_changed':
                transports[-1].events.append({'method': 'item/fileChange/patchUpdated', 'params': {
                    'threadId': thread_id, 'turnId': history[-1]['id'], 'itemId': 'full-item',
                    'changes': [{'path': str(case.root / 'outside-candidate.txt'),
                        'kind': {'type': 'add'}, 'diff': '+ changed scope after question publication'}]}})
            if approval_state == 'second_started':
                transports[-1].events.append({'method': 'item/started', 'params': {
                    'threadId': thread_id, 'turnId': history[-1]['id'],
                    'item': {'id': 'full-item', 'type': 'fileChange', 'status': 'inProgress',
                        'changes': [{'path': str(case.root / 'outside-candidate.txt'),
                            'kind': {'type': 'add'}, 'diff': '+ changed complete changes after human answer'}]}}})
            if approval_state == 'revoked':
                module = importlib.import_module('_codex_task_store')
                module.CodexTaskOperationStore(str(case.agent), state_root=str(case.state)).revoke(deadline=deadline)
                order.append('authority_revoked_after_answer')
            return None

        adapters = {'verify_release': self.verify,
            'host_factory': factory, 'transport_factory': transport_factory,
            'verify_child': child, 'read_thread_metadata': metadata if native_mode is not None else self.native_forbidden,
            'checkpoint': checkpoint if native_mode is not None else self.native_forbidden, 'heartbeat': heartbeat}
        if default_checkpoint:
            adapters.pop('checkpoint')
        self.runtime_native_adapters = dict(adapters)
        controller = self.make(adapters=adapters)
        return controller, hosts, calls, order

    def test_running_host_socket_becomes_ready_by_inspection_without_relaunch(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(readiness_mode='eventual', invalid_names=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))  # Deliberate config refusal follows successful connect.
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].starts, 1)
        self.assertGreaterEqual(hosts[0].inspections, 1)
        self.assertEqual(sum(method == 'config/read' for method, params in calls), 1)
        self.assertTrue(all(method in ('initialize', 'config/read') for method, params in calls))
        self.assertLess(order.index('socket_ready'), order.index('config/read'))
        self.assertEqual(hosts[0].phase, 'stopped')
        self.assertEqual(hosts[0].aborts, 1)

    def test_never_ready_owned_socket_deadline_drains_without_connect_or_relaunch(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(readiness_mode='never')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 1)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].starts, 1)
        self.assertGreaterEqual(hosts[0].inspections, 1)
        self.assertEqual(calls, [])
        self.assertEqual(hosts[0].phase, 'stopped')
        self.assertEqual(hosts[0].aborts, 1)
        self.assertIs(controller.require_drained(deadline=time.monotonic() + 2), True)

    def test_socket_wait_identity_drift_refuses_and_drains_original_host(self):
        for field, value in (('invocation_id', 'f' * 32), ('main_pid', 12347), ('control_group', '/fixture/foreign')):
            with self.subTest(field=field):
                case = RuntimeContract(methodName='test_constructor_is_inert_and_does_not_initialize_missing_index')
                case.build_fixture()
                case.Runtime = self.Runtime
                case.Error = self.Error
                try:
                    case.publish_registry()
                    controller, hosts, calls, order = case.discovery_fixture(readiness_mode='drift', readiness_drift=(field, value))
                    result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
                    self.assertIn(result['outcome'], ('blocked', 'unknown'))
                    self.assertEqual(len(hosts), 1)
                    self.assertEqual(hosts[0].starts, 1)
                    self.assertEqual(calls, [])
                    self.assertIn('socket_wait_identity_drift', order)
                    self.assertEqual(hosts[0].phase, 'stopped')
                    self.assertEqual(hosts[0].aborts, 1)
                    journal = json.loads((hosts[0].directory / 'journal.json').read_text())
                    self.assertEqual(journal['invocation_id'], hosts[0].invocation)
                    self.assertNotEqual(journal['invocation_id'], 'f' * 32)
                finally:
                    case.doCleanups()

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
                             ('invocation_id', 'f' * 32), ('control_group', '/fixture/foreign')):
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

    def test_ordinary_read_callback_is_guarded_after_start_response_and_all_host_drain(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='read')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
        self.assertEqual(result['outcome'], 'ran')
        self.assertEqual(len(hosts), 3)
        self.assertEqual(sum(m == 'turn/start' for m, p in calls), 2)
        self.assertEqual(sum(m == 'thread/resume' for m, p in calls), 1)
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertLess(order.index('bind_operation'), order.index('reply_dynamic'))
        self.assertLess(order.index('reply_dynamic'), len(order) - 1 - order[::-1].index('host_abort'))
        self.assertLess(len(order) - 1 - order[::-1].index('host_abort'),
                        len(order) - 1 - order[::-1].index('checkpoint_commit'))
        self.assertIs(controller.require_drained(deadline=time.monotonic() + 2), True)

    def test_task_ask_callback_publishes_real_question_then_drains_and_checkpoints(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='ask')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
        self.assertEqual(result['outcome'], 'asked')
        questions = list((self.agent / 'questions').glob('*.json'))
        self.assertEqual(len(questions), 1)
        question = json.loads(questions[0].read_text())
        self.assertEqual(question['question'], 'Proceed?')
        self.assertEqual(question['status'], 'open')
        self.assertFalse((self.agent / 'done.json').exists())
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertLess(order.index('reply_dynamic'), len(order) - 1 - order[::-1].index('host_abort'))
        self.assertLess(len(order) - 1 - order[::-1].index('host_abort'),
                        len(order) - 1 - order[::-1].index('checkpoint_commit'))
        before = len(calls)
        recovered = controller.reconcile(deadline=time.monotonic() + 2)
        self.assertIn(recovered['outcome'], ('idle', 'recovered', 'blocked'))
        self.assertEqual(len(calls), before)
        self.assertEqual(len(list((self.agent / 'questions').glob('*.json'))), 1)

    def test_task_done_is_staged_while_live_and_only_requested_after_drain(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='done')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
        self.assertEqual(result['outcome'], 'done_requested')
        done = json.loads((self.agent / 'done.json').read_text())
        self.assertEqual(done['state'], 'requested')
        self.assertEqual(done['envelope_key'], 'event-1')
        self.assertIs(done['finalized'], False)
        self.assertEqual(done['summary'], 'Ready <& unchanged')
        operation_dir = self.state / self.control['codex_state_id'] / 'operations' / result['operation_id']
        completion = json.loads((operation_dir / 'completion.json').read_text())
        self.assertEqual(set(completion), {'schema', 'operation_id', 'task_incarnation',
            'generation', 'attempt_id', 'event_key', 'thread_id', 'turn_id', 'request_id',
            'call_id', 'request_digest', 'summary', 'phase', 'checkpoint', 'done_receipt'})
        self.assertEqual(completion['schema'], 1)
        self.assertEqual(completion['operation_id'], result['operation_id'])
        self.assertEqual(completion['task_incarnation'], INC)
        self.assertEqual((completion['generation'], completion['attempt_id']), (7, 'attempt-1'))
        self.assertEqual(completion['event_key'], 'event-1')
        self.assertEqual(completion['call_id'], 'ordinary-call')
        self.assertEqual(completion['summary'], 'Ready <& unchanged')
        self.assertEqual(completion['phase'], 'done_written')
        self.assertIs(type(completion['request_id']), int)
        self.assertEqual(completion['request_id'], 0)
        self.assertEqual(completion['checkpoint']['commit_sha'], self.base)
        self.assertIsNotNone(completion['done_receipt'])
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        original = (self.agent / 'done.json').read_bytes()
        before = len(calls)
        controller.reconcile(deadline=time.monotonic() + 2)
        self.assertEqual((self.agent / 'done.json').read_bytes(), original)
        self.assertEqual(len(calls), before)

    def test_retained_descriptor_drift_refuses_ordinary_send(self):
        for mode in ('descriptor_loss', 'descriptor_true'):
            with self.subTest(mode=mode):
                case = RuntimeContract(methodName='test_constructor_is_inert_and_does_not_initialize_missing_index')
                case.setUp()
                try:
                    case.publish_registry()
                    controller, hosts, calls, order = case.discovery_fixture(native_mode=mode)
                    result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
                    self.assertIn(result['outcome'], ('blocked', 'unknown'))
                    self.assertEqual(sum(m == 'turn/start' for m, p in calls), 1)
                    self.assertFalse((case.agent / 'done.json').exists())
                    self.assertTrue(all(h.phase == 'stopped' for h in hosts))
                finally:
                    case.doCleanups()

    def test_next_event_uses_new_operation_and_host_with_same_retained_thread(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='read')
        first = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
        self.assertEqual(first['outcome'], 'ran')
        first_projection = json.loads((self.agent / 'inbox/inflight/event-1.json').read_text())
        save(self.agent / 'inbox/inflight/event-2.json', {'key': 'event-2', 'meta': {}})
        self.expected_event_key = 'event-2'
        second = controller.execute('event-2', 7, 'attempt-1', deadline=time.monotonic() + 3)
        self.assertEqual(second['outcome'], 'ran')
        self.assertNotEqual(first['operation_id'], second['operation_id'])
        self.assertNotEqual(first['turn_id'], second['turn_id'])
        self.assertEqual(first['thread_id'], second['thread_id'])
        self.assertEqual(len(hosts), 4)
        self.assertEqual(sum(m == 'thread/start' for m, p in calls), 1)
        self.assertEqual(sum(m == 'thread/resume' for m, p in calls), 2)
        self.assertEqual(sum(m == 'turn/start' for m, p in calls), 3)
        self.assertEqual(json.loads((self.agent / 'inbox/inflight/event-1.json').read_text()), first_projection)
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertIs(controller.require_drained(deadline=time.monotonic() + 2), True)

    def test_reason_only_file_approval_has_no_answer_or_approve_question(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_reason_only')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(len(hosts), 3)
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertFalse((self.agent / 'done.json').exists())
        for path in (self.agent / 'questions').glob('*.json'):
            question = json.loads(path.read_text())
            self.assertNotIn('approve', [str(option).lower() for option in question.get('options', [])])
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip(), self.base)

    def test_native_command_approval_is_policy_violation_without_human_workaround(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='command_approval')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertEqual(list((self.agent / 'questions').glob('*.json')), [])
        self.assertFalse((self.agent / 'done.json').exists())

    def test_dirty_done_uses_default_guarded_git_checkpoint_with_exact_trailers(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='done_dirty', default_checkpoint=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 5)
        self.assertEqual(result['outcome'], 'done_requested')
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        head = self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip()
        self.assertNotEqual(head, self.base)
        self.assertEqual(self.git('rev-parse', 'HEAD^', cwd=self.agent / 'work').strip(), self.base)
        self.assertEqual(self.git('show', 'HEAD:tracked.txt', cwd=self.agent / 'work'), 'native dirty task change\n')
        completion_path = self.state / self.control['codex_state_id'] / 'operations' / result['operation_id'] / 'completion.json'
        completion = json.loads(completion_path.read_text())
        self.assertEqual(completion['phase'], 'done_written')
        self.assertEqual(completion['checkpoint']['commit_sha'], head)
        self.assertIs(completion['checkpoint']['no_commit'], False)
        message = self.git('show', '-s', '--format=%B', head, cwd=self.agent / 'work')
        self.assertEqual(message.count('Codex-Task-Operation: ' + result['operation_id']), 1)
        self.assertEqual(message.count('Codex-Task-Intent: ' + completion['request_digest']), 1)
        done = json.loads((self.agent / 'done.json').read_text())
        self.assertEqual(done['state'], 'requested')
        self.assertIs(done['finalized'], False)
        self.assertEqual(done['summary'], 'Ready <& dirty')
        before_count = self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work')
        controller.reconcile(deadline=time.monotonic() + 3)
        self.assertEqual(self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work'), before_count)
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.project).strip(), self.base)

    def test_correlated_full_file_change_waits_for_genuine_human_decline(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_full', human_decision='decline')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 4)
        self.assertEqual(result['outcome'], 'ran')
        self.assertIn('genuine_human_answer', order)
        self.assertIn('reply_approval', order)
        self.assertLess(order.index('genuine_human_answer'), order.index('reply_approval'))
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'baseline\n')
        self.assertFalse((self.agent / 'done.json').exists())

    def test_full_file_change_approval_timeout_never_autoanswers(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_full')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 1)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertNotIn('reply_approval', order)
        self.assertNotIn('genuine_human_answer', order)
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'baseline\n')

    def test_outside_full_add_routes_genuine_reject_only_human_decline_once(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_outside',
            human_decision='decline')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 4)
        self.assertEqual(result['outcome'], 'ran')
        self.assertIn('outside_programmatic_approve_refused', order)
        self.assertIn('genuine_human_answer', order)
        self.assertEqual(order.count('reply_approval'), 1)
        self.assertLess(order.index('outside_programmatic_approve_refused'), order.index('genuine_human_answer'))
        self.assertLess(order.index('genuine_human_answer'), order.index('reply_approval'))
        self.assertEqual(len(hosts), 3)
        self.assertTrue(all(host.phase == 'stopped' for host in hosts))
        self.assertFalse((self.root / 'outside-candidate.txt').exists())
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'baseline\n')
        self.assertFalse((self.agent / 'done.json').exists())
        self.assertIs(controller.require_drained(deadline=time.monotonic() + 2), True)

    def test_outside_add_and_move_never_expand_baseline_after_human_approval(self):
        for mode in ('approval_outside', 'approval_move_outside'):
            with self.subTest(mode=mode):
                case = RuntimeContract(methodName='test_constructor_is_inert_and_does_not_initialize_missing_index')
                case.setUp()
                try:
                    case.publish_registry()
                    controller, hosts, calls, order = case.discovery_fixture(native_mode=mode)
                    result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 1)
                    self.assertIn(result['outcome'], ('blocked', 'unknown'))
                    self.assertNotIn('reply_approval', order)
                    self.assertFalse((case.root / 'outside-candidate.txt').exists())
                    self.assertTrue(all(h.phase == 'stopped' for h in hosts))
                finally:
                    case.doCleanups()

    def test_in_scope_human_approval_sends_exact_typed_accept_once(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_full',
            human_decision='accept', default_checkpoint=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 5)
        self.assertEqual(result['outcome'], 'ran')
        self.assertEqual(order.count('reply_approval'), 1)
        self.assertLess(order.index('genuine_human_answer'), order.index('reply_approval'))
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'approved change\n')
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertEqual(self.git('show', 'HEAD:tracked.txt', cwd=self.agent / 'work'), 'approved change\n')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.project).strip(), self.base)

    def test_resolved_or_changed_native_request_never_sends_human_approval(self):
        for state in ('resolved', 'changed'):
            with self.subTest(state=state):
                case = RuntimeContract(methodName='test_constructor_is_inert_and_does_not_initialize_missing_index')
                case.setUp()
                try:
                    case.publish_registry()
                    controller, hosts, calls, order = case.discovery_fixture(native_mode='approval_full',
                        human_decision='accept', approval_state=state)
                    result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
                    self.assertIn(result['outcome'], ('blocked', 'unknown'))
                    self.assertNotIn('reply_approval', order)
                    self.assertEqual((case.agent / 'work/tracked.txt').read_text(), 'baseline\n')
                    self.assertTrue(all(h.phase == 'stopped' for h in hosts))
                finally:
                    case.doCleanups()

    def test_string_resolved_id_does_not_cancel_distinct_integer_request(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_full',
            human_decision='decline', approval_state='typed_other')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 4)
        self.assertEqual(result['outcome'], 'ran')
        self.assertEqual(order.count('reply_approval'), 1)
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))

    def test_uncertain_native_approval_send_drains_and_never_retries(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_full',
            human_decision='decline', approval_state='uncertain')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 4)
        self.assertEqual(result['outcome'], 'unknown')
        self.assertEqual(order.count('reply_approval'), 1)
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertFalse((self.agent / 'done.json').exists())
        before = len(calls)
        controller.reconcile(deadline=time.monotonic() + 2)
        self.assertEqual(len(calls), before)
        self.assertEqual(order.count('reply_approval'), 1)
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'baseline\n')

    def completion_crash_fixture(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='checkpoint_crash', checkpoint_crash=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 5)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertIn('actual_commit_before_controller_crash', order)
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        completions = list((self.state / self.control['codex_state_id'] / 'operations').glob('*/completion.json'))
        self.assertEqual(len(completions), 1)
        completion = json.loads(completions[0].read_text())
        self.assertEqual(completion['phase'], 'drained')
        self.assertIsNone(completion['checkpoint']['commit_sha'])
        self.assertFalse((self.agent / 'done.json').exists())
        adapters = dict(self.runtime_native_adapters)
        adapters.pop('checkpoint')
        recovered = self.make(adapters=adapters)
        return recovered, calls, completions[0]

    def ordinary_checkpoint_crash_fixture(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='ordinary_checkpoint_crash', checkpoint_crash=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 5)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(order.count('actual_commit_before_controller_crash'), 1)
        self.assertTrue(all(host.phase == 'stopped' for host in hosts))
        self.assertFalse((self.agent / 'done.json').exists())
        self.assertEqual(list((self.agent / 'questions').glob('*.json')), [])
        head = self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip()
        self.assertNotEqual(head, self.base)
        self.assertEqual(self.git('rev-parse', 'HEAD^', cwd=self.agent / 'work').strip(), self.base)
        self.assertEqual(self.git('show', 'HEAD:tracked.txt', cwd=self.agent / 'work'), 'native dirty task change\n')
        self.assertEqual(sum(method == 'turn/start' for method, params in calls), 2)
        adapters = dict(self.runtime_native_adapters)
        adapters.pop('checkpoint')
        return self.make(adapters=adapters), calls, head

    def test_ordinary_checkpoint_commit_crash_recovers_exact_head_without_second_commit(self):
        controller, calls, head = self.ordinary_checkpoint_crash_fixture()
        before_count = self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work')
        before_calls = len(calls)
        result = controller.reconcile(deadline=time.monotonic() + 5)
        self.assertEqual(result['outcome'], 'recovered')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip(), head)
        self.assertEqual(self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work'), before_count)
        self.assertEqual(len(calls), before_calls)
        message = self.git('show', '-s', '--format=%B', head, cwd=self.agent / 'work')
        self.assertEqual(message.count('Codex-Task-Operation: '), 1)
        self.assertEqual(message.count('Codex-Task-Intent: '), 1)
        self.assertFalse((self.agent / 'done.json').exists())
        self.assertEqual(self.git('status', '--porcelain', cwd=self.agent / 'work'), '')
        controller.reconcile(deadline=time.monotonic() + 2)
        self.assertEqual(self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work'), before_count)

    def test_ordinary_checkpoint_crash_unrelated_head_is_not_recovered_or_recommitted(self):
        controller, calls, head = self.ordinary_checkpoint_crash_fixture()
        self.git('commit', '--allow-empty', '-m', 'unrelated after ordinary checkpoint', cwd=self.agent / 'work')
        unrelated = self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip()
        self.assertNotEqual(unrelated, head)
        count = self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work')
        before_calls = len(calls)
        result = controller.reconcile(deadline=time.monotonic() + 3)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip(), unrelated)
        self.assertEqual(self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work'), count)
        self.assertEqual(len(calls), before_calls)
        self.assertFalse((self.agent / 'done.json').exists())

    def test_commit_crash_recovers_exact_owned_head_without_second_commit(self):
        controller, calls, completion_path = self.completion_crash_fixture()
        head = self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip()
        before_count = self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work')
        before_calls = len(calls)
        result = controller.reconcile(deadline=time.monotonic() + 5)
        self.assertEqual(result['outcome'], 'recovered')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip(), head)
        self.assertEqual(self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work'), before_count)
        self.assertEqual(len(calls), before_calls)
        completion = json.loads(completion_path.read_text())
        self.assertEqual(completion['phase'], 'done_written')
        self.assertEqual(completion['checkpoint']['commit_sha'], head)
        done = json.loads((self.agent / 'done.json').read_text())
        self.assertEqual(done['state'], 'requested')
        self.assertIs(done['finalized'], False)
        self.assertEqual(done['summary'], 'Commit then crash')
        controller.reconcile(deadline=time.monotonic() + 3)
        self.assertEqual(self.git('rev-list', '--count', 'HEAD', cwd=self.agent / 'work'), before_count)

    def test_commit_crash_unrelated_head_is_hold_without_guessed_acceptance(self):
        controller, calls, completion_path = self.completion_crash_fixture()
        self.git('commit', '--allow-empty', '-m', 'unrelated later HEAD', cwd=self.agent / 'work')
        changed_head = self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip()
        before = completion_path.read_bytes()
        before_calls = len(calls)
        result = controller.reconcile(deadline=time.monotonic() + 3)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip(), changed_head)
        self.assertEqual(completion_path.read_bytes(), before)
        self.assertEqual(len(calls), before_calls)
        self.assertFalse((self.agent / 'done.json').exists())

    def test_task_done_forged_operation_trailer_never_creates_duplicate_checkpoint_evidence(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='forged_done', default_checkpoint=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 5)
        self.assertIn(result['outcome'], ('done_requested', 'blocked', 'unknown'))
        self.assertTrue(all(host.phase == 'stopped' for host in hosts))
        head = self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip()
        if result['outcome'] != 'done_requested':
            self.assertEqual(head, self.base, 'Unsafe summary must be refused before commit')
            self.assertFalse((self.agent / 'done.json').exists())
            self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'native dirty task change\n')
            return
        completion = json.loads((self.state / self.control['codex_state_id'] / 'operations' /
            result['operation_id'] / 'completion.json').read_text())
        operation_trailer = 'Codex-Task-Operation: ' + result['operation_id']
        intent_trailer = 'Codex-Task-Intent: ' + completion['request_digest']
        message = self.git('show', '-s', '--format=%B', head, cwd=self.agent / 'work')
        self.assertEqual(message.splitlines().count(operation_trailer), 1)
        self.assertEqual(message.splitlines().count(intent_trailer), 1)
        parsed = subprocess.run(['git', 'interpret-trailers', '--parse'], cwd=self.agent / 'work',
            env=self.git_env, input=message, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True).stdout.splitlines()
        self.assertEqual(parsed.count(operation_trailer), 1)
        self.assertEqual(parsed.count(intent_trailer), 1)
        self.assertEqual(self.git('rev-parse', 'HEAD^', cwd=self.agent / 'work').strip(), self.base)
        done = json.loads((self.agent / 'done.json').read_text())
        self.assertEqual(done['summary'], 'Ready untrusted\n\n' + operation_trailer)
        self.assertIs(done['finalized'], False)
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.project).strip(), self.base)

    def test_corrupt_completion_after_commit_crash_never_creates_done(self):
        controller, calls, completion_path = self.completion_crash_fixture()
        before_head = self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip()
        before_calls = len(calls)
        completion_path.write_text('{"schema":1,"schema":2}')
        result = controller.reconcile(deadline=time.monotonic() + 3)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(completion_path.read_text(), '{"schema":1,"schema":2}')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.agent / 'work').strip(), before_head)
        self.assertEqual(len(calls), before_calls)
        self.assertFalse((self.agent / 'done.json').exists())

    def test_lost_native_start_reply_does_not_resend_or_dispatch_queued_callbacks(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='lost_start')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertEqual(result['outcome'], 'unknown')
        self.assertEqual(sum(m == 'turn/start' for m, p in calls), 1)
        self.assertEqual(len(hosts), 2)
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))
        self.assertFalse((self.agent / 'done.json').exists())
        self.assertEqual(list((self.agent / 'questions').glob('*.json')), [])
        controller.reconcile(deadline=time.monotonic() + 2)
        self.assertEqual(sum(m == 'turn/start' for m, p in calls), 1)
        self.assertEqual(len(hosts), 2)

    def test_task_outcome_duplicate_callback_never_writes_or_replies_twice(self):
        for mode, expected in (('ask_duplicate', 'asked'), ('done_duplicate', 'done_requested')):
            with self.subTest(mode=mode):
                case = RuntimeContract(methodName='test_constructor_is_inert_and_does_not_initialize_missing_index')
                case.setUp()
                try:
                    case.publish_registry()
                    controller, hosts, calls, order = case.discovery_fixture(native_mode=mode)
                    result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
                    self.assertEqual(result['outcome'], expected)
                    self.assertEqual(order.count('reply_dynamic'), 1)
                    self.assertTrue(all(h.phase == 'stopped' for h in hosts))
                    self.assertEqual(len(list((case.agent / 'questions').glob('*.json'))), 1 if mode == 'ask_duplicate' else 0)
                    self.assertEqual((case.agent / 'done.json').exists(), mode == 'done_duplicate')
                finally:
                    case.doCleanups()

    def test_patch_scope_change_after_question_invalidates_old_human_acceptance(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_full',
            human_decision='accept', approval_state='patch_changed')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertIn('genuine_human_answer', order)
        self.assertNotIn('reply_approval', order)
        self.assertFalse((self.root / 'outside-candidate.txt').exists())
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'baseline\n')
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))

    def test_second_item_started_changed_scope_invalidates_already_answered_approval(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_full',
            human_decision='accept', approval_state='second_started')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertIn('genuine_human_answer', order)
        self.assertNotIn('reply_approval', order)
        self.assertFalse((self.root / 'outside-candidate.txt').exists())
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'baseline\n')
        self.assertTrue(all(host.phase == 'stopped' for host in hosts))

    def test_actual_store_revocation_after_answer_wins_before_native_reply(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_full',
            human_decision='accept', approval_state='revoked')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertIn('authority_revoked_after_answer', order)
        self.assertNotIn('reply_approval', order)
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'baseline\n')
        self.assertTrue(all(h.phase == 'stopped' for h in hosts))

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

    def test_drained_bootstrap_publication_crash_repairs_only_from_exact_durable_proof(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='read',
            bootstrap_publication_fault=True)
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertIn('admission_publication_blocked', order)
        proofs = list((self.state / self.control['codex_state_id']).rglob('bootstrap-proof.json'))
        self.assertEqual(len(proofs), 1)
        proof = json.loads(proofs[0].read_text())
        self.assertEqual(set(proof), {'schema', 'operation', 'admission', 'terminal'})
        self.assertEqual(proof['schema'], 1)
        self.assertEqual(set(proof['operation']), {'operation_id', 'task_incarnation', 'generation',
            'attempt_id', 'event_key', 'thread_id', 'turn_id', 'owner_event_key'})
        self.assertEqual(set(proof['terminal']), {'operation_id', 'task_incarnation', 'thread_id',
            'turn_id', 'terminal', 'terminal_proven', 'quiescent'})
        self.assertEqual(proof['terminal']['terminal'], 'completed')
        self.assertIs(proof['terminal']['terminal_proven'], True)
        self.assertIs(proof['terminal']['quiescent'], True)
        self.assertTrue(all(host.phase == 'stopped' for host in hosts))
        self.assertEqual(sum(method == 'turn/start' for method, params in calls), 1)
        baseline_calls = list(calls)
        baseline_starts = [host.starts for host in hosts]
        admission = self.state / self.control['codex_state_id'] / 'admission.json'
        admission.rmdir()
        controller.reconcile(deadline=time.monotonic() + 3)
        self.assertEqual(json.loads(admission.read_text()), proof['admission'])
        self.assertEqual(calls, baseline_calls)
        self.assertEqual([host.starts for host in hosts], baseline_starts)

    def test_ordinary_turn_requires_its_own_exact_correlated_registry_before_task_authority(self):
        for mode in ('ordinary_registry_extra', 'ordinary_registry_missing', 'ordinary_registry_uncorrelated'):
            with self.subTest(mode=mode):
                case = RuntimeContract(methodName='test_constructor_is_inert_and_does_not_initialize_missing_index')
                case.setUp()
                try:
                    case.publish_registry()
                    controller, hosts, calls, order = case.discovery_fixture(native_mode=mode)
                    result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
                    self.assertIn(result['outcome'], ('blocked', 'unknown'))
                    self.assertEqual(sum(method == 'turn/start' for method, params in calls), 2)
                    self.assertNotIn('reply_dynamic', order)
                    self.assertTrue(all(host.phase == 'stopped' for host in hosts))
                    self.assertEqual((case.agent / 'work/tracked.txt').read_text(), 'baseline\n')
                    self.assertFalse((case.agent / 'done.json').exists())
                finally:
                    case.doCleanups()

    def test_unwritable_confirmed_receipt_refuses_before_native_answer(self):
        self.publish_registry()
        controller, hosts, calls, order = self.discovery_fixture(native_mode='approval_full',
            human_decision='accept', approval_state='receipt_blocked')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertIn('confirmed_receipt_target_blocked', order)
        self.assertIn('genuine_human_answer', order)
        self.assertNotIn('reply_approval', order)
        questions = list((self.agent / 'questions').glob('*.json'))
        self.assertEqual(len(questions), 1)
        question = json.loads(questions[0].read_text())
        self.assertEqual(question['status'], 'open')
        self.assertEqual(question['decision'], 'approve')
        self.assertEqual((self.agent / 'work/tracked.txt').read_text(), 'baseline\n')
        self.assertTrue(all(host.phase == 'stopped' for host in hosts))

    def test_execute_foreign_kernel_executor_lock_owner_has_zero_effect(self):
        self.publish_registry()
        self.executor.close()
        lock = self.agent / 'inbox/.executor.lock'
        code = ('import fcntl,sys; '
                "f=open(sys.argv[1],'r+'); fcntl.flock(f,fcntl.LOCK_EX); "
                "print('locked',flush=True); sys.stdin.readline()")
        owner = subprocess.Popen([sys.executable, '-u', '-c', code, str(lock)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=self.git_env)
        try:
            self.assertEqual(owner.stdout.readline().strip(), 'locked')
            before = self.snapshot()
            control_before = (self.agent / 'control.json').read_bytes()
            self.refusal(lambda: self.make().execute('event-1', 7, 'attempt-1',
                                                    deadline=time.monotonic() + 2))
            self.assertEqual(before, self.snapshot())
            self.assertEqual((self.agent / 'control.json').read_bytes(), control_before)
            index = json.loads((self.state / self.control['codex_state_id'] / 'index.json').read_text())
            self.assertEqual(index['operations'], {})
        finally:
            if owner.poll() is None:
                owner.stdin.write('release\n')
                owner.stdin.flush()
            owner.wait(timeout=2)
            owner.stdin.close()
            owner.stdout.close()
            owner.stderr.close()

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
