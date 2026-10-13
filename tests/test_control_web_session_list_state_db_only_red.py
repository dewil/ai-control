"""Blind INV-PSTAB-02 RED contracts for cold project session listing."""
import copy
import inspect
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from test_control_web_session_chat_contract import feature
from test_control_web_session_chat_configured_list_cloud import (
    CONTEXT, FakeCreator, SID1, SID2, SID3, SID4, SID5, SID6, SID7, SID8, SID9,
)


SIDS = (SID1, SID2, SID3, SID4, SID5, SID6, SID7, SID8, SID9)
SID10 = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


class IndexedRPC:
    """Synthetic native index with explicit continuation and a costly default path."""
    def __init__(self, root, *, rows=None, fail=None, mutate=None):
        self.root = Path(root)
        self.rows = rows if rows is not None else [
            {'id': sid, 'cwd': str(root), 'name': f'Native {index}',
             'status': {'type': 'idle'}, 'updatedAt': 1000 - index,
             'source': 'cli', 'archived': False}
            for index, sid in enumerate(SIDS, 1)
        ]
        self.calls = []
        self.context = dict(CONTEXT)
        self.fail = fail
        self.malformed = False
        self.mutate = mutate
        self.repair_calls = 0

    def model_context(self):
        return dict(self.context)

    def prepare_context(self, timeout=None):
        # Match InteractiveRPC's fenced read seam: prepare a validated snapshot
        # before the list/read sequence, then prove that generation at publish.
        context = copy.deepcopy(self.context)
        required = {'schema', 'vendor', 'context_kind', 'context_id',
                    'transport_generation', 'context_generation', 'native_version'}
        if (set(context) != required or context['schema'] != 1 or
                context['vendor'] != 'codex' or context['context_kind'] != 'legacy_unbound' or
                not isinstance(context['context_id'], str) or len(context['context_id']) != 64 or
                any(type(context[key]) is not int or context[key] < 0
                    for key in ('transport_generation', 'context_generation')) or
                not isinstance(context['native_version'], str)):
            raise RuntimeError('synthetic invalid native read context')
        return context

    def receipt_context(self):
        return {key: self.context[key] for key in ('schema', 'vendor', 'context_kind', 'context_id')}

    def call_in_generation(self, method, params, *, transport_generation,
                           context_generation, timeout=None):
        before = (self.context['transport_generation'], self.context['context_generation'])
        if before != (transport_generation, context_generation):
            raise RuntimeError('synthetic stale peer generation')
        try:
            return self(method, params)
        except Exception:
            if self.mutate == 'generation-after-read-error':
                self.mutate = None
                self.context['context_generation'] += 1
            raise

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method == 'thread/list':
            if params.get('useStateDbOnly') is not True:
                self.repair_calls += 1  # represents native default scan/repair latency
            if self.fail:
                raise self.fail
            if self.malformed:
                return {'data': 'malformed', 'nextCursor': None}
            cursor = params.get('cursor')
            page = self.rows[:8] if cursor is None else self.rows[8:]
            next_cursor = 'opaque-native-next' if cursor is None and len(self.rows) > 8 else None
            return {'data': copy.deepcopy(page), 'nextCursor': next_cursor}
        if method in ('thread/read', 'thread/resume'):
            if callable(self.mutate):
                self.mutate(method)
            elif self.mutate == 'root':
                self.mutate = None
                self.root = self.root.parent / 'rebound'
            elif self.mutate == 'generation':
                self.mutate = None
                self.context['context_generation'] += 1
            sid = params.get('threadId')
            row = next((row for row in self.rows if row['id'] == sid), None)
            return {'thread': {'id': sid, 'cwd': str(self.root),
                               'name': row['name'] if row else 'Fresh proof',
                               'status': {'type': 'idle'},
                               'updatedAt': row.get('updatedAt') if row else 1000}}
        raise AssertionError('unexpected synthetic native RPC: ' + method)


