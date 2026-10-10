"""INV-PART-01/04/05/07 actual Chromium153 + actual application assets/local HTTP."""
from copy import deepcopy
import json
import re
import time
from urllib.parse import urlsplit,parse_qs
import unittest
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from control_browser_helpers import choose_project
import live_sse_blind_support as live
import participation_blind_support as s
import test_control_web_participation_http_broker_blind as h

PROMPT='Synthetic choice?'
SUBMIT=re.compile(r'^(Отправить ответ|Ответить|Подтвердить ответ|Send answer)$',re.I)
PART_PATHS={'/api/participation-overview','/api/session-questions'}


class BrowserBackend(h.ParticipationBackend):
    def session_list(self,project,page):
        value=super().session_list(project,page)
        for row in value['rows']:row['vendor']='codex'
        return value


class ParticipationBrowserBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True);cls.addClassCleanup(cls.browser.close)
        if cls.browser.version!='153.0.8010.12':raise RuntimeError('Chromium153 fixture drift; no skip')
    def setUp(self):
        with patch.object(live,'Backend',BrowserBackend):self.fixture=live.Fixture(transport=True,session_store=True)
        self.addCleanup(self.fixture.stop);self.fixture.login();self.backend=self.fixture.backend
        self.context=self.browser.new_context(viewport=dict(width=390,height=900));self.addCleanup(self.context.close)
        name,value=self.fixture.cookie.split('=',1);self.context.add_cookies([dict(name=name,value=value,url=self.fixture.origin)])
        self.page=self.context.new_page();self.page.set_default_timeout(1800)
        self.requests=[];self.errors=[]
        self.page.on('request',lambda r:self.requests.append((r.method,urlsplit(r.url).path,r.post_data,time.monotonic())))
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
    def tearDown(self):self.assertEqual(self.errors,[])
    def until(self,predicate,message='Expected public participation browser outcome',timeout=2):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate():return
            self.page.wait_for_timeout(20)
        self.assertTrue(predicate(),message)
    def select(self):
        self.page.goto(self.fixture.origin)
        self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        choose_project(self.page,'demo')
        self.page.get_by_role('button',name='LIVE synthetic A',exact=False).click()
        self.until(lambda:self.page.get_by_text('LIVE original synthetic text',exact=True).count()==1,
            'Existing synthetic chat must open before participation assertions')
    def participation_ready(self):
        self.until(lambda:PART_PATHS.issubset({r[1] for r in self.requests}),
            'Visible session must observe common overview and selected questions (semantic RED)')
    def prompt_ready(self):
        self.participation_ready()
        self.until(lambda:self.page.get_by_text(PROMPT,exact=True).is_visible(),
            'Received actionable question missing from actual browser')
    def choice(self):
        radio=self.page.get_by_role('radio',name='Exact option A',exact=False)
        if radio.count():return radio
        return self.page.get_by_role('button',name='Exact option A',exact=True).or_(
            self.page.get_by_label('Exact option A',exact=True))
    def submit(self):
        button=self.page.get_by_role('button',name=SUBMIT)
        self.assertEqual(button.count(),1,'Question needs explicit labelled answer submit')
        return button
    def posts(self):return [r for r in self.requests if r[0]=='POST' and r[1]=='/api/session-question-answer']
    def select_answer(self):
        self.prompt_ready();choice=self.choice();self.assertEqual(choice.count(),1,'Exact option control missing')
        self.assertFalse(choice.is_checked() if choice.get_attribute('type')=='radio' else
            choice.get_attribute('aria-pressed')=='true','Question preselected a recommended/default answer')
        choice.click();self.submit().click()

    def test_INV_PART_01_pool_approval_native_only_no_reply_buttons_or_POST_on_open(self):
        # INV-PART-01
        self.backend.selected=s.questions_dto([])
        self.backend.overview['rows'][0].update(waits=['approval'],questions=[])
        self.select();self.participation_ready()
        self.until(lambda:self.page.get_by_text('Подтвердите в Codex',exact=False).count()>0,
            'Approval read-only fallback absent')
        self.assertEqual(self.page.get_by_role('button',name=re.compile('^(Разрешить|Отклонить|Approve|Deny)$',re.I)).count(),0)
        self.assertEqual([r for r in self.requests if r[0]=='POST'],[])

    def test_INV_PART_04_exact_option_one_submit_honest_sent_no_automatic_retry(self):
        # INV-PART-03 INV-PART-04
        self.page.clock.install();self.select();self.select_answer()
        self.until(lambda:len(self.posts())==1)
        body=json.loads(self.posts()[0][2]);self.assertEqual(set(body),{'project','sid','epoch','interaction_id','action_id','answers'})
        self.assertEqual(body['answers'],s.ANSWER);self.assertEqual(body['interaction_id'],s.HANDLE)
        self.assertRegex(body['action_id'],r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
        self.until(lambda:self.page.get_by_text('Ответ отправлен; применение не подтверждено',exact=False).count()>0)
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100)
        self.assertEqual(len(self.posts()),1)
        self.assertEqual(self.page.get_by_text('Ваш ответ применён',exact=False).count(),0)

    def test_INV_PART_04_closed_unknown_displays_exact_combined_copy_and_no_retry(self):
        # INV-PART-04 INV-PART-05
        self.backend.answer_value=s.action_dto('closed','delivery_unknown')
        self.page.clock.install();self.select();self.select_answer()
        text='Запрос закрыт. Доставка ответа неизвестна; проверьте Codex'
        self.until(lambda:self.page.get_by_text(text,exact=False).count()>0,
            'Closed request lost independent unknown delivery state')
        self.assertEqual(self.page.get_by_text('Ваш ответ применён',exact=False).count(),0)
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100)
        self.assertEqual(len(self.posts()),1)
        self.assertEqual(self.page.get_by_role('button',name=re.compile('Повторить.*ответ|Retry.*answer',re.I)).count(),0)

    def test_INV_PART_07_question_controls_no_overflow_44px_at_all_phone_widths(self):
        # INV-PART-07
        self.select();self.prompt_ready()
        for width in [320,360,390,412]:
            self.page.set_viewport_size(dict(width=width,height=900))
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width+1)
            option=self.choice()
            target=option.locator('xpath=ancestor::label[1]') if option.get_attribute('type')=='radio' else option
            if target.count()==0:target=option
            for control in [target,self.submit()]:
                box=control.bounding_box();self.assertIsNotNone(box)
                self.assertGreaterEqual(box['height'],44);self.assertGreaterEqual(box['width'],44)
                self.assertGreaterEqual(box['x'],-1);self.assertLessEqual(box['x']+box['width'],width+1)

    def test_INV_PART_07_poll_preserves_composer_draft_focus_and_history_anchor(self):
        # INV-PART-07
        self.page.clock.install();self.select();self.prompt_ready()
        composer=self.page.locator('textarea').first;composer.fill('Keep synthetic composer draft');composer.focus()
        history=self.page.get_by_text('LIVE original synthetic text',exact=True)
        history.scroll_into_view_if_needed();before=history.bounding_box()['y']
        self.backend.selected['revision']=2;self.backend.overview['revision']=2
        self.page.clock.fast_forward(6000);self.page.wait_for_timeout(100)
        self.assertEqual(composer.input_value(),'Keep synthetic composer draft')
        self.assertTrue(composer.evaluate('el=>el===document.activeElement'))
        self.assertLessEqual(abs(history.bounding_box()['y']-before),8)

    def test_INV_PART_07_hidden_pagehide_and_logout_stop_observations(self):
        # INV-PART-07
        self.page.clock.install();self.select();self.prompt_ready()
        self.page.wait_for_timeout(80)
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('pagehide'))")
        self.page.wait_for_timeout(60);before=len(self.requests)
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100)
        self.assertEqual(len(self.requests),before,'Hidden/pagehide kept polling backend')
        self.assertEqual(self.posts(),[])
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('pageshow'))")
        self.page.wait_for_timeout(100)
        logout=self.page.get_by_role('button',name=re.compile('Выйти|Logout',re.I));self.assertEqual(logout.count(),1);logout.click()
        self.page.wait_for_timeout(80);before=len(self.requests)
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100)
        self.assertEqual(len(self.requests),before,'Logout kept polling participation')

    def test_INV_PART_05_late_question_response_cannot_cross_selected_chat(self):
        # INV-PART-05 INV-PART-07
        held=[]
        def route(value):
            if parse_qs(urlsplit(value.request.url).query).get('sid')==[s.SID]:held.append(value)
            else:value.continue_()
        self.page.route('**/api/session-questions?*',route)
        self.select();self.until(lambda:len(held)==1,'Selected chat question read missing (semantic RED)')
        self.page.get_by_role('button',name='LIVE synthetic B',exact=False).click()
        old=s.questions_dto();old['questions'][0]['questions'][0]['question']='Forbidden old chat question'
        held[0].fulfill(status=200,json=old);self.page.wait_for_timeout(100)
        self.assertEqual(self.page.get_by_text('Forbidden old chat question',exact=True).count(),0)
        self.assertEqual(self.posts(),[])

    def test_INV_PART_05_new_questions_epoch_invalidates_late_old_overview(self):
        # INV-PART-05 INV-PART-07
        held=[];self.backend.selected['epoch']='c'*32
        self.page.route('**/api/participation-overview',lambda route:held.append(route))
        self.select();self.until(lambda:len(held)==1,'Overview read missing (semantic RED)')
        self.until(lambda:self.page.get_by_text(PROMPT,exact=True).count()==1,'New questions epoch not admitted')
        old=s.overview_dto();old['rows'][0]['label']='Forbidden old source epoch row'
        held[0].fulfill(status=200,json=old);self.page.wait_for_timeout(100)
        self.assertEqual(self.page.get_by_text('Forbidden old source epoch row',exact=False).count(),0)
        self.assertEqual(self.posts(),[])

    def test_INV_PART_05_new_overview_epoch_invalidates_late_old_questions(self):
        # INV-PART-05 INV-PART-07
        held=[];self.backend.overview['epoch']='c'*32
        self.backend.overview['rows'][0]['label']='Current epoch pool marker'
        self.page.route('**/api/session-questions?*',lambda route:held.append(route))
        self.select();self.until(lambda:len(held)==1,'Question read missing (semantic RED)')
        self.until(lambda:self.page.get_by_text('Current epoch pool marker',exact=False).count()>0,
            'New owner overview epoch not admitted')
        old=s.questions_dto();old['questions'][0]['questions'][0]['question']='Forbidden old source question'
        held[0].fulfill(status=200,json=old);self.page.wait_for_timeout(100)
        self.assertEqual(self.page.get_by_text('Forbidden old source question',exact=True).count(),0)
        self.assertEqual(self.posts(),[])

    def test_INV_PART_07_no_answers_handles_or_transcript_in_browser_storage(self):
        # INV-PART-07
        self.select();self.select_answer();self.until(lambda:len(self.posts())==1)
        stored=self.page.evaluate('JSON.stringify({local:{...localStorage},session:{...sessionStorage}})')
        for text in ['Exact option A',s.HANDLE,'Synthetic choice?','LIVE original synthetic text']:
            self.assertNotIn(text,stored)
