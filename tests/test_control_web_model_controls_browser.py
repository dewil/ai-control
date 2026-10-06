"""Source-blind INV-WSESS-27 browser contracts with synthetic HTTP fixtures."""
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

from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET, SID

ROOT = Path(__file__).resolve().parents[1]
OTHER = '44444444-4444-4444-8444-444444444444'
MODEL_CATALOG_ID = 'a' * 64


def available(rows=None, catalog_id=MODEL_CATALOG_ID, expires_in_ms=60000):
    return {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
            'selection_support': 'available', 'reason': None, 'catalog_id': catalog_id,
            'expires_in_ms': expires_in_ms, 'rows': rows or [
                {'id': 'alpha-ui', 'label': 'Model Alpha', 'efforts': ['low', 'high'],
                 'default_effort': 'low', 'is_default': True},
                {'id': 'beta-ui', 'label': 'Model Beta', 'efforts': ['high', 'medium'],
                 'default_effort': 'medium', 'is_default': False},
                {'id': 'gamma-ui', 'label': 'Model Gamma', 'efforts': ['low'],
                 'default_effort': 'low', 'is_default': False}]}


def unavailable(reason='unsupported_capability', vendor='codex'):
    return {'schema': 1, 'vendor': vendor, 'context_kind': 'legacy_unbound',
            'selection_support': 'unavailable', 'reason': reason, 'catalog_id': None,
            'expires_in_ms': 0, 'rows': []}


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
            return {'rows': [{'sid': SID, 'title': 'Model Alpha synthetic session', 'status': 'idle'},
                             {'sid': OTHER, 'title': 'Model Beta synthetic session', 'status': 'idle'}], 'has_more': False}
        def session_models(self, project, sid):
            data = json.loads((evidence / 'control.json').read_text(encoding='utf-8'))
            record({'method': 'models', 'sid': sid})
            delay = data.get('model_delay', {}).get(sid, 0)
            if delay: time.sleep(delay)
            return data.get('models', {}).get(sid, data.get('default_models', available()))
        def session_history(self, project, sid, cursor):
            title = 'Alpha' if sid == SID else 'Beta'
            return {'turns': [{'id': 'synthetic-turn', 'status': 'completed', 'items': [
                {'id': 'synthetic-assistant', 'role': 'assistant',
                 'text': f'{title} synthetic history', 'truncated': False}]}],
                'next_cursor': None, 'truncated': False, 'recent_sends': []}
        def session_send(self, project, sid, message_id, text, selection=None):
            data = json.loads((evidence / 'control.json').read_text(encoding='utf-8'))
            record({'method': 'send', 'sid': sid, 'message_id': message_id,
                    'text': text, 'selection': selection})
            if data.get('send_delay'): time.sleep(data['send_delay'])
            status = data.get('send_status', 'accepted')
            if status == 'stale': return {'error': 'stale'}
            return {'status': status, 'message_id': message_id,
                    'turn_id': SID if status == 'accepted' else None}
        def session_send_status(self, project, sid, message_id):
            data = json.loads((evidence / 'control.json').read_text(encoding='utf-8'))
            record({'method': 'status', 'sid': sid, 'message_id': message_id})
            return {'status': data.get('checked_status', 'delivery_unknown'),
                    'message_id': message_id, 'turn_id': None}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0)); listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD),
                          'totp_secret': SECRET, 'session_ttl': 3600, 'secure_cookie': False}, Backend())
    private_json(evidence / 'ready.json', {'url': origin})
    uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[listener])


class ModelControlsBrowserContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Optional Playwright browser dependency unavailable')
        os.umask(0o077)
        cls.evidence = Path(tempfile.mkdtemp(prefix='control-model-controls-', dir='/var/tmp'))
        cls.evidence.chmod(0o700)
        private_json(cls.evidence / 'control.json', {'default_models': available()})
        interpreter = os.environ.get('CONTROL_MODEL_CONTROLS_SERVER_PYTHON', sys.executable)
        cls.root = Path(os.environ.get('CONTROL_MODEL_CONTROLS_REPO', str(ROOT)))
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve', str(cls.root), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        while not (cls.evidence / 'ready.json').exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None: raise RuntimeError('Synthetic fixture server failed to start')
            time.sleep(.02)
        cls.url = json.loads((cls.evidence / 'ready.json').read_text(encoding='utf-8'))['url']
        cls.playwright = sync_playwright().start(); cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_MODEL_CONTROLS_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={'width': 390, 'height': 844}, color_scheme='dark', has_touch=True)
        cls.addClassCleanup(cls.context.close)
        login = cls.context.new_page(); login.goto(cls.url)
        login.locator('input[type=password]').fill(PASSWORD)
        login.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        login.get_by_role('button', name=re.compile('^Войти$', re.I)).click()
        login.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(login.get_by_role('tab', name=re.compile('^Сессии$', re.I))).wait_for()
        login.close()

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try: cls.server.wait(4)
        except subprocess.TimeoutExpired: cls.server.kill(); cls.server.wait()

    def setUp(self):
        private_json(self.evidence / 'control.json', {'default_models': available()})
        (self.evidence / 'calls.jsonl').unlink(missing_ok=True)
        self.page = self.context.new_page(); self.page.set_default_timeout(5000)
        self.addCleanup(self.page.close)
        self.network = []; self.errors = []
        self.page.on('request', lambda request: self.network.append(request))
        self.page.on('pageerror', lambda error: self.errors.append(type(error).__name__))
        self.page.goto(self.url)
        self.page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(self.page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).click()
        choose_project(self.page, 'demo')
        self.alpha_session = self.page.get_by_role('button', name=re.compile('Model Alpha synthetic session'))
        self.beta_session = self.page.get_by_role('button', name=re.compile('Model Beta synthetic session'))
        self.alpha_session.wait_for(state='visible')

    def tearDown(self):
        self.assertEqual(self.errors, [], 'Synthetic browser flow must not raise JavaScript exceptions')
        self.assertFalse(any(request.url.split('/')[2] != self.url.split('/')[2] for request in self.network),
                         'Synthetic browser flow must not contact another origin')
        self.assertTrue(self.page.evaluate('localStorage.length===0 && sessionStorage.length===0'),
                        'Selection must stay in session-local draft state')

    def calls(self):
        path = self.evidence / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def open_alpha(self):
        self.alpha_session.click()
        self.page.locator('textarea').wait_for(state='visible')
        self.assert_controls()

    def assert_controls(self):
        model = self.page.get_by_role('combobox', name='Модель', exact=True)
        effort = self.page.get_by_role('combobox', name='Уровень размышления', exact=True)
        self.assertEqual(model.count(), 1, 'INV-WSESS-27 must render one labelled native model select')
        self.assertEqual(effort.count(), 1, 'INV-WSESS-27 must render one labelled native effort select')
        return model, effort

    def wait_for_option(self, label):
        self.page.get_by_role('option', name=label, exact=True).wait_for(state='attached')

    def send_button(self):
        return self.page.get_by_role('button', name='Отправить', exact=True)

    def send_requests(self):
        return [request for request in self.network if request.method == 'POST' and '/api/session-send' in request.url]

    def test_INV_WSESS_27_available_catalog_starts_inherit_and_explains_sticky_future_effect(self):
        self.open_alpha()
        model, effort = self.assert_controls()
        self.wait_for_option('Model Alpha')
        self.assertEqual(model.locator('option').all_text_contents()[:2], ['Наследовать текущую', 'Model Alpha'])
        self.assertEqual(effort.locator('option').first.inner_text(), 'Выберите уровень размышления')
        self.assertEqual(effort.input_value(), '', 'Catalog default is not effective thread state')
        body = self.page.locator('body').inner_text()
        self.assertIn('Выбор сохраняется для следующих сообщений; перед отправкой можно изменить', body)
        self.assertIn('Уже начатая работа сохраняет свои настройки; выбор действует при следующем запуске', body)
        self.assertFalse(any(request.method == 'POST' for request in self.network), 'Opening controls is metadata-only')

    def test_INV_WSESS_27_effort_choices_follow_model_and_incompatible_effort_resets_visibly(self):
        self.open_alpha(); model, effort = self.assert_controls(); self.wait_for_option('Model Gamma')
        model.select_option(label='Model Alpha'); effort.select_option(label='high')
        model.select_option(label='Model Beta')
        self.assertEqual(effort.input_value(), 'high', 'A compatible effort remains selected')
        model.select_option(label='Model Gamma')
        self.assertEqual(effort.locator('option').first.inner_text(), 'Выберите уровень размышления')
        self.assertEqual(effort.input_value(), '', 'An unsupported effort must reset instead of being reused')
        status = self.page.get_by_role('status').all_inner_texts()
        self.assertTrue(any(re.search(r'уров|размыш', value, re.I) for value in status),
                        'Incompatible effort reset needs a visible polite announcement')
        model.select_option(label='Наследовать текущую')
        self.assertEqual(effort.input_value(), '', 'Inherit clears explicit effort')

    def test_INV_WSESS_27_explicit_send_waits_for_effort_and_posts_exact_ui_selection_shape(self):
        self.open_alpha(); model, effort = self.assert_controls(); self.wait_for_option('Model Alpha')
        draft = 'Synthetic explicit model choice'
        self.page.locator('textarea').fill(draft)
        model.select_option(label='Model Alpha')
        self.assertFalse(self.send_button().is_enabled(), 'Explicit model without an effort cannot submit')
        self.assertEqual(self.send_requests(), [], 'Missing effort must be rejected before HTTP send')
        effort.select_option(label='high')
        self.assertTrue(self.send_button().is_enabled())
        self.send_button().click()
        self.page.get_by_role('status').filter(has_text=re.compile('принято', re.I)).wait_for()
        requests = self.send_requests(); self.assertEqual(len(requests), 1)
        body = json.loads(requests[0].post_data)
        self.assertEqual(set(body), {'project', 'sid', 'message_id', 'text', 'selection'})
        self.assertEqual(body['text'], draft)
        self.assertEqual(body['selection'], {'catalog_id': MODEL_CATALOG_ID, 'model_id': 'alpha-ui', 'effort': 'high'})
        self.assertNotIn('wire_model', body); self.assertNotIn('vendor', body); self.assertNotIn('context_id', body)

    def test_INV_WSESS_27_inherit_request_omits_selection_entirely(self):
        self.open_alpha(); model, effort = self.assert_controls(); self.wait_for_option('Model Alpha')
        model.select_option(label='Наследовать текущую')
        self.page.locator('textarea').fill('Synthetic inherit request')
        self.send_button().click()
        self.page.get_by_role('status').filter(has_text=re.compile('принято', re.I)).wait_for()
        self.assertEqual(len(self.send_requests()), 1)
        body = json.loads(self.send_requests()[0].post_data)
        self.assertEqual(set(body), {'project', 'sid', 'message_id', 'text'}, 'Inherit is represented by omission')
        self.assertNotIn('selection', body)
        self.assertEqual(self.calls()[-1]['selection'], None)

    def test_INV_WSESS_27_unsupported_catalog_keeps_inherit_send_without_model_fallback(self):
        private_json(self.evidence / 'control.json', {'default_models': unavailable()})
        self.open_alpha(); model, _ = self.assert_controls()
        self.assertEqual(model.locator('option').all_text_contents(), ['Наследовать текущую'])
        self.assertRegex(self.page.locator('body').inner_text(), r'(?i)недоступ|не поддерж|модел|выбор')
        self.page.locator('textarea').fill('Synthetic inherit under unavailable catalog')
        self.assertTrue(self.send_button().is_enabled(), 'Unavailable discovery cannot remove ordinary inherit send')
        self.send_button().click()
        self.page.get_by_role('status').filter(has_text=re.compile('принято', re.I)).wait_for()
        body = json.loads(self.send_requests()[0].post_data)
        self.assertNotIn('selection', body, 'Unsupported catalog must not silently choose a default model')

    def test_INV_WSESS_27_expired_catalog_blocks_explicit_send_and_never_falls_back(self):
        private_json(self.evidence / 'control.json', {'default_models': available(expires_in_ms=40)})
        self.open_alpha(); model, effort = self.assert_controls(); self.wait_for_option('Model Alpha')
        model.select_option(label='Model Alpha'); effort.select_option(label='high')
        self.page.wait_for_timeout(150)
        self.page.locator('textarea').fill('Synthetic expired catalog draft')
        self.assertFalse(self.send_button().is_enabled(), 'Expired catalog must block explicit send')
        self.assertEqual(self.send_requests(), [], 'Expiry must not turn an explicit choice into inherit')
        self.assertEqual(self.page.locator('textarea').input_value(), 'Synthetic expired catalog draft')
        self.assertRegex(self.page.locator('body').inner_text(), r'(?i)ист[её]к|обнов|устар|каталог')

    def test_INV_WSESS_27_stale_explicit_send_preserves_draft_and_pair_without_automatic_retry(self):
        private_json(self.evidence / 'control.json', {'default_models': available(), 'send_status': 'stale'})
        self.open_alpha(); model, effort = self.assert_controls(); self.wait_for_option('Model Alpha')
        model.select_option(label='Model Alpha'); effort.select_option(label='high')
        draft = 'Synthetic draft after stale catalog'
        self.page.locator('textarea').fill(draft); self.send_button().click()
        self.page.get_by_role('status').filter(has_text=re.compile(r'устар|обнов|ошиб|каталог', re.I)).wait_for()
        self.assertEqual(self.page.locator('textarea').input_value(), draft)
        self.assertEqual(model.locator('option:checked').inner_text(), 'Model Alpha')
        self.assertEqual(effort.locator('option:checked').inner_text(), 'high')
        self.assertEqual(len(self.send_requests()), 1, 'Known stale pre-effects error cannot trigger retry or fallback')
        self.assertEqual(self.calls()[-1]['selection'], {'catalog_id': MODEL_CATALOG_ID, 'model_id': 'alpha-ui', 'effort': 'high'})

    def test_INV_WSESS_27_late_catalog_response_cannot_replace_current_session_catalog(self):
        private_json(self.evidence / 'control.json', {
            'models': {SID: available([{'id': 'alpha-ui', 'label': 'Model Alpha', 'efforts': ['high'],
                                       'default_effort': 'high', 'is_default': True}]),
                       OTHER: available([{'id': 'beta-ui', 'label': 'Model Beta', 'efforts': ['medium'],
                                          'default_effort': 'medium', 'is_default': True}], catalog_id='b' * 64)},
            'model_delay': {SID: .6}})
        self.alpha_session.click()
        self.page.locator('textarea').wait_for(state='visible')
        model, _ = self.assert_controls()
        deadline = time.monotonic() + 1.0
        while not any('/api/session-models?' in request.url and SID in request.url for request in self.network) and time.monotonic() < deadline:
            self.page.wait_for_timeout(20)
        self.assertTrue(any('/api/session-models?' in request.url and SID in request.url for request in self.network),
                        'Opening a session must start its model catalog request before testing late-response fencing')
        self.beta_session.click()
        model, _ = self.assert_controls()
        self.wait_for_option('Model Beta')
        self.page.wait_for_timeout(800)
        options = model.locator('option').all_text_contents()
        self.assertIn('Model Beta', options)
        self.assertNotIn('Model Alpha', options, 'Late response from previous sid cannot replace current catalog')
        self.assertFalse(any(request.method == 'POST' for request in self.network), 'Catalog race cannot send')

    def test_INV_WSESS_27_pending_send_locks_controls_and_keeps_immutable_selection_snapshot(self):
        private_json(self.evidence / 'control.json', {'default_models': available(), 'send_delay': 1.0})
        self.open_alpha(); model, effort = self.assert_controls(); self.wait_for_option('Model Alpha')
        model.select_option(label='Model Alpha'); effort.select_option(label='high')
        self.page.locator('textarea').fill('Synthetic pending snapshot')
        with self.page.expect_request(lambda request: request.method == 'POST' and '/api/session-send' in request.url):
            self.send_button().click()
        self.assertTrue(model.is_disabled(), 'Model control remains locked until this send resolves')
        self.assertTrue(effort.is_disabled(), 'Effort control remains locked until this send resolves')
        request = self.send_requests()[0]
        body = json.loads(request.post_data)
        self.assertEqual(body['text'], 'Synthetic pending snapshot')
        self.assertEqual(body['selection'], {'catalog_id': MODEL_CATALOG_ID, 'model_id': 'alpha-ui', 'effort': 'high'})
        self.page.get_by_role('status').filter(has_text=re.compile('принято', re.I)).wait_for()
        self.assertEqual(len(self.send_requests()), 1)

    def test_INV_WSESS_27_unknown_receipt_keeps_snapshot_and_blocks_new_send(self):
        private_json(self.evidence / 'control.json', {'default_models': available(), 'send_status': 'delivery_unknown'})
        self.open_alpha(); model, effort = self.assert_controls(); self.wait_for_option('Model Alpha')
        model.select_option(label='Model Alpha'); effort.select_option(label='high')
        draft = 'Synthetic unknown receipt selection'
        self.page.locator('textarea').fill(draft); self.send_button().click()
        check = self.page.get_by_role('button', name='Проверить доставку', exact=True)
        check.wait_for(state='visible')
        self.assertEqual(self.page.locator('textarea').input_value(), draft)
        self.assertEqual(model.locator('option:checked').inner_text(), 'Model Alpha')
        self.assertEqual(effort.locator('option:checked').inner_text(), 'high')
        self.assertTrue(model.is_disabled(), 'Unknown receipt keeps its selection snapshot locked')
        self.assertTrue(effort.is_disabled(), 'Unknown receipt cannot be changed into a new explicit override')
        self.assertFalse(self.send_button().is_enabled(), 'Unknown receipt locks retry/override pending manual resolution')
        check.click()
        self.assertEqual(len([call for call in self.calls() if call['method'] == 'send']), 1)
        statuses = [call for call in self.calls() if call['method'] == 'status']
        self.assertGreaterEqual(len(statuses), 1)
        self.assertEqual({call['message_id'] for call in statuses}, {self.calls()[0]['message_id']})


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--serve': serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else: unittest.main(verbosity=2)
