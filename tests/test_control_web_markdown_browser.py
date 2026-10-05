"""Blind browser contracts: docs/dev/2026-10-05-spec-web-chat-markdown.md.

Optional Playwright runner; server interpreter/executable are configurable via
CONTROL_MARKDOWN_QA_SERVER_PYTHON and CONTROL_MARKDOWN_QA_BROWSER_EXECUTABLE.
Only public create_app executes application code; source bodies are never read.
Synthetic evidence stays in a private /var/tmp directory, never the repository.
"""
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
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SID = '11111111-1111-4111-8111-111111111111'
PASSWORD = 'synthetic-markdown-fixture-password'
SECRET = 'JBSWY3DPEHPK3PXP'
SENTINEL = 'MD_MSG_SENTINEL'


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


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
            return {'rows': [{'sid': SID, 'title': 'Markdown synthetic session', 'status': 'idle'}], 'has_more': False}
        def session_history(self, project, sid, cursor):
            data = json.loads((evidence / 'control.json').read_text())
            older = cursor is not None
            text = data['older_text'] if older else data['text']
            identity = 'synthetic-markdown-older' if older else 'synthetic-markdown'
            return {'turns': [{'id': identity + '-turn', 'status': 'completed', 'items': [
                {'id': identity + '-item', 'role': 'assistant', 'text': text, 'truncated': False}]}],
                'next_cursor': 'markdown-older-page' if not older and 'older_text' in data else None, 'recent_sends': []}
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


class MarkdownBrowserContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Optional Playwright browser QA dependency is not installed')
        os.umask(0o077)
        requested = os.environ.get('CONTROL_MARKDOWN_QA_EVIDENCE')
        cls.evidence = Path(requested) if requested else Path(tempfile.mkdtemp(prefix='control-markdown-qa-', dir='/var/tmp'))
        cls.evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
        cls.evidence.chmod(0o700)
        cls.root = Path(os.environ.get('CONTROL_MARKDOWN_QA_REPO', str(ROOT)))
        (cls.evidence / 'ready.json').unlink(missing_ok=True)
        private_json(cls.evidence / 'control.json', {'text': SENTINEL})
        interpreter = os.environ.get('CONTROL_MARKDOWN_QA_SERVER_PYTHON', sys.executable)
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
        executable = os.environ.get('CONTROL_MARKDOWN_QA_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={'width': 390, 'height': 844}, color_scheme='dark')
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

    def setUp(self):
        self.runtime_errors = []
        self.network = []
        self.error_listener = lambda error: self.runtime_errors.append(type(error).__name__)
        self.request_listener = lambda request: self.network.append(request.url)
        self.page.on('pageerror', self.error_listener)
        self.page.on('request', self.request_listener)

    def tearDown(self):
        self.page.screenshot(path=str(self.evidence / (self._testMethodName + '.png')), full_page=True)
        self.page.remove_listener('pageerror', self.error_listener)
        self.page.remove_listener('request', self.request_listener)
        self.assertEqual(self.runtime_errors, [])
        self.assertTrue(self.page.evaluate('localStorage.length===0 && sessionStorage.length===0'))
        self.assertFalse(any('md-untrusted.invalid' in url or '/md-image-probe' in url or '/md-iframe-probe' in url
                             for url in self.network), 'Markdown content must not create image/embed network requests')
        self.assertFalse(any(urlsplit(url).netloc != urlsplit(self.url).netloc for url in self.network),
                         'Rendering synthetic Markdown must not contact another origin')

    def render(self, text, **history):
        private_json(self.evidence / 'control.json', {'text': text + '\n\n' + SENTINEL, **history})
        self.page.goto(self.url)
        self.page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(self.page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).click()
        self.page.get_by_label('Проект', exact=True).select_option('demo')
        self.page.get_by_role('button', name=re.compile('Markdown synthetic session')).click()
        self.page.get_by_text(SENTINEL, exact=False).first.wait_for(state='attached')

    def test_headings_one_through_six_are_semantic(self):
        self.render('\n\n'.join('#' * level + ' MD heading ' + str(level) for level in range(1, 7)))
        for level in range(1, 7):
            self.assertEqual(self.page.get_by_role('heading', name='MD heading ' + str(level), level=level, exact=True).count(), 1)

    def test_inline_strong_em_and_code_are_semantic_with_literal_code(self):
        self.render('Paragraph **MD BOLD** and *MD EMPHASIS* with `MD CODE **literal** <b>tag</b>`.')
        self.assertEqual(self.page.locator('strong').filter(has_text='MD BOLD').count(), 1)
        self.assertEqual(self.page.locator('strong').filter(has_text='MD BOLD').inner_text(), 'MD BOLD')
        self.assertEqual(self.page.locator('em').filter(has_text='MD EMPHASIS').inner_text(), 'MD EMPHASIS')
        code = self.page.locator('code').filter(has_text='MD CODE')
        self.assertEqual(code.text_content(), 'MD CODE **literal** <b>tag</b>')
        self.assertEqual(code.locator('strong,b,script').count(), 0)

    def test_fenced_code_preserves_whitespace_and_language_label(self):
        code = '  def sample():\n\treturn "**literal** <script>plain</script>"\n\n  # trailing spaces  \n'
        self.render('```python\n' + code + '```')
        node = self.page.locator('pre code').filter(has_text='def sample')
        self.assertEqual(node.count(), 1)
        self.assertEqual(node.text_content(), code)
        self.assertEqual(node.locator('strong,script').count(), 0)
        self.assertGreater(self.page.get_by_text('python', exact=True).count(), 0, 'Fence language is a visible textual label')

    def test_lists_and_blockquote_have_semantic_containers(self):
        self.render('- MD bullet alpha\n- MD bullet beta\n\n1. MD order first\n2. MD order second\n\n> MD quoted line\n> MD quoted continuation')
        self.assertEqual(self.page.locator('ul li').filter(has_text='MD bullet').count(), 2)
        self.assertEqual(self.page.locator('ol > li').filter(has_text=re.compile(r'^MD order (?:first|second)$')).count(), 2)
        quote = self.page.locator('blockquote').filter(has_text='MD quoted line')
        self.assertIn('MD quoted continuation', quote.inner_text())

    def test_pipe_table_has_headers_and_cells(self):
        self.render('| MD column A | MD column B |\n| --- | --- |\n| MD cell alpha | MD cell beta |')
        table = self.page.locator('table').filter(has_text='MD column A')
        self.assertEqual(table.count(), 1)
        self.assertEqual(table.locator('th').all_text_contents(), ['MD column A', 'MD column B'])
        self.assertEqual(table.locator('td').all_text_contents(), ['MD cell alpha', 'MD cell beta'])

    def test_valid_links_have_safe_target_and_relative_origin(self):
        self.render('[MD safe external](https://example.invalid/path?x=1&y=two) and [MD safe relative](/md-safe-relative).')
        for label, href in [('MD safe external', 'https://example.invalid/path?x=1&y=two'),
                            ('MD safe relative', self.url + '/md-safe-relative')]:
            link = self.page.get_by_role('link', name=label, exact=True)
            self.assertEqual(link.count(), 1)
            self.assertEqual(urljoin(self.url, link.get_attribute('href')), href)
            self.assertEqual(link.get_attribute('target'), '_blank')
            self.assertTrue({'noopener', 'noreferrer'} <= set((link.get_attribute('rel') or '').split()))

    def test_raw_html_media_and_script_stay_literal_without_execution_or_network(self):
        raw = '<script>window.mdProbe=1</script>\n<img src="/md-image-probe" onerror="window.mdProbe=2">\n<svg id="md-svg-probe" onload="window.mdProbe=3"></svg>\n<iframe src="/md-iframe-probe"></iframe>\n![MD hidden image](https://md-untrusted.invalid/pixel)'
        self.render(raw)
        self.assertIn('<script>window.mdProbe=1</script>', self.page.locator('body').inner_text())
        self.assertIn('<img src="/md-image-probe"', self.page.locator('body').inner_text())
        self.assertEqual(self.page.locator('script').filter(has_text='window.mdProbe').count(), 0)
        self.assertEqual(self.page.locator('img[src*="md-image-probe"],svg#md-svg-probe,iframe[src*="md-iframe-probe"],[onerror],[onload],[onclick]').count(), 0)
        self.assertTrue(self.page.evaluate('typeof window.mdProbe === "undefined"'))

    def test_dangerous_url_forms_remain_text_without_active_anchors(self):
        targets = ['javascript:alert(1)', 'data:text/html,probe', 'vbscript:probe', 'file:///private-probe',
                   '//md-untrusted.invalid/x', '\\\\md-untrusted.invalid/x', 'java&#x73;cript:alert(1)',
                   'jav&#97;script:alert(1)', 'java\tscript:alert(1)', '\x01javascript:alert(1)']
        self.render('\n\n'.join('[MD BAD ' + str(i) + '](' + target + ')' for i, target in enumerate(targets)) +
                    '\n\n[MD injected attribute](https://example.invalid/x" onclick="window.mdProbe=4)')
        self.assertEqual(self.page.locator('a').filter(has_text='MD BAD').count(), 0)
        self.assertEqual(self.page.locator('[onclick],[onerror],[onload]').count(), 0)
        self.assertTrue(self.page.evaluate('typeof window.mdProbe === "undefined"'))

    def test_partial_markdown_unicode_and_bounded_unmatched_input_are_readable(self):
        self.render('Привет 👋 漢字 & <literal>\n\n**unfinished\n\n```text\n  unfinished fence **literal**\nPARTIAL END')
        body = self.page.locator('body').inner_text()
        self.assertIn('Привет 👋 漢字 & <literal>', body)
        self.assertIn('PARTIAL END', body)
        self.assertEqual(self.page.locator('literal').count(), 0)
        self.render('[' * 7900 + '\nUNICODE FINISH 👋')
        self.assertIn('UNICODE FINISH 👋', self.page.locator('body').inner_text())


class SafeResult(unittest.TestResult):
    def __init__(self): super().__init__(); self.records = []
    def addSuccess(self, test):
        super().addSuccess(test); self.records.append({'test': test.id(), 'status': 'PASS'})
    def addFailure(self, test, error):
        super().addFailure(test, error); self.records.append({'test': test.id(), 'status': 'FAIL', 'reason_class': error[0].__name__})
    def addError(self, test, error):
        super().addError(test, error); self.records.append({'test': test.id(), 'status': 'ERROR', 'reason_class': error[0].__name__})
    def addSkip(self, test, reason):
        super().addSkip(test, reason); self.records.append({'test': test.id(), 'status': 'SKIP', 'reason': reason})


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--serve':
        serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        result = SafeResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(MarkdownBrowserContract).run(result)
        evidence = getattr(MarkdownBrowserContract, 'evidence', None)
        if evidence: private_json(evidence / 'markdown-report.json', result.records)
        print('Markdown QA:', result.testsRun, 'tests;', len(result.failures), 'failures;', len(result.errors), 'errors;', len(result.skipped), 'skips')
        if evidence: print('Private evidence:', evidence)
        raise SystemExit(0 if result.wasSuccessful() else 1)
