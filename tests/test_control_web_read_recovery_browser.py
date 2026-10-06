"""INV-WSESS-18/03: blind bounded cold read recovery, synthetic browser only.

Design frozen from 37f76a3 normative contract, before application source reads.
Public HTTP routes and DOM are observations; no real account/provider calls.
"""
import copy
import json
from pathlib import Path
import re
import unittest

import test_control_web_project_cloud_browser as cloud
from test_control_web_chat_width_browser import PASSWORD, SID, totp


def summaries(state='fresh', high=17, low=99):
    rows = cloud.project_rows()
    for row in rows:
        if row['name'] != 'down':
            row.update(summary_state=state, session_count=None if state == 'unknown' else 0,
                       last_activity=None, as_of=None if state == 'unknown' else 1800000000)
    for row in rows:
        if row['name'] in ('high', 'loww') and state == 'fresh':
            row.update(session_count=high if row['name'] == 'high' else low,
                       last_activity=500 if row['name'] == 'high' else 600)
    return {'projects': rows}


IO_PROBE = """(() => {
const originalFetch=window.fetch, originalSet=window.setTimeout, originalClear=window.clearTimeout;
const signals=new WeakMap();let next=0;const timers=new Map();
window.__readRecoveryIO={reads:[],timers};
window.fetch=function(input,options={}) {
 const url=new URL(typeof input==='string'?input:input.url,location.href);
 if(['/api/session-project-summary','/api/sessions'].includes(url.pathname)) {
  const signal=options.signal || (typeof input==='object'?input.signal:null);
  if(signal&&!signals.has(signal))signals.set(signal,++next);
  window.__readRecoveryIO.reads.push({path:url.pathname,signal:signal?signals.get(signal):null});
 }
 return originalFetch.apply(this,arguments);
};
window.setTimeout=function(fn,delay,...args) {
 let id;id=originalSet.call(this,(...values)=>{timers.delete(id);fn(...values)},delay,...args);
 if(delay===30000)timers.set(id,delay);return id;
};
window.clearTimeout=function(id){timers.delete(id);return originalClear.call(this,id)};
})()"""


