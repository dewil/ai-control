"""INV-WEB-13 actual browser DOM contract; no source-string assertions."""
import json
import os
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'synthetic-owner-password'


class LoginNameBrowserContract(unittest.TestCase):
    """Exercise real DOM assets and browser submission; no source-string assertions."""
    # INV-WEB-13
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.html_path = ROOT / 'bin' / '_control_web.html'
        cls.css_path = ROOT / 'bin' / '_control_web.css'
        cls.js_path = ROOT / 'bin' / '_control_web.js'
        cls.html = cls.html_path.read_text(encoding='utf-8')
        cls.css = cls.css_path.read_text(encoding='utf-8')
        cls.js = cls.js_path.read_text(encoding='utf-8')
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_COMPACT_LOGIN_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(
            headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 390, 'height': 844})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(2000)
        self.page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body='<html></html>'))
        self.page.goto('https://control.example.test/', wait_until='domcontentloaded')
        self.posts = []
        self.page.route('**/api/**', self._api)
        html = re.sub(r'<script\b[^>]*>.*?</script\s*>', '', self.html,
                      flags=re.IGNORECASE | re.DOTALL)
        self.page.set_content(html, wait_until='domcontentloaded')
        self.page.add_style_tag(content=self.css)
        self.page.add_script_tag(content=self.js)
        self.page.evaluate("""() => {
          for (const id of ['login', 'workspace']) {
            const el = document.getElementById(id);
            if (el) { el.hidden = false; el.removeAttribute('hidden'); el.style.display = 'block'; }
          }
        }""")

    def _api(self, route):
        request = route.request
        if request.method == 'POST' and request.url.endswith('/api/login'):
            self.posts.append(json.loads(request.post_data or '{}'))
            route.fulfill(status=401, content_type='application/json', body='{"error":"unauthorized"}')
        else:
            route.fulfill(status=401, content_type='application/json', body='{"error":"unauthorized"}')

    def test_username_semantics_order_and_browser_posts_username(self):
        username = self.page.locator('#login input[name="username"]')
        self.assertEqual(username.count(), 1)
        self.assertEqual(username.get_attribute('id'), 'username')
        self.assertEqual(username.get_attribute('autocomplete'), 'username')
        self.assertEqual(username.get_attribute('autocapitalize'), 'none')
        self.assertTrue(username.evaluate('(el) => el.required'))
        self.assertEqual(username.input_value(), '', 'Personal account must not be hardcoded')
        self.assertEqual(username.get_attribute('minlength'), '2')
        self.assertEqual(username.get_attribute('maxlength'), '32')
        self.assertTrue(username.get_attribute('pattern'), 'Username grammar must be exposed')
        password = self.page.locator('#login input[type="password"]')
        totp = self.page.locator('#login input[autocomplete="one-time-code"]')
        self.assertEqual(password.get_attribute('autocomplete'), 'current-password')
        self.assertEqual(totp.count(), 1)
        self.assertLess(username.bounding_box()['y'], password.bounding_box()['y'])

    def test_browser_payload_requires_username_and_never_persists_it(self):
        username = self.page.locator('#login input[name="username"]')
        self.assertEqual(username.count(), 1, 'Required login field is absent')
        password = self.page.locator('#login input[type="password"]')
        totp = self.page.locator('#login input[autocomplete="one-time-code"]')
        password.fill(PASSWORD)
        totp.fill('123456')
        self.page.locator('#login button[type="submit"]').click()
        self.page.wait_for_timeout(100)
        self.assertEqual(self.posts, [], 'Browser must prevent empty username submission')
        order = self.page.locator('#login input').evaluate_all('(els) => els.map(el => el.name)')
        self.assertEqual(order[:3], ['username', 'password', 'totp'])
        username.fill('dwl')
        password.fill(PASSWORD)
        totp.fill('123456')
        self.page.locator('#login button[type="submit"]').click()
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.posts), 1, 'Form submission must reach the login API')
        self.assertEqual(set(self.posts[0]), {'username', 'password', 'totp'})
        self.assertEqual(self.posts[0]['username'], 'dwl')
        self.assertFalse(self.page.evaluate("""() =>
          [localStorage, sessionStorage].some(s => Object.keys(s).some(k => s.getItem(k)?.includes('dwl')))
        """))

    def test_login_controls_fit_at_phone_widths_and_desktop(self):
        for width in (320, 390, 1440):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 900})
                observed = self.page.evaluate("""() => {
                  const card = document.querySelector('#login').getBoundingClientRect();
                  const controls = [...document.querySelectorAll('#login input, #login button')]
                    .map(e => e.getBoundingClientRect());
                  return {doc: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
                    card: {left:card.left,right:card.right,width:card.width},
                    controls:controls.map(r => ({left:r.left,right:r.right,width:r.width}))};
                }""")
                self.assertLessEqual(observed['doc'], width + 1, observed)
                self.assertLessEqual(observed['card']['width'], min(width, 448.5) + 1, observed)
                for control in observed['controls']:
                    self.assertGreater(control['width'], 0, observed)
                    self.assertGreaterEqual(control['left'], observed['card']['left'] - 1, observed)
                    self.assertLessEqual(control['right'], observed['card']['right'] + 1, observed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
