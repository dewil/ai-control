"""Source-blind limits UI acceptance: actual app/server/JS and synthetic DTOs."""
import base64
import re
import time
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright
import limits_dashboard_blind_support as s
import live_sse_blind_support as live

NORMAL='Обычный ×1'
DOUBLE='Ориентир ×2'


class LimitsBrowserRED(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True);cls.addClassCleanup(cls.browser.close)
        if cls.browser.version!='153.0.8010.12':raise RuntimeError('Chromium153 fixture drift; no skip')

    def setUp(self):
        original=live.Backend;live.Backend=s.LimitsBackend
        try:self.fixture=live.Fixture(session_store=True)
        finally:live.Backend=original
        self.addCleanup(self.fixture.stop);self.fixture.login();self.backend=self.fixture.backend
        self.context=self.browser.new_context(viewport={'width':390,'height':900})
        self.addCleanup(self.context.close)
        name,value=self.fixture.cookie.split('=',1)
        self.context.add_cookies([dict(name=name,value=value,url=self.fixture.origin)])
        self.page=self.context.new_page();self.page.set_default_timeout(2500)
        self.requests=[];self.errors=[]
        self.page.on('request',lambda request:self.requests.append((request.method,urlsplit(request.url).path)))
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.add_init_script('''window.testLimitsAborts=0;
          const originalAbort=AbortController.prototype.abort;
          AbortController.prototype.abort=function(...args){testLimitsAborts++;return originalAbort.apply(this,args)};''')

    def tearDown(self):self.assertEqual(self.errors,[])

    def tab(self,name):
        return self.page.get_by_role('tab',name=name,exact=True).or_(self.page.get_by_role('button',name=name,exact=True))

    def panel(self):
        return self.page.get_by_role('tabpanel',name='Лимиты',exact=True)

    def open(self):
        self.page.goto(self.fixture.origin)
        expect(self.tab('Лимиты')).to_be_visible()
        self.tab('Лимиты').click()

    def until(self,predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline:self.page.wait_for_timeout(20)
        self.assertTrue(predicate(),'Expected public limits outcome')

    def gets(self):return [request for request in self.requests if request==('GET','/api/limits-overview')]

    def meters(self):
        normal=self.panel().get_by_role('meter',name=NORMAL,exact=True)
        double=self.panel().get_by_role('meter',name=DOUBLE,exact=True)
        expect(normal).to_be_visible();expect(double).to_be_visible()
        return normal,double

    def assert_marker_values(self,elapsed_days):
        for meter,label,value in zip(self.meters(),(NORMAL,DOUBLE),(min(7,elapsed_days),min(7,elapsed_days*2))):
            self.assertEqual(float(meter.get_attribute('aria-valuemin')),0)
            self.assertEqual(float(meter.get_attribute('aria-valuemax')),7)
            self.assertAlmostEqual(float(meter.get_attribute('aria-valuenow')),value,delta=.002)
            expect(self.panel().get_by_text(label,exact=True).first).to_be_visible()

    def test_real_route_primary_weekly_markers_at_0_1_3point5_days_and_mobile_geometry(self):
        # INV-WLIM-14 INV-WLIM-15: primary is weekly, rather than assumed 5h.
        self.open();self.meters()
        for elapsed in (0,s.DAY,3.5*s.DAY):
            with self.subTest(elapsed_days=elapsed/s.DAY):
                self.backend.limits_value=s.overview(elapsed=elapsed)
                self.open();self.assert_marker_values(elapsed/s.DAY)
                self.assertEqual(len(self.backend.limits_calls),len(self.gets()),'GET must traverse actual authenticated API')
                expect(self.panel().get_by_text(re.compile(r'7\s*(?:дней|дн\b)')).first).to_be_visible()
                expect(self.panel().get_by_text(re.compile(r'75\s*%')).first).to_be_visible()
                expect(self.panel().get_by_text(re.compile('Codex',re.I)).first).to_be_visible()
                rendered=self.page.locator('body').inner_text()
                self.assertTrue(any(part in s.identity() for part in re.findall(r'\b[0-9a-f]{8,64}\b',rendered)),
                                'Source account identity must be readable in full or abbreviated form')
                expect(self.panel().get_by_text(re.compile('Claude',re.I)).first).to_be_visible()
                expect(self.panel().get_by_text(re.compile('Недоступ|Не подключ',re.I)).first).to_be_visible()
                for width in (320,390,1280):
                    with self.subTest(width=width):
                        self.page.set_viewport_size(dict(width=width,height=900))
                        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width+1)
                        normal,double=self.meters()
                        geometry=normal.evaluate('''(first,second)=>{
                          if(!second)return null;
                          let common=first.parentElement;while(common&&!common.contains(second))common=common.parentElement;
                          if(!common)return null;
                          const a=first.getBoundingClientRect(),b=second.getBoundingClientRect(),t=common.getBoundingClientRect();
                          return {track:{x:t.x,width:t.width},normal:{x:a.x,width:a.width},double:{x:b.x,width:b.width}};
                        }''',double.element_handle())
                        self.assertIsNotNone(geometry,'Both labelled meters require a common timeline track')
                        track=geometry['track'];self.assertGreater(track['width'],100)
                        for label,value in (('normal',min(7,elapsed/s.DAY)),('double',min(7,2*elapsed/s.DAY))):
                            box=geometry[label];center=box['x']+box['width']/2
                            expected=track['x']+track['width']*value/7
                            self.assertAlmostEqual(center,expected,delta=4,msg='Marker center disagrees with seven-day value')
                            self.assertGreaterEqual(center,-1);self.assertLessEqual(center,width+1)
                        button=self.tab('Лимиты');box=button.bounding_box()
                        self.assertGreaterEqual(box['width'],44);self.assertGreaterEqual(box['height'],44)
                        button.focus();self.page.keyboard.press('Shift+Tab');self.page.keyboard.press('Tab')
                        self.assertTrue(button.evaluate('e=>{const s=getComputedStyle(e);return document.activeElement===e&&(parseFloat(s.outlineWidth)>0&&s.outlineStyle!=="none"||s.boxShadow!=="none")}'),
                                        'Keyboard focus must remain visible')
                if elapsed==3.5*s.DAY:
                    expect(self.panel().get_by_text('Ориентир достиг границы',exact=True)).to_be_visible()
                self.assertEqual(self.backend.limits_value['sources'][0]['windows'][0]['remaining_percent'],75)
                self.assertNotIn(s.ACCOUNT,self.page.locator('body').inner_text())

    def test_null_percent_is_unknown_without_bar_and_expired_reset_is_explicit(self):
        # INV-WLIM-14 INV-WLIM-15
        self.backend.limits_value=s.overview(remaining=None,anchor=False)
        self.backend.limits_value['sources'][0]['windows'][0]['resets_at']=s.NOW-1
        self.open()
        expect(self.panel().get_by_text('Неизвестно',exact=True).first).to_be_visible()
        expect(self.panel().get_by_text('Окно истекло, ожидаем новые данные',exact=True)).to_be_visible()
        expect(self.panel().get_by_role('meter',name=NORMAL)).to_have_count(0)
        expect(self.panel().get_by_role('meter',name=DOUBLE)).to_have_count(0)
        expect(self.panel().get_by_role('progressbar')).to_have_count(0)
        self.assertNotRegex(self.page.locator('body').inner_text(),r'(?<!\d)0\s*%')

    def test_remaining_bar_zero_full_and_three_quarters_have_real_visual_geometry(self):
        # INV-WLIM-14: compare rendered pixels, without private fill-node selectors.
        self.open();expect(self.panel().get_by_role('progressbar')).to_be_visible()
        for width in (320,390,1280):
            rows={}
            for remaining in (0,100,75):
                with self.subTest(width=width,remaining=remaining):
                    self.backend.limits_value=s.overview(elapsed=0,remaining=remaining,duration=300)
                    self.page.set_viewport_size(dict(width=width,height=900));self.open()
                    bar=self.panel().get_by_role('progressbar');expect(bar).to_be_visible()
                    self.assertEqual(float(bar.get_attribute('aria-valuemin')),0)
                    self.assertEqual(float(bar.get_attribute('aria-valuemax')),100)
                    self.assertEqual(float(bar.get_attribute('aria-valuenow')),remaining)
                    box=bar.bounding_box();self.assertGreater(box['width'],100)
                    self.assertGreaterEqual(box['x'],-1);self.assertLessEqual(box['x']+box['width'],width+1)
                    png=base64.b64encode(bar.screenshot(scale='css')).decode('ascii')
                    rows[remaining]=self.page.evaluate('''async encoded=>{
                      const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
                      const bitmap=await createImageBitmap(new Blob([bytes],{type:'image/png'}));
                      const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
                      const context=canvas.getContext('2d');context.drawImage(bitmap,0,0);
                      return Array.from(context.getImageData(0,Math.floor(bitmap.height/4),bitmap.width,1).data);
                    }''',png)
            self.assertEqual(len(rows[0]),len(rows[100]));self.assertEqual(len(rows[0]),len(rows[75]))
            def changed(reference,current):
                pixels=len(reference)//4
                return [x for x in range(4,pixels-4)
                        if sum(abs(reference[4*x+c]-current[4*x+c]) for c in range(3))>45]
            full=changed(rows[0],rows[100]);partial=changed(rows[0],rows[75])
            self.assertGreater(len(full),len(rows[0])//4*.6,'Zero and full must change the actual bar, beyond its text label')
            self.assertAlmostEqual(len(partial)/len(full),.75,delta=.08,
                                   msg='75% bar must fill about three quarters of the same track')

    def test_visible_tick_expires_window_before_pending_poll_response(self):
        # INV-WLIM-11 INV-WLIM-14 INV-WLIM-16
        self.page.clock.install();self.backend.limits_value=s.overview(elapsed=0,duration=300)
        self.backend.limits_value['sources'][0]['windows'][0].update(
            resets_at=s.NOW+30,window_started_at=s.NOW+30-300*60)
        self.open();expect(self.panel().get_by_role('progressbar')).to_be_visible()
        held=[];self.page.route('**/api/limits-overview',lambda route:held.append(route))
        self.page.clock.fast_forward(61000);self.until(lambda:len(held)==1)
        expect(self.panel().get_by_text('Окно истекло, ожидаем новые данные',exact=True)).to_be_visible()
        expect(self.panel().get_by_text('Неизвестно',exact=True).first).to_be_visible()
        expect(self.panel().get_by_role('progressbar')).to_have_count(0)

    def test_known_percent_unknown_anchor_has_remaining_but_no_weekly_markers(self):
        # INV-WLIM-11 INV-WLIM-14 INV-WLIM-15
        self.backend.limits_value=s.overview(anchor=False)
        self.backend.limits_value['sources'][0]['windows'][0]['resets_at']=None
        self.open();expect(self.panel().get_by_text(re.compile(r'75\s*%')).first).to_be_visible()
        expect(self.panel().get_by_role('meter',name=NORMAL)).to_have_count(0)
        expect(self.panel().get_by_role('meter',name=DOUBLE)).to_have_count(0)

    def test_only_weekly_duration_gets_two_markers_and_payload_text_is_not_HTML(self):
        # INV-WLIM-14 INV-WLIM-15: malicious synthetic bucket remains text.
        self.backend.limits_value=s.overview(elapsed=0,duration=300)
        self.backend.limits_value['sources'][0]['windows'][0].update(
            bucket='<img src=x onerror="window.limitsInjected=1">',id='codex:primary')
        # Malformed browser input is intentionally intercepted outside the safe
        # HTTP validator; rejecting it is also a valid UI outcome.
        self.page.route('**/api/limits-overview',lambda route:route.fulfill(status=200,json=self.backend.limits_value))
        self.open();self.until(lambda:len(self.gets())==1);self.page.wait_for_timeout(80)
        expect(self.panel().get_by_role('meter',name=NORMAL)).to_have_count(0)
        expect(self.panel().get_by_role('meter',name=DOUBLE)).to_have_count(0)
        self.assertIsNone(self.page.evaluate('window.limitsInjected'))
        self.assertEqual(self.page.locator('img[onerror]').count(),0)

    def test_server_monotonic_clock_survives_wallclock_skew_and_reaches_stale(self):
        # INV-WLIM-16: Date.now is intentionally years away from server_now.
        self.page.clock.install(time=s.NOW*1000+10*365*s.DAY*1000)
        self.backend.limits_value=s.overview(elapsed=s.DAY)
        self.open();self.assert_marker_values(1)
        held=[];self.page.route('**/api/limits-overview',lambda route:held.append(route))
        self.page.clock.fast_forward(60000);self.until(lambda:len(held)==1)
        self.assert_marker_values(1+60/s.DAY)
        self.page.clock.fast_forward(121000);self.page.wait_for_timeout(50)
        self.assertEqual(len(held),1,'Refreshing must remain single-flight')
        expect(self.panel().get_by_text(re.compile('Устарел|stale',re.I)).first).to_be_visible()
        self.assert_marker_values(1+181/s.DAY)

    def test_hidden_tabclose_and_foreground_reentry_abort_and_request_once(self):
        # INV-WLIM-16
        self.page.clock.install();self.open();self.meters()
        self.assertEqual(len(self.gets()),1)
        self.page.clock.fast_forward(59000);self.page.wait_for_timeout(30)
        self.assertEqual(len(self.gets()),1,'Refresh ran more often than 60s')
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
        before=len(self.gets());self.page.clock.fast_forward(300000);self.page.wait_for_timeout(50)
        self.assertEqual(len(self.gets()),before,'Hidden page polled vendor limits')
        held=[];self.page.route('**/api/limits-overview',lambda route:held.append(route))
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('pageshow'))")
        self.until(lambda:len(held)==1)
        self.assertEqual(len(self.gets()),before+1,'Foreground entry duplicated fresh GET')
        expect(self.panel().get_by_text(re.compile('Загруз|Обновл|Устарел|stale',re.I)).first).to_be_visible()
        self.tab('Сессии').click();aborts=self.page.evaluate('testLimitsAborts')
        self.assertGreater(aborts,0,'Closing limits gates must abort the held request')
        self.page.clock.fast_forward(300000);self.page.wait_for_timeout(50)
        self.assertEqual(len(held),1,'Inactive limits tab polled')

    def test_late_response_after_logout_login_cannot_repaint_new_identity(self):
        # INV-WLIM-16: bypass abort to test generation fence independently.
        self.page.add_init_script('''const actualFetch=window.fetch.bind(window);
          window.fetch=(input,init={})=>String(input).includes('/api/limits-overview')?
            actualFetch(input,{...init,signal:undefined}):actualFetch(input,init);''')
        held=[];self.page.route('**/api/limits-overview',lambda route:held.append(route))
        self.open();self.until(lambda:len(held)==1)
        old=s.overview(remaining=13)
        self.page.get_by_role('button',name='Выйти',exact=True).click()
        expect(self.page.get_by_role('button',name='Войти',exact=True)).to_be_visible()
        self.fixture.login()
        name,value=self.fixture.cookie.split('=',1)
        self.context.add_cookies([dict(name=name,value=value,url=self.fixture.origin)])
        self.page.locator('input[autocomplete=username]').fill('dwl')
        self.page.locator('input[type=password]').fill(live.PASSWORD)
        self.page.locator('input[autocomplete=one-time-code]').fill(self.fixture.web.totp_code(live.SECRET,self.fixture.now+30))
        self.fixture.now+=30
        self.page.get_by_role('button',name='Войти',exact=True).click()
        expect(self.tab('Лимиты')).to_be_visible();self.tab('Лимиты').click()
        self.until(lambda:len(held)>=2)
        fresh=s.overview(remaining=88);fresh['sources'][0]['account_id']=s.identity('new-login-account')
        held[-1].fulfill(status=200,json=fresh)
        expect(self.panel().get_by_text(re.compile(r'88\s*%')).first).to_be_visible()
        held[0].fulfill(status=200,json=old);self.page.wait_for_timeout(80)
        expect(self.panel().get_by_text(re.compile(r'88\s*%')).first).to_be_visible()
        expect(self.panel().get_by_text(re.compile(r'13\s*%'))).to_have_count(0)

    def test_android_suspend_never_polls_and_resume_gets_fresh_anchor(self):
        # INV-WLIM-16 with existing public Android lifecycle protocol2.
        self.page.clock.install();self.open();self.assert_marker_values(1)
        self.assertEqual(self.page.evaluate('typeof aiControlAndroidSuspend'),'function')
        self.page.evaluate('aiControlAndroidSuspend({protocol:2,serial:1})')
        before=len(self.gets());self.page.clock.fast_forward(600000);self.page.wait_for_timeout(50)
        self.assertEqual(len(self.gets()),before)
        self.backend.limits_value=s.overview(elapsed=0)
        self.page.evaluate('aiControlAndroidResume({protocol:2,serial:2,phase:"admit"})')
        self.page.evaluate('aiControlAndroidResume({protocol:2,serial:3,phase:"activate",admissionSerial:2})')
        self.until(lambda:len(self.gets())==before+1)
        self.assert_marker_values(0)


if __name__=='__main__':unittest.main()
