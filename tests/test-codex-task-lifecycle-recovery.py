"""Independent public-contract regressions for preserved local evidence.

Prepared intent without turn/start remains retryable after the exact baseline
returns. Durable terminal evidence survives native-history unavailability;
current thread inspection remains unknown and grants no cleanup permission.
"""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'blind_lifecycle_contract', Path(__file__).with_name('test-codex-task-lifecycle.py'))
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


class ReadFailureTransport(contract.Transport):
    def __init__(self, thread_id, cwd):
        super().__init__(thread_id, cwd)
        self.read_failure = None

    def call(self, method, params, *, deadline):
        if method == 'thread/read' and self.read_failure is not None:
            self.calls.append((method, copy.deepcopy(params), deadline))
            raise self.read_failure
        return super().call(method, params, deadline=deadline)


class RecoveryRegression(unittest.TestCase):
    def setUp(self):
        self.f = contract.LifecycleAcceptance()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.transport = ReadFailureTransport(self.f.thread_id, self.f.cwd)
        self.f.adapter = self.f.reopen()

    def blocked_submit(self):
        f = self.f
        try:
            snapshot = f.adapter.submit(f.operation, deadline=10)
            self.assertEqual(snapshot.phase, 'prepared')
            self.assertFalse(snapshot.terminal_proven)
        except contract.lifecycle.LifecycleError:
            pass
        self.assertEqual(f.transport.count('turn/start'), 0)

    def test_prepared_read_timeout_preserves_intent_until_baseline_returns(self):
        f = self.f
        f.prepare()
        f.transport.read_failure = TimeoutError('temporary native read timeout')
        self.blocked_submit()
        f.adapter = f.reopen()
        f.transport.read_failure = None
        result = f.adapter.submit(f.operation, deadline=10)
        self.assertEqual(result.phase, 'running')
        self.assertEqual(f.transport.count('turn/start'), 1)

    def test_prepared_foreign_activity_preserves_intent_and_exact_baseline(self):
        f = self.f
        f.prepare()
        baseline = copy.deepcopy(f.transport.thread)
        f.transport.thread['turns'].append(contract.turn(text='foreign', status='inProgress'))
        self.blocked_submit()
        # A foreign turn becoming terminal is not permission to adopt history.
        f.transport.thread['turns'][-1]['status'] = 'completed'
        self.blocked_submit()
        f.adapter = f.reopen()
        f.transport.thread = baseline
        result = f.adapter.submit(f.operation, deadline=10)
        self.assertEqual(result.phase, 'running')
        self.assertEqual(f.transport.count('turn/start'), 1)

    def terminal_receipt(self):
        f = self.f
        started = f.submit()
        native = f.transport.thread['turns'][-1]
        native['status'] = 'completed'
        native['items'].append({'type': 'agentMessage', 'id': 'receipt-answer',
                               'text': 'durable final text', 'phase': 'final'})
        receipt = f.reconcile()
        self.assertEqual(receipt.phase, 'completed')
        self.assertTrue(receipt.terminal_proven)
        self.assertEqual(receipt.turn_id, started.turn_id)
        self.assertEqual(receipt.final_text, 'durable final text')
        f.adapter = f.reopen()
        return receipt

    def assert_receipt(self, result, receipt):
        self.assertEqual(result.phase, receipt.phase)
        self.assertTrue(result.terminal_proven)
        self.assertEqual(result.turn_id, receipt.turn_id)
        self.assertEqual(result.final_text, receipt.final_text)

    def test_terminal_receipt_survives_read_timeout(self):
        receipt = self.terminal_receipt()
        self.f.transport.read_failure = TimeoutError('native unavailable')
        self.assert_receipt(self.f.reconcile(), receipt)

    def test_terminal_receipt_survives_read_not_found(self):
        receipt = self.terminal_receipt()
        self.f.transport.read_failure = RuntimeError('thread not found')
        self.assert_receipt(self.f.reconcile(), receipt)

    def test_unavailable_current_history_inspection_remains_unknown(self):
        self.terminal_receipt()
        self.f.transport.read_failure = TimeoutError('native unavailable')
        inspection = self.f.adapter.inspect_thread(deadline=10)
        self.assertFalse(inspection['identity_valid'])
        self.assertTrue(inspection['reason'])
        self.assertNotIn('cleanup_allowed', inspection)

    def test_terminal_interrupt_with_unavailable_history_retains_receipt(self):
        receipt = self.terminal_receipt()
        self.f.transport.read_failure = TimeoutError('native unavailable')
        result = self.f.adapter.interrupt(self.f.operation, deadline=10)
        self.assert_receipt(result, receipt)
        self.assertEqual(self.f.transport.count('turn/interrupt'), 0)


if __name__ == '__main__':
    unittest.main()
