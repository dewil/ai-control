"""Independent INV-WSESS-18 summary tests from public specification only."""
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


class SummaryRPC:
    def __init__(self):
        self.calls = []
        self.generation = 1
        self.pages = {None: {'data': [], 'nextCursor': None}}
        self.before_call = None
        self.send_root = None
    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if self.before_call: self.before_call()
        if method == 'thread/list':
            result = self.pages[params.get('cursor')]
            if isinstance(result, Exception): raise result
            return result
        if self.send_root is not None:
            if method in ('thread/read','thread/resume'): return {'thread': {'id': SID, 'cwd': self.send_root}}
            if method=='turn/start': return {'turn': {'id': SID}}
        raise AssertionError('Summary must not call native ' + method)


class ProjectSummaryContract(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        self.module = importlib.import_module('_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='control-summary-contract-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.base.chmod(0o700)
        self.roots = {name: self.base / name for name in ('alpha', 'beta', 'secret')}
        for path in self.roots.values(): path.mkdir(mode=0o700)
        self.roots['alias-alpha'] = self.roots['alpha']
        self.roots['missing'] = self.base / 'absent'
        self.names = ['alpha', 'beta', 'alias-alpha', 'missing']
        self.resolved = []
        self.resolve_errors = {}
        self.rpc = SummaryRPC()
        self.now = [1800000000.0]
        self.addCleanup(patch.stopall)
        patch('time.monotonic', side_effect=lambda: self.now[0]).start()
        patch('time.time', side_effect=lambda: self.now[0]).start()
        args = (self.rpc, self.resolve, lambda: list(self.names), str(self.base / 'receipts'))
        if callable(getattr(self.module.SessionChat, 'project_summary', None)):
            self.chat = self.module.SessionChat(*args, summary_clock=lambda: self.now[0],
                summary_wall_clock=lambda: self.now[0], summary_generation=lambda: self.rpc.generation)
        else:
            self.chat = self.module.SessionChat(*args)

    def resolve(self, name):
        self.resolved.append(name)
        if name in self.resolve_errors: raise self.resolve_errors[name]
        return str(self.roots[name])

    def thread(self, number, root='alpha', updated=100, source='cli', archived=False):
        return {'id': '55555555-5555-4555-8555-' + str(number).zfill(12), 'cwd': str(self.roots[root]),
                'updatedAt': updated, 'source': source, 'archived': archived, 'status': {'type': 'idle'},
                'name': 'Synthetic metadata'}

    def summary(self, refresh=False):
        method = getattr(self.chat, 'project_summary', None)
        self.assertTrue(callable(method), 'INV-WSESS-18 public summary service is required')
        if refresh: self.now[0] += 31
        return method()

    def rows(self, result):
        self.assertEqual(set(result), {'projects'})
        rows = {r['name']: r for r in result['projects']}
        self.assertEqual(set(rows), set(self.names))
        encoded = json.dumps(result)
        self.assertNotIn(str(self.base), encoded)
        self.assertNotIn('55555555-', encoded, 'Summary DTO cannot leak thread IDs')
        self.assertNotIn('secret', rows)
        return rows

    def test_INV_WSESS_18_paginated_single_multi_root_scan_counts_dedup_and_max_native_activity(self):
        self.rpc.pages = {
            None: {'data': [self.thread(1, updated=100), self.thread(2, updated=400, source='vscode'), self.thread(3, 'beta', 90)], 'nextCursor': 'p2'},
            'p2': {'data': [self.thread(1, updated=100), self.thread(4, 'beta', 300, source='appServer'), self.thread(5, 'secret', 9999),
                            self.thread(6, source='exec'), self.thread(7, source='subAgent'), self.thread(8, archived=True)], 'nextCursor': None}}
        rows = self.rows(self.summary())
        for alias in ('alpha', 'alias-alpha'):
            self.assertEqual((rows[alias]['session_count'], rows[alias]['last_activity'], rows[alias]['summary_state']), (2, 400, 'fresh'))
        self.assertEqual((rows['beta']['session_count'], rows['beta']['last_activity']), (2, 300))
        self.assertIsNone(rows['missing']['session_count']); self.assertEqual(rows['missing']['summary_state'], 'unavailable')
        self.assertEqual(len(self.rpc.calls), 2, 'Only one shared paginated scan')
        for method, params in self.rpc.calls:
            self.assertEqual(method, 'thread/list')
            self.assertEqual(set(params['cwd']), {str(self.roots['alpha']), str(self.roots['beta'])})
            self.assertEqual(params['sourceKinds'], ['cli', 'vscode', 'appServer'])
            self.assertIs(params['archived'], False)
            self.assertEqual((params['sortKey'], params['sortDirection'], params['limit']), ('updated_at', 'desc', 100))
        self.assertNotIn('secret', self.resolved, 'Grants filter before resolving roots')

    def test_INV_WSESS_18_confirmed_empty_is_zero_without_synthesized_activity(self):
        rows = self.rows(self.summary())
        for name in ('alpha', 'beta', 'alias-alpha'):
            self.assertEqual(rows[name]['session_count'], 0)
            self.assertIsNone(rows[name]['last_activity'])
            self.assertEqual(rows[name]['summary_state'], 'fresh')
        self.assertEqual(len(self.rpc.calls), 1)

    def test_INV_WSESS_18_cache_ttl_explicit_refresh_and_stale_asof_never_rejuvenates(self):
        self.rpc.pages[None] = {'data': [self.thread(1, updated=123)], 'nextCursor': None}
        original = self.rows(self.summary())['alpha']; count = len(self.rpc.calls)
        self.now[0] += 29; self.summary(); self.assertEqual(len(self.rpc.calls), count)
        self.now[0] += 2; self.summary(); self.assertGreater(len(self.rpc.calls), count)
        fresh = self.rows(self.summary())['alpha']; calls = len(self.rpc.calls)
        self.rpc.pages[None] = RuntimeError('synthetic-private-provider-failure')
        stale = self.rows(self.summary(refresh=True))['alpha']
        self.assertGreater(len(self.rpc.calls), calls)
        self.assertEqual(stale['summary_state'], 'stale')
        self.assertEqual((stale['session_count'], stale['last_activity'], stale['as_of']),
                         (fresh['session_count'], fresh['last_activity'], fresh['as_of']))
        self.now[0] += 31
        again = self.rows(self.summary())['alpha']
        self.assertEqual(again['as_of'], stale['as_of'])
        self.assertNotEqual(original['as_of'], fresh['as_of'])
        self.assertNotIn('synthetic-private', json.dumps(again))

    def test_INV_WSESS_18_rootset_and_native_generation_invalidate_cache(self):
        self.summary(); calls = len(self.rpc.calls)
        self.names = ['alpha']; self.summary()
        self.assertGreater(len(self.rpc.calls), calls)
        self.assertEqual(self.rpc.calls[-1][1]['cwd'], [str(self.roots['alpha'])])
        calls = len(self.rpc.calls); self.rpc.generation += 1; self.summary()
        self.assertGreater(len(self.rpc.calls), calls, 'New native connection generation must not reuse old summary')

    def test_INV_WSESS_18_incomplete_pages_do_not_export_partial_counts_or_replace_good(self):
        cases = {'repeat': {'data': [self.thread(2)], 'nextCursor': 'again'},
                 'malformed': {'data': [{'id': SID, 'cwd': str(self.roots['alpha'])}], 'nextCursor': None},
                 'timestamp': {'data': [self.thread(2, updated='not-a-timestamp')], 'nextCursor': None},
                 'page-error': RuntimeError('synthetic-private-page-error')}
        for label, terminal in cases.items():
            with self.subTest(label=label):
                self.rpc.pages = {None: {'data': [self.thread(1, updated=321)], 'nextCursor': None}}
                good = self.rows(self.summary(refresh=True))['alpha']
                self.rpc.pages = {None: {'data': [self.thread(2, updated=999)], 'nextCursor': 'again'}, 'again': terminal}
                calls_before=len(self.rpc.calls)
                bad = self.rows(self.summary(refresh=True))['alpha']
                if label=='repeat': self.assertLessEqual(len(self.rpc.calls)-calls_before,2,'Repeated cursor must stop immediately')
                self.assertEqual(bad['summary_state'], 'stale')
                self.assertEqual((bad['session_count'], bad['last_activity'], bad['as_of']),
                                 (good['session_count'], good['last_activity'], good['as_of']))

    def test_INV_WSESS_18_first_failure_unknown_count_never_zero(self):
        self.rpc.pages[None] = RuntimeError('synthetic-private-first-failure')
        rows = self.rows(self.summary())
        for name in ('alpha', 'beta', 'alias-alpha'):
            self.assertIn(rows[name]['summary_state'], ('unknown', 'unavailable'))
            self.assertIsNone(rows[name]['session_count']); self.assertIsNone(rows[name]['last_activity'])

    def test_INV_WSESS_18_scan_limit_is_100_pages_and_remains_incomplete(self):
        for i in range(100):
            cursor = None if i == 0 else 'page-' + str(i)
            self.rpc.pages[cursor] = {'data': [self.thread(i+1)], 'nextCursor': 'page-' + str(i+1)}
        rows = self.rows(self.summary())
        self.assertLessEqual(len(self.rpc.calls), 100)
        self.assertEqual(len(self.rpc.calls), 100, 'Limit is100 complete metadata pages')
        self.assertIsNone(rows['alpha']['session_count'])
        self.assertNotEqual(rows['alpha']['summary_state'], 'fresh')

    def test_INV_WSESS_18_deadline_bounds_scan_without_partial_fresh_result(self):
        self.rpc.pages[None] = {'data': [self.thread(1)], 'nextCursor': 'next'}
        self.rpc.before_call = lambda: self.now.__setitem__(0, self.now[0] + 16)
        rows = self.rows(self.summary())
        self.assertLessEqual(len(self.rpc.calls), 1)
        self.assertIsNone(rows['alpha']['session_count'])
        self.assertNotEqual(rows['alpha']['summary_state'], 'fresh')

    def test_INV_WSESS_18_empty_allowed_set_has_no_rpc_and_no_project_leak(self):
        self.names=[]
        self.assertEqual(self.summary(),{'projects':[]})
        self.assertEqual(self.rpc.calls,[]); self.assertEqual(self.resolved,[])

    def test_INV_WSESS_18_changed_generation_failure_cannot_reuse_previous_lastgood(self):
        self.rpc.pages[None]={'data':[self.thread(1,updated=999)],'nextCursor':None}
        self.summary(); self.rpc.generation += 1
        self.rpc.pages[None]=RuntimeError('synthetic-private-new-generation')
        rows=self.rows(self.summary())
        self.assertIsNone(rows['alpha']['session_count'])
        self.assertNotEqual(rows['alpha']['summary_state'],'stale','Lastgood belongs to old native generation')

    def test_INV_WSESS_18_canonical_root_rebind_invalidates_cache_without_carrying_counts(self):
        self.summary(); calls=len(self.rpc.calls)
        new=self.base/'new-alpha'; new.mkdir(mode=0o700)
        self.roots['alpha']=new; self.roots['alias-alpha']=new
        self.rpc.pages[None]={'data':[self.thread(3,updated=555)],'nextCursor':None}
        rows=self.rows(self.summary())
        self.assertGreater(len(self.rpc.calls),calls)
        self.assertEqual((rows['alpha']['session_count'],rows['alpha']['last_activity']),(1,555))
        self.assertIn(str(new),self.rpc.calls[-1][1]['cwd'])

    def test_INV_WSESS_18_confirmed_own_send_invalidates_fresh_summary(self):
        self.summary(); calls=len([c for c in self.rpc.calls if c[0]=='thread/list'])
        self.rpc.send_root=str(self.roots['alpha'])
        result=self.chat.send('alpha',SID,MID,'Synthetic summary invalidation instruction')
        self.assertEqual(result['status'],'accepted')
        self.rpc.pages[None]={'data':[self.thread(1,updated=900)],'nextCursor':None}
        rows=self.rows(self.summary())
        self.assertGreater(len([c for c in self.rpc.calls if c[0]=='thread/list']),calls)
        self.assertEqual(rows['alpha']['last_activity'],900)

    def test_INV_WSESS_18_page_over_100_rows_is_incomplete_not_silently_counted(self):
        self.rpc.pages[None]={'data':[self.thread(i+1) for i in range(101)],'nextCursor':None}
        rows=self.rows(self.summary())
        self.assertIsNone(rows['alpha']['session_count'])
        self.assertNotEqual(rows['alpha']['summary_state'],'fresh')

    def test_INV_WSESS_18_one_root_resolution_failure_is_localized_without_raw_error(self):
        self.resolve_errors['beta']=RuntimeError('synthetic-private-resolver '+str(self.roots['beta']))
        rows=self.rows(self.summary())
        self.assertEqual(rows['alpha']['summary_state'],'fresh')
        self.assertEqual(rows['beta']['summary_state'],'unavailable')
        self.assertIsNone(rows['beta']['session_count'])
        self.assertNotIn('synthetic-private',json.dumps(rows))
        self.assertEqual(self.rpc.calls[0][1]['cwd'],[str(self.roots['alpha'])])


if __name__ == '__main__': unittest.main(verbosity=2)
