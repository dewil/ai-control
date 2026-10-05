"""Source blind browser regression for chat width (INV-WIDTH-01/02)."""
import base64
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SID = '11111111-1111-4111-8111-111111111111'
PASSWORD = 'synthetic-width-fixture-password'
SECRET = 'JBSWY3DPEHPK3PXP'
SENTINEL = 'WIDTH_SENTINEL'


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle, ensure_ascii=False)


def totp():
    digest = hmac.new(base64.b32decode(SECRET), struct.pack('>Q', int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return str((struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000).zfill(6)


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
            return {'rows': [{'sid': SID, 'title': 'Width synthetic session', 'status': 'idle'}], 'has_more': False}
        def session_history(self, project, sid, cursor):
            data = json.loads((evidence / 'control.json').read_text())
            return {'turns': [{'id': 'width-turn', 'status': 'completed', 'items': data['items']}],
                    'next_cursor': None, 'recent_sends': []}
        def session_send(self, *args): return {'error': 'unavailable'}
        def session_send_status(self, *args): return {'error': 'stale'}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD),
                          'totp_secret': SECRET, 'session_ttl': 3600, 'secure_cookie': False}, Backend())
    private_json(evidence / 'ready.json', {'url': origin})
    uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[listener])


class ChatWidthBrowserContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Optional Playwright browser QA dependency is not installed')
        os.umask(0o077)
        requested = os.environ.get('CONTROL_WIDTH_QA_EVIDENCE')
        cls.evidence = Path(requested) if requested else Path(tempfile.mkdtemp(prefix='control-width-qa-', dir='/var/tmp'))
        cls.evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
        cls.evidence.chmod(0o700)
        cls.root = Path(os.environ.get('CONTROL_WIDTH_QA_REPO', str(ROOT)))
        (cls.evidence / 'ready.json').unlink(missing_ok=True)
        cls.write_items()
        interpreter = os.environ.get('CONTROL_WIDTH_QA_SERVER_PYTHON', sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve', str(cls.root), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 5
        while not (cls.evidence / 'ready.json').exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None: raise RuntimeError('Synthetic fixture server failed to start')
            time.sleep(.02)
        cls.url = json.loads((cls.evidence / 'ready.json').read_text())['url']
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_WIDTH_QA_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={'width': 360, 'height': 900}, color_scheme='dark')
        cls.page = cls.context.new_page()
        cls.page.set_default_timeout(5000)
        cls.page.goto(cls.url)
        cls.page.locator('input[type=password]').fill(PASSWORD)
        cls.page.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        cls.page.get_by_role('button', name=re.compile('^Войти$', re.I)).click()
        cls.page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(cls.page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).wait_for()

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try: cls.server.wait(4)
        except subprocess.TimeoutExpired: cls.server.kill(); cls.server.wait()

    @classmethod
    def write_items(cls):
        lines = 'ordinary spaced text ' * 22
        md = ('Paragraph one has ordinary spaced words that must wrap safely.\n\n'
              'Paragraph two includes another readable line and a long word: '
              'supercalifragilisticexpialidocious' * 7 + '\n\n'
              '[A very long link label with many ordinary words that should wrap over several lines](https://example.invalid/' + 'segment-' * 25 + ')')
        code = '```text\n' + ('LOCAL_CODE_CONTENT_' * 38) + '\n```'
        table = '| ' + ' | '.join('WIDE_HEADER_' + str(i) for i in range(12)) + ' |\n'
        table += '| ' + ' | '.join('---' for _ in range(12)) + ' |\n'
        table += '| ' + ' | '.join('WIDE_CELL_' + str(i) for i in range(12)) + ' |'
        items = [
            {'id': 'width-user', 'role': 'user', 'text': 'USER_START ' + lines + ' USER_END', 'truncated': False},
            {'id': 'width-assistant', 'role': 'assistant', 'text': 'ASSISTANT_START ' + md + '\n\n' + code + '\n\n' + table + '\n\n' + SENTINEL, 'truncated': False},
        ]
        private_json(cls.evidence / 'control.json', {'items': items})

    def setUp(self):
        self.runtime_errors = []
        self.network = []
        self.error_listener = lambda error: self.runtime_errors.append(type(error).__name__)
        self.request_listener = lambda request: self.network.append(request.url)
        self.page.on('pageerror', self.error_listener)
        self.page.on('request', self.request_listener)
        self.page.goto(self.url)
        self.page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(self.page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).click()
        self.page.get_by_label('Проект', exact=True).select_option('demo')
        self.page.get_by_role('button', name=re.compile('Width synthetic session')).click()
        self.page.get_by_text(SENTINEL, exact=False).wait_for(state='attached')

    def tearDown(self):
        self.page.screenshot(path=str(self.evidence / (self._testMethodName + '.png')), full_page=True)
        self.page.remove_listener('pageerror', self.error_listener)
        self.page.remove_listener('request', self.request_listener)
        self.assertEqual(self.runtime_errors, [])
        self.assertTrue(self.page.evaluate('localStorage.length===0 && sessionStorage.length===0'))
        self.assertFalse(any('example.invalid' in url for url in self.network), 'Markdown must not contact external origins')
        self.assertFalse(any(url.split('/')[2] != self.url.split('/')[2] for url in self.network),
                         'Synthetic fixture must remain same-origin')

    def test_chat_content_fits_and_wraps_at_mobile_tablet_and_desktop_widths(self):
        observations = []
        for width in (360, 768, 1280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.page.wait_for_timeout(75)
            result = self.page.evaluate('''() => {
              const body = document.body;
              const text = needle => [...document.querySelectorAll('body *')]
                .filter(el => el.children.length === 0 && (el.textContent || '').includes(needle))
                .sort((a,b) => a.getBoundingClientRect().width - b.getBoundingClientRect().width)[0];
              const leaf = text('USER_START');
              const assistantLeaf = text('ASSISTANT_START');
              const chain = el => { const a=[]; for(let n=el; n && a.length<9; n=n.parentElement) a.push({tag:n.tagName, cls:String(n.className||''), rect:(()=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width}})(), sw:n.scrollWidth,cw:n.clientWidth}); return a; };
              const user = leaf && leaf.closest('article, [class*=message], [class*=bubble]');
              const assistant = assistantLeaf && assistantLeaf.closest('article, [class*=message], [class*=bubble]');
              const pre = document.querySelector('pre'); const table = document.querySelector('table');
              const panel = document.querySelector('.chat-items')?.closest('section');
              const scroller = el => { for(let n=el; n && n!==document.body; n=n.parentElement) { const s=getComputedStyle(n); if((s.overflowX==='auto'||s.overflowX==='scroll')&&n.scrollWidth>n.clientWidth+1) { const r=n.getBoundingClientRect(); return {sw:n.scrollWidth,cw:n.clientWidth,left:r.left,right:r.right}; } } return null; };
              const page = document.documentElement;
              return {vw:innerWidth, pageSW:page.scrollWidth, bodySW:body.scrollWidth,
                userText:leaf && leaf.innerText, assistantText:assistantLeaf && assistantLeaf.innerText,
                userRects:user ? {left:user.getBoundingClientRect().left,right:user.getBoundingClientRect().right,width:user.getBoundingClientRect().width} : null,
                assistantRects:assistant ? {left:assistant.getBoundingClientRect().left,right:assistant.getBoundingClientRect().right,width:assistant.getBoundingClientRect().width} : null,
                panel:panel && {left:panel.getBoundingClientRect().left,right:panel.getBoundingClientRect().right},
                markdownParagraphs:document.querySelectorAll('.content.markdown p').length,
                longLink:[...document.querySelectorAll('.content.markdown a')].some(a=>(a.innerText||'').includes('A very long link label')),
                pre:pre && {sw:pre.scrollWidth,cw:pre.clientWidth,rect:pre.getBoundingClientRect().toJSON()},
                table:table && {sw:table.scrollWidth,cw:table.clientWidth,rect:table.getBoundingClientRect().toJSON()},
                codeScroller:pre && scroller(pre), tableScroller:table && scroller(table),
                userChain:leaf && chain(leaf), assistantChain:assistantLeaf && chain(assistantLeaf)};
            }''')
            observations.append(result)
        private_json(self.evidence / 'width-report.json', observations)
        self.assertTrue(all(item['pageSW'] <= item['vw'] + 1 for item in observations),
                        'Page horizontal overflow by viewport: ' + repr([(x['vw'], x['pageSW']) for x in observations]))
        self.assertTrue(all(item['bodySW'] <= item['vw'] + 1 for item in observations),
                        'Body horizontal overflow by viewport: ' + repr([(x['vw'], x['bodySW']) for x in observations]))
        for item in observations:
            self.assertIn('USER_END', item['userText'] or '', f"viewport {item['vw']}: user text missing/clipped")
            self.assertIn('ASSISTANT_START', item['assistantText'] or '', f"viewport {item['vw']}: assistant text missing/clipped")
            self.assertTrue(item['pre'] and item['table'], f"viewport {item['vw']}: code/table missing")
            self.assertGreaterEqual(item['markdownParagraphs'], 2, f"viewport {item['vw']}: multiple Markdown paragraphs missing")
            self.assertTrue(item['longLink'], f"viewport {item['vw']}: long link missing")
            self.assertTrue(item['userRects'] and item['assistantRects'], f"viewport {item['vw']}: message card missing")
            for name in ('userRects', 'assistantRects'):
                self.assertGreaterEqual(item[name]['left'], -1, f"viewport {item['vw']}: {name} left outside viewport")
                self.assertLessEqual(item[name]['right'], item['vw'] + 1, f"viewport {item['vw']}: {name} right outside viewport")
                self.assertGreaterEqual(item[name]['left'], item['panel']['left'] - 1, f"viewport {item['vw']}: {name} outside chat panel")
                self.assertLessEqual(item[name]['right'], item['panel']['right'] + 1, f"viewport {item['vw']}: {name} outside chat panel")
            self.assertTrue(item['codeScroller'], f"viewport {item['vw']}: code has no local horizontal scroller")
            self.assertTrue(item['tableScroller'], f"viewport {item['vw']}: table has no local horizontal scroller")
        self.assertGreater(observations[0]['userRects']['left'], observations[0]['assistantRects']['left'],
                           'user card should align right of assistant card')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--serve':
        serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main(verbosity=2)
