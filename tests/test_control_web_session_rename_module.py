"""Synthetic INV-WSESS-30 rename contracts from the frozen public spec."""
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
SID = "11111111-1111-4111-8111-111111111111"
OP = "22222222-2222-4222-8222-222222222222"
CONTEXT = {"schema": 1, "vendor": "codex", "context_kind": "legacy_unbound", "context_id": "a" * 64, "transport_generation": 3, "context_generation": 7, "native_version": "0.160.0"}


def feature(case):
    path = ROOT / "bin" / "_control_web_sessions.py"
    case.assertTrue(path.is_file(), "SessionChat public module must exist")
    return importlib.import_module("_control_web_sessions")


class RenameRPC:
    """In-memory native boundary; permits only thread/read and name/set."""
    def __init__(self, root):
        self.root, self.calls, self.thread_id, self.thread_root = root, [], SID, root
        self.name, self.preview, self.read_error, self.set_error = "Before rename", None, None, None
        self.set_updates_name, self.on_set = True, None
        self.transport_generation, self.context_generation = 3, 7

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method == "thread/read":
            if self.read_error:
                raise self.read_error
            thread = {"id": self.thread_id, "cwd": str(self.thread_root), "name": self.name}
            if self.preview is not None:
                thread["preview"] = self.preview
            return {"thread": thread}
        if method == "thread/name/set":
            if self.on_set:
                self.on_set()
            if self.set_error:
                raise self.set_error
            if self.set_updates_name:
                self.name = params.get("name")
            return {}
        raise AssertionError("Unexpected synthetic native call: " + method)

    def call_in_generation(self, method, params, *, transport_generation, context_generation, timeout=None):
        if (transport_generation, context_generation) != (self.transport_generation, self.context_generation):
            raise RuntimeError("synthetic captured generation mismatch")
        return self(method, params)


