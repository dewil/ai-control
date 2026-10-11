"""Independent INV-WFILE04/05 browser contracts from the frozen file-viewer spec.

Only spec/public test fixtures read. Real authenticated app, history and Markdown;
project_file is the documented injection seam. Held routes affect only file GETs.
No providers, real project files, external origins or production state are used.
"""
from copy import deepcopy
import re
import unittest
from urllib.parse import parse_qsl, urlsplit, urljoin

from playwright.sync_api import expect, sync_playwright
from control_browser_helpers import choose_project, project_is_selected
import live_sse_blind_support as live


class FileBackend(live.Backend):
    def __init__(self):
        super().__init__()
        self.markdown = ''
        self.file_value = dict(name='test.md', text='FILE CONTENT', truncated=False)
        self.file_calls = []

    def session_projects(self):
        return {'projects': [{'name': name} for name in ('demo', 'other')]}

    def session_project_summary(self):
        return {'projects': [dict(name=name, session_count=3, last_activity=1770000000,
                                 summary_state='fresh', as_of=1770000000)
                             for name in ('demo', 'other')]}

    def session_history(self, project, sid, cursor):
        return live.history(self.markdown, item='file-history-' + project + '-' + sid)

    def session_live_snapshot(self, project, sid):
        return {'schema': 1, 'scope_id': ('1' if project == 'demo' else '2') * 64,
                'history': self.session_history(project, sid, None)}

    def project_file(self, project, path):
        self.file_calls.append((project, path))
        return deepcopy(self.file_value)


