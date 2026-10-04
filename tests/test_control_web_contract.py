"""Blind HTTP acceptance for docs/specs/web.md; synthetic credentials only."""
import importlib.util
from pathlib import Path
import unittest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'JBSWY3DPEHPK3PXP'
PASSWORD = 'synthetic-web-test-password'
ORIGIN = 'https://control.example.test'
QID = '11111111-1111-4111-8111-111111111111'


def load_feature(case, filename):
    path = ROOT / 'bin' / filename
    case.assertTrue(path.is_file(), f'Absent WEB feature: public module {filename} required by docs/specs/web.md')
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Backend:
    def __init__(self):
        self.calls = []
        self.outcome = {'status': 'applied'}
        self.failure = False
    def snapshot(self):
        self.calls.append(('snapshot',))
        if self.failure:
            raise RuntimeError('synthetic-secret-from-backend')
        return {'tasks': [{'agent': 'task-one', 'engine': 'claude', 'state': 'waiting',
            'questions': [{'qid': QID, 'kind': 'info', 'status': 'open',
                'question': '<img src=x onerror=alert(1)>', 'allowed_decisions': []}],
            'result': {'generation': 'deadbeef', 'state': 'requested', 'summary': 'Ready',
                'commit_sha': 'a'*40, 'finalized': True}}]}
    def answer(self, agent, qid, decision, text):
        self.calls.append(('answer', agent, qid, decision, text))
        return self.outcome
    def verdict(self, agent, generation, decision, comment):
        self.calls.append(('verdict', agent, generation, decision, comment))
        return self.outcome


