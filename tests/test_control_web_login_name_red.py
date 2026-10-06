"""INV-WEB-13 blind owner-login contract; all credentials are synthetic."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'synthetic-owner-password'
SECRET = 'JBSWY3DPEHPK3PXP'
ORIGIN = 'https://control.example.test'


def load_web(case):
    path = ROOT / 'bin' / '_control_web.py'
    case.assertTrue(path.is_file())
    spec = importlib.util.spec_from_file_location('_control_web_login_name_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Backend:
    def __init__(self):
        self.calls = []

    def snapshot(self):
        self.calls.append(('snapshot',))
        return {'tasks': []}

    def answer(self, *args):
        self.calls.append(('answer', *args))
        return {'status': 'applied'}

    def verdict(self, *args):
        self.calls.append(('verdict', *args))
        return {'status': 'applied'}


class LoginNameHTTPContract(unittest.TestCase):
    # INV-WEB-13
    def setUp(self):
        self.web = load_web(self)
        self.now = 1800000000
        self.backend = Backend()
        self.root = tempfile.TemporaryDirectory(prefix='web-login-name-', dir='/var/tmp')
        self.addCleanup(self.root.cleanup)
        self.state = Path(self.root.name) / 'totp-state.json'
        self.state.write_text(json.dumps({'last_step': -1}))
        self.state.chmod(0o600)
        self.config = dict(origin=ORIGIN,
            password_hash=self.web.hash_password(PASSWORD), totp_secret=SECRET,
            session_ttl=10800, secure_cookie=True, totp_state_path=str(self.state),
            username='dwl')
        self.client = TestClient(self.web.create_app(self.config, self.backend,
            clock=lambda: self.now), base_url=ORIGIN)

    def attempt(self, username='dwl', password=PASSWORD, totp=None, **extra):
        body = {'username': username, 'password': password,
                'totp': self.web.totp_code(SECRET, self.now) if totp is None else totp}
        body.update(extra)
        return self.client.post('/api/login', json=body, headers={'Origin': ORIGIN})

    def safe_unauthorized(self, response):
        self.assertEqual(response.status_code, 401, response.text)
        body = response.json()
        self.assertEqual(set(body), {'error'})
        self.assertEqual(body['error'], 'unauthorized')
        self.assertNotIn(PASSWORD, response.text)
        self.assertNotIn(SECRET, response.text)
        self.assertFalse(self.client.cookies)

    def test_configured_username_is_required_exact_and_owner_only_fields_rejected(self):
        self.safe_unauthorized(self.attempt(username='owner'))
        self.safe_unauthorized(self.client.post('/api/login', json={
            'password': PASSWORD, 'totp': self.web.totp_code(SECRET, self.now)},
            headers={'Origin': ORIGIN}))
        for key in ('role', 'principal', 'grants'):
            response = self.attempt(**{key: 'admin'})
            self.assertEqual(response.status_code, 422, response.text)
            self.assertFalse(self.client.cookies)
        accepted = self.attempt()
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(set(accepted.json()), {'csrf'})
        attributes = {part.strip().lower() for part in accepted.headers['set-cookie'].split(';')[1:]}
        self.assertIn('max-age=10800', attributes)

    def test_legacy_config_without_username_accepts_only_owner(self):
        legacy = {key: value for key, value in self.config.items() if key != 'username'}
        legacy_state = Path(self.root.name) / 'legacy-totp-state.json'
        legacy_state.write_text(json.dumps({'last_step': -1}))
        legacy_state.chmod(0o600)
        legacy['totp_state_path'] = str(legacy_state)
        client = TestClient(self.web.create_app(legacy, self.backend,
            clock=lambda: self.now), base_url=ORIGIN)
        response = client.post('/api/login', json={
            'username': 'owner', 'password': PASSWORD,
            'totp': self.web.totp_code(SECRET, self.now)}, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        self.safe_unauthorized(self.attempt(username='owner'))

    def test_username_grammar_http_malformed_is_422_and_valid_wrong_is_same_401(self):
        malformed = ('', 'Dwl', ' dwl', 'dwl ', 'a', 'éx', 'ab.c', 'a' + 'b' * 32)
        for username in malformed:
            with self.subTest(username=username):
                response = self.attempt(username=username)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn(SECRET, response.text)
        wrong_name = self.attempt(username='other')
        wrong_password = self.attempt(username='dwl', password='wrong-synthetic-password')
        self.safe_unauthorized(wrong_name)
        self.safe_unauthorized(wrong_password)

    def test_grammatically_valid_unknown_username_still_verifies_password_hash(self):
        verify = self.web.verify_password
        with patch.object(self.web, 'verify_password', wraps=verify) as checked:
            response = self.attempt(username='someone-else')
        self.safe_unauthorized(response)
        checked.assert_called_once_with(PASSWORD, self.config['password_hash'])

    def test_wrong_name_does_not_consume_valid_totp_step(self):
        code = self.web.totp_code(SECRET, self.now)
        self.safe_unauthorized(self.attempt(username='other', totp=code))
        self.assertEqual(json.loads(self.state.read_text()), {'last_step': -1})
        accepted = self.attempt(username='dwl', totp=code)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(json.loads(self.state.read_text()), {'last_step': self.now // 30})

    def test_unknown_valid_form_attempts_are_rate_limited(self):
        responses = [self.attempt(username='unknown-' + str(i % 10)).status_code
                     for i in range(40)]
        self.assertIn(429, responses, responses)
        self.assertFalse(self.client.cookies)
        self.assertEqual(json.loads(self.state.read_text()), {'last_step': -1})

    def test_invalid_config_username_fails_before_auth_state_changes(self):
        before = self.state.read_bytes()
        for username in ('Owner', 'a', 'dwl!', 'éx', 'x' * 33):
            with self.subTest(username=username):
                with self.assertRaises(Exception):
                    self.web.create_app({**self.config, 'username': username}, self.backend,
                                        clock=lambda: self.now)
                self.assertEqual(self.state.read_bytes(), before)
                self.assertEqual(self.backend.calls, [])

    def test_login_session_keeps_absolute_three_hour_expiry(self):
        self.assertEqual(self.attempt().status_code, 200)
        self.now += 10799
        self.assertEqual(self.client.get('/api/session').status_code, 200)
        self.now += 2
        self.assertEqual(self.client.get('/api/session').status_code, 401)


class LoginNameProvisioningContract(unittest.TestCase):
    # INV-WEB-13
    def run_enrollment(self, username=None):
        with tempfile.TemporaryDirectory(prefix='web-login-enroll-', dir='/var/tmp') as directory:
            root = Path(directory)
            root.chmod(0o700)
            installed = root / 'bin'
            installed.mkdir(mode=0o700)
            for filename in ('ai-control-web', '_control_web.py'):
                shutil.copy2(ROOT / 'bin' / filename, installed / filename)
            auth, state = root / 'auth.json', root / 'totp-state.json'
            output = io.StringIO()
            args = [str(installed / 'ai-control-web'), 'init-auth', '--origin',
                    'http://127.0.0.1:8787', '--loopback-development', '--output',
                    str(auth), '--totp-state', str(state)]
            if username is not None:
                args += ['--username', username]
            with patch.object(sys, 'argv', args), \
                 patch.object(sys, 'path', [str(installed), *sys.path]), \
                 patch('getpass.getpass', return_value='synthetic-enrollment-password'), \
                 contextlib.redirect_stdout(output):
                runpy.run_path(str(installed / 'ai-control-web'), run_name='login_name_enrollment')['main']()
            config = json.loads(auth.read_text())
            self.assertNotIn('synthetic-enrollment-password', output.getvalue())
            self.assertNotIn(config['totp_secret'], output.getvalue())
            self.assertEqual(auth.stat().st_mode & 0o777, 0o600)
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            return config

    def test_init_auth_persists_custom_username(self):
        self.assertEqual(self.run_enrollment('dwl').get('username'), 'dwl')

    def test_init_auth_defaults_new_enrollment_to_owner(self):
        self.assertEqual(self.run_enrollment().get('username'), 'owner')


if __name__ == "__main__":
    unittest.main(verbosity=2)
