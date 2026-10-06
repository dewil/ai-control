"""Source-blind synthetic HTTP/broker acceptance for INV-WSESS-24."""
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
sys.path.insert(0, str(ROOT / "bin"))
from test_control_web_session_chat_contract import ORIGIN, PASSWORD, SECRET, SID, feature

EVIL_ORIGIN = "https://evil.example.test"
DTO = {
    "schema": 1,
    "vendor": "codex",
    "context_kind": "legacy_unbound",
    "selection_support": "unavailable",
    "reason": "unsupported_capability",
    "catalog_id": None,
    "expires_in_ms": 0,
    "rows": [],
}


class HTTPBackend:
    def __init__(self):
        self.calls = []
        self.outcome = dict(DTO)
    def session_models(self, project, sid):
        self.calls.append(("session_models", project, sid))
        return self.outcome
    def session_history(self, project, sid, cursor):
        self.calls.append(("session_history", project, sid, cursor))
        return {"turns": []}
    def session_list(self, project, page):
        self.calls.append(("session_list", project, page))
        return {"rows": []}
    def session_send(self, project, sid, message_id, text):
        self.calls.append(("session_send", project, sid, message_id, text))
        return {"error": "unexpected"}


class SessionModelsHTTP(unittest.TestCase):
    def setUp(self):
        self.web = feature(self, "_control_web")
        self.backend = HTTPBackend()
        self.now = 1800000000
        config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
                      totp_secret=SECRET, session_ttl=60, secure_cookie=True)
        self.client = TestClient(self.web.create_app(config, self.backend, clock=lambda: self.now), base_url=ORIGIN)
        self.path = f"/api/session-models?project=demo&sid={SID}"
    def login(self):
        response = self.client.post("/api/login", json={"username": "owner", "password": PASSWORD,
            "totp": self.web.totp_code(SECRET, self.now)}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
    def test_authentication_precedes_session_model_discovery(self):
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.backend.calls, [])
    def test_origin_if_present_rejects_foreign_origin_but_absent_origin_is_allowed(self):
        self.login()
        denied = self.client.get(self.path, headers={"Origin": EVIL_ORIGIN})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.backend.calls, [])
        allowed = self.client.get(self.path)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json(), DTO)
        self.assertEqual(self.backend.calls, [("session_models", "demo", SID)])
    def test_query_is_exact_and_repeated_or_invalid_values_never_reach_backend(self):
        self.login()
        paths = [
            f"/api/session-models?project=demo&sid={SID}&extra=x",
            f"/api/session-models?project=demo&project=other&sid={SID}",
            f"/api/session-models?project=demo&sid={SID}&sid={SID}",
            f"/api/session-models?project=../private&sid={SID}",
            f"/api/session-models?project=demo&sid={SID[:8]}",
            "/api/session-models?project=demo&sid=ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers={"Origin": ORIGIN}).status_code, 422)
        self.assertEqual(self.backend.calls, [])
    def test_unavailable_catalog_dto_is_preserved_exactly_and_never_exports_wire_fields(self):
        self.login()
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("cache-control", ""))
        self.assertEqual(response.json(), DTO)
        self.assertEqual(set(response.json()), {"schema", "vendor", "context_kind", "selection_support", "reason", "catalog_id", "expires_in_ms", "rows"})
        self.assertNotIn("wire_model", response.text)
        self.assertEqual(self.backend.calls, [("session_models", "demo", SID)])
    def test_permission_failure_keeps_existing_error_envelope_and_no_catalog_dto(self):
        self.login()
        self.backend.outcome = {"error": "forbidden"}
        response = self.client.get(self.path, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "forbidden"})
        self.assertNotIn("selection_support", response.json())
        self.assertEqual(self.backend.calls, [("session_models", "demo", SID)])


class SessionModelsChat:
    def __init__(self):
        self.calls = []
        self.outcome = dict(DTO)
    def models(self, project, sid):
        self.calls.append(("models", project, sid))
        return self.outcome
    def history(self, project, sid, cursor=None):
        self.calls.append(("history", project, sid, cursor))
        return {"turns": []}


class OwnerBackend:
    def __init__(self):
        self.calls = []
        self.outcome = dict(DTO)
    def snapshot(self):
        return {"tasks": []}
    def session_history(self, project, sid, cursor):
        self.calls.append(("session_history", project, sid, cursor))
        return {"turns": []}
    def session_list(self, project, page):
        self.calls.append(("session_list", project, page))
        return {"rows": []}
    def session_send(self, project, sid, message_id, text):
        self.calls.append(("session_send", project, sid, message_id, text))
        return {"error": "unexpected"}
    def session_models(self, project, sid):
        self.calls.append(("session_models", project, sid))
        return self.outcome


class SessionModelsBroker(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("_control_web_broker")
        self.tmp = tempfile.TemporaryDirectory(prefix="web-session-models-broker-", dir="/var/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.socket_path = str(self.base / "broker.sock")
        self.backend = OwnerBackend()
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
        self.assertTrue(ready, "Synthetic broker socket did not become connectable")
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
                chunk = sock.recv(131073)
                if not chunk:
                    break
                data += chunk
                self.assertLessEqual(len(data), 128 * 1024)
        return json.loads(data.split(b"\n", 1)[0])
    def test_registry_backend_forwards_only_project_and_sid_to_session_chat(self):
        registry = self.base / "registry"
        registry.mkdir(mode=0o700)
        chat = SessionModelsChat()
        backend = self.module.RegistryBackend(str(registry), str(ROOT / "bin"), sessions=chat)
        method = getattr(backend, "session_models", None)
        self.assertTrue(callable(method), "RegistryBackend must expose session_models(project, sid)")
        self.assertEqual(method("demo", SID), DTO)
        self.assertEqual(chat.calls, [("models", "demo", SID)])
    def test_owner_allowlisted_session_models_operation_roundtrips_safe_unavailable_dto(self):
        self.start()
        request = {"op": "session_models", "project": "demo", "sid": SID}
        self.assertEqual(self.wire(request), DTO)
        self.assertEqual(self.backend.calls, [("session_models", "demo", SID)])
        self.assertNotIn("wire_model", json.dumps(self.wire(request)))
        self.assertEqual(self.backend.calls, [("session_models", "demo", SID), ("session_models", "demo", SID)])
    def test_owner_rejects_extra_missing_wrong_and_duplicate_fields_before_backend(self):
        self.start()
        requests = [
            {"op": "session_models", "project": "demo", "sid": SID, "wire_model": "private"},
            {"op": "session_models", "project": "demo"},
            {"op": "session_models", "project": "demo", "sid": SID[:8]},
            {"op": "session_models", "project": "../private", "sid": SID},
            {"op": "session_models", "project": "demo", "sid": 7},
            b'{"op":"session_models","project":"demo","sid":"11111111-1111-4111-8111-111111111111","sid":"44444444-4444-4444-8444-444444444444"}',
        ]
        for request in requests:
            with self.subTest(request_type=type(request).__name__):
                self.assertEqual(set(self.wire(request)), {"error"})
        self.assertEqual(self.backend.calls, [])
    def test_socket_backend_exposes_fixed_session_models_operation(self):
        self.start()
        client = self.module.SocketBackend(self.socket_path)
        method = getattr(client, "session_models", None)
        self.assertTrue(callable(method), "SocketBackend must expose session_models(project, sid)")
        self.assertEqual(method("demo", SID), DTO)
        self.assertEqual(self.backend.calls, [("session_models", "demo", SID)])


if __name__ == "__main__":
    unittest.main()
