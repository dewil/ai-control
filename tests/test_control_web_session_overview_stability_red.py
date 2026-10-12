"""Independent public-contract RED for stable session overview admission and rendering."""
from copy import deepcopy
import re
import unittest
from unittest.mock import patch

import participation_blind_support as s
from participation_blind_support import *
import test_control_web_participation_browser_blind as participation_browser


class OverviewNative(s.Native):
    def __init__(self, base, root):
        self.reported_user_agent = 'codex/0.161.0 (synthetic)'
        self.malformed_methods = set()
        self.thread_item_entries_override = None
        self.additive_page_fields = False
        super().__init__(base, root)

    def result(self, method, params):
        if method == 'initialize':
            return {} if self.reported_user_agent is None else {'userAgent': self.reported_user_agent}
        if method in self.malformed_methods:
            return {'data': 'not-a-bounded-list', 'nextCursor': None}
        if method == 'thread/items/list' and self.thread_item_entries_override is not None:
            return {'data': deepcopy(self.thread_item_entries_override), 'nextCursor': None}
        result = super().result(method, params)
        if self.additive_page_fields and method in ('thread/loaded/list', 'thread/turns/list', 'thread/items/list'):
            result['unused_metadata'] = {'synthetic': True}
        if method == 'thread/read' and hasattr(self, 'thread_name_override'):
            result['thread']['name'] = self.thread_name_override
        return result


