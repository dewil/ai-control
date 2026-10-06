"""Blind synthetic checks for nullable signed-int64 native item timing fields."""
import os
from pathlib import Path
import tempfile
import unittest

from test_control_web_session_chat_contract import SID, TURN, feature
from test_control_web_session_chat_items_paging import ItemPagingRPC, agent, native_turn, user

MIN_I64 = -(2 ** 63)
MAX_I64 = 2 ** 63 - 1


class NativeItemTimingFieldsRed(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-native-item-times-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.project = self.base / 'project'
        self.project.mkdir(mode=0o700)

    def page_result(self, timing=None, extra=None):
        metadata = native_turn(TURN, [], startedAt=1700000000)
        rpc = ItemPagingRPC(self.project, [metadata])
        native_items = [
            agent('synthetic-agent-item', 'synthetic assistant text'),
            user('synthetic-user-item', None, 'synthetic user text'),
        ]
        entries = []
        for item in native_items:
            entry = {'turnId': TURN, 'item': item}
            if timing is not None:
                entry.update(timing)
            if extra is not None:
                entry.update(extra)
            entries.append(entry)
        rpc.item_pages[(TURN, None)] = {'data': entries, 'nextCursor': None}
        chat = self.module.SessionChat(rpc, lambda _: str(self.project), lambda: ['demo'],
                                       str(self.base / 'receipts'))
        return chat.history('demo', SID), rpc

    def test_optional_native_int64_times_are_accepted_and_discarded(self):
        cases = (
            ('legacy omitted fields', None),
            ('both null', {'startedAtMs': None, 'completedAtMs': None}),
            ('minimum signed int64', {'startedAtMs': MIN_I64}),
            ('maximum signed int64', {'completedAtMs': MAX_I64}),
            ('both signed int64 bounds', {'startedAtMs': MIN_I64, 'completedAtMs': MAX_I64}),
        )
        violations = []
        for label, timing in cases:
            with self.subTest(case=label):
                result, rpc = self.page_result(timing)
                if 'turns' not in result:
                    violations.append(f'{label}: valid native item timing fields rejected')
                    continue
                items = result['turns'][0]['items']
                if {item['role'] for item in items} != {'user', 'assistant'}:
                    violations.append(f'{label}: text roles changed')
                for item in items:
                    if (item.get('timestamp'), item.get('time_precision')) != (1700000000, 'turn'):
                        violations.append(f'{label}: item-local native times replaced turn-derived time')
                    if set(item) != {'id', 'role', 'text', 'truncated', 'timestamp', 'time_precision'}:
                        violations.append(f'{label}: native timing leaked into the public DTO')
                if rpc.starts():
                    violations.append(f'{label}: history called a writer')
        self.assertEqual(violations, [], 'optional native timing fields are validated then discarded')

    def test_malformed_native_times_and_unknown_item_fields_fail_closed(self):
        violations = []
        malformed = (
            ('bool start', {'startedAtMs': True}),
            ('bool complete', {'completedAtMs': False}),
            ('fractional start', {'startedAtMs': 1.5}),
            ('float complete', {'completedAtMs': 1.0}),
            ('string start', {'startedAtMs': '1'}),
            ('below int64', {'startedAtMs': MIN_I64 - 1}),
            ('above int64', {'completedAtMs': MAX_I64 + 1}),
            ('unknown field', {}, {'futureTimingField': 1}),
        )
        for entry in malformed:
            label, timing, *rest = entry
            extra = rest[0] if rest else None
            with self.subTest(case=label):
                result, rpc = self.page_result(timing, extra)
                if result != {'error': 'unavailable'}:
                    violations.append(f'{label}: expected unavailable, got non-error history')
                if rpc.starts():
                    violations.append(f'{label}: malformed history caused a writer')
        self.assertEqual(violations, [], 'malformed or unrecognized native item fields must fail closed')


if __name__ == '__main__':
    unittest.main()
