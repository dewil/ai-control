"""Source-blind synthetic browser contracts for INV-WSESS-30."""
# Accepted INV-WSESS-47..50 (2026-10-08-spec-live-observability-package.md):
# canonical captions/chips and native disclosures replace the previous labels/layout.

from control_browser_helpers import choose_project
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

from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET

ROOT = Path(__file__).resolve().parents[1]
SID = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
MESSAGE_ID = '33333333-3333-4333-8333-333333333333'
TURN_ID = '44444444-4444-4444-8444-444444444444'
CATALOG_ID = 'a' * 64
OLD_TITLE = 'Alpha synthetic session'
OTHER_TITLE = 'Beta synthetic session'


def model_catalog():
    return {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
            'selection_support': 'available', 'reason': None, 'catalog_id': CATALOG_ID,
            'expires_in_ms': 60000, 'rows': [
                {'id': 'synthetic-model', 'label': 'Synthetic model', 'efforts': ['low', 'high'],
                 'default_effort': 'low', 'is_default': True}]}


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root / 'bin'))
    web = importlib.import_module('_control_web')

    def record(event):
        with (evidence / 'calls.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + '\n')

    class Backend:
        def snapshot(self): return {'tasks': []}
        def answer(self, *args): return {'error': 'unavailable'}
        def verdict(self, *args): return {'error': 'unavailable'}
        def session_projects(self): return {'projects': [{'name': 'demo'}]}
        def session_list(self, project, page):
            return {'rows': [
                {'sid': SID, 'title': OLD_TITLE, 'status': 'idle', 'vendor': 'codex'},
                {'sid': OTHER, 'title': OTHER_TITLE, 'status': 'idle', 'vendor': 'codex'}],
                'has_more': False}
        def session_history(self, project, sid, cursor):
            title = OLD_TITLE if sid == SID else OTHER_TITLE
            return {'turns': [{'id': 'synthetic-turn-' + sid, 'status': 'completed', 'items': [
                {'id': 'synthetic-item-' + sid, 'role': 'assistant',
                 'text': 'Synthetic history for ' + title, 'truncated': False}]}],
                'next_cursor': None, 'truncated': False, 'recent_sends': []}
        def session_models(self, project, sid):
            record({'method': 'models', 'project': project, 'sid': sid})
            return model_catalog()
        def session_send(self, project, sid, message_id, text, selection=None):
            record({'method': 'send', 'project': project, 'sid': sid, 'message_id': message_id,
                    'text': text, 'selection': selection})
            return {'status': 'accepted', 'message_id': message_id, 'turn_id': TURN_ID}
        def session_send_status(self, *args): return {'error': 'stale'}
        def session_rename(self, project, sid, operation_id, title):
            settings = json.loads((evidence / 'control.json').read_text(encoding='utf-8'))
            record({'method': 'rename', 'project': project, 'sid': sid,
                    'operation_id': operation_id, 'title': title})
            if settings.get('hold_rename'):
                deadline = time.monotonic() + 8
                while not (evidence / 'release-rename.json').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
            delay = settings.get('rename_delay', 0)
            if delay: time.sleep(delay)
            result = settings.get('rename_result', 'accepted')
            if result in ('unavailable', 'stale'): return {'error': result}
            if result == 'delivery_unknown':
                return {'operation_id': operation_id, 'status': 'delivery_unknown'}
            return {'operation_id': operation_id, 'status': 'accepted',
                    'title': settings.get('accepted_title', title)}
        def session_rename_status(self, project, sid, operation_id):
            settings = json.loads((evidence / 'control.json').read_text(encoding='utf-8'))
            record({'method': 'rename_status', 'project': project, 'sid': sid,
                    'operation_id': operation_id})
            result = settings.get('status_result', 'delivery_unknown')
            if result == 'error': return {'error': 'unavailable'}
            if result == 'delivery_unknown':
                return {'operation_id': operation_id, 'status': 'delivery_unknown'}
            return {'operation_id': operation_id, 'status': 'accepted',
                    'title': settings.get('status_title', settings.get('accepted_title', ''))}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD),
                          'totp_secret': SECRET, 'session_ttl': 3600, 'secure_cookie': False}, Backend())
    private_json(evidence / 'ready.json', {'url': origin})
    uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[listener])


class SessionRenameBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Optional Playwright browser dependency unavailable')
        os.umask(0o077)
        requested = os.environ.get('CONTROL_WEB_RENAME_UI_EVIDENCE')
        cls.evidence = Path(requested) if requested else Path(
            tempfile.mkdtemp(prefix='control-session-rename-ui-', dir='/var/tmp'))
        cls.evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
        cls.evidence.chmod(0o700)
        (cls.evidence / 'ready.json').unlink(missing_ok=True)
        (cls.evidence / 'release-rename.json').unlink(missing_ok=True)
        cls.root = Path(os.environ.get('CONTROL_WEB_RENAME_UI_REPO', str(ROOT)))
        private_json(cls.evidence / 'control.json', {})
        interpreter = os.environ.get('CONTROL_WEB_RENAME_UI_SERVER_PYTHON', sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve',
                                       str(cls.root), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        while not (cls.evidence / 'ready.json').exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None:
                raise RuntimeError('Synthetic rename fixture server failed to start')
            time.sleep(.02)
        cls.url = json.loads((cls.evidence / 'ready.json').read_text(encoding='utf-8'))['url']
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_WEB_RENAME_UI_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(
            headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True)
        cls.addClassCleanup(cls.context.close)
        page = cls.context.new_page()
        page.goto(cls.url)
        page.locator('#username').fill('owner')
        page.locator('input[type=password]').fill(PASSWORD)
        page.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        page.get_by_role('button', name=re.compile('^Войти$', re.I)).click()
        page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(
            page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).wait_for()
        page.close()

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(4)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait()

    def setUp(self):
        private_json(self.evidence / 'control.json', {})
        (self.evidence / 'release-rename.json').unlink(missing_ok=True)
        (self.evidence / 'calls.jsonl').unlink(missing_ok=True)
        self.network = []
        self.errors = []
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.addCleanup(self.page.close)
        self.page.on('request', lambda request: self.network.append(request))
        self.page.on('pageerror', lambda error: self.errors.append(type(error).__name__))
        self.page.goto(self.url)
        self.page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(
            self.page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).click()
        choose_project(self.page, 'demo')
        self.alpha = self.row(OLD_TITLE)
        self.beta = self.row(OTHER_TITLE)
        self.alpha.wait_for(state='visible')
        self.open_session(SID)

    def tearDown(self):
        self.assertEqual(self.errors, [], 'Synthetic browser flow must not raise JavaScript exceptions')
        self.assertTrue(self.page.evaluate('localStorage.length===0 && sessionStorage.length===0'),
                        'Rename state must remain session-local')
        self.assertFalse(any(request.url.split('/')[2] != self.url.split('/')[2]
                             for request in self.network),
                         'Synthetic fixture must not contact another origin')

    def calls(self):
        path = self.evidence / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def row(self, title):
        return self.page.get_by_role('button', name=re.compile(re.escape(title)))

    def open_session(self, sid):
        (self.alpha if sid == SID else self.beta).click()
        title = OLD_TITLE if sid == SID else OTHER_TITLE
        self.page.get_by_text('Synthetic history for ' + title, exact=True).wait_for(state='attached')

    def dialog(self):
        action = self.page.get_by_role('button', name='Переименовать', exact=True)
        self.assertEqual(action.count(), 1,
                         'INV-WSESS-30 requires a rename action in the selected chat')
        action.click()
        dialog = self.page.get_by_role('dialog')
        dialog.wait_for(state='visible')
        return dialog

    def title_box(self, dialog):
        return dialog.get_by_role('textbox', name='Название сессии', exact=True)

    def heading(self, title):
        return self.page.get_by_role('heading', name=title, exact=True)

    def post_request(self):
        return next((request for request in self.network
                     if request.method == 'POST' and '/api/session-rename' in request.url), None)

    def status_requests(self):
        return [request for request in self.network
                if request.method == 'GET' and '/api/session-rename-status' in request.url]

    def dialog_status_texts(self, dialog):
        return [value.strip() for value in dialog.get_by_role('status').all_inner_texts() if value.strip()]

    def assert_terminal_dialog_status(self, dialog, previous_texts=()):
        dialog.get_by_role('status').filter(has_text=re.compile(r'\S')).wait_for(
            state='visible', timeout=1200)
        values = self.dialog_status_texts(dialog)
        self.assertEqual(len(values), 1, 'Rename exposes exactly one live status inside its dialog')
        self.assertNotIn(values[0], previous_texts,
                         'The terminal acknowledgment replaces any pending dialog status')
        live = dialog.get_by_role('status')
        self.assertEqual(live.count(), 1)
        self.assertEqual(live.get_attribute('aria-live'), 'polite')
        same_text_outside_dialog = self.page.locator('[role="status"]').evaluate_all(
            "(els, text) => els.filter(el => el.textContent.trim() === text && !el.closest('[role=dialog]')).length",
            values[0])
        self.assertEqual(same_text_outside_dialog, 0,
                         'The same rename acknowledgment is not duplicated outside its dialog')
        return values[0]

    def assert_title(self, title):
        # Response headers may arrive before the browser applies its JSON result.
        self.row(title).wait_for(state='visible', timeout=5000)
        self.heading(title).wait_for(state='visible', timeout=5000)
        self.assertEqual(self.row(title).count(), 1, 'Only the matching session list row receives the title')
        self.assertEqual(self.heading(title).count(), 1, 'Selected chat heading shows the confirmed title')

    def test_INV_WSESS_30_labelled_dialog_suggests_current_safe_title_and_cancel_has_no_effect(self):
        dialog = self.dialog()
        box = self.title_box(dialog)
        self.assertEqual(box.input_value(), OLD_TITLE, 'Current safe title is only a proposal')
        self.assertEqual(dialog.get_by_role('button', name='Сохранить', exact=True).count(), 1)
        dialog.get_by_role('button', name='Отмена', exact=True).click()
        dialog.wait_for(state='hidden')
        self.assertEqual(self.row(OLD_TITLE).count(), 1)
        self.assertEqual(self.post_request(), None, 'Opening or cancelling the dialog cannot rename')
        self.assertEqual(self.status_requests(), [])

    def test_INV_WSESS_30_confirmed_title_updates_exact_row_heading_and_keeps_chat_models_and_send(self):
        title = 'Confirmed synthetic rename'
        private_json(self.evidence / 'control.json', {'hold_rename': True, 'accepted_title': title})
        dialog = self.dialog()
        self.title_box(dialog).fill(title)
        previous_statuses = self.dialog_status_texts(dialog)
        with self.page.expect_response(lambda response: response.request.method == 'POST' and
                                       '/api/session-rename' in response.url) as completed:
            with self.page.expect_request(lambda request: request.method == 'POST' and
                                          '/api/session-rename' in request.url) as captured:
                dialog.get_by_role('button', name='Сохранить', exact=True).click()
            request = captured.value
            self.assertTrue(self.title_box(dialog).is_disabled(),
                            'Pending title cannot be changed while the immutable rename is in flight')
            self.assert_title(OLD_TITLE)
            pending_statuses = self.dialog_status_texts(dialog)
            private_json(self.evidence / 'release-rename.json', {'release': True})
        response = completed.value
        self.assertEqual(response.status, 200, 'UI title updates only after an accepted backend response')
        self.assertEqual(set(json.loads(request.post_data)), {'project', 'sid', 'operation_id', 'title'})
        body = json.loads(request.post_data)
        self.assertEqual((body['project'], body['sid'], body['title']), ('demo', SID, title))
        self.assertRegex(body['operation_id'], r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        dto = response.json()
        self.assertEqual(dto.get('status'), 'accepted')
        self.assertEqual(dto.get('operation_id'), body['operation_id'])
        self.assertEqual(dto.get('title'), title)
        self.assert_title(title)
        notice_text = self.assert_terminal_dialog_status(dialog, previous_statuses + pending_statuses)
        self.assertEqual(self.row(OTHER_TITLE).count(), 1, 'Other session row keeps its title')
        self.assertEqual(self.page.get_by_text('Synthetic history for ' + OLD_TITLE, exact=True).count(), 1)

        model = self.page.get_by_role('combobox', name='Модель', exact=True, include_hidden=True)
        effort = self.page.get_by_role('combobox', name='Уровень размышления', exact=True, include_hidden=True)
        for summary in model.locator('xpath=ancestor::details[not(@open)]/summary').all():
            summary.click()
        self.assertTrue(model.is_visible()); self.assertTrue(effort.is_visible())
        self.assertEqual(model.count(), 1, 'Existing model control remains available')
        self.assertEqual(effort.count(), 1, 'Existing effort control remains available')
        self.assertEqual(model.locator('option').first.inner_text(), 'Использовать текущую модель')
        self.page.locator('textarea').fill('Synthetic message after rename')
        self.page.get_by_role('button', name='Отправить', exact=True).click()
        self.page.get_by_role('status').filter(has_text=re.compile('принято', re.I)).wait_for()
        sent = [event for event in self.calls() if event['method'] == 'send']
        self.assertEqual(len(sent), 1)
        self.assertEqual((sent[0]['project'], sent[0]['sid'], sent[0]['text']),
                         ('demo', SID, 'Synthetic message after rename'))
        self.assertEqual([event['sid'] for event in self.calls() if event['method'] == 'models'], [SID])

        self.page.wait_for_timeout(5300)
        notice_visible = dialog.get_by_role('status').evaluate_all(
            """(els, text) => els.some(el => {
              const style = getComputedStyle(el);
              const normalized = value => value.replace(/\\s+/g, ' ').trim();
              return normalized(el.innerText) === normalized(text) && style.display !== 'none' &&
                style.visibility !== 'hidden' && el.getClientRects().length > 0;
            })""", notice_text)
        self.assertFalse(notice_visible,
                         'Accepted dialog status expires after five seconds or dialog closure')
        if dialog.is_visible():
            dialog.get_by_role('button', name='Отмена', exact=True).click()
            dialog.wait_for(state='hidden')
        self.assertEqual(self.post_request().post_data, request.post_data)

    def test_INV_WSESS_30_unknown_preserves_uuid_and_draft_then_manual_status_proves_title(self):
        title = 'Unknown synthetic title'
        fresh_title = 'Different synthetic native title'
        private_json(self.evidence / 'control.json', {
            'rename_result': 'delivery_unknown', 'status_result': 'accepted', 'status_title': fresh_title})
        dialog = self.dialog()
        box = self.title_box(dialog)
        box.fill(title)
        with self.page.expect_response(lambda response: response.request.method == 'POST' and
                                       '/api/session-rename' in response.url) as posted:
            with self.page.expect_request(lambda request: request.method == 'POST' and
                                          '/api/session-rename' in request.url) as captured:
                dialog.get_by_role('button', name='Сохранить', exact=True).click()
        first = posted.value
        self.assertEqual(first.status, 503,
                         'A delivery_unknown response is ambiguous at the HTTP boundary')
        body = json.loads(captured.value.post_data)
        unknown_dto = first.json()
        self.assertEqual(unknown_dto.get('status'), 'delivery_unknown')
        self.assertEqual(unknown_dto.get('operation_id'), body['operation_id'])
        self.assertNotIn('title', unknown_dto)
        self.assertEqual(body['title'], title)
        self.assertEqual(set(body), {'project', 'sid', 'operation_id', 'title'})
        check = self.page.get_by_role('button', name='Проверить название', exact=True)
        check.wait_for(state='visible')
        self.assertEqual(box.input_value(), title, 'Unknown retains the exact draft')
        self.assertTrue(box.is_disabled(), 'Unknown locks title until manual reconciliation')
        self.assertTrue(check.is_enabled(), 'Unknown exposes one explicit read-only status check')
        self.assertEqual(self.status_requests(), [], 'Unknown cannot trigger automatic status polling')
        self.page.wait_for_timeout(150)
        self.assertEqual(self.status_requests(), [], 'A visible unknown state stays inert until user action')
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and
                              '/api/session-rename' in r.url]), 1,
                         'Unknown cannot create a second mutation request')
        previous_statuses = self.dialog_status_texts(dialog)
        with self.page.expect_response(lambda response: response.request.method == 'GET' and
                                       '/api/session-rename-status' in response.url) as checked:
            check.click()
        self.assertEqual(checked.value.status, 200)
        status_request = checked.value.request
        status_dto = checked.value.json()
        self.assertEqual(status_dto.get('status'), 'accepted')
        self.assertEqual(status_dto.get('operation_id'), body['operation_id'])
        self.assertEqual(status_dto.get('title'), fresh_title)
        query = dict(part.split('=', 1) for part in status_request.url.split('?', 1)[1].split('&'))
        self.assertEqual(set(query), {'project', 'sid', 'operation_id'})
        self.assertEqual(query, {'project': 'demo', 'sid': SID, 'operation_id': body['operation_id']})
        self.assertNotEqual(fresh_title, title)
        self.assert_title(fresh_title)
        self.assertEqual(self.row(title).count(), 0, 'Requested draft is not substituted for current native title')
        self.assert_terminal_dialog_status(dialog, previous_statuses)
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and
                              '/api/session-rename' in r.url]), 1, 'Manual reconciliation never repeats mutation')
        self.assertEqual(len(self.status_requests()), 1)
        self.assertEqual([event['method'] for event in self.calls() if event['method'] in
                          ('rename', 'rename_status')], ['rename', 'rename_status'])

    def test_INV_WSESS_30_proven_stale_refusal_preserves_draft_and_corrected_attempt_gets_new_uuid(self):
        from playwright.sync_api import expect
        private_json(self.evidence / 'control.json', {'rename_result': 'stale'})
        title = 'Unconfirmed synthetic title'
        dialog = self.dialog()
        box = self.title_box(dialog)
        box.fill(title)
        with self.page.expect_response(lambda response: response.request.method == 'POST' and
                                       '/api/session-rename' in response.url) as first:
            dialog.get_by_role('button', name='Сохранить', exact=True).click()
        first_body = json.loads(first.value.request.post_data)
        self.assertEqual(first.value.status, 409, 'Stale is a proven pre-effect refusal')
        # The actual refusal handler, rather than response headers alone, unlocks the draft.
        expect(box).to_be_enabled(timeout=5000)
        self.assertEqual(box.input_value(), title, 'Safe error keeps the editable draft')
        self.assertTrue(box.is_enabled(), 'Pre-reserve error permits an explicit corrected attempt')
        self.assertEqual(self.row(OLD_TITLE).count(), 1)
        self.assertEqual(self.heading(OLD_TITLE).count(), 1)
        self.assertEqual(self.row(title).count(), 0, 'Requested text is not presented as confirmed')
        self.assertEqual(self.status_requests(), [])
        corrected = 'Corrected synthetic title'
        box.fill(corrected)
        expect(dialog.get_by_role('button', name='Сохранить', exact=True)).to_be_enabled(timeout=5000)
        self.assertTrue(dialog.get_by_role('button', name='Сохранить', exact=True).is_enabled())
        with self.page.expect_response(lambda response: response.request.method == 'POST' and
                                       '/api/session-rename' in response.url) as second:
            dialog.get_by_role('button', name='Сохранить', exact=True).click()
        second_body = json.loads(second.value.request.post_data)
        self.assertEqual(second_body['title'], corrected)
        self.assertNotEqual(first_body['operation_id'], second_body['operation_id'],
                            'A new UUID is allowed only after the proven initial stale refusal')
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and
                              '/api/session-rename' in r.url]), 2)

    def test_INV_WSESS_30_http_503_unavailable_and_status_error_keep_same_unknown_operation(self):
        from playwright.sync_api import expect
        title = 'Ambiguous synthetic title'
        private_json(self.evidence / 'control.json', {
            'rename_result': 'unavailable', 'status_result': 'error'})
        dialog = self.dialog()
        box = self.title_box(dialog)
        box.fill(title)
        with self.page.expect_response(lambda response: response.request.method == 'POST' and
                                       '/api/session-rename' in response.url) as posted:
            dialog.get_by_role('button', name='Сохранить', exact=True).click()
        self.assertEqual(posted.value.status, 503,
                         'HTTP503 unavailable cannot prove that the owner broker did not dispatch')
        body = json.loads(posted.value.request.post_data)
        self.page.get_by_role('button', name='Проверить название', exact=True).wait_for(state='visible')
        self.assertEqual(box.input_value(), title)
        self.assertTrue(box.is_disabled())
        self.assertEqual(self.status_requests(), [], 'Transport uncertainty cannot trigger an automatic GET')
        check = self.page.get_by_role('button', name='Проверить название', exact=True)
        self.assertTrue(check.is_enabled())
        with self.page.expect_response(lambda response: response.request.method == 'GET' and
                                       '/api/session-rename-status' in response.url) as first_check:
            check.click()
        self.assertEqual(first_check.value.status, 503, 'A status error does not prove mutation was absent')
        self.assertEqual(box.input_value(), title)
        self.assertTrue(box.is_disabled())
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and
                              '/api/session-rename' in r.url]), 1)

        private_json(self.evidence / 'control.json', {'status_result': 'delivery_unknown'})
        check = self.page.get_by_role('button', name='Проверить название', exact=True)
        # A completed HTTP error still needs its browser handler to release inFlight.
        expect(check).to_be_enabled(timeout=5000)
        self.assertTrue(check.is_enabled(), 'A failed manual read may be retried as a read only')
        with self.page.expect_request(lambda request: request.method == 'GET' and
                                      '/api/session-rename-status' in request.url) as second_check:
            check.click()
        query = dict(part.split('=', 1) for part in second_check.value.url.split('?', 1)[1].split('&'))
        self.assertEqual(query['operation_id'], body['operation_id'])
        self.assertEqual((query['project'], query['sid']), ('demo', SID))
        self.assertEqual(self.page.locator('textarea').count(), 1)
        self.assertEqual(len(self.status_requests()), 2)
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and
                              '/api/session-rename' in r.url]), 1,
                         'Neither 503 nor status GET failure permits a new mutation or UUID')

    def test_INV_WSESS_30_pending_payload_is_immutable_and_late_A_to_B_to_A_result_is_fenced(self):
        title = 'Late synthetic confirmation'
        private_json(self.evidence / 'control.json', {'hold_rename': True, 'accepted_title': title})
        dialog = self.dialog()
        box = self.title_box(dialog)
        box.fill(title)
        with self.page.expect_request(lambda request: request.method == 'POST' and
                                      '/api/session-rename' in request.url) as captured:
            dialog.get_by_role('button', name='Сохранить', exact=True).click()
        request = captured.value
        payload = json.loads(request.post_data)
        self.assertEqual((payload['project'], payload['sid'], payload['title']), ('demo', SID, title))
        self.assertTrue(box.is_disabled(), 'Pending title cannot be edited after immutable snapshot')
        self.assertTrue(dialog.get_by_role('button', name='Сохранить', exact=True).is_disabled())

        # The operation remains bound to A while the user changes selection.
        dialog.get_by_role('button', name='Отмена', exact=True).click()
        self.open_session(OTHER)
        self.open_session(SID)
        with self.page.expect_response(lambda response: response.request.method == 'POST' and
                                       '/api/session-rename' in response.url):
            private_json(self.evidence / 'release-rename.json', {'release': True})
        self.assert_title(OLD_TITLE)
        # Explicitly reopen the action after the dialog was closed to switch chats.
        dialog = self.dialog()
        self.assertEqual(self.title_box(dialog).input_value(), title,
                         'Reopening restores the original pending draft')
        self.assertTrue(self.title_box(dialog).is_disabled())
        check = dialog.get_by_role('button', name='Проверить название', exact=True)
        check.wait_for(state='visible')
        self.assertEqual(self.row(title).count(), 0,
                         'Late A result cannot update the reselected A generation or any other row')
        self.assertEqual(self.heading(OLD_TITLE).count(), 1)
        manual = check
        self.assertTrue(manual.is_enabled(), 'Late result leaves the original operation manually reconcilable')
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and
                              '/api/session-rename' in r.url]), 1)
        self.assertEqual(self.status_requests(), [])
        self.assertEqual(payload['operation_id'], json.loads(request.post_data)['operation_id'])

        fresh_title = 'Late current native title'
        private_json(self.evidence / 'control.json', {'status_result': 'accepted',
                     'status_title': fresh_title})
        with self.page.expect_response(lambda response: response.request.method == 'GET' and
                                       '/api/session-rename-status' in response.url) as checked:
            manual.click()
        self.assertEqual(checked.value.status, 200)
        status_dto = checked.value.json()
        self.assertEqual(status_dto.get('status'), 'accepted')
        self.assertEqual(status_dto.get('operation_id'), payload['operation_id'])
        self.assertEqual(status_dto.get('title'), fresh_title)
        query = dict(part.split('=', 1) for part in checked.value.request.url.split('?', 1)[1].split('&'))
        self.assertEqual(query['operation_id'], payload['operation_id'])
        self.assert_title(fresh_title)
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and
                              '/api/session-rename' in r.url]), 1)
        self.assertEqual(len(self.status_requests()), 1)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--serve':
        serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main()