class SessionOverviewReadNegotiationRed(WireCase):
    def setUp(self):
        with patch.object(s, 'Native', OverviewNative):
            super().setUp()

    def reconnect_user_agent(self, user_agent):
        self.chat.close()
        self.rpc.close()
        self.native.reported_user_agent = user_agent
        self.rpc = self.module.InteractiveRPC(str(self.native.path), timeout=1)
        self.addCleanup(self.rpc.close)
        self.chat = self.make_chat()
        self.rpc('thread/read', dict(threadId=SID, includeTurns=False))

    def seed_completed(self):
        self.native.loaded = [SID]
        self.native.status = dict(type='idle', activeFlags=[])
        self.native.turns = [dict(id=TURN, status='completed', completedAt=1800000000,
            items=[dict(id='future-final', type='agentMessage', phase='final_answer',
                        text='Synthetic final witness')])]

    def test_valid_read_shapes_admit_missing_and_future_reported_versions(self):
        # INV-SOV-01: valid bounded reads are admitted independently of native_version.
        self.seed_completed()
        for user_agent, label in ((None, 'missing version'),
                                  ('codex/9.99.0 (synthetic future)', 'future version')):
            with self.subTest(version=label):
                self.reconnect_user_agent(user_agent)
                row = self.wait_for(lambda: next((item for item in self.overview().get('rows', [])
                                                  if item['sid'] == SID), None),
                                    'Valid read shapes must publish a fresh session row', timeout=5)
                self.assertEqual(row['freshness']['state'], 'fresh')
                self.assertTrue(row['result']['ready'])
                self.assertEqual((row['result']['status'], row['result']['item_id']),
                                 ('completed', 'future-final'))
                self.assert_read_only()

    def test_future_version_accepts_unconsumed_additive_page_metadata(self):
        # INV-SOV-READ: require consumed fields, not an exact wrapper around them.
        self.seed_completed()
        self.native.additive_page_fields = True
        self.reconnect_user_agent('codex/9.99.0 (synthetic future)')
        self.overview()
        self.wait_for(lambda: 'thread/loaded/list' in self.native.methods(),
                      'The bounded overview read must start with the loaded-session page', timeout=7)
        self.assert_read_only()
        row = self.wait_for(lambda: next((item for item in self.overview().get('rows', [])
                                          if item['sid'] == SID and item['freshness']['state'] == 'fresh'
                                          and item['result'] and item['result']['ready']), None),
                            'Future version plus harmless unused page metadata must still prove a fresh final result',
                            timeout=8)
        required = {'thread/loaded/list', 'thread/turns/list', 'thread/items/list'}
        self.assertTrue(required.issubset(set(self.native.methods())))
        self.assertEqual((row['result']['status'], row['result']['item_id']),
                         ('completed', 'future-final'))
        self.assert_read_only()

    def test_one_malformed_read_degrades_only_that_feature_without_mutation(self):
        # INV-SOV-01: unknown consumed shape is partial locally, not a global outage.
        self.seed_completed()
        self.native.malformed_methods.add('thread/loaded/list')
        self.overview()
        self.wait_for(lambda: 'thread/loaded/list' in self.native.methods(),
                      'Overview must attempt only its bounded loaded-session read')
        # The worker result is observed only after it has completed; use the
        # closed public reason vocabulary rather than leaking a method name.
        overview = self.overview()
        self.assertIsInstance(overview, dict)
        self.assertIn('coverage', overview)
        self.assertTrue(overview['coverage']['partial'])
        self.assertTrue(set(overview['coverage']['reasons']) & {'source_unavailable', 'unsupported'})
        history = self.chat.history('demo', SID)
        self.assertIn('turns', history, 'A malformed overview read must not disable selected history')
        self.assert_read_only()

    def test_malformed_consumed_thread_name_degrades_fresh_read(self):
        # INV-SOV-01: missing/null title is permitted; structured title is an
        # incompatible consumed shape, not a nameless fresh session.
        self.seed_completed()
        self.wait_for(lambda: self.overview().get('health') == 'fresh',
                      'Warm valid projection must exist before the malformed read', timeout=7)
        self.native.thread_name_override = {'text': 'not-the-supported-title-shape'}
        snapshot = self.wait_for(lambda: (value if value.get('health') in ('stale', 'unavailable') else None)
                                 if isinstance(value := self.overview(), dict) else None,
                                 'Malformed consumed name must not publish a fresh fallback row', timeout=8)
        self.assertTrue(snapshot['coverage']['partial'])
        self.assertTrue(all(row['freshness']['state'] != 'fresh' for row in snapshot['rows']))
        self.assert_read_only()

    def test_history_only_in_progress_without_loaded_snapshot_is_not_confirmed(self):
        # INV-SOV-01: selected-history proof cannot substitute for fresh loaded-list membership.
        self.native.status = dict(type='active', activeFlags=[])
        self.native.turns = [dict(id=TURN, status='inProgress', items=[])]
        self.native.malformed_methods.add('thread/loaded/list')
        history = self.chat.history('demo', SID)
        self.assertIn('turns', history)
        self.overview()
        self.wait_for(lambda: 'thread/loaded/list' in self.native.methods(),
                      'Overview must attempt the loaded-set read before confirming current work')
        overview = self.overview()
        row = next((item for item in overview.get('rows', []) if item['sid'] == SID), None)
        if row is not None:
            self.assertNotEqual(row['running'], 'confirmed',
                                'History status alone is not loaded-session proof')
        self.assertTrue(overview['coverage']['partial'])
        self.assert_read_only()

    def test_mixed_malformed_final_item_page_never_publishes_fresh_ready(self):
        # INV-SOV-02: every consumed item entry needs matching turnId and unique, valid item ID.
        self.seed_completed()
        warm = self.wait_for(lambda: (value if (row := next((item for item in value.get('rows', [])
            if item['sid'] == SID), None)) and row['freshness']['state'] == 'fresh' and row['result']['ready']
            else None) if isinstance(value := self.overview(), dict) else None,
            'A valid completed final item should warm the bounded cache', timeout=7)
        old_item_reads = self.native.methods().count('thread/items/list')
        self.native.thread_item_entries_override = [
            dict(turnId=TURN, item=dict(id='current-final', type='agentMessage', phase='final_answer', text='Current valid witness')),
            dict(turnId=s.OTHER, item=dict(id='foreign-final', type='agentMessage', phase='final_answer', text='Foreign turn')),
            None,
            dict(turnId=TURN, item=dict(type='agentMessage', phase='final_answer', text='Missing item ID')),
            dict(turnId=TURN, item=dict(id='current-final', type='agentMessage', phase='final_answer', text='Duplicate item ID')),
        ]
        self.overview()
        self.wait_for(lambda: self.native.methods().count('thread/items/list') > old_item_reads,
                      'The next public poll must consume the injected mixed item page', timeout=8)
        snapshot = self.wait_for(lambda: (value if value.get('revision', 0) > warm['revision'] or
            value.get('health') in ('stale', 'unavailable') else None)
            if isinstance(value := self.overview(), dict) else None,
            'The public projection must publish the poll outcome', timeout=4)
        row = next((item for item in snapshot['rows'] if item['sid'] == SID), None)
        self.assertIsNotNone(row, 'The last-known completion may remain visible as stale')
        self.assertEqual(row['result']['status'], 'completed')
        self.assertFalse(row['result']['ready'])
        self.assertNotEqual(row['freshness']['state'], 'fresh')
        self.assertIn(snapshot['health'], ('stale', 'unavailable'),
                      'A partially invalid consumed item page cannot leave a fresh ready projection')
        self.assert_read_only()


