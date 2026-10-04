"""Blind INV-WEB-11 HTTP regressions for the accepted session reload spec.

Only the published create_app/hash_password/totp_code contract and existing
HTTP fixtures are used. No production module bodies or browser assets read.
Credentials are synthetic; state is private and disposable under /var/tmp.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from test_control_web_contract import Backend, load_feature, PASSWORD, SECRET, ORIGIN, QID


class SessionReloadContract(unittest.TestCase):
    # INV-WEB-11; retained INV-WEB-01/02/06 barriers on recovered sessions.
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='control-web-reload-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'totp-state.json'
        self.state.write_text(json.dumps({'last_step': -1}))
        self.state.chmod(0o600)
        self.web = load_feature(self, '_control_web.py')
        self.now = 1800000000
        self.backend = Backend()
        self.config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
            totp_secret=SECRET, session_ttl=60, secure_cookie=True,
            totp_state_path=str(self.state))
        self.app = self.web.create_app(self.config, self.backend, clock=lambda: self.now)
        self.client = self.new_client()
        self.addCleanup(self.client.close)

    def new_client(self, app=None):
        return TestClient(self.app if app is None else app, base_url=ORIGIN)

    def login(self):
        response = self.client.post('/api/login', json=dict(password=PASSWORD,
            totp=self.web.totp_code(SECRET, self.now)), headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()['csrf']
        self.assertIsInstance(self.csrf, str)
        self.assertTrue(self.csrf)
        self.assertEqual(self.backend.calls, [])
        return response

    def no_store(self, response):
        directives = {part.strip().lower() for part in response.headers.get('Cache-Control', '').split(',')}
        self.assertIn('no-store', directives)

    def session_ok(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json().get('csrf'), self.csrf)
        self.no_store(response)
        self.assertEqual(self.backend.calls, [])

    def session_error(self, response, status):
        self.assertEqual(response.status_code, status, response.text)
        body = response.json()
        self.assertNotIn('csrf', body)
        if hasattr(self, 'csrf'):
            self.assertNotIn(self.csrf, response.text)
        self.assertNotIn(PASSWORD, response.text)
        self.assertNotIn(SECRET, response.text)
        self.no_store(response)
        self.assertEqual(self.backend.calls, [])

    def test_valid_cookie_restores_identical_csrf_without_origin_or_backend(self):
        login = self.login()
        cookie_header = login.headers['set-cookie'].lower()
        for flag in ('httponly', 'secure', 'samesite=strict'):
            self.assertIn(flag, cookie_header)
        cookies_before = dict(self.client.cookies)
        consumed_before = self.state.read_bytes()
        # A reload has lost JS state: this GET supplies neither CSRF nor TOTP.
        self.session_ok(self.client.get('/api/session'))
        self.session_ok(self.client.get('/api/session', headers={'Origin': ORIGIN}))
        self.assertEqual(dict(self.client.cookies), cookies_before)
        self.assertEqual(self.state.read_bytes(), consumed_before,
                         'session lookup must not consume login/TOTP state')

    def test_missing_cookie_returns_401_and_does_not_create_session(self):
        self.session_error(self.client.get('/api/session'), 401)
        self.session_error(self.client.get('/api/session'), 401)
        self.assertFalse(self.client.cookies)
        self.assertEqual(json.loads(self.state.read_text()), {'last_step': -1})

    def test_unknown_cookie_returns_401_without_csrf(self):
        login = self.login()
        self.client.cookies.clear()
        cookie = '; '.join(f'{name}=synthetic-invalid-session' for name in login.cookies.keys())
        self.assertTrue(cookie, 'positive login must establish a session cookie')
        self.session_error(self.client.get('/api/session', headers={'Cookie': cookie}), 401)

    def test_foreign_origin_is_403_without_csrf_or_session_mutation(self):
        self.login()
        consumed_before = self.state.read_bytes()
        for origin in ('https://evil.example.test', ORIGIN + '.evil.test', 'null'):
            with self.subTest(origin=origin):
                self.session_error(self.client.get('/api/session', headers={'Origin': origin}), 403)
        self.session_ok(self.client.get('/api/session'))
        self.assertEqual(self.state.read_bytes(), consumed_before)

    def test_repeated_lookup_does_not_extend_absolute_session_ttl(self):
        self.login()
        for seconds in (25, 34):
            self.now += seconds
            self.session_ok(self.client.get('/api/session'))
        # Login age 61 seconds, despite a successful lookup two seconds ago.
        self.now += 2
        self.session_error(self.client.get('/api/session'), 401)
        self.session_error(self.client.get('/api/session'), 401)
        mutation = self.client.post('/api/answer', json=self.answer_body(),
            headers={'Origin': ORIGIN, 'X-CSRF-Token': self.csrf})
        self.assertIn(mutation.status_code, (401, 403), mutation.text)
        self.assertEqual(self.backend.calls, [])

    def test_logout_revokes_cookie_even_if_old_cookie_is_replayed(self):
        self.login()
        cookie = '; '.join(f'{name}={value}' for name, value in self.client.cookies.items())
        self.session_ok(self.client.get('/api/session'))
        logout = self.client.post('/api/logout', json={},
            headers={'Origin': ORIGIN, 'X-CSRF-Token': self.csrf})
        self.assertEqual(logout.status_code, 200, logout.text)
        self.session_error(self.client.get('/api/session'), 401)
        self.session_error(self.client.get('/api/session', headers={'Cookie': cookie}), 401)

    def test_server_restart_does_not_restore_memory_session(self):
        self.login()
        cookie = '; '.join(f'{name}={value}' for name, value in self.client.cookies.items())
        restarted_app = self.web.create_app(self.config, self.backend, clock=lambda: self.now)
        with self.new_client(restarted_app) as restarted:
            self.session_error(restarted.get('/api/session', headers={'Cookie': cookie}), 401)

    def answer_body(self):
        return dict(agent='task-one', qid=QID, decision='text', text='Recovered session reply')

    def test_recovered_csrf_allows_mutation_and_keeps_origin_csrf_barriers(self):
        self.login()
        recovered = self.client.get('/api/session')
        self.session_ok(recovered)
        restored_csrf = recovered.json()['csrf']
        for headers in ({'Origin': ORIGIN}, {'Origin': ORIGIN, 'X-CSRF-Token': 'wrong'},
                        {'X-CSRF-Token': restored_csrf},
                        {'Origin': 'https://evil.example.test', 'X-CSRF-Token': restored_csrf}):
            with self.subTest(headers=tuple(headers)):
                response = self.client.post('/api/answer', json=self.answer_body(), headers=headers)
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(self.backend.calls, [])
        response = self.client.post('/api/answer', json=self.answer_body(),
            headers={'Origin': ORIGIN, 'X-CSRF-Token': restored_csrf})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'status': 'applied'})
        self.assertEqual(self.backend.calls,
            [('answer', 'task-one', QID, 'text', 'Recovered session reply')])

    def test_backend_outage_does_not_affect_session_lookup(self):
        self.login()
        self.backend.failure = True
        self.session_ok(self.client.get('/api/session'))
        # Prove the failing backend fixture is meaningful on the actual tasks route.
        response = self.client.get('/api/tasks')
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(self.backend.calls, [('snapshot',)])

    def test_positive_existing_login_and_authenticated_mutation_control(self):
        self.login()
        response = self.client.post('/api/answer', json=self.answer_body(),
            headers={'Origin': ORIGIN, 'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.backend.calls,
            [('answer', 'task-one', QID, 'text', 'Recovered session reply')])


if __name__ == '__main__':
    unittest.main(verbosity=2)
