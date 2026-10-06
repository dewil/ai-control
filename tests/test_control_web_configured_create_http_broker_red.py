"""Independent HTTP/owner-broker RED tests for configured session creation INV-WSESS-36."""
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
from test_control_web_session_chat_contract import ORIGIN, PASSWORD, SECRET, SID, feature

OPID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
EVIL_ORIGIN = 'https://evil.example.test'
OPTIONS = {'schema': 1, 'project': 'demo', 'options': [
    {'context_mode': 'configured', 'provider_id': 'codex', 'available': True, 'reason': None}]}
ACCEPTED = {'operation_id': OPID, 'status': 'accepted', 'session': {
    'sid': SID, 'project': 'demo', 'vendor': 'codex', 'context_mode': 'configured', 'title': None}}
UNKNOWN = {'operation_id': OPID, 'status': 'delivery_unknown'}


class HTTPBackend:
    def __init__(self):
        self.calls = []
        self.options_result = dict(OPTIONS)
        self.create_result = dict(ACCEPTED)
        self.status_result = dict(UNKNOWN)
        self.fallback_calls = []

    def session_create_options(self, project):
        self.calls.append(('session_create_options', project))
        return self.options_result

    def session_create(self, project, operation_id, context_mode, provider_id):
        self.calls.append(('session_create', project, operation_id, context_mode, provider_id))
        return self.create_result

    def session_create_status(self, project, operation_id, context_mode, provider_id):
        self.calls.append(('session_create_status', project, operation_id, context_mode, provider_id))
        return self.status_result

    def session_send(self, *args, **kwargs):
        self.fallback_calls.append((args, kwargs))
        return {'status': 'accepted'}


