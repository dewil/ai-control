"""Source-blind compact contract: frozen 05.10 spec, synthetic RPC only."""
import os
from pathlib import Path
import tempfile
import unittest
from test_control_web_session_chat_contract import RPC, SID, TURN, feature
from test_control_web_session_chat_history_tail import agent, native_turn, encoded, LIMIT


class CompactHistoryContract(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-compact-history-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.rpc = RPC(self.root)
        self.chat = self.module.SessionChat(self.rpc, lambda _: str(self.root), lambda: ['demo'], str(self.root / 'receipts'))

    def test_INV_WSESS_10_latest_open_and_poll_limit4_older_limit8_fresh_proof(self):
        cursor = 'opaque/"界 older'
        self.rpc.pages[cursor] = self.rpc.pages[None]
        for page in (None, None, cursor):
            self.assertIn('turns', self.chat.history('demo', SID, page))
        expected = []
        for page, limit in ((None, 4), (None, 4), (cursor, 8)):
            params = {'threadId': SID, 'itemsView': 'notLoaded', 'sortDirection': 'desc', 'limit': limit}
            if page is not None: params['cursor'] = page
            expected += [('thread/read', {'threadId': SID, 'includeTurns': False}),
                         ('thread/turns/list', params),
                         ('thread/items/list', {'threadId': SID, 'turnId': TURN,
                                                'sortDirection': 'desc', 'limit': 32})]
        self.assertEqual(self.rpc.calls, expected)
        self.assertFalse(self.rpc.starts())

    def test_INV_WSESS_10_latest_newest24_older_newest128_exact_cursor_and_validation(self):
        items = [agent(i) for i in range(160)]
        self.rpc.pages[None] = {'data': [native_turn(0, items)], 'nextCursor': 'exact-next/界'}
        self.rpc.pages['older-fixture'] = self.rpc.pages[None]
        before_latest = len(self.rpc.calls)
        latest = self.chat.history('demo', SID)
        latest_item_requests = [params for method, params in self.rpc.calls[before_latest:]
                                if method == 'thread/items/list']
        before_older = len(self.rpc.calls)
        older = self.chat.history('demo', SID, 'older-fixture')
        older_item_requests = [params for method, params in self.rpc.calls[before_older:]
                               if method == 'thread/items/list']
        for result in (latest, older):
            self.assertIn('turns', result)
            self.assertIs(result['truncated'], True)
            self.assertEqual(result['next_cursor'], 'exact-next/界')
            self.assertLessEqual(len(encoded(result)), LIMIT)
        self.assertEqual([i['id'] for i in older['turns'][0]['items']], [f'item-{i}' for i in range(32, 160)])
        for requests in (latest_item_requests, older_item_requests):
            self.assertLessEqual(len(requests), 4)
            self.assertTrue(all(params['limit'] == 32 for params in requests))
        # An invalid native item within the bounded newest128 scan fails closed.
        for cursor in (None, 'older-fixture'):
            tail = items[:33] + [agent('invalid', 7)] + items[33:]
            self.rpc.pages[cursor] = {'data': [native_turn(0, tail)], 'nextCursor': None}
            self.assertEqual(self.chat.history('demo', SID, cursor), {'error': 'unavailable'})
        self.assertEqual([i['id'] for i in latest['turns'][0]['items']], [f'item-{i}' for i in range(136, 160)])


if __name__ == '__main__': unittest.main()
