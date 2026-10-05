"""Blind synthetic resume-size contract; not a native transport reproduction.

The fake models a version-specific server returning full turns unless requested
otherwise, and a receiver with a fixed 4 MiB budget. No live RPC is used.
"""
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
SID = '11111111-1111-4111-8111-111111111111'
MID = '22222222-2222-4222-8222-222222222222'
TURN = '33333333-3333-4333-8333-333333333333'
OTHER = '44444444-4444-4444-8444-444444444444'
BUDGET = 4 * 1024 * 1024
TEXT = 'Synthetic explicit user message'


class BoundedResumeRPC:
    """Synthetic response-shape semantics and bounded JSON receiver."""
    def __init__(self, root, *, large=True, status='idle'):
        self.root = root
        self.large = large
        self.status = status
        self.calls = []
        self.response_sizes = []
        self.resume_id = SID
        self.resume_root = root
        self.read_root = root
        self.start_error = None
        self.resume_error = None
        self.before_start = None
        self.sticky = {'model': 'synthetic-preserved-model', 'reasoningEffort': 'high',
                       'approvalPolicy': 'on-request', 'sandbox': 'read-only',
                       'cwd': str(root)}
        self.initial_sticky = dict(self.sticky)

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method == 'thread/read':
            return {'thread': {'id': SID, 'cwd': str(self.read_root)}}
        if method == 'thread/resume':
            if self.resume_error:
                raise self.resume_error
            # The fake makes any attempted settings override observable as well
            # as the tests requiring the exact public observational payload.
            for key in self.sticky:
                if key in params:
                    self.sticky[key] = params[key]
            metadata = {'id': self.resume_id, 'cwd': str(self.resume_root),
                        'status': {'type': self.status}}
            response = {'thread': metadata, **self.sticky}
            if params.get('excludeTurns') is not True:
                metadata['turns'] = [{'id': TURN, 'status': 'completed', 'items': [
                    {'id': 'synthetic-long-item', 'type': 'agentMessage',
                     'text': 'x' * (BUDGET + 1024) if self.large else 'small history'}]}]
            size = len(json.dumps(response, separators=(',', ':')).encode('utf-8'))
            self.response_sizes.append(size)
            if size > BUDGET:
                raise ConnectionError('synthetic fixed receiver budget exceeded')
            return response
        if method == 'turn/start':
            if self.before_start:
                self.before_start()
            if self.start_error:
                raise self.start_error
            # Active native steering may acknowledge the same turn id.
            return {'turn': {'id': TURN}}
        raise AssertionError('Send must not fetch history or issue extra RPC: ' + method)

    def starts(self):
        return [p for m, p in self.calls if m == 'turn/start']


