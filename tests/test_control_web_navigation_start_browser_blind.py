"""Blind PIN08/QSTART07 browser acceptance; real local HTTP and rendered JS."""
from copy import deepcopy
import json
import re
from urllib.parse import urlsplit
import uuid
import unittest
from playwright.sync_api import expect
from control_browser_helpers import choose_project,project_is_selected
import live_sse_blind_support as live
import native_queue_blind_support as q
import navigation_start_blind_support as s
import test_control_web_native_queue_browser_blind as core

START=re.compile(r'Запустить.*очеред',re.I)
CONFIRM=re.compile(r'^(Подтвердить|Запустить|Запустить из очереди|Да, запустить)$',re.I)
PIN=re.compile(r'^Закрепить(?: сессию| чат)?$',re.I)
UNPIN=re.compile(r'Открепить|Удалить закрепление',re.I)

class NavigationBackend(core.BrowserQueueBackend):
    def __init__(self):
        super().__init__();self.pin_rows=[s.pin_item(),s.pin_item(q.OTHER,'other',q.OTHER,'Pinned synthetic B')]
        self.nav_calls=[];self.start_state='started';self.start_support=True;self.start_receipts={};self.start_receipt_scopes={};self.blocked_queue_ids={}
    def session_projects(self):return dict(projects=[dict(name='demo'),dict(name='other')])
    def session_project_summary(self):
        value=super().session_project_summary();value['projects'].append({**value['projects'][0],'name':'other'});return value
    def session_pins(self,principal):self.nav_calls.append(('pins',principal));return dict(schema=1,items=deepcopy(self.pin_rows))
    def session_pin(self,principal,project,sid):
        self.nav_calls.append(('pin',principal,project,sid))
        existing=next((row for row in self.pin_rows if row['project']==project and row['sid']==sid),None)
        if not existing:
            existing=s.pin_item(str(uuid.uuid4()),project,sid,'New pinned synthetic');self.pin_rows.insert(0,existing)
        return dict(schema=1,pin_id=existing['pin_id'],pinned=True)
    def session_unpin(self,principal,pin_id):
        self.nav_calls.append(('unpin',principal,pin_id));self.pin_rows=[row for row in self.pin_rows if row['pin_id']!=pin_id]
        return dict(schema=1,pin_id=pin_id,pinned=False)
    def session_queue_start_support(self,project,sid):
        self.nav_calls.append(('support',project,sid))
        blocked=set(self.blocked_queue_ids.get((project,sid),[]))
        blocked.update(result['queued_submission_id'] for action,result in self.start_receipts.items()
            if result['status']=='delivery_unknown' and self.start_receipt_scopes.get(action)==(project,sid))
        return dict(schema=1,supported=self.start_support,reason=None if self.start_support else 'not_idle',blocked_queue_ids=sorted(blocked))
    def session_queue_start(self,project,sid,qid,action):
        self.nav_calls.append(('start',project,sid,qid,action))
        result=dict(status=self.start_state,message_id=action,queued_submission_id=qid,turn_id=live.TURN if self.start_state=='started' else None,
                    reason=None if self.start_state=='started' else 'unavailable')
        self.start_receipts[action]=deepcopy(result);self.start_receipt_scopes[action]=(project,sid);return result
    def session_send_status(self,project,sid,mid):
        return deepcopy(self.start_receipts[mid]) if mid in self.start_receipts else super().session_send_status(project,sid,mid)