class SessionRenameModule(unittest.TestCase):
    def setUp(self):
        self.module = feature(self)
        self.temp = tempfile.TemporaryDirectory(prefix="web-rename-contract-", dir="/var/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        os.chmod(self.base, 0o700)
        self.root = self.base / "project"
        self.root.mkdir(mode=0o700)
        self.store_path = self.base / "rename-receipts"
        self.rpc, self.context, self.now = RenameRPC(self.root), dict(CONTEXT), [100]

    def api(self):
        cls = getattr(self.module, "SessionChat", None)
        self.assertTrue(callable(cls), "SessionChat must exist")
        self.assertTrue(callable(getattr(self.module, "RenameStore", None)), "RenameStore(path) public seam is required")
        self.assertTrue(callable(getattr(cls, "rename", None)), "SessionChat.rename(project, sid, operation_id, title) is required")
        self.assertTrue(callable(getattr(cls, "rename_status", None)), "SessionChat.rename_status(project, sid, operation_id) is required")
        params = inspect.signature(cls).parameters
        self.assertIn("rename_store", params, "SessionChat must accept trusted rename_store")
        self.assertIn("model_context", params, "SessionChat must accept trusted model_context getter")
        return cls

    def chat(self, rpc=None):
        cls = self.api()
        def resolve(alias):
            if alias != "demo":
                raise ValueError("synthetic invalid project")
            return str(self.root)
        return cls(rpc or self.rpc, resolve, lambda: ["demo"], str(self.base / "send-receipts"),
                   model_context=lambda: dict(self.context), model_clock=lambda: self.now[0],
                   rename_store=self.module.RenameStore(str(self.store_path)))

    def invoke(self, title="Next title", operation=OP, rpc=None):
        return self.chat(rpc).rename("demo", SID, operation, title)

    def fenced(self, method):
        return [row for row in self.rpc.calls if row[0] == method]

    def test_public_rename_api_and_private_store_seams_exist(self):
        self.api()
        self.assertIn("path", inspect.signature(self.module.RenameStore).parameters)

    def test_title_is_trimmed_without_rewriting_case_unicode_or_inner_spaces(self):
        result = self.invoke("  Café  Name  ")
        self.assertEqual(self.fenced("thread/name/set"), [("thread/name/set", {"threadId": SID, "name": "Café  Name"})])
        self.assertEqual(result.get("status"), "accepted")
        self.assertEqual(result.get("title"), "Café  Name")
        self.assertEqual(result.get("operation_id"), OP)

    def test_raw_title_limits_and_controls_are_checked_before_trim_or_effects(self):
        result = self.invoke(" " * 10 + "x" * 160 + " " * 10)
        self.assertEqual(result.get("title"), "x" * 160)
        self.assertEqual(len(self.fenced("thread/name/set")), 1)
        self.rpc.calls.clear()
        invalid = ["\tname", "name\n", "\x7fname", "\x85name", "  \x00  ", " " * 40,
                   "x" * 161, "x" * 2049, b"bad-utf8-\xff", None, ["title"]]
        for title in invalid:
            with self.subTest(title_type=type(title).__name__, size=len(title) if hasattr(title, "__len__") else None):
                self.assertEqual(self.invoke(title), {"error": "invalid_request"})
        self.assertEqual(self.rpc.calls, [], "invalid raw titles must have no native effects")
        self.assertFalse(self.store_path.exists(), "invalid input must not create receipt storage")

    def test_raw_utf8_byte_limit_is_enforced_before_native_effects(self):
        self.assertEqual(self.invoke("é" * 2048), {"error": "invalid_request"})
        self.assertEqual(self.rpc.calls, [])
        self.assertFalse(self.store_path.exists())

    def test_bad_identifiers_or_project_are_rejected_before_reservation(self):
        chat = self.chat()
        for project, sid, op in [("../project", SID, OP), ("demo", SID[:8], OP), ("demo", SID, "not-a-uuid"), ("demo", SID.upper(), OP)]:
            with self.subTest(project=project, sid=sid, op=op):
                self.assertEqual(chat.rename(project, sid, op, "Next"), {"error": "invalid_request"})
        self.assertEqual(self.rpc.calls, [])
        self.assertFalse(self.store_path.exists())

    def test_unverified_context_and_native_version_are_unavailable_without_mutation(self):
        for changes in ({"vendor": "unknown"}, {"context_kind": "provider_profile"}, {"native_version": "0.159.9"}, {"native_version": "unknown"}, {"context_id": "bad"}):
            with self.subTest(changes=changes):
                self.context = {**CONTEXT, **changes}
                self.rpc.calls.clear()
                self.assertEqual(self.invoke(), {"error": "unavailable"})
                self.assertFalse(self.fenced("thread/name/set"))
                self.assertFalse(self.store_path.exists())

    def test_full_uuid_root_and_fresh_thread_proof_precede_reservation(self):
        for field, value in (("thread_id", "33333333-3333-4333-8333-333333333333"), ("thread_root", self.base / "other")):
            with self.subTest(field=field):
                setattr(self.rpc, field, value)
                self.rpc.calls.clear()
                self.assertIn(self.invoke(), ({"error": "stale"}, {"error": "unavailable"}))
                self.assertFalse(self.fenced("thread/name/set"))
                self.assertFalse(self.store_path.exists())
                setattr(self.rpc, field, SID if field == "thread_id" else self.root)

    def test_happy_path_reserves_before_one_fenced_set_then_proves_raw_name(self):
        observed = []
        self.rpc.on_set = lambda: observed.append((self.store_path.is_file(), self.store_path.stat().st_mode & 0o777 if self.store_path.exists() else None))
        result = self.invoke("  Approved  ")
        self.assertEqual(observed, [(True, 0o600)], "durable unknown receipt must precede mutation")
        self.assertEqual(self.fenced("thread/name/set"), [("thread/name/set", {"threadId": SID, "name": "Approved"})])
        self.assertEqual(self.fenced("thread/read")[-1], ("thread/read", {"threadId": SID, "includeTurns": False}))
        self.assertEqual(result, {"operation_id": OP, "status": "accepted", "title": "Approved"})
        self.assertEqual({method for method, _ in self.rpc.calls}, {"thread/read", "thread/name/set"})

    def test_receipt_is_exact_private_digest_record_and_never_contains_title(self):
        self.invoke("Private title")
        files = list(self.store_path.iterdir())
        self.assertEqual(len(files), 1)
        receipt_path = files[0]
        self.assertEqual(stat.S_IMODE(self.store_path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
        self.assertEqual(receipt_path.stat().st_nlink, 1)
        raw = receipt_path.read_text(encoding="utf-8")
        record = json.loads(raw)
        self.assertEqual(set(record), {"schema", "kind", "context_id", "root", "sid", "operation_id", "digest", "title_hash", "status", "created"})
        self.assertEqual((record["schema"], record["kind"], record["status"]), (1, "session_rename", "accepted"))
        self.assertEqual((record["context_id"], record["root"], record["sid"], record["operation_id"]), (CONTEXT["context_id"], str(self.root), SID, OP))
        canonical = json.dumps({"kind": "session_rename", "context_id": CONTEXT["context_id"], "root": str(self.root), "sid": SID, "title": "Private title"}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertEqual(record["digest"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(record["title_hash"], hashlib.sha256("Private title".encode("utf-8")).hexdigest())
        self.assertNotIn("Private title", raw)
        self.assertNotIn("Private title", json.dumps(result))
        self.assertEqual(self.rpc.calls.count(("thread/name/set", {"threadId": SID, "name": "Private title"})), 1)

    def test_ack_without_raw_name_proof_is_unknown_and_preview_never_confirms(self):
        self.rpc.set_updates_name, self.rpc.preview = False, "Wanted title"
        self.assertEqual(self.invoke("Wanted title"), {"operation_id": OP, "status": "delivery_unknown"})
        before = len(self.fenced("thread/name/set"))
        self.assertEqual(self.invoke("Wanted title"), {"operation_id": OP, "status": "delivery_unknown"})
        self.assertEqual(len(self.fenced("thread/name/set")), before)

    def test_any_post_reservation_native_error_is_unknown_and_never_retried(self):
        self.rpc.set_error = TimeoutError("synthetic timeout after dispatch")
        self.assertEqual(self.invoke("May have changed"), {"operation_id": OP, "status": "delivery_unknown"})
        self.assertEqual(len(self.fenced("thread/name/set")), 1)
        self.rpc.set_error = None
        self.assertEqual(self.invoke("May have changed"), {"operation_id": OP, "status": "delivery_unknown"})
        self.assertEqual(len(self.fenced("thread/name/set")), 1)

    def test_status_manual_observation_promotes_unknown_without_native_mutation(self):
        self.rpc.set_updates_name = False
        self.assertEqual(self.invoke("Observed later"), {"operation_id": OP, "status": "delivery_unknown"})
        before = list(self.rpc.calls)
        self.rpc.name = "Observed later"
        result = self.chat().rename_status("demo", SID, OP)
        self.assertEqual(result, {"operation_id": OP, "status": "accepted", "title": "Observed later"})
        self.assertEqual(self.rpc.calls[len(before):], [], "status reconciliation must not call native")
        self.assertEqual(json.loads(next(self.store_path.iterdir()).read_text(encoding="utf-8"))["status"], "accepted")

    def test_status_mismatch_keeps_unknown_and_never_mutates_native(self):
        self.rpc.set_updates_name = False
        self.invoke("Wanted")
        before = list(self.rpc.calls)
        self.rpc.name = "Different"
        self.assertEqual(self.chat().rename_status("demo", SID, OP), {"operation_id": OP, "status": "delivery_unknown"})
        self.assertEqual(self.rpc.calls[len(before):], [])
        self.assertEqual(json.loads(next(self.store_path.iterdir()).read_text(encoding="utf-8"))["status"], "unknown")

    def test_replay_conflict_and_corrupt_receipt_fail_closed_without_second_set(self):
        self.rpc.set_updates_name = False
        self.invoke("First title")
        count = len(self.fenced("thread/name/set"))
        self.assertEqual(self.invoke("First title"), {"operation_id": OP, "status": "delivery_unknown"})
        self.assertEqual(self.invoke("Changed payload"), {"error": "invalid_request"})
        self.assertEqual(len(self.fenced("thread/name/set")), count)
        next(self.store_path.iterdir()).write_text("{broken", encoding="utf-8")
        self.assertEqual(self.invoke("First title"), {"error": "unavailable"})
        self.assertEqual(len(self.fenced("thread/name/set")), count)

    def test_accepted_receipt_never_guesses_title_when_fresh_read_is_unusable(self):
        self.invoke("Accepted")
        for bad_name in (None, 7, "  ", b"\xff"):
            with self.subTest(bad_name=bad_name):
                self.rpc.name = bad_name
                result = self.chat().rename_status("demo", SID, OP)
                self.assertEqual(result.get("status"), "unavailable")
                self.assertNotIn("title", result)
                self.assertNotIn("Accepted", json.dumps(result))
                self.assertEqual(json.loads(next(self.store_path.iterdir()).read_text(encoding="utf-8"))["status"], "accepted")
        self.rpc.name, self.rpc.read_error = "Accepted", OSError("synthetic read failure")
        result = self.chat().rename_status("demo", SID, OP)
        self.assertEqual(result.get("status"), "unavailable")
        self.assertNotIn("title", result)
        self.assertEqual(json.loads(next(self.store_path.iterdir()).read_text(encoding="utf-8"))["status"], "accepted")

    def test_generation_change_after_reservation_is_unknown_without_retry(self):
        original = self.rpc.call_in_generation
        def fenced(method, params, *, transport_generation, context_generation, timeout=None):
            if method == "thread/name/set":
                self.rpc.transport_generation += 1
            return original(method, params, transport_generation=transport_generation,
                            context_generation=context_generation, timeout=timeout)
        self.rpc.call_in_generation = fenced
        self.assertEqual(self.invoke("Unknown outcome"), {"operation_id": OP, "status": "delivery_unknown"})
        self.assertFalse(self.fenced("thread/name/set"), "generation mismatch must not dispatch to replacement socket")
        self.assertEqual(self.invoke("Unknown outcome"), {"operation_id": OP, "status": "delivery_unknown"})
        self.assertFalse(self.fenced("thread/name/set"))


if __name__ == "__main__":
    unittest.main()