class ProjectFileBrowserRED(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        original = live.Backend
        live.Backend = FileBackend
        try:
            self.fixture = live.Fixture(session_store=True)
        finally:
            live.Backend = original
        self.addCleanup(self.fixture.stop)
        self.fixture.login()
        self.backend = self.fixture.backend
        self.context = self.browser.new_context(viewport=dict(width=390, height=900))
        self.addCleanup(self.context.close)
        name, value = self.fixture.cookie.split('=', 1)
        self.context.add_cookies([dict(name=name, value=value, url=self.fixture.origin)])
        self.page = self.context.new_page()
        self.page.set_default_timeout(1800)
        self.requests, self.errors = [], []
        self.page.on('request', lambda r: self.requests.append(r))
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        # Deliberately remove the file-fetch abort signal to independently test
        # generation fences against responses which survive cancellation.
        self.page.add_init_script('''const realFetch=window.fetch.bind(window);
          window.fetch=(input,init={})=>String(input).includes('/api/project-file')?
            realFetch(input,{...init,signal:undefined}):realFetch(input,init);''')

    def tearDown(self):
        self.assertEqual(self.errors, [], 'Viewer must not introduce runtime errors')
        self.assertFalse(any(urlsplit(r.url).netloc != urlsplit(self.fixture.origin).netloc
                             for r in self.requests), 'Fixture must remain on loopback origin')

    def tab(self, name):
        return self.page.get_by_role('tab', name=name, exact=True).or_(
            self.page.get_by_role('button', name=name, exact=True))

    def render(self, markdown):
        self.backend.markdown = markdown + '\n\nFILE HISTORY READY'
        self.page.goto(self.fixture.origin)
        self.tab('Сессии').click()
        choose_project(self.page, 'demo')
        self.page.get_by_role('button', name=re.compile('LIVE synthetic A')).click()
        expect(self.page.get_by_text('FILE HISTORY READY', exact=True)).to_be_attached()
        self.assertTrue(project_is_selected(self.page, 'demo'))
        self.assertEqual(self.page.locator('textarea').count(), 1,
                         'Authenticated real history and selected chat must be ready')

    def link(self, name):
        link = self.page.get_by_role('link', name=name, exact=True)
        self.assertEqual(link.count(), 1, 'File destination must render an accessible active link')
        return link

    def viewer(self):
        dialog = self.page.get_by_role('dialog')
        for _ in range(30):
            if dialog.count(): break
            self.page.wait_for_timeout(20)
        self.assertEqual(dialog.count(), 1, 'Local file click must open a viewer, not navigate to a site404')
        expect(dialog).to_be_visible()
        self.assertTrue(dialog.get_attribute('aria-label') or dialog.get_attribute('aria-labelledby'),
                        'File viewer requires an accessible name')
        return dialog

    def activate(self, name='FILE LINK', keyboard=False):
        link = self.link(name)
        if keyboard:
            link.focus(); self.page.keyboard.press('Enter')
        else:
            link.click(no_wait_after=True)
        return self.viewer()

    def close(self):
        self.viewer().get_by_role('button', name=re.compile('Закрыть|Close', re.I)).click()
        expect(self.page.get_by_role('dialog')).to_be_hidden()

    def gets(self):
        return [r for r in self.requests if urlsplit(r.url).path == '/api/project-file']

    def until(self, predicate):
        for _ in range(90):
            if predicate(): return
            self.page.wait_for_timeout(20)
        self.assertTrue(predicate(), 'Expected bounded public viewer outcome')

    def hold(self):
        held = []
        self.page.route('**/api/project-file?*', lambda route: held.append(route))
        return held

    def deliver(self, route, text):
        route.fulfill(status=200, json=dict(name='test.md', text=text, truncated=False))
        self.page.wait_for_timeout(60)

    def test_absolute_file_uri_relative_spaces_and_single_decode_use_exact_get(self):
        # INV-WFILE04 INV-WFILE05: all supported forms, including Enter.
        cases = [('/srv/demo/test.md:12', '/srv/demo/test.md'),
                 ('file:///srv/demo/test.md#L12', '/srv/demo/test.md'),
                 ('docs/test.md#L12', 'docs/test.md'),
                 ('./docs/test.md:12', './docs/test.md'),
                 ('</srv/demo/my file.md:12>', '/srv/demo/my file.md'),
                 ('/srv/demo/my%20file.md#L12', '/srv/demo/my file.md'),
                 ('docs/literal%2520name.md', 'docs/literal%20name.md')]
        for index, (destination, expected_path) in enumerate(cases):
            with self.subTest(destination=destination):
                self.render('[FILE LINK](' + destination + ')')
                before = len(self.gets())
                dialog = self.activate(keyboard=index % 2 == 1)
                expect(dialog.get_by_text('FILE CONTENT', exact=True)).to_be_visible()
                self.assertIn('test.md', dialog.inner_text(), 'Viewer must show the file name')
                self.assertEqual(len(self.gets()), before + 1)
                request = self.gets()[-1]
                self.assertEqual(request.method, 'GET')
                self.assertCountEqual(parse_qsl(urlsplit(request.url).query),
                                      [('project', 'demo'), ('path', expected_path)])
                self.assertEqual(self.backend.file_calls[-1], ('demo', expected_path))
                self.assertEqual(self.page.url, self.fixture.origin + '/')
                self.close()

    def test_reserved_site_http_and_unsafe_destinations_keep_markdown_policy(self):
        # INV-WFILE04: site/download links stay links; unsafe forms stay inert.
        safe = [('HTTPS', 'https://example.invalid/doc.md'),
                ('HTTP', 'http://example.invalid/doc.md'), ('DOWNLOAD', '/download/android/app.apk'),
                ('API', '/api/status'), ('LOGIN', '/login'), ('LOGOUT', '/logout'),
                ('SITE', '/web-help')]
        unsafe = ['file://remote.invalid/etc/test.md', 'file://user@host/test.md',
                  '//remote.invalid/test.md', 'docs/a%5Cb.md', 'docs/a%00b.md',
                  'docs/a%ZZ.md', 'javascript:alert(1)', 'data:text/html,hello']
        self.render('\n\n'.join('[%s](%s)' % pair for pair in safe) + '\n\n' +
                    '\n\n'.join('[BAD%d](%s)' % (i, target) for i, target in enumerate(unsafe)))
        for label, destination in safe:
            link = self.link(label)
            self.assertEqual(urljoin(self.fixture.origin, link.get_attribute('href')),
                             urljoin(self.fixture.origin, destination))
            self.assertEqual(link.get_attribute('target'), '_blank')
            self.assertTrue({'noopener', 'noreferrer'} <= set((link.get_attribute('rel') or '').split()))
        for i in range(len(unsafe)):
            self.assertEqual(self.page.get_by_role('link', name='BAD%d' % i, exact=True).count(), 0,
                             'Invalid/authority/control destinations must never become active file or web links')
        self.assertEqual(self.gets(), [])

    def test_literal_text_xss_and_mobile_viewport_containment(self):
        # INV-WFILE05: real response literal text; horizontal overflow inside pre.
        text = '<script>window.fileXSS=1</script>\n<img src="/file-probe" onerror="window.fileXSS=2">\n' + 'LONG_' * 600
        self.backend.file_value = dict(name='test.md', text=text, truncated=False)
        self.render('[FILE LINK](/srv/demo/test.md)')
        dialog = self.activate()
        expect(dialog.get_by_text(re.compile('window.fileXSS=1')).first).to_be_visible()
        self.assertIn(text, dialog.text_content())
        self.assertEqual(dialog.locator('script,img,iframe,svg,[onerror],[onload]').count(), 0)
        self.assertIsNone(self.page.evaluate('window.fileXSS'))
        self.assertFalse(any(urlsplit(r.url).path == '/file-probe' for r in self.requests))
        for width in (320, 390, 1280):
            with self.subTest(width=width):
                self.page.set_viewport_size(dict(width=width, height=900))
                box = dialog.bounding_box()
                self.assertGreater(box['width'], 100)
                self.assertGreaterEqual(box['x'], -1)
                self.assertLessEqual(box['x'] + box['width'], width + 1)
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                close = dialog.get_by_role('button', name=re.compile('Закрыть|Close', re.I))
                expect(close).to_be_visible(); close.focus()
                self.assertTrue(close.evaluate('e=>document.activeElement===e'))

    def test_line_is_highlighted_scrolled_inside_viewer_and_chat_anchor_is_stable(self):
        # INV-WFILE05: target is far below fold, chat comparison uses same anchor
        # before/after opening with unchanged history, never an absolute Y oracle.
        self.backend.file_value = dict(name='test.md', text='\n'.join('FILE LINE %03d' % n for n in range(1, 501)), truncated=False)
        self.render('\n\n'.join('Chat paragraph %03d' % n for n in range(80)) +
                    '\n\n[FILE LINK](/srv/demo/test.md:400)')
        link = self.link('FILE LINK'); link.scroll_into_view_if_needed()
        before = link.bounding_box()
        dialog = self.activate()
        line = dialog.get_by_text('FILE LINE 400', exact=True)
        expect(line).to_be_visible()
        geometry = line.evaluate('''e=>{let s=e.parentElement;
          while(s && !(s.scrollHeight>s.clientHeight+20 && /auto|scroll/.test(getComputedStyle(s).overflowY)))s=s.parentElement;
          if(!s)return null;const a=e.getBoundingClientRect(),b=s.getBoundingClientRect(),c=getComputedStyle(e);
          return {scroll:s.scrollTop,inside:!!s.closest('[role=dialog],dialog'),visible:a.top>=b.top-2&&a.bottom<=b.bottom+2,
            marked:e.tagName==='MARK'||e.getAttribute('aria-current')==='location'||
              (c.backgroundColor!=='rgba(0, 0, 0, 0)'&&c.backgroundColor!=='transparent')};}''')
        self.assertIsNotNone(geometry, 'Long file requires an internal scroll container')
        self.assertTrue(geometry['inside']); self.assertGreater(geometry['scroll'], 0)
        self.assertTrue(geometry['visible']); self.assertTrue(geometry['marked'], 'Requested line must have visible highlighting')
        after = link.bounding_box()
        self.assertAlmostEqual(before['y'], after['y'], delta=2, msg='Viewer line jump must preserve chat viewport anchor')
        self.close()
        self.assertAlmostEqual(before['y'], link.bounding_box()['y'], delta=2)

    def test_truncated_and_missing_requested_line_are_explicit(self):
        # INV-WFILE05: visible prefix notice and unavailable line, no full-file claim.
        self.backend.file_value = dict(name='test.md', text='ONLY PREFIX LINE', truncated=True)
        self.render('[FILE LINK](docs/test.md#L999)')
        dialog = self.activate()
        expect(dialog.get_by_text('ONLY PREFIX LINE', exact=True)).to_be_visible()
        self.assertRegex(dialog.inner_text(), r'(?i)первые\s*48\s*(?:КБ|KiB)')
        self.assertRegex(dialog.inner_text(), r'(?i)строк[^\n]*(?:нет|отсутств|недоступ|не (?:найден|показан|входит))|(?:нет|недоступ)[^\n]*строк')

    def test_typed_error_stays_in_viewer_preserving_draft_history_and_selection(self):
        # INV-WFILE05: endpoint errors are user-visible without losing chat state.
        self.page.clock.install()
        self.render('[FILE LINK](docs/test.md)')
        self.page.locator('textarea').fill('UNSENT DRAFT')
        self.page.route('**/api/project-file?*', lambda route: route.fulfill(
            status=415, json={'error': 'unsupported_type'}))
        dialog = self.activate()
        expect(dialog.get_by_text(re.compile('не поддерж|неподдерж|недоступ|ошиб', re.I)).first).to_be_visible()
        self.assertEqual(self.page.locator('textarea').input_value(), 'UNSENT DRAFT')
        self.assertTrue(project_is_selected(self.page, 'demo'))
        expect(self.page.get_by_text('FILE HISTORY READY', exact=True)).to_be_attached()
        self.page.clock.fast_forward(120000); self.page.wait_for_timeout(80)
        self.assertEqual(len(self.gets()), 1, 'Error must not automatically retry or poll')

    def test_close_clears_content_and_rejects_late_response(self):
        # INV-WFILE05: signal deliberately removed; late-response fencing required.
        self.render('[FILE LINK](docs/test.md)')
        held = self.hold(); dialog = self.activate(); self.until(lambda: len(held) == 1)
        expect(dialog.get_by_text(re.compile('загруз|loading', re.I)).first).to_be_visible()
        self.close(); self.deliver(held[0], 'CLOSED STALE CONTENT')
        expect(self.page.get_by_role('dialog')).to_be_hidden()
        self.assertNotIn('CLOSED STALE CONTENT', self.page.locator('body').text_content())
        self.assertEqual(len(self.gets()), 1)

    def test_new_click_rejects_previous_response_even_after_latest_content(self):
        # INV-WFILE05: dispatch the public second link click under the modal to
        # isolate replacement from the separately tested close cancellation.
        self.render('[FILE LINK](docs/first.md) and [SECOND FILE](docs/second.md)')
        held = self.hold(); self.activate(); self.until(lambda: len(held) == 1)
        self.link('SECOND FILE').dispatch_event('click')
        self.until(lambda: len(held) == 2)
        self.deliver(held[1], 'LATEST SECOND CONTENT')
        expect(self.viewer().get_by_text('LATEST SECOND CONTENT', exact=True)).to_be_visible()
        self.deliver(held[0], 'STALE FIRST CONTENT')
        expect(self.viewer().get_by_text('LATEST SECOND CONTENT', exact=True)).to_be_visible()
        self.assertNotIn('STALE FIRST CONTENT', self.page.locator('body').text_content())

    def test_project_and_session_changes_clear_viewer_and_fence_delayed_result(self):
        # INV-WFILE04 INV-WFILE05: scope cannot drift to later project/selection.
        for scope in ('project', 'session'):
            with self.subTest(scope=scope):
                self.render('[FILE LINK](docs/test.md)')
                held = self.hold(); self.activate(); self.until(lambda: len(held) == 1)
                # Dispatch a public control's click to isolate the selection
                # handler from close cancellation even if the dialog is modal.
                # No private runtime function or forced pointer through inert UI.
                target = r'^other(?:\b|\s)' if scope == 'project' else 'LIVE synthetic B'
                self.page.get_by_role('button', name=re.compile(target), include_hidden=True).dispatch_event('click')
                self.deliver(held[0], 'OLD SCOPE CONTENT')
                expect(self.page.get_by_role('dialog')).to_be_hidden()
                self.assertNotIn('OLD SCOPE CONTENT', self.page.locator('body').text_content())
                query = dict(parse_qsl(urlsplit(self.gets()[-1].url).query))
                self.assertEqual(query['project'], 'demo')
                self.page.unroute('**/api/project-file?*')

    def test_logout_invalidates_inflight_content(self):
        # INV-WFILE05: old authenticated response cannot outlive principal.
        self.render('[FILE LINK](docs/test.md)')
        held = self.hold(); self.activate(); self.until(lambda: len(held) == 1)
        # Public logout handler isolated while a modal blocks physical clicks.
        self.page.get_by_role('button', name='Выйти', exact=True).dispatch_event('click')
        expect(self.page.get_by_role('button', name='Войти', exact=True)).to_be_visible()
        self.deliver(held[0], 'PREVIOUS OWNER CONTENT')
        self.assertNotIn('PREVIOUS OWNER CONTENT', self.page.locator('body').text_content())
        expect(self.page.get_by_role('dialog')).to_be_hidden()

    def test_background_clears_viewer_and_foreground_does_not_reread(self):
        # INV-WFILE05: background cancellation, no automatic read on return.
        self.page.clock.install()
        self.render('[FILE LINK](docs/test.md)')
        held = self.hold(); self.activate(); self.until(lambda: len(held) == 1)
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
        expect(self.page.get_by_role('dialog')).to_be_hidden()
        self.deliver(held[0], 'BACKGROUND STALE CONTENT')
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('pageshow'))")
        self.page.clock.fast_forward(300000); self.page.wait_for_timeout(80)
        self.assertNotIn('BACKGROUND STALE CONTENT', self.page.locator('body').text_content())
        self.assertEqual(len(self.gets()), 1, 'Foreground must require a new explicit click')


if __name__ == '__main__':
    unittest.main()
