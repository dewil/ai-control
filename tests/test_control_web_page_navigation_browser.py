"""INV-WSESS-14/15: source-blind document navigation, synthetic backend only."""
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

import test_control_web_compact_chat_browser as compact
from test_control_web_compact_chat_browser import OTHER
from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET, SID

ROOT = Path(__file__).resolve().parents[1]


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
            time.sleep(data.get('delay', 0))
            prefix = 'LATEST' if sid == SID else 'SECOND'
            return {'turns': [{'id': 'navigation-turn', 'status': 'completed', 'items': [
                {'id': 'navigation-' + str(i), 'role': 'assistant', 'text': prefix + ' message ' + str(i) + '\n\n' + ('Readable navigation detail ' + str(i) + ' ')*30, 'truncated': False}
                for i in range(data.get('count', 24))]}], 'next_cursor': 'older-fixture', 'truncated': False, 'recent_sends': []}
        def session_send(self, *args): return {'error': 'unavailable'}
        def session_send_status(self, *args): return {'error': 'stale'}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0)); listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD),
                          'totp_secret': SECRET, 'session_ttl': 3600, 'secure_cookie': False}, Backend())
    private_json(evidence / 'ready.json', {'url': origin})
    uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[listener])


class PageNavigationBrowserContract(unittest.TestCase):
    # Share synthetic login, teardown and public-DOM helpers, not existing tests.
    stop_server = classmethod(compact.CompactChatBrowserContract.stop_server.__func__)
    setUp = compact.CompactChatBrowserContract.setUp
    tearDown = compact.CompactChatBrowserContract.tearDown
    open_history = compact.CompactChatBrowserContract.open_history
    history_requests = compact.CompactChatBrowserContract.history_requests

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Optional Playwright dependency unavailable')
        os.umask(0o077)
        cls.evidence = Path(tempfile.mkdtemp(prefix='control-navigation-qa-', dir='/var/tmp'))
        private_json(cls.evidence / 'control.json', {'delay': 0, 'count': 24})
        cls.root = Path(os.environ.get('CONTROL_NAVIGATION_QA_REPO', str(ROOT)))
        interpreter = os.environ.get('CONTROL_NAVIGATION_QA_SERVER_PYTHON', sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve', str(cls.root), str(cls.evidence)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        while not (cls.evidence / 'ready.json').exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None: raise RuntimeError('Synthetic fixture server failed')
            time.sleep(.02)
        cls.url = json.loads((cls.evidence / 'ready.json').read_text())['url']
        cls.playwright = sync_playwright().start(); cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_NAVIGATION_QA_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={'width': 1280, 'height': 900}, color_scheme='dark')
        cls.addClassCleanup(cls.context.close)
        page = cls.context.new_page()
        page.goto(cls.url)
        page.locator('input[type=password]').fill(PASSWORD)
        page.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        page.get_by_role('button', name=re.compile('^Войти$', re.I)).click()
        page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).wait_for()
        page.close()
        print('Navigation evidence: ' + str(cls.evidence), flush=True)

    def buttons(self, direction):
        name = '↑ В начало' if direction == 'up' else '↓ В конец'
        buttons = self.page.get_by_role('button', name=name, exact=True)
        self.assertEqual(buttons.count(), 2, 'INV-WSESS-14: requires top and bottom accessible ' + name + ' buttons')
        return buttons

    def metrics(self):
        return self.page.evaluate('''() => ({y:scrollY,max:Math.max(0,document.scrollingElement.scrollHeight-innerHeight),overflow:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth),width:innerWidth})''')

    def assert_extreme(self, direction):
        self.page.wait_for_timeout(250)
        result = self.metrics()
        self.assertGreater(result['max'], 900, 'Fixture must have a scrollable document')
        self.assertLessEqual(result['y'] if direction == 'up' else result['max']-result['y'], 8,
                             'Navigation must reach natural document ' + direction + ': ' + repr(result))

    def activate(self, direction, index=0, key=None):
        button = self.buttons(direction).nth(index)
        if key:
            button.focus(); self.assertTrue(button.evaluate('el=>el===document.activeElement'))
            button.press(key)
        else:
            button.click()
        self.assert_extreme(direction)

    def test_INV_WSESS_14_both_pairs_layout_document_extremes_and_keyboard(self):
        self.open_history()
        self.assertEqual(self.page.get_by_role('button', name='К последним сообщениям', exact=True).count(), 1)
        observations = []
        for width in (1280, 768, 360):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 900})
                for direction in ('up', 'down'):
                    buttons = self.buttons(direction)
                    positions = [buttons.nth(i).evaluate('el=>{const r=el.getBoundingClientRect();return {top:r.top+scrollY,height:r.height,width:r.width}}') for i in range(2)]
                    self.assertLess(positions[0]['top'], positions[1]['top'])
                    first_message_y = self.page.get_by_text('LATEST message 0', exact=True).evaluate('el=>el.getBoundingClientRect().top+scrollY')
                    last_message_y = self.page.get_by_text('LATEST message 23', exact=True).evaluate('el=>el.getBoundingClientRect().bottom+scrollY')
                    self.assertLess(positions[0]['top'], first_message_y, 'Top navigation precedes history')
                    self.assertGreater(positions[1]['top'], last_message_y, 'Bottom navigation follows history')
                    minimum = 40 if width == 1280 else 44
                    self.assertTrue(all(p['height'] >= minimum-.5 and p['width'] >= minimum-.5 for p in positions), repr(positions))
                    for index in (0, 1):
                        self.activate(direction, index, 'Enter' if index == 0 else 'Space')
                result = self.metrics(); observations.append(result)
                self.assertLessEqual(result['overflow'], width+1, 'No horizontal document overflow')
        private_json(self.evidence / 'layout.json', observations)

    def test_INV_WSESS_15_clicks_preserve_draft_selection_and_make_no_requests(self):
        self.open_history()
        draft = 'Synthetic navigation draft remains unchanged'
        self.page.locator('textarea').fill(draft)
        before_selection = self.session.get_attribute('aria-pressed')
        before_cookies = self.context.cookies()
        for direction in ('up', 'down'):
            for index in (0, 1):
                before = len(self.network)
                self.activate(direction, index)
                self.assertEqual(self.network[before:], [], 'Navigation is local: zero click-caused requests')
                self.assertEqual(self.page.locator('textarea').input_value(), draft)
                self.assertEqual(self.page.get_by_label('Проект', exact=True).input_value(), 'demo')
                self.assertEqual(self.session.get_attribute('aria-pressed'), before_selection)
                self.assertEqual(self.page.get_by_text('LATEST message 23', exact=True).count(), 1)
                self.assertEqual(self.page.get_by_text('SECOND message 23', exact=True).count(), 0)
                self.assertEqual(self.context.cookies(), before_cookies, 'Navigation preserves synthetic auth')
        self.assertFalse(any(method == 'POST' and '/api/' in url for method, url in self.network))

    def test_INV_WSESS_15_up_cancels_delayed_initial_follow(self):
        self.page.set_viewport_size({'width': 360, 'height': 900})
        private_json(self.evidence / 'control.json', {'delay': 1.5, 'count': 24})
        self.session.click()
        self.buttons('up').first.click()
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.assert_extreme('up')
        initial_y = self.metrics()['y']
        self.page.wait_for_timeout(1200)
        self.assertLessEqual(abs(self.metrics()['y']-initial_y), 8, 'No deferred viewport movement after explicit up')

    def test_INV_WSESS_15_down_during_initial_load_follows_loaded_document(self):
        private_json(self.evidence / 'control.json', {'delay': 1.5, 'count': 24})
        self.session.click()
        self.buttons('down').first.click()
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.assert_extreme('down')
        self.page.wait_for_timeout(1200)
        self.assert_extreme('down')

    def test_INV_WSESS_15_up_preserves_reader_anchor_on_real_new_data(self):
        self.page.set_viewport_size({'width': 360, 'height': 900})
        self.open_history()
        self.activate('up')
        private_json(self.evidence / 'control.json', {'delay': 0, 'count': 28})
        self.page.get_by_text('LATEST message 27', exact=True).wait_for(state='attached', timeout=8500)
        self.assert_extreme('up')
        # Read a stable visible paragraph following explicit up; scrolling to it
        # is an ordinary reader action, not an internal app state override.
        anchor = self.page.get_by_text('LATEST message 2', exact=True)
        anchor.scroll_into_view_if_needed(); self.page.wait_for_timeout(150)
        before_y = anchor.bounding_box()['y']
        before_requests = len(self.history_requests())
        private_json(self.evidence / 'control.json', {'delay': 0, 'count': 32})
        self.page.get_by_text('LATEST message 31', exact=True).wait_for(state='attached', timeout=8500)
        self.assertGreater(len(self.history_requests()), before_requests, 'Must observe a real polling update')
        self.assertLessEqual(abs(anchor.bounding_box()['y']-before_y), 8, 'INV-WSESS-15: update retains reader anchor')

    def test_INV_WSESS_15_down_resumes_follow_on_real_new_data(self):
        self.open_history()
        self.activate('up'); self.activate('down', 1)
        before_requests = len(self.history_requests())
        private_json(self.evidence / 'control.json', {'delay': 0, 'count': 28})
        self.page.get_by_text('LATEST message 27', exact=True).wait_for(state='attached', timeout=8500)
        self.page.wait_for_timeout(250)
        self.assertGreater(len(self.history_requests()), before_requests, 'Must observe a real polling update')
        result = self.metrics()
        self.assertLessEqual(result['max']-result['y'], 80, 'INV-WSESS-15: down restores newest-message follow')


    def assert_manual_return_follows_update(self, input_kind):
        self.open_history()
        self.activate('up')
        # Browser-delivered wheel/End is trusted user input. Keep focus on the
        # navigation button so End scrolls the document rather than a textarea.
        events = []
        self.page.expose_function('navigationInputEvidence', lambda kind, trusted: events.append((kind, trusted)))
        self.page.evaluate("""() => {
            for (const kind of ['keydown','wheel']) document.addEventListener(kind,
                event => window.navigationInputEvidence(kind,event.isTrusted), {capture:true});
        }""")
        if input_kind == 'End':
            self.buttons('up').first.focus()
            self.page.keyboard.press('End')
        else:
            self.page.mouse.move(1100, 500)
            self.page.mouse.wheel(0, self.metrics()['max'] + 900)
        self.assert_extreme('down')
        self.assertIn(('keydown' if input_kind == 'End' else 'wheel', True), events,
                      'Manual return must use trusted browser input')
        before_requests = len(self.history_requests())
        private_json(self.evidence / 'control.json', {'delay': 0, 'count': 28})
        self.page.get_by_text('LATEST message 27', exact=True).wait_for(state='attached', timeout=8500)
        self.page.wait_for_timeout(250)
        self.assertGreater(len(self.history_requests()), before_requests, 'Must observe a real polling update')
        result = self.metrics()
        private_json(self.evidence / ('manual-return-' + input_kind + '.json'), {'input': input_kind, 'events': events, **result})
        self.assertLessEqual(result['max']-result['y'], 80,
                             'INV-WSESS-15: trusted manual return restores follow without explicit down: ' + repr(result))

    def test_INV_WSESS_15_manual_End_after_up_restores_follow(self):
        self.assert_manual_return_follows_update('End')

    def test_INV_WSESS_15_manual_wheel_after_up_restores_follow(self):
        self.assert_manual_return_follows_update('wheel')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--serve': serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else: unittest.main(verbosity=2)
