#!/usr/bin/env python3
"""Independent second-compliance recovery tests; native boundaries are fixtures.

Reuse the independent public controller fixtures, never inspect production.
Actual executor/question locks, inbox, Git, answer CLI and card renderer remain real.
"""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
fixture_spec = importlib.util.spec_from_file_location('recovery_native_fixture', ROOT / 'tests/test-codex-task-runtime.py')
fixture_module = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture_module)


def entry(name, label):
    loader = importlib.machinery.SourceFileLoader(label, str(ROOT / 'bin' / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RecoveryCompliance(unittest.TestCase):
    def setUp(self):
        self.f = fixture_module.RuntimeContract('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        # The shared runner derives its store beside the selected agents root;
        # the generic library fixture's explicit private path is not that CLI path.
        canonical_state = self.f.agent.parent.parent / 'codex-task-state'
        self.f.state.rename(canonical_state)
        self.f.state = canonical_state
        self.env = dict(self.f.git_env, CLAUDE_AGENTS_DIR=str(self.f.agent.parent),
            CLAUDE_AGENT_SPOOL_BASE=str(self.f.root / 'spool'),
            CLAUDE_AGENT_GENERATION='7', CLAUDE_AGENT_ATTEMPT='attempt-1')

    def cycle(self, controller):
        calls = []
        f = self.f
        class RecoveryOnly:
            def __init__(self, agent_dir, **kwargs):
                self.agent_dir = agent_dir
            def static_preflight(self, *, deadline):
                return dict(ready=True, version='0.160.0', permission_profile='control_task', release_hashes={})
            def reconcile(self, *, deadline):
                # An independently opened descriptor must not steal the actual lock.
                with (f.agent / 'inbox/.executor.lock').open('a') as competing:
                    try:
                        fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        raise AssertionError('shared recovery lacks actual executor ownership')
                calls.append('reconcile')
                return controller.reconcile(deadline=deadline)
            def execute(self, *args, **kwargs):
                raise AssertionError('recovery may not resubmit a native/model turn')
        boundary = types.ModuleType('_codex_task_runtime')
        boundary.CodexTaskRuntime = RecoveryOnly
        boundary.RuntimeError = fixture_module.runtime_module.RuntimeError
        with mock.patch.dict(os.environ, self.env), mock.patch.dict(sys.modules, {'_codex_task_runtime': boundary}):
            runner = entry('claude-agent-run', 'second_compliance_runner')
            self.assertTrue(callable(getattr(runner, 'codex_cycle', None)), 'public codex_cycle is absent')
            result = runner.codex_cycle(str(f.agent), str(f.agent / 'inbox'), f.agent.name, 0)
        self.assertEqual(calls, ['reconcile'], 'reconcile must precede existing inflight infra_wait')
        return result

    def test_shared_cycle_recovers_completion_before_existing_inflight_wait(self):
        # INV-CXRUN-07: recovery archives real original envelope, no resubmit.
        f = self.f
        controller, native_calls, completion = f.completion_crash_fixture()
        before_calls = list(native_calls)
        head = f.git('rev-parse', 'HEAD', cwd=f.agent / 'work')
        self.assertTrue((f.agent / 'inbox/inflight/event-1.json').is_file())
        self.cycle(controller)
        self.assertFalse((f.agent / 'inbox/inflight/event-1.json').exists())
        archived = json.loads((f.agent / 'inbox/done/event-1.json').read_text())
        self.assertEqual(archived['meta']['history'][-1]['outcome'], 'ok')
        self.assertTrue((f.agent / 'done.json').is_file())
        dedup = [json.loads(line) for line in (f.agent / 'inbox/dedup.jsonl').read_text().splitlines()]
        self.assertEqual(sum(row['key'] == 'event-1' for row in dedup), 1)
        self.assertEqual(native_calls, before_calls)
        self.assertEqual(f.git('rev-parse', 'HEAD', cwd=f.agent / 'work'), head)

    def test_shared_cycle_unknown_recovery_retains_inflight_without_resubmit(self):
        f = self.f
        store = f.publish_registry()
        store.prepare('event-1', 7, 'attempt-1', deadline=time.monotonic() + 3)
        before = (f.agent / 'inbox/inflight/event-1.json').read_bytes()
        class Unknown:
            def reconcile(self, *, deadline):
                return dict(outcome='unknown', operations=[], reason='missing durable evidence')
        self.cycle(Unknown())
        self.assertEqual((f.agent / 'inbox/inflight/event-1.json').read_bytes(), before)
        self.assertFalse((f.agent / 'inbox/done/event-1.json').exists())
        self.assertFalse((f.agent / 'done.json').exists())

    def test_completion_recovery_finalizes_exact_shared_done_before_archive_and_replay(self):
        f = self.f
        controller, calls, completion_path = f.completion_crash_fixture()
        before_calls = list(calls)
        head = f.git('rev-parse', 'HEAD', cwd=f.agent / 'work').strip()
        result = controller.reconcile(deadline=time.monotonic() + 5)
        self.assertEqual(result['outcome'], 'recovered')
        done_path = f.agent / 'done.json'
        done = json.loads(done_path.read_text())
        self.assertEqual(done['state'], 'requested')
        self.assertIs(done['finalized'], True, 'archived completion must finalize shared worktree done')
        self.assertEqual(done['envelope_key'], 'event-1')
        self.assertEqual(done['commit_sha'], head)
        completion = json.loads(completion_path.read_text())
        self.assertEqual(completion['checkpoint']['commit_sha'], head)
        self.assertFalse((f.agent / 'inbox/inflight/event-1.json').exists())
        archived = f.agent / 'inbox/done/event-1.json'
        self.assertTrue(archived.is_file())
        done_before, archived_before = done_path.read_bytes(), archived.read_bytes()
        controller.reconcile(deadline=time.monotonic() + 3)
        self.assertEqual(done_path.read_bytes(), done_before)
        self.assertEqual(archived.read_bytes(), archived_before)
        self.assertEqual(f.git('rev-parse', 'HEAD', cwd=f.agent / 'work').strip(), head)
        self.assertEqual(calls, before_calls)

    def test_completion_recovery_shared_finalization_conflict_holds_original(self):
        f = self.f
        controller, calls, completion_path = f.completion_crash_fixture()
        before_calls = list(calls)
        # Public shared writer creates the real requested done shape. Simulate
        # a conflicting previously finalized shared receipt in this own fixture.
        # The crash used its private checkpoint index; reconcile has not yet
        # synchronized the ordinary index. Arrange the shared writer's genuine
        # clean-tree precondition against that already committed fixture HEAD.
        f.git('read-tree', 'HEAD', cwd=f.agent / 'work')
        self.assertEqual(f.git('status', '--porcelain', cwd=f.agent / 'work'), '')
        from _agent_done_io import request_done_locked
        with (f.agent / 'done.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            request_done_locked(str(f.agent), 'event-1', 'owned conflicting completion',
                                deadline=time.monotonic() + 2)
            done_path = f.agent / 'done.json'
            done = json.loads(done_path.read_text())
            done.update(finalized=True, commit_sha='f' * 40, empty=False, changes=['tracked.txt'])
            fixture_module.save(done_path, done)
        before_done = done_path.read_bytes()
        head = f.git('rev-parse', 'HEAD', cwd=f.agent / 'work')
        try:
            result = controller.reconcile(deadline=time.monotonic() + 5)
        except fixture_module.runtime_module.RuntimeError:
            pass
        else:
            self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(done_path.read_bytes(), before_done)
        self.assertTrue((f.agent / 'inbox/inflight/event-1.json').is_file())
        self.assertFalse((f.agent / 'inbox/done/event-1.json').exists())
        completion = json.loads(completion_path.read_text())
        index = json.loads((f.state / f.control['codex_state_id'] / 'index.json').read_text())
        self.assertNotEqual(index['operations'][completion['operation_id']]['status'], 'finished')
        self.assertEqual(f.git('rev-parse', 'HEAD', cwd=f.agent / 'work'), head)
        self.assertEqual(calls, before_calls)

    def requested_completion_fixture(self):
        f = self.f
        controller, calls, completion_path = f.completion_crash_fixture()
        f.git('read-tree', 'HEAD', cwd=f.agent / 'work')
        self.assertEqual(f.git('status', '--porcelain', cwd=f.agent / 'work'), '')
        from _agent_done_io import request_done_locked
        with (f.agent / 'done.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            request_done_locked(str(f.agent), 'event-1', 'owned pending completion',
                                deadline=time.monotonic() + 2)
        done_path = f.agent / 'done.json'
        self.assertIs(json.loads(done_path.read_text())['finalized'], False)
        return controller, calls, completion_path, done_path

    def test_temporary_dirty_completion_recovery_preserves_request_then_recovers_once(self):
        f = self.f
        controller, calls, completion_path, done_path = self.requested_completion_fixture()
        before_calls = list(calls)
        head = f.git('rev-parse', 'HEAD', cwd=f.agent / 'work').strip()
        before_count = f.git('rev-list', '--count', 'HEAD', cwd=f.agent / 'work')
        tracked = f.agent / 'work/tracked.txt'
        checkpoint_content = tracked.read_bytes()
        before_done = done_path.read_bytes()
        before_completion = completion_path.read_bytes()
        envelope = f.agent / 'inbox/inflight/event-1.json'
        before_envelope = envelope.read_bytes()
        tracked.write_text('own temporary operator edit after verified checkpoint\n')
        try:
            result = controller.reconcile(deadline=time.monotonic() + 3)
        except fixture_module.runtime_module.RuntimeError:
            pass
        else:
            self.assertIn(result['outcome'], ('blocked', 'unknown'))
        self.assertEqual(done_path.read_bytes(), before_done)
        self.assertIs(json.loads(done_path.read_text())['finalized'], False)
        self.assertEqual(completion_path.read_bytes(), before_completion)
        self.assertEqual(envelope.read_bytes(), before_envelope)
        self.assertFalse((f.agent / 'inbox/done/event-1.json').exists())
        index = json.loads((f.state / f.control['codex_state_id'] / 'index.json').read_text())
        operation = json.loads(completion_path.read_text())['operation_id']
        self.assertNotEqual(index['operations'][operation]['status'], 'finished')
        self.assertEqual(calls, before_calls)
        tracked.write_bytes(checkpoint_content)
        result = controller.reconcile(deadline=time.monotonic() + 5)
        self.assertEqual(result['outcome'], 'recovered')
        done = json.loads(done_path.read_text())
        self.assertIs(done['finalized'], True)
        self.assertEqual(done['commit_sha'], head)
        self.assertFalse(envelope.exists())
        self.assertTrue((f.agent / 'inbox/done/event-1.json').is_file())
        rows = [json.loads(line) for line in (f.agent / 'inbox/dedup.jsonl').read_text().splitlines()]
        self.assertEqual(sum(row['key'] == 'event-1' for row in rows), 1)
        self.assertEqual(f.git('rev-parse', 'HEAD', cwd=f.agent / 'work').strip(), head)
        self.assertEqual(f.git('rev-list', '--count', 'HEAD', cwd=f.agent / 'work'), before_count)
        self.assertEqual(calls, before_calls)

    def test_completion_recovery_public_git_checks_share_operation_deadline(self):
        import _agent_worktree
        controller, calls, completion_path, done_path = self.requested_completion_fixture()
        deadline = time.monotonic() + 5
        observed = []
        original = _agent_worktree.git_run
        def bounded_git(*args, **kwargs):
            observed.append(kwargs.get('deadline'))
            return original(*args, **kwargs)
        with mock.patch.object(_agent_worktree, 'git_run', bounded_git):
            controller.reconcile(deadline=deadline)
        self.assertTrue(observed, 'public Git deadline spy must actually observe recovery checks')
        self.assertTrue(all(value is not None and value <= deadline for value in observed),
                        'trusted recovery Git checks must inherit the operation deadline')

    def pending_permission(self):
        f = self.f
        f.publish_registry()
        controller, hosts, calls, order = f.discovery_fixture(native_mode='approval_full')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 1)
        self.assertIn(result['outcome'], ('blocked', 'unknown'))
        questions = list((f.agent / 'questions').glob('*.json'))
        self.assertEqual(len(questions), 1)
        question = json.loads(questions[0].read_text())
        self.assertEqual(question['status'], 'open', 'fixture must capture genuine pending question before recovery')
        self.assertEqual(question['native_callback']['status'], 'pending')
        self.assertIsNone(question['decision'])
        self.assertIsNone(question['answered_at'])
        self.assertNotIn('genuine_human_answer', order)
        self.assertNotIn('reply_approval', order)
        self.assertFalse(list(f.state.rglob('approval-*-intent.json')))
        return controller, hosts, calls, order, questions[0]

    def expire_pending(self):
        controller, hosts, calls, order, path = self.pending_permission()
        before_calls = list(calls)
        controller.reconcile(deadline=time.monotonic() + 3)
        question = json.loads(path.read_text())
        self.assertIn(question['status'], ('expired', 'stale'))
        self.assertIn(question['native_callback']['status'], ('expired', 'stale'))
        self.assertTrue(all(host.phase == 'stopped' for host in hosts))
        self.assertEqual(calls, before_calls)
        self.assertNotIn('reply_approval', order)
        return path, question

    def test_unanswered_native_permission_expires_after_recovery_drain(self):
        # INV-CXRUN-06: no human answer/intent does not leave late authority.
        self.expire_pending()

    def admin_permission_barrier(self, reason):
        # A genuine policy-drained pending callback still carries stale UI
        # authority until the explicit administrative barrier fences it.
        controller, hosts, calls, order, path = self.pending_permission()
        before_calls = list(calls)
        head = self.f.git('rev-parse', 'HEAD', cwd=self.f.agent / 'work')
        result = controller.revoke_and_drain(reason, deadline=time.monotonic() + 3)
        self.assertIs(result['drained'], True)
        question = json.loads(path.read_text())
        self.assertIn(question['status'], ('expired', 'stale'))
        self.assertIn(question['native_callback']['status'], ('expired', 'stale'))
        self.assertIsNone(question['decision'])
        self.assertIsNone(question['answered_at'])
        self.assertTrue(all(host.phase == 'stopped' for host in hosts))
        before_question = path.read_bytes()
        spool = self.f.root / 'spool/taskone'
        before_spool = {p.name: p.read_bytes() for p in spool.glob('*.json')}
        for decision in ('approve', 'reject'):
            result = subprocess.run([str(ROOT / 'bin/claude-agent-answer'), str(self.f.agent),
                '--qid', question['qid'], '--' + decision, '--by', 'fixture-late-human'],
                env=self.env, text=True, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), before_question)
            self.assertEqual({p.name: p.read_bytes() for p in spool.glob('*.json')}, before_spool)
        repeated = controller.revoke_and_drain(reason, deadline=time.monotonic() + 3)
        self.assertIs(repeated['drained'], True)
        self.assertEqual(path.read_bytes(), before_question)
        self.assertEqual(calls, before_calls)
        self.assertNotIn('reply_approval', order)
        self.assertEqual(self.f.git('rev-parse', 'HEAD', cwd=self.f.agent / 'work'), head)
        self.assertFalse((self.f.agent / 'done.json').exists())

    def test_direct_pause_barrier_expires_genuine_pending_permission(self):
        self.admin_permission_barrier('pause')

    def test_direct_cancel_barrier_expires_genuine_pending_permission(self):
        self.admin_permission_barrier('cancel')

    def test_direct_shutdown_barrier_expires_genuine_pending_permission(self):
        self.admin_permission_barrier('shutdown')

    def test_quiescent_shutdown_barrier_under_existing_done_lock_does_not_reenter_it(self):
        # Shared destructive entries already own done.lock before calling their
        # native barrier. A drained tombstone with no questions must remain
        # usable under that real lock, rather than self-block until deadline.
        f = self.f
        store = f.publish_registry()
        operation = store.prepare('event-1', 7, 'attempt-1', deadline=time.monotonic() + 2)
        controller = f.make()
        drained = controller.revoke_and_drain('recovery', deadline=time.monotonic() + 2)
        self.assertIs(drained['drained'], True)
        self.assertIn(operation['operation_id'], drained['operations'])
        self.assertIs(controller.require_drained(deadline=time.monotonic() + 2), True)
        self.assertFalse(list((f.agent / 'questions').glob('*.json')))
        head = f.git('rev-parse', 'HEAD', cwd=f.agent / 'work')
        started = time.monotonic()
        with (f.agent / 'done.lock').open('a') as done_lock:
            fcntl.flock(done_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                result = controller.revoke_and_drain('shutdown', deadline=time.monotonic() + 1)
            except fixture_module.runtime_module.RuntimeError:
                self.fail('bounded nested quiescent barrier refused while holding done lock')
        self.assertIs(result['drained'], True)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(f.git('rev-parse', 'HEAD', cwd=f.agent / 'work'), head)
        self.assertFalse((f.agent / 'done.json').exists())
        self.assertEqual(f.effects, [])

    def test_late_actual_approve_and_reject_refuse_before_question_or_spool_mutation(self):
        path, question = self.expire_pending()
        before = path.read_bytes()
        spool = self.f.root / 'spool/taskone'
        spool_before = {p.name: p.read_bytes() for p in spool.glob('*.json')}
        for decision in ('approve', 'reject'):
            with self.subTest(decision=decision):
                result = subprocess.run([str(ROOT / 'bin/claude-agent-answer'), str(self.f.agent),
                    '--qid', question['qid'], '--' + decision, '--by', 'fixture-late-human'],
                    env=self.env, text=True, capture_output=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual({p.name: p.read_bytes() for p in spool.glob('*.json')}, spool_before)

    def test_expired_native_permission_card_has_no_active_buttons(self):
        path, question = self.expire_pending()
        with mock.patch.dict(os.environ, self.env):
            bot = entry('claude-agent-tgbot', 'second_compliance_bot')
            text, keyboard = bot.question_card(dict(question, agent=self.f.agent.name, project='fixture'))
        buttons = [button for row in keyboard['inline_keyboard'] for button in row]
        self.assertFalse(buttons, 'expired native permission must not offer actionable callback buttons')

    def test_lone_native_send_intent_stays_held_and_never_resends(self):
        f = self.f
        f.publish_registry()
        controller, hosts, calls, order = f.discovery_fixture(native_mode='approval_full',
            human_decision='decline', approval_state='uncertain')
        result = controller.execute('event-1', 7, 'attempt-1', deadline=time.monotonic() + 4)
        self.assertEqual(result['outcome'], 'unknown')
        intents = list(f.state.rglob('approval-*-intent.json'))
        self.assertEqual(len(intents), 1)
        self.assertFalse([p for p in f.state.rglob('approval-*.json') if not p.name.endswith('-intent.json')])
        before = list(calls)
        recovered = controller.reconcile(deadline=time.monotonic() + 3)
        self.assertIn(recovered['outcome'], ('blocked', 'unknown'))
        self.assertEqual(calls, before)
        self.assertEqual(order.count('reply_approval'), 1)
        self.assertFalse((f.agent / 'done.json').exists())

    def test_confirmed_receipt_positive_closes_without_native_resend(self):
        # Retain the already accepted positive counterexample to lone intent.
        self.f.test_confirmed_native_resolution_receipt_recovers_failed_question_close_without_second_reply()


if __name__ == '__main__':
    unittest.main()
