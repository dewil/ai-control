"""Native EventSource public transport/merge tests, actual application page."""
import re
import time
import unittest
from playwright.sync_api import expect, sync_playwright
from control_browser_helpers import choose_project
import live_sse_blind_support as s

UNKNOWN='Сессия: модель неизвестна · Размышление: уровень неизвестен'

class LiveBrowserBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright=sync_playwright().start();cls.addClassCleanup(cls.playwright.stop)
        cls.browser=cls.playwright.chromium.launch(headless=True);cls.addClassCleanup(cls.browser.close)
        if cls.browser.version!='153.0.8010.12':raise RuntimeError('Mandatory Chromium153 drift: explicit rebaseline required, no SKIP')

    def setUp(self):
        self.fixture=s.Fixture(transport=True);self.addCleanup(self.fixture.stop);self.fixture.login()
        self.transport=self.fixture.transport
        self.context=self.browser.new_context(viewport={'width':390,'height':900});self.addCleanup(self.context.close)
        name,value=self.fixture.cookie.split('=',1)
        self.context.add_cookies([{'name':name,'value':value,'url':self.fixture.origin}])
        self.page=self.context.new_page();self.errors=[];self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.set_default_timeout(3000)

    def tearDown(self):self.assertEqual(self.errors,[])

    def until(self,predicate,timeout=3,message='Expected public transport state'):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:self.page.wait_for_timeout(20)
        self.assertTrue(predicate(),message)

    def requests(self,path):return [row for row in self.transport.requests if row[0]==path]

    def select(self):
        self.page.goto(self.fixture.origin)
        if self.page.evaluate('typeof window.AndroidAuth!=="undefined"'):
            self.page.evaluate('window.aiControlAndroidResume()')
        self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        choose_project(self.page,'demo');self.page.get_by_role('button',name='LIVE synthetic A',exact=False).click()
        self.page.get_by_text('LIVE original synthetic text',exact=True).wait_for()
        self.until(lambda:len(self.requests('/api/session-events'))==1,message='Actual application must create native EventSource for selected scope')
        self.transport.emit(s.snapshot());self.page.wait_for_timeout(50)

    def caption_known(self,model='producer-A'):
        expect(self.page.locator('#current-model-status')).to_contain_text(model)

    def test_native_initial_fresh_stream_updates_same_id_without_duplicate(self):
        self.select();self.caption_known()
        changed=s.history('LIVE streamed replacement');self.transport.emit(s.snapshot(2,value=changed))
        expect(self.page.get_by_text('LIVE streamed replacement',exact=True)).to_have_count(1)
        expect(self.page.get_by_text('LIVE original synthetic text',exact=True)).to_have_count(0)
        self.transport.emit(s.snapshot(2,value=changed));self.page.wait_for_timeout(100)
        expect(self.page.get_by_text('LIVE streamed replacement',exact=True)).to_have_count(1)
        self.assertEqual(len(self.requests('/api/session-events')),1)

    def test_HTTP_r12_before_SSE_r12_and_lower_settings_floor_discard(self):
        self.select();self.caption_known()
        fresh=s.history('LIVE r12 changed history')
        self.transport.json_value=s.snapshot(12,observation=12,value=fresh)
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>=1,timeout=7,message='Active SSE must renew via documented JSON endpoint')
        self.page.wait_for_timeout(100)
        expect(self.page.get_by_text('LIVE r12 changed history',exact=True)).to_have_count(0)
        self.transport.emit(s.snapshot(11,value=s.history('LIVE stale r11','stale-item','producer-B')))
        self.page.wait_for_timeout(100);self.caption_known('producer-A')
        expect(self.page.get_by_text('LIVE stale r11',exact=True)).to_have_count(0)
        self.transport.emit(s.snapshot(12,observation=12,value=fresh))
        expect(self.page.get_by_text('LIVE r12 changed history',exact=True)).to_have_count(1)
        self.caption_known('producer-A')

    def test_different_new_HTTP_settings_no_false_fresh_until_matching_SSE(self):
        self.select();self.caption_known()
        fresh=s.history(model='producer-B');self.transport.json_value=s.snapshot(12,value=fresh)
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>=1,timeout=7)
        expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)
        self.transport.emit(s.snapshot(12,value=fresh));self.page.wait_for_timeout(100)
        expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)
        self.transport.json_value=s.snapshot(13,value=fresh)
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>=2,timeout=7)
        self.caption_known('producer-B')

    def test_SSE_settings_heartbeat_never_renew_lease_and_renewal503_keeps_old_deadline(self):
        self.select();self.caption_known();start=time.monotonic()
        self.transport.json_status=503
        self.transport.emit(s.snapshot(2,observation=2))
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>=1,timeout=7)
        self.caption_known()
        self.transport.emit(s.snapshot(3,observation=3));self.caption_known()
        remaining=max(0,15.1-(time.monotonic()-start));self.page.wait_for_timeout(remaining*1000)
        expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)

    def test_unavailable_plus_onerror_latches_single_probe_no_extra_auth_get(self):
        self.select();before=len(self.requests('/api/session'))
        self.transport.json_status=503
        self.transport.emit(dict(schema=1,project='demo',sid=s.SID,error='unavailable'),event='unavailable')
        self.transport.close=True
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))==1)
        self.page.wait_for_timeout(250)
        self.assertEqual(len(self.requests('/api/session-live-snapshot')),1)
        self.assertEqual(len(self.requests('/api/session')),before)
        self.until(lambda:self.transport.closed>=1)
        self.assertEqual(self.page.evaluate('typeof EventSource'),'function')

    def test_Android403_bridge_once_preserves_draft_and_stops_renewals(self):
        self.page.add_init_script('window.liveAndroidCalls=[];window.AndroidAuth={requestAuth:(...args)=>window.liveAndroidCalls.push(args),requestLogout:()=>{}};')
        self.select();self.page.locator('textarea').fill('Synthetic LIVE unsent draft')
        initial_calls=self.page.evaluate('window.liveAndroidCalls.length')
        self.transport.json_status=403;self.transport.close=True
        self.until(lambda:self.page.evaluate('window.liveAndroidCalls.length')==initial_calls+1)
        self.assertEqual(self.page.evaluate('window.liveAndroidCalls')[initial_calls:],[[]])
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic LIVE unsent draft')
        calls=len(self.requests('/api/session-live-snapshot'));self.page.wait_for_timeout(1200)
        self.assertEqual(len(self.requests('/api/session-live-snapshot')),calls)
        self.assertEqual(self.page.evaluate('window.liveAndroidCalls')[initial_calls:],[[]])

    def test_three_failure_fallback_and_visible60s_SSE_attempt_no_overlap(self):
        self.select();self.transport.close=True
        self.until(lambda:len(self.requests('/api/session-events'))>=3,timeout=14)
        streams=len(self.requests('/api/session-events'))
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>=4,timeout=8)
        fallback_start=self.requests('/api/session-live-snapshot')[2][1]
        self.page.wait_for_timeout(50000)
        self.assertEqual(len(self.requests('/api/session-events')),streams,'No periodic SSE attempt before60s fallback boundary')
        self.until(lambda:len(self.requests('/api/session-events'))>streams,timeout=12)
        self.assertGreaterEqual(self.requests('/api/session-events')[-1][1]-fallback_start,59.5)
        rows=self.requests('/api/session-live-snapshot')
        self.assertTrue(all(b[1]-a[1]>.1 for a,b in zip(rows,rows[1:])), 'No concurrent duplicated probe/fallback request')

    def test_epoch_change_preserves_draft_and_gap_stays_sticky(self):
        self.select();self.page.locator('textarea').fill('Synthetic epoch draft')
        self.transport.emit(s.snapshot(2,value=s.history('LIVE no overlap','foreign-item')))
        expect(self.page.get_by_text('Показано последнее окно. Возможен пропуск сообщений',exact=False)).to_be_visible()
        self.transport.emit(s.snapshot(3,value=s.history('LIVE overlap now','foreign-item')))
        expect(self.page.get_by_text('Показано последнее окно. Возможен пропуск сообщений',exact=False)).to_be_visible()
        self.transport.emit(s.snapshot(1,epoch='b'*32,value=s.history('LIVE new epoch','new-epoch-item')))
        expect(self.page.get_by_text('LIVE new epoch',exact=True)).to_have_count(1)
        expect(self.page.get_by_text('LIVE overlap now',exact=True)).to_have_count(0)
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic epoch draft')
        expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)

    def test_age14999_is_not_received_plus15s_freshness(self):
        self.fixture.backend.value['session_settings']=s.settings(age=14999)
        self.select();self.page.wait_for_timeout(50)
        expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)

    def test_wallclock_forward_sleep_without_visibility_invalidates_on_render(self):
        now=int(time.time()*1000);self.page.clock.install(time=now)
        self.select();self.caption_known()
        self.page.clock.set_system_time(now+20000)
        self.transport.emit(s.snapshot(2,value=s.history('Synthetic wake render without visibility event')))
        expect(self.page.get_by_text('Synthetic wake render without visibility event',exact=True)).to_have_count(1)
        expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)

    def test_wallclock_rollback_invalidates_existing_lease_on_render(self):
        now=int(time.time()*1000);self.page.clock.install(time=now)
        self.select();self.caption_known();self.page.clock.set_system_time(now-10000)
        self.transport.emit(s.snapshot(2,value=s.history('Synthetic rollback render')))
        expect(self.page.get_by_text('Synthetic rollback render',exact=True)).to_have_count(1)
        expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)

    def test_source_settings_change_SSE_invalidates_but_never_mints_lease(self):
        self.select();self.caption_known()
        self.transport.emit(s.snapshot(2,value=s.history('Synthetic settings B','item-A','producer-B')))
        expect(self.page.get_by_text('Synthetic settings B',exact=True)).to_have_count(1)
        expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)
        self.transport.emit(s.snapshot(3,value=s.history('Synthetic same settings B','item-A','producer-B')))
        self.page.wait_for_timeout(100)
        expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)

    def test_switch_A_B_A_old_generation_callbacks_discard(self):
        self.select();self.page.locator('textarea').fill('Synthetic A draft')
        self.page.get_by_role('button',name='LIVE synthetic B',exact=False).click()
        self.page.get_by_role('button',name='LIVE synthetic A',exact=False).click()
        self.until(lambda:len(self.requests('/api/session-events'))>=3)
        self.transport.emit(s.snapshot(2,value=s.history('Synthetic current A generation')))
        expect(self.page.get_by_text('Synthetic current A generation',exact=True)).to_have_count(1)
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic A draft')
        self.assertGreaterEqual(self.transport.closed,2,'Each superseded native stream must close')

    def classified_failure(self,status,error):
        self.select();before_auth=len(self.requests('/api/session'))
        self.transport.json_status=status;self.transport.json_error=error;self.transport.close=True
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))==1)
        self.page.wait_for_timeout(300)
        self.assertEqual(len(self.requests('/api/session-live-snapshot')),1)
        self.assertEqual(len(self.requests('/api/session')),before_auth,'Stream failure must use the single JSON probe, not an auth probe')

    def test_probe429_preserves_lease_and_does_not_immediately_fallback(self):
        self.classified_failure(429,'unavailable');self.caption_known()
        self.assertEqual(len(self.requests('/api/session-events')),1)

    def test_probe503_unsupported_manual_mode_no_legacy_background_poll(self):
        self.classified_failure(503,'unsupported')
        old=len(self.requests('/api/session-history'));self.page.wait_for_timeout(6200)
        self.assertEqual(len(self.requests('/api/session-events')),1)
        self.assertEqual(len(self.requests('/api/session-history')),old)
        self.assertEqual(len(self.requests('/api/session-live-snapshot')),1)

    def test_probe401_existing_authExpired_stops_autonomous_stream(self):
        self.classified_failure(401,'unauthorized');self.page.wait_for_timeout(1200)
        self.assertEqual(len(self.requests('/api/session-events')),1)
        self.assertEqual(len(self.requests('/api/session-live-snapshot')),1)

    def test_probe422_terminal_invalid_request_no_retry_loop(self):
        self.classified_failure(422,'invalid_request');self.page.wait_for_timeout(1200)
        self.assertEqual(len(self.requests('/api/session-events')),1)
        self.assertEqual(len(self.requests('/api/session-live-snapshot')),1)

    def test_failed_manual_latest_clears_settings_and_reopens_transport_after_reply(self):
        self.select();self.caption_known()
        self.page.route('**/api/session-history?*',lambda route:route.fulfill(status=503,json={'error':'unavailable'}))
        button=self.page.get_by_role('button',name='Обновить переписку',exact=True)
        details=button.locator('xpath=ancestor::details')
        for detail in details.all():detail.evaluate('e=>e.open=true')
        button.click();expect(self.page.locator('#current-model-status')).to_have_text(UNKNOWN)
        self.until(lambda:self.transport.closed>=1)

