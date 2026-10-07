"""Blind INV-APP-01..05/07 tests from frozen fc2d847 specs, not runtime.
All capabilities/credentials and filesystem contents are synthetic.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_control_web_login_name_red import load_web, Backend, ORIGIN, PASSWORD, SECRET

DAY = 86400


class AppAuthContract(unittest.TestCase):
    # INV-APP-01 INV-APP-02 INV-APP-03 INV-APP-04 INV-APP-05 INV-APP-07
    def setUp(self):
        self.web = load_web(self)
        self.now = 1800000000
        self.root = tempfile.TemporaryDirectory(prefix='app-auth-blind-', dir='/var/tmp')
        self.addCleanup(self.root.cleanup)
        self.private = Path(self.root.name)
        self.private.chmod(0o700)
        self.replay = self.private / 'replay.json'
        self.replay.write_text('{"last_step":-1}')
        self.replay.chmod(0o600)
        self.db = self.private / 'grants.sqlite'
        self.config = dict(origin=ORIGIN, username='dwl',
            password_hash=self.web.hash_password(PASSWORD), totp_secret=SECRET,
            session_ttl=10800, secure_cookie=True, totp_state_path=str(self.replay),
            android_auth_db=str(self.db))
        self.backend = Backend()
        self.client = self.new_client()

    def new_client(self, config=None, **kwargs):
        return TestClient(self.web.create_app(self.config if config is None else config,
            self.backend, clock=lambda: self.now, **kwargs), base_url=ORIGIN)

    def body(self, **changes):
        result = dict(username='dwl', password=PASSWORD,
            totp=self.web.totp_code(SECRET, self.now))
        result.update(changes)
        return result

    def post(self, endpoint, body=None, token=None, client=None, headers=None, raw=None):
        hs = [('Origin', ORIGIN)] if headers is None else headers
        if token is not None:
            hs = [*hs, ('Authorization', 'Bearer ' + token)]
        kwargs = {'content': raw} if raw is not None else {'json': body}
        return (client or self.client).post('/api/app/' + endpoint, headers=hs, **kwargs)

    def error(self, response, status, name):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json(), {'error': name})
        self.assertEqual(response.headers.get('cache-control'), 'no-store')
        self.assertNotIn('set-cookie', response.headers)
        for secret in (PASSWORD, SECRET, str(self.private)):
            self.assertNotIn(secret, response.text)

    def login(self, client=None):
        response = self.post('login', self.body(), client=client)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()), {'device_token'})
        token = response.json()['device_token']
        self.assertRegex(token, r'\A[A-Za-z0-9_-]{43}\Z')
        self.assertEqual(response.headers.get('cache-control'), 'no-store')
        cookie = response.headers['set-cookie'].lower()
        for part in ('control_session=', 'secure', 'httponly', 'samesite=strict', 'max-age=10800'):
            self.assertIn(part, cookie)
        return token

    def session(self, token, foreground=False, client=None):
        return self.post('session', {'foreground_open': foreground}, token, client)

    def test_login_and_web_session_public_contract(self):
        self.login()
        response = self.client.get('/api/session')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('csrf', response.json())

    def test_all_app_origin_preflights_precede_body_and_auth_work(self):
        for endpoint in ('login', 'session', 'logout'):
            for headers in ([], [('Origin', ORIGIN + '/')], [('Origin', ORIGIN), ('Origin', ORIGIN)]):
                with self.subTest(endpoint=endpoint, headers=headers):
                    with patch.object(self.web, 'verify_password', side_effect=AssertionError('verifier before origin')):
                        self.error(self.post(endpoint, headers=headers, raw='{'), 403, 'forbidden')
        self.assertFalse(self.db.exists())
        self.assertEqual(json.loads(self.replay.read_text()), {'last_step': -1})

    def test_owner_only_identity_true_gate_precedes_shape_and_db(self):
        self.assertIn('owner_only', inspect.signature(self.web.create_app).parameters,
            'public create_app owner_only gate absent')
        for value in (False, None, 1, 'true'):
            client = self.new_client(owner_only=value)
            for endpoint in ('login', 'session', 'logout'):
                with self.subTest(owner_only=value, endpoint=endpoint):
                    self.error(self.post(endpoint, client=client, raw='{'), 403, 'forbidden')
        self.assertFalse(self.db.exists())

    def test_raw_json_independent_of_content_type(self):
        for media in ('text/plain', 'application/octet-stream', None):
            self.now += 30
            hs = [('Origin', ORIGIN)] + ([] if media is None else [('Content-Type', media)])
            response = self.post('login', headers=hs, raw=json.dumps(self.body()))
            self.assertEqual(response.status_code, 200, response.text)

    def test_strict_json_and_endpoint_shapes(self):
        shapes = {
            'login': ('{}', '{"username":"dwl","password":"p","totp":"x","role":"admin"}',
                '{"username":"dwl","username":"dwl","password":"p","totp":"x"}',
                '{"username":"dwl","password":null,"totp":"x"}',
                '{"username":"dwl","password":"","totp":"x"}',
                json.dumps(self.body(password='x' * 1025)), json.dumps(self.body(totp='x' * 1025))),
            'session': ('{}', '{"foreground_open":1}', '{"foreground_open":null}',
                '{"foreground_open":true,"foreground_open":false}', '{"foreground_open":true,"role":"owner"}'),
            'logout': ('{"extra":0}', '{"foreground_open":false}'),
        }
        for endpoint, bodies in shapes.items():
            for raw in (*bodies, '', '{', 'null', '[]', 'true', 'NaN', '{"x":Infinity}', '{}{}', ' ' * (128 * 1024) + '{}'):
                with self.subTest(endpoint=endpoint, raw=raw[:80]):
                    self.error(self.post(endpoint, raw=raw), 422, 'invalid_request')
        self.assertFalse(self.db.exists())

    def test_username_fullmatch_and_wrong_totp_stays_credential_failure(self):
        for username in ('DWL', 'dwl ', 'dwl\n', 'éx', 'a', 'a' * 33, 'x' * 1025):
            with self.subTest(username=username):
                self.error(self.post('login', self.body(username=username)), 422, 'invalid_request')
        self.error(self.post('login', self.body(totp='not-a-code')), 401, 'unauthorized')

    def test_wrong_name_and_password_work_without_totp_consumption(self):
        responses = []
        for changes in ({'username': 'other'}, {'password': 'synthetic-wrong'}, {'totp': 'bad'}):
            with patch.object(self.web, 'verify_password', wraps=self.web.verify_password) as checked:
                response = self.post('login', self.body(**changes))
            self.error(response, 401, 'unauthorized')
            checked.assert_called_once_with(changes.get('password', PASSWORD), self.config['password_hash'])
            responses.append((response.json(), response.headers.get('www-authenticate')))
            self.assertEqual(json.loads(self.replay.read_text()), {'last_step': -1})
        self.assertEqual(responses, [responses[0]] * 3)
        self.login()

    def test_db_absent_failure_after_shape_before_credentials_and_bearer(self):
        config = {k: v for k, v in self.config.items() if k != 'android_auth_db'}
        client = self.new_client(config)
        for endpoint, body in (('login', self.body()), ('session', {'foreground_open': False}), ('logout', {})):
            with self.subTest(endpoint=endpoint):
                self.error(self.post(endpoint, {}, client=client, raw='{'), 422, 'invalid_request')
                with patch.object(self.web, 'verify_password', side_effect=AssertionError('hash before DB')):
                    self.error(self.post(endpoint, body, client=client), 503, 'unavailable')
        web = client.post('/api/login', json=self.body(), headers={'Origin': ORIGIN})
        self.assertEqual(web.status_code, 200, web.text)

    def test_strict_single_bearer_on_session_and_logout(self):
        token = self.login()
        malformed = (None, '', 'bearer ' + token, 'Bearer  ' + token,
            ' Bearer ' + token, 'Bearer ' + token + ' ', 'Bearer\t' + token,
            'Bearer ' + token + '=','Bearer ' + token + ' extra', 'Bearer ' + 'x' * 42,
            'Bearer ' + 'x' * 44)
        for endpoint, body in (('session', {'foreground_open': False}), ('logout', {})):
            for auth in malformed:
                hs = [('Origin', ORIGIN)] + ([] if auth is None else [('Authorization', auth)])
                with self.subTest(endpoint=endpoint, auth=auth):
                    self.error(self.post(endpoint, body, headers=hs), 401, 'device_unauthorized')
            self.error(self.post(endpoint, body, headers=[('Origin', ORIGIN),
                ('Authorization', 'Bearer ' + token), ('Authorization', 'Bearer ' + token)]),
                401, 'device_unauthorized')
        self.assertEqual(self.session(token).status_code, 200)

    def test_shared_exact_ten_attempts_both_directions_and_reset(self):
        for first, second in (('/api/app/login', '/api/login'), ('/api/login', '/api/app/login')):
            self.now += 61
            for _ in range(10):
                r = self.client.post(first, json=self.body(username='other'), headers={'Origin': ORIGIN})
                self.assertEqual(r.status_code, 401, r.text)
            r = self.client.post(second, json=self.body(username='other'), headers={'Origin': ORIGIN})
            self.assertEqual(r.status_code, 429, r.text)
            self.now += 60
            r = self.client.post(second, json=self.body(username='other'), headers={'Origin': ORIGIN})
            self.assertEqual(r.status_code, 401, r.text)

    def test_preflight_errors_do_not_spend_shared_budget(self):
        for _ in range(12):
            self.error(self.post('login', raw='{'), 422, 'invalid_request')
            self.error(self.post('login', self.body(), headers=[]), 403, 'forbidden')
        for _ in range(10):
            self.error(self.post('login', self.body(username='other')), 401, 'unauthorized')
        self.error(self.post('login', self.body()), 429, 'rate_limited')

    def test_replay_shared_both_directions_and_restart(self):
        self.login()
        response = self.client.post('/api/login', json=self.body(), headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 401, response.text)
        self.now += 30
        response = self.client.post('/api/login', json=self.body(), headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        self.error(self.post('login', self.body()), 401, 'unauthorized')
        self.error(self.post('login', self.body(), client=self.new_client()), 401, 'unauthorized')

    def test_same_device_preserves_cookie_and_csrf_foreign_cookie_replaced(self):
        token = self.login()
        cookie = self.client.cookies.get('control_session')
        csrf = self.client.get('/api/session').json()['csrf']
        r = self.session(token, True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {'status': 'ok', 'session_replaced': False})
        self.assertEqual(self.client.cookies.get('control_session'), cookie)
        self.assertEqual(self.client.get('/api/session').json()['csrf'], csrf)
        self.now += 30
        other = self.login()
        r = self.session(token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {'status': 'ok', 'session_replaced': True})
        self.assertNotEqual(self.client.cookies.get('control_session'), cookie)
        independent = self.new_client()
        self.assertEqual(self.session(other, client=independent).status_code, 200)

    def test_restart_persists_grant_only_hash_and_loses_cookie(self):
        token = self.login()
        cookie = self.client.cookies.get('control_session')
        self.assertTrue(self.db.is_file())
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(self.db) as db:
            dump = '\n'.join(db.iterdump())
        self.assertNotIn(token, dump)
        # SQLite BLOB dumps use uppercase X'HEX'; TEXT digests may be lowercase.
        self.assertIn(hashlib.sha256(token.encode('ascii')).hexdigest(), dump.lower())
        for file in self.private.iterdir():
            if file.is_file():
                self.assertNotIn(token.encode(), file.read_bytes(), file.name)
        restarted = self.new_client()
        restarted.cookies.set('control_session', cookie)
        self.assertEqual(restarted.get('/api/session').status_code, 401)
        r = self.session(token, client=restarted)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {'status': 'ok', 'session_replaced': True})

    def test_idle_boundary_false_admission_does_not_renew(self):
        token = self.login()
        self.now += 7 * DAY - 1
        self.assertEqual(self.session(token, False).status_code, 200)
        self.now += 1
        self.error(self.session(token, False), 401, 'device_unauthorized')
        self.assertEqual(self.client.get('/api/session').status_code, 401)

    def test_foreground_rolling_deadline_past_original_thirty_days(self):
        token = self.login()
        for _ in range(6):
            self.now += 6 * DAY
            self.assertEqual(self.session(token, True).status_code, 200)
        # now is 36 days after issue; rolling deadline remains admitted.
        self.assertEqual(self.session(token, False).status_code, 200)
        self.now += 7 * DAY
        self.error(self.session(token), 401, 'device_unauthorized')

    def test_logout_exact_body_then_idempotent_revoke_and_cookie_denial(self):
        token = self.login()
        for raw in ('', '{', 'null', '[]', '{"extra":true}'):
            self.error(self.post('logout', token=token, raw=raw), 422, 'invalid_request')
        self.assertEqual(self.session(token).status_code, 200)
        cookie = self.client.cookies.get('control_session')
        for _ in range(2):
            r = self.post('logout', {}, token)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json(), {'status': 'ok'})
            self.assertEqual(r.headers.get('cache-control'), 'no-store')
            self.assertIn('max-age=0', r.headers['set-cookie'].lower())
        self.error(self.session(token, True), 401, 'device_unauthorized')
        self.client.cookies.set('control_session', cookie)
        self.assertEqual(self.client.get('/api/session').status_code, 401)
        self.error(self.post('logout', {}, 'A' * 43), 401, 'device_unauthorized')

    def test_known_idle_grant_can_be_revoked(self):
        token = self.login()
        self.now += 7 * DAY
        self.error(self.session(token), 401, 'device_unauthorized')
        r = self.post('logout', {}, token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {'status': 'ok'})

    def test_web_logout_revokes_device_but_web_only_logout_leaves_other_grant(self):
        token = self.login()
        csrf = self.client.get('/api/session').json()['csrf']
        r = self.client.post('/api/logout', json={}, headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf})
        self.assertEqual(r.status_code, 200, r.text)
        self.error(self.session(token), 401, 'device_unauthorized')
        self.now += 30
        token = self.login()
        browser = self.new_client()
        self.now += 30
        r = browser.post('/api/login', json=self.body(), headers={'Origin': ORIGIN})
        self.assertEqual(r.status_code, 200, r.text)
        csrf = browser.get('/api/session').json()['csrf']
        r = browser.post('/api/logout', json={}, headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.session(token).status_code, 200)

    def test_unsafe_and_corrupt_db_fail_closed_without_path_details(self):
        candidates = []
        unsafe = self.private / 'unsafe'
        unsafe.mkdir(mode=0o755)
        # Earlier tests may set process umask077: this fixture must be truly unsafe.
        unsafe.chmod(0o755)
        candidates.append(unsafe / 'grants.sqlite')
        corrupt = self.private / 'corrupt.sqlite'
        corrupt.write_bytes(b'not a SQLite database')
        corrupt.chmod(0o600)
        candidates.append(corrupt)
        real = self.private / 'real.sqlite'
        real.write_bytes(b'')
        real.chmod(0o600)
        link = self.private / 'symlink.sqlite'
        link.symlink_to(real)
        candidates.append(link)
        for path in candidates:
            with self.subTest(path=path.name):
                client = self.new_client({**self.config, 'android_auth_db': str(path)})
                self.error(self.post('login', self.body(), client=client), 503, 'unavailable')
        self.assertEqual(json.loads(self.replay.read_text()), {'last_step': -1})

    def test_revoke_admission_race_cannot_restore_authority(self):
        token = self.login()
        peers = [self.new_client() for _ in range(5)]
        with ThreadPoolExecutor(max_workers=5) as pool:
            admits = [pool.submit(self.session, token, True, peer) for peer in peers[:4]]
            revoke = pool.submit(self.post, 'logout', {}, token, peers[4])
            revoked = revoke.result()
            self.assertEqual(revoked.status_code, 200, revoked.text)
            for request in admits:
                result = request.result()
                self.assertIn(result.status_code, (200, 401), result.text)
        for peer in peers:
            self.error(self.session(token, True, peer), 401, 'device_unauthorized')
            self.assertEqual(peer.get('/api/session').status_code, 401)

    def test_web_only_unknown_and_expired_cookies_replace_without_authority_transfer(self):
        token = self.login()
        self.now += 30
        browser = self.new_client()
        web = browser.post('/api/login', json=self.body(), headers={'Origin': ORIGIN})
        self.assertEqual(web.status_code, 200, web.text)
        web_cookie = browser.cookies.get('control_session')
        self.client.cookies.set('control_session', web_cookie)
        r = self.session(token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['session_replaced'])
        # Original web-only session remains a separate authority.
        self.assertEqual(browser.get('/api/session').status_code, 200)
        self.client.cookies.set('control_session', 'unknown-synthetic-cookie')
        r = self.session(token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['session_replaced'])
        self.now += 10800
        r = self.session(token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['session_replaced'])

    def test_legacy_native_paths_404_web_r5_absolute_ttl_unchanged(self):
        for endpoint in ('login', 'session', 'logout'):
            r = self.client.post('/api/android/' + endpoint, json={}, headers={'Origin': ORIGIN})
            self.assertEqual(r.status_code, 404, r.text)
        r = self.client.post('/api/login', json=self.body(), headers={'Origin': ORIGIN})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(set(r.json()), {'csrf'})
        self.now += 10799
        self.assertEqual(self.client.get('/api/session').status_code, 200)
        self.now += 1
        self.assertEqual(self.client.get('/api/session').status_code, 401)


if __name__ == '__main__':
    unittest.main()