def overview_row(index, project, sid, label, *, activity='unknown', running='unconfirmed',
                 waits=(), questions=(), result=None, freshness='fresh'):
    return dict(session_key=f'{index:064x}', project=project, sid=sid, label=label, vendor='codex',
        activity=activity, running=running, waits=list(waits), questions=deepcopy(list(questions)),
        result=deepcopy(result), freshness=dict(state=freshness, observed_at=1800000000))


def completed_result(item, *, ready=True, status='completed'):
    return dict(turn_id=s.TURN, item_id=item, status=status, ready=ready,
                completed_at=1800000000)


class SessionOverviewBrowserRed(unittest.TestCase):
    # Reuse only the existing isolated Chromium fixture helpers. Do not inherit
    # its unrelated participation tests into this bounded suite.
    @classmethod
    def setUpClass(cls):
        participation_browser.ParticipationBrowserBlind.setUpClass.__func__(cls)

    setUp = participation_browser.ParticipationBrowserBlind.setUp
    tearDown = participation_browser.ParticipationBrowserBlind.tearDown
    until = participation_browser.ParticipationBrowserBlind.until
    select = participation_browser.ParticipationBrowserBlind.select
    participation_ready = participation_browser.ParticipationBrowserBlind.participation_ready
    posts = participation_browser.ParticipationBrowserBlind.posts

    def set_overview_rows(self, rows, revision=1):
        value=deepcopy(s.overview_dto(revision=revision)); value['rows']=deepcopy(rows)
        self.backend.overview=value
        # Authorized namespace includes every synthetic overview project; page title
        # precedence should not erase the unrelated overview-only source identities.
        names=sorted({'demo',*(row['project'] for row in rows)})
        self.backend.session_projects=lambda:dict(projects=[dict(name=name) for name in names])
        self.backend.session_project_summary=lambda:dict(projects=[dict(name=name,session_count=0,
            last_activity=None,summary_state='fresh',as_of=1800000000) for name in names])

    def browser_navigator(self):
        from control_browser_helpers import session_navigator
        self.select(); self.participation_ready()
        self.assertEqual(self.posts(),[])
        listing=session_navigator(self.page)
        self.page.get_by_role('combobox',name='Проект',exact=True).select_option(label='Все проекты')
        self.page.get_by_role('button',name=re.compile(r'^Все(?:\s|[·(:]|$)')).click()
        self.page.get_by_role('button',name=re.compile(r'^(?:Обновить список|Новые:\s*\d+)$')).click()
        return listing

    def rows(self):
        listing=self.page.get_by_role('list',name='Сессии',exact=True).or_(
            self.page.get_by_role('listbox',name='Сессии',exact=True))
        return listing.get_by_role('listitem').or_(listing.get_by_role('option'))

    def filter_button(self,label):
        return self.page.get_by_role('button',name=re.compile('^'+re.escape(label)+r'(?:\s|[·(:]|$)'))

    def assert_count(self,label,count):
        button=self.filter_button(label)
        self.assertEqual(button.count(),1)
        self.assertRegex(button.get_attribute('aria-label') or button.inner_text(),r'(?<!\d)'+str(count)+r'(?!\d)')

    def assert_no_result_action(self,label):
        row=self.rows().filter(has_text=label)
        actions=row.get_by_role('button',name='Действия',exact=True)
        actions.click()
        self.assertTrue(row.get_by_role('menu').is_visible())
        self.assertEqual(row.get_by_role('menuitem',name='Открыть результат',exact=True).count(),0,
                         'A stale/non-completed snapshot cannot expose a ready-result target')
        actions.click()

    def test_group_priority_title_fallback_stale_copy_and_unique_rows(self):
        # INV-SOV-03 / INV-SOV-05: project/title, fallback, priority, stale badge, and unique row placement.
        # Public project route IDs are ASCII slugs; Unicode belongs in the title field.
        attention = overview_row(1, 'attention', SID, 'Needs attention',
            activity='active', running='confirmed', waits=['approval', 'question'],
            questions=[dict(interaction_id=s.HANDLE, state='actionable', blocking=True)],
            result=completed_result('priority-final'))
        ready = overview_row(2, 'delta', s.OTHER, 'Résumé final · Проект Δ', activity='idle',
            result=completed_result('fresh-final'))
        working_sid = '66666666-6666-4666-8666-666666666666'
        working = overview_row(3, 'work', working_sid, '  ', activity='active',
            running='confirmed')
        stale_sid = '77777777-7777-4777-8777-777777777777'
        stale = overview_row(4, 'stale', stale_sid, '', activity='not_loaded',
            result=completed_result('cached-final', ready=False), freshness='stale')
        unknown_sid = '99999999-9999-4999-8999-999999999999'
        unknown = overview_row(5, 'other', unknown_sid, 'Unconfirmed state',
            activity='unknown', freshness='stale')
        failed = overview_row(6, 'failed', s.TURN, 'Failed for review', activity='idle',
            result=completed_result('failed-item', ready=False, status='failed'))
        rows = [attention, ready, working, stale, unknown, failed]
        self.set_overview_rows(rows)
        self.page.clock.install()
        listing=self.browser_navigator()
        self.assert_count('Внимание',2); self.assert_count('Готовы',1); self.assert_count('Работают',1)
        for label in ('Needs attention','Résumé final · Проект Δ','Сессия '+working_sid[:8],
                      'Сессия '+stale_sid[:8],'Unconfirmed state','Failed for review'):
            self.until(lambda:self.rows().filter(has_text=label).count()==1,
                       'Each overview key must have one unified row: '+label)
        stale_row=self.rows().filter(has_text='Сессия '+stale_sid[:8])
        self.assertRegex(stale_row.inner_text(),r'(?i)устар|последний известный')
        self.assertIn('delta',self.rows().filter(has_text='Résumé final · Проект Δ').inner_text())
        self.filter_button('Внимание').click()
        self.assertEqual(self.rows().filter(has_text='Needs attention').count(),1)
        self.assertEqual(self.rows().filter(has_text='Failed for review').count(),1)
        self.assertEqual(self.rows().filter(has_text='Résumé final · Проект Δ').count(),0)
        self.filter_button('Готовы').click()
        self.assertEqual(self.rows().filter(has_text='Résumé final · Проект Δ').count(),1)
        self.assertEqual(self.rows().filter(has_text='Needs attention').count(),0)
        self.filter_button('Работают').click()
        self.assertEqual(self.rows().filter(has_text='Сессия '+working_sid[:8]).count(),1)
        self.assertEqual(self.rows().filter(has_text='Сессия '+stale_sid[:8]).count(),0)
        self.filter_button('Все').click()
        body=listing.inner_text()
        self.assertNotIn('cached-final',body,'Stale item IDs never become browser actions or links')
        self.assertNotIn('Synthetic final witness',body)
        self.assertEqual(self.posts(),[])

    def test_attention_priority_excludes_fresh_ready_row_from_review_count(self):
        # INV-SOV-05: a high-priority attention row belongs to one group and not the ready count.
        row = overview_row(8, 'counter', SID, 'Ready with question', activity='idle',
            waits=['question'],
            questions=[dict(interaction_id=s.HANDLE, state='actionable', blocking=True)],
            result=completed_result('counter-ready'))
        self.set_overview_rows([row])
        self.page.clock.install()
        self.browser_navigator()
        self.until(lambda:self.rows().filter(has_text='Ready with question').count()==1)
        self.assert_count('Внимание',1); self.assert_count('Готовы',0)
        self.filter_button('Готовы').click()
        self.assertEqual(self.rows().filter(has_text='Ready with question').count(),0)
        self.filter_button('Внимание').click()
        self.assertEqual(self.rows().filter(has_text='Ready with question').count(),1)
        self.assertEqual(self.posts(),[])

    def test_loaded_completed_unload_stays_stale_active_supersedes_and_unload_does_not_resurrect(self):
        # INV-SOV-04: live, last-known, and active-after-completion are distinct.
        sid = '55555555-5555-4555-8555-555555555555'
        label = 'Bounded session'
        def completed(*, ready, freshness):
            return overview_row(7, 'lifecycle', sid, label, activity='idle' if ready else 'not_loaded',
                result=completed_result('lifecycle-final', ready=ready), freshness=freshness)
        self.set_overview_rows([completed(ready=True, freshness='fresh')])
        self.page.clock.install()
        self.browser_navigator()
        self.assertEqual(self.posts(), [], 'Opening overview performs no native answer POST')
        self.until(lambda: self.page.get_by_text(label, exact=True).count() == 1,
                   'Fresh completed result must appear in overview')

        # Native unload preserves only a visibly stale last-known completion.
        self.set_overview_rows([completed(ready=False, freshness='stale')], revision=2)
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.rows().filter(has_text=label).get_by_text('Сведения устарели',exact=True).count()==1,
                   'Unloaded completed result must remain visible with the stale badge')
        self.assert_count('Готовы',0)
        self.assert_no_result_action(label)
        self.assertNotIn('lifecycle-final', self.page.locator('body').inner_text())

        # A fresh current inProgress replaces the old completed witness entirely.
        self.set_overview_rows([overview_row(7, 'lifecycle', sid, label,
            activity='active', running='confirmed', freshness='fresh')], revision=3)
        self.page.clock.fast_forward(6000)
        self.until(lambda:bool(re.search(r'(?<!\d)1(?!\d)',self.filter_button('Работают').inner_text())))
        self.assertEqual(self.rows().filter(has_text=label).get_by_text('Сведения устарели',exact=True).count(),0)
        self.assertNotIn('lifecycle-final', self.page.locator('body').inner_text())

        # Unload after that active observation cannot resurrect the completed result.
        self.set_overview_rows([overview_row(7, 'lifecycle', sid, label,
            activity='not_loaded', running='unconfirmed', result=None, freshness='stale')], revision=4)
        self.page.clock.fast_forward(6000)
        self.until(lambda:bool(re.search(r'(?<!\d)0(?!\d)',self.filter_button('Работают').inner_text())))
        self.assert_count('Готовы',0)
        self.assertEqual(self.rows().filter(has_text=label).count(),1)
        self.assertEqual(self.rows().filter(has_text=label).get_by_text('Сведения устарели',exact=True).count(),1)
        self.assert_no_result_action(label)
        self.assertNotIn('lifecycle-final', self.page.locator('body').inner_text())
        self.assertEqual(self.posts(), [])
