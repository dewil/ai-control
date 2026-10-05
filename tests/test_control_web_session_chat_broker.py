"""Blind fixed-operation broker tests: INV-WSESS-01/02 and bounded admission."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
SID = '11111111-1111-4111-8111-111111111111'
MID = '22222222-2222-4222-8222-222222222222'
TURN = '33333333-3333-4333-8333-333333333333'
ACCEPTED = {'status': 'accepted', 'message_id': MID, 'turn_id': TURN}
HISTORY = {'turns': [], 'next_cursor': None, 'truncated': False, 'recent_sends': []}


class Backend:
    def __init__(self):
        self.calls = []
        self.gate = threading.Event()
        self.gate.set()
        self.condition = threading.Condition()
        self.active_history = 0
    def record(self, *args):
        with self.condition:
            self.calls.append(args)
            self.condition.notify_all()
    def snapshot(self):
        self.record('snapshot')
        return {'tasks': []}
    def answer(self, agent, qid, decision, text):
        self.record('answer', agent, qid, decision, text)
        return {'status': 'applied'}
    def verdict(self, agent, generation, decision, comment):
        self.record('verdict', agent, generation, decision, comment)
        return {'status': 'applied'}
    def session_projects(self):
        self.record('projects')
        return {'projects': [{'name': 'demo'}]}
    def session_list(self, project, page):
        self.record('list', project, page)
        return {'rows': [], 'has_more': False}
    def session_history(self, project, sid, cursor):
        with self.condition:
            self.calls.append(('history', project, sid, cursor))
            self.active_history += 1
            self.condition.notify_all()
        try:
            if not self.gate.wait(5):
                return {'error': 'unavailable'}
            return HISTORY
        finally:
            with self.condition:
                self.active_history -= 1
                self.condition.notify_all()
    def session_send(self, project, sid, message_id, text):
        self.record('send', project, sid, message_id, text)
        return ACCEPTED
    def session_send_status(self, project, sid, message_id):
        self.record('status', project, sid, message_id)
        return ACCEPTED
    def wait_active(self, count, timeout=2):
        with self.condition:
            return self.condition.wait_for(lambda: self.active_history == count, timeout)


class Chat:
    def __init__(self):
        self.calls = []
    def projects(self):
        self.calls.append(('projects',))
        return {'projects': [{'name': 'demo'}]}
    def list_sessions(self, project, page):
        self.calls.append(('list', project, page))
        return {'rows': [], 'has_more': False}
    def history(self, project, sid, cursor):
        self.calls.append(('history', project, sid, cursor))
        return HISTORY
    def send(self, project, sid, message_id, text):
        self.calls.append(('send', project, sid, message_id, text))
        return ACCEPTED
    def send_status(self, project, sid, message_id):
        self.calls.append(('status', project, sid, message_id))
        return ACCEPTED


class BrokerContract(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('_control_web_broker')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-session-broker-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.socket_path = str(self.base / 'broker.sock')
        self.backend = Backend()
        self.stop = threading.Event()
        self.errors = []
        self.worker = None
    def start(self, uid=None):
        def serve():
            try:
                self.module.serve_broker(self.socket_path, self.backend,
                    os.getuid() if uid is None else uid, stop_event=self.stop)
            except Exception as error:
                self.errors.append(error)
        self.worker = threading.Thread(target=serve, daemon=True)
        self.worker.start()
        self.addCleanup(self.shutdown)
        deadline = time.monotonic() + 2
        ready = False
        while time.monotonic() < deadline:
            if self.errors:
                break
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(min(0.1, max(0.001, deadline - time.monotonic())))
                    probe.connect(self.socket_path)
                ready = True
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.01)
        self.assertEqual(self.errors, [])
        self.assertTrue(ready, 'Public broker socket did not become connectable')
        self.assertTrue(Path(self.socket_path).exists(), 'Public broker must bind its private socket')
    def shutdown(self):
        self.backend.gate.set()
        self.stop.set()
        if self.worker:
            self.worker.join(2)
    def wire(self, payload, timeout=2):
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(timeout)
            sock.connect(self.socket_path)
            sock.sendall(encoded + b'\n')
            data = b''
            while b'\n' not in data:
                chunk = sock.recv(131073)
                if not chunk:
                    break
                data += chunk
                self.assertLessEqual(len(data), 128*1024)
        return json.loads(data.split(b'\n', 1)[0])
    def operations(self):
        return [({'op': 'session_projects'}, {'projects': [{'name': 'demo'}]}),
                ({'op': 'session_list', 'project': 'demo', 'page': 0}, {'rows': [], 'has_more': False}),
                ({'op': 'session_history', 'project': 'demo', 'sid': SID, 'cursor': None}, HISTORY),
                ({'op': 'session_send', 'project': 'demo', 'sid': SID, 'message_id': MID, 'text': 'Hello'}, ACCEPTED),
                ({'op': 'session_send_status', 'project': 'demo', 'sid': SID, 'message_id': MID}, ACCEPTED)]

    def test_INV_WSESS_01_registry_forwards_only_public_chat_arguments(self):
        registry = self.base / 'registry'
        registry.mkdir(mode=0o700)
        chat = Chat()
        backend = self.module.RegistryBackend(str(registry), str(ROOT / 'bin'), sessions=chat)
        self.assertEqual(backend.session_projects(), {'projects': [{'name': 'demo'}]})
        self.assertEqual(backend.session_list('demo', 0), {'rows': [], 'has_more': False})
        self.assertEqual(backend.session_history('demo', SID, None), HISTORY)
        self.assertEqual(backend.session_send('demo', SID, MID, 'Hello'), ACCEPTED)
        self.assertEqual(backend.session_send_status('demo', SID, MID), ACCEPTED)
        self.assertEqual(chat.calls, [('projects',), ('list', 'demo', 0), ('history', 'demo', SID, None),
                                      ('send', 'demo', SID, MID, 'Hello'), ('status', 'demo', SID, MID)])

    def test_INV_WSESS_01_registry_without_chat_preserves_tasks_and_reports_unavailable(self):
        registry = self.base / 'registry'
        registry.mkdir(mode=0o700)
        backend = self.module.RegistryBackend(str(registry), str(ROOT / 'bin'))
        self.assertEqual(backend.snapshot(), {'tasks': []})
        for operation in (lambda: backend.session_projects(), lambda: backend.session_list('demo', 0),
                          lambda: backend.session_history('demo', SID, None),
                          lambda: backend.session_send('demo', SID, MID, 'Hello'),
                          lambda: backend.session_send_status('demo', SID, MID)):
            self.assertEqual(operation(), {'error': 'unavailable'})

    def test_INV_WSESS_01_socket_roundtrip_new_and_existing_operations(self):
        self.start()
        client = self.module.SocketBackend(self.socket_path)
        self.assertEqual(client.session_projects(), {'projects': [{'name': 'demo'}]})
        self.assertEqual(client.session_list('demo', 0), {'rows': [], 'has_more': False})
        self.assertEqual(client.session_history('demo', SID, None), HISTORY)
        self.assertEqual(client.session_send('demo', SID, MID, 'Hello'), ACCEPTED)
        self.assertEqual(client.session_send_status('demo', SID, MID), ACCEPTED)
        self.assertEqual(client.snapshot(), {'tasks': []})
        self.assertEqual(self.backend.calls, [('projects',), ('list', 'demo', 0), ('history', 'demo', SID, None),
                                              ('send', 'demo', SID, MID, 'Hello'), ('status', 'demo', SID, MID), ('snapshot',)])

    def test_INV_WSESS_01_owner_dispatcher_fixed_ops_roundtrip(self):
        self.start()
        for request, expected in self.operations():
            self.assertEqual(self.wire(request), expected)
        self.assertEqual(len(self.backend.calls), 5)

    def test_INV_WSESS_01_owner_rejects_extra_duplicate_missing_and_wrong_typed_fields(self):
        self.start()
        requests = []
        for request, _ in self.operations():
            requests.append({**request, 'path': '/private/owner'})
            requests.append({**request, 'rpc': 'turn/interrupt'})
            requests.append({**request, 'peer_uid': os.getuid()})
            for field in request:
                if field != 'op':
                    requests.append({key: value for key, value in request.items() if key != field})
            if 'project' in request:
                requests.extend([{**request, 'project': '/private'}, {**request, 'project': None}])
            if 'sid' in request:
                requests.extend([{**request, 'sid': SID[:8]}, {**request, 'sid': 7}])
        requests.extend([{'op': 'session_list', 'project': 'demo', 'page': True},
                         {'op': 'session_list', 'project': 'demo', 'page': -1},
                         {'op': 'session_history', 'project': 'demo', 'sid': SID, 'cursor': ''},
                         {'op': 'session_history', 'project': 'demo', 'sid': SID, 'cursor': True},
                         {'op': 'session_send', 'project': 'demo', 'sid': SID, 'message_id': MID, 'text': ' '},
                         {'op': 'session_send', 'project': 'demo', 'sid': SID, 'message_id': MID, 'text': 7},
                         {'op': 'session_send', 'project': 'demo', 'sid': SID, 'message_id': MID, 'text': 'x'*16001},
                         {'op': 'session_send_status', 'project': 'demo', 'sid': SID},
                         b'{"op":"session_projects","op":"snapshot"}'])
        for request in requests:
            with self.subTest(request_type=type(request).__name__):
                result = self.wire(request)
                self.assertEqual(set(result), {'error'})
        self.assertEqual(self.backend.calls, [])

    def test_INV_WSESS_01_socket_client_validation_never_contacts_owner(self):
        client = self.module.SocketBackend(self.socket_path)
        for invoke in (lambda: client.session_list('demo', True),
                       lambda: client.session_history('/private', SID, None),
                       lambda: client.session_send('demo', SID[:8], MID, 'Hello'),
                       lambda: client.session_send('demo', SID, MID, ''),
                       lambda: client.session_send_status('demo', SID, MID[:8])):
            self.assertEqual(invoke(), {'error': 'invalid_request'})
        self.assertFalse(Path(self.socket_path).exists())

    def test_INV_WSESS_01_wrong_peer_uid_never_calls_backend(self):
        self.start(uid=os.getuid()+1)
        result = self.wire({'op': 'session_projects'})
        self.assertEqual(set(result), {'error'})
        self.assertNotIn('/var/tmp', json.dumps(result))
        self.assertEqual(self.backend.calls, [])

    def test_INV_WSESS_01_large_wire_request_rejected_before_backend(self):
        self.start()
        oversized = json.dumps({'op': 'session_send', 'project': 'demo', 'sid': SID,
                               'message_id': MID, 'text': 'x'*140000}).encode()
        try:
            result = self.wire(oversized)
        except (ConnectionResetError, BrokenPipeError):
            result = {'error': 'closed'}
        self.assertEqual(set(result), {'error'})
        self.assertEqual(self.backend.calls, [])

    def test_INV_WSESS_01_oversized_backend_response_is_safe_unavailable(self):
        self.backend.session_history = lambda project, sid, cursor: {'turns': ['x'*140000]}
        self.start()
        self.assertEqual(self.wire({'op': 'session_history', 'project': 'demo', 'sid': SID, 'cursor': None}),
                         {'error': 'unavailable'})

    def test_INV_WSESS_01_slow_history_does_not_block_task_snapshot(self):
        self.start()
        self.backend.gate.clear()
        results = []
        slow = threading.Thread(target=lambda: results.append(self.wire(
            {'op': 'session_history', 'project': 'demo', 'sid': SID, 'cursor': None}, timeout=5)), daemon=True)
        slow.start()
        try:
            self.assertTrue(self.backend.wait_active(1))
            self.assertEqual(self.wire({'op': 'snapshot'}, timeout=1), {'tasks': []})
            self.assertFalse(self.backend.gate.is_set())
        finally:
            self.backend.gate.set()
            slow.join(2)
        self.assertEqual(results, [HISTORY])

    def test_INV_WSESS_01_max_four_active_requests_rejects_overload_without_backend(self):
        self.start()
        self.backend.gate.clear()
        results = []
        failures = []
        def request():
            try:
                results.append(self.wire({'op': 'session_history', 'project': 'demo', 'sid': SID, 'cursor': None}, timeout=5))
            except Exception as error:
                failures.append(error)
        workers = [threading.Thread(target=request, daemon=True) for _ in range(4)]
        for worker in workers:
            worker.start()
        try:
            self.assertTrue(self.backend.wait_active(4), 'Broker must permit independent session operations concurrently')
            self.assertEqual(self.wire({'op': 'session_projects'}, timeout=1), {'error': 'unavailable'})
            self.assertEqual(len(self.backend.calls), 4, 'Overload cannot invoke backend')
        finally:
            self.backend.gate.set()
            for worker in workers:
                worker.join(2)
        self.assertEqual(failures, [])
        self.assertEqual(results, [HISTORY]*4)


if __name__ == '__main__':
    unittest.main()
