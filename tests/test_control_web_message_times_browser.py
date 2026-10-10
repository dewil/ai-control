"""Source-blind INV-WSESS-21 browser acceptance with private synthetic history."""
import datetime
import importlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import parse_qsl, urlsplit
from control_browser_helpers import choose_project
from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET, SID

ROOT = Path(__file__).resolve().parents[1]
NOW = 1791248400  # 2026-10-06 01:00 UTC; Moscow04:00.
AGES = [0, 59, 60, 3599, 3600, 86399, 86400, 172800]
LABELS = ['только что', 'только что', '1 мин. назад', '59 мин. назад', '1 ч назад', '23 ч назад', '1 дн. назад', '2 дн. назад']


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root/'bin'))
    web = importlib.import_module('_control_web')
    class Backend:
        def snapshot(self): return {'tasks': []}
        def answer(self, *args): return {'error': 'unavailable'}
        def verdict(self, *args): return {'error': 'unavailable'}
        def session_projects(self): return {'projects': [{'name': 'demo'}]}
        def session_list(self, *args):
            return {'rows': [{'sid': SID, 'title': 'Time synthetic session', 'status': 'idle'}], 'has_more': False}
        def session_history(self, project, sid, cursor):
            data = json.loads((evidence/'control.json').read_text())
            items = [dict(item, id='older-'+item['id'], text='OLDER '+item['text']) for item in data['items']] if cursor else data['items']
            return {'turns': [{'id': 'older' if cursor else 'latest', 'status': 'completed', 'items': items}],
                    'next_cursor': None if cursor else 'older-fixture', 'truncated': False, 'recent_sends': []}
        def session_send(self, *args): return {'error': 'unavailable'}
        def session_send_status(self, *args): return {'error': 'stale'}
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0)); listener.listen(128)
    origin = 'http://127.0.0.1:'+str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD), 'totp_secret': SECRET,
                          'session_ttl': 3600, 'secure_cookie': False}, Backend())
    private_json(evidence/'ready.json', {'url': origin})
    uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[listener])


# Test-owned scheduler only intercepts >=one-minute timers, leaving existing
# initial/history network scheduling alone. It observes browser APIs, not app
# functions. Advancing calls age timers synchronously and never model/network.
CLOCK = '''(() => {
 const RealDate=Date; window.testNow=1791248400000;
 class FrozenDate extends RealDate {constructor(...a){super(...(a.length?a:[window.testNow]));} static now(){return window.testNow;}}
 window.Date=FrozenDate; window.testTimers=[]; window.testHidden=false;
 Object.defineProperty(document,'hidden',{get:()=>window.testHidden,configurable:true});
 Object.defineProperty(document,'visibilityState',{get:()=>window.testHidden?'hidden':'visible',configurable:true});
 for(const key of ['setInterval','setTimeout']) {const real=window[key].bind(window);window[key]=(fn,delay,...args)=>{
   if(delay>=60000){const t={fn,args,delay,key,active:true,due:window.testNow+delay};window.testTimers.push(t);return 100000+window.testTimers.length;}
   return real(fn,delay,...args);};}
 for(const key of ['clearInterval','clearTimeout']) {const real=window[key].bind(window);window[key]=id=>{
   if(id>100000){const t=window.testTimers[id-100001];if(t)t.active=false;}else real(id);};}
 window.testAdvance=ms=>{window.testNow+=ms;for(const t of [...window.testTimers])if(t.active&&t.due<=window.testNow){if(t.key==='setTimeout')t.active=false;else t.due=window.testNow+t.delay;t.fn(...t.args);}};
 window.testVisibility=value=>{window.testHidden=value;document.dispatchEvent(new Event('visibilitychange'));};
})();'''


def items_for(ages=AGES):
    return [{'id': role+str(i), 'role': role, 'text': f'Time {role} {i}', 'truncated': False,
             'timestamp': NOW-age, 'time_precision': 'turn'} for role in ('user', 'assistant') for i, age in enumerate(ages)]


class MessageTimesBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        os.umask(0o077)
        cls.tmp = tempfile.TemporaryDirectory(prefix='control-message-times-', dir='/var/tmp')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.evidence = Path(cls.tmp.name)
        private_json(cls.evidence/'control.json', {'items': items_for()})
        python = os.environ.get('CONTROL_MESSAGE_TIMES_SERVER_PYTHON', sys.executable)
        cls.server = subprocess.Popen([python, str(Path(__file__).resolve()), '--serve', str(ROOT), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            cls.server.terminate()
            try: cls.server.wait(4)
            except subprocess.TimeoutExpired: cls.server.kill(); cls.server.wait()
        cls.addClassCleanup(stop)
        deadline=time.monotonic()+8
        while not (cls.evidence/'ready.json').exists() and time.monotonic()<deadline:
            if cls.server.poll() is not None: raise RuntimeError('Synthetic fixture server failed')
            time.sleep(.02)
        cls.url=json.loads((cls.evidence/'ready.json').read_text())['url']
        cls.pw=sync_playwright().start(); cls.addClassCleanup(cls.pw.stop)
        executable=os.environ.get('CONTROL_MESSAGE_TIMES_BROWSER_EXECUTABLE')
        cls.browser=cls.pw.chromium.launch(headless=True, **({'executable_path':executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context=cls.browser.new_context(viewport={'width':1280,'height':900},timezone_id='America/Los_Angeles',has_touch=True)
        cls.addClassCleanup(cls.context.close)
        page=cls.context.new_page(); page.goto(cls.url)
        page.locator('#username').fill('owner')
        page.locator('input[type=password]').fill(PASSWORD)
        page.get_by_role('textbox',name=re.compile('TOTP|код|однораз',re.I)).fill(totp())
        page.get_by_role('button',name=re.compile('^Войти$',re.I)).click()
        page.get_by_role('button',name=re.compile('^Сессии$',re.I)).or_(page.get_by_role('tab',name=re.compile('^Сессии$',re.I))).wait_for()
        page.close()

    def setUp(self):
        private_json(self.evidence/'control.json', {'items':items_for()})
        self.page=self.context.new_page(); self.addCleanup(self.page.close)
        self.page.add_init_script(CLOCK)
        self.network=[]; self.errors=[]
        self.page.on('request',lambda r:self.network.append((r.method,r.url)))
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.goto(self.url)
        self.page.get_by_role('button',name=re.compile('^Сессии$',re.I)).or_(self.page.get_by_role('tab',name=re.compile('^Сессии$',re.I))).click()
        choose_project(self.page,'demo')
        self.session=self.page.get_by_role('button',name=re.compile('Time synthetic session'))
        self.session.wait_for()

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.assertFalse(any(url.split('/')[2]!=self.url.split('/')[2] for _,url in self.network))

    def open(self):
        self.session.click()
        self.page.get_by_text('Time assistant 0',exact=True).wait_for()

    def bubble(self, text):
        # Existing public .chat-items container; closest ancestor containing one
        # message's own native time avoids depending on new CSS class names.
        return self.page.get_by_text(text,exact=True).locator('xpath=ancestor::*[time or .//time][1]')

    def require_times(self, count=16):
        self.assertEqual(self.page.locator('.chat-items time').count(),count,
                         'INV-WSESS-21 each known user/assistant bubble needs native time')

    def test_relative_thresholds_both_roles_and_native_iso(self):
        self.open(); self.require_times()
        for role in ('user','assistant'):
            for i,(age,label) in enumerate(zip(AGES,LABELS)):
                bubble=self.bubble(f'Time {role} {i}')
                self.assertIn(label,bubble.inner_text())
                iso=bubble.locator('time').get_attribute('datetime')
                self.assertIsNotNone(iso)
                value=datetime.datetime.fromisoformat(iso.replace('Z','+00:00')).timestamp()
                self.assertEqual(value,NOW-age)

    def test_unknown_malformed_defensive_dto_no_invented_date(self):
        values=[(None,'unknown'),(True,'turn'),('1700000000','turn'),(-1,'turn'),(NOW,'unknown'),(253402300800,'turn')]
        fixture=[{'id':str(i),'role':'user' if i%2 else 'assistant','text':f'Unknown {i}',
                  'truncated':False,'timestamp':value,'time_precision':precision} for i,(value,precision) in enumerate(values)]
        private_json(self.evidence/'control.json',{'items':fixture})
        self.session.click(); self.page.get_by_text('Unknown 0',exact=True).wait_for()
        self.assertEqual(self.page.get_by_text('время неизвестно',exact=True).count(),len(values),
                         'Invalid/unknown timestamps must remain honest')
        self.assertEqual(self.page.locator('.chat-items time[datetime]').count(),0)

    def test_full_date_moscow_boundary_focus_hover_and_touch_disclosure(self):
        boundary=int(datetime.datetime(2025,12,31,22,5,tzinfo=datetime.timezone.utc).timestamp())
        private_json(self.evidence/'control.json',{'items':[{'id':'boundary','role':'user','text':'Time assistant 0',
            'truncated':False,'timestamp':boundary,'time_precision':'turn'}]})
        self.open(); self.require_times(1)
        native=self.page.locator('.chat-items time')
        # Exact date is available through a focusable control; time can itself
        # be focusable or live within native summary/button disclosure.
        controls=native.locator('xpath=ancestor-or-self::*[@tabindex="0" or self::button or self::summary][1]')
        if controls.count()==0:
            controls=self.bubble('Time assistant 0').locator('button,summary,[tabindex="0"]')
        self.assertGreater(controls.count(),0,'Date needs keyboard focus and touch control, not title alone')
        control=controls.first
        control.focus(); self.assertTrue(control.evaluate('el=>el===document.activeElement'))
        def date_visible():
            visible=self.page.locator('body').inner_text()
            accessible=control.get_attribute('aria-label') or ''
            return visible
        accessible=control.aria_snapshot()
        self.assertIn('начало хода',accessible.lower(),'Accessible label must declare turn-start precision')
        self.assertIn('01:05',accessible)
        for action in (control.hover,lambda:control.focus(),control.tap):
            action(); full=date_visible()
            self.assertIn('начало хода',full.lower())
            self.assertRegex(full,r'01[.\s]01[.\s]2026|1 января 2026')
            self.assertIn('01:05',full,'Moscow precision must not follow browser Los Angeles timezone')

    def test_local_minute_update_preserves_nodes_focus_draft_anchor_and_network(self):
        self.open(); self.require_times()
        self.page.locator('textarea').fill('Synthetic retained draft')
        self.page.locator('textarea').focus()
        self.page.evaluate('''() => {window.testAnchor=document.querySelectorAll('.chat-items time')[8];testAnchor.scrollIntoView({block:'center'});window.testAnchorTop=testAnchor.getBoundingClientRect().top;window.testFocused=document.activeElement;testFocused.setSelectionRange(5,9);}''')
        timers=self.page.evaluate('testTimers.filter(t=>t.active).map(t=>t.delay)')
        self.assertTrue(timers,'Local age refresh must schedule a bounded minute timer')
        self.assertTrue(all(t>=60000 for t in timers))
        before=list(self.network)
        self.page.evaluate('testAdvance(59000)')
        self.assertIn('только что',self.bubble('Time assistant 0').inner_text())
        self.page.evaluate('testAdvance(1000)')
        self.assertIn('1 мин. назад',self.bubble('Time assistant 0').inner_text())
        self.assertEqual(self.network,before,'Age update must not issue fetch/RPC/poll')
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic retained draft')
        self.assertTrue(self.page.evaluate('testAnchor.isConnected && document.activeElement===testFocused && testFocused.selectionStart===5 && testFocused.selectionEnd===9'))
        self.assertLessEqual(abs(self.page.evaluate('testAnchor.getBoundingClientRect().top-testAnchorTop')),8)

    def test_hidden_tab_pauses_then_return_recomputes_without_network(self):
        self.open(); self.require_times()
        before=list(self.network)
        self.page.evaluate('testVisibility(true)')
        visible=self.page.locator('.chat-items').inner_text()
        self.page.evaluate('testAdvance(120000)')
        self.assertEqual(self.page.locator('.chat-items').inner_text(),visible,'Hidden tab cannot run age updates')
        self.assertEqual(self.network,before,'Hidden tab cannot issue network requests while age timers are paused')
        def exact_queue_read(method, url):
            parsed=urlsplit(url)
            query=parse_qsl(parsed.query,keep_blank_values=True)
            return (method=='GET' and parsed.path=='/api/session-queue' and len(query)==2
                    and dict(query)=={'project':'demo','sid':SID})
        with self.page.expect_request(lambda request: exact_queue_read(request.method,request.url)):
            self.page.evaluate('testVisibility(false)')
        self.assertIn('2 мин. назад',self.bubble('Time assistant 0').inner_text())
        # Visible resume needs fresh LIVE admission/lease and one queue read to
        # restore native rows. No other foreground request is permitted here.
        resumed=self.network[len(before):]
        queue_reads=[(method,url) for method,url in resumed if exact_queue_read(method,url)]
        self.assertEqual(len(queue_reads),1)
        self.assertEqual([(method,url) for method,url in resumed
                          if not exact_queue_read(method,url)
                          and '/api/session-events?' not in url
                          and '/api/session-live-snapshot?' not in url],[])

    def test_valid_future_keeps_exact_date_but_relative_age_unknown(self):
        future=NOW+3600
        private_json(self.evidence/'control.json',{'items':[{'id':'future','role':'assistant','text':'Time assistant 0',
            'truncated':False,'timestamp':future,'time_precision':'turn'}]})
        self.open(); self.require_times(1)
        self.assertIn('время неизвестно',self.bubble('Time assistant 0').inner_text())
        iso=self.page.locator('.chat-items time').get_attribute('datetime')
        self.assertIsNotNone(iso)
        self.assertEqual(datetime.datetime.fromisoformat(iso.replace('Z','+00:00')).timestamp(),future)

    def test_chat_hidden_stops_age_timers(self):
        self.open(); self.require_times()
        self.page.get_by_role('tab',name='Задачи',exact=True).click()
        # Collapse/navigation is a real user action. Detached chat timers must
        # stop; ordinary session-expiration timers are outside this assertion.
        self.assertFalse(self.page.locator('.chat-items').is_visible())
        self.assertEqual(self.page.evaluate('testTimers.filter(t=>t.active&&t.delay===60000).length'),0)

    def test_z_logout_stops_age_timers(self):
        # Last scenario deliberately revokes this synthetic class login.
        self.open(); self.require_times()
        self.page.get_by_role('button',name='Выйти',exact=True).click()
        self.page.locator('input[type=password]').wait_for()
        before=list(self.network)
        self.page.evaluate('testAdvance(120000)')
        self.assertEqual(self.page.evaluate('testTimers.filter(t=>t.active&&t.delay===60000).length'),0)
        self.assertEqual(self.network,before)

    def test_older_items_receive_times_and_mobile_does_not_overflow(self):
        self.open(); self.require_times()
        older=self.page.get_by_role('button',name=re.compile('Older|Предыдущ|Ранние|Старые|Ранее|более старые',re.I))
        self.assertEqual(older.count(),1,'Existing Older control must remain accessible')
        older.click()
        self.page.wait_for_timeout(200)
        self.require_times(32)
        self.page.set_viewport_size({'width':360,'height':900})
        self.assertLessEqual(self.page.evaluate('Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)'),361)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--serve': serve(Path(sys.argv[2]),Path(sys.argv[3]))
    else: unittest.main(verbosity=2)
