#!/usr/bin/env python3
"""Blind native permission answer harvest contract, actual store/IO/inbox/spool.

Fakes cover only controller/native/process boundary. Registry, human answer
writer and intake are real; no native host, bot, network or model is called.
"""
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
try:
    store_module = importlib.import_module('_codex_task_store')
except ModuleNotFoundError as exc:
    if exc.name != '_codex_task_store':
        raise
    store_module = None

INC = '0123456789abcdef0123456789abcdef'
EVENT = 'captured-native-request'


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    path.chmod(0o600)


class NativeAnswerContract(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(store_module, 'accepted operation store dependency is required')
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='native-answer-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        shutil.copytree(ROOT / 'bin', self.bin)
        self.home = self.root / 'home'
        self.home.mkdir(mode=0o700)
        self.stage = self.root / 'agents/.stage'
        self.agent = self.root / 'agents/task-native-answer'
        self.state_root = self.root / 'codex-task-state'
        self.project = self.root / 'project'
        for path in (self.stage / 'work', self.stage / 'inbox/inflight', self.state_root, self.project):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path in self.root.rglob('*'):
            if path.is_dir():
                path.chmod(0o700)
        for path in (self.stage / '.lock', self.stage / 'inbox/.inbox.lock'):
            path.touch(mode=0o600)
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / 'config'),
            CLAUDE_CONFIG_DIR=str(self.root / 'claude'), CODEX_HOME=str(self.root / 'codex'),
            CLAUDE_AGENTS_DIR=str(self.agent.parent), CLAUDE_AGENT_SPOOL_BASE=str(self.root / 'spool'),
            CLAUDE_RECONCILER_DIR=str(self.root / 'reconciler'), CLAUDE_AGENT_PROBE_CMD='/usr/bin/true',
            CLAUDE_AGENT_GENERATION='7', CLAUDE_AGENT_ATTEMPT='attempt-1')
        self.effects = self.root / 'forbidden-native-effects.jsonl'
        mockbin = self.root / 'mockbin'
        mockbin.mkdir(mode=0o700)
        for name in ('codex', 'claude', 'systemd-run', 'systemctl'):
            command = mockbin / name
            command.write_text('#!/usr/bin/env python3\nimport sys,json\n'
                f'with open({str(self.effects)!r},"a") as f: f.write(json.dumps(sys.argv)+"\\n")\n'
                'sys.exit(2)\n')
            command.chmod(0o700)
        self.env['PATH'] = str(mockbin) + os.pathsep + os.environ['PATH']
        self.env['CLAUDE_BIN'] = str(mockbin / 'claude')
        (self.root / 'spool' / self.agent.name).mkdir(parents=True, mode=0o700)
        self.execute_log = self.root / 'controller-execute.jsonl'
        native = self.bin / '_codex_task_runtime.py'
        native.write_text('import json\nclass RuntimeError(Exception): pass\n'
            'class CodexTaskRuntime:\n'
            ' def __init__(self,agent_dir,**kwargs): self.agent_dir=str(agent_dir)\n'
            ' def static_preflight(self,*,deadline): return dict(ready=True,version="0.160.0",permission_profile="control_task",release_hashes={})\n'
            ' def reconcile(self,*,deadline): return dict(outcome="idle",operations=[],reason=None)\n'
            ' def execute(self,event_key,generation,attempt_id,*,deadline):\n'
            f'  with open({str(self.execute_log)!r},"a") as f: f.write(json.dumps([event_key,generation,attempt_id])+"\\n")\n'
            '  raise RuntimeError("unexpected ordinary model turn")\n'
            ' def revoke_and_drain(self,reason,*,deadline): raise RuntimeError("no native fixture host")\n'
            ' def require_drained(self,*,deadline): raise RuntimeError("no native fixture host")\n')
        compile(native.read_text(), str(native), 'exec')
        self.control = dict(schema=1, seq=0, incarnation=INC, generation=0, desired='paused',
            session_id=None, started_at=None, deadline_extension_h=0, mission_base='a' * 40,
            lease=dict(state='none', start_attempt_id=None, gen_base=None, socket=None, unit=None,
                       main_pid=None, pid_start=None, granted_at=None, renewed_at=None, ttl_s=300),
            acceptance=dict(status='pending', artifact=None, verdict_by=None, checked_at=None,
                note=None, check_job=None, check_runs=[]), attention=None, hold=None, handoff=None)
        save(self.stage / 'control.json', self.control)
        spec = dict(schema=1, name=self.agent.name, engine='codex', type='event', runtime='drain',
            workspace='worktree', project=str(self.project), role='none', goal='native answer fixture',
            autonomy='suggest', memory_max_mb=1024, limits=dict(runs_per_day=100, run_timeout_s=20),
            source=dict(kind='spool', replay_window_h=72))
        save(self.stage / 'spec.yaml', spec)
        self.sid = str(uuid.uuid4())
        self.Store = store_module.CodexTaskOperationStore
        deadline = time.monotonic() + 10
        self.Store.initialize(str(self.stage), str(self.agent), self.sid,
                              state_root=str(self.state_root), deadline=deadline)
        self.control['codex_state_id'] = self.sid
        save(self.stage / 'control.json', self.control)
        self.stage.rename(self.agent)
        self.control.update(generation=7, desired='running')
        self.control['lease'].update(state='active', start_attempt_id='attempt-1')
        save(self.agent / 'control.json', self.control)
        save(self.agent / 'inbox/inflight' / (EVENT + '.json'), dict(schema=1, key=EVENT, meta={},
            source_ns='fixture', native_id='captured', received_at='2026-10-03T00:00:00Z',
            payload=dict(text='original captured native request')))
        self.store = self.Store(str(self.agent), state_root=str(self.state_root))
        record = self.store.prepare(EVENT, 7, 'attempt-1', deadline=deadline)
        self.operation = record['operation_id']
        with self.store.launch_guard(self.operation, deadline=deadline):
            pass  # Trusted native boundary fixture; no process launch.
        self.store.record_thread(self.operation, 'native-thread', deadline=deadline)
        with self.store.reserve_start(self.operation, deadline=deadline) as reservation:
            reservation.activate('native-thread', 'native-turn')
        self.opdir = self.state_root / self.sid / 'operations' / self.operation
        self.qid = str(uuid.uuid4())
        self.qfile = self.agent / 'questions' / (self.qid + '.json')
        self.qfile.parent.mkdir(mode=0o700)
        self.callback = dict(operation_id=self.operation, task_incarnation=INC, generation=7,
            attempt_id='attempt-1', thread_id='native-thread', turn_id='native-turn',
            request_id=31, method='item/fileChange/requestApproval', item_id='native-item',
            payload_fingerprint='b' * 64, changes_digest='c' * 64, status='waiting')
        self.question = dict(qid=self.qid, envelope_key=EVENT, asked_at='2026-10-03T00:00:00Z',
            kind='permission', question='May apply this own fixture patch?', options=None, context=None,
            status='open', answer=None, answered_at=None, answered_by=None, decision=None,
            closed_by_envelope=None, native_callback=self.callback,
            reminder=dict(step=0, next_push_at='2026-10-03T00:00:00Z', snoozed_until=None))
        save(self.qfile, self.question)

    def cli(self, name, *args):
        return subprocess.run([str(self.bin / name), *map(str, args)], env=self.env,
            text=True, capture_output=True, timeout=15)

    def publish_answer(self, decision='approve', *, native=True):
        if not native:
            question = json.loads(self.qfile.read_text())
            question.pop('native_callback')
            question.update(kind='info', question='What should TASK do next?', options=None)
            save(self.qfile, question)
            args = ['--text', 'continue with the own fixture']
        else:
            args = ['--' + decision]
        result = self.cli('claude-agent-answer', self.agent, '--qid', self.qid,
                          *args, '--by', 'tg:555')
        self.assertEqual(result.returncode, 0, result.stderr)
        if native:
            question = json.loads(self.qfile.read_text())
            question['status'] = 'closed'
            question['native_callback']['status'] = 'answered'
            save(self.qfile, question)
            callback = question['native_callback']
            digest = hashlib.sha256(json.dumps(callback, sort_keys=True, separators=(',', ':'),
                                               ensure_ascii=False).encode('utf-8')).hexdigest()
            self.receipt = dict(question_id=self.qid, operation_id=self.operation, task_incarnation=INC,
                callback_digest=digest, decision=question['decision'], answered_at=question['answered_at'],
                answered_by=question['answered_by'])
            save(self.opdir / ('approval-' + self.qid + '.json'), self.receipt)
        spool = self.root / 'spool' / self.agent.name
        events = list(spool.glob('ev-*.json'))
        self.assertEqual(len(events), 1, 'genuine answer writer must publish one envelope')
        self.answer_payload = json.loads(events[0].read_text())
        self.assertEqual(self.answer_payload['kind'], 'answer')
        self.assertEqual(self.answer_payload['question_id'], self.qid)

    def intake(self, *, may_hold=False):
        result = self.cli('claude-agent-run', 'intake', self.agent, '--batch', '50')
        self.assertIn(result.returncode, (0, 2) if may_hold else (0,), result.stderr)

    def answers(self, folder):
        paths = []
        for path in (self.agent / 'inbox' / folder).glob('*.json'):
            value = json.loads(path.read_text())
            if value.get('payload', {}).get('question_id') == self.qid:
                paths.append(path)
        return paths

    def no_native(self):
        self.assertFalse(self.execute_log.exists(), 'native permission answer must not become a model turn')
        self.assertFalse(self.effects.exists(), 'answer harvesting must not launch/stop native process or model')

    def consumed(self):
        done = self.answers('done')
        self.assertEqual(len(done), 1, 'matching native answer must become durable done')
        self.assertFalse(self.answers('pending'))
        self.assertFalse(self.answers('inflight'))
        row = json.loads(done[0].read_text())['meta']['history'][-1]
        self.assertEqual(row['outcome'], 'ok')
        self.assertEqual(row['internal'], 'native_permission_answer')
        self.assertIn(done[0].stem, (self.agent / 'inbox/dedup.log').read_text())
        self.no_native()
        return done[0]

    def preserved(self):
        self.assertFalse(self.answers('done'), 'uncertain native receipt may not authorize successful consumption')
        retained = sum((self.answers(folder) for folder in ('pending', 'inflight', 'deadletter')), [])
        self.assertEqual(len(retained), 1, 'uncertain native answer event must remain reviewable')
        self.no_native()

    def cycle(self):
        # Exact public runner seam supplied in the spec; actual inbox data stays real.
        sys.path.insert(0, str(self.bin))
        self.addCleanup(sys.path.remove, str(self.bin))
        runtime_spec = importlib.util.spec_from_file_location('fixture_native_runtime', self.bin / '_codex_task_runtime.py')
        runtime = importlib.util.module_from_spec(runtime_spec)
        runtime_spec.loader.exec_module(runtime)
        loader = importlib.machinery.SourceFileLoader('fixture_native_answer_runner', str(self.bin / 'claude-agent-run'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        runner = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, self.env), mock.patch.dict(sys.modules, {'_codex_task_runtime': runtime}):
            loader.exec_module(runner)
            self.assertTrue(callable(getattr(runner, 'codex_cycle', None)),
                            'Codex cycle public native-answer harvest seam is not implemented')
            runner.codex_cycle(str(self.agent), str(self.agent / 'inbox'), self.agent.name, 0)

    def test_real_permission_approve_answer_is_harvested_in_intake(self):
        # INV-CXRUN-06/08
        self.publish_answer('approve')
        self.intake()
        self.consumed()

    def test_real_permission_reject_answer_is_harvested_in_intake(self):
        # INV-CXRUN-06/08
        self.publish_answer('reject')
        self.intake()
        self.consumed()

    def test_answer_redelivery_dedup_and_unrelated_pending_are_preserved(self):
        # INV-CXRUN-06/08
        self.publish_answer()
        unrelated = self.agent / 'inbox/pending/unrelated.json'
        unrelated.parent.mkdir(exist_ok=True, mode=0o700)
        save(unrelated, dict(schema=1, key='unrelated', meta={}, payload=dict(text='ordinary future TASK event')))
        before = unrelated.read_bytes()
        self.intake()
        done = self.consumed()
        done_before = done.read_bytes()
        self.intake()
        self.assertEqual(done.read_bytes(), done_before)
        self.assertEqual(unrelated.read_bytes(), before)
        self.consumed()

    def test_actual_task_ask_info_answer_remains_normal_pending(self):
        # INV-CXRUN-05/06
        self.publish_answer(native=False)
        self.intake()
        self.assertEqual(len(self.answers('pending')), 1)
        self.assertFalse(self.answers('done'))
        self.no_native()

    def test_missing_receipt_preserves_answer_without_model_turn(self):
        # INV-CXRUN-06
        self.publish_answer()
        (self.opdir / ('approval-' + self.qid + '.json')).unlink()
        self.intake(may_hold=True)
        self.preserved()

    def test_conflicting_receipt_preserves_answer_without_model_turn(self):
        # INV-CXRUN-06
        self.publish_answer()
        self.receipt['decision'] = 'reject'
        save(self.opdir / ('approval-' + self.qid + '.json'), self.receipt)
        self.intake(may_hold=True)
        self.preserved()

    def test_unregistered_operation_receipt_cannot_authorize_consumption(self):
        # INV-CXRUN-06
        self.publish_answer()
        foreign = str(uuid.uuid4())
        question = json.loads(self.qfile.read_text())
        question['native_callback']['operation_id'] = foreign
        save(self.qfile, question)
        directory = self.opdir.parent / foreign
        directory.mkdir(mode=0o700)
        receipt = dict(self.receipt, operation_id=foreign)
        receipt['callback_digest'] = hashlib.sha256(json.dumps(question['native_callback'], sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
        save(directory / ('approval-' + self.qid + '.json'), receipt)
        self.intake(may_hold=True)
        self.preserved()

    def test_pending_native_permission_answer_is_harvested_before_pick_ready(self):
        # INV-CXRUN-06/08. Simulate old intake/crash leaving already-pending answer.
        self.publish_answer()
        receipt_path = self.opdir / ('approval-' + self.qid + '.json')
        receipt_path.unlink()
        self.intake(may_hold=True)
        self.assertEqual(len(self.answers('pending')), 1)
        save(receipt_path, self.receipt)
        self.cycle()
        self.consumed()

    def test_uncertain_pending_native_permission_answer_never_runs_as_model_turn(self):
        # INV-CXRUN-06
        self.publish_answer()
        (self.opdir / ('approval-' + self.qid + '.json')).unlink()
        self.intake(may_hold=True)
        self.assertEqual(len(self.answers('pending')), 1)
        self.cycle()
        self.preserved()


if __name__ == '__main__':
    unittest.main()
