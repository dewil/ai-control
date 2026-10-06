"""Source-blind HTTP, broker, and concurrency RED for web attention.

All requests and snapshots here are synthetic. No filesystem registry, native RPC,
network, account, or service data is read.
"""
import copy
import hashlib
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
sys.path.insert(0, str(ROOT / 'tests'))
from test_control_web_session_chat_contract import ORIGIN, PASSWORD, SECRET, feature
from test_control_web_attention import question, task, make_overview


class BackendStub:
    def __init__(self, value=None, *, tasks=None):
        self.value = value
        self.tasks = list(tasks or [])
        self.calls = 0
        self.snapshot_calls = 0

    def attention_snapshot(self):
        self.calls += 1
        return copy.deepcopy(self.value)

    def snapshot(self):
        self.snapshot_calls += 1
        return {'tasks': copy.deepcopy(self.tasks)}


class AttentionHttpBrokerRED(unittest.TestCase):
    def setUp(self):
        self.web = feature(self, '_control_web')
        self.broker = importlib.import_module('_control_web_broker')
        overview, self.view, self.source = make_overview(
            [task(questions=[question()])])
        self.safe = overview.snapshot()
        self.now = 1800000000
        self.config = {'origin': ORIGIN, 'password_hash': self.web.hash_password(PASSWORD),
                       'totp_secret': SECRET, 'session_ttl': 60, 'secure_cookie': True}

    def app(self, backend, *, owner_only=True):
        try:
            app = self.web.create_app(self.config, backend, clock=lambda: self.now,
                                      owner_only=owner_only)
        except TypeError as exc:
            # Keep an absent planned keyword as an endpoint/status assertion below,
            # rather than turning this RED into an import/setup ERROR.
            if "unexpected keyword argument 'owner_only'" not in str(exc):
                raise
            app = self.web.create_app(self.config, backend, clock=lambda: self.now)
        client = TestClient(app, base_url=ORIGIN)
        login = client.post('/api/login', json={
            'password': PASSWORD, 'totp': self.web.totp_code(SECRET, self.now)},
            headers={'Origin': ORIGIN})
        self.assertEqual(login.status_code, 200, login.text)
        return client

    @staticmethod
    def assert_no_store(case, response):
        case.assertIn('no-store', response.headers.get('cache-control', '').lower())

    def test_authenticated_owner_get_returns_projection_and_allows_absent_origin(self):
        identity = task()
        key_bytes = json.dumps({'kind': 'attention_task', 'registry_id': identity['registry_id'],
                                'agent': identity['agent'], 'incarnation': identity['incarnation']},
                               sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                               allow_nan=False).encode('utf-8')
        task_key = hashlib.sha256(key_bytes).hexdigest()
        backend = BackendStub(self.safe, tasks=[{'agent': identity['agent'], 'task_key': task_key}])
        client = self.app(backend)
        response = client.get('/api/attention', headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), self.safe)
        self.assert_no_store(self, response)
        task_read = client.get('/api/tasks', headers={'Origin': ORIGIN})
        self.assertEqual(task_read.status_code, 200, task_read.text)
        self.assertEqual(task_read.json()['tasks'][0]['task_key'], task_key)
        self.assertEqual(backend.snapshot_calls, 1)
        # An independent exact task-key read must not mutate retained attention.
        # Origin is optional for this read-only owner GET, but exact when supplied.
        without_origin = client.get('/api/attention')
        self.assertEqual(without_origin.status_code, 200, without_origin.text)
        self.assert_no_store(self, without_origin)
        self.assertEqual(without_origin.json(), response.json())
        self.assertEqual(backend.calls, 2)
        self.assertEqual(backend.snapshot_calls, 1)

    def test_authentication_missing_capability_is_503_and_never_falls_back_to_tasks(self):
        backend = BackendStub(self.safe)
        client = self.app(backend)
        unauthenticated = TestClient(client.app, base_url=ORIGIN)
        response = unauthenticated.get('/api/attention')
        self.assertEqual(response.status_code, 401, response.text)
        self.assert_no_store(self, response)
        class TasksOnlyBackend:
            def __init__(self):
                self.snapshot_calls = 0
            def snapshot(self):
                self.snapshot_calls += 1
                return {'tasks': []}
        missing = TasksOnlyBackend()
        client = self.app(missing)
        response = client.get('/api/attention', headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json(), {'error': 'unavailable'})
        self.assert_no_store(self, response)
        self.assertEqual(missing.snapshot_calls, 0)

    def test_owner_only_false_disables_attention_before_backend_call(self):
        backend = BackendStub(self.safe)
        client = self.app(backend, owner_only=False)
        response = client.get('/api/attention', headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json(), {'error': 'forbidden'})
        self.assert_no_store(self, response)
        self.assertEqual(backend.calls, 0)
        self.assertEqual(backend.snapshot_calls, 0)

    def test_get_rejects_any_query_duplicate_query_and_body(self):
        backend = BackendStub(self.safe)
        client = self.app(backend)
        for request in (
            lambda: client.get('/api/attention?project=demo', headers={'Origin': ORIGIN}),
            lambda: client.get('/api/attention?x=1&x=1', headers={'Origin': ORIGIN}),
            lambda: client.request('GET', '/api/attention', content=b'{"project":"demo"}',
                                   headers={'Origin': ORIGIN, 'Content-Type': 'application/json'}),
        ):
            with self.subTest(request=request):
                response = request()
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json(), {'error': 'invalid_request'})
                self.assert_no_store(self, response)
        with self.subTest(request='foreign Origin'):
            response = client.get('/api/attention', headers={'Origin': 'https://evil.invalid'})
            self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual(response.json(), {'error': 'forbidden'})
            self.assert_no_store(self, response)
        self.assertEqual(backend.calls, 0)

    def test_malformed_projection_is_safe_503_and_never_uses_tasks_fallback(self):
        for bad in ({'synthetic_private_field': 'must-not-leak'},
                    {'error': 'stale', 'private': 'synthetic-private-detail'}):
            with self.subTest(variant='malformed' if 'error' not in bad else 'internal stale'):
                backend = BackendStub(bad)
                client = self.app(backend)
                response = client.get('/api/attention', headers={'Origin': ORIGIN})
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json(), {'error': 'unavailable'})
                self.assert_no_store(self, response)
                self.assertNotIn('synthetic_private_field', response.text)
                self.assertNotIn('must-not-leak', response.text)
                self.assertNotIn('synthetic-private-detail', response.text)
                self.assertEqual(backend.calls, 1)
                self.assertEqual(backend.snapshot_calls, 0)

    def server(self, owner, uid=None):
        tmp = tempfile.TemporaryDirectory(prefix='attention-wire-red-', dir='/var/tmp')
        self.addCleanup(tmp.cleanup)
        os.chmod(tmp.name, 0o700)
        path = str(Path(tmp.name) / 'owner.sock')
        stop = threading.Event()
        errors = []
        def serve():
            try:
                self.broker.serve_broker(path, owner, os.getuid() if uid is None else uid,
                                         stop_event=stop)
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=serve, daemon=True, name='synthetic-attention-broker')
        worker.start()
        def shutdown():
            stop.set()
            worker.join(2)
            self.assertFalse(worker.is_alive(), 'synthetic broker did not stop')
        self.addCleanup(shutdown)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not errors:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(.1)
                    probe.connect(path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(.01)
        self.assertEqual(errors, [])
        self.assertTrue(Path(path).exists())
        return path, errors

    @staticmethod
    def raw_request(path, raw):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(path)
            client.sendall(raw + b'\n')
            data = b''
            while b'\n' not in data:
                block = client.recv(131073)
                if not block:
                    break
                data += block
            return json.loads(data)

    def test_broker_exact_fixed_operation_rejects_extras_and_duplicate_keys(self):
        class Owner:
            def __init__(self, value):
                self.value = value
                self.attention_calls = 0
                self.snapshot_calls = 0
            def attention_snapshot(self):
                self.attention_calls += 1
                return self.value
            def snapshot(self):
                self.snapshot_calls += 1
                return {'tasks': []}
        owner = Owner(self.safe)
        path, _ = self.server(owner)
        requests = (
            (b'{"op":"attention_snapshot"}', self.safe, 'exact operation'),
            (b'{"op":"attention_snapshot","project":"demo"}',
             {'error': 'invalid_request'}, 'extra selector refused'),
            (b'{"op":"attention_snapshot","op":"snapshot"}',
             {'error': 'invalid_request'}, 'duplicate op refused'),
        )
        for raw, expected, label in requests:
            with self.subTest(label=label):
                self.assertEqual(self.raw_request(path, raw), expected)
        self.assertEqual(owner.attention_calls, 1)
        self.assertEqual(owner.snapshot_calls, 0)

    def test_broker_peer_uid_gate_applies_before_attention_dispatch(self):
        class Owner:
            def __init__(self):
                self.calls = 0
            def attention_snapshot(self):
                self.calls += 1
                return {'error': 'unavailable'}
        owner = Owner()
        path, _ = self.server(owner, uid=os.getuid() + 1)
        result = self.raw_request(path, b'{"op":"attention_snapshot"}')
        self.assertIn(result.get('error'), ('forbidden', 'unavailable'))
        self.assertEqual(owner.calls, 0)

    def test_socket_backend_forwards_only_fixed_op_and_validates_safe_result(self):
        class Owner:
            def __init__(self, value):
                self.value = value
                self.calls = []
            def attention_snapshot(self):
                self.calls.append('attention_snapshot')
                return self.value
        owner = Owner(self.safe)
        path, _ = self.server(owner)
        backend = self.broker.SocketBackend(path)
        method = getattr(backend, 'attention_snapshot', None)
        self.assertTrue(callable(method), 'SocketBackend must expose fixed attention_snapshot()')
        if not callable(method):
            return
        self.assertEqual(method(), self.safe)
        self.assertEqual(owner.calls, ['attention_snapshot'])

        bad_owner = Owner({'unexpected': 'synthetic-secret'})
        bad_path, _ = self.server(bad_owner)
        bad_method = getattr(self.broker.SocketBackend(bad_path), 'attention_snapshot', None)
        self.assertTrue(callable(bad_method), 'SocketBackend attention_snapshot seam missing')
        if callable(bad_method):
            result = bad_method()
            self.assertEqual(result, {'error': 'unavailable'})
            self.assertNotIn('synthetic-secret', json.dumps(result))

    def registry_backend(self, overview, *, owner_only=True):
        try:
            return self.broker.RegistryBackend(
                '/var/tmp/synthetic-attention-registry', '/var/tmp/synthetic-control-bin',
                runner=lambda *args, **kwargs: None,
                attention=overview, owner_only=owner_only)
        except Exception as exc:
            self.fail('RegistryBackend trusted attention constructor contract missing/invalid: ' + str(exc))

    def attention_call(self, backend):
        method = getattr(backend, 'attention_snapshot', None)
        self.assertTrue(callable(method), 'RegistryBackend must expose attention_snapshot()')
        if not callable(method):
            return None
        try:
            return method()
        except Exception as exc:
            self.fail('attention_snapshot must return a safe DTO instead of raising: ' + type(exc).__name__)
            return None

    def test_registry_backend_absent_attention_is_unavailable_without_task_scan(self):
        backend = self.registry_backend(None)
        scans = []
        backend.snapshot = lambda: scans.append('snapshot') or {'tasks': []}
        result = self.attention_call(backend)
        self.assertEqual(result, {'error': 'unavailable'})
        self.assertEqual(scans, [])

    def test_registry_backend_owner_only_false_refuses_before_projection(self):
        class Overview:
            def __init__(self):
                self.calls = 0
            def snapshot(self):
                self.calls += 1
                return {'error': 'must-not-run'}
        overview = Overview()
        backend = self.registry_backend(overview, owner_only=False)
        result = self.attention_call(backend)
        self.assertEqual(result, {'error': 'forbidden'})
        self.assertEqual(overview.calls, 0)

    def test_registry_backend_whole_call_lock_is_nonblocking_and_never_resamples(self):
        overview, _, source = make_overview([task(questions=[question()])])
        entered = threading.Event()
        release = threading.Event()
        class Gate:
            def __init__(self):
                self.calls = 0
            def snapshot(self):
                self.calls += 1
                entered.set()
                if not release.wait(2):
                    raise TimeoutError('synthetic gate expired')
                return overview.snapshot()
        gate = Gate()
        backend = self.registry_backend(gate)
        first_result = []
        first = threading.Thread(target=lambda: first_result.append(self.attention_call(backend)),
                                 daemon=True)
        first.start()
        self.assertTrue(entered.wait(1), 'first projection did not enter trusted composer')
        before = time.monotonic()
        second_result = self.attention_call(backend)
        elapsed = time.monotonic() - before
        self.assertLess(elapsed, .5, 'contending read must return immediately')
        self.assertEqual(second_result, {'error': 'unavailable'})
        self.assertEqual(gate.calls, 1, 'contended call must not create a fresh composer/deadline')
        self.assertEqual(source.calls, 0, 'contended call must not reach source')
        release.set()
        first.join(2)
        self.assertFalse(first.is_alive())
        self.assertEqual(len(first_result), 1)
        self.assertEqual(first_result[0], self.safe)
        self.assertEqual(source.calls, 1, 'only admitted first call sampled source')

    def test_registry_backend_internal_stale_normalizes_and_exception_releases_lock(self):
        overview, _, _ = make_overview([task(questions=[question()])])
        class Sequence:
            def __init__(self):
                self.calls = 0
            def snapshot(self):
                self.calls += 1
                if self.calls == 1:
                    return {'error': 'stale', 'private': 'synthetic-secret'}
                if self.calls == 2:
                    raise RuntimeError('synthetic-private-diagnostic')
                return overview.snapshot()
        sequence = Sequence()
        backend = self.registry_backend(sequence)
        first = self.attention_call(backend)
        second = self.attention_call(backend)
        third = self.attention_call(backend)
        self.assertEqual(first, {'error': 'unavailable'})
        self.assertEqual(second, {'error': 'unavailable'})
        self.assertNotIn('synthetic-private-diagnostic', json.dumps(second))
        self.assertEqual(third, self.safe)
        self.assertEqual(sequence.calls, 3)


if __name__ == '__main__':
    unittest.main()
