"""Blind INV-WSESS-20/21 producer item-start projection and visible fallback.

Frozen from pre-code norm30ab539. Synthetic RPC/browser only, no source reads.
Existing fixture modules are namespaces, so their tests are not rediscovered.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest

import test_control_web_message_times_browser as browser_fixture

NOW = browser_fixture.NOW
OLD_TURN = NOW - 25 * 60
MAX_MS = 253402300799999
OMITTED = object()


class ItemMessageTimesBackend(unittest.TestCase):
    def setUp(self):
        # Browser runner intentionally has Playwright only; backend fixtures
        # require FastAPI and are imported only in their own server/test venv.
        global contract, paging
        import test_control_web_session_chat_contract as contract
        import test_control_web_session_chat_items_paging as paging
        self.module = contract.feature(self, '_control_web_sessions')
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='web-item-start-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir(mode=0o700)

    def history(self, starts, *, turn_started=OLD_TURN, completed=OMITTED):
        metadata = paging.native_turn(contract.TURN, [])
        if turn_started is not OMITTED:
            metadata['startedAt'] = turn_started
        rpc = paging.ItemPagingRPC(self.project, [metadata])
        # Native item pages are descending; projection preserves chronological
        # user then assistant. Timing belongs to each entry, not inside item.
        natives = [paging.agent('assistant-own', 'own recent assistant'),
                   paging.user('user-own', None, 'own recent user')]
        entries = []
        for native, started in zip(natives, starts):
            entry = {'turnId': contract.TURN, 'item': native}
            if started is not OMITTED:
                entry['startedAtMs'] = started
            if completed is not OMITTED:
                entry['completedAtMs'] = completed
            entries.append(entry)
        rpc.item_pages[(contract.TURN, None)] = {'data': entries, 'nextCursor': None}
        chat = self.module.SessionChat(rpc, lambda _: str(self.project), lambda: ['demo'],
                                       str(self.root / 'receipts'))
        return chat.history('demo', contract.SID), rpc

    def items(self, result):
        self.assertIn('turns', result, 'valid native timing schema must remain readable')
        items = result['turns'][0]['items']
        self.assertEqual([item['id'] for item in items], ['user-own', 'assistant-own'])
        self.assertEqual([item['role'] for item in items], ['user', 'assistant'])
        for item in items:
            self.assertEqual(set(item), {'id', 'role', 'text', 'truncated', 'timestamp', 'time_precision'})
        return {item['id']: item for item in items}

    def test_distinct_recent_item_times_replace_one_old_turn_time(self):
        result, rpc = self.history([(NOW - 60) * 1000 + 999, (NOW - 120) * 1000 + 1])
        items = self.items(result)
        self.assertEqual((items['assistant-own']['timestamp'], items['assistant-own']['time_precision']),
                         (NOW - 60, 'item'))
        self.assertEqual((items['user-own']['timestamp'], items['user-own']['time_precision']),
                         (NOW - 120, 'item'))
        self.assertFalse(rpc.starts())

    def test_item_floor_zero_and_maximum_date_bounds(self):
        for milliseconds in (0, 999, 1001, MAX_MS):
            with self.subTest(milliseconds=milliseconds):
                result, rpc = self.history([milliseconds, milliseconds])
                for item in self.items(result).values():
                    self.assertEqual((item['timestamp'], item['time_precision']), (milliseconds // 1000, 'item'))

    def test_missing_null_negative_and_date_overflow_fall_back_to_valid_turn(self):
        for started in (OMITTED, None, -1, -(2 ** 63), MAX_MS + 1, 2 ** 63 - 1):
            with self.subTest(started='omitted' if started is OMITTED else started):
                result, rpc = self.history([started, started])
                for item in self.items(result).values():
                    self.assertEqual((item['timestamp'], item['time_precision']), (OLD_TURN, 'turn'))

    def test_no_turn_fallback_is_unknown_and_completion_is_never_start(self):
        for turn_started in (OMITTED, None):
            with self.subTest(turn_started='omitted' if turn_started is OMITTED else turn_started):
                result, rpc = self.history([OMITTED, None], turn_started=turn_started, completed=NOW * 1000)
                for item in self.items(result).values():
                    self.assertEqual((item['timestamp'], item['time_precision']), (None, 'unknown'))
        result, rpc = self.history([OMITTED, OMITTED], completed=NOW * 1000)
        for item in self.items(result).values():
            self.assertEqual((item['timestamp'], item['time_precision']), (OLD_TURN, 'turn'))

    def test_malformed_native_item_timing_types_still_refuse_without_writer(self):
        for started in (True, False, 1.5, 1.0, '1000', -(2 ** 63) - 1, 2 ** 63):
            with self.subTest(started=started):
                result, rpc = self.history([started, started])
                self.assertEqual(result, {'error': 'unavailable'})
                self.assertFalse(rpc.starts())

    def test_item_timing_adds_no_rpc_query_or_exported_internal_fields(self):
        result, rpc = self.history([NOW * 1000, NOW * 1000], completed=NOW * 1000 + 1000)
        self.items(result)
        self.assertEqual([method for method, params in rpc.calls],
                         ['thread/read', 'thread/turns/list', 'thread/items/list'])
        self.assertEqual(rpc.calls[-1][1], {'threadId': contract.SID, 'turnId': contract.TURN,
                                         'sortDirection': 'desc', 'limit': 32})
        self.assertNotIn('startedAtMs', json.dumps(result))
        self.assertNotIn('completedAtMs', json.dumps(result))


class ItemMessageTimesBrowser(unittest.TestCase):
    setUpClass = classmethod(browser_fixture.MessageTimesBrowser.setUpClass.__func__)
    setUp = browser_fixture.MessageTimesBrowser.setUp
    tearDown = browser_fixture.MessageTimesBrowser.tearDown
    open = browser_fixture.MessageTimesBrowser.open
    bubble = browser_fixture.MessageTimesBrowser.bubble

    def test_recent_item_precision_age_accessible_moscow_label_and_local_update(self):
        items = [{'id': 'assistant-item', 'role': 'assistant', 'text': 'Time assistant 0', 'truncated': False,
                  'timestamp': NOW - 60, 'time_precision': 'item'},
                 {'id': 'user-item', 'role': 'user', 'text': 'Time user 0', 'truncated': False,
                  'timestamp': NOW - 120, 'time_precision': 'item'}]
        browser_fixture.private_json(self.evidence / 'control.json', {'items': items})
        self.open()
        assistant = self.bubble('Time assistant 0')
        user = self.bubble('Time user 0')
        self.assertIn('1 мин. назад', assistant.inner_text())
        self.assertIn('2 мин. назад', user.inner_text())
        native = assistant.locator('time')
        control = native.locator('xpath=ancestor-or-self::*[@tabindex="0" or self::button or self::summary][1]')
        self.assertGreater(control.count(), 0, 'item exact date needs focus/tap access')
        control.first.focus()
        accessible = control.first.aria_snapshot().lower()
        self.assertRegex(accessible, 'начало сообщ|сообщение нач|сообщени.*начал')
        self.assertNotIn('начало хода', accessible)
        self.assertIn('03:59', accessible, 'Moscow item start, independent of browser Los Angeles zone')
        before = list(self.network)
        self.page.evaluate('testAdvance(60000)')
        self.assertIn('2 мин. назад', assistant.inner_text())
        self.assertEqual(self.network, before, 'item ages update locally without fetch/RPC')
        self.assertTrue(control.first.evaluate('el=>el===document.activeElement'))

    def test_old_turn_fallback_visibly_qualifies_age_before_hover(self):
        browser_fixture.private_json(self.evidence / 'control.json', {'items': [
            {'id': 'turn-fallback', 'role': 'assistant', 'text': 'Time assistant 0', 'truncated': False,
             'timestamp': OLD_TURN, 'time_precision': 'turn'}]})
        self.open()
        bubble = self.bubble('Time assistant 0')
        self.assertIn('25 мин. назад', bubble.inner_text())
        self.assertRegex(bubble.inner_text().lower(), 'ход начат|начало хода|начат.*ход',
                         'turn qualifier must be visible ordinary text, not tooltip/ARIA only')


if __name__ == '__main__':
    unittest.main(verbosity=2)
