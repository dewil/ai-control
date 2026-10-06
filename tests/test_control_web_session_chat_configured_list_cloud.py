"""Source-blind SessionChat list/cloud contracts for confirmed origin overlays.

Public contract: b8949ed57e2cf480b28c91cbe11738863cfaa9e6. Existing SessionChat
and CodexSessions implementations are used only as stable baseline context; all
native metadata and creator overlays are synthetic.
"""
import copy
from dataclasses import dataclass
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))

import _control_web_sessions as web_sessions  # noqa: E402

SID1 = '11111111-1111-4111-8111-111111111111'
SID2 = '22222222-2222-4222-8222-222222222222'
SID3 = '33333333-3333-4333-8333-333333333333'
SID4 = '44444444-4444-4444-8444-444444444444'
SID5 = '55555555-5555-4555-8555-555555555555'
SID6 = '66666666-6666-4666-8666-666666666666'
SID7 = '77777777-7777-4777-8777-777777777777'
SID8 = '88888888-8888-4888-8888-888888888888'
SID9 = '99999999-9999-4999-8999-999999999999'
CONTEXT = {
    'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
    'context_id': 'a' * 64, 'transport_generation': 3,
    'context_generation': 7, 'native_version': '0.160.0',
}


@dataclass(frozen=True)
class FakeCacheIdentity:
    context: object
    namespace: object


class FakeCreator:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.deadlines = []

    def overlay(self, project, *, deadline=None):
        self.calls.append(project)
        self.deadlines.append(('overlay', deadline))
        if isinstance(self.response, BaseException):
            raise self.response
        return copy.deepcopy(self.response)

    def cache_identity(self, *, deadline=None):
        self.deadlines.append(('cache_identity', deadline))
        return FakeCacheIdentity(MappingProxyType(dict(CONTEXT)), None)


class SyntheticRPC:
    def __init__(self, root, rows):
        self.root = Path(root)
        self.rows = list(rows)
        self.calls = []
        self.generation = 1
        self.by_id = {row['id']: row for row in self.rows}

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method == 'thread/list':
            return {'data': copy.deepcopy(self.rows), 'nextCursor': None}
        if method == 'thread/read':
            sid = params.get('threadId')
            row = self.by_id[sid]
            return {'thread': {
                'id': sid, 'cwd': str(self.root), 'name': row['name'],
                'status': copy.deepcopy(row['status']), 'updatedAt': row['updatedAt'],
            }}
        raise AssertionError('unexpected synthetic RPC: ' + method)