class NavigationStartBrowserBlind(unittest.TestCase):
    setUpClass=classmethod(core.NativeQueueBrowserBlind.setUpClass.__func__)
    until=core.NativeQueueBrowserBlind.until
    select=core.NativeQueueBrowserBlind.select
    tearDown=core.NativeQueueBrowserBlind.tearDown
    def setUp(self):
        core.NativeQueueBrowserBlind.setUp(self)
        fixture=NavigationBackend();self.backend.__class__=NavigationBackend
        self.backend.__dict__.update(fixture.__dict__)
        self.backend.queue_rows[live.SID]=[q.public_row('native-selected-row','mac-original-client','Selected current native queue text')]
    def navposts(self):return [r for r in self.requests if r[0]=='POST' and r[1] in ['/api/session-pin','/api/session-unpin','/api/session-queue-start']]
    def start_button(self):
        row=self.page.get_by_text('Selected current native queue text',exact=True)
        expect(row).to_have_count(1)
        button=row.locator('xpath=ancestor::*[.//button][1]').get_by_role('button',name=START)
        self.assertEqual(button.count(),1,'Selected idle native row needs separate queue-start action')
        return button
    def pins_title(self):
        title=self.page.get_by_text('Закреплённые',exact=True).first
        self.assertEqual(title.count(),1,'Global compact pins block missing');expect(title).to_be_visible();return title
    def pin_block(self):
        title=self.pins_title()
        block=title.locator('xpath=ancestor::*[self::details or self::section or @role="region"][1]')
        self.assertEqual(block.count(),1,'Pins need a bounded accessible block container');return block
    def dialog(self):
        self.start_button().click();dialog=self.page.get_by_role('dialog');expect(dialog).to_be_visible()
        self.assertEqual(dialog.get_attribute('aria-modal'),'true')
        return dialog
    def hidden(self):
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('pagehide'))")
    def visible(self):
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('pageshow'))")

    def test_pins_global_cross_project_reload_saved_title_and_compact_collapse(self):
        # INV-PIN-01 INV-PIN-07 INV-PIN-08
        self.select();block=self.pin_block()
        for text in ['Pinned synthetic A','Pinned synthetic B']:expect(block.get_by_text(text,exact=True)).to_be_visible()
        choose_project(self.page,'other');expect(block.get_by_text('Pinned synthetic A',exact=True)).to_be_visible()
        self.page.reload();self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        block=self.pin_block();expect(block.get_by_text('Pinned synthetic B',exact=True)).to_be_visible()
        for width in [320,360]:
            self.page.set_viewport_size(dict(width=width,height=900));box=block.bounding_box()
            self.assertIsNotNone(box);self.assertLessEqual(box['x']+box['width'],width+1);self.assertGreaterEqual(box['x'],-1)
            self.assertLessEqual(box['height'],260,'Two compact pinned rows consume excessive phone height')
            toggle=block.locator('summary').or_(block.get_by_role('button',name=re.compile('Закреплённые',re.I))).first
            self.assertEqual(toggle.count(),1,'Pins require persistent collapse toggle');toggle.click();expect(self.pins_title()).to_be_visible();toggle.click()
        block.get_by_text('Pinned synthetic B',exact=True).click()
        self.assertTrue(project_is_selected(self.page,'other'),'Pin must navigate to its own project')
        self.assertEqual(self.navposts(),[])

    def test_unavailable_pin_exports_generic_label_and_can_unpin(self):
        # INV-PIN-04 INV-PIN-05 INV-PIN-08
        self.backend.pin_rows=[s.pin_item(available=False)];self.select();block=self.pin_block()
        expect(block.get_by_text('Недоступная сессия',exact=True)).to_be_visible()
        self.assertNotIn(live.SID,block.inner_text());self.assertNotIn('demo',block.inner_text())
        button=block.get_by_role('button',name=UNPIN);self.assertEqual(button.count(),1);button.click()
        self.until(lambda:any(call[0]=='unpin' for call in self.backend.nav_calls))
        expect(block.get_by_text('Недоступная сессия',exact=True)).to_have_count(0)
        self.assertEqual([call for call in self.backend.nav_calls if call[0]=='unpin'],[('unpin','owner',q.MID)])
        self.assertEqual(len(self.navposts()),1)

    def test_initial_late_pins_preserve_composer_focus_and_stale_GET_cannot_restore_unpin(self):
        # INV-PIN-05 INV-PIN-08
        held=[];self.page.route('**/api/session-pins',lambda route:held.append(route))
        self.select();self.until(lambda:len(held)==1)
        composer=self.page.locator('textarea');composer.fill('Unsent navigation draft');composer.focus()
        held[0].fulfill(status=200,json=dict(schema=1,items=deepcopy(self.backend.pin_rows)))
        block=self.pin_block();expect(block.get_by_text('Pinned synthetic A',exact=True)).to_be_visible()
        self.assertEqual(composer.input_value(),'Unsent navigation draft');self.assertTrue(composer.evaluate('e=>e===document.activeElement'))
        self.page.unroute('**/api/session-pins');self.page.route('**/api/session-pins',lambda route:held.append(route))
        self.visible();self.until(lambda:len(held)>=2)
        block.get_by_text('Pinned synthetic A',exact=True).locator('xpath=ancestor::*[.//button][1]').get_by_role('button',name=UNPIN).click()
        self.until(lambda:any(call[0]=='unpin' for call in self.backend.nav_calls))
        held[1].fulfill(status=200,json=dict(schema=1,items=[s.pin_item()]))
        self.page.wait_for_timeout(100);expect(self.page.get_by_text('Pinned synthetic A',exact=True)).to_have_count(0)
        self.assertEqual(composer.input_value(),'Unsent navigation draft')

    def test_pin_from_current_selection_uses_exact_body_and_preserves_draft(self):
        # INV-PIN-02 INV-PIN-05 INV-PIN-08
        self.backend.pin_rows=[];self.select();self.pins_title()
        composer=self.page.locator('textarea');composer.fill('Draft before pin')
        button=self.page.get_by_role('button',name=PIN);self.assertGreater(button.count(),0,'Current/list session needs pin action');button.first.click()
        self.until(lambda:any(call[0]=='pin' for call in self.backend.nav_calls))
        posts=self.navposts();self.assertEqual(len(posts),1)
        body=json.loads(posts[0][2]);self.assertEqual(body,dict(project='demo',sid=live.SID))
        self.assertEqual(composer.input_value(),'Draft before pin')
        expect(self.pin_block().get_by_text('New pinned synthetic',exact=True)).to_be_visible()

    def test_current_native_confirmation_uuid_only_on_confirm_doubleclick_one_post_no_bubble(self):
        # INV-QSTART-02 INV-QSTART-07
        self.select();self.page.evaluate("window.startUUIDs=0;const nativeUUID=crypto.randomUUID.bind(crypto);crypto.randomUUID=()=>{startUUIDs++;return nativeUUID()};undefined")
        dialog=self.dialog();self.assertEqual(self.page.evaluate('startUUIDs'),0)
        expect(dialog.get_by_text(re.compile(r'текущ.*(?:верси|текст)|актуальн.*(?:верси|текст)',re.I)).first).to_be_visible()
        expect(dialog.get_by_text(re.compile(r'Mac|родн|нативн',re.I)).first).to_be_visible()
        expect(dialog.get_by_text('Selected current native queue text',exact=True)).to_be_visible()
        self.assertEqual(self.navposts(),[])
        composer=self.page.locator('textarea');composer.fill('Other unsent draft')
        held=[];self.page.route('**/api/session-queue-start',lambda route:held.append(route))
        confirm=dialog.get_by_role('button',name=CONFIRM);self.assertEqual(confirm.count(),1);confirm.dblclick()
        self.until(lambda:len(held)==1);body=held[0].request.post_data_json
        self.assertEqual(set(body),{'project','sid','queued_submission_id','action_id'})
        self.assertEqual((body['project'],body['sid'],body['queued_submission_id']),('demo',live.SID,'native-selected-row'))
        uuid.UUID(body['action_id']);self.assertEqual(self.page.evaluate('startUUIDs'),1)
        held[0].fulfill(status=200,json=dict(status='started',message_id=body['action_id'],queued_submission_id='native-selected-row',turn_id=live.TURN,reason=None))
        self.page.wait_for_timeout(100);self.assertEqual(len(self.navposts()),1)
        expect(self.page.get_by_text('Selected current native queue text',exact=True)).to_have_count(1)
        self.assertEqual(composer.input_value(),'Other unsent draft')

    def test_unknown_manual_status_reload_and_cancel_do_not_replay_start(self):
        # INV-QSTART-03 INV-QSTART-04 INV-QSTART-07
        self.backend.start_state='delivery_unknown';self.select()
        dialog=self.dialog();self.page.keyboard.press('Escape');expect(dialog).to_have_count(0)
        self.assertEqual(self.navposts(),[])
        dialog=self.dialog();dialog.get_by_role('button',name=CONFIRM).click()
        self.until(lambda:len([call for call in self.backend.nav_calls if call[0]=='start'])==1)
        expect(self.page.get_by_text(re.compile('неизвест|не подтверж|native|родн',re.I)).first).to_be_visible()
        self.assertEqual(self.start_button().is_enabled(),False,'Unknown qid must not offer another start')
        checks=self.page.get_by_role('button',name=re.compile('Проверить.*статус|Обновить.*статус',re.I))
        if checks.count():checks.first.click()
        self.select();self.page.wait_for_timeout(100)
        self.assertEqual(len([call for call in self.backend.nav_calls if call[0]=='start']),1)
        self.assertEqual(self.start_button().is_enabled(),False,'Reload must restore unknown guard for same qid')
        expect(self.page.get_by_text('Selected current native queue text',exact=True)).to_have_count(1)

    def test_hidden_android_suspend_no_new_support_pin_refresh_or_mutation_and_late_logout_ignored(self):
        # INV-PIN-08 INV-QSTART-07 INV-QSTART-08
        self.select();self.pins_title();self.start_button();self.page.clock.install()
        self.hidden();self.until(lambda:self.fixture.transport.closed>=1);before=len(self.requests)
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100)
        self.assertEqual(len(self.requests),before,'Hidden Android lifecycle started new foreground work')
        self.assertEqual(self.navposts(),[])
        self.visible();self.until(lambda:len(self.requests)>before)
        held=[];self.page.route('**/api/session-pins',lambda route:held.append(route));self.visible();self.until(lambda:len(held)>=1)
        logout=self.page.get_by_role('button',name=re.compile('Выйти|Выход',re.I));self.assertEqual(logout.count(),1);logout.click()
        held[0].fulfill(status=200,json=dict(schema=1,items=[s.pin_item(title='Late private pin after logout')]))
        self.page.wait_for_timeout(100);expect(self.page.get_by_text('Late private pin after logout',exact=True)).to_have_count(0)

    def test_pin_refresh_preserves_reader_node_and_scroll_anchor(self):
        # INV-PIN-08 INV-QSTART-07
        self.select();self.pins_title()
        history=live.history('Reader synthetic first')
        history['turns'][0]['items']=[dict(id='reader-'+str(i),role='assistant',text='Reader synthetic '+str(i)+'\n'+'long line\n'*12,
            truncated=False,timestamp=1770000000+i,time_precision='item') for i in range(24)]
        self.backend.value=history;self.fixture.transport.emit(live.snapshot(2,value=history))
        anchor=self.page.get_by_text(history['turns'][0]['items'][10]['text'],exact=True);expect(anchor).to_have_count(1)
        anchor.evaluate("e=>{e.scrollIntoView({block:'start'});window.pinnedReaderNode=e}")
        self.page.locator('textarea').fill('Reader retained unsent draft')
        anchor.evaluate("e=>e.scrollIntoView({block:'start'})");before=anchor.bounding_box()['y']
        self.backend.pin_rows.insert(0,s.pin_item(q.ACTION,'demo',live.THIRD,'New asynchronous pin'))
        self.visible();expect(self.page.get_by_text('New asynchronous pin',exact=True)).to_have_count(1)
        self.assertTrue(anchor.evaluate('e=>e===window.pinnedReaderNode'),'Pin refresh replaced reader node')
        self.assertLessEqual(abs(anchor.bounding_box()['y']-before),8,'Pin refresh moved reader anchor')
        self.assertEqual(self.page.locator('textarea').input_value(),'Reader retained unsent draft')

    def test_late_start_ACK_cannot_touch_other_selected_session(self):
        # INV-QSTART-06 INV-QSTART-07
        self.select();held=[];self.page.route('**/api/session-queue-start',lambda route:held.append(route))
        self.dialog().get_by_role('button',name=CONFIRM).click();self.until(lambda:len(held)==1)
        body=held[0].request.post_data_json
        self.page.get_by_role('button',name='LIVE synthetic B',exact=False).click()
        expect(self.page.get_by_text('Queue browser B history',exact=True)).to_have_count(1)
        self.page.locator('textarea').fill('B retained draft')
        held[0].fulfill(status=200,json=dict(status='started',message_id=body['action_id'],queued_submission_id='native-selected-row',turn_id=live.TURN,reason=None))
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.locator('textarea').input_value(),'B retained draft')
        expect(self.page.get_by_text('Selected current native queue text',exact=True)).to_have_count(0)
        self.assertEqual(len(self.navposts()),1)

    def test_unavailable_support_disables_only_new_start_keeps_native_queue(self):
        # INV-QSTART-01 INV-QSTART-07 INV-QSTART-08
        self.select();self.assertTrue(self.start_button().is_enabled())
        self.page.route('**/api/session-queue-start?*',lambda route:route.fulfill(status=404,json=dict(error='unavailable')))
        self.visible();self.page.wait_for_timeout(200)
        expect(self.page.get_by_text('Selected current native queue text',exact=True)).to_have_count(1)
        buttons=self.page.get_by_role('button',name=START)
        self.assertTrue(buttons.count()==0 or not buttons.first.is_enabled(),'Missing support endpoint must disable new action')
        self.assertEqual(self.navposts(),[])

    def test_native_Android_protocol2_suspension_blocks_pins_start_support_and_actions(self):
        # INV-PIN-08 INV-QSTART-07 INV-QSTART-08
        self.context=self.browser.new_context(viewport=dict(width=360,height=844),user_agent='Mozilla/5.0 Android SyntheticWebView AiControlLifecycle/2')
        self.addCleanup(self.context.close)
        name,value=self.fixture.cookie.split('=',1);self.context.add_cookies([dict(name=name,value=value,url=self.fixture.origin)])
        self.page=self.context.new_page();self.page.set_default_timeout(2500);self.requests=[]
        self.page.on('request',lambda r:self.requests.append((r.method,urlsplit(r.url).path,r.post_data)))
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.add_init_script('window.AndroidAuth={requestAuth:()=>{},requestLogout:()=>{}};')
        self.page.goto(self.fixture.origin)
        self.assertEqual(self.page.evaluate('aiControlAndroidLifecycleProtocol()'),2)
        self.assertEqual(self.page.evaluate('aiControlAndroidSuspend({protocol:2,serial:1})'),dict(protocol=2,action='suspend',serial=1,ok=True))
        self.assertTrue(self.page.evaluate('aiControlAndroidResume({protocol:2,serial:2,phase:"admit"})'))
        self.assertTrue(self.page.evaluate('aiControlAndroidResume({protocol:2,serial:3,phase:"activate",admissionSerial:2})'))
        self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        choose_project(self.page,'demo');self.page.get_by_role('button',name='LIVE synthetic A',exact=False).click()
        self.pins_title();self.start_button();self.page.clock.install()
        self.assertTrue(self.page.evaluate('aiControlAndroidSuspend({protocol:2,serial:4}).ok'))
        self.until(lambda:self.fixture.transport.closed>=1);before=len(self.requests)
        self.visible();self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100)
        self.assertEqual(len(self.requests),before,'Browser visibility bypassed native suspend and issued new requests')
        self.assertEqual(self.navposts(),[])
        self.assertTrue(self.page.evaluate('aiControlAndroidResume({protocol:2,serial:5,phase:"admit"})'))
        self.assertTrue(self.page.evaluate('aiControlAndroidResume({protocol:2,serial:6,phase:"activate",admissionSerial:5})'))
        self.until(lambda:len(self.requests)>before)
        self.assertEqual(self.navposts(),[])
