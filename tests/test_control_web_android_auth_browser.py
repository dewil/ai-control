"""Source-blind real-page tests for the narrow AndroidAuth bridge contract.

Synthetic local server/browser fixture only. Production JS is loaded by the
browser; this test never reads its source or overrides application functions.
"""
import re
import unittest
import test_control_web_compact_chat_browser as compact
from control_browser_helpers import choose_project


# INV-AUTHAND-04 INV-AUTHAND-05 INV-AUTHAND-06
class AndroidAuthBrowserContract(unittest.TestCase):
    open_history = compact.CompactChatBrowserContract.open_history
    history_requests = compact.CompactChatBrowserContract.history_requests

    def setUp(self):
        # Cookie logout invalidates the server session too; each case needs its
        # own authenticated server rather than a cloned, already revoked cookie.
        class Fixture(compact.CompactChatBrowserContract):
            pass
        self.addCleanup(Fixture.doClassCleanups)
        Fixture.setUpClass()
        self.browser = Fixture.browser
        self.url = Fixture.url
        self.fixture_cookies = Fixture.context.cookies()
        self.case_context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.addCleanup(self.case_context.close)
        self.case_context.add_cookies(self.fixture_cookies)
        self.page = self.case_context.new_page()
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(5000)
        self.network = []
        self.page.on('request', lambda request: self.network.append(
            {'method': request.method, 'url': request.url, 'headers': request.headers,
             'body': request.post_data}))
        self.page.add_init_script('''
            window.androidCalls = [];
            window.AndroidAuth = {
                requestAuth: (...args) => window.androidCalls.push({method:'auth',args}),
                requestLogout: (...args) => window.androidCalls.push({method:'logout',args})
            };
        ''')
        self.page.goto(self.url)
        # INV-APP-02: mimic native cookie-sync completion, exactly one initial CSRF GET.
        self.page.evaluate("window.aiControlAndroidResume()")
        self.page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(
            self.page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).click()
        choose_project(self.page, 'demo')
        self.session = self.page.get_by_role('button', name=re.compile('Compact synthetic session'))
        self.session.wait_for()
        self.open_history()
        self.page.locator('textarea').fill('Synthetic unsent draft survives Android auth')

    def posts(self):
        return [request for request in self.network if request['method'] == 'POST']

    def send_button(self):
        return self.page.get_by_role('button', name=re.compile('^Отправить$', re.I))

    def fail_send(self):
        self.page.route('**/api/session-send', lambda route: route.fulfill(
            status=401, content_type='application/json', body='{"error":"unauthorized"}'))
        self.send_button().click()
        self.page.wait_for_timeout(500)

    def draft(self):
        self.assertEqual(self.page.locator('textarea').count(), 1,
                         'Android 401 must retain the live page and draft')
        return self.page.locator('textarea').input_value()

    def test_android_401_requests_noarg_native_auth_preserves_draft_no_post_replay(self):
        before = self.draft()
        self.fail_send()
        calls = self.page.evaluate('window.androidCalls')
        self.assertTrue(any(call == {'method': 'auth', 'args': []} for call in calls),
                        '401 must signal only no-argument native requestAuth')
        self.assertEqual(self.draft(), before)
        count = len(self.posts())
        histories = len([r for r in self.network if '/api/session-history?' in r['url']])
        self.page.wait_for_timeout(6200)
        self.assertEqual(len([r for r in self.network if '/api/session-history?' in r['url']]),
                         histories, 'Android auth wait must suspend polling')
        self.assertEqual(len(self.posts()), count, 'failed mutation must never be replayed')
        self.assertEqual(count, 1)

    def test_fixed_resume_get_refreshes_csrf_before_next_explicit_send(self):
        before = self.draft()
        self.assertEqual(self.page.evaluate('typeof window.aiControlAndroidResume'), 'function',
                         'native requires the fixed no-argument resume entry point')
        csrf = 'synthetic-replacement-csrf'

        def replaced_session(route):
            response = route.fetch()
            body = response.json()
            body['csrf'] = csrf
            route.fulfill(response=response, json=body)

        self.page.route('**/api/session', replaced_session)
        start = len(self.network)
        self.page.evaluate('window.aiControlAndroidResume()')
        self.page.wait_for_timeout(600)
        session_gets = [r for r in self.network[start:] if r['url'].endswith('/api/session')]
        self.assertEqual([r['method'] for r in session_gets], ['GET'],
                         'resume must fetch CSRF through exactly one GET')
        self.assertEqual(self.posts(), [], 'resume cannot replay any mutation')
        self.assertEqual(self.draft(), before)
        self.page.route('**/api/session-send', lambda route: route.fulfill(
            status=503, content_type='application/json', body='{"error":"unavailable"}'))
        self.send_button().click()
        self.page.wait_for_timeout(300)
        sends = [r for r in self.posts() if r['url'].endswith('/api/session-send')]
        self.assertEqual(len(sends), 1, 'one explicit user send after recovery')
        self.assertEqual(sends[0]['headers'].get('x-csrf-token'), csrf)

    def test_late_401_after_resume_preserves_live_draft(self):
        self.assertEqual(self.page.evaluate('typeof window.aiControlAndroidResume'), 'function')
        self.page.evaluate('window.aiControlAndroidResume()')
        self.page.wait_for_timeout(400)
        before = self.draft()
        self.fail_send()
        self.assertEqual(self.draft(), before)
        self.assertIn({'method': 'auth', 'args': []}, self.page.evaluate('window.androidCalls'))
        self.assertEqual(len(self.posts()), 1)

    def test_android_logout_delegates_to_native_before_cookie_logout(self):
        self.page.get_by_role('button', name=re.compile('^Выйти$', re.I)).click()
        self.page.wait_for_timeout(300)
        self.assertIn({'method': 'logout', 'args': []}, self.page.evaluate('window.androidCalls'),
                      'Android logout must first delegate durable revoke to native')
        self.assertFalse(any('/api/logout' in r['url'] for r in self.posts()),
                         'JS cannot discard working cookie before native pending marker')

    def test_browser_without_bridge_still_signs_out_on_401(self):
        self.page.evaluate('delete window.AndroidAuth')
        self.fail_send()
        self.assertTrue(self.page.locator('input[type=password]').is_visible(),
                        'ordinary browser retains its existing signed-out flow')
        self.assertEqual(self.page.evaluate('window.androidCalls'), [])
        self.assertEqual(len(self.posts()), 1)


if __name__ == '__main__':
    unittest.main()
