"""Public history-unavailable contract preserves valid existing send receipts."""
import importlib
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

MID = '22222222-2222-4222-8222-222222222222'
TURN = '33333333-3333-4333-8333-333333333333'


class Owner:
    def __init__(self):
        self.calls = []
        self.history_result = None

    def session_history(self, project, sid, cursor):
        self.calls.append((project, sid, cursor))
        return self.history_result


class UnavailableHistoryReceipts(unittest.TestCase):
    def setUp(self):
        self.web = feature(self, '_control_web')
        self.broker = importlib.import_module('_control_web_broker')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-history-receipt-wire-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.socket_path = str(self.base / 'owner.sock')
        self.owner = Owner()
        self.stop = threading.Event()
        self.errors = []

        def serve():
            try:
                self.broker.serve_broker(self.socket_path, self.owner, os.getuid(), stop_event=self.stop)
            except Exception as error:
                self.errors.append(error)

        self.worker = threading.Thread(target=serve, daemon=True, name='synthetic-history-broker')
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
        self.assertTrue(Path(self.socket_path).exists(), 'Synthetic owner broker became ready')
        backend = self.broker.SocketBackend(self.socket_path)
        now = 1800000000
        config = {'origin': ORIGIN, 'password_hash': self.web.hash_password(PASSWORD),
                  'totp_secret': SECRET, 'session_ttl': 60, 'secure_cookie': True}
        self.client = TestClient(self.web.create_app(config, backend, clock=lambda: now), base_url=ORIGIN)
        login = self.client.post('/api/login', json={'password': PASSWORD,
            'totp': self.web.totp_code(SECRET, now)}, headers={'Origin': ORIGIN})
        self.assertEqual(login.status_code, 200, login.text)

    def shutdown(self):
        self.stop.set()
        if getattr(self, 'worker', None):
            self.worker.join(2)

    def get_history(self):
        return self.client.get(f'/api/session-history?project=demo&sid={SID}',
                               headers={'Origin': ORIGIN})

    def test_unavailable_history_preserves_valid_rejected_receipt_across_broker_and_http(self):
        valid = {'history_state': 'unavailable', 'reason': 'unavailable',
                 'recent_sends': [{'status': 'rejected', 'message_id': MID, 'turn_id': None}]}
        malformed = {'history_state': 'unavailable', 'reason': 'unavailable',
                     'recent_sends': [{'status': 'rejected', 'message_id': MID, 'turn_id': TURN}]}
        for label, dto, expected_status, expected_body in (
                ('valid rejected receipt', valid, 200, valid),
                ('rejected receipt cannot carry a turn id', malformed, 503, {'error': 'unavailable'})):
            with self.subTest(label=label):
                self.owner.history_result = dto
                response = self.get_history()
                self.assertEqual(response.status_code, expected_status, response.text)
                self.assertEqual(response.json(), expected_body)
        self.assertEqual(self.owner.calls, [('demo', SID, None), ('demo', SID, None)])
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
