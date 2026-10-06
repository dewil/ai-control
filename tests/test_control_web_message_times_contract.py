"""Independent INV-WSESS-20 tests; synthetic RPC only, no implementation reads."""
import os
from pathlib import Path
import tempfile
import unittest
from test_control_web_session_chat_contract import RPC, SID, TURN, feature, turn


class MessageTimesContract(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        self.tmp = tempfile.TemporaryDirectory(prefix='web-message-times-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rpc = RPC(self.root)
        module = feature(self, '_control_web_sessions')
        self.chat = module.SessionChat(self.rpc, lambda alias: str(self.root), lambda: ['demo'], str(self.root/'receipts'))

    def project(self, started, present=True):
        frame = turn(client_id='22222222-2222-4222-8222-222222222222')
        frame['completedAt'] = 1700000100
        if present:
            frame['startedAt'] = started
        # Item-local invented timestamps cannot override enclosing Turn.
        for item in frame['items']:
            item['timestamp'] = 1700000200
        self.rpc.pages[None] = {'data': [frame], 'nextCursor': None}
        before = len(self.rpc.calls)
        result = self.chat.history('demo', SID)
        self.assertIn('turns', result)
        items = result['turns'][0]['items']
        self.assertEqual({i['role'] for i in items}, {'user', 'assistant'})
        self.assertEqual([m for m, _ in self.rpc.calls[before:]],
                         ['thread/read', 'thread/turns/list', 'thread/items/list'])
        self.assertFalse(self.rpc.starts())
        return items

    def assert_time(self, items, timestamp, precision):
        for item in items:
            self.assertIn('timestamp', item, 'INV-WSESS-20 additive timestamp missing')
            self.assertIn('time_precision', item, 'INV-WSESS-20 additive precision missing')
            self.assertEqual(item['timestamp'], timestamp)
            self.assertEqual(item['time_precision'], precision)
            self.assertEqual(set(item), {'id', 'role', 'text', 'truncated', 'timestamp', 'time_precision'})
            self.assertFalse(item['truncated'])

    def test_valid_integer_bounds_zero_and_future_preserved_for_both_roles(self):
        for value in (0, 1700000000, 253402300799):
            with self.subTest(value=value):
                self.assert_time(self.project(value), value, 'turn')

    def test_missing_and_null_have_no_completed_or_item_fallback(self):
        self.assert_time(self.project(None, False), None, 'unknown')
        self.assert_time(self.project(None), None, 'unknown')

    def test_malformed_boolean_fraction_string_and_out_of_range_are_unknown(self):
        for value in (True, False, -1, 253402300800, 1700000000.5, 1700000000.0, '1700000000', [], {}):
            with self.subTest(value=value):
                self.assert_time(self.project(value), None, 'unknown')

    def test_each_turn_owns_time_and_older_cursor_uses_same_projection(self):
        frames = []
        for index, started in enumerate((1700000000, 0, None)):
            frame = turn(turn_id=f'turn-{index}')
            frame['startedAt'] = started
            for item in frame['items']:
                item['id'] = f"{item['id']}-{index}"
            frames.append(frame)
        self.rpc.pages['opaque-older'] = {'data': frames, 'nextCursor': 'next-opaque'}
        result = self.chat.history('demo', SID, 'opaque-older')
        self.assertEqual(result.get('next_cursor'), 'next-opaque')
        for frame, expected in zip(result['turns'], (1700000000, 0, None)):
            self.assert_time(frame['items'], expected, 'unknown' if expected is None else 'turn')
        turn_page_calls = [(method, params) for method, params in self.rpc.calls
                           if method == 'thread/turns/list']
        self.assertEqual(turn_page_calls[-1][1]['cursor'], 'opaque-older')


if __name__ == '__main__':
    unittest.main()
