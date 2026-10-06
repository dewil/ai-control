"""Source-blind HTTP/owner-broker contract tests for INV-WSESS-30."""
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

OPID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
EVIL_ORIGIN = "https://evil.example.test"
TITLE = "Renamed synthetic session"
ACCEPTED = {"operation_id": OPID, "status": "accepted", "title": TITLE}
UNKNOWN = {"operation_id": OPID, "status": "delivery_unknown"}


class HTTPBackend:
    def __init__(self):
        self.calls = []
        self.rename_result = dict(ACCEPTED)
        self.status_result = dict(UNKNOWN)

    def session_rename(self, project, sid, operation_id, title):
        self.calls.append(("session_rename", project, sid, operation_id, title))
        return self.rename_result

    def session_rename_status(self, project, sid, operation_id):
        self.calls.append(("session_rename_status", project, sid, operation_id))
        return self.status_result

    def session_send(self, project, sid, message_id, text):
        self.calls.append(("session_send", project, sid, message_id, text))
        return {"status": "accepted", "message_id": message_id}


class RenameHTTP(unittest.TestCase):
    def setUp(self):
        self.web = feature(self, "_control_web")
        self.backend = HTTPBackend()
        self.now = 1800000000
        config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
                      totp_secret=SECRET, session_ttl=60, secure_cookie=True)
        self.client = TestClient(self.web.create_app(config, self.backend, clock=lambda: self.now), base_url=ORIGIN)
        self.body = {"project": "demo", "sid": SID, "operation_id": OPID, "title": TITLE}
        self.status_path = f"/api/session-rename-status?project=demo&sid={SID}&operation_id={OPID}"
        self.csrf = None

    def login(self):
        response = self.client.post("/api/login", json={"username": "owner", "password": PASSWORD,
            "totp": self.web.totp_code(SECRET, self.now)}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json()["csrf"]

    def post(self, body=None, *, headers=None, content=None):
        request_headers = {"Origin": ORIGIN}
        if self.csrf is not None:
            request_headers["X-CSRF-Token"] = self.csrf
        if headers:
            request_headers.update(headers)
        if content is not None:
            request_headers["Content-Type"] = "application/json"
            return self.client.post("/api/session-rename", content=content, headers=request_headers)
        return self.client.post("/api/session-rename", json=self.body if body is None else body,
                                headers=request_headers)

    def test_exact_post_and_status_safe_dtos_no_store_and_no_mutating_status(self):
        self.login()
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), ACCEPTED)
        self.assertIn("no-store", response.headers.get("cache-control", ""))
        status = self.client.get(self.status_path, headers={"Origin": ORIGIN})
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json(), UNKNOWN)
        self.assertIn("no-store", status.headers.get("cache-control", ""))
        self.assertEqual(self.backend.calls, [
            ("session_rename", "demo", SID, OPID, TITLE),
            ("session_rename_status", "demo", SID, OPID),
        ])

    def test_auth_csrf_and_origin_gate_before_backend(self):
        self.assertEqual(self.post().status_code, 401)
        self.login()
        self.assertEqual(self.post(headers={"Origin": EVIL_ORIGIN}).status_code, 403)
        self.assertEqual(self.post(headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        self.assertEqual(self.client.get(self.status_path, headers={"Origin": EVIL_ORIGIN}).status_code, 403)
        self.assertEqual(self.backend.calls, [])

    def test_post_and_status_reject_extra_duplicate_malformed_and_unsafe_fields(self):
        self.login()
        bad_bodies = [
            {**self.body, "rpc_method": "thread/name/set"},
            {key: value for key, value in self.body.items() if key != "title"},
            {**self.body, "vendor": "claude"},
            {**self.body, "root": "/tmp"},
            {**self.body, "sid": SID[:8]},
            {**self.body, "operation_id": "bad"},
            {**self.body, "title": " leading-control\n"},
            {**self.body, "title": "\tTitle"},
            {**self.body, "title": "x" * 161},
        ]
        for body in bad_bodies:
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 422)
        duplicate = ("{\"project\":\"demo\",\"sid\":\"" + SID + "\",\"operation_id\":\"" +
                     OPID + "\",\"title\":\"first\",\"title\":\"second\"}")
        self.assertEqual(self.post(content=duplicate).status_code, 422)
        malformed_status = [
            f"/api/session-rename-status?project=demo&project=other&sid={SID}&operation_id={OPID}",
            f"/api/session-rename-status?project=demo&sid={SID}&sid={OTHER}&operation_id={OPID}",
            f"/api/session-rename-status?project=demo&sid={SID}&operation_id={OPID}&rpc=x",
            f"/api/session-rename-status?project=../private&sid={SID}&operation_id={OPID}",
            f"/api/session-rename-status?project=demo&sid={SID[:8]}&operation_id={OPID}",
        ]
        for path in malformed_status:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers={"Origin": ORIGIN}).status_code, 422)
        self.assertEqual(self.backend.calls, [])

    def test_unsupported_or_unknown_is_forwarded_once_without_fallback_or_retry(self):
        self.login()
        self.backend.rename_result = {"error": "unavailable"}
        result = self.post()
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json(), {"error": "unavailable"})
        self.assertEqual(self.backend.calls, [("session_rename", "demo", SID, OPID, TITLE)])

    def test_existing_legacy_send_contract_remains_four_argument(self):
        self.login()
        message_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        response = self.client.post("/api/session-send", json={"project": "demo", "sid": SID,
            "message_id": message_id, "text": "still works"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.backend.calls, [("session_send", "demo", SID, message_id, "still works")])


class ChatFacade:
    def __init__(self):
        self.calls = []
        self.result = dict(ACCEPTED)

    def rename(self, project, sid, operation_id, title):
        self.calls.append(("rename", project, sid, operation_id, title))
        return self.result

    def rename_status(self, project, sid, operation_id):
        self.calls.append(("rename_status", project, sid, operation_id))
        return dict(UNKNOWN)


class OwnerBackend:
    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {"tasks": []}

    def session_rename(self, project, sid, operation_id, title):
        self.calls.append(("session_rename", project, sid, operation_id, title))
        return dict(ACCEPTED)

    def session_rename_status(self, project, sid, operation_id):
        self.calls.append(("session_rename_status", project, sid, operation_id))
        return dict(UNKNOWN)


class RenameBroker(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("_control_web_broker")
        self.tmp = tempfile.TemporaryDirectory(prefix="web-session-rename-broker-", dir="/var/tmp")
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

    def test_registry_backend_exposes_only_fixed_rename_methods_and_arguments(self):
        registry = self.base / "registry"
        registry.mkdir(mode=0o700)
        chat = ChatFacade()
        backend = self.module.RegistryBackend(str(registry), str(ROOT / "bin"), sessions=chat)
        rename = getattr(backend, "session_rename", None)
        status = getattr(backend, "session_rename_status", None)
        self.assertTrue(callable(rename), "RegistryBackend must expose fixed session_rename")
        self.assertTrue(callable(status), "RegistryBackend must expose fixed session_rename_status")
        if not callable(rename) or not callable(status):
            return
        self.assertEqual(rename("demo", SID, OPID, TITLE), ACCEPTED)
        self.assertEqual(status("demo", SID, OPID), UNKNOWN)
        self.assertEqual(chat.calls, [
            ("rename", "demo", SID, OPID, TITLE),
            ("rename_status", "demo", SID, OPID),
        ])

    def test_owner_fixed_operations_roundtrip_safe_dtos(self):
        self.start()
        self.assertEqual(self.wire({"op": "session_rename", "project": "demo", "sid": SID,
            "operation_id": OPID, "title": TITLE}), ACCEPTED)
        self.assertEqual(self.wire({"op": "session_rename_status", "project": "demo", "sid": SID,
            "operation_id": OPID}), UNKNOWN)
        self.assertEqual(self.backend.calls, [
            ("session_rename", "demo", SID, OPID, TITLE),
            ("session_rename_status", "demo", SID, OPID),
        ])

    def test_owner_rejects_wrong_or_duplicate_fields_before_backend(self):
        self.start()
        requests = [
            {"op": "session_rename", "project": "demo", "sid": SID, "operation_id": OPID,
             "title": TITLE, "rpc": "thread/name/set"},
            {"op": "session_rename", "project": "../private", "sid": SID,
             "operation_id": OPID, "title": TITLE},
            {"op": "session_rename", "project": "demo", "sid": SID[:8],
             "operation_id": OPID, "title": TITLE},
            {"op": "session_rename_status", "project": "demo", "sid": SID, "operation_id": OPID,
             "root": "/tmp"},
            b'{"op":"session_rename_status","project":"demo","sid":"' + SID.encode() +
                b'","operation_id":"' + OPID.encode() + b'","sid":"' + OTHER.encode() + b'"}',
        ]
        for request in requests:
            with self.subTest(kind=type(request).__name__):
                self.assertIn("error", self.wire(request))
        self.assertEqual(self.backend.calls, [])

    def test_socket_backend_sends_only_the_fixed_operations(self):
        self.start()
        backend = self.module.SocketBackend(self.socket_path)
        rename = getattr(backend, "session_rename", None)
        status = getattr(backend, "session_rename_status", None)
        self.assertTrue(callable(rename), "SocketBackend must expose fixed session_rename")
        self.assertTrue(callable(status), "SocketBackend must expose fixed session_rename_status")
        if not callable(rename) or not callable(status):
            return
        self.assertEqual(rename("demo", SID, OPID, TITLE), ACCEPTED)
        self.assertEqual(status("demo", SID, OPID), UNKNOWN)
        self.assertEqual(self.backend.calls, [
            ("session_rename", "demo", SID, OPID, TITLE),
            ("session_rename_status", "demo", SID, OPID),
        ])


if __name__ == "__main__":
    unittest.main()
