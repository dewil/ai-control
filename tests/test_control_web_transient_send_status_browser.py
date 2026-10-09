"""INV-WSESS-16/17: source-blind transient send status, synthetic backend only."""
# Accepted INV-WSESS-47/48 (2026-10-08-spec-live-observability-package.md):
# empty statuses collapse; nonempty accepted status remains visible in normal flow.

from control_browser_helpers import choose_project
from control_live_legacy_fixture import LiveHistoryFixture, replay_path, observe_snapshots
import importlib
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
import urllib.request
import unittest

import test_control_web_compact_chat_browser as compact
from test_control_web_compact_chat_browser import OTHER
from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET, SID

ROOT = Path(__file__).resolve().parents[1]


def publish_ready(evidence, origin):
    ready = evidence / 'ready.json'
    temporary = evidence / f'.ready-{os.getpid()}.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump({'url': origin}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, ready)
    finally:
        temporary.unlink(missing_ok=True)


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root / 'bin'))
    web = importlib.import_module('_control_web')

    # INV-WSESS-53: actual public LIVE backend replaces legacy automatic polling.
    class Backend(LiveHistoryFixture):
        _live_evidence = evidence
        def snapshot(self): return {'tasks': []}
        def answer(self, *args): return {'error': 'unavailable'}
        def verdict(self, *args): return {'error': 'unavailable'}
        def session_projects(self): return {'projects': [{'name': 'demo'}]}
        def session_list(self, project, page):
            return {'rows': [{'sid': SID, 'title': 'Compact synthetic session', 'status': 'idle'},
                             {'sid': OTHER, 'title': 'Second synthetic session', 'status': 'idle'}], 'has_more': False}
        def session_history(self, project, sid, cursor):
            data = json.loads((evidence / 'control.json').read_text())
            records = json.loads((evidence / 'receipts.json').read_text())
            seeds = data.get('seeds', []) if sid == SID else []
            receipts = [r for r in records if r['sid'] == sid]
            recent = [{k: r[k] for k in ('status', 'message_id', 'turn_id')} for r in receipts] + seeds
            result = {'turns': [{'id': 'status-turn', 'status': 'completed', 'items': [
                {'id': 'status-' + str(i), 'role': 'assistant', 'text': 'LATEST message ' + str(i) + '\n\n' + ('Readable status detail ' + str(i) + ' ')*30, 'truncated': False}
                for i in range(24)]}], 'next_cursor': None, 'truncated': False, 'recent_sends': recent[-8:]}
            if data.get('marker'):
                result['turns'][0]['items'][-1]['text'] += '\n\n' + data['marker']
            return result
        def session_send(self, project, sid, message_id, text):
            data = json.loads((evidence / 'control.json').read_text())
            record = {'status': data.get('send_status', 'accepted'), 'message_id': message_id,
                      'turn_id': SID if data.get('send_status', 'accepted') == 'accepted' else None}
            records = json.loads((evidence / 'receipts.json').read_text())
            records.append({**record, 'sid': sid}); private_json(evidence / 'receipts.json', records)
            with (evidence / 'calls.jsonl').open('a') as f: f.write(json.dumps({'method': 'send', 'sid': sid, 'message_id': message_id}) + '\n')
            return record
        def session_send_status(self, project, sid, message_id):
            data = json.loads((evidence / 'control.json').read_text())
            with (evidence / 'calls.jsonl').open('a') as f: f.write(json.dumps({'method': 'status', 'sid': sid, 'message_id': message_id}) + '\n')
            time.sleep(data.get('status_delay', 0))
            records = json.loads((evidence / 'receipts.json').read_text()) + data.get('seeds', [])
            record = next((r for r in records if r['message_id'] == message_id), None)
            if record is None: return {'error': 'stale'}
            return {'status': data.get('checked_status', record['status']), 'message_id': message_id,
                    'turn_id': SID if data.get('checked_status', record['status']) == 'accepted' else None}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0)); listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD),
                          'totp_secret': SECRET, 'session_ttl': 3600, 'secure_cookie': False, 'totp_state_path': replay_path(evidence)}, Backend())
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    server_thread = threading.Thread(
        target=server.run, kwargs={'sockets': [listener]}, daemon=True,
        name='synthetic-status-http',
    )
    server_thread.start()
    deadline = time.monotonic() + 8
    try:
        while not server.started:
            if not server_thread.is_alive():
                raise RuntimeError('Synthetic fixture server exited before startup')
            if time.monotonic() >= deadline:
                raise RuntimeError('Synthetic fixture server startup timed out')
            time.sleep(.01)
        while time.monotonic() < deadline:
            if not server_thread.is_alive():
                raise RuntimeError('Synthetic fixture server exited before HTTP readiness')
            try:
                with urllib.request.urlopen(origin, timeout=.25) as response:
                    if response.status == 200:
                        publish_ready(evidence, origin)
                        break
            except OSError:
                time.sleep(.02)
        else:
            raise RuntimeError('Synthetic fixture HTTP endpoint did not become ready')
    except BaseException:
        server.should_exit = True
        server_thread.join(timeout=2)
        listener.close()
        raise
    server_thread.join()


