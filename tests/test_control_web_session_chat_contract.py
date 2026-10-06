"""Independent synthetic INV-WSESS acceptance, written from committed specs only."""
import importlib
import json
import os
from pathlib import Path
import stat
import shutil
import threading
import sys
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
SID = '11111111-1111-4111-8111-111111111111'
MID = '22222222-2222-4222-8222-222222222222'
TURN = '33333333-3333-4333-8333-333333333333'
OTHER = '44444444-4444-4444-8444-444444444444'
ORIGIN = 'https://control.example.test'
PASSWORD = 'synthetic-web-test-password'
SECRET = 'JBSWY3DPEHPK3PXP'


def feature(case, name):
    case.assertTrue((ROOT / 'bin' / (name + '.py')).is_file(),
                    f'Missing public feature {name} from web-session-chat specification')
    return importlib.import_module(name)


def turn(text='assistant reply', client_id=None, turn_id=TURN):
    items = [{'id': 'agent-item', 'type': 'agentMessage', 'text': text}]
    if client_id is not None:
        items.append({'id': 'user-item', 'type': 'userMessage', 'clientId': client_id,
                      'content': [{'type': 'text', 'text': 'synthetic input'}]})
    return {'id': turn_id, 'status': 'completed', 'items': items}


class RPC:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.pages = {None: {'data': [turn()], 'nextCursor': None}}
        self.item_sources = {}
        self.list_response = {'data': [{'id': SID, 'cwd': str(root), 'name': 'Synthetic session', 'status': {'type': 'idle'}}], 'nextCursor': None}
        self.read_id = SID
        self.resume_root = None
        self.metadata_status = None
        self.start_error = None
        self.start_response = {'turn': {'id': TURN}}
        self.before_start = None
    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method in ('thread/read', 'thread/resume'):
            cwd = self.resume_root if method == 'thread/resume' and self.resume_root else self.root
            metadata = {'id': self.read_id, 'cwd': str(cwd)}
            if self.metadata_status is not None:
                metadata['status'] = self.metadata_status
            return {'thread': metadata}
        if method == 'thread/list':
            return self.list_response
        if method == 'thread/turns/list':
            response = self.pages[params.get('cursor')]
            if params.get('itemsView') != 'notLoaded':
                return response
            if not isinstance(response, dict) or not isinstance(response.get('data'), list):
                return response
            rows = response['data']
            if any(not isinstance(row, dict) or not isinstance(row.get('items'), list)
                   or not isinstance(row.get('id'), str) for row in rows):
                return response
            metadata = []
            for row in rows:
                self.item_sources[row['id']] = list(row['items'])
                metadata.append({key: value for key, value in row.items() if key != 'items'} | {'items': []})
            return {'data': metadata, 'nextCursor': response.get('nextCursor')}
        if method == 'thread/items/list':
            items = list(reversed(self.item_sources[params['turnId']]))
            cursor = params.get('cursor')
            prefix = f"items:{params['turnId']}:"
            offset = int(cursor[len(prefix):]) if isinstance(cursor, str) and cursor.startswith(prefix) else 0
            batch = items[offset:offset + params['limit']]
            next_offset = offset + len(batch)
            next_cursor = f'{prefix}{next_offset}' if next_offset < len(items) else None
            return {'data': [{'turnId': params['turnId'], 'item': item} for item in batch],
                    'nextCursor': next_cursor}
        if method == 'turn/start':
            if self.before_start:
                self.before_start()
            if self.start_error:
                raise self.start_error
            return self.start_response
        raise AssertionError('Unexpected RPC: ' + method)
    def starts(self):
        return [p for m, p in self.calls if m == 'turn/start']


