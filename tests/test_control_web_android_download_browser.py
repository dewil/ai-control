"""Source-blind real browser acceptance for INV-AND-12 FR-AND-07 US-AND-004."""
# Accepted INV-WSESS-47..50 (2026-10-08-spec-live-observability-package.md):
# canonical captions/chips and native disclosures replace the previous labels/layout.

import importlib
import hashlib
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

ROOT = Path(os.environ.get('CONTROL_ANDROID_DOWNLOAD_QA_REPO', str(Path(__file__).resolve().parents[1])))
PREFIX = '/download/android/'


# Independent fixture handoff: a path may exist before private_json finishes.
# Readiness requires complete usable JSON within the original bounded deadline.
def wait_ready_json(path, server, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError('Synthetic download fixture failed')
        try:
            ready = json.loads(path.read_text())
            if (isinstance(ready, dict) and all(isinstance(ready.get(key), str)
                    and ready[key].startswith('http://127.0.0.1:')
                    for key in ('url', 'disabled_url'))):
                return ready
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.02)
    raise RuntimeError('Synthetic download fixture readiness timed out')


def manifest(code=1, name='0.1.0', payload=b'synthetic APK one'):
    return dict(versionCode=code, versionName=name,
                apkUrl='https://llm-web.dewil.ru:18443' + PREFIX + f'ai-control-{code}.apk',
                sha256=hashlib.sha256(payload).hexdigest())


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
            return {'rows': [{'sid': SID, 'title': 'Download synthetic session', 'status': 'idle'}], 'has_more': False}
        def session_history(self, *args):
            return {'turns': [{'id': 'download-fixture-turn', 'status': 'completed', 'items': [
                {'id': 'download-fixture-item', 'role': 'assistant', 'text': 'Download fixture history', 'truncated': False}]}],
                'next_cursor': None, 'truncated': False, 'recent_sends': []}
        def session_send(self, *args): return {'error': 'unavailable'}
        def session_send_status(self, *args): return {'error': 'stale'}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0)); listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD),
        'totp_secret': SECRET, 'session_ttl': 3600, 'secure_cookie': False,
        'android_download_dir': str(evidence / 'feed')}, Backend())
    disabled_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    disabled_listener.bind(('127.0.0.1', 0)); disabled_listener.listen(128)
    disabled_origin = 'http://127.0.0.1:' + str(disabled_listener.getsockname()[1])
    disabled_app = web.create_app({'origin': disabled_origin,
        'password_hash': web.hash_password(PASSWORD), 'totp_secret': SECRET,
        'session_ttl': 3600, 'secure_cookie': False}, Backend())
    disabled_server = uvicorn.Server(uvicorn.Config(disabled_app, log_level='error', access_log=False))
    threading.Thread(target=lambda: disabled_server.run(sockets=[disabled_listener]), daemon=True).start()
    private_json(evidence / 'ready.json', {'url': origin, 'disabled_url': disabled_origin})
    uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[listener])


class AndroidDownloadBrowserContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Optional Playwright dependency unavailable')
        cls.evidence = Path(tempfile.mkdtemp(prefix='android-download-browser-', dir='/var/tmp'))
        cls.addClassCleanup(lambda: __import__('shutil').rmtree(cls.evidence))
        cls.feed = cls.evidence / 'feed'; cls.feed.mkdir()
        interpreter = os.environ.get('CONTROL_DOWNLOAD_SERVER_PYTHON', sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve', str(ROOT), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        ready = wait_ready_json(cls.evidence / 'ready.json', cls.server)
        cls.url = ready['url']
        cls.disabled_url = ready['disabled_url']
        cls.playwright = sync_playwright().start(); cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(headless=True); cls.addClassCleanup(cls.browser.close)
        cls.auth = cls.browser.new_context(); cls.addClassCleanup(cls.auth.close)
        page = cls.auth.new_page()
        page.goto(cls.url)
        # INV-APP-07: R5 web requires username; preserve download assertions.
        page.locator('#username').fill('owner')
        page.locator('input[type=password]').fill(PASSWORD)
        page.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        page.get_by_role('button', name=re.compile('^Войти$', re.I)).click()
        page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(
            page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).wait_for()
        page.close()

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try: cls.server.wait(4)
        except subprocess.TimeoutExpired: cls.server.kill(); cls.server.wait()

    def setUp(self):
        for child in self.feed.iterdir(): child.unlink()
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.requests = []
        self.page.on('request', lambda req: self.requests.append((req.method, req.url)))

    def publish(self, code=1, name='0.1.0'):
        payload = f'synthetic APK {code}'.encode()
        (self.feed / f'ai-control-{code}.apk').write_bytes(payload)
        private_json(self.feed / 'version.json', manifest(code, name, payload))

    def landing(self):
        response = self.page.goto(self.url + PREFIX)
        self.assertEqual(response.status, 200, 'configured public landing must be available')
        self.assertEqual(self.page.url, self.url + PREFIX, 'no auth redirect')
        self.page.wait_for_timeout(200)

    def apk_links(self):
        return self.page.locator('a[href$=".apk"]')

    def assert_panel_link(self, page):
        # Требование изменено явно 11.10: постоянная ссылка в шапке подписана APP.
        link = page.get_by_role('link', name='APP', exact=True)
        self.assertEqual(link.count(), 1, 'permanent common download link required')
        self.assertTrue(link.is_visible())
        self.assertEqual(link.get_attribute('href'), PREFIX)

    def test_login_and_common_navigation_keep_download_link_on_mobile_and_selection(self):
        self.page.goto(self.url)
        for width in (1280, 360):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.assert_panel_link(self.page)
        logged = self.auth.new_page(); self.addCleanup(logged.close)
        logged.goto(self.url)
        logged.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(
            logged.get_by_role('tab', name=re.compile('^Сессии$', re.I))).click()
        choose_project(logged, 'demo')
        logged.get_by_role('button', name='Download synthetic session', exact=False).click()
        logged.get_by_text('Download fixture history', exact=True).wait_for()
        logged.locator('textarea').fill('Synthetic panel download draft')
        for width in (1280, 360):
            logged.set_viewport_size({'width': width, 'height': 900})
            self.assert_panel_link(logged)
            self.assertEqual(logged.locator('textarea').input_value(), 'Synthetic panel download draft')
        self.assertFalse(any(method == 'POST' and 'download' in url for method, url in self.requests))

    def test_panel_link_remains_visible_when_download_feature_is_disabled(self):
        self.page.goto(self.disabled_url)
        for width in (1280, 360):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.assert_panel_link(self.page)
        # Session admission resolves asynchronously; retain a bounded visible gate.
        self.page.locator('input[type=password]').wait_for(state='visible', timeout=5000)
        self.assertTrue(self.page.locator('input[type=password]').is_visible())

    def test_anonymous_latest_link_updates_after_manifest_publication_with_cache_enabled(self):
        self.publish()
        self.landing()
        self.assertEqual(self.apk_links().count(), 1)
        self.assertEqual(self.apk_links().first.get_attribute('href'), PREFIX + 'ai-control-1.apk')
        self.publish(2, '0.2.0')
        self.landing()
        self.assertEqual(self.apk_links().count(), 1)
        self.assertEqual(self.apk_links().first.get_attribute('href'), PREFIX + 'ai-control-2.apk')
        self.assertEqual(self.context.cookies(), [])
        self.assertFalse(any(method != 'GET' for method, _ in self.requests))

    def test_unpublished_and_invalid_manifest_show_safe_state_without_apk_link(self):
        self.landing()
        self.assertEqual(self.apk_links().count(), 0)
        self.assertIn('Версия еще не опубликована', self.page.locator('body').inner_text())
        (self.feed / 'version.json').write_bytes(b'broken fixture')
        self.landing()
        self.assertEqual(self.apk_links().count(), 0)
        self.assertFalse(self.page.locator('input[type=password]').count())
        self.assertEqual(self.context.cookies(), [])

    def test_missing_apk_never_shows_a_false_download_link(self):
        private_json(self.feed / 'version.json', manifest())
        self.landing()
        self.assertEqual(self.apk_links().count(), 0)

    def test_nonfinite_and_unpaired_surrogate_feed_never_creates_apk_link(self):
        self.publish()
        valid = manifest(payload=b'synthetic APK 1')
        variants = [dict(valid, unknown=value) for value in
                    (float('nan'), float('inf'), float('-inf'))]
        variants += [dict(valid, versionName='\ud800'),
                     dict(valid, unknown={'nested': ['\udfff']})]
        for index, doc in enumerate(variants):
            with self.subTest(index=index):
                (self.feed / 'version.json').write_bytes(
                    json.dumps(doc, ensure_ascii=True).encode('ascii'))
                self.landing()
                self.assertEqual(self.apk_links().count(), 0,
                                 'Invalid JSON must not offer a release')

    def test_hostile_version_name_is_plain_text_and_never_creates_external_href(self):
        name = "<img src=x onerror='window.feedInjected=1'>"
        self.publish(1, name)
        self.landing()
        self.assertIn(name, self.page.locator('body').inner_text())
        self.assertIsNone(self.page.evaluate('window.feedInjected'))
        self.assertEqual(self.page.locator('img[src=x]').count(), 0)
        self.assertEqual(self.apk_links().first.get_attribute('href'), PREFIX + 'ai-control-1.apk')
        self.assertFalse(any(url.startswith('https://llm-web') for _, url in self.requests),
                         'landing must use canonical relative APK href')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--serve': serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else: unittest.main()
