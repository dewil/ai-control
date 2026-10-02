#!/usr/bin/env python3
"""Blind CXRUN public controller tests. Native boundaries only; private IO is real."""
import copy
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