class ReadRecoveryBrowserContract(unittest.TestCase):
    setUpClass = classmethod(cloud.ProjectCloudBrowserContract.setUpClass.__func__)
    stop_server = classmethod(cloud.ProjectCloudBrowserContract.stop_server.__func__)
    control = cloud.ProjectCloudBrowserContract.control
    tile = cloud.ProjectCloudBrowserContract.tile
    choose_sort = cloud.ProjectCloudBrowserContract.choose_sort

    def setUp(self):
        self.control(projects=summaries()['projects'])
        self.page = self.context.new_page()
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(3000)
        self.page.add_init_script(IO_PROBE)
        self.network = []
        self.errors = []
        self.page.on('request', lambda request: self.network.append((request.method, request.url)))
        self.page.on('pageerror', lambda error: self.errors.append(type(error).__name__))
        self.page.goto(self.url)
        if self.page.locator('input[type=password]').is_visible():
            self.login()
        self.page.get_by_role('button', name='Сессии', exact=True).or_(
            self.page.get_by_role('tab', name='Сессии', exact=True)).click()
        self.page.wait_for_timeout(200)
        self.tile('high').wait_for()
        self.network.clear()
        self.page.evaluate('window.__readRecoveryIO.reads.length=0')

    def login(self):
        self.page.locator('input[type=password]').fill(PASSWORD)
        self.page.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        self.page.get_by_role('button', name='Войти', exact=True).click()
        self.page.get_by_role('button', name='Сессии', exact=True).or_(
            self.page.get_by_role('tab', name='Сессии', exact=True)).wait_for()

    def tearDown(self):
        self.assertEqual(self.errors, [], 'public browser execution must have no JS exceptions')
        self.assertFalse(any(url.split('/')[2] != self.url.split('/')[2] for _, url in self.network))

    def route_sequence(self, endpoint, replies):
        calls = []
        def handler(route):
            calls.append((route.request.method, route.request.url))
            reply = replies[min(len(calls) - 1, len(replies) - 1)]
            if reply == 'abort':
                route.abort('failed')
            else:
                status, body = reply
                route.fulfill(status=status, content_type='application/json',
                              body=json.dumps(body) if not isinstance(body, str) else body)
        pattern = '**/api/' + endpoint + '*'
        self.page.route(pattern, handler)
        self.addCleanup(self.page.unroute, pattern, handler)
        return calls

    def refresh(self):
        self.page.get_by_role('button', name='Обновить проекты', exact=True).click()
        self.page.wait_for_timeout(300)

    def quiet(self):
        self.page.wait_for_timeout(300)
        self.assertFalse(any(method == 'POST' for method, url in self.network), 'read recovery must not create mutations')
        self.assertFalse(any('/api/session-history' in url for method, url in self.network),
                         'project metadata refresh must not load history')

    def test_unknown_then_fresh_two_gets_whole_counts_and_sort(self):
        calls = self.route_sequence('session-project-summary', [(200, summaries('unknown')), (200, summaries())])
        self.refresh()
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(method == 'GET' for method, url in calls))
        self.assertRegex(self.tile('high').inner_text(), r'\b17\b')
        self.assertRegex(self.tile('loww').inner_text(), r'\b99\b')
        positions = [self.tile(name).evaluate('el=>[...document.querySelectorAll("button")].indexOf(el)')
                     for name in ('loww', 'high')]
        self.assertLess(positions[0], positions[1], 'fresh numeric counts must drive existing sorting')
        self.quiet()
        self.assertEqual(len(calls), 2, 'no third request/poll after recovery')

    def test_unknown_then_unknown_honest_and_bounded(self):
        calls = self.route_sequence('session-project-summary', [(200, summaries('unknown'))])
        self.refresh()
        self.assertEqual(len(calls), 2)
        self.assertNotRegex(self.tile('high').inner_text(), r'\b0\b')
        self.assertRegex(self.page.locator('body').inner_text(), '(?i)неизвест|не удалось|ошиб')
        self.assertTrue(self.page.get_by_role('button', name='Обновить проекты', exact=True).is_enabled())
        self.quiet()
        self.assertEqual(len(calls), 2)

    def test_confirmed_zero_and_null_activity_do_not_retry(self):
        body = summaries(high=0, low=4)
        for row in body['projects']:
            row['last_activity'] = None
        calls = self.route_sequence('session-project-summary', [(200, body)])
        self.refresh()
        self.assertEqual(len(calls), 1)
        self.assertRegex(self.tile('high').inner_text(), r'\b0\b')
        self.quiet()
        self.assertEqual(len(calls), 1)

    def test_all_unavailable_no_retry_or_fake_counts(self):
        body = summaries('unknown')
        for row in body['projects']:
            row['summary_state'] = 'unavailable'
        calls = self.route_sequence('session-project-summary', [(200, body)])
        self.refresh()
        self.assertEqual(len(calls), 1)
        self.assertNotRegex(self.tile('high').inner_text(), r'\b0\b')
        self.quiet()

    def test_summary_error_transport_and_malformed_do_not_retry(self):
        cases = [(503, {'error': 'unavailable'}), (409, {'error': 'stale'}),
                 (200, '{malformed'), (200, {'projects': 'malformed'}), 'abort']
        for reply in cases:
            with self.subTest(reply=reply):
                calls = self.route_sequence('session-project-summary', [reply])
                self.refresh()
                self.assertEqual(len(calls), 1)
                self.page.unroute('**/api/session-project-summary*')
        self.quiet()

    def test_summary_recovery_uses_single_abort_deadline_and_cleans_timer(self):
        self.route_sequence('session-project-summary', [(200, summaries('unknown')), (200, summaries())])
        self.refresh()
        evidence = self.page.evaluate('({reads:window.__readRecoveryIO.reads,timers:window.__readRecoveryIO.timers.size})')
        reads = [r for r in evidence['reads'] if r['path'] == '/api/session-project-summary']
        self.assertEqual(len(reads), 2)
        self.assertIsNotNone(reads[0]['signal'])
        self.assertEqual(reads[0]['signal'], reads[1]['signal'], 'both attempts share original AbortController')
        self.assertEqual(evidence['timers'], 0, '30s deadline must be cleared after success')

    def session_success(self, title='Recovered synthetic session'):
        return {'rows': [{'sid': SID, 'title': title, 'status': 'idle'}], 'has_more': False}

    def test_session_explicit_409_stale_then_success_exact_same_get(self):
        calls = self.route_sequence('sessions', [(409, {'error': 'stale'}), (200, self.session_success())])
        self.tile('high').click()
        self.page.wait_for_timeout(300)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1], 'retry must preserve exact project/page URL and GET')
        self.page.get_by_role('button', name='Recovered synthetic session', exact=False).wait_for()
        self.quiet()
        self.assertEqual(len(calls), 2)

    def test_session_stale_then_stale_no_third_and_manual_refresh_visible(self):
        calls = self.route_sequence('sessions', [(409, {'error': 'stale'})])
        self.tile('high').click()
        self.page.wait_for_timeout(500)
        self.assertEqual(len(calls), 2)
        self.assertRegex(self.page.locator('body').inner_text(), '(?i)устар|stale|ошиб|не удалось')
        self.assertTrue(self.page.get_by_role('button', name=re.compile('обнов', re.I)).count())
        self.quiet()
        self.assertEqual(len(calls), 2)

    def test_session_other_errors_and_non409_stale_do_not_retry(self):
        for status, error in [(503, 'unavailable'), (409, 'unavailable'), (400, 'stale'), (500, 'stale')]:
            with self.subTest(status=status, error=error):
                calls = self.route_sequence('sessions', [(status, {'error': error})])
                self.tile('high').click()
                self.page.wait_for_timeout(300)
                self.assertEqual(len(calls), 1)
                self.page.unroute('**/api/sessions*')
                self.tile('loww').click()
                self.page.wait_for_timeout(100)
        self.quiet()

    def test_session_retry_preserves_shared_deadline_and_cleans_timer(self):
        self.route_sequence('sessions', [(409, {'error': 'stale'}), (200, self.session_success())])
        self.tile('high').click()
        self.page.wait_for_timeout(300)
        evidence = self.page.evaluate('({reads:window.__readRecoveryIO.reads,timers:window.__readRecoveryIO.timers.size})')
        reads = [r for r in evidence['reads'] if r['path'] == '/api/sessions']
        self.assertEqual(len(reads), 2)
        self.assertIsNotNone(reads[0]['signal'])
        self.assertEqual(reads[0]['signal'], reads[1]['signal'])
        self.assertEqual(evidence['timers'], 0)

    def test_changed_project_before_first_stale_does_not_dispatch_old_retry(self):
        held = []
        calls = []
        def handler(route):
            calls.append(route.request.url)
            if 'project=high' in route.request.url:
                held.append(route)
            else:
                route.fulfill(status=200, json=self.session_success('CURRENT LOW SESSION'))
        self.page.route('**/api/sessions*', handler)
        self.tile('high').click()
        self.page.wait_for_timeout(100)
        self.assertEqual(len(held), 1)
        self.tile('loww').click()
        self.page.get_by_role('button', name='CURRENT LOW SESSION', exact=False).wait_for()
        held[0].fulfill(status=409, json={'error': 'stale'})
        self.page.wait_for_timeout(250)
        self.assertEqual(sum('project=high' in url for url in calls), 1)
        self.assertEqual(self.tile('loww').get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.page.get_by_role('button', name='CURRENT LOW SESSION', exact=False).count(), 1)

    def test_changed_project_during_retry_discards_old_rows(self):
        held = []
        high_calls = []
        def handler(route):
            if 'project=high' in route.request.url:
                high_calls.append(route.request.url)
                if len(high_calls) == 1:
                    route.fulfill(status=409, json={'error': 'stale'})
                else:
                    held.append(route)
            else:
                route.fulfill(status=200, json=self.session_success('CURRENT LOW SESSION'))
        self.page.route('**/api/sessions*', handler)
        self.tile('high').click()
        self.page.wait_for_timeout(200)
        self.assertEqual(len(held), 1, 'actual retry must reach controlled second response')
        self.tile('loww').click()
        self.page.get_by_role('button', name='CURRENT LOW SESSION', exact=False).wait_for()
        held[0].fulfill(status=200, json=self.session_success('OBSOLETE HIGH SESSION'))
        self.page.wait_for_timeout(250)
        self.assertEqual(self.page.get_by_role('button', name='OBSOLETE HIGH SESSION', exact=False).count(), 0)
        self.assertEqual(len(high_calls), 2)
        self.assertEqual(self.tile('loww').get_attribute('aria-pressed'), 'true')

    def test_logout_before_unknown_summary_response_never_dispatches_retry(self):
        held = []
        self.page.route('**/api/session-project-summary*', lambda route: held.append(route))
        self.page.get_by_role('button', name='Обновить проекты', exact=True).click()
        self.page.wait_for_timeout(100)
        self.assertEqual(len(held), 1)
        self.page.get_by_role('button', name=re.compile('^(Выйти|Выход)$')).click()
        self.page.locator('input[type=password]').wait_for()
        held[0].fulfill(status=200, json=summaries('unknown'))
        self.page.wait_for_timeout(250)
        self.assertEqual(len(held), 1)
        self.assertEqual(self.page.get_by_role('button', name='Обновить проекты', exact=True).count(), 0)

    def test_auth_failure_summary_has_no_retry_and_cleans_deadline(self):
        calls = self.route_sequence('session-project-summary', [(401, {'error': 'unauthorized'})])
        self.refresh()
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.page.evaluate('window.__readRecoveryIO.timers.size'), 0)

    def test_project_refresh_does_not_replay_send_or_selected_history(self):
        self.tile('high').click()
        self.page.get_by_role('button', name='Cloud synthetic session', exact=False).click()
        self.page.get_by_text('CLOUD SYNTHETIC HISTORY', exact=True).wait_for()
        sends = self.route_sequence('session-send', [(503, {'error': 'unavailable'})])
        self.page.locator('textarea').fill('own synthetic message')
        self.page.get_by_role('button', name='Отправить', exact=True).click()
        self.page.wait_for_timeout(300)
        self.assertEqual(len(sends), 1)
        self.network.clear()
        calls = self.route_sequence('session-project-summary', [(200, summaries('unknown')), (200, summaries())])
        self.refresh()
        self.assertEqual(len(calls), 2)
        self.quiet()
        self.assertEqual(len(sends), 1, 'readonly retry never retries failed POST')


if __name__ == '__main__':
    unittest.main(verbosity=2)
