"""Independent INV-USN01..08 public browser RED; synthetic HTTP only.

Use unittest discovery/-m unittest; the main guard also executes tests directly.
No frontend private functions/state/IDs are used as acceptance oracles.
"""
from copy import deepcopy
import json
import re
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

import unified_navigator_blind_support as s


class UnifiedNavigatorBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s.pin_actual_app()
        cls.expected_assets = s.asset_digests()
        print('USN fixture root='+str(s.ROOT)+' HTTP asset expectations='+json.dumps(cls.expected_assets,sort_keys=True),flush=True)
        cls.pw = sync_playwright().start(); cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(headless=True); cls.addClassCleanup(cls.browser.close)
        if cls.browser.version != '153.0.8010.12':
            raise RuntimeError('Chromium153 fixture drift: explicit rebaseline, no skip')

    def setUp(self):
        with patch.object(s.live,'Backend',s.Backend):
            self.fixture = s.live.Fixture(transport=True,session_store=True)
        self.addCleanup(self.fixture.stop)
        self.fixture.login(); self.backend = self.fixture.backend
        self.context = self.browser.new_context(viewport=dict(width=1280,height=900))
        self.addCleanup(self.context.close)
        name,value = self.fixture.cookie.split('=',1)
        self.context.add_cookies([dict(name=name,value=value,url=self.fixture.origin)])
        self.page = self.context.new_page(); self.page.set_default_timeout(1600)
        self.page.clock.install()
        self.errors = []; self.requests = []; self.responses = []
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.on('request',lambda r:self.requests.append((r.method,r.url,r.post_data)))
        self.page.on('response',lambda r:self.responses.append((urlsplit(r.url).path,r.status)))
        # Each fixture must prove actual HTTP bytes, not just env/CWD or an unrelated server.
        for path,wanted in self.expected_assets.items():
            connection,response = self.fixture.request(path)
            self.assertEqual(response.status,200)
            body=response.read(); connection.close()
            self.assertEqual(s.hashlib.sha256(body).hexdigest(),wanted,'Wrong served '+path)
        for path in ('/api/participation-overview','/api/session-pins?activity=1',
                     '/api/session-projects','/api/sessions?project=demo&page=0'):
            connection,response = self.fixture.request(path)
            self.assertEqual(response.status,200,'Invalid frozen positive DTO '+path)
            json.loads(response.read()); connection.close()
        self.backend.reads.clear()

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.assertFalse(any(urlsplit(url).netloc != urlsplit(self.fixture.origin).netloc
                             for _,url,_ in self.requests),'Synthetic browser contacted outside origin')

    def until(self,predicate,message='Expected public navigator state',timeout=3):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:self.page.wait_for_timeout(20)
        self.assertTrue(predicate(),message)

    def enter(self,mobile=False):
        if mobile:self.page.set_viewport_size(dict(width=360,height=844))
        self.page.goto(self.fixture.origin)
        self.page.get_by_role('button',name='Сессии',exact=True).or_(
            self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        self.listing()
        self.until(lambda:any(c[0]=='overview' for c in self.backend.reads)
                   and any(c[0]=='pins' for c in self.backend.reads))
        # Late initial feeds may legitimately be pending after first hydration.
        # Explicitly apply before scenarios needing their complete known union.
        self.page.wait_for_timeout(60)
        self.apply()

    def listing(self):
        value=self.page.get_by_role('list',name=re.compile('Сессии',re.I)).or_(
            self.page.get_by_role('listbox',name=re.compile('Сессии',re.I)))
        expect(value).to_have_count(1)
        expect(value).to_be_visible()
        return value

    def rows(self):
        listing=self.listing()
        return listing.get_by_role('listitem').or_(listing.get_by_role('option'))

    def row(self,title):
        value=self.rows().filter(has_text=title)
        expect(value).to_have_count(1)
        return value

    def primary(self,title):
        value=self.row(title).get_by_role('button',name=re.compile('Открыть(?: сессию)?|'+re.escape(title),re.I))
        expect(value).to_have_count(1)
        return value

    def project(self):
        value=self.page.get_by_role('combobox',name=re.compile('Проект',re.I))
        expect(value).to_have_count(1)
        return value

    def all_projects(self):
        control=self.project()
        choices=control.locator('option').evaluate_all('es=>es.map(e=>({value:e.value,text:e.textContent}))')
        choice=next((c for c in choices if re.search(r'^Все(?: проекты)?$',c['text'].strip(),re.I)),None)
        self.assertIsNotNone(choice,'Project filter needs an explicit All option')
        control.select_option(choice['value'])

    def status(self,label):
        pattern=r'^(?:★|Закреплённые)(?:\s|[·(:]|$)' if label=='★' else '^'+re.escape(label)+r'(?:\s|[·(:]|$)'
        value=self.page.get_by_role('button',name=re.compile(pattern))
        expect(value).to_have_count(1)
        return value

    def count(self,label,number):
        self.assertRegex(self.status(label).get_attribute('aria-label') or self.status(label).inner_text(),
                         r'(?<!\d)'+str(number)+r'(?!\d)')

    def apply(self):
        button=self.page.get_by_role('button',name=re.compile(r'^Обновить список$|^Новые:\s*\d+'))
        self.assertGreater(button.count(),0,'Explicit snapshot apply control missing')
        button.first.click()

    def tick(self):
        before=sum(c[0]=='overview' for c in self.backend.reads)
        self.backend.overview['revision']+=1; self.backend.overview['generated_at']+=1
        self.page.clock.fast_forward(6000)
        self.until(lambda:sum(c[0]=='overview' for c in self.backend.reads)>before,
                   'Automatic public overview polling missing')
        self.page.wait_for_timeout(60)

    def no_writes(self):
        self.assertEqual(self.backend.writes,[])
        self.assertEqual([(method,urlsplit(url).path) for method,url,_ in self.requests
                          if method=='POST'],[],'Navigation submitted a mutation')

    def open_a(self):
        self.enter()
        self.primary(s.A_TITLE).click()
        expect(self.page.get_by_text(re.compile('Unified reader 10'))).to_be_visible()
        self.until(lambda:self.fixture.transport.streams>=1)
        self.page.locator('textarea').fill('Unified unsent draft A')
        self.chat_url=self.page.url
        self.assertEqual(parse_qs(urlsplit(self.chat_url).query),dict(project=['demo'],sid=[s.live.SID]))

    def test_USN01_union_dedup_authority_and_one_visible_list(self):
        self.enter()
        self.row(s.A_TITLE); self.row(s.READY_TITLE); self.row(s.C_TITLE)
        self.project().select_option('demo')
        self.until(lambda:('list','demo',0) in self.backend.reads)
        self.row(s.A_TITLE); self.row(s.READY_TITLE)
        self.assertEqual(self.row(s.A_TITLE).get_by_role('button',name=re.compile('Открыть',re.I)).count(),1)
        self.status('Все').click(); self.all_projects()
        for selector in ('#pin-list button','#participation-list button','#session-list button'):
            self.assertFalse(any(b.is_visible() for b in self.page.locator(selector).all()),
                             'Legacy controller produced duplicate visible navigation')
        self.no_writes()

    def test_USN02_03_frozen_membership_current_counts_pending_and_explicit_apply(self):
        self.enter(); self.status('Внимание').click(); self.row(s.A_TITLE)
        self.count('Внимание',1)
        self.backend.overview['rows'][0]=s.overview_row(s.live.SID,s.A_TITLE)
        self.backend.overview['rows'][1]=s.overview_row(s.live.OTHER,s.READY_TITLE,kind='attention')
        self.tick()
        expect(self.row(s.A_TITLE).get_by_text('Статус изменился',exact=True)).to_be_visible()
        expect(self.rows().filter(has_text=s.READY_TITLE)).to_have_count(0)
        self.count('Внимание',1)
        expect(self.page.get_by_role('button',name=re.compile(r'^Новые:\s*1'))).to_be_visible()
        self.apply()
        self.row(s.READY_TITLE)
        expect(self.rows().filter(has_text=s.A_TITLE)).to_have_count(0)
        self.no_writes()

    def test_USN03_order_stays_fixed_and_new_keys_do_not_insert_until_apply(self):
        self.enter(); self.row(s.A_TITLE); self.row(s.C_TITLE)
        self.apply()
        before=self.rows().all_text_contents()
        self.assertLess(next(i for i,t in enumerate(before) if s.C_TITLE in t),
                        next(i for i,t in enumerate(before) if s.A_TITLE in t))
        self.backend.overview['rows'][1]['result']['completed_at']=s.NOW-1
        self.backend.overview['rows'].append(s.overview_row(s.NEW,s.NEW_TITLE,kind='ready',index=0))
        self.tick()
        after=self.rows().all_text_contents()
        identify=lambda texts:[next(t for t in (s.C_TITLE,s.A_TITLE,s.READY_TITLE,s.WORK_TITLE) if t in row) for row in texts]
        self.assertEqual(identify(after),identify(before),'Background time/status reordered snapshot')
        expect(self.rows().filter(has_text=s.NEW_TITLE)).to_have_count(0)
        expect(self.page.get_by_role('button',name=re.compile(r'^Новые:\s*1'))).to_be_visible()
        self.apply(); self.row(s.NEW_TITLE)
        self.no_writes()

    def test_USN01_07_project_filter_late_B_after_C_preserves_chat_A_draft_URL(self):
        self.open_a()
        held=[]
        self.page.route(re.compile(r'/api/sessions\?'),lambda route:
            held.append(route) if parse_qs(urlsplit(route.request.url).query).get('project')==['bravo']
            else route.continue_())
        self.project().select_option('bravo'); self.until(lambda:len(held)==1)
        self.project().select_option('charlie')
        self.until(lambda:('list','charlie',0) in self.backend.reads)
        self.row(s.C_TITLE)
        held[0].fulfill(status=200,json=dict(rows=self.backend.pages['bravo'],has_more=False))
        self.page.wait_for_timeout(80)
        self.assertEqual(self.project().input_value(),'charlie')
        expect(self.rows().filter(has_text=s.B_TITLE)).to_have_count(0)
        self.assertEqual(self.page.url,self.chat_url)
        self.assertEqual(self.page.locator('textarea').input_value(),'Unified unsent draft A')
        expect(self.page.get_by_text(re.compile('Unified reader 10'))).to_be_visible()
        self.no_writes()

    def test_USN05_mobile_modal_focus_escape_backdrop_resize_preserve_chat(self):
        self.open_a(); self.page.set_viewport_size(dict(width=360,height=844))
        trigger=self.page.get_by_role('button',name=re.compile('^Сессии.*внимание|Открыть список сессий',re.I))
        expect(trigger).to_have_count(1); trigger.click()
        drawer=self.page.get_by_role('dialog',name=re.compile('Сессии',re.I))
        expect(drawer).to_be_visible()
        self.assertTrue(drawer.evaluate('e=>e.contains(document.activeElement)'))
        for _ in range(16):
            self.page.keyboard.press('Tab')
            self.assertTrue(drawer.evaluate('e=>e.contains(document.activeElement)'),'Modal focus escaped')
        self.page.keyboard.press('Escape'); expect(drawer).not_to_be_visible()
        self.assertTrue(trigger.evaluate('e=>e===document.activeElement'))
        self.assertEqual(self.page.locator('textarea').input_value(),'Unified unsent draft A')
        before=self.page.evaluate('document.scrollingElement.scrollHeight')
        trigger.click(); expect(drawer).to_be_visible()
        # Real backdrop hit: no private dialog-close function or forced dispatch.
        box=drawer.bounding_box()
        outside=next(((x,y) for x,y in ((1,1),(359,1),(1,843),(359,843))
            if not(box['x']<=x<=box['x']+box['width'] and box['y']<=y<=box['y']+box['height'])),None)
        self.assertIsNotNone(outside,'Mobile panel needs a real backdrop close surface')
        self.page.mouse.click(*outside); expect(drawer).not_to_be_visible()
        self.assertLessEqual(abs(self.page.evaluate('document.scrollingElement.scrollHeight')-before),3)
        trigger.click(); expect(drawer).to_be_visible()
        self.page.set_viewport_size(dict(width=1280,height=900))
        self.listing()
        self.assertFalse(self.page.locator('textarea').evaluate('e=>Boolean(e.closest("[inert]"))'))
        self.assertEqual(self.page.url,self.chat_url)
        self.no_writes()

    def test_USN06_desktop_sidebar_scroll_and_poll_do_not_move_chat_reader(self):
        self.backend.overview['rows']=[s.overview_row(s.live.SID,s.A_TITLE,kind='attention')]+[
            s.overview_row(f'{i:08x}-0000-4000-8000-{i:012x}','Long navigator row %03d'%i,index=i)
            for i in range(20,90)]
        self.open_a()
        reader=self.page.get_by_text(re.compile('Unified reader 10'))
        reader.evaluate("e=>e.scrollIntoView({block:'center'})")
        before=reader.bounding_box()['y']; listing=self.listing()
        scrollbox=listing.evaluate_handle('''e=>{for(let p=e;p;p=p.parentElement){
            const s=getComputedStyle(p);if(/auto|scroll/.test(s.overflowY)&&p.scrollHeight>p.clientHeight)return p;}return null;}''')
        self.assertTrue(scrollbox.evaluate('e=>Boolean(e)'),'Desktop sidebar needs its own scroll container')
        scrollbox.evaluate('e=>e.scrollTop=200')
        self.assertGreater(scrollbox.evaluate('e=>e.scrollTop'),0)
        self.backend.overview['rows'][2]['label']='Updated sidebar row'
        self.tick()
        self.assertLessEqual(abs(reader.bounding_box()['y']-before),3)
        self.assertEqual(scrollbox.evaluate('e=>e.scrollTop'),200)
        self.no_writes()

    def test_USN07_explicit_ready_target_opens_exact_history_without_native_write(self):
        self.enter(); row=self.row(s.READY_TITLE)
        row.get_by_role('button',name=re.compile('Действия|Меню',re.I)).click()
        action=self.page.get_by_role('menuitem',name=re.compile('Результат|Открыть результат',re.I)).or_(
            self.page.get_by_role('button',name='Открыть результат',exact=True))
        expect(action).to_have_count(1); action.click()
        expect(self.page.get_by_text('Unified exact final result',exact=True)).to_be_visible()
        self.assertIn(('history','demo',s.live.OTHER,None),self.backend.reads)
        self.assertEqual(parse_qs(urlsplit(self.page.url).query),dict(project=['demo'],sid=[s.live.OTHER]))
        self.no_writes()

    def test_USN01_07_redacted_pin_scrubs_old_identity_late_positive_cannot_restore(self):
        self.enter(); self.status('★').click(); self.row(s.C_TITLE)
        held=[]
        self.page.route(re.compile(r'/api/participation-overview(?:\?.*)?$'),lambda route:held.append(route))
        self.page.clock.fast_forward(6000); self.until(lambda:len(held)==1)
        redacted=s.pins.unknown(s.PIN_C,available=False)
        self.backend.pin_value=s.pins.dto([self.backend.pin_value['items'][0],redacted])
        self.backend.unavailable.add('charlie')
        # Existing user refresh/foreground reads, not a fabricated HTTP403 for all owner data.
        self.page.get_by_role('button',name=re.compile('Обновить проекты',re.I)).click()
        self.page.clock.fast_forward(31000)
        self.until(lambda:sum(c[0]=='pins' for c in self.backend.reads)>=2)
        expect(self.page.get_by_text(s.C_TITLE,exact=True)).to_have_count(0)
        late=deepcopy(self.backend.overview)
        late['rows'].append(s.overview_row(s.C,s.C_TITLE,'charlie',kind='attention'))
        held[0].fulfill(status=200,json=late); self.page.wait_for_timeout(80)
        expect(self.page.get_by_text(s.C_TITLE,exact=True)).to_have_count(0)
        self.assertNotIn(s.C,self.listing().inner_text())
        placeholder=self.rows().filter(has_text='Недоступная сессия'); expect(placeholder).to_have_count(1)
        self.assertEqual(placeholder.get_by_role('button',name=re.compile('Открыть',re.I)).count(),0)
        unpin=placeholder.get_by_role('button',name=re.compile('Открепить',re.I))
        if not unpin.count():
            placeholder.get_by_role('button',name=re.compile('Действия|Меню',re.I)).click()
            unpin=self.page.get_by_role('menuitem',name=re.compile('Открепить',re.I))
        unpin.click(); self.until(lambda:('unpin',s.PIN_C) in self.backend.writes)
        self.assertEqual(self.backend.writes,[('unpin',s.PIN_C)])

    def test_USN03_08_union_cap_overflow_is_partial_and_retains_visible_keys(self):
        rows=[s.overview_row(f'{i:08x}-0000-4000-8000-{i:012x}','Bounded row %03d'%i,index=i)
              for i in range(1,257)]
        self.backend.overview['rows']=rows; self.backend.pin_value=s.pins.dto([])
        self.enter(); self.apply(); self.assertEqual(self.rows().count(),256)
        before=self.rows().all_text_contents()
        self.backend.pin_value=s.pins.dto([s.pins.item(s.PIN_C,'charlie',s.C,s.C_TITLE)])
        pin_reads=sum(c[0]=='pins' for c in self.backend.reads)
        self.page.clock.fast_forward(31000)
        self.until(lambda:sum(c[0]=='pins' for c in self.backend.reads)>pin_reads)
        self.assertLessEqual(self.rows().count(),256)
        expect(self.page.get_by_text(re.compile('усеч|огранич|непол|частич|partial|truncat',re.I)).first).to_be_visible()
        self.assertEqual(self.rows().all_text_contents(),before,
                         'A visible snapshot key was displaced by background overflow')
        self.apply(); self.assertLessEqual(self.rows().count(),256)
        self.assertTrue(all(c[2]==0 for c in self.backend.reads if c[0]=='list'),
                        'Navigator walked pages without explicit pagination')

    def test_USN07_create_target_B_cancel_and_late_success_preserve_chat_A(self):
        self.open_a()
        self.project().select_option('bravo')
        self.page.get_by_role('button',name=re.compile('Создать.*сесси|Новая сессия',re.I)).click()
        dialog=self.page.get_by_role('dialog',name=re.compile('Созда|Новая сессия',re.I))
        expect(dialog).to_be_visible()
        target=dialog.get_by_role('combobox',name=re.compile('Проект',re.I))
        expect(target).to_have_count(1); self.assertEqual(target.input_value(),'bravo')
        self.until(lambda:('create-options','bravo') in self.backend.reads)
        self.assertEqual(self.page.url,self.chat_url)
        self.page.keyboard.press('Escape'); expect(dialog).not_to_be_visible()
        self.assertEqual(self.page.locator('textarea').input_value(),'Unified unsent draft A')
        self.page.get_by_role('button',name=re.compile('Создать.*сесси|Новая сессия',re.I)).click()
        held=[]; self.page.route('**/api/session-create',lambda route:held.append(route))
        dialog.get_by_role('button',name=re.compile('^Создать(?: сессию)?$')).click()
        self.until(lambda:len(held)==1)
        body=held[0].request.post_data_json
        self.assertEqual(set(body),{'project','operation_id','context_mode','provider_id'})
        self.assertEqual((body['project'],body['context_mode'],body['provider_id']),('bravo','configured','codex'))
        self.page.keyboard.press('Escape')
        held[0].fulfill(status=200,json=dict(operation_id=body['operation_id'],status='accepted',
            session=dict(sid=s.NEW,project='bravo',vendor='codex',context_mode='configured',title='Created Bravo')))
        self.page.wait_for_timeout(80)
        self.assertEqual(self.page.url,self.chat_url)
        self.assertEqual(self.page.locator('textarea').input_value(),'Unified unsent draft A')
        self.assertEqual(len([r for r in self.requests if r[0]=='POST' and urlsplit(r[1]).path=='/api/session-create']),1)
        self.assertFalse(any(r[0]=='POST' and urlsplit(r[1]).path not in ('/api/session-create',)
                             for r in self.requests))


if __name__ == '__main__':
    unittest.main()
