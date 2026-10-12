"""INV-APRI01..04 public browser contract against synthetic local HTTP only."""
from copy import deepcopy
import re
import time
import unittest
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
import live_sse_blind_support as live
import participation_blind_support as part


SID4 = '66666666-6666-4666-8666-666666666666'
SID5 = '77777777-7777-4777-8777-777777777777'
INTERACTION2 = '99999999-9999-4999-8999-999999999999'
READY_ITEM = 'attention-ready-item'


def row(index, sid, label, *, activity='idle', running='unconfirmed', waits=None,
        questions=None, result=None, freshness='fresh'):
    return dict(session_key=(hex(index)[2:] * 64)[:64], project='demo', sid=sid,
        label=label, vendor='codex', activity=activity, running=running,
        waits=list(waits or []), questions=deepcopy(questions or []), result=deepcopy(result),
        freshness=dict(state=freshness, observed_at=1800000000 if freshness == 'fresh' else 1799990000))


class PriorityBackend(live.Backend):
    def __init__(self):
        super().__init__(); self.part_calls = []; self.history_calls = []; self.selected = part.questions_dto()
        self.overview = part.overview_dto()
        q = dict(interaction_id=part.HANDLE, state='actionable', blocking=False)
        self.overview['rows'] = [
            row(1, live.SID, 'Priority approval and question', activity='active',
                waits=['approval', 'question'], questions=[dict(interaction_id=part.HANDLE,
                state='actionable', blocking=True)], result=dict(turn_id=part.TURN,
                item_id=READY_ITEM, status='completed', ready=True, completed_at=1800000000)),
            row(2, live.OTHER, 'Nonblocking question in active work', activity='active',
                running='confirmed', questions=[dict(interaction_id=INTERACTION2,
                state='actionable', blocking=False)]),
            row(3, live.THIRD, 'Ready answer', result=dict(turn_id=part.TURN,
                item_id=READY_ITEM, status='completed', ready=True, completed_at=1800000000)),
            row(4, SID4, 'Confirmed work', activity='idle', running='confirmed'),
            row(5, SID5, 'Active Codex work', activity='active'),
        ]
        self.overview['coverage'] = dict(partial=True, reasons=['native_callbacks_partial'])
        self.extra_sessions = [SID4, SID5]

    def participation_overview(self):
        self.part_calls.append(('overview',)); return deepcopy(self.overview)

    def session_questions(self, project, sid):
        self.part_calls.append(('questions', project, sid)); return deepcopy(self.selected)

    def session_question_answer(self, *args):
        raise AssertionError('Attention overview must not submit question answers')

    def session_list(self, project, page):
        value = super().session_list(project, page)
        value['rows'].extend(dict(sid=sid, title=title, status='idle') for sid, title in
            ((SID4, 'Confirmed work'), (SID5, 'Active Codex work')))
        for item in value['rows']:
            item['vendor'] = 'codex'
        return value

    def session_history(self, project, sid, cursor):
        self.history_calls.append((project, sid, cursor))
        if sid in (live.SID, live.THIRD):
            return dict(turns=[dict(id=part.TURN, status='completed', items=[dict(
                id=READY_ITEM, role='assistant', text='Synthetic ready answer target',
                truncated=False, timestamp=1770000000, time_precision='item')])],
                next_cursor=None, truncated=False, recent_sends=[], session_settings=live.settings())
        return super().session_history(project, sid, cursor)


class AttentionPriorityBrowserBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start(); cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(headless=True); cls.addClassCleanup(cls.browser.close)
        if cls.browser.version != '153.0.8010.12':
            raise RuntimeError('Mandatory Chromium153 drift: explicit rebaseline required, no SKIP')

    def setUp(self):
        with patch.object(live, 'Backend', PriorityBackend):
            self.fixture = live.Fixture(transport=True, session_store=True)
        self.addCleanup(self.fixture.stop); self.fixture.login(); self.backend = self.fixture.backend
        self.context = self.browser.new_context(viewport=dict(width=390, height=900))
        self.addCleanup(self.context.close)
        name, value = self.fixture.cookie.split('=', 1)
        self.context.add_cookies([dict(name=name, value=value, url=self.fixture.origin)])
        self.page = self.context.new_page(); self.page.set_default_timeout(2200)
        self.errors = []; self.requests = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('request', lambda request:self.requests.append((request.method, request.url,
                                                                     request.post_data)))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def until(self, predicate, message='Expected public attention panel outcome', timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            self.page.wait_for_timeout(20)
        self.assertTrue(predicate(), message)

    def open_navigator(self, *, navigate=False):
        if navigate:
            self.page.goto(self.fixture.origin)
        tab = self.page.get_by_role('tab', name='Сессии', exact=True)
        if tab.get_attribute('aria-selected') != 'true':
            tab.click()
        existing = self.page.get_by_role('dialog', name='Сессии', exact=True)
        if existing.count() and existing.is_visible():
            return existing
        trigger = self.page.get_by_role('button',
            name=re.compile(r'^(?:Открыть список сессий|Сессии · внимание \d+)$'))
        trigger.click()
        drawer = self.page.get_by_role('dialog', name='Сессии', exact=True)
        expect(drawer).to_be_visible()
        self.until(lambda:drawer.get_by_role('combobox', name='Проект', exact=True).count() == 1,
                   'Project filter must be present in the session navigator')
        return drawer

    def session_list(self, drawer):
        return drawer.get_by_role('list', name='Сессии', exact=True)

    def session_item(self, drawer, label):
        return self.session_list(drawer).get_by_role('listitem').filter(has_text=label)

    def open_panel(self):
        drawer = self.open_navigator(navigate=True)
        self.until(lambda:any(call[0] == 'overview' for call in self.backend.part_calls),
                   'Public overview request missing')
        items = self.session_list(drawer).get_by_role('listitem')
        expected = len(self.backend.overview['rows'])
        self.until(lambda:drawer.is_visible() and items.count() == expected,
            f'All {expected} synthetic sessions must render in the unified list; currently '
            f'{items.count()} rows and navigator visible={drawer.is_visible()}')
        return drawer

    def test_INV_APRI01_unified_list_deduplicates_and_filters_priority_states(self):
        # The old three visible priority groups are superseded by USN's one
        # snapshot list with independent status filters.
        drawer = self.open_panel()
        items = self.session_list(drawer).get_by_role('listitem')
        self.assertEqual(self.page.get_by_role('list', name='Сессии', exact=True).count(), 1,
                         'There is one visible session list, not separate priority sections')
        labels = [item.get_by_role('button').first.inner_text() for item in items.all()]
        self.assertEqual(labels, ['Priority approval and question', 'Ready answer',
                                  'Nonblocking question in active work', 'Confirmed work', 'Active Codex work'],
                         'All status classes share one stable activity-ordered snapshot')
        self.assertEqual(len(labels), len(set(labels)), 'Union dedup renders each known session once')

        attention = drawer.get_by_role('button', name=re.compile(r'^Внимание\s*·\s*2$'))
        ready = drawer.get_by_role('button', name=re.compile(r'^Готовы\s*·\s*1$'))
        working = drawer.get_by_role('button', name=re.compile(r'^Работают\s*·\s*0$'))
        expect(attention).to_be_visible(); expect(ready).to_be_visible(); expect(working).to_be_visible()
        attention.click()
        self.until(lambda:items.count() == 2, 'Attention filter must show its two unique rows')
        self.assertEqual({item.get_by_role('button').first.inner_text() for item in items.all()},
                         {'Priority approval and question', 'Nonblocking question in active work'})
        ready.click()
        self.until(lambda:items.count() == 1, 'Ready filter must show the one completed target')
        self.assertEqual(items.first.get_by_role('button').first.inner_text(), 'Ready answer')
        drawer.get_by_role('button', name=re.compile(r'^Все\s*·\s*5$')).click()
        self.until(lambda:items.count() == 5, 'All filter restores the fixed union snapshot')

    def test_INV_APRI02_unified_actions_keep_question_result_and_readonly_approval(self):
        drawer = self.open_panel()
        approval = self.session_item(drawer, 'Priority approval and question')
        badge_text = approval.inner_text()
        with self.subTest(contract='attention and approval remain visible in the compact row'):
            self.assertIn('Разрешение в Codex', badge_text)
            self.assertIn('?', badge_text, 'Attention state has a visible text marker')
        with self.subTest(contract='native approval remains visible-only'):
            approval.get_by_role('button', name='Действия', exact=True).click()
            menu = approval.get_by_role('menu')
            expect(menu).to_be_visible()
            self.assertEqual(menu.get_by_role('menuitem',
                name=re.compile('Разрешить|Отклонить|Approve|Deny', re.I)).count(), 0)
            self.assertEqual(menu.get_by_role('menuitem', name='Открыть вопрос', exact=True).count(), 1)
            self.assertEqual(menu.get_by_role('menuitem', name='Открыть результат', exact=True).count(), 1)
            self.assertEqual([request for request in self.requests if request[0] == 'POST' and
                              '/api/session-question-answer' in request[1]], [])

    def test_INV_APRI02_question_and_ready_buttons_keep_exact_session_and_item_targets(self):
        drawer = self.open_panel()
        approval = self.session_item(drawer, 'Priority approval and question')
        approval.get_by_role('button', name='Действия', exact=True).click()
        approval.get_by_role('menuitem', name='Открыть вопрос', exact=True).click()
        self.until(lambda:self.page.get_by_text('Synthetic choice?', exact=True).count() == 1,
                   'Question action must open the exact interaction')
        self.assertTrue(any(call[:3] == ('questions', 'demo', live.SID)
                            for call in self.backend.part_calls), 'Question navigation changed its bound session')
        drawer = self.open_navigator()
        approval = self.session_item(drawer, 'Priority approval and question')
        approval.get_by_role('button', name='Действия', exact=True).click()
        approval.get_by_role('menuitem', name='Открыть результат', exact=True).click()
        self.until(lambda:self.page.get_by_text('Synthetic ready answer target', exact=True).count() == 1,
                   'Ready-result action must open its exact final item')
        self.assertIn(('demo', live.SID, None), self.backend.history_calls,
                      'Result navigation changed the session bound to its turn/item target')
        self.assertFalse(any(request[0] == 'POST' and '/api/session-question-answer' in request[1]
                             for request in self.requests))

    def test_INV_APRI03_status_filter_counts_partial_stale_and_safe_reason_copy(self):
        self.backend.overview['health'] = 'stale'
        self.backend.overview['rows'][0]['freshness'] = dict(state='stale', observed_at=1799990000)
        self.backend.overview['coverage'] = dict(partial=True, reasons=['deadline', 'native_callbacks_partial'])
        self.backend.overview['generated_at'] = 1799990000
        drawer = self.open_panel()
        status = drawer.get_by_role('status')
        with self.subTest(contract='observed mutually exclusive counters'):
            self.assertRegex(drawer.inner_text(), r'Внимание\s*·\s*0')
            self.assertRegex(drawer.inner_text(), r'Готовы\s*·\s*0')
        with self.subTest(contract='stale and partial are explicit with safe reason labels'):
            expect(status).to_be_visible()
            self.assertRegex(status.inner_text(), r'(?i)(частич|не подтверждена|недоступ)')
            self.assertNotIn('native_callbacks_partial', status.inner_text())
            self.assertNotIn('deadline', status.inner_text())
            self.assertRegex(self.session_list(drawer).inner_text().lower(), r'устар|stale')

    def test_INV_APRI04_all_projects_empty_keeps_honest_partial_boundary(self):
        self.backend.overview['rows'] = []
        self.backend.overview['coverage'] = dict(partial=False, reasons=[])
        self.backend.overview['health'] = 'fresh'
        drawer = self.open_panel()
        items = self.session_list(drawer).get_by_role('listitem')
        self.assertEqual(items.count(), 0)
        self.assertRegex(drawer.inner_text(), r'(?i)(частич|обновите список|выберите проект)')
        self.assertNotRegex(drawer.inner_text(), r'Нет сессий для отображения|Полный список пуст')

    def test_INV_APRI03_partial_empty_never_claims_no_sessions_or_zero_waiting(self):
        self.backend.overview['rows'] = []
        self.backend.overview['coverage'] = dict(partial=True, reasons=['source_unavailable'])
        self.backend.overview['health'] = 'unavailable'
        drawer = self.open_panel()
        text = drawer.inner_text()
        with self.subTest(contract='partial empty is not a confirmed empty result'):
            self.assertIn('Список частичный', text)
            self.assertRegex(text, r'Внимание\s*·\s*0')
            self.assertNotRegex(text, r'(?i)полный список пуст|все сессии загружены')

    def test_INV_APRI04_selected_filter_freezes_rows_until_explicit_apply(self):
        self.page.clock.install()
        drawer = self.open_panel()
        attention_filter = drawer.get_by_role('button', name=re.compile(r'^Внимание'))
        attention_filter.click()
        items = self.session_list(drawer).get_by_role('listitem')
        self.assertEqual(items.count(), 2)
        frozen = self.session_item(drawer, 'Priority approval and question')
        self.backend.overview['rows'][0].update(activity='active', running='confirmed',
            waits=[], questions=[], result=None)
        self.backend.overview['revision'] += 1
        self.backend.overview['generated_at'] += 1
        self.page.clock.fast_forward(6000)
        self.until(lambda:frozen.get_by_text('Статус изменился', exact=False).count() == 1,
                   'A row that left the selected filter remains marked until explicit apply')
        self.assertEqual(items.count(), 2, 'background refresh does not remove the frozen row')
        self.assertEqual(attention_filter.get_attribute('aria-pressed'), 'true')
        self.assertRegex(attention_filter.inner_text(), r'·\s*1')
        drawer.get_by_role('button', name='Обновить список', exact=True).click()
        self.until(lambda:items.count() == 1, 'explicit apply rebuilds the selected attention snapshot')
        self.assertEqual(self.session_item(drawer, 'Priority approval and question').count(), 0)

    def test_INV_APRI04_320_and_390_phone_widths_have_no_horizontal_overflow(self):
        drawer = self.open_panel()
        for width in (320, 390):
            self.page.set_viewport_size(dict(width=width, height=900))
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1,
                                 f'Unified session navigator overflows at {width}px')
            rect = drawer.bounding_box()
            self.assertIsNotNone(rect)
            self.assertGreaterEqual(rect['x'], -1)
            self.assertLessEqual(rect['x'] + rect['width'], width + 1)
