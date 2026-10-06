"""Source-blind INV-WSESS-37 browser contracts with a synthetic HTTP backend."""
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
import unittest
import urllib.request

from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET

ROOT = Path(__file__).resolve().parents[1]
SID = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
CREATED = '33333333-3333-4333-8333-333333333333'
OPERATION = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')


def publish_ready(path, origin):
    temporary = path.with_name('.ready-' + str(os.getpid()) + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump({'url': origin}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root / 'bin'))
    web = importlib.import_module('_control_web')

    def settings():
        return json.loads((evidence / 'control.json').read_text(encoding='utf-8'))

    def record(value):
        with (evidence / 'calls.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(value) + '\n')

    class Backend:
        def snapshot(self): return {'tasks': []}
        def answer(self, *args): return {'error': 'unavailable'}
        def verdict(self, *args): return {'error': 'unavailable'}
        def session_projects(self): return {'projects': [{'name': 'demo'}]}
        def session_list(self, project, page):
            return {'rows': [{'sid': SID, 'title': 'Alpha synthetic session', 'status': 'idle', 'vendor': 'codex'},
                             {'sid': OTHER, 'title': 'Beta synthetic session', 'status': 'idle', 'vendor': 'codex'}],
                    'has_more': False}
        def session_history(self, project, sid, cursor):
            data = settings()
            if sid == CREATED or data.get('history_unavailable'):
                return {'history_state': 'unavailable', 'reason': 'unavailable', 'recent_sends': []}
            return {'turns': [{'id': 'synthetic-turn', 'status': 'completed', 'items': [
                {'id': 'synthetic-item', 'role': 'assistant', 'text': 'Synthetic existing history', 'truncated': False}]}],
                'next_cursor': None, 'truncated': False, 'recent_sends': []}
        def session_models(self, project, sid):
            return {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                    'selection_support': 'unavailable', 'reason': 'unsupported_capability',
                    'catalog_id': None, 'expires_in_ms': 0, 'rows': []}
        def session_send(self, project, sid, message_id, text, selection=None):
            record({'method': 'send', 'project': project, 'sid': sid, 'message_id': message_id, 'text': text})
            return {'status': 'accepted', 'message_id': message_id, 'turn_id': '33333333-3333-4333-8333-333333333333'}
        def session_send_status(self, *args): return {'error': 'stale'}
        def session_create_options(self, project):
            record({'method': 'options', 'project': project})
            return {'schema': 1, 'project': project, 'options': [
                {'context_mode': 'configured', 'provider_id': 'codex', 'available': True, 'reason': None}]}
        def session_create(self, project, operation_id, context_mode, provider_id):
            data = settings()
            record({'method': 'create', 'project': project, 'operation_id': operation_id,
                    'context_mode': context_mode, 'provider_id': provider_id})
            if data.get('hold_create'):
                deadline = time.monotonic() + 8
                while not (evidence / 'release-create.json').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
            result = data.get('create_result', 'accepted')
            if result == 'delivery_unknown':
                return {'operation_id': operation_id, 'status': 'delivery_unknown'}
            if result == 'malformed':
                return {'operation_id': operation_id, 'status': 'accepted',
                        'session': {'sid': 'PRIVATE_PATH_SENTINEL<script>alert(1)</script>',
                                    'project': project, 'vendor': 'codex',
                                    'context_mode': 'configured', 'title': '<img src=x onerror=alert(1)>'}}
            return {'operation_id': operation_id, 'status': 'accepted',
                    'session': {'sid': CREATED, 'project': project, 'vendor': 'codex',
                                'context_mode': 'configured', 'title': None}}
        def session_create_status(self, project, operation_id, context_mode, provider_id):
            record({'method': 'status', 'project': project, 'operation_id': operation_id,
                    'context_mode': context_mode, 'provider_id': provider_id})
            return {'operation_id': operation_id, 'status': 'delivery_unknown'}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0)); listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD),
                          'totp_secret': SECRET, 'session_ttl': 3600, 'secure_cookie': False}, Backend())
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]},
                              daemon=True, name='synthetic-configured-create-http')
    worker.start()
    deadline = time.monotonic() + 8
    while not server.started and time.monotonic() < deadline:
        if not worker.is_alive():
            raise RuntimeError('Synthetic create fixture exited before startup')
        time.sleep(.01)
    if not server.started:
        raise RuntimeError('Synthetic create fixture startup timed out')
    with urllib.request.urlopen(origin + '/', timeout=1) as response:
        if response.status != 200:
            raise RuntimeError('Synthetic create fixture HTTP readiness failed')
    publish_ready(evidence / 'ready.json', origin)
    worker.join()


class ConfiguredCreateBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Optional Playwright browser dependency unavailable')
        os.umask(0o077)
        requested = os.environ.get('CONTROL_WEB_CREATE_UI_EVIDENCE')
        cls.evidence = Path(requested) if requested else Path(tempfile.mkdtemp(
            prefix='control-configured-create-ui-', dir='/var/tmp'))
        cls.evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
        cls.evidence.chmod(0o700)
        for name in ('ready.json', 'release-create.json', 'calls.jsonl'):
            (cls.evidence / name).unlink(missing_ok=True)
        cls.root = Path(os.environ.get('CONTROL_WEB_CREATE_UI_REPO', str(ROOT)))
        private_json(cls.evidence / 'control.json', {})
        interpreter = os.environ.get('CONTROL_WEB_CREATE_UI_SERVER_PYTHON', sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve',
                                       str(cls.root), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        ready = cls.evidence / 'ready.json'
        while not ready.exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None:
                raise RuntimeError('Synthetic create fixture server failed to start')
            time.sleep(.01)
        if not ready.exists():
            raise RuntimeError('Synthetic create fixture server readiness timed out')
        cls.url = json.loads(ready.read_text(encoding='utf-8'))['url']
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_WEB_CREATE_UI_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(
            headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True)
        cls.addClassCleanup(cls.context.close)
        page = cls.context.new_page()
        page.goto(cls.url)
        page.locator('input[type=password]').fill(PASSWORD)
        page.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        page.get_by_role('button', name=re.compile('^Войти$', re.I)).click()
        page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(
            page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).wait_for(timeout=3000)
        page.close()

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(4)
        except subprocess.TimeoutExpired:
            cls.server.kill(); cls.server.wait()

    def setUp(self):
        private_json(self.evidence / 'control.json', {})
        (self.evidence / 'release-create.json').unlink(missing_ok=True)
        (self.evidence / 'calls.jsonl').unlink(missing_ok=True)
        self.network = []
        self.errors = []
        self.page = self.context.new_page()
        self.page.set_default_timeout(3000)
        self.addCleanup(self.page.close)
        self.page.on('request', lambda request: self.network.append(request))
        self.page.on('pageerror', lambda error: self.errors.append(type(error).__name__))
        self.page.goto(self.url)
        self.page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(
            self.page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).click()
        from control_browser_helpers import choose_project
        choose_project(self.page, 'demo')

    def tearDown(self):
        self.assertEqual(self.errors, [], 'Synthetic create flow must not raise JavaScript exceptions')
        self.assertTrue(self.page.evaluate('localStorage.length===0 && sessionStorage.length===0'),
                        'Create operation state must remain session-local')
        self.assertFalse(any(request.url.split('/')[2] != self.url.split('/')[2]
                             for request in self.network),
                         'Synthetic fixture must not contact another origin')

    def calls(self):
        path = self.evidence / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def open_dialog(self):
        button = self.page.get_by_role('button', name='Новая сессия', exact=True)
        self.assertEqual(button.count(), 1, 'INV-WSESS-37 requires one project-toolbar create action')
        button.click()
        dialog = self.page.get_by_role('dialog', name='Новая сессия', exact=True)
        self.assertEqual(dialog.count(), 1, 'Create action opens the named accessible dialog')
        return dialog

    def configure_and_create(self, dialog):
        vendor = dialog.get_by_label('Вендор', exact=True)
        self.assertEqual(vendor.count(), 1, 'Dialog exposes the specified vendor select')
        create = dialog.get_by_role('button', name='Создать', exact=True)
        self.assertEqual(create.count(), 1, 'Dialog exposes one explicit create action')
        create.click()

    def test_toolbar_dialog_and_only_fresh_available_vendor(self):
        dialog = self.open_dialog()
        self.assertEqual(dialog.get_by_text('Текущие настройки сервера. Выбор подписки пока недоступен.', exact=True).count(), 1)
        vendor = dialog.get_by_label('Вендор', exact=True)
        self.assertEqual(vendor.count(), 1)
        codex = vendor.locator('option').filter(has_text='Codex')
        self.assertEqual(codex.count(), 1)
        self.assertFalse(codex.is_disabled(), 'Fresh server-proven Codex option is selectable')
        other_options = vendor.locator('option').evaluate_all(
            "els => els.filter(e => e.value && e.value !== 'codex').map(e => ({disabled:e.disabled,text:e.textContent.trim()}))")
        self.assertTrue(all(item['disabled'] for item in other_options),
                        'Unsupported vendors remain disabled, never mapped to Codex')
        self.assertEqual(dialog.get_by_role('button', name='Отмена', exact=True).count(), 1)
        self.assertEqual(dialog.get_by_role('button', name='Создать', exact=True).count(), 1)
        self.assertEqual(dialog.get_by_role('textbox').count(), 0, 'Create dialog has no title or first-message field')
        self.assertEqual(self.calls().count({'method': 'options', 'project': 'demo'}), 1)

    def test_explicit_create_posts_exact_snapshot_and_honest_accepted_result(self):
        dialog = self.open_dialog()
        self.assertEqual(dialog.get_by_role('button', name='Создать', exact=True).count(), 1)
        with self.page.expect_request(lambda r: r.method == 'POST' and '/api/session-create' in r.url) as captured:
            dialog.get_by_role('button', name='Создать', exact=True).click()
        request = captured.value
        payload = json.loads(request.post_data)
        self.assertEqual(set(payload), {'project', 'operation_id', 'context_mode', 'provider_id'})
        self.assertEqual(payload['project'], 'demo')
        self.assertEqual(payload['context_mode'], 'configured')
        self.assertEqual(payload['provider_id'], 'codex')
        self.assertRegex(payload['operation_id'], OPERATION)
        self.assertFalse(set(payload) & {'sid', 'title', 'account_id', 'model', 'text'})
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and '/api/session-create' in r.url]), 1)
        self.assertEqual([c['method'] for c in self.calls()].count('create'), 1)
        self.assertEqual([c['method'] for c in self.calls()].count('send'), 0,
                         'Accepted create does not send a hidden greeting')
        self.assertNotIn('PRIVATE_PATH_SENTINEL', self.page.locator('body').inner_text())

    def test_accepted_create_selects_original_project_and_uses_honest_empty_history(self):
        dialog = self.open_dialog()
        self.assertEqual(dialog.get_by_role('button', name='Создать', exact=True).count(), 1)
        with self.page.expect_response(lambda response: response.request.method == 'POST' and
                                       '/api/session-create' in response.url) as completed:
            dialog.get_by_role('button', name='Создать', exact=True).click()
        self.assertEqual(completed.value.status, 200)
        dto = completed.value.json()
        self.assertEqual(dto.get('status'), 'accepted')
        self.assertEqual(dto.get('session', {}).get('sid'), CREATED)
        self.page.get_by_role('heading', name='Новая сессия', exact=True).wait_for(state='visible')
        self.page.get_by_text('История пока недоступна', exact=True).wait_for(state='visible')
        self.assertEqual(self.page.locator('textarea').count(), 1,
                         'Only the explicit-message composer is available for the accepted empty thread')
        send = self.page.get_by_role('button', name='Отправить', exact=True)
        self.assertEqual(send.count(), 1)
        self.assertTrue(send.is_enabled())
        self.assertEqual([c['method'] for c in self.calls()].count('send'), 0,
                         'Create acceptance does not send a hidden greeting')
        self.assertEqual(self.page.get_by_text('<img src=x onerror=alert(1)>', exact=True).count(), 0)

    def test_unknown_preserves_dialog_uuid_and_uses_only_manual_status(self):
        private_json(self.evidence / 'control.json', {'create_result': 'delivery_unknown'})
        dialog = self.open_dialog()
        self.assertEqual(dialog.get_by_role('button', name='Создать', exact=True).count(), 1)
        with self.page.expect_request(lambda r: r.method == 'POST' and '/api/session-create' in r.url) as captured:
            dialog.get_by_role('button', name='Создать', exact=True).click()
        payload = json.loads(captured.value.post_data)
        self.assertEqual(dialog.get_by_role('button', name='Проверить статус', exact=True).count(), 1)
        self.assertTrue(dialog.get_by_role('button', name='Отмена', exact=True).is_visible())
        dialog.get_by_role('button', name='Отмена', exact=True).click()
        dialog = self.open_dialog()
        self.assertEqual(dialog.get_by_role('button', name='Проверить статус', exact=True).count(), 1,
                         'Closing an unknown create dialog preserves its pending operation')
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and '/api/session-create' in r.url]), 1)
        with self.page.expect_request(lambda r: r.method == 'GET' and '/api/session-create-status' in r.url) as status:
            dialog.get_by_role('button', name='Проверить статус', exact=True).click()
        query = dict(part.split('=', 1) for part in status.value.url.split('?', 1)[1].split('&'))
        self.assertEqual(query['operation_id'], payload['operation_id'])
        self.assertEqual(query['project'], 'demo')
        self.assertEqual(query['context_mode'], 'configured')
        self.assertEqual(query['provider_id'], 'codex')
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and '/api/session-create' in r.url]), 1)
        self.assertEqual(len([r for r in self.network if r.method == 'GET' and '/api/session-create-status' in r.url]), 1)

    def test_late_accepted_create_cannot_change_reselected_session_generation(self):
        private_json(self.evidence / 'control.json', {'hold_create': True})
        dialog = self.open_dialog()
        self.assertEqual(dialog.get_by_role('button', name='Создать', exact=True).count(), 1)
        with self.page.expect_request(lambda r: r.method == 'POST' and '/api/session-create' in r.url) as captured:
            dialog.get_by_role('button', name='Создать', exact=True).click()
        payload = json.loads(captured.value.post_data)
        dialog.get_by_role('button', name='Отмена', exact=True).click()
        beta = self.page.get_by_role('button', name=re.compile('Beta synthetic session'))
        self.assertEqual(beta.count(), 1)
        beta.click()
        alpha = self.page.get_by_role('button', name=re.compile('Alpha synthetic session'))
        self.assertEqual(alpha.count(), 1)
        alpha.click()
        private_json(self.evidence / 'release-create.json', {'release': True})
        self.page.wait_for_timeout(150)
        self.assertEqual(alpha.count(), 1, 'Late A response must not replace the reselected session')
        self.assertEqual(len([r for r in self.network if r.method == 'POST' and '/api/session-create' in r.url]), 1)
        self.assertEqual([c for c in self.calls() if c['method'] == 'create'][0]['operation_id'], payload['operation_id'])

    def test_malformed_accepted_dto_does_not_render_untrusted_values(self):
        private_json(self.evidence / 'control.json', {'create_result': 'malformed'})
        dialog = self.open_dialog()
        self.assertEqual(dialog.get_by_role('button', name='Создать', exact=True).count(), 1)
        dialog.get_by_role('button', name='Создать', exact=True).click()
        self.page.wait_for_timeout(100)
        body = self.page.locator('body').inner_text()
        self.assertNotIn('PRIVATE_PATH_SENTINEL', body)
        self.assertNotIn('onerror=alert(1)', body)
        self.assertEqual(self.page.locator('img[src="x"]').count(), 0)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--serve':
        serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main()
