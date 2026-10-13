"""Blind INV-PSTAB-03/04 browser contracts; synthetic HTTP, no native writes.

Designed only from 2026-10-14-spec-panel-stability.md and existing browser
fixtures. Visibility events model the web lifecycle, not physical Android.
"""
import json
import re
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
        expect(self.page.get_by_role('status').filter(has_text=re.compile(
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
        expect(self.page.get_by_role('status').filter(has_text=re.compile(
            'недоступ|отсутств|больше|выбран|каталог', re.I))).to_be_visible()
        self.assertEqual(self.send_requests(), [])

    def test_INV_PSTAB_03_sse_reconnect_after_error_refreshes_once_without_post(self):
        # Observe actual native EventSource instances, retaining all browser
        # behaviour. Only public lifecycle events are injected by this test.
        self.page.add_init_script("""(() => {
            const NativeSource = window.EventSource;
            window.__catalogSources = [];
            window.EventSource = class extends NativeSource {
                constructor(...args) {super(...args); window.__catalogSources.push(this);}
            };
        })()""")
        self.page.reload()
        self.page.get_by_role('button', name='Сессии', exact=True).or_(
            self.page.get_by_role('tab', name='Сессии', exact=True)).click()
        choose_project(self.page, 'demo')
        calls = self.catalog_sequence([(200, fixture.available())])
        self.choose_pair()
        self.assertGreater(self.page.evaluate('window.__catalogSources.length'), 0,
                           'SSE fixture must actually observe a browser EventSource')
        self.page.evaluate("""() => {
            const source=window.__catalogSources[window.__catalogSources.length-1];
            source.dispatchEvent(new Event('error'));
            source.dispatchEvent(new Event('open'));
        }""")
        self.await_calls(calls, 2)
        self.assert_pair_draft()
        expect(self.send_button()).to_be_enabled()
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