# INV-WEB-01 INV-WEB-02 INV-WEB-04 INV-WEB-05 INV-WEB-06 INV-WEB-08
class WebContract(unittest.TestCase):
    def setUp(self):
        self.web = load_feature(self, '_control_web.py')
        self.now = 1800000000
        self.backend = Backend()
        self.config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
            totp_secret=SECRET, session_ttl=60, secure_cookie=True)
        self.client = TestClient(self.web.create_app(self.config, self.backend, clock=lambda: self.now), base_url=ORIGIN)
    def login(self):
        r = self.client.post('/api/login', json={'password': PASSWORD, 'totp': self.web.totp_code(SECRET, self.now)}, headers={'Origin': ORIGIN})
        self.assertEqual(r.status_code, 200, r.text)
        self.csrf = r.json()['csrf']
        self.assertTrue(self.csrf)
        return r
    def post(self, path, body, **headers):
        return self.client.post(path, json=body, headers={'Origin': ORIGIN, 'X-CSRF-Token': self.csrf, **headers})
    def answer(self, **changes):
        return dict(agent='task-one', qid=QID, decision='text', text='Human reply', **changes)
    def verdict(self, **changes):
        body = dict(agent='task-one', generation='deadbeef', decision='accept', comment='', confirmed=True)
        body.update(changes)
        return body
    def safe_error(self, response, status):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(set(response.json()), {'error'})
        self.assertIsInstance(response.json()['error'], str)
        self.assertNotIn('synthetic-secret', response.text)

    def test_INV_WEB_01_password_hash_and_wrong_credentials(self):
        self.assertNotIn(PASSWORD, self.config['password_hash'])
        self.assertTrue(self.web.verify_password(PASSWORD, self.config['password_hash']))
        self.assertFalse(self.web.verify_password('wrong', self.config['password_hash']))
        for password, totp in [('wrong', self.web.totp_code(SECRET, self.now)), (PASSWORD, 'invalid')]:
            self.safe_error(self.client.post('/api/login', json=dict(password=password, totp=totp), headers={'Origin': ORIGIN}), 401)
        self.assertEqual(self.backend.calls, [])

    def test_INV_WEB_01_unauthenticated_never_reaches_backend(self):
        self.safe_error(self.client.get('/api/tasks'), 401)
        for route, body in [('/api/answer', self.answer()), ('/api/verdict', self.verdict())]:
            r = self.client.post(route, json=body, headers={'Origin': ORIGIN})
            self.assertIn(r.status_code, (401, 403))
        self.assertEqual(self.backend.calls, [])

    def test_INV_WEB_01_totp_replay_and_rate_limit(self):
        self.login()
        self.safe_error(self.client.post('/api/login', json={'password': PASSWORD, 'totp': self.web.totp_code(SECRET, self.now)}, headers={'Origin': ORIGIN}), 401)
        statuses = [self.client.post('/api/login', json={'password': 'wrong', 'totp': '000000'}, headers={'Origin': ORIGIN}).status_code for _ in range(100)]
        self.assertIn(429, statuses)

    def test_INV_WEB_02_cookie_expiry_logout(self):
        cookie = self.login().headers['set-cookie'].lower()
        for flag in ('httponly', 'secure', 'samesite=strict'):
            self.assertIn(flag, cookie)
        self.assertEqual(self.client.get('/api/tasks').status_code, 200)
        self.assertEqual(self.post('/api/logout', {}).status_code, 200)
        self.safe_error(self.client.get('/api/tasks'), 401)
        self.now += 30
        self.login()
        self.now += 61
        self.safe_error(self.client.get('/api/tasks'), 401)

    def test_INV_WEB_02_exact_origin_csrf_and_proxy_headers(self):
        self.login()
        for headers in ({'Origin': 'https://evil.example', 'X-CSRF-Token': self.csrf}, {'Origin': ORIGIN}, {'Origin': ORIGIN, 'X-CSRF-Token': 'wrong'}, {'X-CSRF-Token': self.csrf}, {'Origin': 'https://evil.example', 'X-CSRF-Token': self.csrf, 'X-Forwarded-Host': 'control.example.test', 'X-Forwarded-Proto': 'https'}):
            self.safe_error(self.client.post('/api/answer', json=self.answer(), headers=headers), 403)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.post('/api/answer', self.answer()).json(), {'status': 'applied'})

    def test_INV_WEB_02_csrf_cannot_cross_sessions(self):
        self.login()
        first = self.csrf
        second = TestClient(self.client.app, base_url=ORIGIN)
        self.now += 30
        r = second.post('/api/login', json={'password': PASSWORD, 'totp': self.web.totp_code(SECRET, self.now)}, headers={'Origin': ORIGIN})
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(first, r.json()['csrf'])
        self.safe_error(second.post('/api/answer', json=self.answer(), headers={'Origin': ORIGIN, 'X-CSRF-Token': first}), 403)
        self.assertEqual(self.backend.calls, [])

    def test_INV_WEB_02_insecure_only_explicit_loopback(self):
        for origin in ('http://control.example.test', 'http://127.0.0.1.evil.test', 'http://0.0.0.0'):
            with self.subTest(origin=origin), self.assertRaises((ValueError, RuntimeError)):
                self.web.create_app({**self.config, 'origin': origin, 'secure_cookie': False}, self.backend)
        self.web.create_app({**self.config, 'origin': 'http://127.0.0.1', 'secure_cookie': False}, self.backend)

    def test_INV_WEB_05_06_validation_does_not_call_writers(self):
        self.login()
        for changes in ({'agent': '../secret'}, {'qid': '../secret'}, {'decision': 'cancel'}, {'text': ''}, {'text': 'x'*16001}):
            body = self.answer()
            body.update(changes)
            self.safe_error(self.post('/api/answer', body), 422)
        for body in (self.verdict(confirmed=False), self.verdict(generation='DEADBEEF'), self.verdict(decision='cancel')):
            self.safe_error(self.post('/api/verdict', body), 422)
        self.assertEqual(self.backend.calls, [])

    def test_INV_WEB_06_answer_limit_and_explicit_accept(self):
        self.login()
        body = self.answer()
        body['text'] = 'я'*16000
        self.assertEqual(self.post('/api/answer', body).json()['status'], 'applied')
        self.assertEqual(self.post('/api/verdict', self.verdict()).json()['status'], 'applied')
        self.assertEqual(self.backend.calls[-1], ('verdict', 'task-one', 'deadbeef', 'accept', ''))

    def test_INV_WEB_06_reject_requires_fresh_totp(self):
        self.login()
        self.assertIn(self.post('/api/verdict', self.verdict(decision='reject')).status_code, (401, 403, 422))
        replay = self.web.totp_code(SECRET, self.now)
        self.assertIn(self.post('/api/verdict', self.verdict(decision='reject', totp=replay)).status_code, (401, 403))
        self.assertEqual(self.backend.calls, [])
        self.now += 30
        r = self.post('/api/verdict', self.verdict(decision='reject', totp=self.web.totp_code(SECRET, self.now)))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.backend.calls[-1][3], 'reject')

    def test_INV_WEB_04_transient_stale_already_are_not_applied(self):
        self.login()
        for outcome, status in [({'error': 'stale'}, 409), ({'error': 'saved_pending'}, 503), ({'status': 'already'}, 200)]:
            self.backend.outcome = outcome
            r = self.post('/api/answer', self.answer())
            self.assertEqual(r.status_code, status, r.text)
            self.assertNotEqual(r.json().get('status'), 'applied')

    def test_INV_WEB_05_08_backend_outage_visible_safe(self):
        self.login()
        self.backend.failure = True
        self.safe_error(self.client.get('/api/tasks'), 503)


if __name__ == '__main__':
    unittest.main(verbosity=2)