class SessionListStateDbOnlyRED(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-state-db-list-red-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.root = self.base / 'project'
        self.root.mkdir(mode=0o700)

    def overlay(self):
        return {'sessions': [{
            'sid': SID1, 'project': 'demo', 'vendor': 'codex',
            'context_mode': 'configured', 'title': 'Duplicate overlay loses',
            'status': 'active', 'updated_at': 9000,
        }, {
            'sid': SID10, 'project': 'demo', 'vendor': 'codex',
            'context_mode': 'configured', 'title': 'Fresh configured row',
            'status': 'idle', 'updated_at': 8000,
        }], 'truncated': False}

    def make_chat(self, rpc, creator=None, root_state=None):
        if creator is None:
            creator = FakeCreator({'sessions': [], 'truncated': False})
        if root_state is None:
            root_state = {'root': self.root}
        parameters = inspect.signature(self.module.SessionChat).parameters
        self.assertIn('configured_creator', parameters,
                      'Configured origin overlay seam must remain available to list_sessions')
        return self.module.SessionChat(
            rpc, lambda alias: str(root_state['root']) if alias == 'demo'
            else (_ for _ in ()).throw(ValueError('synthetic permission denied')),
            lambda: ['demo'], str(self.base / 'receipts'),
            configured_creator=creator), root_state

    def list_calls(self, rpc):
        return [(method, params) for method, params in rpc.calls if method == 'thread/list']

    def test_each_native_page_is_index_only_and_overlay_merge_keeps_pagination_and_fresh_proofs(self):
        rpc = IndexedRPC(self.root)
        creator = FakeCreator(self.overlay())
        chat, _ = self.make_chat(rpc, creator)

        first = chat.list_sessions('demo', page=0)
        second = chat.list_sessions('demo', page=1)
        pages = self.list_calls(rpc)
        self.assertGreaterEqual(len(pages), 2, 'Every native index cursor page must be consumed')
        self.assertTrue(all(params.get('useStateDbOnly') is True for _, params in pages),
                        'Every native thread/list page must use the current state DB only')
        self.assertEqual(rpc.repair_calls, 0,
                         'Cold listing must never enter the default JSONL scan/repair path')

        combined = first.get('rows', []) + second.get('rows', [])
        self.assertEqual(len(combined), 10,
                         'Pagination must include all nine indexed sessions and the configured overlay row')
        self.assertEqual([row['sid'] for row in combined], [SID10, *SIDS],
                         'Overlay/native merge must sort by fresh activity while duplicate native metadata wins')
        by_sid = {row['sid']: row for row in combined}
        self.assertEqual(set(by_sid), set(SIDS) | {SID10},
                         'Index continuation and overlay membership must both be complete')
        self.assertEqual(by_sid[SID1]['title'], 'Native 1',
                         'Fresh native thread/read proof retains authoritative duplicate metadata')
        self.assertEqual(by_sid[SID10]['title'], 'Fresh configured row')
        native_ids = {row['sid'] for row in combined if row['sid'] != SID10}
        proved = {params.get('threadId') for method, params in rpc.calls if method == 'thread/read'}
        self.assertTrue(native_ids.issubset(proved),
                        'Every exported native row needs a fresh per-row thread/read proof')
        self.assertIn('opaque-native-next', [params.get('cursor') for _, params in pages],
                      'Opaque native pagination cursor must be forwarded unchanged')
        self.assertIs(first.get('has_more'), True)
        self.assertIs(second.get('has_more'), False)
        self.assertEqual(creator.calls, ['demo', 'demo'])

    def test_index_error_or_malformed_result_is_unavailable_without_slow_empty_fallback(self):
        cases = (
            ('unsupported-or-error', RuntimeError('synthetic state-db-only unsupported')),
            ('malformed-index-page', None),
        )
        for label, failure in cases:
            with self.subTest(case=label):
                rpc = IndexedRPC(self.root, fail=failure)
                if failure is None:
                    rpc.malformed = True
                chat, _ = self.make_chat(rpc)
                result = chat.list_sessions('demo')
                self.assertEqual(result, {'error': 'unavailable'},
                                 'Index failure/malformed page must remain visible as unavailable')
                calls = self.list_calls(rpc)
                self.assertTrue(calls)
                self.assertTrue(all(params.get('useStateDbOnly') is True for _, params in calls))
                self.assertEqual(rpc.repair_calls, 0,
                                 'Unavailable index must not silently invoke scan/repair and return empty')

    def test_root_or_peer_generation_change_during_row_proof_denies_list_export(self):
        for fence in ('root', 'generation'):
            with self.subTest(fence=fence):
                rpc = IndexedRPC(self.root, mutate=fence)
                root_state = {'root': self.root}
                if fence == 'root':
                    def change_root(method):
                        if method == 'thread/read' and root_state['root'] == self.root:
                            rebound = self.base / 'rebound'
                            rebound.mkdir(exist_ok=True)
                            root_state['root'] = rebound
                    rpc.mutate = change_root
                chat, _ = self.make_chat(rpc, root_state=root_state)
                result = chat.list_sessions('demo')
                self.assertEqual(result, {'error': 'stale'},
                                 'Final root/peer generation recheck must deny raced list results')
                self.assertEqual(rpc.repair_calls, 0)

    def test_fenced_read_exception_is_stale_only_when_prepared_context_drifted(self):
        for drift, expected in ((True, {'error': 'stale'}),
                                (False, {'error': 'unavailable'})):
            with self.subTest(context_drift=drift):
                rpc = IndexedRPC(
                    self.root,
                    fail=RuntimeError('synthetic native read transport failure'),
                    mutate='generation-after-read-error' if drift else None)
                chat, _ = self.make_chat(rpc)
                result = chat.list_sessions('demo')
                self.assertEqual(result, expected,
                                 'Only confirmed prepared-context drift classifies a read failure as stale')
                list_calls = [call for call in rpc.calls if call[0] == 'thread/list']
                self.assertEqual(len(list_calls), 1,
                                 'Backend must not retry a failed fenced read itself')
                self.assertIs(list_calls[0][1].get('useStateDbOnly'), True)
                self.assertEqual(rpc.repair_calls, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
