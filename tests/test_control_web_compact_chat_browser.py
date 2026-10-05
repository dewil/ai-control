"""Source-blind compact browser acceptance, synthetic local backend only.

No asset-source reads or native/user history. Runtime DOM and computed styles
are observations. Fixture controls and screenshots stay private in /var/tmp.
"""
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
from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET, SID

ROOT = Path(__file__).resolve().parents[1]
OTHER = '44444444-4444-4444-8444-444444444444'


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root / 'bin'))
    web = importlib.import_module('_control_web')
    class Backend:
        def snapshot(self): return {'tasks': []}
        def answer(self, *args): return {'error': 'unavailable'}
        def verdict(self, *args): return {'error': 'unavailable'}
        def session_projects(self): return {'projects': [{'name': 'demo'}]}
        def session_list(self, project, page):
            return {'rows': [{'sid': SID, 'title': 'Compact synthetic session', 'status': 'idle'},
                             {'sid': OTHER, 'title': 'Second synthetic session', 'status': 'idle'}], 'has_more': False}
        def session_history(self, project, sid, cursor):
            data = json.loads((evidence / 'control.json').read_text())
            with (evidence / 'requests.jsonl').open('a') as handle:
                handle.write(json.dumps({'method': 'history', 'sid': sid, 'cursor': cursor}) + '\n')
            time.sleep(data.get('delay', 0) if sid == SID else 0)
            prefix = 'OLDER' if cursor else ('SECOND' if sid == OTHER else 'LATEST')
            return {'turns': [{'id': prefix + '-turn', 'status': 'completed', 'items': [
                {'id': prefix + '-' + str(i), 'role': 'assistant', 'text': prefix + ' message ' + str(i) + '\n\n' + (prefix + ' detail ' + str(i) + ' readable words ')*18, 'truncated': False}
                for i in range(24)]}], 'next_cursor': None if cursor else 'older-fixture', 'truncated': False, 'recent_sends': []}
        def session_send(self, *args): return {'error': 'unavailable'}
        def session_send_status(self, *args): return {'error': 'stale'}
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0)); listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD),
                          'totp_secret': SECRET, 'session_ttl': 3600, 'secure_cookie': False}, Backend())
    private_json(evidence / 'ready.json', {'url': origin})
    uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[listener])


class CompactChatBrowserContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Optional Playwright dependency unavailable')
        os.umask(0o077)
        cls.evidence = Path(tempfile.mkdtemp(prefix='control-compact-qa-', dir='/var/tmp'))
        private_json(cls.evidence / 'control.json', {'delay': 0})
        interpreter = os.environ.get('CONTROL_COMPACT_QA_SERVER_PYTHON', sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve', str(ROOT), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        while not (cls.evidence / 'ready.json').exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None: raise RuntimeError('Synthetic fixture server failed')
            time.sleep(.02)
        cls.url = json.loads((cls.evidence / 'ready.json').read_text())['url']
        cls.playwright = sync_playwright().start(); cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_COMPACT_QA_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={'width': 1280, 'height': 900}, color_scheme='dark')
        cls.addClassCleanup(cls.context.close)
        login = cls.context.new_page()
        login.goto(cls.url)
        login.locator('input[type=password]').fill(PASSWORD)
        login.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        login.get_by_role('button', name=re.compile('^Войти$', re.I)).click()
        login.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(login.get_by_role('tab', name=re.compile('^Сессии$', re.I))).wait_for()
        login.close()

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try: cls.server.wait(4)
        except subprocess.TimeoutExpired: cls.server.kill(); cls.server.wait()

    def setUp(self):
        private_json(self.evidence / 'control.json', {'delay': 0})
        self.page = self.context.new_page(); self.page.set_viewport_size({'width': 1280, 'height': 900})
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(5000)
        self.network = []; self.runtime_errors = []
        self.page.on('request', lambda request: self.network.append((request.method, request.url)))
        self.page.on('pageerror', lambda error: self.runtime_errors.append(type(error).__name__))
        self.page.goto(self.url)
        self.page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(self.page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).click()
        self.page.get_by_label('Проект', exact=True).select_option('demo')
        self.session = self.page.get_by_role('button', name=re.compile('Compact synthetic session'))
        self.session.wait_for()

    def tearDown(self):
        self.page.screenshot(path=str(self.evidence / (self._testMethodName + '.png')), full_page=True)
        self.assertEqual(self.runtime_errors, [])
        self.assertFalse(any(url.split('/')[2] != self.url.split('/')[2] for _, url in self.network), 'No external fonts/CDN/network')
        self.assertTrue(self.page.evaluate('localStorage.length===0 && sessionStorage.length===0'))

    def open_history(self):
        self.session.click()
        self.page.get_by_text('LATEST message 23', exact=False).wait_for(state='attached')

    def history_requests(self):
        return [request for request in self.network if '/api/session-history?' in request[1]]

    def test_INV_WSESS_13_desktop_sidebar_sans_menu_mobile_targets_and_no_overflow(self):
        self.open_history()
        observations = []
        for width in (1280, 768, 360):
            self.page.set_viewport_size({'width': width, 'height': 900}); self.page.wait_for_timeout(100)
            menu = self.session.evaluate('''el => {const s=getComputedStyle(el),r=el.getBoundingClientRect();return {font:s.fontFamily,size:parseFloat(s.fontSize),weight:Number(s.fontWeight),left:r.left,right:r.right,width:r.width,height:r.height}}''')
            sidebar = self.session.evaluate('''el => {const project=document.querySelector('select');let n=el;while(n.parentElement&&!n.contains(project)) n=n.parentElement;const r=n.getBoundingClientRect();return {width:r.width,right:r.right,containsChat:n.contains(document.querySelector('.chat-items'))};}''')
            chat = self.page.locator('.chat-items').bounding_box()
            page = self.page.evaluate('''() => ({width:innerWidth,overflow:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth),targets:[...document.querySelectorAll('button,select,textarea')].filter(el=>el.getBoundingClientRect().width&&el.getBoundingClientRect().height).map(el=>({text:el.textContent.slice(0,50),height:el.getBoundingClientRect().height}))})''')
            typography = self.page.locator('.chat-items p').first.evaluate('''el=>{const s=getComputedStyle(el);return {size:parseFloat(s.fontSize),line:parseFloat(s.lineHeight)/parseFloat(s.fontSize),font:s.fontFamily,overflow:s.overflowX,textOverflow:s.textOverflow};}''')
            observations.append({'typography': typography, 'menu': menu, 'sidebar': sidebar, 'chat': chat, **page})
        private_json(self.evidence / 'layout.json', observations)
        failures = []
        if 'Готова' not in self.session.inner_text(): failures.append('idle session must be labelled Готова')
        for result in observations:
            width = result['width']; menu = result['menu']
            if menu['size'] != 14 or not 400 <= menu['weight'] <= 500 or re.search('mono|courier|consolas', menu['font'], re.I): failures.append(f'{width}: menu typography {menu}')
            if result['overflow'] > width + 1: failures.append(f'{width}: horizontal overflow {result["overflow"]}')
            text = result['typography']
            if not 15 <= text['size'] <= 16 or abs(text['line'] - 1.5) > .05: failures.append(f'{width}: message typography {text}')
            if text['textOverflow'] == 'ellipsis' or text['overflow'] == 'hidden': failures.append(f'{width}: ordinary message text clipped')
            minimum = 44 if width < 1024 else 40
            if any(t['height'] < minimum - .5 for t in result['targets']): failures.append(f'{width}: targets below {minimum}px')
            if width == 1280:
                if not 240 <= result['sidebar']['width'] <= 280 or result['sidebar']['containsChat']: failures.append('desktop: sidebar width outside240–280')
                if result['chat']['x'] < menu['right'] - 1: failures.append('desktop: chat is not to right of session menu')
        self.assertEqual(failures, [])

    def test_INV_WSESS_11_keyboard_top_jump_only_on_click_retains_reader_anchor(self):
        self.open_history()
        button = self.page.get_by_role('button', name='К последним сообщениям', exact=True)
        self.assertEqual(button.count(), 1, 'Missing accessible explicit top jump button')
        # Capture an actual visible message and its viewport offset, rather than scrollHeight.
        self.page.evaluate('''() => {let box=document.querySelector('.chat-items');while(box&&!(box.scrollHeight>box.clientHeight+1&&/auto|scroll/.test(getComputedStyle(box).overflowY))) box=box.parentElement;box=box||document.scrollingElement;box.scrollTop=Math.max(0,box.scrollHeight/2-box.clientHeight/2);}''')
        self.page.wait_for_timeout(200)
        anchor = self.page.evaluate('''() => {const box=document.querySelector('.chat-items'),r={top:0,bottom:innerHeight};const el=[...box.querySelectorAll('p')].find(el=>{const q=el.getBoundingClientRect();return q.top>=r.top&&q.bottom<=r.bottom});return el&&{text:el.textContent,top:el.getBoundingClientRect().top};}''')
        self.assertIsNotNone(anchor, 'Fixture must expose a visible reader anchor')
        polling_before = len(self.history_requests())
        self.page.wait_for_timeout(6500)
        self.assertGreater(len(self.history_requests()), polling_before, 'Reader-anchor assertion must observe a real polling request')
        actual = self.page.get_by_text(anchor['text'], exact=True).first.bounding_box()
        self.assertLessEqual(abs(actual['y'] - anchor['top']), 8, 'Polling must not drag reader')
        before = len(self.history_requests()); sends = len([x for x in self.network if '/api/session-send' in x[1]])
        button.focus(); self.assertTrue(button.evaluate('el=>el===document.activeElement'))
        button.press('Enter'); self.page.wait_for_timeout(200)
        metrics = self.page.locator('.chat-items').evaluate('''el=> {let box=el;while(box&&!(box.scrollHeight>box.clientHeight+1&&/auto|scroll/.test(getComputedStyle(box).overflowY))) box=box.parentElement;box=box||document.scrollingElement;return {gap:box.scrollHeight-box.clientHeight-box.scrollTop};}''')
        self.assertTrue(self.page.locator('textarea').is_visible())
        self.assertLessEqual(metrics['gap'], 8, 'Explicit jump must reach newest message and remove scroll slack')
        self.assertEqual(len(self.history_requests()), before, 'Jump is local, no API history request')
        self.assertEqual(len([x for x in self.network if '/api/session-send' in x[1]]), sends, 'Jump cannot send')

    def test_INV_WSESS_12_first_load_timeout_stops_polling_retains_draft_and_manual_retry(self):
        private_json(self.evidence / 'control.json', {'delay': 21})
        started = time.monotonic(); self.session.click()
        draft = 'Synthetic draft retained after slow history'
        self.page.locator('textarea').fill(draft)
        # Allow 1.5s browser scheduling overhead around the specified 15s deadline.
        self.page.wait_for_timeout(max(0, 16500 - (time.monotonic() - started) * 1000))
        retry = self.page.get_by_role('button', name='Повторить загрузку', exact=True)
        self.assertEqual(retry.count(), 1, 'At15s blocked history must replace first-load spinner with error/retry')
        self.assertTrue(retry.is_visible()); self.assertTrue(retry.is_enabled())
        self.assertRegex(self.page.locator('body').inner_text(), r'(?i)ошиб|не удалось|время|загрузк')
        self.assertEqual(self.page.locator('textarea').input_value(), draft)
        count = len(self.history_requests()); self.page.wait_for_timeout(6500)
        self.assertEqual(len(self.history_requests()), count, 'Error suspends automatic polling and retries')
        self.assertEqual(self.page.get_by_text('LATEST message 23', exact=False).count(), 0, 'Late success cannot overwrite timeout screen')
        private_json(self.evidence / 'control.json', {'delay': 0})
        retry.click(); self.page.get_by_text('LATEST message 23', exact=False).wait_for(state='attached')
        self.assertGreater(len(self.history_requests()), count)
        self.assertEqual(self.page.locator('textarea').input_value(), draft)
        self.assertFalse(any(method == 'POST' and '/api/session-send' in url for method, url in self.network))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--serve': serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else: unittest.main(verbosity=2)
