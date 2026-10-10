"""Independent queue UI RED: actual JS, local HTTP and native EventSource."""
from copy import deepcopy
import re
import time
from urllib.parse import urlsplit,parse_qs
import unittest
from playwright.sync_api import expect,sync_playwright
from control_browser_helpers import choose_project
import live_sse_blind_support as live
import native_queue_blind_support as q

CANCEL=re.compile(r'Отменить|Удалить.*очеред|Cancel',re.I)
SEND=re.compile(r'^(Отправить|В очередь|Поставить в очередь)$',re.I)


class BrowserQueueBackend(live.Backend):
    def __init__(self):
        super().__init__();self.queue_rows={live.SID:[],live.OTHER:[]};self.supported=True
        self.queue_calls=[];self.enqueue_calls=[];self.cancel_calls=[];self.direct_calls=[]
        self.cancel_state='cancelled'
    def session_queue(self,project,sid):
        self.queue_calls.append((project,sid));value=q.queue_dto(self.queue_rows.get(sid,[]))
        if not self.supported:value.update(supported=False,reason='unsupported_queue',send_now_reason='unsupported_queue',rows=[])
        return value
    def session_enqueue(self,project,sid,mid,text,selection=None):
        self.enqueue_calls.append((project,sid,mid,text,selection))
        self.queue_rows[sid].append(q.public_row('queue-'+mid,mid,text))
        return dict(status='queued',message_id=mid,queued_submission_id='queue-'+mid)
    def session_queue_cancel(self,project,sid,qid,action):
        self.cancel_calls.append((project,sid,qid,action))
        if self.cancel_state=='cancelled':self.queue_rows[sid]=[row for row in self.queue_rows[sid] if row['queued_submission_id']!=qid]
        return dict(status=self.cancel_state,message_id=action,queued_submission_id=qid)
    def session_send(self,project,sid,mid,text,selection=None):
        self.direct_calls.append((project,sid,mid,text,selection));return dict(status='accepted',message_id=mid,turn_id=live.TURN)
    def session_send_status(self,project,sid,mid):
        accepted=any(item.get('client_id')==mid for turn in self.value['turns'] for item in turn['items'])
        return dict(status='accepted' if accepted else 'delivery_unknown',message_id=mid,turn_id=live.TURN if accepted else None)
    def session_history(self,project,sid,cursor):
        return deepcopy(self.value if sid==live.SID else live.history('Queue browser B history'))


class NativeQueueBrowserBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True);cls.addClassCleanup(cls.browser.close)
        if cls.browser.version!='153.0.8010.12':raise RuntimeError('Chromium153 fixture drift; no skip')
    def setUp(self):
        original=live.Backend;live.Backend=BrowserQueueBackend
        try:self.fixture=live.Fixture(transport=True)
        finally:live.Backend=original
        self.addCleanup(self.fixture.stop);self.fixture.login();self.backend=self.fixture.backend
        self.context=self.browser.new_context(viewport=dict(width=390,height=900));self.addCleanup(self.context.close)
        name,value=self.fixture.cookie.split('=',1);self.context.add_cookies([dict(name=name,value=value,url=self.fixture.origin)])
        self.page=self.context.new_page();self.page.set_default_timeout(2500)
        self.requests=[];self.errors=[]
        self.page.on('request',lambda r:self.requests.append((r.method,urlsplit(r.url).path,r.post_data)))
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
    def tearDown(self):self.assertEqual(self.errors,[])
    def until(self,predicate,timeout=3):
        until=time.monotonic()+timeout
        while not predicate() and time.monotonic()<until:self.page.wait_for_timeout(20)
        self.assertTrue(predicate(),'Expected public queue/transport outcome')
    def select(self):
        self.page.goto(self.fixture.origin)
        self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        choose_project(self.page,'demo');self.page.get_by_role('button',name='LIVE synthetic A',exact=False).click()
        expect(self.page.get_by_text('LIVE original synthetic text',exact=True)).to_have_count(1)
        self.until(lambda:self.fixture.transport.streams>=1)
        self.fixture.transport.emit(live.snapshot(value=live.history('Queue browser streamed ready A')))
        expect(self.page.get_by_text('Queue browser streamed ready A',exact=True)).to_have_count(1)
    def send_button(self):return self.page.get_by_role('button',name=SEND)
    def hold_send(self):
        held=[];self.page.route(re.compile(r'/api/session-(?:send|queue)$'),lambda route:held.append(route))
        return held
    def send(self,text=q.TEXT):self.page.locator('textarea').fill(text);self.send_button().click()
    def queue_request(self,held):
        self.until(lambda:len(held)==1)
        self.assertEqual(urlsplit(held[0].request.url).path,'/api/session-queue','Supported composer must default to native enqueue, not implicit direct steering')
        return held[0].request.post_data_json
    def user_history(self,mid,text):
        value=live.history('Authoritative queued history proof')
        value['turns'][0]['items'].append(dict(id='native-user-'+mid,role='user',text=text,client_id=mid,truncated=False,timestamp=1770000000,time_precision='item'))
        self.backend.value=deepcopy(value);self.fixture.transport.emit(live.snapshot(2,value=value))
        return value
    def direct_mode(self):
        select=self.page.get_by_role('combobox',name=re.compile('Режим.*отправ|Отправка',re.I))
        if select.count():
            labels=select.locator('option').all_text_contents();label=next((x for x in labels if re.search('Сразу|Немедленно|Прям|Direct',x,re.I)),None)
            self.assertIsNotNone(label,'Explicit direct-send option missing');select.select_option(label=label);return
        direct=self.page.get_by_role('radio',name=re.compile('Сразу|Немедленно|Прям|Direct',re.I)).or_(self.page.get_by_role('button',name=re.compile(r'^(Сразу|Немедленно|Прямая отправка|Отправить напрямую|Direct)$',re.I)))
        self.assertEqual(direct.count(),1,'Supported queue must expose explicit labelled direct-send mode');direct.click()

    def test_default_queue_optimistic_bubble_and_draft_clears_only_after_ACK(self):
        # INV-SQUEUE-02 INV-SQUEUE-07 INV-SQUEUE-08
        held=self.hold_send();self.select();self.send();payload=self.queue_request(held)
        expect(self.page.get_by_text(q.TEXT,exact=True)).to_have_count(1)
        self.assertEqual(self.page.locator('textarea').input_value(),q.TEXT,'Pending enqueue cleared draft before durable ACK')
        row=q.public_row('native-ui-row',payload['message_id']);self.backend.queue_rows[live.SID]=[row]
        held[0].fulfill(status=200,json=dict(status='queued',message_id=payload['message_id'],queued_submission_id='native-ui-row'))
        expect(self.page.locator('textarea')).to_have_value('')
        expect(self.page.get_by_text(q.TEXT,exact=True)).to_have_count(1)
        expect(self.page.get_by_text(re.compile('В очереди|queued',re.I)).first).to_be_visible()

    def test_503_unknown_retains_draft_UUID_and_never_auto_posts(self):
        # INV-SQUEUE-02 INV-SQUEUE-08: semantic unknown503 must not be generic retry.
        self.page.clock.install();held=self.hold_send();self.select();self.send();payload=self.queue_request(held)
        held[0].fulfill(status=503,json=dict(status='delivery_unknown',message_id=payload['message_id'],queued_submission_id=None))
        self.page.wait_for_timeout(80);self.page.clock.fast_forward(65000);self.page.wait_for_timeout(80)
        self.assertEqual(self.page.locator('textarea').input_value(),q.TEXT)
        self.assertEqual(len([r for r in self.requests if r[0]=='POST']),1,'Unknown enqueue replayed or minted a new UUID')
        expect(self.page.get_by_text(q.TEXT,exact=True)).to_have_count(1)

    def test_native_Mac_rows_restore_after_reload_with_mobile_queue_geometry(self):
        # INV-SQUEUE-04 INV-SQUEUE-08: this row never had a Control local receipt.
        text='Mac-only durable native queue row';self.backend.queue_rows[live.SID]=[q.public_row('mac-native-id','mac-client-id',text)]
        self.select();expect(self.page.get_by_text(text,exact=True)).to_have_count(1)
        self.select();expect(self.page.get_by_text(text,exact=True)).to_have_count(1)
        for width in [320,360]:
            self.page.set_viewport_size(dict(width=width,height=900));box=self.page.get_by_text(text,exact=True).bounding_box()
            self.assertIsNotNone(box);self.assertGreaterEqual(box['x'],-1);self.assertLessEqual(box['x']+box['width'],width+1)
        self.assertEqual([r for r in self.requests if r[0]=='POST'],[],'Reload dispatched a pending row')

    def test_cancel_Mac_false_never_claims_cancelled_or_loses_pending_item(self):
        # INV-SQUEUE-05 INV-SQUEUE-08
        text='Mac cancel-race row';self.backend.queue_rows[live.SID]=[q.public_row('mac-cancel-id','mac-action-client',text)]
        self.backend.cancel_state='changed';self.select();expect(self.page.get_by_text(text,exact=True)).to_have_count(1)
        container=self.page.get_by_text(text,exact=True).locator('xpath=ancestor::*[.//button][1]')
        button=container.get_by_role('button',name=CANCEL);self.assertEqual(button.count(),1,'Native row needs its own compact cancel action')
        button.click();self.until(lambda:len(self.backend.cancel_calls)==1)
        self.assertEqual(self.backend.cancel_calls[0][2],'mac-cancel-id')
        self.assertRegex(self.backend.cancel_calls[0][3],r'^[0-9a-f-]{36}$')
        expect(self.page.get_by_text(text,exact=True)).to_have_count(1)
        expect(self.page.get_by_text('Отменено',exact=True)).to_have_count(0)

    def test_history_proof_before_late_queue_ACK_never_duplicates_or_regresses(self):
        # INV-SQUEUE-08: accepted history > exact queue match > queued ACK.
        held=self.hold_send();self.select();self.send();payload=self.queue_request(held)
        self.user_history(payload['message_id'],q.TEXT)
        expect(self.page.get_by_text('Authoritative queued history proof',exact=True)).to_have_count(1)
        expect(self.page.get_by_text(q.TEXT,exact=True)).to_have_count(1)
        held[0].fulfill(status=200,json=dict(status='queued',message_id=payload['message_id'],queued_submission_id='already-dispatched'))
        self.page.wait_for_timeout(100)
        expect(self.page.get_by_text(q.TEXT,exact=True)).to_have_count(1)
        expect(self.page.get_by_role('button',name=CANCEL)).to_have_count(0)

    def test_late_queue_GET_cannot_cross_selected_session(self):
        # INV-SQUEUE-01 INV-SQUEUE-08
        held=[]
        def route_queue(route):
            if parse_qs(urlsplit(route.request.url).query).get('sid')==[live.SID]:held.append(route)
            else:route.continue_()
        self.page.route('**/api/session-queue?*',route_queue);self.select();self.until(lambda:len(held)==1)
        self.page.get_by_role('button',name='LIVE synthetic B',exact=False).click()
        expect(self.page.get_by_text('Queue browser B history',exact=True)).to_have_count(1)
        held[0].fulfill(status=200,json=q.queue_dto([q.public_row(text='Forbidden A queue repaint')]))
        self.page.wait_for_timeout(100);expect(self.page.get_by_text('Forbidden A queue repaint',exact=True)).to_have_count(0)

    def test_explicit_direct_mode_preserves_model_effort_override(self):
        # INV-SQUEUE-07: direct is an explicit choice, never a silent queue downgrade.
        held=self.hold_send();self.select();self.direct_mode()
        model=self.page.get_by_role('combobox',name='Модель',exact=True,include_hidden=True)
        for summary in model.locator('xpath=ancestor::details[not(@open)]/summary').all():summary.click()
        model.select_option(label='Model Alpha')
        self.page.get_by_role('combobox',name='Уровень размышления',exact=True).select_option(label='high')
        self.send();self.until(lambda:len(held)==1)
        self.assertEqual(urlsplit(held[0].request.url).path,'/api/session-send')
        self.assertEqual(held[0].request.post_data_json['selection'],dict(catalog_id='a'*64,model_id='model-alpha',effort='high'))

    def test_unsupported_queue_displays_reason_and_keeps_direct_send(self):
        # INV-SQUEUE-07: capability failure must be explicit, not false queued.
        self.backend.supported=False;held=self.hold_send();self.select()
        expect(self.page.get_by_text(re.compile('Очеред.*не поддерж|Очеред.*недоступ|Queue.*unavailable',re.I)).first).to_be_visible()
        self.send();self.until(lambda:len(held)==1)
        self.assertEqual(urlsplit(held[0].request.url).path,'/api/session-send')

    def test_background_stops_observers_native_progress_reconciles_on_return(self):
        # INV-SQUEUE-03 INV-SQUEUE-08: native persistence is independent of phone.
        text='Native queued while phone closes';self.backend.queue_rows[live.SID]=[q.public_row('background-row',q.MID,text)]
        self.select();expect(self.page.get_by_text(text,exact=True)).to_have_count(1)
        self.page.clock.install();self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
        self.until(lambda:self.fixture.transport.closed>=1);before=len(self.requests)
        self.backend.queue_rows[live.SID]=[];value=self.user_history(q.MID,text)
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(80)
        self.assertEqual(len(self.requests),before,'Phone background started new queue/LIVE/API observations')
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('pageshow'))")
        self.until(lambda:self.fixture.transport.streams-self.fixture.transport.closed==1)
        expect(self.page.get_by_text(text,exact=True)).to_have_count(1)
        self.assertEqual(self.backend.enqueue_calls,[]);self.assertEqual(self.backend.direct_calls,[])
