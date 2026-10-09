"""INV-WSESS-42/43/45 independent DOM/HTTP oracle; synthetic local fixture only.

No production asset reads, no provider/private history. INV44 is pending and absent.
"""
from control_live_legacy_fixture import LiveHistoryFixture, replay_path
import importlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from control_browser_helpers import choose_project
from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET, SID
from test_control_web_compact_chat_browser import OTHER

ROOT = Path(__file__).resolve().parents[1]


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root / 'bin'))
    web = importlib.import_module('_control_web')
    def config(): return json.loads((evidence / 'control.json').read_text())
    def calls():
        path = evidence / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    def record(data):
        with (evidence / 'calls.jsonl').open('a') as handle: handle.write(json.dumps(data)+'\n')
    # INV-WSESS-53: actual public LIVE backend replaces legacy automatic polling.
    class Backend(LiveHistoryFixture):
        _live_evidence = evidence
        def snapshot(self): return {'tasks': []}
        def answer(self, *args): return {'error': 'unavailable'}
        def verdict(self, *args): return {'error': 'unavailable'}
        def session_projects(self): return {'projects': [{'name': 'demo'}, {'name':'alternate'}]}
        def session_list(self, project, page):
            return {'rows':[{'sid':SID,'title':'UX synthetic session with a long readable title','status':'idle'},
                            {'sid':OTHER,'title':'Other UX synthetic session','status':'idle'}],'has_more':False}
        def session_history(self, project, sid, cursor):
            data=config(); record({'kind':'history','project':project,'sid':sid,'cursor':cursor})
            if sid == SID: time.sleep(data.get('history_delay',0))
            if data.get('history_error') and sid == SID: return {'error':'unavailable'}
            items=[{'id':'item-'+str(i),'role':'assistant','text':'Fixture readable message '+str(i),
                    'truncated':False} for i in range(24)]
            sends=[r for r in calls() if r['kind']=='send' and r['sid']==sid and r['project']==project]
            if data.get('canonical'):
                for n, send in enumerate(sends):
                    item={'id':data.get('canonical_key','canonical')+'-'+str(n),'role':data.get('canonical_role','user'),
                          'text':data.get('canonical_text','Canonical redacted ')+str(n),'truncated':data.get('truncated',False)}
                    if not data.get('missing_id'): item['client_id']=data.get('client_id',send['message_id'])
                    items.append(item)
            return {'turns':[{'id':'fixture-turn','status':'completed','items':items}],
                    'next_cursor':None,'truncated':data.get('truncated',False),'recent_sends':[]}
        def session_send(self, project, sid, message_id, text):
            data=config(); record({'kind':'send','project':project,'sid':sid,'message_id':message_id,'text':text})
            time.sleep(data.get('send_delay',0))
            return {'status':data.get('send_status','accepted'),'message_id':message_id,
                    'turn_id':SID if data.get('send_status','accepted')=='accepted' else None}
        def session_send_status(self, project, sid, message_id):
            record({'kind':'status','project':project,'sid':sid,'message_id':message_id})
            return {'status':config().get('checked_status','accepted'),'message_id':message_id,'turn_id':SID}
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    origin='http://127.0.0.1:'+str(listener.getsockname()[1])
    app=web.create_app({'origin':origin,'password_hash':web.hash_password(PASSWORD),'totp_secret':SECRET,
                        'session_ttl':3600,'secure_cookie':False,'totp_state_path':replay_path(evidence)},Backend())
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    deadline=time.monotonic()+8
    while not server.started:
        if not thread.is_alive() or time.monotonic()>deadline: raise RuntimeError('Synthetic startup failed')
        time.sleep(.01)
    private_json(evidence/'ready.json',{'url':origin});thread.join()


class WebUXBlindBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.tmp=tempfile.TemporaryDirectory(prefix='web-ux-blind-',dir='/var/tmp');cls.addClassCleanup(cls.tmp.cleanup)
        cls.evidence=Path(cls.tmp.name);private_json(cls.evidence/'control.json',{})
        cls.server=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--serve',str(ROOT),str(cls.evidence)],
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def stop():
            cls.server.terminate()
            try:cls.server.wait(4)
            except subprocess.TimeoutExpired:cls.server.kill();cls.server.wait()
        cls.addClassCleanup(stop)
        deadline=time.monotonic()+8
        while not (cls.evidence/'ready.json').exists():
            if cls.server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Synthetic server not ready')
            time.sleep(.02)
        cls.url=json.loads((cls.evidence/'ready.json').read_text())['url']
        cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True);cls.addClassCleanup(cls.browser.close)
        cls.context=cls.browser.new_context(viewport={'width':1280,'height':900});cls.addClassCleanup(cls.context.close)
        page=cls.context.new_page();page.goto(cls.url)
        page.locator('#username').fill('owner');page.locator('input[type=password]').fill(PASSWORD)
        page.get_by_role('textbox',name=re.compile('TOTP|код|однораз',re.I)).fill(totp())
        page.get_by_role('button',name='Войти',exact=True).click()
        page.get_by_role('button',name='Сессии',exact=True).or_(page.get_by_role('tab',name='Сессии',exact=True)).wait_for();page.close()

    def setUp(self):
        self.control();(self.evidence/'calls.jsonl').unlink(missing_ok=True)
        self.page=self.context.new_page();self.addCleanup(self.page.close)
        self.page.set_default_timeout(4000);self.errors=[];self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.goto(self.url);self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        choose_project(self.page,'demo');self.session=self.page.get_by_role('button',name=re.compile('^UX synthetic session'))
        self.session.wait_for()
    def tearDown(self):self.assertEqual(self.errors,[])
    def control(self,**data):
        target=self.evidence/'control-next.json';private_json(target,data);target.replace(self.evidence/'control.json')
    def calls(self,kind):
        path=self.evidence/'calls.jsonl'
        return [r for r in map(json.loads,path.read_text().splitlines()) if r['kind']==kind] if path.exists() else []
    def open(self):
        self.session.click();self.page.get_by_text('Fixture readable message 23',exact=True).wait_for()
    def toggle(self):
        element=self.page.locator('#projects-toggle')
        self.assertEqual(element.count(),1,'INV43 accessible projects toggle absent')
        return element
    def local(self):return self.page.locator('#chat-items [data-local-outgoing="true"]')
    def send(self,text='Exact synthetic outgoing text'):
        self.page.locator('textarea').fill(text);self.page.get_by_role('button',name='Отправить',exact=True).click()
        self.assertEqual(self.local().count(),1,'INV45 local outgoing bubble absent before delayed ACK')
        self.assertIn(text,self.local().inner_text());self.assertIn('Отправляется',self.local().inner_text())
        return self.local().get_attribute('data-send-id')
    def poll(self):
        before=len(self.calls('history'));deadline=time.monotonic()+9
        while len(self.calls('history'))<=before and time.monotonic()<deadline:self.page.wait_for_timeout(100)
        self.assertGreater(len(self.calls('history')),before,'Fixture must observe actual history poll')
        self.page.wait_for_timeout(250)

    def test_INV42_geometry(self):
        self.open()
        for width in (320,390,1280):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':900})
                observation=self.page.evaluate('''() => {const article=document.querySelector('article.chat-message'),s=getComputedStyle(article);return {overflow:Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth,padding:[s.paddingTop,s.paddingBottom,s.paddingLeft,s.paddingRight].map(parseFloat),targets:[...document.querySelectorAll('button,input,select,textarea')].filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().height).map(e=>[e.getBoundingClientRect().width,e.getBoundingClientRect().height]),font:parseFloat(getComputedStyle(article.querySelector('p')).fontSize)}}''')
                self.assertLessEqual(observation['overflow'],1)
                self.assertTrue(all(p<=limit for p,limit in zip(observation['padding'],[8,8,12,12])),observation)
                self.assertGreaterEqual(observation['font'],14)
                self.assertTrue(all(w>=43.5 and h>=43.5 for w,h in observation['targets']),observation)

    def test_INV43_selection_manual_reopen_poll_keyboard(self):
        toggle=self.toggle();self.assertEqual(toggle.get_attribute('aria-controls'),'projects-body')
        self.assertEqual(toggle.get_attribute('aria-expanded'),'true')
        self.open();self.assertEqual(toggle.get_attribute('aria-expanded'),'false')
        toggle.focus();toggle.press('Enter');self.assertEqual(toggle.get_attribute('aria-expanded'),'true')
        self.page.locator('textarea').fill('Retained draft');self.page.locator('textarea').focus()
        self.poll();self.assertEqual(toggle.get_attribute('aria-expanded'),'true')
        self.assertEqual(self.page.locator('textarea').input_value(),'Retained draft')
        self.assertTrue(self.page.locator('textarea').evaluate('e=>e===document.activeElement'))
        toggle.focus();toggle.press('Space');self.assertEqual(toggle.get_attribute('aria-expanded'),'false')

    def test_INV43_failed_and_stale_selection(self):
        toggle=self.toggle();self.control(history_error=True);self.session.click();self.page.wait_for_timeout(500)
        self.assertEqual(toggle.get_attribute('aria-expanded'),'true')
        self.control(history_delay=1);self.session.click()
        self.page.get_by_role('button',name=re.compile('^Other UX')).click()
        self.page.get_by_text('Fixture readable message 23',exact=True).wait_for()
        toggle.click();self.page.wait_for_timeout(1300)
        self.assertEqual(toggle.get_attribute('aria-expanded'),'true','Late A proof must not close manually opened B')

    def test_INV45_delayed_ack_exact_id_lag_timer_series(self):
        self.open();self.control(send_delay=1)
        mid=self.send();self.page.wait_for_timeout(200)
        self.assertEqual(self.calls('send')[0]['message_id'],mid)
        self.page.get_by_role('button',name='Отправить',exact=True).evaluate('e=>e.click()')
        self.assertEqual(self.local().count(),1);self.page.wait_for_timeout(1300)
        self.assertIn('Принято',self.local().inner_text());self.poll()
        self.assertEqual(self.local().count(),1,'Lagging history or receipt timer removed unmatched text')
        self.page.locator('textarea').fill('Exact synthetic outgoing text')
        self.page.get_by_role('button',name='Отправить',exact=True).click();self.page.wait_for_timeout(200)
        self.assertEqual(self.local().count(),2,'Previous attempt lost when latest attempt changed')
        self.assertEqual(len(set(self.local().evaluate_all('nodes=>nodes.map(n=>n.dataset.sendId)'))),2)

    def test_INV45_exact_role_id_canonical_and_truncated_reconciliation(self):
        self.open();self.control(send_delay=1);mid=self.send();self.page.wait_for_timeout(1300)
        for number,invalid in enumerate(({'canonical_role':'assistant'},{'missing_id':True},{'client_id':'invalid'},
                        {'client_id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'})):
            with self.subTest(invalid=invalid):
                self.control(canonical=True,canonical_key='unmatched-'+str(number),canonical_text='Unmatched fixture '+str(number)+' ',**invalid);self.poll()
                self.assertEqual(self.local().count(),1,'Nonmatching/nonuser canonical entry removed outgoing bubble')
        self.control(canonical=True,truncated=True);self.poll()
        self.assertEqual(self.local().count(),0)
        self.assertEqual(self.page.locator('#chat-items article').filter(has_text='Canonical redacted 0').count(),1)
        self.assertNotIn('Exact synthetic outgoing text',self.page.locator('#chat-items').inner_text())
        self.poll();self.assertEqual(self.local().count(),0,'Repeated snapshot resurrected local text')
        self.assertEqual(len(self.calls('send')),1)

    def test_INV45_ack_outcomes_and_scope(self):
        for outcome,label in [('rejected','Не принято'),('delivery_unknown','Доставка неизвестна')]:
            with self.subTest(outcome=outcome):
                prior=len(self.calls('send'))
                self.open();self.control(send_delay=1,send_status=outcome);self.send()
                self.page.get_by_role('button',name=re.compile('^Other UX')).click()
                self.page.get_by_text('Fixture readable message 23',exact=True).wait_for();self.page.wait_for_timeout(1300)
                self.assertEqual(self.local().count(),0,'Late A ACK leaked into B')
                self.session.click();self.page.get_by_text('Fixture readable message 23',exact=True).wait_for()
                self.assertIn(label,self.local().inner_text())
                self.assertEqual(len(self.calls('send')),prior+1,'Unknown/rejected receipt caused automatic resend')
                # New context for next outcome; no stale local text persistence.
                self.page.reload();self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
                choose_project(self.page,'demo');self.session.wait_for()

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--serve':serve(Path(sys.argv[2]),Path(sys.argv[3]))
    else:unittest.main()
