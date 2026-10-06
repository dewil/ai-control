"""Independent synthetic INV-WSESS-30 fixed RPC and receipt crash tests."""
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
SID = "11111111-1111-4111-8111-111111111111"
OP = "22222222-2222-4222-8222-222222222222"
TITLE = "Crash-safe synthetic title"
CONTEXT = {"schema": 1, "vendor": "codex", "context_kind": "legacy_unbound",
           "context_id": "a" * 64, "transport_generation": 1,
           "context_generation": 1, "native_version": "0.160.0"}


def feature(case):
    path = ROOT / "bin" / "_control_web_sessions.py"
    case.assertTrue(path.is_file(), "Public session transport module must exist")
    return importlib.import_module("_control_web_sessions")


class InteractiveRenameTransport(unittest.TestCase):
    def setUp(self):
        self.module = feature(self)
        self.temp = tempfile.TemporaryDirectory(prefix="web-rename-transport-", dir="/var/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        os.chmod(self.base, 0o700)
        self.socket_path = self.base / "synthetic-codex.sock"
        self.frames = []
        self.server_errors = []
        self.ready = threading.Event()

    def start_server(self):
        from websockets.sync.server import unix_serve

        def handler(ws):
            try:
                while True:
                    frame = json.loads(ws.recv(timeout=3))
                    self.frames.append(frame)
                    method = frame.get("method")
                    if method == "initialize":
                        ws.send(json.dumps({"id": frame["id"], "result": {
                            "userAgent": "codex/0.160.0 (synthetic fixture)",
                            "codexHome": str(self.base / "synthetic-codex-home"),
                            "platformFamily": "unix", "platformOs": "linux"}}))
                    elif method == "initialized":
                        self.ready.set()
                    elif method == "thread/read":
                        ws.send(json.dumps({"id": frame["id"], "result": {"thread": {
                            "id": SID, "cwd": str(self.base / "project"), "name": "Old title"}}}))
                    elif method == "thread/name/set":
                        ws.send(json.dumps({"id": frame["id"], "result": {}}))
                    else:
                        ws.send(json.dumps({"id": frame.get("id"), "error": {
                            "code": -32601, "message": "synthetic method denied"}}))
            except Exception as error:
                from websockets.exceptions import ConnectionClosed
                if not isinstance(error, ConnectionClosed):
                    self.server_errors.append(type(error).__name__)

        server = unix_serve(handler, str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(server.shutdown)

    def test_INV_WSESS_30_interactive_transport_dispatches_only_fixed_name_set_in_captured_generation(self):
        rpc_type = getattr(self.module, "InteractiveRPC", None)
        self.assertTrue(callable(rpc_type), "InteractiveRPC public transport seam must exist")
        fenced = getattr(rpc_type, "call_in_generation", None)
        self.assertTrue(callable(fenced), "InteractiveRPC must expose call_in_generation")
        context_method = getattr(rpc_type, "model_context", None)
        self.assertTrue(callable(context_method), "InteractiveRPC must expose validated model_context")
        if not (callable(rpc_type) and callable(fenced) and callable(context_method)):
            return

        self.start_server()
        rpc = rpc_type(str(self.socket_path), timeout=1)
        self.addCleanup(rpc.close)
        self.assertEqual(rpc("thread/read", {"threadId": SID, "includeTurns": False}),
                         {"thread": {"id": SID, "cwd": str(self.base / "project"), "name": "Old title"}})
        context = rpc.model_context()
        self.assertIsInstance(context, dict)
        if not isinstance(context, dict):
            return
        transport_generation = context.get("transport_generation")
        context_generation = context.get("context_generation")
        self.assertIs(type(transport_generation), int)
        self.assertIs(type(context_generation), int)
        if type(transport_generation) is not int or type(context_generation) is not int:
            return

        try:
            result = rpc.call_in_generation("thread/name/set", {"threadId": SID, "name": TITLE},
                transport_generation=transport_generation, context_generation=context_generation, timeout=1)
        except Exception as error:
            result = {"raised": type(error).__name__}
        self.assertEqual(result, {})
        before_forbidden = len(self.frames)
        try:
            rpc.call_in_generation("thread/start", {"cwd": str(self.base / "project")},
                transport_generation=transport_generation, context_generation=context_generation, timeout=1)
            forbidden_error = None
        except Exception as error:
            forbidden_error = error
        self.assertIsNotNone(forbidden_error, "arbitrary native RPC methods must be refused")
        self.assertEqual(len(self.frames), before_forbidden,
                         "arbitrary or create RPC methods must be refused before wire dispatch")
        self.assertEqual([frame.get("method") for frame in self.frames],
                         ["initialize", "initialized", "thread/read", "thread/name/set"])
        name_frames = [frame for frame in self.frames if frame.get("method") == "thread/name/set"]
        self.assertEqual(len(name_frames), 1)
        if name_frames:
            name_call = name_frames[0]
            self.assertEqual(name_call.get("params"), {"threadId": SID, "name": TITLE})
            self.assertIsNotNone(name_call.get("id"))
        self.assertEqual(self.server_errors, [])


class RenamePublicationCrash(unittest.TestCase):
    def setUp(self):
        self.module = feature(self)
        self.temp = tempfile.TemporaryDirectory(prefix="web-rename-crash-", dir="/var/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        os.chmod(self.base, 0o700)
        self.root = self.base / "project"
        self.root.mkdir(mode=0o700)
        self.store_path = self.base / "rename-receipts"
        self.title_path = self.base / "native-title"
        self.counter_path = self.base / "native-set-count"
        self.title_path.write_text("Before", encoding="utf-8")
        self.counter_path.write_text("0", encoding="ascii")

    def receipt_files(self):
        found = []
        if not self.store_path.is_dir():
            return found
        for path in self.store_path.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if type(record) is dict and record.get("operation_id") == OP:
                found.append((path, record))
        return found

    def child_source(self):
        return r'''
import importlib, json, os, sys
from pathlib import Path
root, store_path, title_path, counter_path = map(Path, sys.argv[1:5])
sys.path.insert(0, os.environ["PYTHONPATH"])
module = importlib.import_module("_control_web_sessions")
sid = "11111111-1111-4111-8111-111111111111"
operation = "22222222-2222-4222-8222-222222222222"
context = {"schema":1,"vendor":"codex","context_kind":"legacy_unbound","context_id":"a"*64,
           "transport_generation":1,"context_generation":1,"native_version":"0.160.0"}
class RPC:
    def model_context(self): return dict(context)
    def __call__(self, method, params):
        if method == "thread/read":
            return {"thread":{"id":sid,"cwd":str(root),"name":title_path.read_text(encoding="utf-8")}}
        if method == "thread/name/set":
            counter_path.write_text(str(int(counter_path.read_text(encoding="ascii"))+1), encoding="ascii")
            title_path.write_text(params["name"], encoding="utf-8")
            return {}
        raise AssertionError("unexpected synthetic RPC " + method)
    def call_in_generation(self, method, params, *, transport_generation, context_generation, timeout=None):
        if (transport_generation,context_generation)!=(1,1): raise RuntimeError("generation mismatch")
        return self(method,params)
def resolve(project):
    if project != "demo": raise ValueError("unknown project")
    return str(root)
original_link = os.link
def crash_after_link(*args, **kwargs):
    result = original_link(*args, **kwargs)
    os._exit(85)
os.link = crash_after_link
chat = module.SessionChat(RPC(), resolve, lambda:["demo"], str(root.parent/"send-receipts"),
    model_context=lambda:dict(context), model_clock=lambda:100,
    rename_store=module.RenameStore(str(store_path)))
result = chat.rename("demo",sid,operation,"Crash-safe synthetic title")
print(json.dumps(result))
'''

    def parent_chat(self):
        sid = SID
        root, title_path, counter_path = self.root, self.title_path, self.counter_path
        context = dict(CONTEXT)

        class RPC:
            def model_context(self):
                return dict(context)
            def __call__(self, method, params):
                if method == "thread/read":
                    return {"thread": {"id": sid, "cwd": str(root),
                                        "name": title_path.read_text(encoding="utf-8")}}
                if method == "thread/name/set":
                    counter_path.write_text(str(int(counter_path.read_text(encoding="ascii")) + 1), encoding="ascii")
                    title_path.write_text(params["name"], encoding="utf-8")
                    return {}
                raise AssertionError("Unexpected synthetic RPC: " + method)
            def call_in_generation(self, method, params, *, transport_generation, context_generation, timeout=None):
                if (transport_generation, context_generation) != (1, 1):
                    raise RuntimeError("synthetic generation mismatch")
                return self(method, params)

        def resolve(project):
            if project != "demo":
                raise ValueError("unknown synthetic project")
            return str(root)
        return self.module.SessionChat(RPC(), resolve, lambda: ["demo"],
            str(self.base / "send-receipts"), model_context=lambda: dict(context), model_clock=lambda: 100,
            rename_store=self.module.RenameStore(str(self.store_path)))

    def test_INV_WSESS_30_crash_during_initial_publication_recovers_unknown_without_hardlink_or_second_set(self):
        store_type = getattr(self.module, "RenameStore", None)
        session_chat = getattr(self.module, "SessionChat", None)
        self.assertTrue(callable(store_type), "RenameStore public seam must exist")
        self.assertTrue(callable(getattr(session_chat, "rename_status", None)),
                        "SessionChat.rename_status public seam must exist")
        if not callable(store_type) or not callable(getattr(session_chat, "rename_status", None)):
            return

        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "bin")
        source = self.child_source()
        child = subprocess.run([sys.executable, "-c", source, str(self.root), str(self.store_path),
            str(self.title_path), str(self.counter_path)], cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
        self.assertIn(child.returncode, (0, 85),
                      "Synthetic child must either complete via another safe primitive or crash after os.link")
        records = self.receipt_files()
        self.assertTrue(records, "A durable receipt identified by public operation_id fields must survive restart")
        bad_links = []
        for path, record in records:
            link_count = path.stat().st_nlink
            if link_count != 1:
                bad_links.append((str(path), link_count))
            self.assertEqual(record.get("operation_id"), OP)
            self.assertEqual(record.get("kind"), "session_rename")

        chat = self.parent_chat()
        status = chat.rename_status("demo", SID, OP)
        status_ok = status.get("status") in ("delivery_unknown", "accepted")
        first_count = int(self.counter_path.read_text(encoding="ascii"))
        replay = chat.rename("demo", SID, OP, TITLE)
        replay_ok = replay.get("status") in ("delivery_unknown", "accepted")
        self.assertEqual(int(self.counter_path.read_text(encoding="ascii")), first_count,
                         "Exact replay after restart must not issue another thread/name/set")
        self.assertEqual(
            {"status_preserved": status_ok, "replay_preserved": replay_ok, "bad_links": bad_links},
            {"status_preserved": True, "replay_preserved": True, "bad_links": []},
            "Crash publication must preserve unknown/accepted status and exact replay without a hardlinked receipt; "
            + repr({"child_rc": child.returncode, "status": status, "replay": replay,
                    "records": [record for _, record in records], "native_set_count": first_count,
                    "link_counts": [path.stat().st_nlink for path, _ in records]}))
        if child.returncode == 85:
            self.assertEqual(first_count, 0, "Publication crash must precede native mutation")
            self.assertNotEqual(self.title_path.read_text(encoding="utf-8"), TITLE)
        else:
            self.assertEqual(first_count, 1)
            self.assertEqual(self.title_path.read_text(encoding="utf-8"), TITLE)


if __name__ == "__main__":
    unittest.main()