class TransientSendStatusBrowserContract(unittest.TestCase):
    # Share synthetic login, teardown and public-DOM helpers, not existing tests.
    stop_server = classmethod(compact.CompactChatBrowserContract.stop_server.__func__)
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
        cls.evidence = Path(tempfile.mkdtemp(prefix='control-status-qa-', dir='/var/tmp'))
        private_json(cls.evidence / 'control.json', {'delay': 0, 'count': 24})
        private_json(cls.evidence / 'receipts.json', [])
        cls.root = Path(os.environ.get('CONTROL_STATUS_QA_REPO', str(ROOT)))
        interpreter = os.environ.get('CONTROL_STATUS_QA_SERVER_PYTHON', sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve', str(cls.root), str(cls.evidence)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        while not (cls.evidence / 'ready.json').exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None: raise RuntimeError('Synthetic fixture server failed')
            time.sleep(.02)
        cls.url = json.loads((cls.evidence / 'ready.json').read_text())['url']
        cls.playwright = sync_playwright().start(); cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_STATUS_QA_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={'width': 1280, 'height': 900}, color_scheme='dark')
        cls.addClassCleanup(cls.context.close)
        page = cls.context.new_page()
        page.goto(cls.url)
        page.locator('#username').fill('owner')
        page.locator('input[type=password]').fill(PASSWORD)
        page.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        page.get_by_role('button', name=re.compile('^Войти$', re.I)).click()
        page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).wait_for()
        page.close()
        print('Status evidence: ' + str(cls.evidence), flush=True)

    def setUp(self):
        private_json(self.evidence / 'receipts.json', [])
        (self.evidence / 'calls.jsonl').unlink(missing_ok=True)
        compact.CompactChatBrowserContract.setUp(self)
        self.live_frames=observe_snapshots(self.page)

    def control(self, **data):
        pending = self.evidence / 'control-next.json'
        private_json(pending, data)
        pending.replace(self.evidence / 'control.json')

    def send(self, text='Synthetic transient status message'):
        self.page.locator('textarea').fill(text)
        self.page.get_by_role('button', name='Отправить', exact=True).click()
        self.page.wait_for_timeout(200)

    def slot(self):
        return self.page.locator('form').get_by_role('status',include_hidden=True)

    def accepted(self):
        accepted = bool(re.search('принято', self.slot().inner_text(), re.I))
        if accepted:
            self.assertTrue(self.slot().is_visible(), 'Nonempty accepted status remains visible in normal flow')
        return accepted

    def calls(self):
        path = self.evidence / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def seed(self, number, status='accepted'):
        return {'message_id': '55555555-5555-4555-8555-' + str(number).zfill(12),
                'status': status, 'turn_id': SID if status == 'accepted' else None}

    def disclosure(self, count):
        summary = self.page.locator('details > summary').filter(has_text=re.compile(r'Проблемы доставки'))
        self.assertEqual(summary.count(), 1, 'INV-WSESS-17 requires native delivery-problem disclosure')
        self.assertRegex(summary.inner_text(), r'Проблемы доставки\s*\(' + str(count) + r'\)')
        details = summary.locator('..')
        self.assertIsNone(details.get_attribute('open'), 'Delivery problems collapsed by default')
        summary.focus(); summary.press('Enter')
        self.assertIsNotNone(details.get_attribute('open'), 'Keyboard expands native disclosure')
        self.assertEqual(details.locator('[aria-live]').count(), 0, 'Problem details cannot repeat live announcements')
        return details

    def test_INV_WSESS_16_one_accepted_expires_without_poll_extension_or_reader_shift(self):
        self.open_history()
        self.slot().evaluate("el=>{window.statusAnnouncements=[];new MutationObserver(()=>{if(/принято/i.test(el.textContent))window.statusAnnouncements.push(el.textContent)}).observe(el,{childList:true,subtree:true,characterData:true});}")
        self.send()
        self.assertTrue(self.accepted(), 'Local transition must show accepted immediately')
        accepted_at=time.monotonic()
        self.page.locator('textarea').fill('Draft survives status expiry')
        self.page.get_by_text('LATEST message 21', exact=True).scroll_into_view_if_needed()
        anchor = self.page.get_by_text('LATEST message 21', exact=True)
        before_form_height = self.page.locator('form').filter(has=self.page.locator('textarea')).bounding_box()['height']
        before_y = anchor.bounding_box()['y']; before_requests = len(self.history_requests())
        before_calls = self.calls()
        before_ids = [r['message_id'] for r in self.calls() if r['method'] == 'send']
        # BR6a/INV53: prove the same UUID reconciliation frame reached the DOM,
        # then measure expiry against the original accepted transition.
        marker='Synthetic accepted receipt reconciliation reached the UI'
        self.control(marker=marker)
        self.page.get_by_text(marker,exact=True).wait_for(timeout=6000)
        self.assertLessEqual(abs(anchor.bounding_box()['y']-before_y),8)
        before_history = self.page.locator('.chat-items').inner_html()
        self.page.wait_for_timeout(max(0,4.2-(time.monotonic()-accepted_at))*1000)
        self.assertTrue(self.accepted(), 'Accepted remains visible through its five-second lifetime')
        self.page.wait_for_timeout(max(0,5.8-(time.monotonic()-accepted_at))*1000)
        # INV-WSESS-53 automatic receipt projection arrives through actual SSE.
        self.assertTrue(any('/api/session-events?' in url for _,url in self.network))
        self.assertTrue(any(any(row['message_id']==before_ids[-1] for row in frame['history']['recent_sends']) for frame in self.live_frames),
                        'Actual native SSE delivers this accepted UUID')
        self.assertEqual(len(self.history_requests()),before_requests,'Automatic receipt update uses no legacy GET')
        self.assertEqual(self.slot().inner_text().strip(), '', 'Accepted clears after5s despite repeated history GET')
        self.assertEqual(self.slot().count(), 1, 'Empty polite live region remains attached after expiry')
        self.assertLess(self.page.locator('form').filter(has=self.page.locator('textarea')).bounding_box()['height'], before_form_height, 'INV47 removes the empty status reserve after expiry')
        self.assertLessEqual(self.slot().evaluate('el=>el.getBoundingClientRect().height'), .5, 'Empty accepted slot must collapse to0px')
        self.assertEqual(self.calls(), before_calls, 'Expiry cannot trigger status GET or send')
        self.assertEqual(self.page.locator('.chat-items').inner_html(), before_history, 'Expiry preserves rendered history')
        self.assertEqual(len(self.page.evaluate('window.statusAnnouncements')), 1, 'Repeated polling cannot repeat accepted announcement')
        self.assertLessEqual(abs(anchor.bounding_box()['y']-before_y), 8, 'Status collapse preserves reader anchor')
        self.assertEqual(self.page.locator('textarea').input_value(), 'Draft survives status expiry')
        self.assertEqual([r['message_id'] for r in self.calls() if r['method'] == 'send'], before_ids)
        self.assertEqual(self.page.get_by_text(re.compile('Сообщение принято')).count(), 0, 'No accepted pile after expiry')

    def test_INV_WSESS_16_seed_and_full_reload_hide_accepted(self):
        self.control(seeds=[self.seed(i) for i in range(8)])
        self.open_history()
        self.assertEqual(self.page.get_by_text(re.compile('Сообщение принято')).count(), 0, 'History seed accepted stays hidden')
        self.send(); self.assertTrue(self.accepted())
        self.page.reload()
        self.page.get_by_role('button', name=re.compile('^Сессии$')).or_(self.page.get_by_role('tab', name=re.compile('^Сессии$'))).click()
        choose_project(self.page, 'demo'); self.session.click()
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.assertEqual(self.page.get_by_text(re.compile('Сообщение принято')).count(), 0, 'Reload cannot restore accepted UI')
        self.assertEqual(len([r for r in self.calls() if r['method'] == 'send']), 1, 'Reload never resends')

    def test_INV_WSESS_16_series_accepted_has_single_polite_slot_and_no_pile(self):
        self.open_history()
        for i in range(9): self.send('Synthetic accepted series ' + str(i))
        self.assertEqual(self.slot().count(), 1)
        self.assertEqual(self.slot().get_attribute('aria-live'), 'polite')
        self.assertEqual(self.page.get_by_text(re.compile('Сообщение принято')).count(), 1, 'Accepted only in current slot')
        receipt_live = self.page.locator('[aria-live]').filter(has_text=re.compile('Недавние отправки|Проблемы доставки'))
        self.assertEqual(receipt_live.count(), 0, 'Receipt listing cannot announce current status again')
        self.assertEqual(len(set(r['message_id'] for r in self.calls() if r['method'] == 'send')), 9)
        for width in (360, 768, 1280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.assertLessEqual(self.page.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)'), width+1)

    def test_INV_WSESS_16_new_attempt_outlives_old_timer_and_switch_does_not_restart(self):
        self.open_history(); self.send('Synthetic first accepted')
        self.page.wait_for_timeout(3200); self.send('Synthetic second accepted')
        self.page.wait_for_timeout(2000)
        self.assertTrue(self.accepted(), 'Old UUID timer cannot clear newer accepted')
        self.page.get_by_role('button', name=re.compile('Second synthetic session')).click()
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.assertFalse(self.accepted(), 'Other session cannot inherit current accepted')
        self.page.wait_for_timeout(3300); self.session.click()
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.assertEqual(self.slot().inner_text().strip(), '', 'Return cannot restart elapsed UUID timer')

    def test_INV_WSESS_17_all_known_unresolved_survive_eight_newer_receipts_exact_manual_checks(self):
        unknowns = [self.seed(101, 'delivery_unknown'), self.seed(102, 'delivery_unknown')]
        self.control(seeds=unknowns + [self.seed(103, 'rejected'), self.seed(104, 'sending')])
        self.open_history()
        marker='Synthetic receipt projection 200 through 207 reached the UI'
        before_requests=len(self.history_requests())
        self.control(seeds=[self.seed(i+200) for i in range(8)], status_delay=1.2, marker=marker)
        # INV-WSESS-53: new seed projection is automatic via real SSE.
        expected={self.seed(i+200)['message_id'] for i in range(8)}
        deadline=time.monotonic()+6
        observed=self.live_frames
        while time.monotonic()<deadline:
            if any({row['message_id'] for row in frame['history']['recent_sends']}==expected for frame in observed):break
            self.page.wait_for_timeout(50)
        self.assertTrue(any({row['message_id'] for row in frame['history']['recent_sends']}==expected for frame in observed),
                        'Actual native SSE delivers the second bounded seed projection')
        self.page.get_by_text(marker,exact=True).wait_for(timeout=6000)
        self.assertEqual(len(self.history_requests()),before_requests,'Marker and receipts arrive automatically without legacy GET')
        details = self.disclosure(4)
        checks = details.get_by_role('button', name='Проверить доставку', exact=True)
        self.assertEqual(checks.count(), 2, 'Every older unknown remains manually checkable')
        # Status fixture still knows older IDs even though latest history omitted them.
        self.control(seeds=unknowns, status_delay=1.2)
        for index in range(2):
            button = checks.nth(index); button.click()
            self.assertTrue(button.is_disabled(), 'Only this UUID check disabled while underway')
            self.assertTrue(checks.nth(1-index).is_enabled(), 'Unrelated UUID check stays available')
            self.page.wait_for_timeout(1500)
            self.assertTrue(button.is_enabled(), 'Repeated unknown retains manual check')
        status_calls = [r for r in self.calls() if r['method'] == 'status']
        self.assertEqual({r['message_id'] for r in status_calls}, {r['message_id'] for r in unknowns})
        self.assertEqual(len(status_calls), 2)
        self.assertFalse(any(r['method'] == 'send' for r in self.calls()), 'Manual check never sends')
        self.assertRegex(details.inner_text(), '(?i)отклон|rejected')
        self.assertRegex(details.inner_text(), '(?i)отправ|sending')
        self.assertNotRegex(details.inner_text(), '(?i)сообщение принято')

    def test_INV_WSESS_16_local_unknown_status_transition_gets_five_seconds(self):
        self.control(send_status='delivery_unknown')
        self.open_history(); self.send()
        self.assertFalse(self.accepted())
        self.control(checked_status='accepted')
        checks = self.page.get_by_role('button', name='Проверить доставку', exact=True)
        self.assertGreater(checks.count(), 0, 'Current unknown must expose manual status check')
        checks.first.click(); self.page.wait_for_timeout(250)
        self.assertTrue(self.accepted(), 'Locally observed unknown→accepted starts expiry')
        self.page.wait_for_timeout(5400)
        self.assertEqual(self.slot().inner_text().strip(), '', 'Reconciled accepted expires after5s')
        self.assertEqual(len([r for r in self.calls() if r['method'] == 'send']), 1)

    def test_INV_WSESS_16_late_old_status_and_old_timer_cannot_replace_new_current(self):
        self.control(send_status='delivery_unknown')
        self.open_history(); self.send('Synthetic unknown first')
        self.control(checked_status='accepted', status_delay=9)
        checks = self.page.get_by_role('button', name='Проверить доставку', exact=True)
        self.assertGreater(checks.count(), 0)
        checks.first.click(); self.page.wait_for_timeout(200)
        # History terminalizes the old unknown before its slow status response
        # returns, allowing a legitimate fresh local attempt with distinct state.
        records = json.loads((self.evidence / 'receipts.json').read_text())
        first_id = records[0]['message_id']
        self.control(seeds=[{'status':'accepted','message_id':first_id,'turn_id':SID}],
                     checked_status='accepted', status_delay=9, send_status='rejected')
        self.page.wait_for_timeout(5500)
        self.send('Synthetic newer rejected attempt')
        current = self.slot().inner_text()
        self.assertRegex(current, '(?i)отклон|rejected')
        self.page.wait_for_timeout(4800)
        self.assertEqual(self.slot().inner_text(), current, 'Late old response and old accepted expiry cannot replace newer rejected')
        self.assertEqual(self.page.locator('textarea').input_value(), 'Synthetic newer rejected attempt')

    def test_INV_WSESS_16_tasks_tab_and_hidden_expiry_cannot_move_reader_or_restore_accepted(self):
        self.open_history(); self.send()
        tasks = self.page.get_by_role('button', name='Задачи', exact=True).or_(self.page.get_by_role('tab', name='Задачи', exact=True))
        self.assertEqual(tasks.count(), 1, 'Existing tasks tab is accessible')
        tasks.click(); self.page.wait_for_timeout(200)
        y = self.page.evaluate('scrollY')
        self.page.wait_for_timeout(5400)
        self.assertLessEqual(abs(self.page.evaluate('scrollY')-y), 8, 'Expired hidden session status cannot move tasks viewport')
        self.page.get_by_role('button', name='Сессии', exact=True).or_(self.page.get_by_role('tab', name='Сессии', exact=True)).click()
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.assertEqual(self.slot().inner_text().strip(), '', 'Hidden accepted expires without restart')

    def restore_authentication_after_logout(self):
        # Login deliberately consumes a TOTP step. Restore the shared synthetic
        # context with a fresh step so logout cannot contaminate another case.
        self.page.goto(self.url)
        self.page.locator('input[type=password]').wait_for()
        self.page.wait_for_timeout((30 - time.time() % 30) * 1000 + 150)
        self.page.locator('#username').fill('owner')
        self.page.locator('input[type=password]').fill(PASSWORD)
        self.page.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        self.page.get_by_role('button', name='Войти', exact=True).click()
        self.page.get_by_role('button', name='Сессии', exact=True).or_(self.page.get_by_role('tab', name='Сессии', exact=True)).wait_for()

    def test_INV_WSESS_16_logout_clears_current_timer(self):
        self.open_history(); self.send()
        logout = self.page.get_by_role('button', name=re.compile('^(Выйти|Выход)$'))
        self.assertEqual(logout.count(), 1, 'Existing logout control is accessible')
        self.addCleanup(self.restore_authentication_after_logout)
        logout.click(); self.page.locator('input[type=password]').wait_for()
        self.page.wait_for_timeout(5400)
        self.assertTrue(self.page.locator('input[type=password]').is_visible(), 'Old timer cannot change logged-out page')
        self.assertEqual(self.page.locator('#send-status').inner_text().strip(), '', 'Logout clears current send status')
        self.assertEqual(len([r for r in self.calls() if r['method'] == 'send']), 1)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--serve': serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else: unittest.main(verbosity=2)
