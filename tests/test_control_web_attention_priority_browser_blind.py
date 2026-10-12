"""INV-APRI01..04 public browser contract against synthetic local HTTP only."""
from copy import deepcopy
import re
import time
import unittest
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from control_browser_helpers import choose_project
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

    def open_panel(self):
        self.page.goto(self.fixture.origin)
        self.page.get_by_role('button', name='Сессии', exact=True).or_(
            self.page.get_by_role('tab', name='Сессии', exact=True)).click()
        choose_project(self.page, 'demo')
        self.until(lambda:any(call[0] == 'overview' for call in self.backend.part_calls),
                   'Public overview request missing')
        self.until(lambda:self.page.locator('#participation-list .participation-row').count() ==
                   len(self.backend.overview['rows']), 'All synthetic overview rows must render')

    def test_INV_APRI01_priority_groups_question_override_unique_rows_and_source_order(self):
        self.open_panel()
        headings = self.page.locator('#participation-list h3').all_text_contents()
        with self.subTest(contract='priority group headings and order'):
            self.assertEqual(headings, ['Требуют внимания', 'Ответы готовы', 'Сейчас работают',
                                        'Активны по Codex'])
        labels = self.page.locator('#participation-list .participation-row strong').all_text_contents()
        with self.subTest(contract='each row once and source order within groups'):
            self.assertEqual(labels, ['Priority approval and question',
                                      'Nonblocking question in active work', 'Ready answer',
                                      'Confirmed work', 'Active Codex work'])
            self.assertEqual(len(labels), len(set(labels)), 'Each overview session must render exactly once')
        second = self.page.locator('#participation-list .participation-row').filter(
            has_text='Nonblocking question in active work')
        with self.subTest(contract='nonblocking open question overrides working classification'):
            self.assertEqual(second.count(), 1)
            self.assertEqual(second.evaluate("""el=>{let n=el.previousElementSibling;
                while(n&&n.tagName!=='H3')n=n.previousElementSibling;return n?.textContent}"""),
                'Требуют внимания')

    def test_INV_APRI02_distinct_badges_native_only_approval_and_bound_question_result_targets(self):
        self.open_panel()
        approval = self.page.locator('#participation-list .participation-row').filter(
            has_text='Priority approval and question')
        badge_text = approval.locator('p').inner_text()
        with self.subTest(contract='separate text badges'):
            self.assertIn('Вопрос', badge_text)
            self.assertIn('Разрешение в Codex', badge_text)
            self.assertIn('Ответ готов', badge_text)
        with self.subTest(contract='native approval remains visible-only'):
            self.assertEqual(approval.get_by_role('button',
                name=re.compile('Разрешить|Отклонить|Approve|Deny', re.I)).count(), 0)
            self.assertEqual([request for request in self.requests if request[0] == 'POST' and
                              '/api/session-question-answer' in request[1]], [])

    def test_INV_APRI02_question_and_ready_buttons_keep_exact_session_and_item_targets(self):
        self.open_panel()
        approval = self.page.locator('#participation-list .participation-row').filter(
            has_text='Priority approval and question')
        approval.get_by_role('button', name='Открыть вопрос', exact=True).click()
        self.until(lambda:self.page.get_by_text('Synthetic choice?', exact=True).count() == 1,
                   'Question action must open the exact interaction')
        self.assertTrue(any(call[:3] == ('questions', 'demo', live.SID)
                            for call in self.backend.part_calls), 'Question navigation changed its bound session')
        approval.get_by_role('button', name='Открыть результат', exact=True).click()
        self.until(lambda:self.page.get_by_text('Synthetic ready answer target', exact=True).count() == 1,
                   'Ready-result action must open its exact final item')
        self.assertIn(('demo', live.SID, None), self.backend.history_calls,
                      'Result navigation changed the session bound to its turn/item target')
        self.assertFalse(any(request[0] == 'POST' and '/api/session-question-answer' in request[1]
                             for request in self.requests))

    def test_INV_APRI03_priority_counters_partial_stale_disclosure_and_safe_reason_copy(self):
        self.backend.overview['health'] = 'stale'
        self.backend.overview['rows'][0]['freshness'] = dict(state='stale', observed_at=1799990000)
        self.backend.overview['coverage'] = dict(partial=True, reasons=['deadline', 'native_callbacks_partial'])
        self.backend.overview['generated_at'] = 1799990000
        self.open_panel()
        panel = self.page.locator('#participation-overview')
        summary = panel.locator('summary').inner_text()
        status = self.page.locator('#participation-status')
        with self.subTest(contract='observed mutually exclusive counters'):
            self.assertRegex(summary, r'Наблюдается:.*Сессии: требуется внимание\s*2\s*·\s*работают\s*2\s*·\s*ответы\s*1')
        with self.subTest(contract='stale and partial are explicit with safe reason labels'):
            expect(status).to_be_visible()
            self.assertIn('Полнота не подтверждена', status.inner_text())
            self.assertRegex(status.inner_text(), r'(?i)(устар|stale)')
            self.assertNotIn('native_callbacks_partial', status.inner_text())
            self.assertNotIn('deadline', status.inner_text())
            self.assertIn('устар', self.page.locator('#participation-list').inner_text().lower())

    def test_INV_APRI04_empty_fresh_full_is_explicit_and_disclosure_survives_refresh(self):
        self.backend.overview['rows'] = []
        self.backend.overview['coverage'] = dict(partial=False, reasons=[])
        self.backend.overview['health'] = 'fresh'
        self.open_panel()
        panel = self.page.locator('#participation-overview')
        self.assertTrue(panel.evaluate('el=>el.open'), 'Panel defaults to expanded')
        expect(self.page.get_by_text('Нет сессий для отображения', exact=True)).to_have_count(1)

    def test_INV_APRI03_partial_empty_never_claims_no_sessions_or_zero_waiting(self):
        self.backend.overview['rows'] = []
        self.backend.overview['coverage'] = dict(partial=True, reasons=['source_unavailable'])
        self.backend.overview['health'] = 'unavailable'
        self.open_panel()
        text = self.page.locator('#participation-overview').inner_text()
        with self.subTest(contract='partial empty is not a confirmed empty result'):
            self.assertIn('Список сессий не подтверждён', text)
            self.assertRegex(text, r'Наблюдается:.*Сессии: требуется внимание\s*0\s*·\s*работают\s*0\s*·\s*ответы\s*0')
            self.assertIn('Полнота не подтверждена', text)

    def test_INV_APRI04_manual_collapse_survives_foreground_overview_refresh(self):
        self.page.clock.install()
        self.open_panel()
        panel = self.page.locator('#participation-overview')
        self.assertTrue(panel.evaluate('el=>el.open'), 'Panel defaults to expanded')
        panel.evaluate('el=>el.open=false')
        self.backend.overview['rows'][0]['label'] = 'Refreshed visible-source row'
        self.backend.overview['revision'] += 1
        self.backend.overview['generated_at'] += 1
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('Refreshed visible-source row', exact=True).count() == 1,
                   'Foreground refresh did not render the changed overview row')
        self.assertFalse(panel.evaluate('el=>el.open'), 'Manual disclosure state must survive refresh')
        self.assertFalse(self.page.get_by_text('Refreshed visible-source row', exact=True).is_visible(),
                         'A refreshed row should remain under the collapsed disclosure')

    def test_INV_APRI04_320_and_390_phone_widths_have_no_horizontal_overflow(self):
        self.open_panel()
        for width in (320, 390):
            self.page.set_viewport_size(dict(width=width, height=900))
            self.page.wait_for_timeout(50)
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1,
                                 f'Priority panel overflows at {width}px')
            rect = self.page.locator('#participation-overview').bounding_box()
            self.assertIsNotNone(rect)
            self.assertGreaterEqual(rect['x'], -1)
            self.assertLessEqual(rect['x'] + rect['width'], width + 1)
