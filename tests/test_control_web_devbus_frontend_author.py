"""Public frontend regressions for shared admission and actual IO ownership."""
import asyncio
import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from playwright.sync_api import expect
from control_browser_helpers import choose_project
import live_devbus_blind_support as s
import test_control_web_devbus_main_browser_red as browser_fixture


class FrontendOwnership(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = s.BusBackend()
        self.frontend = s.seam(self, '_control_web', 'DevbusFrontend')(self.backend)

    async def asyncTearDown(self):
        self.backend.bus_gate.set()
        await self.frontend.close()

    async def until(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        self.assertTrue(predicate())

    async def test_TTL_starts_when_worker_enters_not_before_thread_startup(self):
        await self.frontend.close()
        now = [0.0]
        self.frontend = s.seam(self, '_control_web', 'DevbusFrontend')(self.backend, clock=lambda:now[0])
        submit = ThreadPoolExecutor.submit
        def delayed_submit(pool, *args, **kwargs):
            now[0] = .5
            return submit(pool, *args, **kwargs)
        with patch.object(ThreadPoolExecutor, 'submit', delayed_submit):
            self.assertEqual(await self.frontend.overview(), self.backend.bus_value)
        now[0] = 1.1
        self.assertEqual(await self.frontend.overview(), self.backend.bus_value)
        self.assertEqual(len(self.backend.bus_calls), 1)

    async def test_cancelled_only_waiter_never_populates_cache(self):
        self.backend.bus_gate.clear()
        waiter = asyncio.create_task(self.frontend.overview())
        await self.until(lambda: self.backend.bus_active == 1)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.backend.bus_gate.set()
        await self.until(lambda: self.backend.bus_active == 0)
        self.assertEqual(await self.frontend.overview(), self.backend.bus_value)
        self.assertEqual(len(self.backend.bus_calls), 2)
        self.assertEqual(self.backend.bus_maximum, 1)

    async def test_close_reports_live_thread_after_bounded_wait_and_prevents_new_reads(self):
        self.backend.bus_gate.clear()
        waiter = asyncio.create_task(self.frontend.overview())
        await self.until(lambda: self.backend.bus_active == 1)
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'devbus owner did not stop'):
            await self.frontend.close()
        self.assertGreaterEqual(time.monotonic() - started, 6.8)
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual(self.backend.bus_active, 1)
        self.assertEqual(await waiter, {'error': 'unavailable'})
        self.assertEqual(await self.frontend.overview(), {'error': 'unavailable'})
        self.assertEqual(len(self.backend.bus_calls), 1)
        self.backend.bus_gate.set()
        await self.frontend.close()

    async def test_filter_change_fences_late_cache_and_close_fences_new_admission(self):
        self.backend.bus_gate.clear()
        waiter = asyncio.create_task(self.frontend.overview(task='task1'))
        await self.until(lambda: self.backend.bus_active == 1)
        self.assertIn(await self.frontend.overview(task='task2'),
                      ({'error': 'busy'}, {'error': 'unavailable'}))
        self.backend.bus_gate.set()
        await waiter
        await self.frontend.overview(task='task1')
        self.assertEqual(len(self.backend.bus_calls), 2)
        await self.frontend.close()
        self.assertEqual(await self.frontend.overview(), {'error': 'unavailable'})
        self.assertEqual(len(self.backend.bus_calls), 2)


class SharedHttpAdmission(s.HttpCase):
    def stream(self, sid):
        connection, response = self.fixture.request('/api/session-events?project=demo&sid=' + sid,
                                                     headers=[('Accept', 'text/event-stream')])
        self.addCleanup(connection.close)
        self.assertEqual(response.status, 200)
        s.live.event(response)

    def test_two_active_live_scopes_do_not_reject_another_cookie_BUS(self):
        self.stream(s.live.SID)
        self.stream(s.live.OTHER)
        self.fixture.login()
        response, value = self.response()
        self.assertEqual(response.status, 200)
        self.assertEqual(value, self.backend.bus_value)
        self.assertEqual(len(self.backend.bus_calls), 1)

    def test_global_eight_stream_budget_includes_BUS_even_with_fresh_cookie(self):
        for index in range(4):
            if index:
                self.fixture.login()
            self.stream(s.live.SID)
            self.stream(s.live.SID)
        self.fixture.login()
        self.expect_error(429)
        self.assertEqual(self.backend.bus_calls, [])


class FrontendBrowserAuthor(s.HttpCase):
    setUpClass = classmethod(browser_fixture.BusMainBrowserBlind.setUpClass.__func__)
    def setUp(self):
        super().setUp()
        self.context = self.browser.new_context(viewport={'width':390, 'height':844}, has_touch=True)
        self.addCleanup(self.context.close)
        name, value = self.fixture.cookie.split('=', 1)
        self.context.add_cookies([dict(name=name, value=value, url=self.fixture.origin)])
        self.page = self.context.new_page()
        self.page.set_default_timeout(3000)
        self.errors, self.requests = [], []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('request', lambda request: self.requests.append(request))
    tearDown = browser_fixture.BusMainBrowserBlind.tearDown
    until = browser_fixture.BusMainBrowserBlind.until

    def open(self, android=False):
        if android:
            self.page.add_init_script('window.syntheticAuth=[];window.syntheticLogout=0;window.AndroidAuth={requestAuth:(...args)=>syntheticAuth.push(args),requestLogout:()=>syntheticLogout++};')
        self.page.goto(self.fixture.origin)
        if android:
            self.assertTrue(self.page.evaluate('window.aiControlAndroidResume()'))
        expect(self.page.get_by_role('tab', name='Шина', exact=True)).to_be_visible(timeout=4000)

    def enter_bus(self):
        self.page.get_by_role('tab', name='Шина', exact=True).click()
        expect(self.page.get_by_text('BUS synthetic result', exact=True)).to_have_count(1, timeout=4000)

    def visibility(self, value):
        self.page.evaluate("value=>{Object.defineProperty(document,'visibilityState',{configurable:true,value});document.dispatchEvent(new Event('visibilitychange'));}", value)

    def test_visible_BUS_waits_for_fresh_auth_admission_and_failed_restore_clears_data(self):
        self.open(); self.enter_bus()
        self.visibility('hidden')
        expect(self.page.locator('#devbus-root')).to_be_empty()
        pending = []
        self.page.route('**/api/session', lambda route: pending.append(route))
        self.visibility('visible')
        self.until(lambda: bool(pending))
        count = len(self.backend.bus_calls)
        self.page.wait_for_timeout(250)
        self.assertEqual(len(self.backend.bus_calls), count)
        pending.pop().fulfill(status=401, content_type='application/json', body='{"error":"unauthorized"}')
        expect(self.page.locator('#login')).to_be_visible()
        self.page.wait_for_timeout(2200)
        self.assertEqual(len(self.backend.bus_calls), count)
        expect(self.page.locator('#devbus-root')).to_be_empty()

    def test_stale_failed_admission_cannot_clear_a_newer_authenticated_mount(self):
        self.open(); self.enter_bus()
        self.visibility('hidden')
        pending = []
        self.page.route('**/api/session', lambda route: pending.append(route))
        self.visibility('visible')
        self.until(lambda: len(pending) == 1)
        self.page.get_by_role('tab', name='Задачи', exact=True).click()
        self.page.get_by_role('tab', name='Шина', exact=True).click()
        self.until(lambda: len(pending) == 2)
        csrf = self.fixture.sessions[self.fixture.cookie.split('=', 1)[1]]['csrf']
        pending[1].fulfill(status=200, content_type='application/json', body=json.dumps({'csrf':csrf}))
        expect(self.page.get_by_text('BUS synthetic result', exact=True)).to_have_count(1, timeout=4000)
        pending[0].fulfill(status=503, content_type='application/json', body='{"error":"unavailable"}')
        # Wait for the old admission response to finish, then the next normal BUS poll.
        count = len(self.backend.bus_calls)
        self.until(lambda: len(self.backend.bus_calls) > count, timeout=3)
        expect(self.page.get_by_text('BUS synthetic result', exact=True)).to_have_count(1)

    def test_LIVE_and_BUS_share_one_native_owner403_latch_and_preserve_draft(self):
        self.open(android=True)
        self.page.get_by_role('tab', name='Сессии', exact=True).click()
        choose_project(self.page, 'demo')
        self.page.get_by_role('button', name='LIVE synthetic A', exact=False).click()
        expect(self.page.get_by_text('LIVE original synthetic text', exact=True)).to_have_count(1)
        self.page.locator('#chat-draft').fill('Synthetic retained native auth draft')
        self.fixture.sessions[self.fixture.cookie.split('=', 1)[1]]['principal'] = 'project'
        self.until(lambda: self.page.evaluate('syntheticAuth.length') == 1, timeout=7)
        self.page.get_by_role('tab', name='Шина', exact=True).click()
        self.until(lambda: any('/api/devbus/overview' in request.url for request in self.requests))
        self.page.wait_for_timeout(2300)
        self.assertEqual(self.page.evaluate('syntheticAuth'), [[]])
        expect(self.page.locator('#devbus-root')).to_be_empty()
        self.assertEqual(self.page.locator('#chat-draft').input_value(), 'Synthetic retained native auth draft')

    def test_native_resume_on_BUS_avoids_retained_chat_and_logout_stops_before_bridge(self):
        self.open(android=True)
        self.page.get_by_role('tab', name='Сессии', exact=True).click()
        choose_project(self.page, 'demo')
        self.page.get_by_role('button', name='LIVE synthetic A', exact=False).click()
        expect(self.page.get_by_text('LIVE original synthetic text', exact=True)).to_have_count(1)
        self.enter_bus()
        before = len(self.requests)
        self.assertTrue(self.page.evaluate('window.aiControlAndroidResume()'))
        expect(self.page.get_by_text('BUS synthetic result', exact=True)).to_have_count(1)
        self.assertFalse(any('/api/session-history?' in row.url or '/api/session-events?' in row.url
                             for row in self.requests[before:]))
        self.page.get_by_role('button', name='Выйти', exact=True).click()
        self.assertEqual(self.page.evaluate('syntheticLogout'), 1)
        expect(self.page.locator('#devbus-root')).to_be_empty()
        count = len(self.backend.bus_calls)
        self.page.wait_for_timeout(2300)
        self.assertEqual(len(self.backend.bus_calls), count)
