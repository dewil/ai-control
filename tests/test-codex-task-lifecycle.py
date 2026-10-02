"""Blind offline acceptance tests for FR-CXTASK-LIFE-01..10.

Written from the feature spec and pinned 0.159.3 public wire schemas.
No runtime implementation was consulted. Missing module is a real RED.
"""
import copy
import concurrent.futures
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import _codex_task_lifecycle as lifecycle


def turn(marker=None, text='baseline', status='completed', answer=None):
    items = [{'type': 'userMessage', 'id': str(uuid4()), 'clientId': marker,
              'content': [{'type': 'text', 'text': text, 'textElements': []}]}]
    if answer is not None:
        items.append({'type': 'agentMessage', 'id': str(uuid4()), 'text': answer,
                      'phase': 'final', 'memoryCitation': None})
    return {'id': str(uuid4()), 'items': items, 'itemsView': 'full',
            'status': status, 'error': None, 'startedAt': 1,
            'completedAt': 2 if status != 'inProgress' else None,
            'durationMs': None}


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


class Transport:
    """Only local native-shaped data; unexpected methods fail closed."""
    def __init__(self, thread_id, cwd):
        self.thread = {'id': thread_id, 'cwd': str(cwd), 'ephemeral': False,
                       'path': '/native/server/rollout.jsonl', 'historyMode': 'legacy',
                       'model': 'native-model', 'reasoningEffort': 'high',
                       'status': {'type': 'idle'}, 'turns': [turn()]}
        self.calls = []
        self.events = []
        self.start_hook = None
        self.interrupt_hook = None
        self.receive_count = 0
        self.guard = threading.Lock()

    def call(self, method, params, *, deadline):
        with self.guard:
            self.calls.append((method, copy.deepcopy(params), deadline))
            if method == 'thread/read':
                if params.get('threadId') != self.thread['id']:
                    raise RuntimeError('thread not found')
                if params.get('includeTurns') is not True:
                    raise AssertionError('full-history read required')
                return {'thread': copy.deepcopy(self.thread)}
            if method == 'turn/start':
                self.assert_start(params)
                created = turn(params['clientUserMessageId'], params['input'][0]['text'], 'inProgress')
                self.thread['turns'].append(created)
                self.thread['status'] = {'type': 'active', 'activeFlags': []}
                if self.start_hook: self.start_hook(created)
                return {'turn': copy.deepcopy(created)}
            if method == 'turn/interrupt':
                if self.interrupt_hook: self.interrupt_hook(params)
                return {}
            raise AssertionError('forbidden RPC: ' + method)

    @staticmethod
    def assert_start(params):
        if set(params) != {'threadId', 'clientUserMessageId', 'input'}:
            raise AssertionError('turn/start must not carry configuration overrides')

    def receive(self, *, deadline):
        self.receive_count += 1
        if self.events: return self.events.pop(0)
        raise TimeoutError('offline event queue empty')

    def count(self, method): return sum(m == method for m, _, _ in self.calls)


class LifecycleAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cwd = self.root / 'work'
        self.cwd.mkdir()
        self.journal = self.root / 'journal'
        self.thread_id = str(uuid4())
        self.identity = lifecycle.TaskThread('task-incarnation-1', self.thread_id, str(self.cwd))
        self.clock = Clock()
        self.transport = Transport(self.thread_id, self.cwd)
        self.operation = str(uuid4())
        self.text = 'PROMPT_SECRET: perform the offline task'
        self.adapter = self.reopen()

    def reopen(self):
        return lifecycle.CodexTaskLifecycle(self.journal, self.identity, self.transport, clock=self.clock)

    def prepare(self): return self.adapter.prepare(self.operation, self.text, deadline=10)
    def submit(self):
        self.prepare()
        return self.adapter.submit(self.operation, deadline=10)
    def reconcile(self): return self.adapter.reconcile(self.operation, deadline=10)
    def fail_reply(self, created): raise ConnectionError('lost reply')
    def lost_submission(self):
        self.prepare()
        self.transport.start_hook = self.fail_reply
        snapshot = self.adapter.submit(self.operation, deadline=10)
        self.assertFalse(snapshot.terminal_proven)
        self.adapter = self.reopen()
        return snapshot

    def test_FR_CXTASK_LIFE_01_constructor_has_no_rpc_and_rejects_unsafe_journal(self):
        self.assertEqual(self.transport.calls, [])
        for location in [self.cwd / 'journal', self.root / 'link']:
            if location.name == 'link': location.symlink_to(self.cwd, target_is_directory=True)
            with self.subTest(location=location), self.assertRaises(lifecycle.LifecycleError):
                a = lifecycle.CodexTaskLifecycle(location, self.identity, self.transport, clock=self.clock)
                a.prepare(self.operation, self.text, deadline=10)
        self.assertEqual(self.transport.count('turn/start'), 0)

    def test_FR_CXTASK_LIFE_01_operation_id_is_not_a_path(self):
        for invalid in ['../../escape', 'not-a-uuid', str(uuid4())[:8]]:
            with self.subTest(invalid=invalid), self.assertRaises(lifecycle.LifecycleError):
                self.adapter.prepare(invalid, self.text, deadline=10)
        self.assertFalse((self.root / 'escape').exists())

    def test_FR_CXTASK_LIFE_02_prepare_survives_reopen_and_text_is_immutable(self):
        self.assertEqual(self.prepare().phase, 'prepared')
        self.adapter = self.reopen()
        self.assertEqual(self.prepare().phase, 'prepared')
        with self.assertRaises(lifecycle.LifecycleConflict):
            self.adapter.prepare(self.operation, 'different', deadline=10)
        self.assertEqual(self.transport.count('turn/start'), 0)
        self.assertEqual(self.adapter.submit(self.operation, deadline=10).phase, 'running')

    def test_FR_CXTASK_LIFE_02_atomic_replace_failure_prevents_submission(self):
        self.prepare()
        with patch.object(os, 'replace', side_effect=OSError('replace failed')):
            with self.assertRaises(lifecycle.JournalError):
                self.adapter.submit(self.operation, deadline=10)
        self.assertEqual(self.transport.count('turn/start'), 0)

    def test_FR_CXTASK_LIFE_02_fsync_failure_prevents_submission(self):
        self.prepare()
        with patch.object(os, 'fsync', side_effect=OSError('fsync failed')):
            with self.assertRaises(lifecycle.JournalError):
                self.adapter.submit(self.operation, deadline=10)
        self.assertEqual(self.transport.count('turn/start'), 0)

    def test_FR_CXTASK_LIFE_02_concurrent_adapters_submit_at_most_once(self):
        self.prepare()
        barrier = threading.Barrier(2)
        def send(_):
            adapter = self.reopen()
            barrier.wait(timeout=5)
            return adapter.submit(self.operation, deadline=10)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, range(2)))
        self.assertEqual(self.transport.count('turn/start'), 1)
        self.assertTrue(all(s.turn_id == results[0].turn_id for s in results))

    def test_FR_CXTASK_LIFE_03_lost_reply_recovers_only_marker_without_retry(self):
        self.lost_submission()
        expected = self.transport.thread['turns'][-1]['id']
        self.transport.thread['turns'].insert(1, turn(text=self.text))
        result = self.reconcile()
        self.assertEqual(result.turn_id, expected)
        self.assertEqual(result.phase, 'running')
        self.adapter.submit(self.operation, deadline=10)
        self.assertEqual(self.transport.count('turn/start'), 1)

    def test_FR_CXTASK_LIFE_04_ambiguous_history_never_retries_or_proves_terminal(self):
        mutations = {
            'no-marker': lambda t: t['items'][0].update(clientId=None),
            'altered-text': lambda t: t['items'][0]['content'][0].update(text='other'),
            'summary': lambda t: t.update(itemsView='summary'),
            'not-loaded': lambda t: t.update(itemsView='notLoaded', items=[]),
            'unknown-status': lambda t: t.update(status='mystery'),
            'duplicate-marker': lambda t: self.transport.thread['turns'].append(copy.deepcopy(t)),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                # Independent operation and journal for each fault.
                self.journal = self.root / ('journal-' + label)
                self.operation = str(uuid4())
                self.transport = Transport(self.thread_id, self.cwd)
                self.adapter = self.reopen()
                self.lost_submission()
                mutate(self.transport.thread['turns'][-1])
                result = self.adapter.submit(self.operation, deadline=10)
                self.assertEqual(result.phase, 'unknown')
                self.assertFalse(result.terminal_proven)
                self.assertEqual(self.transport.count('turn/start'), 1)

    def test_FR_CXTASK_LIFE_05_configuration_observed_and_identity_rechecked(self):
        prepared = self.prepare()
        self.assertEqual((prepared.model, prepared.reasoning_effort), ('native-model', 'high'))
        self.transport.thread['cwd'] = str(self.root)
        try:
            result = self.adapter.submit(self.operation, deadline=10)
            self.assertFalse(result.terminal_proven)
        except lifecycle.LifecycleError:
            pass
        self.assertEqual(self.transport.count('turn/start'), 0)

    def test_FR_CXTASK_LIFE_05_missing_materialization_or_paginated_history_blocks_start(self):
        for key, value in [('ephemeral', True), ('path', None), ('historyMode', 'paginated'), ('turns', [])]:
            with self.subTest(key=key):
                self.transport = Transport(self.thread_id, self.cwd)
                self.transport.thread[key] = value
                self.journal = self.root / ('invalid-' + key)
                self.adapter = self.reopen()
                try:
                    result = self.prepare()
                    self.assertNotEqual(result.phase, 'prepared')
                except lifecycle.LifecycleError:
                    pass
                self.assertEqual(self.transport.count('turn/start'), 0)

    def test_FR_CXTASK_LIFE_06_approval_unanswered_and_reconnect_does_not_infer_decision(self):
        result = self.submit()
        self.transport.events = [{'id': 7, 'method': 'item/commandExecution/requestApproval',
                                  'params': {'threadId': self.thread_id, 'turnId': result.turn_id,
                                             'itemId': 'item', 'command': 'APPROVAL_SECRET'}}]
        observed = self.adapter.observe(self.operation, deadline=10)
        self.assertEqual(observed.phase, 'waiting_approval')
        self.assertFalse(observed.terminal_proven)
        self.assertNotIn('APPROVAL_SECRET', observed.reason or '')
        self.adapter = self.reopen()
        self.assertEqual(self.reconcile().phase, 'running')
        self.assertTrue(all(m in {'thread/read', 'turn/start', 'turn/interrupt'} for m, _, _ in self.transport.calls))

    def test_FR_CXTASK_LIFE_06_foreign_and_unknown_requests_do_not_prove_success(self):
        result = self.submit()
        self.transport.events = [
            {'id': 1, 'method': 'unknown/requestApproval', 'params': {'secret': 'APPROVAL_SECRET'}},
            {'method': 'turn/completed', 'params': {'threadId': str(uuid4()),
              'turn': turn(self.operation, self.text, answer='FOREIGN')}}]
        observed = self.adapter.observe(self.operation, deadline=10)
        self.assertFalse(observed.terminal_proven)
        self.assertNotEqual(observed.final_text, 'FOREIGN')
        self.assertEqual(observed.turn_id, result.turn_id)

    def test_FR_CXTASK_LIFE_07_interrupt_ack_is_not_terminal_proof(self):
        started = self.submit()
        stopped = self.adapter.interrupt(self.operation, deadline=10)
        self.assertFalse(stopped.terminal_proven)
        params = [p for m, p, _ in self.transport.calls if m == 'turn/interrupt']
        self.assertEqual(params, [{'threadId': self.thread_id, 'turnId': started.turn_id}])

    def test_FR_CXTASK_LIFE_07_unmatched_submission_cannot_be_interrupted(self):
        self.lost_submission()
        self.transport.thread['turns'][-1]['items'][0]['clientId'] = None
        result = self.adapter.interrupt(self.operation, deadline=10)
        self.assertFalse(result.terminal_proven)
        self.assertEqual(self.transport.count('turn/interrupt'), 0)

    def test_FR_CXTASK_LIFE_07_stop_intent_write_failure_prevents_interrupt(self):
        self.submit()
        with patch.object(os, 'replace', side_effect=OSError('write failed')):
            with self.assertRaises(lifecycle.JournalError):
                self.adapter.interrupt(self.operation, deadline=10)
        self.assertEqual(self.transport.count('turn/interrupt'), 0)

    def test_FR_CXTASK_LIFE_08_post_effect_journal_failure_retains_no_retry_truth(self):
        self.prepare()
        def fail_after_send(created):
            os_patch = patch.object(os, 'replace', side_effect=OSError('storage lost'))
            os_patch.start()
            self.addCleanup(os_patch.stop)
        self.transport.start_hook = fail_after_send
        with self.assertRaises(lifecycle.JournalError):
            self.adapter.submit(self.operation, deadline=10)
        patch.stopall()
        self.adapter = self.reopen()
        self.adapter.submit(self.operation, deadline=10)
        self.assertEqual(self.transport.count('turn/start'), 1)

    def test_FR_CXTASK_LIFE_09_terminal_receipt_survives_and_foreign_active_is_visible(self):
        self.submit()
        native = self.transport.thread['turns'][-1]
        native['status'] = 'completed'
        native['items'].append({'type': 'agentMessage', 'id': 'answer', 'text': 'matched final', 'phase': 'final'})
        result = self.reconcile()
        self.assertTrue(result.terminal_proven)
        self.assertEqual(result.final_text, 'matched final')
        self.adapter = self.reopen()
        self.assertTrue(self.reconcile().terminal_proven)
        self.adapter.interrupt(self.operation, deadline=10)
        self.assertEqual(self.transport.count('turn/interrupt'), 0)
        foreign = turn(text='new native work', status='inProgress')
        self.transport.thread['turns'].append(foreign)
        inspection = self.adapter.inspect_thread(deadline=10)
        self.assertIn(foreign['id'], inspection['active_turn_ids'])
        self.assertNotIn('cleanup_allowed', inspection)
        with self.assertRaises(lifecycle.LifecycleError):
            self.adapter.prepare(str(uuid4()), 'new work', deadline=10)

    def test_FR_CXTASK_LIFE_10_failed_and_interrupted_are_distinct_terminal_outcomes(self):
        for outcome in ['failed', 'interrupted']:
            with self.subTest(outcome=outcome):
                self.transport = Transport(self.thread_id, self.cwd)
                self.operation = str(uuid4())
                self.journal = self.root / outcome
                self.adapter = self.reopen()
                self.submit()
                self.transport.thread['turns'][-1]['status'] = outcome
                result = self.reconcile()
                self.assertEqual(result.phase, outcome)
                self.assertTrue(result.terminal_proven)

    def test_FR_CXTASK_LIFE_10_expired_deadline_does_not_send_prepared_submission(self):
        self.prepare()
        self.clock.now = 11
        try:
            result = self.adapter.submit(self.operation, deadline=10)
            self.assertEqual(result.phase, 'prepared')
        except lifecycle.LifecycleError:
            pass
        self.assertEqual(self.transport.count('turn/start'), 0)
        self.clock.now = 0
        self.assertEqual(self.adapter.submit(self.operation, deadline=10).phase, 'running')


if __name__ == '__main__': unittest.main()
