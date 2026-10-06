"""Synthetic transport contract tests for INV-WSESS-25 selection forwarding."""
import importlib
import inspect
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
sys.path.insert(0, str(ROOT / "bin"))
SID = "11111111-1111-4111-8111-111111111111"
MID = "22222222-2222-4222-8222-222222222222"
TURN = "33333333-3333-4333-8333-333333333333"
ORIGIN = "https://control.example.test"
PASSWORD = "synthetic-web-test-password"
SECRET = "JBSWY3DPEHPK3PXP"


def feature(case, name):
    case.assertTrue((ROOT / "bin" / (name + ".py")).is_file(),
                    "Missing session web feature " + name)
    return importlib.import_module(name)

SELECTION = {"catalog_id": "a" * 64, "model_id": "ui-model", "effort": "high"}
ACCEPTED = {"status": "accepted", "message_id": MID, "turn_id": TURN}


class HTTPBackend:
    def __init__(self):
        self.calls = []

    def session_send(self, project, sid, message_id, text, selection=None):
        self.calls.append((project, sid, message_id, text) if selection is None else
                          (project, sid, message_id, text, selection))
        return dict(ACCEPTED)


class LegacyHTTPBackend:
    def __init__(self):
        self.calls = []

    def session_send(self, project, sid, message_id, text):
        self.calls.append((project, sid, message_id, text))
        return dict(ACCEPTED)


