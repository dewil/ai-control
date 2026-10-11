"""INV-COMPAT-03/04: reviewed0.162.1 composer via real synthetic HTTP API."""
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

import test_control_web_model_controls_browser as fixture
import test_control_web_codex_0162_mutations_blind as mutations
from test_control_web_read_capabilities_support import expected_capabilities


def serve(root, evidence):
    """Extend the public synthetic backend, retaining the actual HTTP DTO validator."""
    sys.path.insert(0, str(root / 'bin'))
    web = importlib.import_module('_control_web')
    create_app = web.create_app
    def application(config, backend, **kwargs):
        def capabilities(project, sid):
            data = json.loads((evidence / 'control.json').read_text())
            with (evidence / 'calls.jsonl').open('a') as handle:
                handle.write(json.dumps(dict(method='capabilities', project=project, sid=sid)) + '\n')
            return data.get('capabilities', expected_capabilities())
        backend.session_capabilities = capabilities
        return create_app(config, backend, **kwargs)
    web.create_app = application
    fixture.serve(root, evidence)


class Codex0162BrowserBlind(unittest.TestCase):
    # Reuse public browser lifecycle/DOM helpers, without inheriting old test cases.
    stop_server = classmethod(fixture.ModelControlsBrowserContract.stop_server.__func__)
    for name in ('setUp', 'tearDown', 'calls', 'open_alpha', 'assert_controls',
                 'wait_for_option', 'send_button', 'send_requests'):
        locals()[name] = getattr(fixture.ModelControlsBrowserContract, name)

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.evidence = Path(tempfile.mkdtemp(prefix='control-0162-browser-', dir='/var/tmp'))
        cls.evidence.chmod(0o700)
        fixture.private_json(cls.evidence / 'control.json', dict(default_models=fixture.available()))
        interpreter = os.environ.get('CONTROL_MODEL_CONTROLS_SERVER_PYTHON', sys.executable)
        cls.root = Path(os.environ.get('CONTROL_MODEL_CONTROLS_REPO', str(fixture.ROOT)))
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve', str(cls.root), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        while not (cls.evidence / 'ready.json').exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None: raise RuntimeError('Synthetic capability fixture failed to start')
            time.sleep(.02)
        cls.url = json.loads((cls.evidence / 'ready.json').read_text())['url']
        cls.playwright = sync_playwright().start(); cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_MODEL_CONTROLS_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport=dict(width=390, height=844), color_scheme='dark', has_touch=True)
        cls.addClassCleanup(cls.context.close)
        login = cls.context.new_page(); login.goto(cls.url)
        login.locator('#username').fill('owner'); login.locator('input[type=password]').fill(fixture.PASSWORD)
        login.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(fixture.totp())
        login.get_by_role('button', name='Войти', exact=True).click()
        login.get_by_role('button', name='Сессии', exact=True).or_(login.get_by_role('tab', name='Сессии', exact=True)).wait_for()
        login.close()

    def control(self, capabilities, **kwargs):
        fixture.private_json(self.evidence / 'control.json', dict(default_models=fixture.available(), capabilities=capabilities, **kwargs))

    def open_capability(self, dto):
        self.control(dto)
        with self.page.expect_response(lambda response: '/api/session-capabilities?' in response.url) as received:
            self.open_alpha()
        self.assertEqual(received.value.status, 200, 'Actual HTTP DTO validator must admit this capability')
        self.assertEqual(received.value.json(), dto)
        self.wait_for_option('Model Alpha')

    def test_ready_version_admits_exact_send_but_missing_effort_inflight_and_unknown_stay_blocked(self):
        # INV-COMPAT-03: existing unknown denial is replaced by an applied reviewed DTO.
        self.open_capability(expected_capabilities())
        self.page.locator('textarea').fill(mutations.TEXT)
        self.page.wait_for_timeout(100)
        self.assertTrue(self.send_button().is_disabled())
        self.assertEqual(self.send_requests(), [])
        blocked = mutations.reviewed_capabilities()
        blocked['operations']['send'] = dict(supported=False, reason='unavailable')
        self.control(blocked)
        with self.page.expect_response(lambda response: '/api/session-capabilities?' in response.url) as refused:
            self.alpha_session.click()
        self.assertEqual(refused.value.status, 200)
        self.assertEqual(refused.value.json(), blocked)
        self.page.locator('textarea').fill(mutations.TEXT)
        self.page.wait_for_timeout(100)
        self.assertTrue(self.send_button().is_disabled(), 'Reviewed version must apply the per-session send refusal')
        self.assertEqual(self.send_requests(), [])
        self.control(mutations.reviewed_capabilities(), send_delay=.5, send_status='delivery_unknown')
        with self.page.expect_response(lambda response: '/api/session-capabilities?' in response.url) as received:
            self.alpha_session.click()
        self.assertEqual(received.value.status, 200, 'Actual HTTP validator must recognize reviewed0.162.1')
        self.assertEqual(received.value.json(), mutations.reviewed_capabilities())
        model, effort = self.assert_controls(); self.wait_for_option('Model Alpha')
        self.page.locator('textarea').fill(mutations.TEXT)
        model.select_option(label='Model Alpha')
        self.assertTrue(self.send_button().is_disabled(), 'Explicit model requires an effort')
        self.assertEqual(self.send_requests(), [])
        effort.select_option(label='high')
        self.assertTrue(self.send_button().is_enabled(), 'Applied reviewed capability must release the previous version denial')
        with self.page.expect_request(lambda request: request.method == 'POST' and '/api/session-send' in request.url):
            self.send_button().click()
        self.assertTrue(self.send_button().is_disabled(), 'Inflight send cannot be duplicated')
        self.page.get_by_role('button', name='Проверить доставку', exact=True).wait_for()
        self.assertTrue(self.send_button().is_disabled(), 'Unknown delivery cannot create another send')
        self.assertEqual(self.page.locator('textarea').input_value(), mutations.TEXT)
        self.assertEqual(len(self.send_requests()), 1)
        body = json.loads(self.send_requests()[0].post_data)
        self.assertEqual(set(body), {'project', 'sid', 'message_id', 'text', 'selection'})
        self.assertEqual((body['project'], body['sid'], body['text']), ('demo', fixture.SID, mutations.TEXT))
        self.assertEqual(body['selection'], dict(catalog_id=fixture.MODEL_CATALOG_ID, model_id='alpha-ui', effort='high'))
        calls = self.calls()
        self.assertGreaterEqual(len([call for call in calls if call['method'] == 'capabilities']), 3)
        self.assertEqual(len([call for call in calls if call['method'] == 'send']), 1)

    def test_unknown_version_never_enables_send_despite_valid_draft_and_catalog(self):
        # INV-COMPAT-03: valid catalog/text cannot authorize an unreviewed version.
        self.open_capability(expected_capabilities())
        self.page.locator('textarea').fill('Synthetic unreviewed version')
        self.page.wait_for_timeout(100)
        self.assertTrue(self.send_button().is_disabled())
        self.assertEqual(self.send_requests(), [])
        self.assertEqual(len([call for call in self.calls() if call['method'] == 'capabilities']), 1)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--serve': serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else: unittest.main()
