"""Synthetic INV-WSESS-03 per-item history paging acceptance tests.

No native RPC, real history, authentication, timing gate, or production mutation.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest

from test_control_web_session_chat_contract import RPC, SID, TURN, feature


def native_turn(turn_id, items, **extra):
    return {'id': turn_id, 'status': 'completed', **extra, 'items': items}


def agent(item_id, text):
    return {'id': item_id, 'type': 'agentMessage', 'text': text}


def user(item_id, client_id, text):
    return {'id': item_id, 'type': 'userMessage', 'clientId': client_id,
            'content': [{'type': 'text', 'text': text}]}


class ItemPagingRPC(RPC):
    def __init__(self, root, turns=None, turn_cursor=None):
        super().__init__(root)
        self.turns = turns if turns is not None else [native_turn(TURN, [agent('a', 'answer')])]
        self.turn_cursor = turn_cursor
        self.item_pages = {}

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method in ('thread/read', 'thread/resume'):
            return {'thread': {'id': self.read_id, 'cwd': str(self.root)}}
        if method == 'thread/turns/list':
            # Correct native behavior for the requested metadata-only view.
            if params.get('itemsView') == 'notLoaded':
                metadata = [{k: v for k, v in row.items() if k != 'items'} | {'items': []}
                            for row in self.turns]
                next_cursor = None if params.get('cursor') is not None else self.turn_cursor
                return {'data': metadata, 'nextCursor': next_cursor}
            if params.get('itemsView') == 'full':
                # Same synthetic source data for legacy send_status/full-history behavior.
                return {'data': self.turns, 'nextCursor': self.turn_cursor}
            # The incident shape: full turn expansion is large enough to exceed frame cap.
            raise RuntimeError('synthetic full-turn response would close WebSocket 1009')
        if method == 'thread/items/list':
            key = (params['turnId'], params.get('cursor'))
            return self.item_pages[key]
        if method == 'thread/list':
            return self.list_response
        if method == 'turn/start':
            if self.start_error:
                raise self.start_error
            return self.start_response
        raise AssertionError('Unexpected synthetic RPC: ' + method)


class SessionChatItemsPaging(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-history-items-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.project = self.base / 'project'
        self.project.mkdir(mode=0o700)

    def chat(self, rpc):
        return self.module.SessionChat(rpc, lambda _: str(self.project), lambda: ['demo'],
                                       str(self.base / 'receipts'))

    def test_oversized_tool_turn_uses_not_loaded_metadata_and_preserves_commentary_and_steering(self):
        huge = 'x' * (4 * 1024 * 1024 + 1)
        turns = [native_turn(TURN, [])]
        rpc = ItemPagingRPC(self.project, turns)
        rpc.item_pages[(TURN, None)] = {'data': [
            {'turnId': TURN, 'item': {'id': 'tool', 'type': 'commandExecution', 'output': huge}},
            {'turnId': TURN, 'item': user('steer', 'client-steer-7', 'keep this steering text')},
            {'turnId': TURN, 'item': agent('comment', 'intermediate commentary')},
            {'turnId': TURN, 'item': user('initial', None, 'first user text')},
        ], 'nextCursor': None}
        result = self.chat(rpc).history('demo', SID)
        self.assertIn('turns', result, 'metadata and bounded item pages should avoid oversized full-turn frame')
        self.assertEqual([item['text'] for item in result['turns'][0]['items']],
                         ['first user text', 'intermediate commentary', 'keep this steering text'])
        self.assertNotIn(huge, json.dumps(result))
        self.assertIn(('thread/turns/list', {'threadId': SID, 'itemsView': 'notLoaded',
            'sortDirection': 'desc', 'limit': 4}), rpc.calls)
        self.assertIn(('thread/items/list', {'threadId': SID, 'turnId': TURN,
            'sortDirection': 'desc', 'limit': 32}), rpc.calls)

    def test_latest_and_older_keep_opaque_turn_cursor_and_chronological_items(self):
        latest = [native_turn(f'{i:08x}-1111-4111-8111-111111111111', []) for i in range(4)]
        rpc = ItemPagingRPC(self.project, latest, 'opaque/older?x=1')
        for row in latest:
            tid = row['id']
            rpc.item_pages[(tid, None)] = {'data': [
                {'turnId': tid, 'item': agent(f'{tid}-new', 'newest')},
                {'turnId': tid, 'item': agent(f'{tid}-old', 'oldest')}], 'nextCursor': None}
        chat = self.chat(rpc)
        first = chat.history('demo', SID)
        self.assertEqual(first['next_cursor'], 'opaque/older?x=1')
        self.assertEqual([i['text'] for i in first['turns'][0]['items']], ['oldest', 'newest'])
        self.assertIn(('thread/turns/list', {'threadId': SID, 'itemsView': 'notLoaded',
            'sortDirection': 'desc', 'limit': 4}), rpc.calls)
        older = chat.history('demo', SID, 'opaque/older?x=1')
        self.assertIn('turns', older, 'Older paging must return the synthetic older window')
        self.assertTrue(any(m == 'thread/turns/list' and p == {'threadId': SID,
            'itemsView': 'notLoaded', 'sortDirection': 'desc', 'limit': 8,
            'cursor': 'opaque/older?x=1'} for m, p in rpc.calls))
        self.assertEqual(older['next_cursor'], 'opaque/older?x=1')

    def test_four_item_pages_with_continuation_report_truncated_tail(self):
        rpc = ItemPagingRPC(self.project, [native_turn(TURN, [])])
        for n in range(4):
            cursor = None if n == 0 else f'page-{n}'
            nxt = f'page-{n+1}'
            rpc.item_pages[(TURN, cursor)] = {'data': [
                {'turnId': TURN, 'item': agent(f'i{n}', f'text-{n}') }], 'nextCursor': nxt}
        result = self.chat(rpc).history('demo', SID)
        self.assertIs(result.get('truncated'), True)
        item_calls = [p for m, p in rpc.calls if m == 'thread/items/list']
        self.assertEqual(len(item_calls), 4)
        self.assertEqual([p.get('cursor') for p in item_calls], [None, 'page-1', 'page-2', 'page-3'])

        # Every native page is below the 4 MiB frame cap, but the third would
        # cross the cumulative 8 MiB budget; it must be excluded and flagged.
        rpc = ItemPagingRPC(self.project, [native_turn(TURN, [])])
        text = 'z' * (3 * 1024 * 1024)
        for n in range(3):
            cursor = None if n == 0 else f'budget-page-{n}'
            rpc.item_pages[(TURN, cursor)] = {'data': [
                {'turnId': TURN, 'item': agent(f'budget-{n}', text)}],
                'nextCursor': f'budget-page-{n+1}'}
            self.assertLess(len(json.dumps(rpc.item_pages[(TURN, cursor)], separators=(',', ':')).encode()),
                            4 * 1024 * 1024, 'Each synthetic native page remains below the frame cap')
        result = self.chat(rpc).history('demo', SID)
        self.assertIs(result.get('truncated'), True)
        self.assertEqual(len(rpc.item_pages[(TURN, None)]['data'][0]['item']['text'].encode()), 3 * 1024 * 1024)
        self.assertEqual(len(result.get('turns', [{}])[0].get('items', [])), 2,
                         'The successfully received over-budget third page is not retained')
        self.assertEqual([item['id'] for item in result['turns'][0]['items']], ['budget-1', 'budget-0'])

    def test_wrong_turn_duplicate_cursor_and_malformed_page_are_unavailable(self):
        cases = [
            {'data': [{'turnId': 'foreign-turn', 'item': agent('a', 'wrong turn')}], 'nextCursor': None},
            {'data': [{'turnId': TURN, 'item': agent('a', 'one')}], 'nextCursor': 'again'},
            {'data': [{'turnId': TURN, 'item': agent('duplicate', 'one')},
                      {'turnId': TURN, 'item': agent('duplicate', 'two')}], 'nextCursor': None},
            {'data': [{'turnId': TURN, 'item': {'id': 'bad', 'type': 'agentMessage', 'text': 7}}], 'nextCursor': None},
        ]
        for page in cases:
            with self.subTest(page=page):
                rpc = ItemPagingRPC(self.project, [native_turn(TURN, [])])
                rpc.item_pages[(TURN, None)] = page
                rpc.item_pages[(TURN, 'again')] = page
                result = self.chat(rpc).history('demo', SID)
                self.assertEqual(result, {'error': 'unavailable'})
        self.assertTrue(any(m == 'thread/items/list' for m, _ in rpc.calls),
                                'The malformed synthetic item page must be inspected and rejected')

    def test_duplicate_metadata_turn_ids_and_invalid_turn_cursor_fail_closed(self):
        duplicate = [native_turn(TURN, []), native_turn(TURN, [])]
        rpc = ItemPagingRPC(self.project, duplicate)
        self.assertEqual(self.chat(rpc).history('demo', SID), {'error': 'unavailable'})
        self.assertTrue(any(m == 'thread/turns/list' and p.get('itemsView') == 'notLoaded'
                            for m, p in rpc.calls))
        rpc = ItemPagingRPC(self.project, [native_turn(TURN, [])], turn_cursor=4)
        self.assertEqual(self.chat(rpc).history('demo', SID), {'error': 'unavailable'})

    def test_send_status_still_uses_full_items_to_find_steering_client_id(self):
        rpc = ItemPagingRPC(self.project, [native_turn(TURN, [
            user('steer', '22222222-2222-4222-8222-222222222222', 'steering text')])])
        rpc.start_error = TimeoutError()
        chat = self.chat(rpc)
        chat.send('demo', SID, '22222222-2222-4222-8222-222222222222', 'steering text')
        result = chat.send_status('demo', SID, '22222222-2222-4222-8222-222222222222')
        self.assertEqual(result.get('status'), 'accepted')
        full_requests = [p for m, p in rpc.calls if m == 'thread/turns/list']
        self.assertTrue(any(p.get('itemsView') == 'full' for p in full_requests),
                        'send_status must retain full history search for clientUserMessageId')
        self.assertFalse(any(m == 'thread/items/list' for m, _ in rpc.calls))


if __name__ == '__main__':
    unittest.main()
