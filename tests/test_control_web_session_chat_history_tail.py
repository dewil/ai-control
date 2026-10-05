"""Independent synthetic INV-WSESS-09 tests from the public history-tail spec.

No native RPC, real history, authentication, timing gate, or implementation reads.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_control_web_session_chat_contract import RPC, SID, TURN, feature

LIMIT = 96 * 1024


def agent(index, text='synthetic text', item_id=None):
    return {'id': item_id or f'item-{index}', 'type': 'agentMessage', 'text': text}


def native_turn(index, items, turn_id=None):
    return {'id': turn_id or f'turn-{index}', 'status': 'completed', 'items': items}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


class SerializationBudgetExceeded(RuntimeError):
    """Stop an old expensive loop without creating a CI wall-clock gate."""


class HistoryTailContract(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-history-tail-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.project = self.base / 'project'
        self.project.mkdir(mode=0o700)
        self.rpc = RPC(self.project)
        self.resolutions = []
        self.chat = self.module.SessionChat(self.rpc, self.resolve, lambda: ['demo'], str(self.base / 'receipts'))

    def resolve(self, alias):
        self.resolutions.append(alias)
        if alias != 'demo':
            raise ValueError('synthetic invalid project')
        return str(self.project)

    def page(self, turns, next_cursor=None, cursor=None):
        self.rpc.pages[cursor] = {'data': turns, 'nextCursor': next_cursor}

    def bounded_history(self, cursor=None):
        original = self.module._json
        self.whole_serializations = 0
        def count(value, *args, **kwargs):
            if isinstance(value, dict) and 'turns' in value:
                self.whole_serializations += 1
                if self.whole_serializations > 4:
                    raise SerializationBudgetExceeded('synthetic whole-history serialization budget')
            return original(value, *args, **kwargs)
        with patch.object(self.module, '_json', side_effect=count):
            result = self.chat.history('demo', SID, cursor)
        self.assertIn('turns', result, 'Valid full page must yield a bounded history, not unavailable')
        self.assertLessEqual(self.whole_serializations, 4)
        self.assertLessEqual(len(encoded(result)), LIMIT)
        return result

    def test_4096_messages_newest128_with_at_most_four_whole_exports(self):
        safe_text = 'safe word ' * 51 + 'ok'
        self.assertEqual(len(safe_text), 512)
        items = [agent(i, safe_text) for i in range(4096)]
        frame = {'data': [native_turn(0, items)], 'nextCursor': 'opaque-older'}
        self.assertLessEqual(len(encoded(frame)), 4 * 1024 * 1024)
        self.rpc.pages[None] = frame
        # Older retains the pre-05.10 128-item/work-budget contract.
        self.rpc.pages['older-fixture'] = self.rpc.pages[None]
        result = self.bounded_history(cursor='older-fixture')
        selected = result['turns'][0]['items']
        self.assertEqual([i['id'] for i in selected], [f'item-{i}' for i in range(3968, 4096)])
        self.assertTrue(all(i['text'] == safe_text and i['truncated'] is False for i in selected))
        self.assertIs(result['truncated'], True)
        self.assertEqual(result['next_cursor'], 'opaque-older')

    def test_newest_turn_priority_and_chronological_items_preserve_all_metadata(self):
        self.page([native_turn(t, [agent(f'{t}-{i}') for i in range(24)]) for t in range(8)], 'native-next')
        # Older retains the pre-05.10 128-item/work-budget contract.
        self.rpc.pages['older-fixture'] = self.rpc.pages[None]
        result = self.bounded_history(cursor='older-fixture')
        self.assertEqual([t['id'] for t in result['turns']], [f'turn-{t}' for t in range(8)])
        self.assertTrue(all(t['status'] == 'completed' for t in result['turns']))
        self.assertEqual([[i['id'] for i in t['items']] for t in result['turns']],
                         [[f'item-{t}-{i}' for i in range(24)] for t in range(5)] +
                         [[f'item-5-{i}' for i in range(16, 24)], [], []])
        self.assertIs(result['truncated'], True)

    def test_unsupported_and_image_only_items_do_not_consume_text_limit(self):
        items = []
        for i in range(128):
            items.extend([{'id': f'tool-{i}', 'type': 'commandExecution', 'output': 'not exported'},
                          {'id': f'image-{i}', 'type': 'userMessage', 'content': [{'type': 'image', 'url': 'private://synthetic'}]},
                          agent(i)])
        items.append({'id': 'future', 'type': 'futureItem', 'text': 'not exported'})
        self.page([native_turn(0, items)])
        # Older retains the pre-05.10 128-item/work-budget contract.
        self.rpc.pages['older-fixture'] = self.rpc.pages[None]
        result = self.bounded_history(cursor='older-fixture')
        self.assertEqual([i['id'] for i in result['turns'][0]['items']], [f'item-{i}' for i in range(128)])
        self.assertIs(result['truncated'], False)

    def test_empty_user_text_parts_are_eligible_for_newest128(self):
        items = [agent('oldest')]
        items += [{'id': f'empty-{i}', 'type': 'userMessage', 'content': [{'type': 'text', 'text': ''}]} for i in range(128)]
        self.page([native_turn(0, items)])
        # Older retains the pre-05.10 128-item/work-budget contract.
        self.rpc.pages['older-fixture'] = self.rpc.pages[None]
        result = self.bounded_history(cursor='older-fixture')
        self.assertEqual([i['id'] for i in result['turns'][0]['items']], [f'empty-{i}' for i in range(128)])
        self.assertTrue(all(i['text'] == '' and i['role'] == 'user' and i['truncated'] is False for i in result['turns'][0]['items']))
        self.assertIs(result['truncated'], True)

    def test_encoded_budget_reserves_exact_cursor_receipts_attention_and_turn_metadata(self):
        receipts = []
        for i in range(9):
            mid = f'{i+1:08x}-2222-4222-8222-222222222222'
            receipt = self.chat.send('demo', SID, mid, 'Synthetic receipt only')
            self.assertEqual(receipt['status'], 'accepted')
            receipts.append(receipt)
        # Unicode, quotes, backslashes and control bytes require exact JSON/UTF-8 accounting.
        body = ('界👋"\\\n\t\x01' * 1200)[:8000]
        ids = ['界' * 499 + str(t) for t in range(8)]
        cursor = ('界"\\\x01' * 1024)[:4096]
        self.rpc.metadata_status = {'type': 'active', 'activeFlags': ['waitingOnApproval']}
        self.page([native_turn(t, [agent(f'{t}-{i}', body, item_id='項' * 497 + f'{t}-{i}') for i in range(8)], ids[t])
                   for t in range(8)], cursor)
        # Older retains the pre-05.10 128-item/work-budget contract.
        self.rpc.pages['older-fixture'] = self.rpc.pages[None]
        result = self.bounded_history(cursor='older-fixture')
        self.assertEqual([t['id'] for t in result['turns']], ids)
        self.assertTrue(all(t['status'] == 'completed' for t in result['turns']))
        self.assertEqual(result['next_cursor'], cursor)
        self.assertCountEqual(result['recent_sends'], receipts[-8:])
        self.assertIs(result['needs_native_attention'], True)
        self.assertIs(result['truncated'], True)
        newest = result['turns'][0]['items']
        self.assertTrue(newest)
        self.assertEqual(newest[-1]['id'], '項' * 497 + '0-7')
        self.assertEqual(newest[-1]['text'], body, 'Older items cannot shorten the newest fully fitting text')
        self.assertIs(newest[-1]['truncated'], False)
        for turn in result['turns']:
            for item in turn['items']:
                self.assertTrue(body.startswith(item['text']))
                self.assertLessEqual(len(item['text']), 8000)
                self.assertIs(item['truncated'], len(item['text']) < len(body))
        partials = [(ti, ii, item) for ti, turn in enumerate(result['turns'])
                    for ii, item in enumerate(turn['items']) if item['truncated']]
        self.assertEqual(len(partials), 1, 'Only the final selected older message may use a partial budget prefix')
        ti, ii, partial = partials[0]
        self.assertTrue(partial['text'])
        longer = json.loads(encoded(result))
        longer['turns'][ti]['items'][ii]['text'] += body[len(partial['text'])]
        self.assertGreater(len(encoded(longer)), LIMIT, 'Available encoded budget must not discard an additional fitting character')
        encoded(result).decode('utf-8')

    def test_redaction_before8000_prefix_clipping(self):
        self.page([native_turn(0, [agent(0, 'token=synthetic-private-tail-value ' + 'я' * 9000)])])
        result = self.bounded_history()
        item = result['turns'][0]['items'][0]
        self.assertNotIn('synthetic-private-tail-value', item['text'])
        self.assertNotIn('synthetic-private-tail-value', encoded(result).decode('utf-8'))
        self.assertEqual(len(item['text']), 8000)
        self.assertIs(item['truncated'], True)
        self.assertIs(result['truncated'], True)

    def test_discarded_older_malformed_items_fail_closed(self):
        malformed = [agent(0, 7), {'id': 'bad-user', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 7}]},
                     {'type': 'futureItem', 'text': 'missing required native item id'}]
        for bad in malformed:
            with self.subTest(item_type=bad['type']):
                self.page([native_turn(0, [bad] + [agent(i) for i in range(128)])])
                self.assertEqual(self.chat.history('demo', SID), {'error': 'unavailable'})
        self.assertFalse(self.rpc.starts())

    def test_small_response_exact_contract_and_fresh_metadata_exact_opaque_cursor_rpc(self):
        cursor = 'opaque-input/"界'
        self.page([native_turn(0, [agent(0, 'small answer')], TURN)], 'opaque-output', cursor)
        expected = {'turns': [{'id': TURN, 'status': 'completed', 'items': [
            {'id': 'item-0', 'role': 'assistant', 'text': 'small answer', 'truncated': False, 'timestamp': None, 'time_precision': 'unknown'}]}],
            'next_cursor': 'opaque-output', 'truncated': False, 'recent_sends': []}
        for _ in range(2):
            self.assertEqual(self.bounded_history(cursor), expected)
        self.assertEqual(self.rpc.calls, [('thread/read', {'threadId': SID, 'includeTurns': False}),
            ('thread/turns/list', {'threadId': SID, 'itemsView': 'full', 'sortDirection': 'desc', 'limit': 8, 'cursor': cursor})] * 2)
        self.assertGreaterEqual(len(self.resolutions), 2)

    def test_deadline_expired_after_frame_is_not_partial_history(self):
        clock = [100.0]
        original_rpc = self.rpc.__call__
        def expired_rpc(method, params):
            result = original_rpc(method, params)
            if method == 'thread/turns/list':
                clock[0] += 56
            return result
        chat = self.module.SessionChat(expired_rpc, self.resolve, lambda: ['demo'], str(self.base / 'deadline-receipts'))
        with patch('time.monotonic', side_effect=lambda: clock[0]):
            self.assertEqual(chat.history('demo', SID), {'error': 'unavailable'})
        self.assertFalse(self.rpc.starts())

    def test_deadline_expired_during_export_is_not_success(self):
        clock = [100.0]
        original_json = self.module._json
        exports = []
        def expire(value, *args, **kwargs):
            if isinstance(value, dict) and 'turns' in value:
                exports.append(1)
                clock[0] = 156.0
            return original_json(value, *args, **kwargs)
        with patch('time.monotonic', side_effect=lambda: clock[0]), patch.object(self.module, '_json', side_effect=expire):
            result = self.chat.history('demo', SID)
        self.assertTrue(exports, 'Synthetic clock expires while whole history is prepared')
        self.assertEqual(result, {'error': 'unavailable'})
        self.assertFalse(self.rpc.starts())


if __name__ == '__main__':
    unittest.main()
