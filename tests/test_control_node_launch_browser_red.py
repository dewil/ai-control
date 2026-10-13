"""INV-NRUN-09: real app mobile nodes, pending recovery and lifecycle RED.

Every case proves worktree JS/CSS bytes through the actual HTTP fixture.
No replacement application, private DOM hooks, NATS, credentials or inference.
"""
import json
import time
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright
import node_launch_red_support as s


class NodeLaunchBrowserRed(s.HttpCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start(); cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True); cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        super().setUp(); self.prove_assets()
        self.context=self.browser.new_context(viewport={'width':390,'height':844},has_touch=True)
        self.addCleanup(self.context.close)
        name,value=self.fixture.cookie.split('=',1)
        self.context.add_cookies([dict(name=name,value=value,url=self.fixture.origin)])
        self.page=self.context.new_page(); self.page.set_default_timeout(1800)
        self.errors=[]; self.requests=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.on('request',lambda request:self.requests.append(request))
        self.addCleanup(lambda:self.assertEqual(self.errors,[]))

    def enter(self):
        self.page.goto(self.fixture.origin)
        button=self.page.get_by_role('button',name='Шина',exact=True).or_(self.page.get_by_role('tab',name='Шина',exact=True))
        expect(button).to_have_count(1,timeout=4000); button.click()
        expect(self.page.get_by_role('button',name='Новая задача',exact=True)).to_be_visible(timeout=4000)

    def open_form(self):
        self.page.get_by_role('button',name='Новая задача',exact=True).click()
        textarea=self.page.locator('textarea:visible'); expect(textarea).to_have_count(1)
        return textarea

    def node_requests(self,method=None):
        return [r for r in self.requests if urlsplit(r.url).path.startswith('/api/node-tasks') and (method is None or r.method==method)]

    def until(self,predicate,timeout=4):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline: self.page.wait_for_timeout(20)
        self.assertTrue(predicate(),'Expected public node UI lifecycle transition')

    def test_compact_mobile_fixed_profile_and_independent_states(self):
        self.enter()
        expect(self.page.get_by_text('Узлы',exact=True)).to_be_visible()
        expect(self.page.get_by_text('Задачи Control',exact=True)).to_be_visible()
        expect(self.page.get_by_text('Расход неизвестен',exact=False).first).to_be_visible()
        expect(self.page.get_by_text('ALP',exact=True).first).to_be_visible()
        for width in (320,390,412):
            self.page.set_viewport_size({'width':width,'height':844})
            self.assertLessEqual(self.page.evaluate('Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth'),1)
        self.page.set_viewport_size({'width':390,'height':844})
        button=self.page.get_by_role('button',name='Новая задача',exact=True)
        self.assertLess(button.bounding_box()['y'],600,'Compact node launch action should fit first mobile screen')
        textarea=self.open_form()
        expect(self.page.get_by_text('/home/dwl/alp-ai-study/diagnostic-context',exact=False).first).to_be_visible()
        textarea.fill('🙂'*5)
        expect(self.page.get_by_text('20',exact=False).first).to_be_visible()
        self.assertEqual(self.page.locator('input[name="model"],input[name="account"],input[name="path"]').count(),0)

    def test_new_task_preserves_exact_UTF8_prompt_and_commit_only_states(self):
        self.enter(); textarea=self.open_form(); prompt='  Synthetic audit\n🙂 preserve trailing space  '
        textarea.fill(prompt)
        self.page.get_by_role('button',name='Отправить',exact=True).click()
        self.until(lambda:any(row['op']=='submit' for row in self.backend.node_calls))
        call=next(row for row in self.backend.node_calls if row['op']=='submit')
        import uuid
        self.assertEqual(str(uuid.UUID(call['request_id'])),call['request_id'])
        self.assertEqual(call['prompt'],prompt); self.assertEqual(call['node_id'],'alp')
        self.assertEqual(len(self.node_requests('POST')),1)
        self.assertFalse(any('completed' in r.post_data if r.post_data else False for r in self.node_requests('POST')))

    def test_explicit_row_detail_safe_text_partial_and_quality(self):
        value=self.backend.node_values['overview']; value['tasks'][0].update(result_available=True,execution='completed',delivery='published',coverage='partial')
        detail=self.backend.node_values['get']; detail.update(execution='completed',delivery='published',coverage='partial',
            result={'text':'<img src=x onerror="window.nodeLaunchXss=1">','executor':'codex','output_truncated':True})
        self.enter()
        self.assertFalse(any(row['op']=='get' for row in self.backend.node_calls),'No unsolicited detail prefetch')
        self.page.get_by_text(s.PROMPT,exact=True).click()
        expect(self.page.get_by_text(detail['result']['text'],exact=True)).to_be_visible()
        self.assertIsNone(self.page.evaluate('window.nodeLaunchXss'))
        expect(self.page.get_by_text('Расход неизвестен',exact=False).first).to_be_visible()
        self.assertEqual(self.page.get_by_role('button',name='Отменить выполнение',exact=True).count(),0)

    def test_pending_reload_status404_and_explicit_retry_keep_immutable_UUID(self):
        captured=[]
        def lose_response(route):
            captured.append(json.loads(route.request.post_data)); route.abort('failed')
        self.page.route('**/api/node-tasks',lose_response)
        self.enter(); self.open_form().fill(s.PROMPT)
        self.page.get_by_role('button',name='Отправить',exact=True).click()
        expect(self.page.get_by_role('button',name='Повторить отправку',exact=True)).to_be_visible(timeout=5000)
        self.assertEqual(len(captured),1); first=captured[0]
        storage=self.page.evaluate('Object.values(sessionStorage)')
        self.assertTrue(any(first['request_id'] in value and s.PROMPT in value for value in storage),'Persist exact pending before network')
        self.page.reload(); self.enter()
        self.assertEqual(len(captured),1,'Reload must never auto POST pending')
        self.backend.node_values['get']={'error':'not_found'}
        self.page.get_by_role('button',name='Проверить статус',exact=True).click()
        self.until(lambda:any(row['op']=='get' and row['task_id']==first['request_id'] for row in self.backend.node_calls))
        self.assertEqual(len(captured),1,'404 must not create a new request ID or POST')
        self.page.get_by_role('button',name='Повторить отправку',exact=True).click()
        self.until(lambda:len(captured)==2)
        self.assertEqual(captured,[first,first])
        self.page.get_by_role('button',name='Выйти',exact=True).click()
        self.until(lambda:not any(first['request_id'] in value for value in self.page.evaluate('Object.values(sessionStorage)')))
        self.assertEqual(len(captured),2,'Logout must clear pending without POST')

    def test_tab_exit_aborts_late_node_reply_and_stops_poll(self):
        self.enter(); self.backend.node_gate.clear(); before=len(self.backend.node_calls)
        self.until(lambda:len(self.backend.node_calls)>before,timeout=7)
        self.page.get_by_role('button',name='Задачи',exact=True).or_(self.page.get_by_role('tab',name='Задачи',exact=True)).click()
        self.backend.node_values['overview']['node']['label']='STALE NODE RESPONSE MARKER'
        self.backend.node_gate.set(); self.page.wait_for_timeout(150)
        expect(self.page.get_by_text('STALE NODE RESPONSE MARKER',exact=True)).to_have_count(0)
        count=len(self.node_requests()); self.page.wait_for_timeout(5300)
        self.assertEqual(len(self.node_requests()),count,'Offscreen node overview timer must stop')

    def test_auth_loss_stops_nodes_without_replaying_mutation(self):
        self.enter()
        self.fixture.sessions.clear()
        self.until(lambda:self.page.get_by_role('button',name='Новая задача',exact=True).count()==0,timeout=7)
        count=len(self.node_requests()); self.page.wait_for_timeout(5300)
        self.assertEqual(len(self.node_requests()),count,'Auth failure must stop node polling')
        self.assertEqual(len(self.node_requests('POST')),0,'Auth loss cannot replay mutation')

    def test_hidden_background_suspends_node_requests_and_native_auth_bridge(self):
        self.page.add_init_script("window.nodeAuthCalls=[];window.AndroidAuth={requestAuth:(...args)=>window.nodeAuthCalls.push(args),requestLogout:()=>{}}")
        self.enter()
        before=self.page.evaluate('window.nodeAuthCalls.length')
        self.page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
        count=len(self.node_requests()); self.page.wait_for_timeout(5300)
        self.assertEqual(len(self.node_requests()),count,'Hidden page must not poll node API')
        self.assertEqual(self.page.evaluate('window.nodeAuthCalls.length'),before,'Background must not invoke native authentication')
        self.assertEqual(len(self.node_requests('POST')),0)
