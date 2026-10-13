"""Blind INV-PSTAB-03/04 browser contracts; synthetic HTTP, no native writes.

Designed only from 2026-10-14-spec-panel-stability.md and existing browser
fixtures. Visibility events model the web lifecycle, not physical Android.
"""
import json
import re
import time
import unittest

from playwright.sync_api import expect
import test_control_web_model_controls_browser as fixture
from control_browser_helpers import choose_project, session_navigator


class SendRecoveryStabilityContract(unittest.TestCase):
    setUpClass = classmethod(fixture.ModelControlsBrowserContract.setUpClass.__func__)
    stop_server = classmethod(fixture.ModelControlsBrowserContract.stop_server.__func__)
    setUp = fixture.ModelControlsBrowserContract.setUp
    tearDown = fixture.ModelControlsBrowserContract.tearDown
    calls = fixture.ModelControlsBrowserContract.calls
    open_alpha = fixture.ModelControlsBrowserContract.open_alpha
    assert_controls = fixture.ModelControlsBrowserContract.assert_controls
    wait_for_option = fixture.ModelControlsBrowserContract.wait_for_option
    send_button = fixture.ModelControlsBrowserContract.send_button
    send_requests = fixture.ModelControlsBrowserContract.send_requests

    def catalog_sequence(self, replies):
        calls = []
        def handler(route):
            self.assertEqual(route.request.method, 'GET', 'Catalog recovery must remain read-only')
            calls.append(route)
            reply = replies[min(len(calls) - 1, len(replies) - 1)]
            if reply is None:
                return  # Intentionally hold the response until test releases it.
            status, body = reply
            route.fulfill(status=status, json=body)
        self.page.route('**/api/session-models?*', handler)
        return calls

    def choose_pair(self):
        self.open_alpha()
        model, effort = self.assert_controls()
        self.wait_for_option('Model Alpha')
        model.select_option(label='Model Alpha')
        effort.select_option(label='high')
        self.page.locator('textarea').fill('Preserve this synthetic draft')
        expect(self.send_button()).to_be_enabled()
        return model, effort

    def assert_pair_draft(self):
        model, effort = self.assert_controls()
        self.assertEqual(model.input_value(), 'alpha-ui')
        self.assertEqual(effort.input_value(), 'high')
        self.assertEqual(self.page.locator('textarea').input_value(), 'Preserve this synthetic draft')

    def visibility(self, visible):
        self.page.evaluate('''visible => {
            Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>visible?'visible':'hidden'});
            Object.defineProperty(document,'hidden',{configurable:true,get:()=>!visible});
            document.dispatchEvent(new Event('visibilitychange'));
        }''', visible)
        self.page.wait_for_timeout(80)

    def tick(self, ms):
        self.page.clock.fast_forward(ms)
        self.page.wait_for_timeout(100)

    def await_calls(self, calls, count):
        # Poll a browser-observable counter using real event-loop time while
        # browser application timers remain under Playwright's virtual clock.
        for _ in range(30):
            if len(calls) >= count:
                break
            self.page.wait_for_timeout(25)
        self.assertEqual(len(calls), count, 'INV-PSTAB-03 requires exactly one bounded recovery GET')

    def test_INV_PSTAB_03_explicit_ttl_refresh_restores_send_and_preserves_pair_draft(self):
        self.page.clock.install()
        calls = self.catalog_sequence([(200, fixture.available(expires_in_ms=1000)),
                                       (200, fixture.available(catalog_id='b'*64))])
        self.choose_pair()
        self.tick(1100)
        self.await_calls(calls, 2)
        self.assert_pair_draft()
        expect(self.send_button()).to_be_enabled()
        self.assertEqual(self.send_requests(), [])
        self.send_button().click()
        expect(self.page.get_by_role('status').filter(has_text=re.compile('принято', re.I))).to_be_visible()
        self.assertEqual(json.loads(self.send_requests()[0].post_data)['selection'],
                         {'catalog_id': 'b'*64, 'model_id': 'alpha-ui', 'effort': 'high'})

    def foreground_contract(self, width):
        self.page.set_viewport_size({'width': width, 'height': 844})
        calls = self.catalog_sequence([(200, fixture.available())])
        self.choose_pair()
        self.visibility(False)
        self.visibility(True)
        self.await_calls(calls, 2)
        self.assert_pair_draft()
        expect(self.send_button()).to_be_enabled()
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_03_desktop_foreground_one_read_preserves_draft(self):
        self.foreground_contract(1280)

    def test_INV_PSTAB_03_android_sized_foreground_one_read_preserves_draft(self):
        self.foreground_contract(360)

    def test_INV_PSTAB_03_foreground_and_expiry_coalesce_while_read_pending(self):
        self.page.clock.install()
        calls = self.catalog_sequence([(200, fixture.available(expires_in_ms=1000)), None])
        self.choose_pair()
        self.visibility(False)
        self.visibility(True)
        self.await_calls(calls, 2)
        self.tick(1100)
        self.assertEqual(len(calls), 2, 'TTL and foreground share one in-flight catalog read')
        self.assertFalse(self.send_button().is_enabled(), 'Expired explicit pair waits for a checked lease')
        calls[1].fulfill(status=200, json=fixture.available())
        expect(self.send_button()).to_be_enabled()
        self.assert_pair_draft()
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_03_failed_refresh_no_timer_loop_and_explicit_retry_recovers(self):
        self.page.clock.install()
        calls = self.catalog_sequence([(200, fixture.available(expires_in_ms=1000)),
                                       (503, {'error': 'unavailable'}), (200, fixture.available())])
        self.choose_pair()
        self.tick(1100)
        self.await_calls(calls, 2)
        self.assert_pair_draft()
        expect(self.send_button()).to_be_disabled()
        expect(self.page.locator('#model-status').filter(has_text=re.compile(
            'недоступ|не удалось|ошиб|обнов', re.I))).to_be_visible()
        self.tick(120000)
        self.assertEqual(len(calls), 2, 'Failed read must not schedule a retry timer')
        refresh = self.page.get_by_role('button', name=re.compile('обнов.*модел|обнов.*каталог', re.I))
        expect(refresh).to_be_visible()
        expect(refresh).to_be_enabled()
        refresh.click()
        self.await_calls(calls, 3)
        expect(self.send_button()).to_be_enabled()
        self.assert_pair_draft()
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_03_background_ttl_does_not_read_until_foreground(self):
        self.page.clock.install()
        calls = self.catalog_sequence([(200, fixture.available(expires_in_ms=1000)), (200, fixture.available())])
        self.choose_pair()
        self.visibility(False)
        self.tick(3000)
        self.assertEqual(len(calls), 1, 'Hidden page must not refresh expired explicit selection')
        self.visibility(True)
        self.await_calls(calls, 2)
        expect(self.send_button()).to_be_enabled()
        self.assert_pair_draft()

    def test_INV_PSTAB_03_successful_lease_may_refresh_again_after_its_own_ttl(self):
        self.page.clock.install()
        calls = self.catalog_sequence([(200, fixture.available(expires_in_ms=1000)),
                                       (200, fixture.available(expires_in_ms=1000)),
                                       (200, fixture.available())])
        self.choose_pair()
        self.tick(1100)
        self.await_calls(calls, 2)
        self.tick(1100)
        self.await_calls(calls, 3)
        self.assert_pair_draft()
        expect(self.send_button()).to_be_enabled()
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_03_removed_pair_stays_visible_unavailable_and_does_not_inherit(self):
        self.page.clock.install()
        beta_only = fixture.available([{'id': 'beta-ui', 'label': 'Model Beta',
            'efforts': ['medium'], 'default_effort': 'medium', 'is_default': True}])
        calls = self.catalog_sequence([(200, fixture.available(expires_in_ms=1000)), (200, beta_only)])
        self.choose_pair()
        self.tick(1100)
        self.await_calls(calls, 2)
        self.assert_pair_draft()
        expect(self.send_button()).to_be_disabled()
        expect(self.page.locator('#model-status').filter(has_text=re.compile(
            'недоступ|отсутств|больше|выбран|каталог', re.I))).to_be_visible()
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_03_sse_reconnect_after_error_refreshes_once_without_post(self):
        # A real native stream closes, then the documented JSON snapshot and
        # new stream restore the connection. An open event on a closed source
        # is a late callback and cannot represent a successful reconnect.
        import live_sse_blind_support as live
        server = live.Fixture(transport=True)
        self.addCleanup(server.stop)
        server.login()
        context = self.browser.new_context(viewport={'width': 390, 'height': 844})
        self.addCleanup(context.close)
        name, value = server.cookie.split('=', 1)
        context.add_cookies([{'name': name, 'value': value, 'url': server.origin}])
        self.page.close()
        self.page = context.new_page()
        self.addCleanup(self.page.close)
        self.url = server.origin
        self.network = []
        self.page.on('request', lambda request: self.network.append(request))
        self.page.on('pageerror', lambda error: self.errors.append(type(error).__name__))
        self.page.goto(self.url)
        self.page.get_by_role('button', name='Сессии', exact=True).or_(
            self.page.get_by_role('tab', name='Сессии', exact=True)).click()
        choose_project(self.page, 'demo')
        self.alpha_session = self.page.get_by_role('button', name=re.compile('LIVE synthetic A'))
        calls = self.catalog_sequence([(200, fixture.available())])
        self.choose_pair()
        server.transport.emit(live.snapshot())
        expect(self.page.locator('#current-model-status')).to_contain_text('producer-A')
        server.transport.close = True
        deadline = time.monotonic() + 5
        while server.transport.closed < 1 and time.monotonic() < deadline:
            self.page.wait_for_timeout(25)
        self.assertGreaterEqual(server.transport.closed, 1, 'Actual SSE must close before reconnect')
        server.transport.close = False
        deadline = time.monotonic() + 7
        while server.transport.streams < 2 and time.monotonic() < deadline:
            self.page.wait_for_timeout(25)
        self.assertGreaterEqual(server.transport.streams, 2, 'Reconnect must use a new native EventSource')
        server.transport.emit(live.snapshot(2))
        self.await_calls(calls, 2)
        self.page.wait_for_timeout(250)
        self.assertEqual(len(calls), 2, 'A single reconnect must not duplicate catalog reads')
        self.assert_pair_draft()
        expect(self.send_button()).to_be_enabled()
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_03_pending_recovery_aborts_at_10s_and_manual_retry_is_available(self):
        # Public fetch AbortSignal observation proves the network operation is
        # cancelled, independently from merely changing a loading caption.
        self.page.clock.install()
        self.page.evaluate("""() => {
            const originalFetch = window.fetch;
            window.__catalogDeadlineSignals = [];
            window.fetch = function(input, options = {}) {
                const url = new URL(typeof input === 'string' ? input : input.url, location.href);
                if (url.pathname === '/api/session-models') {
                    const signal = options.signal || (typeof input === 'object' ? input.signal : null);
                    const observed = {aborted: !!signal?.aborted};
                    window.__catalogDeadlineSignals.push(observed);
                    signal?.addEventListener('abort', () => observed.aborted = true, {once: true});
                }
                return originalFetch.apply(this, arguments);
            };
        }""")
        beta_only = fixture.available([{'id': 'beta-ui', 'label': 'Model Beta',
            'efforts': ['medium'], 'default_effort': 'medium', 'is_default': True}])
        calls = self.catalog_sequence([(200, fixture.available(expires_in_ms=1000)), None,
                                       (200, fixture.available()), (200, beta_only)])
        self.choose_pair()
        self.tick(1100)
        self.await_calls(calls, 2)
        self.tick(10001)
        self.assertTrue(self.page.evaluate('window.__catalogDeadlineSignals[1].aborted'),
                        'INV-PSTAB-03: catalog request must abort within the accepted 10000ms budget')
        expect(self.send_button()).to_be_disabled()
        self.assert_pair_draft()
        refresh = self.page.get_by_role('button', name=re.compile('обнов.*модел|обнов.*каталог', re.I))
        expect(refresh).to_be_visible()
        expect(refresh).to_be_enabled()
        expect(self.page.locator('#model-status')).to_contain_text(re.compile(
            'недоступ|не удалось|ошиб|обнов|время', re.I))
        self.tick(120000)
        self.assertEqual(len(calls), 2, 'Timed out recovery cannot start an automatic retry loop')
        refresh.click()
        self.await_calls(calls, 3)
        expect(self.send_button()).to_be_enabled()
        self.assert_pair_draft()
        session_navigator(self.page)
        self.beta_session.click()
        self.wait_for_option('Model Beta')
        calls[1].fulfill(status=200, json=fixture.available())
        self.page.wait_for_timeout(150)
        model, _ = self.assert_controls()
        self.assertNotIn('Model Alpha', model.locator('option').all_text_contents(),
                         'An aborted old read cannot replace a different selected session')
        self.assertEqual(self.page.locator('textarea').input_value(), '')
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_03_inherit_expiry_requires_no_refresh(self):
        self.page.clock.install()
        calls = self.catalog_sequence([(200, fixture.available(expires_in_ms=1000))])
        self.open_alpha()
        self.wait_for_option('Model Alpha')
        self.page.locator('textarea').fill('Inherit draft')
        self.tick(3000)
        self.assertEqual(len(calls), 1)
        expect(self.send_button()).to_be_enabled()
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_03_stale_send_refreshes_read_without_reposting(self):
        fixture.private_json(self.evidence / 'control.json', {'send_status': 'stale'})
        calls = self.catalog_sequence([(200, fixture.available()), (200, fixture.available(catalog_id='c'*64))])
        self.choose_pair()
        self.send_button().click()
        self.await_calls(calls, 2)
        expect(self.send_button()).to_be_enabled()
        self.assert_pair_draft()
        self.page.wait_for_timeout(250)
        self.assertEqual(len(self.send_requests()), 1, 'Stale recovery cannot repeat the POST')

    def test_INV_PSTAB_03_late_recovery_response_cannot_replace_new_session(self):
        calls = self.catalog_sequence([(200, fixture.available()), None,
                                       (200, fixture.available([{'id': 'beta-ui', 'label': 'Model Beta',
                                           'efforts': ['medium'], 'default_effort': 'medium', 'is_default': True}]))])
        self.choose_pair()
        self.visibility(False)
        self.visibility(True)
        self.await_calls(calls, 2)
        session_navigator(self.page)
        self.beta_session.click()
        model, _ = self.assert_controls()
        self.wait_for_option('Model Beta')
        calls[1].fulfill(status=200, json=fixture.available())
        self.page.wait_for_timeout(200)
        self.assertNotIn('Model Alpha', model.locator('option').all_text_contents())
        self.assertEqual(self.page.locator('textarea').input_value(), '')
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_04_catalog_refresh_keeps_unknown_locked_until_manual_resolution(self):
        fixture.private_json(self.evidence / 'control.json', {'send_status': 'delivery_unknown',
                                                           'checked_status': 'accepted'})
        calls = self.catalog_sequence([(200, fixture.available())])
        self.choose_pair()
        self.send_button().click()
        check = self.page.get_by_role('button', name='Проверить доставку', exact=True)
        expect(check).to_be_visible()
        self.visibility(False)
        self.visibility(True)
        self.await_calls(calls, 2)
        self.assert_pair_draft()
        expect(check).to_be_visible()
        expect(self.send_button()).to_be_disabled()
        self.assertEqual(len(self.send_requests()), 1)
        check.click()
        expect(check).to_have_count(0)
        self.page.locator('textarea').fill('Fresh draft after resolved delivery')
        expect(self.send_button()).to_be_enabled()
        self.assertEqual(len(self.send_requests()), 1, 'Resolving delivery must not resend the original')


if __name__ == '__main__':
    unittest.main(verbosity=2)