class ConfiguredOriginSessionChatListCloud(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        self.module = importlib.import_module('_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='control-sessionchat-cloud-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.base.chmod(0o700)
        self.root = self.base / 'project'
        self.root.mkdir(mode=0o700)
        self.receipts = self.base / 'send-receipts'

    def native(self, sid, number, *, updated=1000, title=None, status='idle'):
        return {
            'id': sid, 'cwd': str(self.root), 'name': title or f'Native {number}',
            'status': {'type': status}, 'updatedAt': updated, 'source': 'cli',
            'archived': False,
        }

    def overlay(self, sid, *, title, status='idle', updated=1):
        return {
            'sid': sid, 'project': 'demo', 'vendor': 'codex',
            'context_mode': 'configured', 'title': title,
            'status': status, 'updated_at': updated,
        }

    def chat(self, rpc, creator, *, clock=None):
        parameters = inspect.signature(self.module.SessionChat).parameters
        self.assertIn('configured_creator', parameters,
                      'SessionChat needs the trusted configured_creator constructor seam')
        kwargs = {'configured_creator': creator}
        if clock is not None:
            kwargs.update(summary_clock=clock, summary_wall_clock=lambda: 1800000000,
                          summary_generation=lambda: rpc.generation)
        return self.module.SessionChat(
            rpc, lambda project: str(self.root), lambda: ['demo'],
            str(self.receipts), **kwargs)

    def test_INV_WSESS_35_list_merges_before_pagination_deduplicates_full_sid_and_prefers_native_metadata(self):
        rows = [self.native(sid, index, updated=1000 - index)
                for index, sid in enumerate((SID1, SID2, SID3, SID4, SID5, SID6, SID7, SID8))]
        rpc = SyntheticRPC(self.root, rows)
        creator = FakeCreator({'sessions': [
            self.overlay(SID1, title='Overlay duplicate must lose', status='active', updated=9000),
            self.overlay(SID9, title='Confirmed loaded empty', updated=900),
        ], 'truncated': False})
        chat = self.chat(rpc, creator)
        first = chat.list_sessions('demo', page=0)
        second = chat.list_sessions('demo', page=1)
        self.assertEqual(len(first['rows']), 8)
        self.assertIs(first['has_more'], True,
                      'pagination must be computed after adding the confirmed ninth row')
        self.assertEqual(second['rows'], [{
            'sid': SID9, 'title': 'Confirmed loaded empty', 'status': 'idle', 'vendor': 'codex'}])
        self.assertIs(second['has_more'], False)
        by_sid = {row['sid']: row for row in first['rows'] + second['rows']}
        self.assertEqual(len(by_sid), 9, 'full canonical SID dedup keeps one row per session')
        self.assertEqual(by_sid[SID1]['title'], 'Native 0',
                         'already-authoritative native metadata wins duplicate overlay metadata')
        self.assertEqual(by_sid[SID1]['status'], 'idle')
        self.assertEqual(by_sid[SID1]['vendor'], 'codex')
        exported = json.dumps(first) + json.dumps(second)
        self.assertNotIn(str(self.base), exported)
        self.assertNotIn('updated_at', exported)
        self.assertEqual(creator.calls, ['demo', 'demo'])

    def test_INV_WSESS_35_project_summary_deduplicates_native_activity_and_uses_only_complete_overlay_evidence(self):
        rpc = SyntheticRPC(self.root, [self.native(SID1, 1, updated=100)])
        creator = FakeCreator({'sessions': [
            self.overlay(SID1, title='Duplicate', updated=9000),
            self.overlay(SID2, title='Loaded empty', updated=500),
        ], 'truncated': False})
        now = [2000.0]
        chat = self.chat(rpc, creator, clock=lambda: now[0])
        summary = chat.project_summary()['projects'][0]
        self.assertEqual(summary['name'], 'demo')
        self.assertEqual((summary['session_count'], summary['last_activity']), (2, 500),
                         'native full-SID duplicate wins; fresh overlay updated_at adds only its new SID')
        self.assertEqual(summary['summary_state'], 'fresh')

        # Expire the existing summary TTL, then provide incomplete overlay evidence.
        now[0] += 31
        creator.response = {'sessions': [self.overlay(SID3, title='Partial', updated=9999)],
                            'truncated': True}
        incomplete = chat.project_summary()['projects'][0]
        self.assertIn(incomplete['summary_state'], ('unknown', 'stale'))
        if incomplete['summary_state'] == 'stale':
            self.assertEqual((incomplete['session_count'], incomplete['last_activity']), (2, 500),
                             'stale state may retain only the last complete summary')
        else:
            self.assertIsNone(incomplete['session_count'],
                              'partial origin membership cannot produce a guessed count')
            self.assertIsNone(incomplete['last_activity'],
                              'partial origin membership cannot produce guessed activity')

    def test_INV_WSESS_35_first_truncated_or_unavailable_overlay_never_exports_partial_counts(self):
        for label, response in (
            ('truncated', {'sessions': [self.overlay(SID2, title='Partial', updated=999)],
                           'truncated': True}),
            ('unavailable', {'error': 'unavailable'}),
        ):
            with self.subTest(case=label):
                rpc = SyntheticRPC(self.root, [self.native(SID1, 1, updated=100)])
                creator = FakeCreator(response)
                chat = self.chat(rpc, creator, clock=lambda: 3000.0)
                summary = chat.project_summary()['projects'][0]
                self.assertIn(summary['summary_state'], ('unknown', 'unavailable'))
                self.assertIsNone(summary['session_count'])
                self.assertIsNone(summary['last_activity'])


if __name__ == '__main__':
    unittest.main()
