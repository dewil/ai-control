"""INV-DEVBUS-09 FR-BUS-03: isolated component, synthetic fetch only."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
JS=ROOT/'bin/_control_web_devbus.js'
CSS=ROOT/'bin/_control_web_devbus.css'


def snapshot(text='safe result',state='completed'):
    return {'schema':1,'connection':{'state':'live','reason':None},
            'coverage':{'mode':'window','first_seq':1,'last_seq':2,'ttl_seconds':60,'max_bytes':1024,'replay_complete':True,'truncated':False,'issues':[]},
            'tasks':[{'task_id':'t1','agent':'worker1','state':state,'delivery':'unknown','quality':'unreviewed','event_at':None,'submitted_at':None,'duration_seconds':None,'result':text,'error':None,'output_truncated':False,'transitions':[]}],
            'agents':[],'events':[]}


class BrowserRED(unittest.TestCase):
    def setUp(self):
        self.assertTrue(JS.is_file(),'missing planned feature: bin/_control_web_devbus.js')
        from playwright.sync_api import sync_playwright
        self.pw=sync_playwright().start()
        self.browser=self.pw.chromium.launch(headless=True)
        self.page=self.browser.new_page(viewport={'width':320,'height':640})
        self.page.set_content('<div id="root" class="devbus"></div>')
        if CSS.is_file():
            self.page.add_style_tag(path=str(CSS))
        self.page.add_script_tag(path=str(JS))
        self.addCleanup(self.pw.stop)
        self.addCleanup(self.browser.close)

    def mount(self,value):
        self.page.evaluate('''value=>{
          window.calls=[]; window.status=200; window.offline=false; window.value=value;
          window.handle=ControlDevbus.mount(document.querySelector('#root'),{intervalMs:25,
            fetch:async (url,opts)=>{calls.push({url:String(url),credentials:opts.credentials,cache:opts.cache});
              if(window.offline) throw Error("synthetic offline");
              return {ok:status===200,status,json:async()=>window.value};}});
        }''',value)
        self.page.wait_for_selector('[data-devbus-task="t1"]')

    def test_live_replace_filters_safe_text_and_mobile(self):
        self.mount(snapshot('<img src=x onerror="window.xss=true">'+'x'*1000))
        self.assertEqual(self.page.locator('#root img').count(),0)
        self.assertIsNone(self.page.evaluate('window.xss'))
        self.assertIn('<img',self.page.locator('#root').inner_text())
        self.page.evaluate('window.value.tasks[0].result="updated result"')
        self.page.wait_for_function('document.querySelector("#root").textContent.includes("updated result")')
        self.page.get_by_label('Задача',exact=True).fill('t1')
        self.page.get_by_label('Агент',exact=True).fill('worker1')
        self.page.wait_for_function('calls.some(c=>c.url.includes("task=t1")&&c.url.includes("agent=worker1"))')
        self.assertTrue(self.page.evaluate('calls.every(c=>c.credentials==="same-origin"&&c.cache==="no-store")'))
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=320'))
        self.page.evaluate('handle.stop()')
        count=self.page.evaluate('calls.length')
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate('calls.length'),count)

    def test_401_and_403_clear_content_and_stop_polling(self):
        for status in (401,403):
            with self.subTest(status=status):
                self.mount(snapshot('sensitive synthetic result'))
                self.page.evaluate('s=>window.status=s',status)
                self.page.wait_for_function('!document.querySelector("#root").textContent.includes("sensitive synthetic result")')
                count=self.page.evaluate('calls.length')
                self.page.wait_for_timeout(100)
                self.assertEqual(self.page.evaluate('calls.length'),count)

    def test_network_failure_keeps_old_data_with_connection_label(self):
        self.mount(snapshot('retained synthetic result'))
        self.page.evaluate('window.offline=true')
        self.page.wait_for_timeout(75)
        text=self.page.locator('#root').inner_text()
        self.assertIn('retained synthetic result',text)
        self.assertRegex(text.lower(),'нет связи|отключ|устар|потер')
