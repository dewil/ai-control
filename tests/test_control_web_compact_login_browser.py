"""Source-blind geometry and semantic checks for the compact login card.

The browser receives the real HTML and CSS as local assets. Scripts and external
resources are not executed; hidden product regions are exposed only in the
synthetic page. No login, network, API, or user profile is involved.
"""
import os
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML_ASSET = ROOT / 'bin' / '_control_web.html'
CSS_ASSET = ROOT / 'bin' / '_control_web.css'


class CompactLoginBrowserContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.html = HTML_ASSET.read_text(encoding='utf-8')
        cls.css = CSS_ASSET.read_text(encoding='utf-8')
        # Keep this a passive DOM fixture: do not execute page scripts or load
        # linked resources. CSS is attached directly from the checked-in asset.
        cls.html = re.sub(r'<script\b[^>]*>.*?</script\s*>', '', cls.html,
                          flags=re.IGNORECASE | re.DOTALL)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_COMPACT_LOGIN_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(
            headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 900})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_content(self.html, wait_until='domcontentloaded')
        self.page.add_style_tag(content=self.css)
        # Render the existing hidden login and workspace in a synthetic DOM.
        # No handlers are invoked and no authentication state is created.
        self.page.evaluate("""() => {
          for (const id of ['login', 'workspace']) {
            const el = document.getElementById(id);
            if (el) { el.hidden = false; el.removeAttribute('hidden'); el.style.display = 'block'; }
          }
        }""")

    def _geometry(self):
        return self.page.evaluate("""() => {
          const rect = el => { const r = el.getBoundingClientRect(); return {
            left:r.left, right:r.right, top:r.top, bottom:r.bottom,
            width:r.width, height:r.height
          }; };
          const login = document.querySelector('#login');
          const main = document.querySelector('main');
          const workspace = document.querySelector('#workspace');
          const fields = [...document.querySelectorAll('#login input, #login button')];
          return {
            viewport: innerWidth,
            documentWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
            login: login && rect(login), main: main && rect(main),
            workspace: workspace && rect(workspace),
            controls: fields.map(el => ({tag:el.tagName, type:el.type, rect:rect(el)}))
          };
        }""")

    def test_INV_LOGIN_01_desktop_login_card_is_centered_and_workspace_stays_wide(self):
        self.page.set_viewport_size({'width': 1440, 'height': 900})
        observed = self._geometry()
        self.assertIsNotNone(observed['login'], 'Expected #login in real HTML')
        self.assertIsNotNone(observed['main'], 'Expected main content region in real HTML')
        main = observed['main']
        login = observed['login']
        self.assertLessEqual(login['width'], 448.5,
                             f'Login card exceeds 28rem at 16px root font: {login}')
        self.assertLessEqual(abs((login['left'] + login['right']) / 2 -
                                 (main['left'] + main['right']) / 2), 1,
                             f'Login card is not centered within main content: {observed}')
        self.assertIsNotNone(observed['workspace'], 'Expected #workspace in real HTML')
        self.assertGreaterEqual(observed['workspace']['width'], 1000,
                                f'Workspace was constrained with login: {observed}')
        for control in observed['controls']:
            self.assertGreater(control['rect']['width'], 0, f'Invisible login control: {control}')
            self.assertGreaterEqual(control['rect']['left'], login['left'] - 1,
                                    f'Control begins outside login card: {control}')
            self.assertLessEqual(control['rect']['right'], login['right'] + 1,
                                 f'Control extends outside login card: {control}')

    def test_INV_LOGIN_01_mobile_login_fits_without_horizontal_overflow(self):
        for width in (320, 390):
            with self.subTest(viewport=width):
                self.page.set_viewport_size({'width': width, 'height': 800})
                observed = self._geometry()
                self.assertLessEqual(observed['documentWidth'], width + 1,
                                     f'Horizontal overflow at {width}px: {observed}')
                login = observed['login']
                self.assertGreater(login['width'], 0, f'Login card is not visible at {width}px')
                for control in observed['controls']:
                    self.assertGreater(control['rect']['width'], 0,
                                       f'Invisible login control at {width}px: {control}')
                    self.assertGreaterEqual(control['rect']['left'], login['left'] - 1,
                                            f'Control begins outside login at {width}px: {control}')
                    self.assertLessEqual(control['rect']['right'], login['right'] + 1,
                                         f'Control extends outside login at {width}px: {control}')

    def test_INV_LOGIN_02_password_and_totp_semantics_are_preserved(self):
        password = self.page.locator('#login input[type="password"]')
        totp = self.page.locator('#login input[autocomplete="one-time-code"]')
        self.assertEqual(password.count(), 1, 'Expected existing password input')
        self.assertEqual(password.get_attribute('autocomplete'), 'current-password')
        self.assertEqual(totp.count(), 1, 'Expected existing one-time-code input')
        self.assertEqual(totp.get_attribute('maxlength'), '6')
        self.assertEqual(totp.get_attribute('inputmode'), 'numeric')


if __name__ == '__main__':
    unittest.main()