class NativeTransportFixtureProof(unittest.TestCase):
    def test_actual_native_EventSource_parses_fixture_before_application_claims(self):
        fixture=s.Fixture(transport=True);self.addCleanup(fixture.stop);fixture.login()
        playwright=sync_playwright().start();self.addCleanup(playwright.stop)
        browser=playwright.chromium.launch(headless=True);self.addCleanup(browser.close)
        self.assertEqual(browser.version,'153.0.8010.12')
        context=browser.new_context();self.addCleanup(context.close);page=context.new_page();page.goto(fixture.origin)
        # This isolated native transport harness observation never invokes an
        # application callback or claims manager/auth/freshness acceptance.
        page.evaluate("""sid=>{window.fixtureEvent=null;window.fixtureES=new EventSource('/api/session-events?project=demo&sid='+sid);window.fixtureES.addEventListener('snapshot',e=>window.fixtureEvent=JSON.parse(e.data));}""",s.SID)
        deadline=time.monotonic()+3
        while fixture.transport.streams<1 and time.monotonic()<deadline:page.wait_for_timeout(20)
        self.assertEqual(fixture.transport.streams,1)
        fixture.transport.emit(s.snapshot());deadline=time.monotonic()+30
        # Poll the observed native event without a page-side eval waiter blocked by strict CSP.
        while page.evaluate('window.fixtureEvent') is None and time.monotonic()<deadline:page.wait_for_timeout(20)
        self.assertEqual(page.evaluate('window.fixtureEvent'),s.snapshot())
        page.evaluate('window.fixtureES.close()');deadline=time.monotonic()+3
        while fixture.transport.closed<1 and time.monotonic()<deadline:page.wait_for_timeout(20)
        self.assertEqual(fixture.transport.closed,1)
