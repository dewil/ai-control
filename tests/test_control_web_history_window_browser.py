"""Independent INV-WSESS-22/23 DOM-window acceptance; synthetic local backend only."""
# Accepted INV-WSESS-47 (2026-10-08-spec-live-observability-package.md):
# bottom navigation remains reachable through the explicit compact disclosure.

import datetime
from control_live_legacy_fixture import LiveHistoryFixture, replay_path, observe_snapshots
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
from control_browser_helpers import choose_project
from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET, SID

ROOT = Path(__file__).resolve().parents[1]
NOW = 1791248400  # 2026-10-06 01:00 UTC; Moscow04:00.
OTHER = '44444444-4444-4444-8444-444444444444'
CURSOR = 'opaque/native-before/界?part=128'

def fixture(count=101, first=0):
    return {'count':count,'first':first,'delay':0,'older_mode':'normal'}

def history_items(first,count,prefix='MAIN'):
    return [{'id':f'{prefix}-item-{i}', 'role':'user' if i%2 else 'assistant',
             'text':f'{prefix} item {i:04d} turn-{i//8} {prefix}-item-{i}', 'truncated':False,
             'timestamp':NOW-i, 'time_precision':'turn'} for i in range(first,first+count)]


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root/'bin'))
    web = importlib.import_module('_control_web')
    # INV-WSESS-53: actual public LIVE backend replaces legacy automatic polling.
    class Backend(LiveHistoryFixture):
        _live_evidence = evidence
        def snapshot(self): return {'tasks': []}
        def answer(self, *args): return {'error': 'unavailable'}
        def verdict(self, *args): return {'error': 'unavailable'}
        def session_projects(self): return {'projects': [{'name': 'demo'},{'name':'alternate'}]}
        def session_list(self, *args):
            return {'rows': [{'sid': SID, 'title':'Alternate synthetic session' if args and args[0]=='alternate' else 'Window synthetic session','status':'idle'},
                             {'sid': OTHER,'title':'Other synthetic session','status':'idle'}], 'has_more':False}
        def session_history(self, project, sid, cursor):
            data=json.loads((evidence/'control.json').read_text())
            with (evidence/'calls.jsonl').open('a') as handle:
                handle.write(json.dumps({'sid':sid,'cursor':cursor})+'\n')
            time.sleep(data.get('delay',0) if sid==SID else 0)
            if project=='alternate':
                items=history_items(0,2,'ALT'); next_cursor=None
            elif sid==OTHER:
                items=history_items(0,2,'OTHER'); next_cursor=None
            elif cursor is None:
                if data.get('latest_mode')=='error': return {'error':'unavailable'}
                items=history_items(data.get('first',0),data.get('count',101)); next_cursor=CURSOR
            else:
                if cursor!=CURSOR: return {'error':'unavailable'}
                mode=data.get('older_mode','normal')
                if mode=='error': return {'error':'unavailable'}
                items=[] if mode=='empty' else history_items(-128,128)
                next_cursor=CURSOR if mode in ('cycle','empty') else None
            if data.get('repeat_ids'):
                for index,item in enumerate(items):
                    item['id']='repeated-item-'+str(index%8)
                    item['text']=item['text'].rsplit(' ',1)[0]+' '+item['id']
            groups=[]
            for offset in range(0,len(items),8):
                groups.append({'id':items[offset]['text'].split()[3],'status':'completed','items':items[offset:offset+8]})
            # Public history API retains descending native turn order;
            # each turn's items stay chronological (FR-WSESS-01).
            return {'turns':list(reversed(groups)),'next_cursor':next_cursor,'truncated':False,
                    'recent_sends':[{'status':'accepted','message_id':'22222222-2222-4222-8222-222222222222','turn_id':SID},
                                    {'status':'delivery_unknown','message_id':'55555555-5555-4555-8555-000000000001','turn_id':None}]}
        def session_send(self, *args): return {'error': 'unavailable'}
        def session_send_status(self, *args): return {'error': 'stale'}
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0)); listener.listen(128)
    origin = 'http://127.0.0.1:'+str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD), 'totp_secret': SECRET,
                          'session_ttl': 3600, 'secure_cookie': False, 'totp_state_path': replay_path(evidence)}, Backend())
    private_json(evidence/'ready.json', {'url': origin})
    uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[listener])


class HistoryWindowBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        os.umask(0o077)
        cls.tmp = tempfile.TemporaryDirectory(prefix='control-history-window-', dir='/var/tmp')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.evidence = Path(cls.tmp.name)
        private_json(cls.evidence/'control.json', fixture())
        python = os.environ.get('CONTROL_HISTORY_WINDOW_SERVER_PYTHON', sys.executable)
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
        executable=os.environ.get('CONTROL_HISTORY_WINDOW_BROWSER_EXECUTABLE')
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
        private_json(self.evidence/'control.json', fixture())
        self.page=self.context.new_page(); self.addCleanup(self.page.close)
        self.live_frames=observe_snapshots(self.page)
        self.network=[]; self.errors=[]
        self.page.on('request',lambda r:self.network.append((r.method,r.url)))
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.goto(self.url)
        self.page.get_by_role('button',name=re.compile('^Сессии$',re.I)).or_(self.page.get_by_role('tab',name=re.compile('^Сессии$',re.I))).click()
        choose_project(self.page,'demo')
        self.session=self.page.get_by_role('button',name=re.compile('Window synthetic session'))
        self.session.wait_for()

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.assertFalse(any(method in ('DELETE','PUT','PATCH') for method,url in self.network),
                         'Window navigation cannot mutate/delete native history')
        self.assertFalse(any(url.split('/')[2]!=self.url.split('/')[2] for _,url in self.network))

    def configure(self, **changes):
        data=fixture(); data.update(changes)
        private_json(self.evidence/'control.json',data)

    def open(self):
        self.session.click()
        self.page.get_by_text(re.compile(r'^MAIN item ')).first.wait_for()

    def texts(self):
        return self.page.locator('.chat-items').get_by_text(re.compile(r'^MAIN item [-\d]+ turn-')).all_text_contents()

    def ids(self):
        return [int(re.search(r'MAIN item ([-\d]+)',text).group(1)) for text in self.texts()]

    def cap(self):
        ids=self.ids()
        self.assertLessEqual(len(ids),100,'INV-WSESS-22 current DOM must have at most100 text bubbles')
        self.assertEqual(ids,sorted(set(ids)),'Rendered full identities remain unique and chronological')
        self.assertEqual(self.page.locator('.chat-items article.chat-message').count(),len(ids))
        self.assertTrue(self.page.locator('.chat-items > li.turn').evaluate_all(
            'groups=>groups.every(group=>group.querySelectorAll("article.chat-message").length>0)'),
            'Empty turngroups must not leave orphan turn-status headings')
        self.assertEqual(self.page.locator('.chat-items time').count(),len(ids),'Turn-start time labels survive every window')
        return ids

    def requests(self):
        return [r for r in self.network if '/api/session-history?' in r[1]]

    def older(self):
        button=self.page.get_by_role('button',name='Загрузить более старые сообщения',exact=True)
        self.assertEqual(button.count(),1)
        return button

    def activate_older(self):
        self.older().evaluate('button=>button.click()')
        self.page.wait_for_timeout(150)

    def reader(self):
        messages=self.page.locator('.chat-items').get_by_text(re.compile(r'^MAIN item '))
        messages.nth(2).evaluate("el=>el.scrollIntoView({block:'start'})")
        self.page.wait_for_timeout(100)
        value=self.page.evaluate('''() => {const items=[...document.querySelector('.chat-items').querySelectorAll('p')].filter(el=>/^MAIN item /.test(el.textContent));const visible=items.filter(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight});const el=visible[0];window.windowTestAnchor=el;return el&&{text:el.textContent,top:el.getBoundingClientRect().top};}''')
        self.assertIsNotNone(value,'Synthetic reader must expose visible anchor')
        return value

    def assert_anchor(self, anchor, same_node=False):
        node=self.page.get_by_text(anchor['text'],exact=True)
        self.assertEqual(node.count(),1,'Reader overlap must remain in the visible window')
        self.assertLessEqual(abs(node.bounding_box()['y']-anchor['top']),8)
        if same_node:
            self.assertTrue(self.page.evaluate('windowTestAnchor.isConnected'),'Polling must preserve reader DOM node')

    def latest(self):
        button=self.page.get_by_role('button',name='К последним сообщениям',exact=True)
        button.evaluate('button=>button.click()'); self.page.wait_for_timeout(150)

    def refresh_latest(self):
        # INV-WSESS-53 removes automatic legacy /session-history polling.
        # Only failed-latest result cases exercise explicit refresh.
        with self.page.expect_response(lambda response:'/api/session-history?' in response.url):
            self.page.get_by_role('button',name='Обновить переписку',exact=True).evaluate('button=>button.click()')
        self.page.wait_for_function("()=>!document.querySelector('#chat-refresh').disabled",timeout=6000)

    def poll(self, count):
        # INV-WSESS-53: observe real owner→SSE updates, no legacy GET timer.
        before=list(self.requests())
        self.configure(count=count)
        target='MAIN item '+str(count-1).zfill(4)+' '
        def received():
            return any(any(item['text'].startswith(target) for turn in frame['history'].get('turns',[]) for item in turn['items']) for frame in self.live_frames)
        deadline=time.monotonic()+6
        while not received() and time.monotonic()<deadline:
            self.page.wait_for_timeout(50)
        self.assertTrue(received(),'Actual native SSE delivers the correlated new count')
        self.page.wait_for_function("target=>[...document.querySelectorAll('.chat-items p')].some(p=>p.textContent.startsWith(target))||[...document.querySelectorAll('button')].some(b=>/Есть новые сообщения|Перейти к последним/.test(b.textContent))",arg=target,timeout=6000)
        self.assertEqual(self.requests(),before,'Automatic update cannot issue legacy history GET')

    def test_initial_101_keeps_newest100_and_unchanged_draft_receipt_and_times(self):
        self.open()
        self.assertEqual(self.cap(),list(range(1,101)))
        self.page.locator('textarea').fill('Synthetic retained draft')
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic retained draft')
        self.assertFalse(any(method=='POST' and 'session-send' in url for method,url in self.network))

    def test_initial_1000_keeps_newest100_chronological_full_ids(self):
        self.configure(count=1000); self.open()
        self.assertEqual(self.cap(),list(range(900,1000)))
        # Empty turngroups must not leave empty headings/containers; public
        # history text and native time count already exclude hidden bubbles.
        self.assertNotIn('MAIN item 0899',self.page.locator('.chat-items').inner_text())

    def test_older_loaded_cache_is_local_then_exact_cursor_and_all128_page_items_reachable(self):
        self.configure(count=1000); self.open(); self.cap()
        seen=set(self.ids()); fetched=False
        for _ in range(30):
            if not self.older().is_enabled(): break
            before=list(self.requests()); prior=self.ids(); anchor=self.reader()
            self.activate_older(); current=self.cap(); seen.update(current)
            self.assert_anchor(anchor)
            if len(self.requests())>len(before):
                from urllib.parse import parse_qs,urlsplit
                cursors=[parse_qs(urlsplit(url).query).get('cursor',[None])[0] for _,url in self.requests()[len(before):]]
                self.assertEqual(cursors,[CURSOR],'Only exact opaque continuation may fetch at cache boundary')
                fetched=True
            elif min(prior)>0:
                self.assertLess(min(current),min(prior),'Older must expose hidden earlier loaded items locally')
            if set(range(-128,1000))<=seen: break
        self.assertTrue(fetched)
        self.assertEqual(seen,set(range(-128,1000)),'Every hidden slice of the128-item native page remains reachable')
        self.assertFalse(self.older().is_enabled())

    def test_same_item_id_in_distinct_turns_remains_distinct_full_identity(self):
        self.configure(count=101,repeat_ids=True); self.open()
        self.assertEqual(self.cap(),list(range(1,101)))
        self.assertTrue(all('repeated-item-' in text for text in self.texts()))

    def test_bottom_and_latest_choose_newest100_without_fetch_after_older(self):
        self.configure(count=1000); self.open(); self.cap()
        receipt=self.page.locator('details > summary').filter(has_text=re.compile('Проблемы доставки'))
        self.assertEqual(receipt.count(),1)
        receipt_text=receipt.inner_text()
        self.page.locator('textarea').fill('Synthetic window draft')
        self.reader(); self.activate_older()
        before=list(self.requests()); self.latest()
        self.assertEqual(self.cap(),list(range(900,1000))); self.assertEqual(self.requests(),before)
        self.reader(); self.activate_older()
        before=list(self.requests())
        bottom=self.page.get_by_role('button',name='↓ В конец',exact=True,include_hidden=True)
        for summary in bottom.last.locator('xpath=ancestor::details[not(@open)]/summary').all():
            summary.click()
        self.assertTrue(bottom.first.is_visible()); self.assertTrue(bottom.last.is_visible())
        self.assertEqual(bottom.count(),2); bottom.first.evaluate('button=>button.click()')
        self.page.wait_for_timeout(150)
        self.assertEqual(self.cap(),list(range(900,1000))); self.assertEqual(self.requests(),before)
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic window draft')
        self.assertEqual(receipt.inner_text(),receipt_text,'Local navigation cannot clear existing UUID receipt evidence')
        self.assertFalse(any(method=='POST' for method,url in self.network))
        metrics=self.page.evaluate('({gap:document.scrollingElement.scrollHeight-innerHeight-scrollY})')
        self.assertLessEqual(metrics['gap'],8)

    def test_incoming_reader_freezes_window_nodes_anchor_draft_then_accessible_latest(self):
        self.open(); self.cap(); anchor=self.reader(); prior=self.ids()
        self.page.locator('textarea').fill('Synthetic retained draft')
        # Filling may scroll; put reader back at the captured viewport position.
        self.page.get_by_text(anchor['text'],exact=True).evaluate('(el,y)=>scrollBy(0,el.getBoundingClientRect().top-y)',anchor['top'])
        self.poll(104)
        self.assertEqual(self.cap(),prior); self.assert_anchor(anchor,True)
        self.assertEqual(self.page.locator('textarea').input_value(),'Synthetic retained draft')
        pending=self.page.get_by_role('button',name=re.compile('Есть новые сообщения|Перейти к последним',re.I))
        self.assertGreater(pending.count(),0,'New cached items need an accessible pending-latest action')
        before=list(self.requests()); pending.first.evaluate('button=>button.click()'); self.page.wait_for_timeout(150)
        self.assertEqual(self.cap(),list(range(4,104))); self.assertEqual(self.requests(),before)

    def test_incoming_focused_bubble_preserves_node_focus_selection_and_window(self):
        self.open(); self.cap(); prior=self.ids()
        control=self.page.locator('.chat-items time').first.locator('xpath=ancestor-or-self::*[@tabindex="0" or self::button or self::summary][1]')
        if not control.count():
            control=self.page.locator('.chat-items').locator('summary,button,[tabindex="0"]').first
        self.assertGreater(control.count(),0,'Timestamp bubble has existing keyboard focus control')
        control.focus()
        self.page.evaluate('''() => {window.windowTestFocus=document.activeElement;const p=document.querySelector('.chat-items p');const r=document.createRange();r.selectNodeContents(p);const selection=getSelection();selection.removeAllRanges();selection.addRange(r);window.windowTestSelection=selection.toString();scrollTo(0,document.scrollingElement.scrollHeight);}''')
        self.page.wait_for_timeout(100)
        self.assertLessEqual(self.page.evaluate('document.scrollingElement.scrollHeight-innerHeight-scrollY'),8)
        self.poll(104)
        self.assertEqual(self.cap(),prior)
        self.assertTrue(self.page.evaluate('windowTestFocus.isConnected&&document.activeElement===windowTestFocus&&getSelection().toString()===windowTestSelection'))
        before=list(self.requests()); self.latest()
        self.assertEqual(self.cap(),list(range(4,104)))
        self.assertEqual(self.requests(),before,'Correlated new items were cached by SSE')

    def test_incoming_older_window_stays_frozen_until_explicit_latest(self):
        self.configure(count=1000); self.open(); self.cap(); self.reader(); self.activate_older()
        prior=self.ids(); anchor=self.reader()
        self.poll(1003)
        self.assertEqual(self.cap(),prior); self.assert_anchor(anchor,True)
        before=list(self.requests()); self.latest()
        self.assertEqual(self.cap(),list(range(903,1003))); self.assertEqual(self.requests(),before)

    def test_follow_bottom_incoming_slides_to_newest100(self):
        self.open(); self.cap(); self.latest(); self.poll(104)
        self.assertEqual(self.cap(),list(range(4,104)))
        self.assertLessEqual(self.page.evaluate('document.scrollingElement.scrollHeight-innerHeight-scrollY'),8)

    def test_late_history_cannot_replace_new_session_window(self):
        self.configure(count=1000,delay=1)
        self.session.click()
        self.page.get_by_role('button',name=re.compile('Other synthetic session')).click()
        self.page.get_by_text(re.compile('^OTHER item ')).first.wait_for()
        self.page.wait_for_timeout(1400)
        self.assertEqual(self.ids(),[])
        self.assertEqual(self.page.locator('.chat-items').get_by_text(re.compile('^OTHER item ')).count(),2)
        # Reopening starts a new selection's own latest window, not stale Older.
        self.configure(count=101); self.session.click()
        self.page.get_by_text(re.compile('^MAIN item ')).first.wait_for()
        self.assertEqual(self.cap(),list(range(1,101)))

    def test_older_error_never_claims_exhausted_end(self):
        self.open(); self.cap(); self.reader(); self.activate_older()
        self.configure(older_mode='error')
        # The101-item cache has one hidden item; first Older is local, next
        # crosses to the native cursor. Error must retain current window.
        prior=self.ids(); self.activate_older()
        self.assertEqual(self.cap(),prior)
        self.assertRegex(self.page.locator('body').inner_text(),r'(?i)ошиб|не удалось|недоступ|повтор')
        self.assertTrue(self.older().is_enabled(),'A failed continuation is not native end')

    def test_failed_latest_refresh_keeps_cached_older_navigation_available(self):
        self.configure(count=1000); self.open(); self.assertEqual(self.cap(),list(range(900,1000)))
        self.configure(count=1000,latest_mode='error')
        before=list(self.requests())
        self.refresh_latest()
        self.assertGreater(len(self.requests()),len(before),'Fixture must observe the failed latest refresh')
        self.assertRegex(self.page.locator('body').inner_text(),r'(?i)ошиб|не удалось|недоступ|повтор')
        before=list(self.requests()); prior=self.ids()
        self.activate_older()
        current=self.cap()
        self.assertLess(min(current),min(prior),'Cached Older navigation must progress after refresh failure')
        self.assertTrue(set(prior)&set(current),'Cached Older keeps an overlap with the readable window')
        self.assertEqual(self.requests(),before,'Cached Older navigation must not retry the failed request')
        self.assertRegex(self.page.locator('body').inner_text(),r'(?i)ошиб|не удалось|недоступ|повтор')

    def test_failed_latest_refresh_still_allows_explicit_opaque_older_continuation(self):
        from urllib.parse import parse_qs,urlsplit
        self.configure(count=101); self.open()
        self.assertEqual(self.cap(),list(range(1,101)))
        self.configure(count=101,latest_mode='error')
        before=list(self.requests())
        self.refresh_latest()
        after_failure=list(self.requests())
        self.assertGreater(len(after_failure),len(before),'Fixture must observe an actual failed latest GET')
        self.assertEqual([parse_qs(urlsplit(url).query).get('cursor',[None])[0]
                          for _,url in after_failure[len(before):]],[None],
                         'The failed latest refresh uses the existing null cursor')
        error_pattern=r'(?i)ошиб|не удалось|недоступ|повтор'
        self.assertRegex(self.page.locator('body').inner_text(),error_pattern)

        # The hidden item0 is still cached: explicit Older must reveal it locally.
        before_local=list(self.requests())
        self.activate_older()
        local=self.cap()
        self.assertLess(min(local),1)
        self.assertEqual(self.requests(),before_local,'Cached Older must not call the backend')
        self.assertRegex(self.page.locator('body').inner_text(),error_pattern,
                         'The latest endpoint failure remains visible after local navigation')

        # At the cache boundary, another explicit Older may use only CURSOR.
        before_cursor=list(self.requests())
        self.activate_older()
        deadline=time.monotonic()+3
        while len(self.requests())==len(before_cursor) and time.monotonic()<deadline:
            self.page.wait_for_timeout(50)
        current=self.cap()
        cursor_requests=self.requests()[len(before_cursor):]
        self.assertEqual([parse_qs(urlsplit(url).query).get('cursor',[None])[0]
                          for _,url in cursor_requests],[CURSOR],
                         'Older must send the exact opaque continuation once it reaches the cache boundary')
        negatives=[value for value in current if value<0]
        self.assertTrue(negatives,'Successful continuation must expose earlier native items')
        self.assertTrue(all(value<1 for value in negatives))
        self.assertEqual(negatives,list(range(min(negatives),0)),
                         'Negative earlier items remain contiguous before zero')
        self.assertTrue(all(b-a==1 for a,b in zip(current,current[1:])),
                        'The entire earlier window remains contiguous without a cached gap')
        self.assertLessEqual(len(current),100)
        self.assertEqual(current,sorted(set(current)))
        self.assertRegex(self.page.locator('body').inner_text(),error_pattern,
                         'Older success does not clear the latest endpoint failure')

        # Allow more than one poll interval: no implicit latest retry follows Older success.
        after_older=list(self.requests())
        self.page.wait_for_timeout(5600)
        self.assertEqual(self.requests(),after_older,
                         'Latest failure cannot trigger an automatic retry after Older succeeds')
        self.assertRegex(self.page.locator('body').inner_text(),error_pattern)

    def test_extreme_reader_anchor_yields_contiguous_progressing_older_windows(self):
        self.configure(count=1000); self.open(); self.assertEqual(self.cap(),list(range(900,1000)))
        anchor_text='MAIN item 0999 turn-124 MAIN-item-999'
        anchor_node=self.page.get_by_text(anchor_text,exact=True)
        anchor_article=anchor_node.locator('xpath=ancestor::article')
        anchor_article.evaluate("el=>el.style.minHeight='1100px'")
        anchor_node.evaluate("el=>el.scrollIntoView({block:'start'})")
        self.page.wait_for_timeout(100)
        visible=self.page.evaluate('''() => [...document.querySelectorAll('.chat-items article.chat-message')]
            .map(el=>({text:el.querySelector('p')?.textContent,top:el.getBoundingClientRect().top,bottom:el.getBoundingClientRect().bottom}))
            .filter(item=>item.top<innerHeight&&item.bottom>0).sort((a,b)=>a.top-b.top)''')
        self.assertTrue(visible and visible[0]['text']==anchor_text,
                        'Synthetic reader must capture bubble 999 first; visible='+repr(visible[:2]))
        before=list(self.requests())
        self.activate_older()
        first=self.cap()
        self.assertEqual(first,list(range(801,901)),'When preserving the extreme anchor blocks progress, Older must use boundary overlap')
        self.assertEqual(self.requests(),before,'Both older windows are already cached')
        self.activate_older()
        second=self.cap()
        self.assertLess(min(second),min(first),'A repeated Older action must continue to earlier history')
        self.assertEqual(second,sorted(set(second)),'Repeated Older remains chronological and unique')
        self.assertTrue(all(b-a==1 for a,b in zip(second,second[1:])),'Repeated Older must not expose an arbitrary cached gap')
        self.assertTrue(set(first)&set(second),'Repeated Older retains its reachable boundary overlap')
        self.assertEqual(self.requests(),before,'Cached Older must not fabricate a cursor or fetch a cached gap')

    def test_cycle_or_empty_continuation_does_not_erase_readable_window_or_loop(self):
        for mode in ('cycle','empty'):
            with self.subTest(mode=mode):
                self.configure(older_mode=mode)
                self.open(); self.cap(); self.reader(); self.activate_older()
                prior=self.ids(); before=len(self.requests())
                self.activate_older()
                current=self.cap()
                self.assertTrue(current,'An unresolved native continuation cannot erase known history')
                self.assertTrue(set(prior)&set(current),'Gap/cycle keeps readable overlap')
                self.assertLessEqual(len(self.requests())-before,2,'Cycle/empty cursor cannot trigger an unbounded fetch loop')
                self.assertRegex(self.page.locator('body').inner_text(),r'(?i)ошиб|не удалось|недоступ|повтор|разрыв|частич|пробел')

    def test_project_switch_same_sid_is_a_new_window_generation(self):
        self.configure(count=1000,delay=1); self.session.click()
        choose_project(self.page,'alternate')
        self.page.get_by_role('button',name=re.compile('Alternate synthetic session')).click()
        self.page.get_by_text(re.compile('^ALT item ')).first.wait_for()
        self.page.wait_for_timeout(1400)
        self.assertEqual(self.ids(),[])
        self.assertEqual(self.page.locator('.chat-items').get_by_text(re.compile('^ALT item ')).count(),2)
        self.configure(count=101); choose_project(self.page,'demo')
        self.page.get_by_role('button',name=re.compile('Window synthetic session')).click()
        self.page.get_by_text(re.compile('^MAIN item ')).first.wait_for()
        self.assertEqual(self.cap(),list(range(1,101)))

    def test_z_hidden_chat_logout_fences_pending_history(self):
        # Final scenario revokes this private synthetic class login.
        self.open(); self.cap(); self.reader(); self.activate_older()
        prior=self.ids()
        self.page.get_by_role('tab',name='Задачи',exact=True).click()
        self.assertFalse(self.page.locator('.chat-items').is_visible())
        self.configure(count=104)
        before=len(self.requests()); self.page.wait_for_timeout(6500)
        self.assertEqual(len(self.requests()),before,'Hidden chat must not poll/replace its local window')
        self.page.get_by_role('tab',name='Сессии',exact=True).click()
        self.assertEqual(self.ids(),prior,'Returning to hidden Older window preserves reader state')
        self.page.get_by_role('button',name='Выйти',exact=True).click()
        self.page.locator('input[type=password]').wait_for()
        before=len(self.requests()); self.page.wait_for_timeout(1200)
        self.assertEqual(len(self.requests()),before)
        self.assertEqual(self.page.locator('.chat-items').get_by_text(re.compile('^MAIN item ')).count(),0,
                         'Logout clears session-scoped history and pending window state')


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--serve': serve(Path(sys.argv[2]),Path(sys.argv[3]))
    else: unittest.main(verbosity=2)