class SessionChatContract(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-session-test-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.project = self.base / 'project'
        self.project.mkdir(mode=0o700)
        self.receipts = self.base / 'receipts'
        self.rpc = RPC(self.project)
        self.resolutions = []
        self.bound_root = self.project
        self.chat = self.new_chat()
    def resolve(self, alias):
        self.resolutions.append(alias)
        if alias != 'demo':
            raise ValueError('synthetic-invalid-project')
        return str(self.bound_root)
    def new_chat(self):
        return self.module.SessionChat(self.rpc, self.resolve, lambda: ['demo'], str(self.receipts))
    def send(self, text='Hello', mid=MID):
        return self.chat.send('demo', SID, mid, text)
    def assert_error(self, result, code):
        self.assertEqual(result, {'error': code})
    def receipt(self, status, mid=MID, tid=None):
        return {'status': status, 'message_id': mid, 'turn_id': tid}

    def test_INV_WSESS_02_projects_do_not_export_paths(self):
        self.assertEqual(self.chat.projects(), {'projects': [{'name': 'demo'}]})
        self.assertTrue(self.resolutions)
        self.assertNotIn(str(self.base), json.dumps(self.chat.projects()))

    def test_INV_WSESS_02_list_requires_metadata_proof_for_exported_uuid(self):
        result = self.chat.list_sessions('demo')
        # INV-WSESS-28: fixed adapter vendor accompanies the existing proved row.
        self.assertEqual(result, {'rows': [{'sid': SID, 'title': 'Synthetic session', 'status': 'idle', 'vendor': 'codex'}], 'has_more': False})
        self.assertIn(('thread/read', {'threadId': SID, 'includeTurns': False}), self.rpc.calls)
        self.rpc.read_id = OTHER
        self.assert_error(self.chat.list_sessions('demo'), 'stale')

    def test_INV_WSESS_02_listing_corrupt_response_is_unavailable(self):
        self.rpc.list_response = {'data': 'corrupt', 'nextCursor': None}
        self.assert_error(self.chat.list_sessions('demo'), 'unavailable')

    def test_INV_WSESS_02_invalid_uuid_alias_and_types_before_rpc(self):
        for project, sid, mid, text in [('demo', SID[:8], MID, 'x'), ('demo', SID.upper().replace('1', 'A', 1), MID, 'x'),
                ('../project', SID, MID, 'x'), ('demo', SID, MID[:8], 'x'), ('demo', SID, MID, ''),
                ('demo', SID, MID, ' \n '), ('demo', SID, MID, 7), ('demo', SID, MID, 'x'*16001)]:
            with self.subTest(project=project, sid=sid, mid=mid, text_type=type(text).__name__):
                self.assert_error(self.chat.send(project, sid, mid, text), 'invalid_request')
        self.assertEqual(self.rpc.calls, [])
        for page in (True, -1, '0', 1.5):
            self.assert_error(self.chat.list_sessions('demo', page), 'invalid_request')
        for cursor in ('', True, 4, 'x'*100000):
            self.assert_error(self.chat.history('demo', SID, cursor), 'invalid_request')
        self.assertEqual(self.rpc.calls, [])

    def test_INV_WSESS_02_cross_project_proof_and_reresolution(self):
        self.assertIn('turns', self.chat.history('demo', SID))
        self.bound_root = self.base / 'rebound'
        self.bound_root.mkdir(mode=0o700)
        for invoke in (lambda: self.chat.history('demo', SID), self.send,
                       lambda: self.chat.send_status('demo', SID, MID)):
            self.assert_error(invoke(), 'stale')
        self.assertEqual(self.rpc.starts(), [])
        self.assertGreaterEqual(len(self.resolutions), 4)

    def test_INV_WSESS_02_returned_thread_id_must_match(self):
        self.rpc.read_id = OTHER
        self.assert_error(self.chat.history('demo', SID), 'stale')
        self.assert_error(self.send(), 'stale')
        self.assertEqual(self.rpc.starts(), [])

    def test_INV_WSESS_02_resume_proof_prevents_rebind_send(self):
        self.rpc.resume_root = self.base / 'other-project'
        self.rpc.resume_root.mkdir(mode=0o700)
        self.assert_error(self.send(), 'stale')
        self.assertEqual(self.rpc.starts(), [])

    def test_INV_WSESS_07_native_attention_from_active_flags(self):
        for flag in ('waitingOnApproval', 'waitingOnUserInput'):
            with self.subTest(flag=flag):
                status = {'type': 'active', 'activeFlags': [flag]}
                self.rpc.metadata_status = status
                self.rpc.list_response['data'][0]['status'] = status
                self.assertIs(self.chat.history('demo', SID).get('needs_native_attention'), True)
                self.assertIs(self.chat.list_sessions('demo')['rows'][0].get('needs_native_attention'), True)

    def test_INV_WSESS_07_no_false_native_attention_guarantee(self):
        for status in (None, {'type': 'idle'}, {'type': 'active', 'activeFlags': []}):
            with self.subTest(status=status):
                self.rpc.metadata_status = status
                self.rpc.list_response['data'][0]['status'] = status or {'type': 'idle'}
                self.assertNotIn('needs_native_attention', self.chat.history('demo', SID))
                self.assertNotIn('needs_native_attention', self.chat.list_sessions('demo')['rows'][0])

    def test_INV_WSESS_03_native_arbitrary_client_ids_are_allowed_but_private(self):
        for client_id in ('native-client-123', None):
            with self.subTest(client_id=client_id):
                page = turn(client_id='native-client-123')
                page['items'][-1]['clientId'] = client_id
                self.rpc.pages[None] = {'data': [page], 'nextCursor': None}
                result = self.chat.history('demo', SID)
                self.assertIn('turns', result)
                self.assertEqual(result['turns'][0]['items'][-1]['text'], 'synthetic input')
                self.assertNotIn('clientId', result['turns'][0]['items'][-1])

    def test_INV_WSESS_05_native_client_id_never_confirms_our_unknown_send(self):
        self.rpc.start_error = TimeoutError()
        self.send()
        self.rpc.pages[None] = {'data': [turn(client_id='native-client-123')], 'nextCursor': None}
        self.assertEqual(self.chat.send_status('demo', SID, MID), self.receipt('delivery_unknown'))
        self.assertEqual(len(self.rpc.starts()), 1)

    def test_INV_WSESS_03_history_exact_rpc_and_allowlist(self):
        self.rpc.pages[None] = {'data': [{'id': TURN, 'status': 'completed', 'items': [
            {'id': 'u', 'type': 'userMessage', 'clientId': MID, 'content': [
                {'type': 'text', 'text': 'first'}, {'type': 'image', 'url': 'private://attachment'},
                {'type': 'text', 'text': 'second'}]},
            {'id': 'a', 'type': 'agentMessage', 'text': 'answer'},
            {'id': 'r', 'type': 'reasoning', 'text': 'private reasoning'},
            {'id': 'h', 'type': 'hookPrompt', 'text': 'private hook'},
            {'id': 't', 'type': 'commandExecution', 'output': 'private tool'},
            {'id': 'unknown', 'type': 'futureMessage', 'text': 'private unknown'}]}], 'nextCursor': 'opaque-next'}
        result = self.chat.history('demo', SID)
        self.assertEqual(result, {'turns': [{'id': TURN, 'status': 'completed', 'items': [
            {'id': 'u', 'role': 'user', 'text': 'first\nsecond', 'truncated': False, 'timestamp': None, 'time_precision': 'unknown'},
            {'id': 'a', 'role': 'assistant', 'text': 'answer', 'truncated': False, 'timestamp': None, 'time_precision': 'unknown'}]}],
            'next_cursor': 'opaque-next', 'truncated': False, 'recent_sends': []})
        # 05.10 compact policy intentionally changes latest native limit8 to limit4.
        # History uses metadata-only turns before fetching their supported text items.
        self.assertEqual(self.rpc.calls, [('thread/read', {'threadId': SID, 'includeTurns': False}),
            ('thread/turns/list', {'threadId': SID, 'itemsView': 'notLoaded', 'sortDirection': 'desc', 'limit': 4}),
            ('thread/items/list', {'threadId': SID, 'turnId': TURN, 'sortDirection': 'desc', 'limit': 32})])

    def test_INV_WSESS_03_pagination_preserves_server_order(self):
        self.rpc.pages['opaque'] = {'data': [turn(turn_id=OTHER), turn()], 'nextCursor': None}
        result = self.chat.history('demo', SID, 'opaque')
        self.assertEqual([t['id'] for t in result['turns']], [OTHER, TURN])
        self.assertIsNone(result['next_cursor'])
        turn_requests = [params for method, params in self.rpc.calls if method == 'thread/turns/list']
        self.assertEqual(turn_requests[-1], {'threadId': SID, 'itemsView': 'notLoaded',
            'sortDirection': 'desc', 'limit': 8, 'cursor': 'opaque'})

    def test_INV_WSESS_03_redaction_then_unicode_clipping(self):
        raw = 'token=synthetic-private-token-value ' + 'я'*9000
        self.rpc.pages[None] = {'data': [turn(raw)], 'nextCursor': None}
        result = self.chat.history('demo', SID)
        item = result['turns'][0]['items'][0]
        self.assertNotIn('synthetic-private-token-value', item['text'])
        self.assertLessEqual(len(item['text']), 8000)
        self.assertTrue(item['truncated'])
        self.assertTrue(result['truncated'])
        json.dumps(result, ensure_ascii=False).encode('utf-8').decode('utf-8')

    def test_INV_WSESS_03_total_encoded_budget_is_honest(self):
        # 05.10 compact latest requests4 turns; Older retains this8-turn budget fixture.
        self.rpc.pages['older-budget-fixture'] = {'data': [turn('界'*8000, turn_id=f'{i:08x}-1111-4111-8111-111111111111')
                                        for i in range(8)], 'nextCursor': 'older'}
        result = self.chat.history('demo', SID, 'older-budget-fixture')
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')), 96*1024)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['next_cursor'], 'older')
        self.assertTrue(result['turns'])

    def test_INV_WSESS_03_corrupt_upstream_is_not_empty_history(self):
        for response in ({}, {'data': 'bad', 'nextCursor': None}, {'data': [{'status': 'completed', 'items': []}], 'nextCursor': None},
                         {'data': [turn()], 'nextCursor': 4}):
            with self.subTest(response=response):
                self.rpc.pages[None] = response
                self.assert_error(self.chat.history('demo', SID), 'unavailable')

    def test_INV_WSESS_04_exact_send_without_settings_and_unmodified_text(self):
        text = '  token=synthetic-user-instruction \n'
        self.assertEqual(self.send(text), self.receipt('accepted', tid=TURN))
        # Resume keeps the root/UUID proof but requests metadata without full turns.
        self.assertEqual(self.rpc.calls, [('thread/read', {'threadId': SID, 'includeTurns': False}),
            ('thread/resume', {'threadId': SID, 'excludeTurns': True}), ('turn/start', {'threadId': SID,
            'input': [{'type': 'text', 'text': text}], 'clientUserMessageId': MID})])

    def test_INV_WSESS_05_repeat_restart_and_changed_text_never_resend(self):
        expected = self.send()
        self.assertEqual(self.send(), expected)
        self.chat = self.new_chat()
        self.assertEqual(self.send(), expected)
        self.assert_error(self.send('Changed'), 'invalid_request')
        self.assertEqual(len(self.rpc.starts()), 1)
        self.assertEqual(sum(m == 'thread/resume' for m, _ in self.rpc.calls), 1)

    def test_INV_WSESS_05_aliases_same_canonical_root_share_dedup_and_recent(self):
        def resolve(alias):
            if alias not in ('demo', 'alias'):
                raise ValueError('unknown project')
            return str(self.project)
        chat = self.module.SessionChat(self.rpc, resolve, lambda: ['demo', 'alias'], str(self.receipts))
        expected = chat.send('demo', SID, MID, 'Hello')
        self.assertEqual(chat.send('alias', SID, MID, 'Hello'), expected)
        self.assertEqual(chat.send('alias', SID, MID, 'Changed'), {'error': 'invalid_request'})
        self.assertEqual(chat.history('alias', SID)['recent_sends'], [expected])
        self.assertEqual(len(self.rpc.starts()), 1)
        self.assertEqual(sum(m == 'thread/resume' for m, _ in self.rpc.calls), 1)

    def test_INV_WSESS_05_parallel_instances_reserve_once(self):
        chats = [self.new_chat(), self.new_chat()]
        barrier = threading.Barrier(2)
        results = []
        def submit(chat):
            barrier.wait(timeout=3)
            results.append(chat.send('demo', SID, MID, 'Hello'))
        workers = [threading.Thread(target=submit, args=(chat,)) for chat in chats]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive(), 'Private receipt lock must finish')
        self.assertEqual(results, [self.receipt('accepted', tid=TURN)]*2)
        self.assertEqual(len(self.rpc.starts()), 1)

    def test_INV_WSESS_05_lost_ack_stays_unknown_on_restart(self):
        self.rpc.start_error = TimeoutError('synthetic-private-transport-error')
        expected = self.receipt('delivery_unknown')
        self.assertEqual(self.send(), expected)
        self.chat = self.new_chat()
        self.assertEqual(self.send(), expected)
        self.assertEqual(self.chat.send_status('demo', SID, MID), expected)
        self.assertEqual(len(self.rpc.starts()), 1)
        self.assertNotIn('synthetic-private', json.dumps(expected))

    def test_INV_WSESS_05_even_valid_rpc_error_after_send_is_unknown(self):
        self.rpc.start_error = self.module.RPCRejected('safe-class')
        expected = self.receipt('delivery_unknown')
        self.assertEqual(self.send(), expected)
        self.assertEqual(self.new_chat().send('demo', SID, MID, 'Hello'), expected)
        self.assertEqual(len(self.rpc.starts()), 1)

    def test_INV_WSESS_05_malformed_ack_is_unknown(self):
        self.rpc.start_response = {'turn': {}}
        self.assertEqual(self.send(), self.receipt('delivery_unknown'))
        self.assertEqual(len(self.rpc.starts()), 1)

    def test_INV_WSESS_05_status_correlation_requires_client_id(self):
        self.rpc.start_error = TimeoutError()
        self.send()
        self.rpc.pages[None] = {'data': [turn(client_id=OTHER)], 'nextCursor': 'older'}
        self.rpc.pages['older'] = {'data': [turn(client_id=MID, turn_id=OTHER)], 'nextCursor': None}
        self.assertEqual(self.chat.send_status('demo', SID, MID), self.receipt('accepted', tid=OTHER))
        self.chat = self.new_chat()
        self.assertEqual(self.chat.send_status('demo', SID, MID), self.receipt('accepted', tid=OTHER))
        self.assertEqual(len(self.rpc.starts()), 1)

    def test_INV_WSESS_05_status_missing_and_repeated_cursor(self):
        self.assert_error(self.chat.send_status('demo', SID, MID), 'stale')
        self.rpc.start_error = TimeoutError()
        self.send()
        self.rpc.pages[None] = {'data': [turn()], 'nextCursor': 'again'}
        self.rpc.pages['again'] = {'data': [turn()], 'nextCursor': 'again'}
        self.assert_error(self.chat.send_status('demo', SID, MID), 'unavailable')
        self.assertEqual(len(self.rpc.starts()), 1)

    def test_INV_WSESS_05_recent_receipts_bounded_safe_and_reload(self):
        mids = [f'{i:08x}-2222-4222-8222-222222222222' for i in range(10)]
        for mid in mids:
            self.send(mid=mid)
        history = self.new_chat().history('demo', SID)
        self.assertEqual(history['recent_sends'], [self.receipt('accepted', mid=mid, tid=TURN) for mid in reversed(mids[-8:])])
        for entry in history['recent_sends']:
            self.assertEqual(set(entry), {'status', 'message_id', 'turn_id'})

    def test_INV_WSESS_05_receipts_are_owned_by_selected_thread(self):
        self.send()
        self.rpc.read_id = OTHER
        self.rpc.start_response = {'turn': {'id': OTHER}}
        self.assertEqual(self.chat.history('demo', OTHER)['recent_sends'], [])
        self.assert_error(self.chat.send_status('demo', OTHER, MID), 'stale')
        self.assertEqual(self.chat.send('demo', OTHER, MID, 'Other thread'), self.receipt('accepted', tid=OTHER))
        self.assertEqual(self.chat.history('demo', OTHER)['recent_sends'], [self.receipt('accepted', tid=OTHER)])
        self.rpc.read_id = SID
        self.assertEqual(self.chat.history('demo', SID)['recent_sends'], [self.receipt('accepted', tid=TURN)])
        self.assertEqual(len(self.rpc.starts()), 2)

    def test_INV_WSESS_06_private_files_digest_only_and_reserve_precedes_send(self):
        text = 'never-store-this-synthetic-body'
        def reserved():
            files = [p for p in self.receipts.rglob('*') if p.is_file()]
            self.assertTrue(files, 'Durable receipt must precede turn/start')
            self.assertTrue(any(MID in p.read_text() for p in files))
            for p in files:
                self.assertNotIn(text, p.read_text())
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.receipts.stat().st_mode), 0o700)
        self.rpc.before_start = reserved
        self.send(text)
        reserved()

    def test_INV_WSESS_06_reserve_fsync_failure_prohibits_send(self):
        with patch('os.fsync', side_effect=OSError('synthetic-write-failure')):
            self.assert_error(self.send(), 'unavailable')
        self.assertEqual(self.rpc.starts(), [])

    def test_INV_WSESS_06_receipts_inside_git_ancestor_fail_closed(self):
        for marker_type in ('directory', 'worktree-file', 'bare'):
            with self.subTest(marker_type=marker_type):
                git_root = self.base / ('git-' + marker_type)
                git_root.mkdir(mode=0o700)
                if marker_type == 'directory':
                    (git_root / '.git').mkdir(mode=0o700)
                elif marker_type == 'worktree-file':
                    (git_root / '.git').write_text('gitdir: /var/tmp/synthetic-git-metadata\n')
                else:
                    (git_root / 'HEAD').write_text('ref: refs/heads/synthetic\n')
                    (git_root / 'objects').mkdir(mode=0o700)
                    (git_root / 'refs').mkdir(mode=0o700)
                nested = git_root / 'nested'
                nested.mkdir(mode=0o700)
                try:
                    chat = self.module.SessionChat(self.rpc, self.resolve, lambda: ['demo'], str(nested / 'receipts'))
                    result = chat.send('demo', SID, MID, 'Synthetic git fixture')
                except (ValueError, OSError, RuntimeError):
                    result = {'error': 'unavailable'}
                self.assert_error(result, 'unavailable')
                self.assertEqual(self.rpc.starts(), [])

    def receipt_namespace(self):
        for path in self.receipts.rglob('*'):
            if not path.is_file():
                continue
            try:
                record = json.loads(path.read_text())
            except (ValueError, OSError):
                continue
            if isinstance(record, dict) and record.get('message_id') == MID:
                return path.parent
        self.fail('Private synthetic receipt must retain its message_id metadata')

    def test_INV_WSESS_06_namespace_limit_counts_ignored_temporary_files(self):
        self.send()
        namespace = self.receipt_namespace()
        for index in range(10003):
            fd = os.open(namespace / f'.tmp-{index:05d}', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        self.assert_error(self.chat.history('demo', SID), 'unavailable')
        self.assert_error(self.chat.send('demo', SID, OTHER, 'New bounded namespace send'), 'unavailable')
        self.assertEqual(len(self.rpc.starts()), 1)
        self.assertEqual(self.receipt_namespace(), namespace, 'Exhaustion cannot delete protective records')

    def test_INV_WSESS_06_namespace_limit_counts_ignored_directories(self):
        self.send()
        namespace = self.receipt_namespace()
        for index in range(10003):
            (namespace / f'.junk-{index:05d}').mkdir(mode=0o700)
        self.assert_error(self.chat.history('demo', SID), 'unavailable')
        self.assert_error(self.chat.send('demo', SID, OTHER, 'New directory-exhaustion send'), 'unavailable')
        self.assertEqual(len(self.rpc.starts()), 1)

    def test_INV_WSESS_06_receipt_directory_symlink_fails_closed(self):
        target = self.base / 'unsafe-target'
        target.mkdir(mode=0o700)
        if self.receipts.exists():
            shutil.rmtree(self.receipts)
        self.receipts.symlink_to(target, target_is_directory=True)
        try:
            result = self.new_chat().send('demo', SID, MID, 'Hello')
        except (ValueError, OSError, RuntimeError):
            result = {'error': 'unavailable'}
        self.assert_error(result, 'unavailable')
        self.assertEqual(self.rpc.starts(), [])
        self.assertEqual(list(target.iterdir()), [])

    def test_INV_WSESS_05_status_scan_is_bounded_to_eight_pages(self):
        self.rpc.start_error = RuntimeError('generic error is not rejection')
        self.assertEqual(self.send(), self.receipt('delivery_unknown'))
        for i in range(9):
            key = None if i == 0 else f'cursor-{i}'
            self.rpc.pages[key] = {'data': [turn()], 'nextCursor': f'cursor-{i+1}'}
        before = len(self.rpc.calls)
        self.assertEqual(self.chat.send_status('demo', SID, MID), self.receipt('delivery_unknown'))
        scans = [params for method, params in self.rpc.calls[before:] if method == 'thread/turns/list']
        self.assertEqual(len(scans), 8)
        self.assertEqual(len(self.rpc.starts()), 1)

    def test_INV_WSESS_06_corrupt_existing_record_never_becomes_new_send(self):
        self.send()
        records = []
        for path in self.receipts.rglob('*'):
            if path.is_file():
                try:
                    value = json.loads(path.read_text())
                except (ValueError, OSError):
                    continue
                if isinstance(value, dict) and value.get('message_id') == MID:
                    records.append(path)
        self.assertTrue(records, 'Specified digest receipt must retain message_id metadata')
        for path in records:
            path.write_text('{corrupt')
        self.assert_error(self.new_chat().send('demo', SID, MID, 'Hello'), 'unavailable')
        self.assertEqual(len(self.rpc.starts()), 1)

    def test_INV_WSESS_06_ack_write_failure_reserve_still_prevents_retry(self):
        def after_reserve():
            self.failure_patch = patch('os.fsync', side_effect=OSError('post-RPC-write-failure'))
            self.failure_patch.start()
        self.rpc.before_start = after_reserve
        try:
            result = self.send()
        finally:
            if hasattr(self, 'failure_patch'):
                self.failure_patch.stop()
        self.assertIn(result.get('status'), ('accepted', 'delivery_unknown'))
        self.chat = self.new_chat()
        self.rpc.before_start = None
        restarted = self.send()
        self.assertIn(restarted.get('status'), ('accepted', 'delivery_unknown'))
        self.assertEqual(len(self.rpc.starts()), 1)


class InteractiveRPCContract(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-session-wire-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        os.chmod(self.tmp.name, 0o700)
        self.socket = str(Path(self.tmp.name) / 'rpc.sock')
        self.frames = []
        self.server_errors = []
    def server(self, handler):
        from websockets.sync.server import unix_serve
        def safe_handler(ws):
            try:
                handler(ws)
            except Exception as error:
                self.server_errors.append(error)
        server = unix_serve(safe_handler, self.socket)
        # Keep the fake owned transport socket private under any process umask.
        os.chmod(self.socket, 0o600)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(server.shutdown)
    def receive(self, ws):
        frame = json.loads(ws.recv(timeout=3))
        self.frames.append(frame)
        return frame
    def handshake(self, ws):
        request = self.receive(ws)
        self.assertEqual(request['method'], 'initialize')
        self.assertEqual(request['params'], {'clientInfo': {'name': 'ai_control_web', 'version': '0.1'},
                                             'capabilities': {'experimentalApi': True}})
        ws.send(json.dumps({'id': request['id'], 'result': {}}))
        initialized = self.receive(ws)
        self.assertEqual(initialized['method'], 'initialized')
        self.assertNotIn('id', initialized)
    def client(self):
        rpc = self.module.InteractiveRPC(self.socket, timeout=1)
        self.addCleanup(rpc.close)
        return rpc

    def test_INV_WSESS_07_interleaved_callback_receives_no_response(self):
        done = threading.Event()
        unexpected = []
        def handler(ws):
            self.handshake(ws)
            request = self.receive(ws)
            ws.send(json.dumps({'id': 'native-callback', 'method': 'item/commandExecution/requestApproval',
                                'params': {'threadId': SID, 'command': 'synthetic-private-command'}}))
            ws.send(json.dumps({'id': 'unrelated-response', 'result': {'private': 'unknown-id'}}))
            ws.send(json.dumps({'method': 'turn/started', 'params': {'threadId': SID}}))
            ws.send(json.dumps({'id': request['id'], 'result': {'thread': {'id': SID, 'cwd': '/var/tmp/synthetic'}}}))
            try:
                unexpected.append(json.loads(ws.recv(timeout=0.25)))
            except TimeoutError:
                pass
            done.set()
        self.server(handler)
        rpc = self.client()
        self.assertEqual(rpc('thread/read', {'threadId': SID, 'includeTurns': False}),
                         {'thread': {'id': SID, 'cwd': '/var/tmp/synthetic'}})
        self.assertTrue(done.wait(3))
        self.assertEqual(unexpected, [], 'No server-request response, including unknown/error, is allowed')
        self.assertEqual(self.server_errors, [])

    def test_INV_WSESS_07_disconnect_does_not_repeat_start_and_new_call_reconnects(self):
        connections = []
        def handler(ws):
            connections.append(1)
            self.handshake(ws)
            request = self.receive(ws)
            if request['method'] == 'turn/start':
                ws.close()
            else:
                ws.send(json.dumps({'id': request['id'], 'result': {'thread': {'id': SID, 'cwd': '/var/tmp/synthetic'}}}))
        self.server(handler)
        rpc = self.client()
        with self.assertRaises(Exception) as raised:
            rpc('turn/start', {'threadId': SID, 'input': [{'type': 'text', 'text': 'synthetic'}], 'clientUserMessageId': MID})
        self.assertNotIsInstance(raised.exception, self.module.RPCRejected)
        self.assertEqual(rpc('thread/read', {'threadId': SID, 'includeTurns': False})['thread']['id'], SID)
        self.assertEqual(sum(f.get('method') == 'turn/start' for f in self.frames), 1)
        self.assertEqual(len(connections), 2)
        self.assertEqual(self.server_errors, [])

    def test_INV_WSESS_07_unknown_rpc_is_rejected_before_connection(self):
        rpc = self.client()
        with self.assertRaises(Exception):
            rpc('turn/interrupt', {'threadId': SID})
        self.assertFalse(Path(self.socket).exists())
        self.assertEqual(self.frames, [])

    def test_INV_WSESS_07_rejection_is_sanitized_and_malformed_error_is_not_rejection(self):
        errors = [{'code': -32000, 'message': 'synthetic-private-remote-error', 'data': {'secret': 'synthetic-payload'}},
                  {'code': True, 'message': 'synthetic-private-remote-error'}]
        def handler(ws):
            self.handshake(ws)
            request = self.receive(ws)
            ws.send(json.dumps({'id': request['id'], 'error': errors.pop(0)}))
            if errors:
                request = self.receive(ws)
                ws.send(json.dumps({'id': request['id'], 'error': errors.pop(0)}))
        self.server(handler)
        rpc = self.client()
        with self.assertRaises(self.module.RPCRejected) as rejected:
            rpc('turn/start', {'threadId': SID, 'input': [{'type': 'text', 'text': 'x'}], 'clientUserMessageId': MID})
        self.assertNotIn('synthetic-private', str(rejected.exception))
        self.assertNotIn('synthetic-payload', str(rejected.exception))
        with self.assertRaises(Exception) as malformed:
            rpc('turn/start', {'threadId': SID, 'input': [{'type': 'text', 'text': 'x'}], 'clientUserMessageId': OTHER})
        self.assertNotIsInstance(malformed.exception, self.module.RPCRejected)
        self.assertNotIn('synthetic-private', str(malformed.exception))


class HTTPBackend:
    def __init__(self):
        self.calls = []
        self.outcome = {'status': 'accepted', 'message_id': MID, 'turn_id': TURN}
    def session_projects(self):
        self.calls.append(('projects',))
        return {'projects': [{'name': 'demo'}]}
    def session_list(self, project, page):
        self.calls.append(('list', project, page))
        return {'rows': [], 'has_more': False}
    def session_history(self, project, sid, cursor):
        self.calls.append(('history', project, sid, cursor))
        return {'turns': [], 'next_cursor': None, 'truncated': False, 'recent_sends': []}
    def session_send(self, project, sid, message_id, text):
        self.calls.append(('send', project, sid, message_id, text))
        return self.outcome
    def session_send_status(self, project, sid, message_id):
        self.calls.append(('status', project, sid, message_id))
        return self.outcome


class SessionHTTPContract(unittest.TestCase):
    def setUp(self):
        self.web = feature(self, '_control_web')
        self.backend = HTTPBackend()
        self.now = 1800000000
        config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
                      totp_secret=SECRET, session_ttl=60, secure_cookie=True)
        self.client = TestClient(self.web.create_app(config, self.backend, clock=lambda: self.now), base_url=ORIGIN)
        self.body = {'project': 'demo', 'sid': SID, 'message_id': MID, 'text': 'Hello'}
    def login(self):
        response = self.client.post('/api/login', json={'password': PASSWORD,
            'totp': self.web.totp_code(SECRET, self.now)}, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json()['csrf']
    def post(self, body=None):
        return self.client.post('/api/session-send', json=self.body if body is None else body,
            headers={'Origin': ORIGIN, 'X-CSRF-Token': self.csrf})

    def test_INV_WSESS_01_auth_required_for_all_session_routes(self):
        for path in ('/api/session-projects', '/api/sessions?project=demo',
                     f'/api/session-history?project=demo&sid={SID}',
                     f'/api/session-send-status?project=demo&sid={SID}&message_id={MID}'):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertIn(self.client.post('/api/session-send', json=self.body, headers={'Origin': ORIGIN}).status_code, (401, 403))
        self.assertEqual(self.backend.calls, [])

    def test_INV_WSESS_01_send_origin_and_csrf(self):
        self.login()
        for headers in ({'Origin': ORIGIN}, {'Origin': ORIGIN, 'X-CSRF-Token': 'wrong'},
                        {'Origin': 'https://evil.example', 'X-CSRF-Token': self.csrf}, {'X-CSRF-Token': self.csrf}):
            self.assertEqual(self.client.post('/api/session-send', json=self.body, headers=headers).status_code, 403)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.post().status_code, 200)

    def test_INV_WSESS_01_strict_queries_no_path_rpc_or_duplicate_fields(self):
        self.login()
        paths = ['/api/session-projects?path=/private', '/api/sessions?project=demo&project=other',
            '/api/sessions?project=../private', '/api/sessions?project=demo&page=true',
            '/api/sessions?project=demo&page=-1', f'/api/session-history?project=demo&sid={SID}&rpc=turn/start',
            f'/api/session-history?project=demo&sid={SID[:8]}', f'/api/session-history?project=demo&sid={SID}&cursor=',
            f'/api/session-send-status?project=demo&sid={SID}&message_id={MID}&text=extra']
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 422, path)
        self.assertEqual(self.backend.calls, [])

    def test_INV_WSESS_01_strict_send_json_before_backend(self):
        self.login()
        for body in ({**self.body, 'model': 'override'}, {**self.body, 'project': '/private'},
                     {**self.body, 'sid': SID[:8]}, {**self.body, 'message_id': None},
                     {**self.body, 'text': ' '}, {**self.body, 'text': 4}, {**self.body, 'text': 'x'*16001}):
            self.assertEqual(self.post(body).status_code, 422)
        duplicate = json.dumps(self.body)[:-1] + ', "text": "other"}'
        self.assertEqual(self.client.post('/api/session-send', content=duplicate,
            headers={'Content-Type': 'application/json', 'Origin': ORIGIN, 'X-CSRF-Token': self.csrf}).status_code, 422)
        self.assertEqual(self.backend.calls, [])

    def test_INV_WSESS_01_fixed_backend_arguments_and_no_store(self):
        self.login()
        paths = ['/api/session-projects', '/api/sessions?project=demo',
                 f'/api/session-history?project=demo&sid={SID}',
                 f'/api/session-send-status?project=demo&sid={SID}&message_id={MID}']
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('no-store', response.headers.get('cache-control', ''))
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers.get('cache-control', ''))
        self.assertEqual(self.backend.calls, [('projects',), ('list', 'demo', 0),
            ('history', 'demo', SID, None), ('status', 'demo', SID, MID), ('send', 'demo', SID, MID, 'Hello')])

    def test_INV_WSESS_05_unknown_send_and_status_keep_receipt(self):
        self.login()
        self.backend.outcome = {'status': 'delivery_unknown', 'message_id': MID, 'turn_id': None}
        sent = self.post()
        self.assertEqual(sent.status_code, 503)
        self.assertEqual(sent.json(), self.backend.outcome)
        status = self.client.get(f'/api/session-send-status?project=demo&sid={SID}&message_id={MID}')
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json(), self.backend.outcome)

    def test_INV_WSESS_01_domain_status_mapping(self):
        self.login()
        for outcome, status in [({'error': 'invalid_request'}, 422), ({'error': 'stale'}, 409),
                                ({'error': 'unavailable'}, 503),
                                ({'status': 'rejected', 'message_id': MID, 'turn_id': None}, 409)]:
            self.backend.outcome = outcome
            response = self.post()
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json(), outcome)
            self.assertIn('no-store', response.headers.get('cache-control', ''))


if __name__ == '__main__':
    unittest.main()
