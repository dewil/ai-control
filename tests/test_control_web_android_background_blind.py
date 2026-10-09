"""Blind RED: accepted Android lifecycle v2, executable page + real local HTTP/SSE.

No application source inspection; oracle is docs/dev/2026-10-09-spec-android-background.md.
Clock controls page scheduling only, EventSource is the browser's native transport.
"""
import time
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright
from control_browser_helpers import choose_project
import live_sse_blind_support as live
from live_devbus_blind_support import BusBackend


class AndroidBackgroundBrowserBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start(); cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(headless=True); cls.addClassCleanup(cls.browser.close)
        if cls.browser.version != '153.0.8010.12': raise RuntimeError('Chromium153 fixture drift; no skip')

    def setUp(self):
        original = live.Backend; live.Backend = BusBackend
        try: self.fixture = live.Fixture(transport=True, session_store=True)
        finally: live.Backend = original
        self.addCleanup(self.fixture.stop); self.addCleanup(self.fixture.backend.bus_gate.set)
        self.fixture.login(); self.transport = self.fixture.transport
        self.context = self.browser.new_context(viewport={'width':390,'height':844},
            user_agent='Mozilla/5.0 Android SyntheticWebView AiControlLifecycle/2')
        self.addCleanup(self.context.close)
        name, value = self.fixture.cookie.split('=', 1)
        self.context.add_cookies([dict(name=name,value=value,url=self.fixture.origin)])
        self.page = self.context.new_page(); self.page.set_default_timeout(2500)
        self.requests = []; self.page.on('request', lambda r:self.requests.append((r.method,urlsplit(r.url).path,r.post_data)))
        self.page.add_init_script('''window.batteryAuth=[];window.batteryAborts=0;window.batteryCloses=0;
          window.AndroidAuth={requestAuth:()=>batteryAuth.push('auth'),requestLogout:()=>batteryAuth.push('logout')};
          const abort=AbortController.prototype.abort;AbortController.prototype.abort=function(...a){batteryAborts++;return abort.apply(this,a)};
          const close=EventSource.prototype.close;EventSource.prototype.close=function(){batteryCloses++;return close.call(this)};''')
        self.serial = 0

    def until(self, predicate, timeout=3):
        deadline = time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline: self.page.wait_for_timeout(20)
        self.assertTrue(predicate(), 'Expected public lifecycle/transport outcome')

    def api(self): return [r for r in self.requests if r[1].startswith('/api/')]
    def next_serial(self): self.serial += 1; return self.serial

    def suspend(self, serial=None):
        serial = serial or self.next_serial()
        self.assertEqual(self.page.evaluate('typeof aiControlAndroidSuspend'), 'function', 'INV-BATT-01/02: explicit native suspend entry missing')
        value = self.page.evaluate('(serial)=>aiControlAndroidSuspend({protocol:2,serial})', serial)
        self.assertEqual(value,dict(protocol=2,action='suspend',serial=serial,ok=True))
        return value

    def admit(self, serial=None):
        serial = serial or self.next_serial()
        self.assertTrue(self.page.evaluate('(serial)=>aiControlAndroidResume({protocol:2,serial,phase:"admit"})',serial), 'INV-BATT-04: fresh admission rejected')
        return serial

    def activate(self, admission):
        serial = self.next_serial()
        self.assertTrue(self.page.evaluate('p=>aiControlAndroidResume(p)', dict(protocol=2,serial=serial,phase='activate',admissionSerial=admission)))
        return serial

    def open_v2(self):
        self.page.goto(self.fixture.origin)
        self.assertEqual(self.page.evaluate('typeof aiControlAndroidLifecycleProtocol'), 'function', 'INV-BATT-04: protocol2 negotiation missing')
        self.assertEqual(self.page.evaluate('aiControlAndroidLifecycleProtocol()'),2)
        self.suspend(); self.activate(self.admit())

    def select(self):
        self.open_v2()
        self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        choose_project(self.page,'demo');self.page.get_by_role('button',name='LIVE synthetic A',exact=False).click()
        expect(self.page.get_by_text('LIVE original synthetic text',exact=True)).to_have_count(1)
        self.until(lambda:self.transport.streams==1)
        self.page.locator('textarea').fill('Synthetic retained background draft')

    def bypass_events(self):
        self.page.evaluate('''()=>{document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('pageshow'));}''')
        for name in ['Задачи','Сессии','Шина','Обновить переписку']:
            buttons=self.page.get_by_role('button',name=name,exact=True).or_(self.page.get_by_role('tab',name=name,exact=True))
            if buttons.count(): buttons.first.evaluate('e=>e.click()')

    def test_v2_boot_is_suspended_and_noarg_cannot_admit(self):
        # INV-BATT-03 INV-BATT-04: version marker is not an auth capability.
        self.page.goto(self.fixture.origin); self.page.wait_for_timeout(80)
        self.assertEqual(self.api(),[])
        self.assertFalse(self.page.evaluate('aiControlAndroidResume()'), 'v2 accepts legacy no-arg resume and bypasses native admission')
        self.assertEqual(self.api(),[], 'No-arg v2 resume dispatched credentialed API')

    def test_admit_ready_only_one_session_get_no_initial_reads_and_coalesced(self):
        # INV-BATT-04 INV-BATT-05: history may stall >10s without delaying admission.
        self.open_v2(); self.suspend(); start=len(self.api()); serial=self.next_serial()
        self.page.route('**/api/session-history?*',lambda r:None)
        self.page.evaluate('s=>{window.batteryAdmission=aiControlAndroidResume({protocol:2,serial:s,phase:"admit"});}',serial)
        self.until(lambda:len(self.api())>start)
        self.assertTrue(self.page.evaluate('window.batteryAdmission'))
        self.assertTrue(self.page.evaluate('s=>aiControlAndroidResume({protocol:2,serial:s,phase:"admit"})',serial))
        self.page.wait_for_timeout(100)
        self.assertEqual(self.api()[start:],[('GET','/api/session',None)])
        self.bypass_events(); self.assertEqual(self.api()[start:],[('GET','/api/session',None)])
        self.activate(serial)

    def test_visible_suspend_closes_real_SSE_cancels_65s_scheduling_retains_draft(self):
        # INV-BATT-01 INV-BATT-02 INV-BATT-07 INV-BATT-09
        self.select(); self.page.clock.install(); self.suspend()
        self.assertEqual(self.page.evaluate('document.visibilityState'),'visible')
        self.assertGreaterEqual(self.page.evaluate('batteryCloses'),1)
        self.until(lambda:self.transport.closed==1)
        start=len(self.api()); self.page.clock.fast_forward(65000); self.page.wait_for_timeout(80)
        self.assertEqual(len(self.api()),start); self.assertEqual(self.transport.streams,1)
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic retained background draft')
        expect(self.page.locator('#current-model-status')).to_contain_text('неизвестна')

    def test_suspended_visible_events_manual_reads_cannot_dispatch(self):
        # INV-BATT-03: no visibility/page/tab/manual bypass.
        self.select(); self.suspend(); start=len(self.api()); self.bypass_events(); self.page.wait_for_timeout(100)
        self.assertEqual(len(self.api()),start);self.assertEqual(self.transport.streams,1)

    def test_pending_bus_GET_aborted_and_late_reply_cannot_repaint_or_restart(self):
        # INV-BATT-02 INV-BATT-03 INV-BATT-09
        self.open_v2(); self.page.get_by_role('button',name='Шина',exact=True).or_(self.page.get_by_role('tab',name='Шина',exact=True)).click()
        expect(self.page.get_by_text('BUS synthetic result',exact=True)).to_have_count(1)
        self.fixture.backend.bus_gate.clear(); old=len(self.fixture.backend.bus_calls)
        self.until(lambda:len(self.fixture.backend.bus_calls)>old,4)
        before=self.page.evaluate('batteryAborts');self.suspend();self.assertGreater(self.page.evaluate('batteryAborts'),before)
        start=len(self.api());self.fixture.backend.bus_value['tasks'][0]['result']='Forbidden late BUS repaint';self.fixture.backend.bus_gate.set()
        self.page.clock.install();self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100)
        expect(self.page.get_by_text('Forbidden late BUS repaint',exact=True)).to_have_count(0)
        self.assertEqual(len(self.api()),start);self.assertEqual(self.transport.streams,0)

    def test_pending_HTTP_renewal_aborted_and_background_401_cannot_auth(self):
        # INV-BATT-02 INV-BATT-03 INV-BATT-09: unlike POST, observation GET is canceled.
        self.select();held=[];self.page.route('**/api/session-live-snapshot?*',lambda r:held.append(r))
        self.page.clock.install();self.page.clock.fast_forward(5000);self.until(lambda:len(held)==1)
        before=self.page.evaluate('batteryAborts');self.suspend();self.assertGreater(self.page.evaluate('batteryAborts'),before)
        start=len(self.api());held[0].fulfill(status=401,json={'error':'unauthorized'})
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate('batteryAuth'),[]);self.assertEqual(len(self.api()),start)
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic retained background draft')

    def test_admission_late_success_after_new_suspend_never_activates(self):
        # INV-BATT-03 INV-BATT-04
        self.select();self.suspend();held=[]
        self.page.route('**/api/session',lambda r:held.append(r));serial=self.next_serial()
        self.page.evaluate('s=>{window.oldAdmit=aiControlAndroidResume({protocol:2,serial:s,phase:"admit"});}',serial)
        self.until(lambda:len(held)==1);self.suspend();start=len(self.api())
        held[0].fulfill(status=200,json={'csrf':'synthetic-stale','principal':'owner'})
        self.assertFalse(self.page.evaluate('window.oldAdmit'))
        self.assertFalse(self.page.evaluate('p=>aiControlAndroidResume(p)',dict(protocol=2,serial=self.next_serial(),phase='activate',admissionSerial=serial)))
        self.page.wait_for_timeout(100);self.assertEqual(len(self.api()),start)
        self.assertEqual(self.page.evaluate('batteryAuth'),[])

    def test_serial_idempotence_old_suspend_and_wrong_activation_cannot_change_current(self):
        # INV-BATT-04 INV-BATT-06 INV-BATT-09
        self.select();suspend=self.next_serial();ack=self.suspend(suspend);self.assertEqual(self.suspend(suspend),ack)
        admission=self.admit();self.assertFalse(self.page.evaluate('p=>aiControlAndroidResume(p)',dict(protocol=2,serial=self.next_serial(),phase='activate',admissionSerial=admission-1)))
        self.activate(admission);self.until(lambda:self.transport.streams==2)
        self.page.evaluate('s=>aiControlAndroidSuspend({protocol:2,serial:s})',suspend);self.page.wait_for_timeout(80)
        self.assertEqual(self.transport.closed,1,'Old suspend closed current active stream')

    def test_ten_resume_cycles_no_duplicate_stream_or_draft_loss(self):
        # INV-BATT-06 INV-BATT-07 INV-BATT-09
        self.select()
        for index in range(10):
            self.suspend();self.until(lambda:self.transport.closed==index+1)
            admission=self.admit();serial=self.activate(admission)
            self.assertTrue(self.page.evaluate('p=>aiControlAndroidResume(p)',dict(protocol=2,serial=serial,phase='activate',admissionSerial=admission)))
            self.until(lambda:self.transport.streams==index+2)
            self.assertEqual(self.transport.streams-self.transport.closed,1)
            self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic retained background draft')

    def test_ready_mutation_rejected_before_UUID_receipt_unknown_and_not_queued(self):
        # INV-BATT-07 INV-BATT-08: bypass disabled button using DOM click; no product internals.
        self.select();self.suspend();admission=self.admit();start=len(self.api())
        self.page.evaluate('''()=>{window.batteryUUIDs=0;const random=crypto.randomUUID.bind(crypto);crypto.randomUUID=()=>{batteryUUIDs++;return random()}}''')
        self.page.get_by_role('button',name='Отправить',exact=True).evaluate('e=>{e.disabled=false;e.click()}')
        self.page.wait_for_timeout(80)
        self.assertEqual(self.page.evaluate('batteryUUIDs'),0)
        self.assertEqual([r for r in self.api()[start:] if r[0]=='POST'],[])
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic retained background draft')
        self.activate(admission);self.page.wait_for_timeout(100)
        self.assertEqual([r for r in self.api()[start:] if r[0]=='POST'],[],'Refused mutation replayed on activation')

    def test_inflight_send_not_aborted_replayed_or_unrelated_draft_erased(self):
        # INV-BATT-07 INV-BATT-08
        self.select();held=[];self.page.route('**/api/session-send',lambda r:held.append(r))
        self.page.get_by_role('button',name='Отправить',exact=True).click();self.until(lambda:len(held)==1)
        payload=held[0].request.post_data_json;self.page.locator('textarea').fill('Unrelated new draft')
        failures=[];self.page.on('requestfailed',lambda r:failures.append(urlsplit(r.url).path))
        self.suspend();self.page.wait_for_timeout(100)
        self.assertNotIn('/api/session-send',failures,'Suspend aborted mutation IO')
        held[0].fulfill(status=200,json={'status':'delivery_unknown','message_id':payload['message_id'],'turn_id':None})
        self.page.wait_for_timeout(100);self.activate(self.admit());self.page.wait_for_timeout(100)
        self.assertEqual(self.page.locator('textarea').input_value(),'Unrelated new draft')
        self.assertEqual(len([r for r in self.api() if r[1]=='/api/session-send']),1)

    def late_mutation_auth(self,status):
        # INV-BATT-03 INV-BATT-08: stale POST response must reconcile without native auth.
        self.select();held=[];self.page.route('**/api/session-send',lambda r:held.append(r))
        self.page.get_by_role('button',name='Отправить',exact=True).click();self.until(lambda:len(held)==1)
        self.page.locator('textarea').fill('Synthetic unrelated pending draft');self.suspend();start=len(self.api())
        held[0].fulfill(status=status,json={'error':'unauthorized' if status==401 else 'forbidden'})
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate('batteryAuth'),[])
        self.assertEqual(len(self.api()),start)
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic unrelated pending draft')

    def test_late_send401_in_background_cannot_request_native_auth(self):self.late_mutation_auth(401)
    def test_late_send403_in_background_cannot_request_native_auth(self):self.late_mutation_auth(403)

    def test_legacy_no_marker_keeps_existing_noarg_resume(self):
        # INV-BATT-10: old APK/new web remains compatible, separate context UA.
        context=self.browser.new_context();self.addCleanup(context.close);context.add_cookies(self.context.cookies())
        page=context.new_page();page.add_init_script('window.AndroidAuth={requestAuth:()=>{},requestLogout:()=>{}}');page.goto(self.fixture.origin)
        self.assertTrue(page.evaluate('aiControlAndroidResume()'))
        expect(page.get_by_role('button',name='Сессии',exact=True).or_(page.get_by_role('tab',name='Сессии',exact=True))).to_be_visible()