class ResumeSizeContract(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-resume-size-test-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.project = self.base / 'project'
        self.project.mkdir(mode=0o700)
        self.receipts = self.base / 'receipts'
        self.rpc = BoundedResumeRPC(self.project)
        self.chat = self.new_chat()

    def resolve(self, alias):
        if alias != 'demo':
            raise ValueError('unknown synthetic project')
        return str(self.project)

    def new_chat(self):
        return self.module.SessionChat(self.rpc, self.resolve, lambda: ['demo'], str(self.receipts))

    def send(self, text=TEXT):
        return self.chat.send('demo', SID, MID, text)

    def receipt(self, status, tid=None):
        return {'status': status, 'message_id': MID, 'turn_id': tid}

    def expected_send_calls(self):
        return [('thread/read', {'threadId': SID, 'includeTurns': False}),
                ('thread/resume', {'threadId': SID, 'excludeTurns': True}),
                ('turn/start', {'threadId': SID,
                 'input': [{'type': 'text', 'text': TEXT}], 'clientUserMessageId': MID})]

    def assert_reserved(self):
        files = [p for p in self.receipts.rglob('*') if p.is_file()]
        self.assertTrue(files, 'Durable receipt must exist before turn/start')
        self.assertTrue(any(MID in p.read_text() for p in files))
        for path in files:
            self.assertNotIn(TEXT, path.read_text())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.receipts.stat().st_mode), 0o700)

    def test_INV_WSESS_04_exact_metadata_resume_even_for_small_thread(self):
        self.rpc.large = False
        self.assertEqual(self.send(), self.receipt('accepted', TURN))
        self.assertEqual(self.rpc.calls, self.expected_send_calls())
        self.assertEqual(self.rpc.sticky, self.rpc.initial_sticky)

    def assert_large_metadata_send(self, status):
        self.rpc.status = status
        self.rpc.before_start = self.assert_reserved
        self.assertEqual(self.send(), self.receipt('accepted', TURN),
                         'Metadata resume must allow send under the fixed receiver budget')
        self.assertEqual(self.rpc.calls, self.expected_send_calls())
        self.assertEqual(len(self.rpc.response_sizes), 1)
        self.assertLess(self.rpc.response_sizes[0], 4096)
        self.assertEqual(self.rpc.sticky, self.rpc.initial_sticky)
        # INV-WSESS-05: repeat and restart preserve UUID dedup without another
        # resume/start; changed text under that UUID remains invalid.
        self.assertEqual(self.send(), self.receipt('accepted', TURN))
        self.chat = self.new_chat()
        self.assertEqual(self.send(), self.receipt('accepted', TURN))
        self.assertEqual(self.send('Changed text'), {'error': 'invalid_request'})
        self.assertEqual(len(self.rpc.starts()), 1)
        self.assertEqual(sum(m == 'thread/resume' for m, _ in self.rpc.calls), 1)
        self.assertTrue(all(m in ('thread/read', 'thread/resume', 'turn/start')
                            for m, _ in self.rpc.calls))

    def test_INV_WSESS_04_05_07_large_idle_metadata_send_is_bounded_and_deduplicated(self):
        self.assert_large_metadata_send('idle')

    def test_INV_WSESS_04_05_07_large_active_metadata_send_preserves_same_turn(self):
        self.assert_large_metadata_send('active')

    def test_INV_WSESS_02_04_metadata_resume_still_proves_root_and_thread(self):
        self.rpc.large = False
        other = self.base / 'other-project'
        other.mkdir(mode=0o700)
        for changed_id, changed_root in ((OTHER, self.project), (SID, other)):
            with self.subTest(changed_id=changed_id, changed_root=changed_root.name):
                self.rpc.calls.clear()
                self.rpc.resume_id = changed_id
                self.rpc.resume_root = changed_root
                self.assertEqual(self.send(), {'error': 'stale'})
                self.assertEqual(self.rpc.starts(), [])
                self.assertEqual(self.rpc.calls, self.expected_send_calls()[:2])

    def test_INV_WSESS_02_fresh_read_proof_blocks_resume_and_send(self):
        other = self.base / 'rebound-project'
        other.mkdir(mode=0o700)
        self.rpc.read_root = other
        self.assertEqual(self.send(), {'error': 'stale'})
        self.assertEqual(self.rpc.calls, self.expected_send_calls()[:1])

    def test_INV_WSESS_04_05_07_lost_ack_after_bounded_resume_never_resends(self):
        self.rpc.start_error = TimeoutError('synthetic private ACK diagnostic')
        self.rpc.before_start = self.assert_reserved
        expected = self.receipt('delivery_unknown')
        self.assertEqual(self.send(), expected)
        self.assertEqual(self.rpc.calls, self.expected_send_calls())
        self.chat = self.new_chat()
        self.assertEqual(self.send(), expected)
        self.assertEqual(self.send('Changed text'), {'error': 'invalid_request'})
        self.assertEqual(len(self.rpc.starts()), 1)
        self.assertEqual(sum(m == 'thread/resume' for m, _ in self.rpc.calls), 1)
        self.assertNotIn('diagnostic', json.dumps(expected))

    def test_INV_WSESS_02_07_resume_error_does_not_send_or_expose_raw_error(self):
        self.rpc.resume_error = ConnectionError('synthetic private resume diagnostic')
        result = self.send()
        self.assertEqual(result, {'error': 'unavailable'})
        self.assertEqual(self.rpc.starts(), [])
        self.assertNotIn('diagnostic', json.dumps(result))

    def test_fake_receiver_distinguishes_full_history_from_metadata(self):
        # Fixture control only; establishes the discriminating input, without
        # claiming an actual native 0.160 transport failure was reproduced.
        with self.assertRaises(ConnectionError):
            self.rpc('thread/resume', {'threadId': SID})
        self.assertGreater(self.rpc.response_sizes[-1], BUDGET)
        response = self.rpc('thread/resume', {'threadId': SID, 'excludeTurns': True})
        self.assertNotIn('turns', response['thread'])
        self.assertLess(self.rpc.response_sizes[-1], 4096)
        self.assertEqual(response['thread']['id'], SID)
        self.assertEqual(response['thread']['cwd'], str(self.project))


if __name__ == '__main__':
    unittest.main()
