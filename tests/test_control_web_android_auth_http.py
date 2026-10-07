"""Blind HTTP admission contracts; synthetic credentials and private fixture DB."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from test_control_web_contract import Backend, load_feature, PASSWORD, SECRET, ORIGIN

# INV-APP-01/03/05: migrate legacy fixture to exact username/app paths/logout body; assertions retained.
DAY = 86400


# INV-AUTHAND-01 INV-AUTHAND-02 INV-AUTHAND-03 INV-AUTHAND-04 INV-AUTHAND-05 INV-AUTHAND-06
class AndroidAuthHTTPContract(unittest.TestCase):
    def setUp(self):
        self.web = load_feature(self, '_control_web.py')
        previous = os.umask(0o077)
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix='android-http-contract-', dir='/var/tmp')
        finally:
            os.umask(previous)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'totp-state.json'
        self.state.write_text(json.dumps({'last_step': -1}))
        self.state.chmod(0o600)
        self.now = 1800000000
        self.backend = Backend()
        self.config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
                           totp_secret=SECRET, session_ttl=10800, secure_cookie=True,
                           totp_state_path=str(self.state),
                           android_auth_db=str(self.root / 'device.sqlite3'))

    def client(self, config=None, owner_only=True):
        client = TestClient(self.web.create_app(config or self.config, self.backend,
                           clock=lambda: self.now, owner_only=owner_only), base_url=ORIGIN)
        self.addCleanup(client.close)
        return client

    def login(self, client, route='/api/app/login', password=PASSWORD):
        return client.post(route, json={'username': 'owner', 'password': password,
                           'totp': self.web.totp_code(SECRET, self.now)},
                           headers={'Origin': ORIGIN})

    def admitted(self, client=None):
        client = client or self.client()
        response = self.login(client)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()), {'device_token'})
        token = response.json()['device_token']
        self.assertIsInstance(token, str)
        self.assertTrue(token)
        self.assertIn('no-store', response.headers.get('cache-control', ''))
        self.assertTrue(client.cookies.get('control_session'))
        return client, token

    def refresh(self, client, token, foreground=False, **kwargs):
        return client.post('/api/app/session', json={'foreground_open': foreground},
                           headers={'Origin': ORIGIN, 'Authorization': 'Bearer ' + token}, **kwargs)

    def denied(self, response, status, error):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json(), {'error': error})
        self.assertNotIn(PASSWORD, response.text)
        self.assertNotIn(SECRET, response.text)
        self.assertNotIn(str(self.root), response.text)

    def session(self, client):
        response = client.get('/api/session')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json().get('csrf'))
        return response.json()

    def test_login_sets_secure_httponly_cookie_exact_three_hours(self):
        client, _ = self.admitted()
        cookie = self.login_cookie_header(client)
        self.assertIn('max-age=10800', cookie.lower())
        self.assertIn('httponly', cookie.lower())
        self.assertIn('secure', cookie.lower())
        self.assertIn('samesite=strict', cookie.lower())

    def login_cookie_header(self, client):
        # Response from renewal exposes the same public cookie attributes.
        token_client = client
        self.now += 30
        result = self.login(token_client)
        self.assertEqual(result.status_code, 200, result.text)
        return result.headers.get('set-cookie', '')

    def test_live_refresh_preserves_cookie_csrf_and_reports_not_replaced(self):
        client, token = self.admitted()
        cookie = client.cookies.get('control_session')
        csrf = self.session(client)['csrf']
        self.now += 2 * 3600
        response = self.refresh(client, token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'status': 'ok', 'session_replaced': False})
        self.assertEqual(client.cookies.get('control_session'), cookie)
        self.assertEqual(self.session(client)['csrf'], csrf)
        self.now += 2 * 3600
        self.assertEqual(self.session(client)['csrf'], csrf, 'device cookie expiry renewed')

    def test_expired_cookie_refresh_replaces_cookie_and_csrf(self):
        client, token = self.admitted()
        cookie = client.cookies.get('control_session')
        csrf = self.session(client)['csrf']
        self.now += 10800
        self.assertEqual(client.get('/api/session').status_code, 401)
        response = self.refresh(client, token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'status': 'ok', 'session_replaced': True})
        self.assertNotEqual(client.cookies.get('control_session'), cookie)
        self.assertNotEqual(self.session(client)['csrf'], csrf)
        self.assertEqual(self.backend.calls, [], 'renewal cannot replay a backend mutation')

    def test_restart_restores_device_admission_with_replacement_cookie(self):
        client, token = self.admitted()
        old = client.cookies.get('control_session')
        restart = self.client()
        restart.cookies.set('control_session', old)
        self.assertEqual(restart.get('/api/session').status_code, 401)
        response = self.refresh(restart, token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['session_replaced'])
        self.session(restart)
        self.assertEqual(self.backend.calls, [])

    def test_background_refresh_does_not_prevent_week_idle(self):
        client, token = self.admitted()
        for _ in range(6):
            self.now += DAY
            self.assertEqual(self.refresh(client, token).status_code, 200)
        self.now += DAY
        self.denied(self.refresh(client, token, foreground=True), 401, 'device_unauthorized')
        self.assertEqual(client.get('/api/session').status_code, 401)

    def test_foreground_refresh_extends_admission_using_same_token(self):
        client, token = self.admitted()
        for _ in range(7):
            self.now += 6 * DAY
            self.assertEqual(self.refresh(client, token, foreground=True).status_code, 200)
        self.session(client)

    def test_idle_invalidates_still_live_device_bound_cookie(self):
        client, token = self.admitted()
        self.now += 7 * DAY - 3600
        self.assertEqual(self.refresh(client, token).status_code, 200)
        self.now += 3600
        self.assertEqual(client.get('/api/session').status_code, 401)

    def test_android_logout_without_live_cookie_revokes_persistently(self):
        client, token = self.admitted()
        self.now += 10800
        client.cookies.clear()
        response = client.post('/api/app/logout', json={}, headers={'Origin': ORIGIN,
                               'Authorization': 'Bearer ' + token})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'status': 'ok'})
        again = client.post('/api/app/logout', json={}, headers={'Origin': ORIGIN,
                            'Authorization': 'Bearer ' + token})
        self.assertEqual(again.status_code, 200)
        self.denied(self.refresh(self.client(), token, foreground=True), 401, 'device_unauthorized')

    def test_cookie_logout_revokes_only_its_device(self):
        client, token = self.admitted()
        csrf = self.session(client)['csrf']
        self.now += 30
        other, other_token = self.admitted()
        response = client.post('/api/logout', headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf})
        self.assertEqual(response.status_code, 200, response.text)
        self.denied(self.refresh(client, token, foreground=True), 401, 'device_unauthorized')
        self.assertEqual(self.refresh(other, other_token).status_code, 200)

    def test_browser_logout_does_not_revoke_unrelated_device(self):
        device, token = self.admitted()
        self.now += 30
        browser = self.client()
        login = self.login(browser, route='/api/login')
        self.assertEqual(login.status_code, 200)
        csrf = self.session(browser)['csrf']
        self.assertEqual(browser.post('/api/logout', headers={'Origin': ORIGIN,
                         'X-CSRF-Token': csrf}).status_code, 200)
        self.assertEqual(self.refresh(device, token).status_code, 200)

    def test_web_and_android_login_share_totp_replay_protection(self):
        client, _ = self.admitted()
        self.assertEqual(self.login(self.client(), route='/api/login').status_code, 401)
        self.now += 30
        browser = self.client()
        self.assertEqual(self.login(browser, route='/api/login').status_code, 200)
        self.assertEqual(self.login(client).status_code, 401)

    def test_wrong_password_does_not_issue_cookie_or_grant(self):
        client = self.client()
        response = self.login(client, password='synthetic-wrong-password')
        self.assertEqual(response.status_code, 401, response.text)
        self.assertFalse(client.cookies.get('control_session'))
        self.assertEqual(self.backend.calls, [])

    def test_android_and_browser_share_login_rate_limit(self):
        client = self.client()
        throttled = None
        for i in range(40):
            route = '/api/app/login' if i % 2 else '/api/login'
            response = self.login(client, route=route, password='synthetic-wrong-password')
            if response.status_code == 429:
                throttled = route
                break
            self.assertEqual(response.status_code, 401, response.text)
        self.assertIsNotNone(throttled, 'bounded failed attempts must throttle shared auth')
        next_route = '/api/login' if throttled == '/api/app/login' else '/api/app/login'
        self.assertEqual(self.login(client, route=next_route).status_code, 429)

    def test_wrong_or_missing_origin_rejected_before_grant_creation(self):
        client = self.client()
        for origin in (None, 'https://foreign.invalid', ORIGIN + '/'):
            headers = {} if origin is None else {'Origin': origin}
            for route, payload in [('/api/app/login', {'username': 'owner', 'password': PASSWORD, 'totp': '123456'}),
                                   ('/api/app/session', {'foreground_open': True}),
                                   ('/api/app/logout', {})]:
                with self.subTest(origin=origin, route=route):
                    self.denied(client.post(route, json=payload, headers=headers), 403, 'forbidden')
        self.assertFalse(client.cookies.get('control_session'))

    def test_malformed_foreground_flag_rejected_without_token_revocation(self):
        client, token = self.admitted()
        for payload in ({}, {'foreground_open': 'true'}, {'foreground_open': 1},
                        {'foreground_open': None}, []):
            with self.subTest(payload=payload):
                response = client.post('/api/app/session', json=payload,
                           headers={'Origin': ORIGIN, 'Authorization': 'Bearer ' + token})
                self.denied(response, 422, 'invalid_request')
        self.assertEqual(self.refresh(client, token).status_code, 200)

    def test_invalid_bearer_is_terminal_device_unauthorized(self):
        client = self.client()
        for authorization in (None, 'Basic fake', 'Bearer ', 'Bearer unknown-test-token'):
            headers = {'Origin': ORIGIN}
            if authorization is not None:
                headers['Authorization'] = authorization
            for route in ('/api/app/session', '/api/app/logout'):
                with self.subTest(authorization=authorization, route=route):
                    response = client.post(route, json=({'foreground_open': False} if route.endswith('/session') else {}), headers=headers)
                    self.denied(response, 401, 'device_unauthorized')
                    self.assertNotIn('unknown-test-token', response.text)

    def test_disabled_android_store_503_leaves_browser_login_operational(self):
        config = dict(self.config)
        del config['android_auth_db']
        client = self.client(config)
        for route, payload in [('/api/app/login', {'username': 'owner', 'password': PASSWORD, 'totp': '123456'}),
                               ('/api/app/session', {'foreground_open': False}),
                               ('/api/app/logout', {})]:
            self.denied(client.post(route, json=payload, headers={'Origin': ORIGIN,
                        'Authorization': 'Bearer synthetic-token'}), 503, 'unavailable')
        self.assertEqual(self.login(client, route='/api/login').status_code, 200)

    def test_corrupt_store_returns_generic_503(self):
        path = Path(self.config['android_auth_db'])
        path.write_bytes(b'not sqlite fixture')
        path.chmod(0o600)
        client = self.client()
        response = self.login(client)
        self.denied(response, 503, 'unavailable')
        self.assertFalse(client.cookies.get('control_session'))

    def test_nonowner_mode_forbids_all_android_routes_before_store_access(self):
        client = self.client(owner_only=False)
        for route, payload in [('/api/app/login', {'username': 'owner', 'password': PASSWORD, 'totp': '123456'}),
                               ('/api/app/session', {'foreground_open': True}),
                               ('/api/app/logout', {})]:
            self.denied(client.post(route, json=payload, headers={'Origin': ORIGIN,
                        'Authorization': 'Bearer synthetic-token'}), 403, 'forbidden')
        self.assertFalse(Path(self.config['android_auth_db']).exists())
        self.assertFalse(client.cookies.get('control_session'))

    def test_browser_expiry_stays_absolute_after_read_requests(self):
        client = self.client()
        self.assertEqual(self.login(client, route='/api/login').status_code, 200)
        self.now += 10800 - 1
        self.session(client)
        self.now += 1
        self.assertEqual(client.get('/api/session').status_code, 401)

    def test_browser_default_ttl_remains_one_hour(self):
        config = dict(self.config)
        del config['session_ttl']
        client = self.client(config)
        response = self.login(client, route='/api/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn('max-age=3600', response.headers.get('set-cookie', '').lower())
        self.now += 3600
        self.assertEqual(client.get('/api/session').status_code, 401)


if __name__ == '__main__':
    unittest.main()