class SessionSelectionHTTP(unittest.TestCase):
    def setUp(self):
        self.web = feature(self, "_control_web")
        self.backend = HTTPBackend()
        self.now = 1800000000
        config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
                      totp_secret=SECRET, session_ttl=60, secure_cookie=True)
        self.client = TestClient(self.web.create_app(config, self.backend, clock=lambda: self.now),
                                 base_url=ORIGIN)
        self.body = {"project": "demo", "sid": SID, "message_id": MID, "text": "Hello"}
        self.csrf = None

    def login(self):
        response = self.client.post("/api/login", json={"username": "owner", "password": PASSWORD,
            "totp": self.web.totp_code(SECRET, self.now)}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json()["csrf"]

    def post(self, body=None, *, headers=None, content=None):
        request_headers = {"Origin": ORIGIN, "X-CSRF-Token": self.csrf}
        if headers:
            request_headers.update(headers)
        if content is not None:
            request_headers["Content-Type"] = "application/json"
            return self.client.post("/api/session-send", content=content, headers=request_headers)
        return self.client.post("/api/session-send", json=self.body if body is None else body,
                                headers=request_headers)

    def test_inherit_omission_keeps_legacy_four_argument_backend_call(self):
        self.login()
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), ACCEPTED)
        self.assertEqual(self.backend.calls, [("demo", SID, MID, "Hello")])

    def test_explicit_selection_is_forwarded_as_the_exact_optional_value(self):
        self.login()
        signature = inspect.signature(self.backend.session_send)
        self.assertEqual(signature.parameters["selection"].default, None)
        response = self.post({**self.body, "selection": dict(SELECTION)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), ACCEPTED)
        self.assertEqual(self.backend.calls, [("demo", SID, MID, "Hello", SELECTION)])

    def test_bad_selection_shapes_and_duplicate_keys_fail_before_backend(self):
        self.login()
        invalid = [None, [], "model", {}, {"model_id": "ui-model", "effort": "high"},
                   {**SELECTION, "extra": "value"}, {**SELECTION, "effort": 7},
                   {**SELECTION, "model_id": "\u0001"},
                   {**SELECTION, "catalog_id": "A" * 64}]
        for selection in invalid:
            with self.subTest(selection_type=type(selection).__name__):
                response = self.post({**self.body, "selection": selection})
                self.assertEqual(response.status_code, 422, response.text)
        duplicate_root = (json.dumps(self.body)[:-1] + ', "selection": {"catalog_id":"' + "a" * 64 +
                          '","model_id":"ui-model","effort":"high"},"selection":null}')
        duplicate_nested = (json.dumps(self.body)[:-1] + ', "selection": {"catalog_id":"' + "a" * 64 +
                            '","model_id":"ui-model","effort":"high","effort":"low"}}')
        for raw in (duplicate_root, duplicate_nested):
            self.assertEqual(self.post(content=raw).status_code, 422)
        self.assertEqual(self.backend.calls, [])

    def test_auth_origin_and_csrf_checks_still_precede_selection_backend_effects(self):
        body = {**self.body, "selection": dict(SELECTION)}
        unauthenticated = self.client.post("/api/session-send", json=body,
                                           headers={"Origin": ORIGIN})
        self.assertIn(unauthenticated.status_code, (401, 403))
        self.assertEqual(self.backend.calls, [])
        self.login()
        for headers in ({"Origin": ORIGIN}, {"Origin": "https://evil.example.test",
                                                "X-CSRF-Token": self.csrf}):
            response = self.client.post("/api/session-send", json=body, headers=headers)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.backend.calls, [])

    def test_explicit_selection_is_not_downgraded_for_legacy_backend(self):
        legacy = LegacyHTTPBackend()
        config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
                      totp_secret=SECRET, session_ttl=60, secure_cookie=True)
        client = TestClient(self.web.create_app(config, legacy, clock=lambda: self.now),
                            base_url=ORIGIN, raise_server_exceptions=False)
        login = client.post("/api/login", json={"username": "owner", "password": PASSWORD,
            "totp": self.web.totp_code(SECRET, self.now)}, headers={"Origin": ORIGIN})
        self.assertEqual(login.status_code, 200)
        response = client.post("/api/session-send", json={**self.body, "selection": dict(SELECTION)},
            headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf"]})
        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(legacy.calls, [])


class Chat:
    def __init__(self):
        self.calls = []

    def send(self, project, sid, message_id, text, selection=None):
        self.calls.append((project, sid, message_id, text) if selection is None else
                          (project, sid, message_id, text, selection))
        return dict(ACCEPTED)


class Backend:
    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {"tasks": []}

    def session_send(self, project, sid, message_id, text, selection=None):
        self.calls.append((project, sid, message_id, text) if selection is None else
                          (project, sid, message_id, text, selection))
        return dict(ACCEPTED)


class SessionSelectionBroker(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("_control_web_broker")
        self.tmp = tempfile.TemporaryDirectory(prefix="web-session-selection-broker-", dir="/var/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.socket_path = str(self.base / "broker.sock")
        self.backend = Backend()
        self.stop = threading.Event()
        self.errors = []
        self.worker = None

    def start(self):
        def serve():
            try:
                self.module.serve_broker(self.socket_path, self.backend, os.getuid(), stop_event=self.stop)
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
        self.assertTrue(ready)

    def shutdown(self):
        self.stop.set()
        if self.worker:
            self.worker.join(2)

    def wire(self, payload):
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            sock.connect(self.socket_path)
            sock.sendall(encoded + b"\n")
            data = b""
            while b"\n" not in data:
                data += sock.recv(131073)
                self.assertLessEqual(len(data), 128 * 1024)
        return json.loads(data.split(b"\n", 1)[0])

    def test_registry_preserves_omission_and_forwards_explicit_selection(self):
        registry = self.base / "registry"
        registry.mkdir(mode=0o700)
        chat = Chat()
        backend = self.module.RegistryBackend(str(registry), str(ROOT / "bin"), sessions=chat)
        signature = inspect.signature(backend.session_send)
        self.assertIn("selection", signature.parameters,
                      "RegistryBackend.session_send must accept optional selection")
        self.assertEqual(signature.parameters["selection"].default, None)
        self.assertEqual(backend.session_send("demo", SID, MID, "Hello"), ACCEPTED)
        self.assertEqual(backend.session_send("demo", SID, MID, "Hello", dict(SELECTION)), ACCEPTED)
        self.assertEqual(chat.calls, [("demo", SID, MID, "Hello"),
                                      ("demo", SID, MID, "Hello", SELECTION)])

    def test_owner_allowlist_roundtrips_old_inherit_and_exact_explicit_selection(self):
        self.start()
        inherit = {"op": "session_send", "project": "demo", "sid": SID,
                   "message_id": MID, "text": "Hello"}
        explicit = {**inherit, "selection": dict(SELECTION)}
        self.assertEqual(self.wire(inherit), ACCEPTED)
        self.assertEqual(self.wire(explicit), ACCEPTED)
        self.assertEqual(self.backend.calls, [("demo", SID, MID, "Hello"),
                                              ("demo", SID, MID, "Hello", SELECTION)])

    def test_owner_rejects_malformed_selection_and_duplicate_nested_keys_before_backend(self):
        self.start()
        base = {"op": "session_send", "project": "demo", "sid": SID,
                "message_id": MID, "text": "Hello"}
        invalid = [None, [], {}, {"model_id": "ui-model", "effort": "high"},
                   {**SELECTION, "extra": "private"}, {**SELECTION, "effort": True},
                   {**SELECTION, "model_id": ""}]
        for selection in invalid:
            with self.subTest(selection_type=type(selection).__name__):
                self.assertEqual(set(self.wire({**base, "selection": selection})), {"error"})
        raw = (b'{"op":"session_send","project":"demo","sid":"' + SID.encode() +
               b'","message_id":"' + MID.encode() + b'","text":"Hello","selection":'
               b'{"catalog_id":"' + b"a" * 64 +
               b'","model_id":"ui-model","effort":"high","effort":"low"}}')
        self.assertEqual(set(self.wire(raw)), {"error"})
        self.assertEqual(self.backend.calls, [])

    def test_socket_backend_preserves_omission_and_transmits_selection_as_one_fixed_field(self):
        self.start()
        client = self.module.SocketBackend(self.socket_path)
        signature = inspect.signature(client.session_send)
        self.assertIn("selection", signature.parameters)
        self.assertEqual(signature.parameters["selection"].default, None)
        self.assertEqual(client.session_send("demo", SID, MID, "Hello"), ACCEPTED)
        self.assertEqual(client.session_send("demo", SID, MID, "Hello", dict(SELECTION)), ACCEPTED)
        self.assertEqual(self.backend.calls, [("demo", SID, MID, "Hello"),
                                              ("demo", SID, MID, "Hello", SELECTION)])


if __name__ == "__main__":
    unittest.main()