class ConfiguredCreateHTTP(unittest.TestCase):
    def setUp(self):
        self.web = feature(self, '_control_web')
        self.backend = HTTPBackend()
        self.now = 1800000000
        config = {'origin': ORIGIN, 'password_hash': self.web.hash_password(PASSWORD),
                  'totp_secret': SECRET, 'session_ttl': 60, 'secure_cookie': True}
        self.client = TestClient(self.web.create_app(config, self.backend, clock=lambda: self.now),
                                 base_url=ORIGIN)
        self.csrf = None

    def login(self):
        response = self.client.post('/api/login', json={'password': PASSWORD,
            'totp': self.web.totp_code(SECRET, self.now)}, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()['csrf']

    def post(self, body=None, *, headers=None, content=None):
        h = {'Origin': ORIGIN}
        if self.csrf is not None:
            h['X-CSRF-Token'] = self.csrf
        if headers:
            h.update(headers)
        if content is not None:
            h['Content-Type'] = 'application/json'
            return self.client.post('/api/session-create', content=content, headers=h)
        payload = {'project': 'demo', 'operation_id': OPID,
                   'context_mode': 'configured', 'provider_id': 'codex'} if body is None else body
        return self.client.post('/api/session-create', json=payload, headers=h)

    def test_options_create_and_manual_status_use_exact_safe_dtos(self):
        self.login()
        options = self.client.get('/api/session-create-options?project=demo', headers={'Origin': ORIGIN})
        self.assertEqual(options.status_code, 200, options.text)
        self.assertEqual(options.json(), OPTIONS)
        self.assertIn('no-store', options.headers.get('cache-control', ''))
        created = self.post()
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json(), ACCEPTED)
        self.assertIn('no-store', created.headers.get('cache-control', ''))
        status = self.client.get('/api/session-create-status?project=demo&operation_id=' + OPID +
            '&context_mode=configured&provider_id=codex', headers={'Origin': ORIGIN})
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json(), UNKNOWN)
        self.assertIn('no-store', status.headers.get('cache-control', ''))
        self.assertEqual(self.backend.calls, [
            ('session_create_options', 'demo'),
            ('session_create', 'demo', OPID, 'configured', 'codex'),
            ('session_create_status', 'demo', OPID, 'configured', 'codex')])

    def test_http_requires_exact_bounded_json_and_query_schemas(self):
        self.login()
        unsafe = [
            {'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'account_id': None},
            {'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'sid': SID},
            {'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'model': 'gpt-x'},
            {'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'cwd': '/tmp'},
            {'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'rpc_method': 'thread/start'},
            {'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'native_rpc': True},
            {'project': 'demo', 'operation_id': 'bad', 'context_mode': 'configured', 'provider_id': 'codex'},
            {'project': '../private', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex'},
            {'project': 'demo', 'operation_id': OPID, 'context_mode': 'bound', 'provider_id': 'codex'},
            {'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'claude'},
        ]
        for body in unsafe:
            with self.subTest(keys=sorted(body)):
                response = self.post(body)
                self.assertEqual(response.status_code, 422, response.text)
        duplicate = ('{"project":"demo","operation_id":"' + OPID +
            '","context_mode":"configured","provider_id":"codex","project":"other"}')
        self.assertEqual(self.post(content=duplicate).status_code, 422)
        self.assertEqual(self.post(content=b'{"project":"demo","operation_id":"' + OPID.encode() +
            b'","context_mode":"configured","provider_id":"codex","extra":NaN}').status_code, 422)
        self.assertEqual(self.post(content=b'\xff').status_code, 422)
        self.assertEqual(self.post(content=b' ' * 4097).status_code, 422)
        invalid_queries = [
            '/api/session-create-options',
            '/api/session-create-options?project=demo&project=demo',
            '/api/session-create-options?project=demo&sid=' + SID,
            '/api/session-create-status?project=demo&operation_id=' + OPID + '&context_mode=configured&provider_id=codex&sid=' + SID,
            '/api/session-create-status?project=demo&operation_id=bad&context_mode=configured&provider_id=codex',
            '/api/session-create-status?project=demo&operation_id=' + OPID + '&context_mode=configured&provider_id=codex&x=' + ('a' * 4100),
        ]
        for path in invalid_queries:
            with self.subTest(path_length=len(path)):
                response = self.client.get(path, headers={'Origin': ORIGIN})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.backend.calls, [])

    def test_http_auth_origin_csrf_project_denial_and_invalid_dto_are_safe(self):
        unauthenticated = self.post()
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertIn('no-store', unauthenticated.headers.get('cache-control', ''))
        self.login()
        for headers in ({'Origin': EVIL_ORIGIN}, {'X-CSRF-Token': 'wrong'}):
            with self.subTest(headers=headers):
                response = self.post(headers=headers)
                self.assertEqual(response.status_code, 403)
                self.assertIn('no-store', response.headers.get('cache-control', ''))
        self.assertEqual(self.client.get('/api/session-create-options?project=demo',
            headers={'Origin': EVIL_ORIGIN}).status_code, 403)
        self.backend.options_result = {'error': 'forbidden'}
        denied = self.client.get('/api/session-create-options?project=demo', headers={'Origin': ORIGIN})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json(), {'error': 'forbidden'})
        self.backend.create_result = {**ACCEPTED, 'session_ref': 'synthetic-private-sentinel'}
        malformed = self.post()
        self.assertEqual(malformed.status_code, 503)
        self.assertEqual(malformed.json(), {'error': 'unavailable'})
        self.assertNotIn('synthetic-private-sentinel', malformed.text)
        self.assertIn('no-store', malformed.headers.get('cache-control', ''))
        self.backend.create_result = {'error': 'unavailable'}
        unsupported = self.post()
        self.assertEqual(unsupported.status_code, 503)
        self.assertEqual(self.backend.fallback_calls, [])


class OwnerBackend:
    def __init__(self):
        self.calls = []
        self.options_result = dict(OPTIONS)
        self.create_result = dict(ACCEPTED)
        self.status_result = dict(UNKNOWN)

    def session_create_options(self, project):
        self.calls.append(('session_create_options', project))
        return self.options_result

    def session_create(self, project, operation_id, context_mode, provider_id):
        self.calls.append(('session_create', project, operation_id, context_mode, provider_id))
        return self.create_result

    def session_create_status(self, project, operation_id, context_mode, provider_id):
        self.calls.append(('session_create_status', project, operation_id, context_mode, provider_id))
        return self.status_result


class ConfiguredCreateBroker(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('_control_web_broker')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-configured-create-broker-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.socket_path = str(self.base / 'broker.sock')
        self.backend = OwnerBackend()
        self.stop = threading.Event()
        self.errors = []
        self.worker = None

    def start(self, allowed_uid=None):
        uid = os.getuid() if allowed_uid is None else allowed_uid
        def serve():
            try:
                self.module.serve_broker(self.socket_path, self.backend, uid, stop_event=self.stop)
            except Exception as error:
                self.errors.append(error)
        self.worker = threading.Thread(target=serve, daemon=True)
        self.worker.start()
        self.addCleanup(self.shutdown)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.errors:
                break
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(.1)
                    probe.connect(self.socket_path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(.01)
        self.assertEqual(self.errors, [])
        self.assertTrue(Path(self.socket_path).exists())

    def shutdown(self):
        self.stop.set()
        if self.worker:
            self.worker.join(2)

    def wire(self, payload):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(self.socket_path)
            conn.sendall(data + b'\n')
            raw = b''
            while b'\n' not in raw:
                raw += conn.recv(131073)
                self.assertLessEqual(len(raw), 128 * 1024)
        return json.loads(raw.split(b'\n', 1)[0])

    def test_owner_accepts_only_fixed_create_operations_and_exact_dtos(self):
        self.start()
        requests = [
            {'op': 'session_create_options', 'project': 'demo'},
            {'op': 'session_create', 'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex'},
            {'op': 'session_create_status', 'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex'},
        ]
        expected = [OPTIONS, ACCEPTED, UNKNOWN]
        for request, result in zip(requests, expected):
            with self.subTest(op=request['op']):
                self.assertEqual(self.wire(request), result)
        self.assertEqual(self.backend.calls, [
            ('session_create_options', 'demo'),
            ('session_create', 'demo', OPID, 'configured', 'codex'),
            ('session_create_status', 'demo', OPID, 'configured', 'codex')])

    def test_owner_rejects_sids_selectors_unknown_fields_duplicates_and_bad_dtos(self):
        self.start()
        bad = [
            {'op': 'session_create', 'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'sid': SID},
            {'op': 'session_create', 'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'account_id': None},
            {'op': 'session_create', 'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'model': 'gpt-x'},
            {'op': 'session_create', 'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'native_method': 'thread/start'},
            {'op': 'session_create_status', 'project': 'demo', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex', 'sid': SID},
            {'op': 'session_create', 'project': '../private', 'operation_id': OPID, 'context_mode': 'configured', 'provider_id': 'codex'},
            {'op': 'session_create', 'project': 'demo', 'operation_id': 'bad', 'context_mode': 'configured', 'provider_id': 'codex'},
        ]
        for request in bad:
            with self.subTest(keys=sorted(request)):
                self.assertIn('error', self.wire(request))
        duplicate = ('{"op":"session_create_status","project":"demo","operation_id":"' + OPID +
            '","context_mode":"configured","provider_id":"codex","project":"other"}').encode()
        self.assertIn('error', self.wire(duplicate))
        self.assertEqual(self.backend.calls, [])
        self.backend.create_result = {**ACCEPTED, 'session_ref': 'synthetic-private-sentinel'}
        malformed = self.wire({'op': 'session_create', 'project': 'demo', 'operation_id': OPID,
            'context_mode': 'configured', 'provider_id': 'codex'})
        self.assertEqual(malformed, {'error': 'unavailable'})
        self.assertNotIn('synthetic-private-sentinel', json.dumps(malformed))

    def test_socket_backend_exposes_only_fixed_create_methods_and_preserves_peer_gate(self):
        self.start()
        client = self.module.SocketBackend(self.socket_path)
        methods = [getattr(client, name, None) for name in (
            'session_create_options', 'session_create', 'session_create_status')]
        self.assertTrue(all(callable(method) for method in methods),
                        'SocketBackend must expose fixed configured-create methods')
        if not all(callable(method) for method in methods):
            return
        self.assertEqual(methods[0]('demo'), OPTIONS)
        self.assertEqual(methods[1]('demo', OPID, 'configured', 'codex'), ACCEPTED)
        self.assertEqual(methods[2]('demo', OPID, 'configured', 'codex'), UNKNOWN)
        self.assertEqual(len(self.backend.calls), 3)

    def test_owner_keeps_peer_uid_refusal_before_create_dispatch(self):
        self.start(allowed_uid=os.getuid() + 1)
        response = self.wire({'op': 'session_create_options', 'project': 'demo'})
        self.assertEqual(response, {'error': 'forbidden'})
        self.assertEqual(self.backend.calls, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
