"""Blind installed-project provider correction, public spec e455864 only."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
SID = '11111111-1111-4111-8111-111111111111'
MID = '22222222-2222-4222-8222-222222222222'
TURN = '33333333-3333-4333-8333-333333333333'


class ProjectProviderContract(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-session-projects-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.root = self.base / 'control'
        self.root.mkdir(mode=0o700)
        self.missing = self.base / 'missing-project'
        self.receipts = self.base / 'receipts'
        self.names = ['control', 'missing']
        self.names_error = None
        self.resolver_error = None
        self.rpc_calls = []
        self.resolved = []
        self.clock = None
        self.expire_after = None
        self.chat = self.module.SessionChat(self.rpc, self.resolve, self.project_names, str(self.receipts))
    def project_names(self):
        if self.names_error:
            raise self.names_error
        return self.names
    def resolve(self, name):
        self.resolved.append(name)
        if self.clock is not None and self.expire_after == name:
            self.clock[0] += 56
        if name == 'control':
            return str(self.root)
        if name == 'missing':
            if self.resolver_error:
                raise self.resolver_error
            return str(self.missing)
        return str(self.base / name)
    def rpc(self, method, params):
        self.rpc_calls.append((method, dict(params)))
        if method in ('thread/read', 'thread/resume'):
            return {'thread': {'id': SID, 'cwd': str(self.root)}}
        if method == 'thread/turns/list':
            return {'data': [{'id': TURN, 'status': 'completed', 'items': [
                {'id': 'synthetic-user-item', 'type': 'userMessage', 'clientId': None,
                 'content': [{'type': 'text', 'text': 'Synthetic control history'}]}]}], 'nextCursor': None}
        if method == 'turn/start':
            return {'turn': {'id': TURN}}
        raise AssertionError('Unexpected RPC method: ' + method)
    def safe_unavailable(self, result):
        self.assertEqual(result, {'error': 'unavailable'})
        self.assertNotIn(str(self.base), json.dumps(result))
        self.assertNotIn('synthetic-private', json.dumps(result))

    def test_INV_WSESS_02_mixed_roots_export_ordered_explicit_availability(self):
        self.assertEqual(self.chat.projects(), {'projects': [{'name': 'control'}, {'name': 'missing', 'unavailable': True}]})
        self.assertEqual(self.resolved, ['control', 'missing'])
        self.assertEqual(self.rpc_calls, [])

    def test_INV_WSESS_02_reverse_input_order_preserved(self):
        self.names = ['missing', 'control']
        self.assertEqual(self.chat.projects(), {'projects': [{'name': 'missing', 'unavailable': True}, {'name': 'control'}]})
        self.assertEqual(self.resolved, self.names)
        self.assertEqual(self.rpc_calls, [])

    def test_INV_WSESS_02_failed_resolver_is_local_entry_without_raw_error(self):
        self.resolver_error = RuntimeError('synthetic-private-root-resolution ' + str(self.missing))
        result = self.chat.projects()
        self.assertEqual(result, {'projects': [{'name': 'control'}, {'name': 'missing', 'unavailable': True}]})
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertNotIn(str(self.base), json.dumps(result))
        self.assertEqual(self.rpc_calls, [])

    def test_INV_WSESS_02_all_missing_remain_visible_explicit_entries(self):
        self.names = ['missing', 'other-missing']
        self.assertEqual(self.chat.projects(), {'projects': [
            {'name': 'missing', 'unavailable': True}, {'name': 'other-missing', 'unavailable': True}]})
        self.assertEqual(self.rpc_calls, [])

    def test_INV_WSESS_02_missing_foreign_root_does_not_block_valid_history_or_send(self):
        result = self.chat.history('control', SID)
        self.assertEqual(result['turns'][0]['items'][0]['text'], 'Synthetic control history')
        self.assertEqual(self.chat.send('control', SID, MID, 'Synthetic control instruction'),
                         {'status': 'accepted', 'message_id': MID, 'turn_id': TURN})
        self.assertEqual([method for method, _ in self.rpc_calls],
                         ['thread/read', 'thread/turns/list', 'thread/read', 'thread/resume', 'turn/start'])

    def test_INV_WSESS_02_selected_missing_root_never_gets_native_rpc(self):
        for invoke in (lambda: self.chat.history('missing', SID),
                       lambda: self.chat.send('missing', SID, MID, 'Synthetic missing instruction'),
                       lambda: self.chat.send_status('missing', SID, MID)):
            self.assertEqual(set(invoke()), {'error'})
        self.assertEqual(self.rpc_calls, [])

    def test_INV_WSESS_02_selected_failed_resolver_never_gets_native_rpc(self):
        self.resolver_error = RuntimeError('synthetic-private-selected-root')
        for invoke in (lambda: self.chat.history('missing', SID),
                       lambda: self.chat.send('missing', SID, MID, 'Synthetic missing instruction'),
                       lambda: self.chat.send_status('missing', SID, MID)):
            result = invoke()
            self.assertEqual(set(result), {'error'})
            self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertEqual(self.rpc_calls, [])

    def test_INV_WSESS_02_global_names_failure_is_not_partial_projects(self):
        self.names_error = RuntimeError('synthetic-private-registry-provider')
        self.safe_unavailable(self.chat.projects())
        self.assertEqual(self.resolved, [])
        self.assertEqual(self.rpc_calls, [])

    def test_INV_WSESS_02_invalid_or_duplicate_names_are_global_failure(self):
        for names in (['control', '../bad'], ['control', 'control'], ['control', 7], None, {'control': 'path'}):
            with self.subTest(names_type=type(names).__name__):
                self.names = names
                self.safe_unavailable(self.chat.projects())
        self.assertEqual(self.rpc_calls, [])

    def test_INV_WSESS_02_deadline_during_valid_root_check_never_partial_success(self):
        self.clock = [100.0]
        self.expire_after = 'control'
        with patch('time.monotonic', side_effect=lambda: self.clock[0]):
            self.safe_unavailable(self.chat.projects())
        self.assertEqual(self.rpc_calls, [])

    def test_INV_WSESS_02_deadline_during_failed_root_check_not_local_unavailable_entry(self):
        self.clock = [100.0]
        self.expire_after = 'missing'
        self.resolver_error = RuntimeError('synthetic-private-error-after-deadline')
        with patch('time.monotonic', side_effect=lambda: self.clock[0]):
            self.safe_unavailable(self.chat.projects())
        self.assertEqual(self.rpc_calls, [])


if __name__ == '__main__':
    unittest.main()
