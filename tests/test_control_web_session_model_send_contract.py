"""Synthetic source-blind INV-WSESS-25/26 send and receipt acceptance."""
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from test_control_web_session_chat_contract import MID, OTHER, SID, TURN, feature

TEXT = "synthetic private draft only"
CONTEXT = {
    "schema": 1,
    "vendor": "codex",
    "context_kind": "legacy_unbound",
    "context_id": "a" * 64,
    "transport_generation": 3,
    "context_generation": 7,
    "native_version": "0.160.0",
}


def native_model(model_id="ui-gpt", wire="wire-gpt", **overrides):
    row = {
        "id": model_id,
        "model": wire,
        "displayName": "Synthetic GPT",
        "description": "Synthetic native model row",
        "supportedReasoningEfforts": [
            {"reasoningEffort": "low", "description": "Synthetic low"},
            {"reasoningEffort": "high", "description": "Synthetic high"},
        ],
        "defaultReasoningEffort": "low",
        "isDefault": True,
        "hidden": False,
    }
    row.update(overrides)
    return row


class FakeRPC:
    """Synthetic owner/native boundary; never opens a socket or reads history."""
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.fenced_calls = []
        self.pages = {None: {"data": [native_model()], "nextCursor": None}}
        self.active_transport_generation = CONTEXT["transport_generation"]
        self.active_context_generation = CONTEXT["context_generation"]
        self.thread_id = SID
        self.thread_root = root
        self.start_response = {"turn": {"id": TURN}}
        self.start_error = None
        self.before_start = None
        self.after_response = None
    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method in ("thread/read", "thread/resume"):
            result = {"thread": {"id": self.thread_id, "cwd": str(self.thread_root), "status": {"type": "idle"}}}
        elif method == "model/list":
            result = self.pages[params.get("cursor")]
            if isinstance(result, BaseException):
                raise result
        elif method == "turn/start":
            if self.before_start:
                self.before_start()
            if self.start_error:
                raise self.start_error
            result = self.start_response
        else:
            raise AssertionError("Unexpected synthetic RPC: " + method)
        if self.after_response:
            self.after_response(method, params)
        return result
    def call_in_generation(self, method, params, *, transport_generation, context_generation, timeout=None):
        self.fenced_calls.append((method, dict(params), transport_generation, context_generation, timeout))
        if (transport_generation, context_generation) != (self.active_transport_generation, self.active_context_generation):
            raise RuntimeError("synthetic captured generation is no longer live")
        return self(method, params)
    def methods(self):
        return [method for method, _params in self.calls]
    def params_for(self, method):
        return [params for name, params in self.calls if name == method]
    def starts(self):
        return self.params_for("turn/start")
    def effects(self):
        return [name for name in self.methods() if name in {"model/list", "thread/resume", "turn/start"}]


class SessionModelSendContract(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, "_control_web_sessions")
        self.tmp = tempfile.TemporaryDirectory(prefix="web-session-model-send-", dir="/var/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.project = self.base / "project"
        self.project.mkdir(mode=0o700)
        self.receipts = self.base / "receipts"
        self.rpc = FakeRPC(self.project)
        self.now = [100.0]
        self.context = dict(CONTEXT)
        self.context_getter = lambda: dict(self.context)

    def chat(self, require_selection=True, rpc=None, context_getter=None):
        cls = self.module.SessionChat
        self.assertTrue(callable(getattr(cls, "send", None)), "SessionChat.send is required")
        constructor = inspect.signature(cls).parameters
        self.assertIn("model_context", constructor, "trusted model_context seam is required")
        self.assertIn("model_clock", constructor, "model_clock seam is required")
        send_parameters = inspect.signature(cls.send).parameters
        if require_selection:
            self.assertIn("selection", send_parameters,
                          "SessionChat.send(..., selection=None) is required by INV-WSESS-25")
            self.assertIsNone(send_parameters["selection"].default)
        def resolve(alias):
            if alias != "demo":
                raise ValueError("synthetic invalid project")
            return str(self.project)
        return cls(rpc or self.rpc, resolve, lambda: ["demo"], str(self.receipts),
                   model_context=context_getter or self.context_getter,
                   model_clock=lambda: self.now[0])

    def catalog(self, chat=None):
        cls = self.module.SessionChat
        self.assertTrue(callable(getattr(cls, "models", None)),
                        "SessionChat.models is required to issue an explicit catalog selection")
        return (chat or self.chat()).models("demo", SID)

    def selection(self, catalog_id, model_id="ui-gpt", effort="high"):
        return {"catalog_id": catalog_id, "model_id": model_id, "effort": effort}

    def receipt_paths(self, message_id=MID):
        paths = []
        if not self.receipts.exists():
            return paths
        for path in self.receipts.rglob("*"):
            if not path.is_file():
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if isinstance(record, dict) and record.get("message_id") == message_id:
                paths.append(path)
        return paths

    def record_for(self, message_id=MID):
        paths = self.receipt_paths(message_id)
        self.assertEqual(len(paths), 1, "expected exactly one private receipt for synthetic UUID")
        return paths[0], json.loads(paths[0].read_text(encoding="utf-8"))

    def assert_no_send_effects(self):
        self.assertNotIn("model/list", self.rpc.methods(), "send must not refresh catalog automatically")
        self.assertNotIn("thread/resume", self.rpc.methods(), "pre-reserve rejection must not resume")
        self.assertNotIn("turn/start", self.rpc.methods(), "pre-reserve rejection must not dispatch a turn")
        self.assertEqual(self.receipt_paths(), [], "known pre-effect rejection must not reserve a receipt")

    def test_four_argument_inherit_preserves_legacy_native_params_and_safe_public_receipt(self):
        chat = self.chat(require_selection=False)
        result = chat.send("demo", SID, MID, TEXT)
        self.assertEqual(result, {"status": "accepted", "message_id": MID, "turn_id": TURN})
        self.assertEqual(set(result), {"status", "message_id", "turn_id"})
        self.assertEqual(self.rpc.methods().count("model/list"), 0)
        start = self.rpc.starts()[0]
        self.assertEqual(set(start), {"threadId", "input", "clientUserMessageId"})
        self.assertEqual(start["threadId"], SID)
        self.assertEqual(start["clientUserMessageId"], MID)
        self.assertEqual(start["input"], [{"type": "text", "text": TEXT}])
        self.assertNotIn("model", start)
        self.assertNotIn("effort", start)
        self.assertNotIn("collaborationMode", start)
        _path, record = self.record_for()
        self.assertEqual(record.get("schema"), 2, "new inherit receipts use private schema2")
        self.assertIsNone(record.get("selection"))
        self.assertNotIn(TEXT, json.dumps(record))

    def test_explicit_pair_maps_ui_id_to_wire_and_reserves_exact_private_digest_before_start(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        self.assertEqual(catalog["selection_support"], "available")
        self.assertRegex(catalog["catalog_id"], r"^[0-9a-f]{64}$")
        self.rpc.calls.clear()
        self.rpc.fenced_calls.clear()
        reserved = []
        def before_start():
            path, record = self.record_for()
            self.assertTrue(path.exists(), "durable reservation must precede turn/start")
            reserved.append(record)
        self.rpc.before_start = before_start
        private_selection = {"catalog_id": catalog["catalog_id"], "model_id": "ui-gpt",
                             "wire_model": "wire-gpt", "effort": "high"}
        result = chat.send("demo", SID, MID, TEXT,
                           selection=self.selection(catalog["catalog_id"], effort="high"))
        self.assertEqual(result, {"status": "accepted", "message_id": MID, "turn_id": TURN})
        self.assertEqual(len(reserved), 1)
        start = self.rpc.starts()[0]
        self.assertEqual(set(start), {"threadId", "input", "clientUserMessageId", "model", "effort"})
        self.assertEqual((start["model"], start["effort"]), ("wire-gpt", "high"))
        self.assertNotIn("collaborationMode", start)
        self.assertNotEqual(start["model"], "ui-gpt")
        self.assertEqual([(method, transport, context) for method, _params, transport, context, _timeout in self.rpc.fenced_calls],
                         [("thread/resume", 3, 7), ("turn/start", 3, 7)])
        path, record = self.record_for()
        self.assertEqual(set(record), {"schema", "context_id", "root", "sid", "message_id", "digest", "selection", "status", "turn_id", "created"})
        self.assertEqual(record["schema"], 2)
        self.assertEqual(record["context_id"], CONTEXT["context_id"])
        self.assertEqual(record["root"], str(self.project.resolve()))
        self.assertEqual(record["sid"], SID)
        self.assertEqual(record["message_id"], MID)
        self.assertEqual(record["selection"], private_selection)
        canonical = json.dumps({"context_id": CONTEXT["context_id"], "root": str(self.project.resolve()),
                                "sid": SID, "text": TEXT, "selection": private_selection},
                               sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertEqual(record["digest"], hashlib.sha256(canonical).hexdigest())
        self.assertNotIn(TEXT, path.read_text(encoding="utf-8"))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(set(result), {"status", "message_id", "turn_id"})
        self.assertNotIn("wire_model", json.dumps(result))
        self.assertNotIn("digest", json.dumps(result))

    def test_explicit_selection_is_exact_nonnull_object_and_rejects_malformed_before_reserve(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        self.rpc.calls.clear()
        self.rpc.fenced_calls.clear()
        valid = self.selection(catalog["catalog_id"])
        malformed = [
            [],
            "selection",
            {"catalog_id": catalog["catalog_id"], "model_id": "ui-gpt"},
            {"catalog_id": catalog["catalog_id"], "effort": "high"},
            {**valid, "wire_model": "wire-gpt"},
            {**valid, "context_id": "a" * 64},
            {**valid, "effort": None},
            {**valid, "catalog_id": None},
            {**valid, "model_id": ""},
            {**valid, "effort": "high\n"},
        ]
        for bad in malformed:
            with self.subTest(selection=bad):
                self.assertEqual(chat.send("demo", SID, MID, TEXT, selection=bad), {"error": "invalid_request"})
        self.assert_no_send_effects()

    def test_unknown_model_and_effort_from_another_pair_are_invalid_before_reservation(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        self.rpc.calls.clear()
        for selection in (self.selection(catalog["catalog_id"], model_id="unknown-ui"),
                          self.selection(catalog["catalog_id"], effort="unsupported")):
            with self.subTest(selection=selection):
                self.assertEqual(chat.send("demo", SID, MID, TEXT, selection=selection), {"error": "invalid_request"})
        self.assert_no_send_effects()

    def test_missing_catalog_is_unavailable_without_automatic_model_list_or_send_effects(self):
        chat = self.chat()
        choice = self.selection("c" * 64)
        self.assertEqual(chat.send("demo", SID, MID, TEXT, selection=choice), {"error": "unavailable"})
        self.assert_no_send_effects()

    def test_expired_catalog_is_stale_before_reservation_and_never_refreshed_by_send(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        self.rpc.calls.clear()
        self.now[0] += 60.001
        self.assertEqual(chat.send("demo", SID, MID, TEXT,
                                   selection=self.selection(catalog["catalog_id"])), {"error": "stale"})
        self.assert_no_send_effects()

    def test_context_generation_change_invalidates_catalog_before_reservation(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        self.rpc.calls.clear()
        self.context["context_generation"] += 1
        self.rpc.active_context_generation = self.context["context_generation"]
        self.assertEqual(chat.send("demo", SID, MID, TEXT,
                                   selection=self.selection(catalog["catalog_id"])), {"error": "stale"})
        self.assert_no_send_effects()

    def test_context_change_during_fresh_thread_proof_is_rechecked_before_reserve(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        self.rpc.calls.clear()
        self.rpc.fenced_calls.clear()
        changed = [False]
        def change_after_read(method, params):
            if method == "thread/read" and not changed[0]:
                changed[0] = True
                self.context["context_generation"] += 1
                self.rpc.active_context_generation = self.context["context_generation"]
        self.rpc.after_response = change_after_read
        result = chat.send("demo", SID, MID, TEXT,
                           selection=self.selection(catalog["catalog_id"]))
        self.assertEqual(result, {"error": "stale"})
        self.assert_no_send_effects()

    def test_same_uuid_exact_replay_uses_receipt_before_expired_catalog_and_has_no_new_effects(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        choice = self.selection(catalog["catalog_id"])
        first = chat.send("demo", SID, MID, TEXT, selection=choice)
        self.assertEqual(first, {"status": "accepted", "message_id": MID, "turn_id": TURN})
        first_path, first_record = self.record_for()
        first_bytes = first_path.read_bytes()
        self.now[0] += 60.001
        self.rpc.pages = {None: RuntimeError("model/list must not run on exact replay")}
        self.rpc.calls.clear()
        self.rpc.fenced_calls.clear()
        restarted_chat = self.chat()
        replay = restarted_chat.send("demo", SID, MID, TEXT, selection=choice)
        self.assertEqual(replay, first)
        self.assertEqual(self.rpc.starts(), [])
        self.assertNotIn("model/list", self.rpc.methods())
        self.assertNotIn("thread/resume", self.rpc.methods())
        self.assertEqual(first_path.read_bytes(), first_bytes)
        self.assertEqual(self.record_for()[1], first_record)

    def test_replay_rejects_changes_to_text_model_effort_catalog_or_inherit_without_resend(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        choice = self.selection(catalog["catalog_id"])
        self.assertEqual(chat.send("demo", SID, MID, TEXT, selection=choice)["status"], "accepted")
        path, original = self.record_for()
        original_bytes = path.read_bytes()
        variants = [
            (TEXT + " changed", choice),
            (TEXT, self.selection(catalog["catalog_id"], model_id="other-ui")),
            (TEXT, self.selection(catalog["catalog_id"], effort="low")),
            (TEXT, self.selection("d" * 64)),
            (TEXT, None),
        ]
        self.rpc.calls.clear()
        for text, selection in variants:
            with self.subTest(text=text, selection=selection):
                self.assertEqual(chat.send("demo", SID, MID, text, selection=selection), {"error": "invalid_request"})
        self.assertEqual(len(self.rpc.starts()), 0)
        self.assertNotIn("thread/resume", self.rpc.methods())
        self.assertNotIn("model/list", self.rpc.methods())
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertEqual(self.record_for()[1], original)

    def test_turn_start_uncertainty_is_delivery_unknown_and_exact_replay_never_retries(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        choice = self.selection(catalog["catalog_id"])
        self.rpc.start_error = TimeoutError("synthetic uncertain dispatch")
        first = chat.send("demo", SID, MID, TEXT, selection=choice)
        self.assertEqual(first, {"status": "delivery_unknown", "message_id": MID, "turn_id": None})
        path, record = self.record_for()
        self.assertEqual(record["status"], "delivery_unknown")
        first_bytes = path.read_bytes()
        self.now[0] += 60.001
        self.rpc.calls.clear()
        replay = self.chat().send("demo", SID, MID, TEXT, selection=choice)
        self.assertEqual(replay, first)
        self.assertEqual(self.rpc.starts(), [])
        self.assertNotIn("model/list", self.rpc.methods())
        self.assertNotIn("thread/resume", self.rpc.methods())
        self.assertEqual(path.read_bytes(), first_bytes)

    def test_generation_change_after_reservation_never_falls_back_or_retries_on_new_scope(self):
        chat = self.chat()
        catalog = self.catalog(chat)
        self.rpc.calls.clear()
        self.rpc.fenced_calls.clear()
        changed = [False]
        def change_after_resume(method, params):
            if method == "thread/resume" and not changed[0]:
                changed[0] = True
                self.context["transport_generation"] += 1
                self.rpc.active_transport_generation = self.context["transport_generation"]
        self.rpc.after_response = change_after_resume
        result = chat.send("demo", SID, MID, TEXT,
                           selection=self.selection(catalog["catalog_id"]))
        self.assertEqual(result, {"status": "delivery_unknown", "message_id": MID, "turn_id": None})
        self.assertEqual(len(self.receipt_paths()), 1, "reservation remains after post-reserve scope loss")
        self.assertEqual(self.record_for()[1]["status"], "delivery_unknown")
        self.assertEqual(self.rpc.starts(), [], "changed captured socket must never receive turn/start fallback")
        self.assertEqual([name for name, _params in self.rpc.calls if name == "turn/start"], [])
        self.assertEqual([(method, transport, context) for method, _params, transport, context, _timeout in self.rpc.fenced_calls],
                         [("thread/resume", 3, 7)])

    def test_schema1_legacy_receipt_accepts_inherit_but_rejects_explicit_selection(self):
        catalog_chat = self.chat()
        catalog = self.catalog(catalog_chat)
        legacy_chat = self.chat(require_selection=False)
        self.assertEqual(legacy_chat.send("demo", SID, MID, TEXT)["status"], "accepted")
        path, prior = self.record_for()
        legacy = {key: prior[key] for key in ("root", "sid", "message_id", "status", "turn_id", "created") if key in prior}
        legacy["digest"] = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
        path.write_text(json.dumps(legacy, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        before = len(self.rpc.starts())
        self.assertEqual(self.chat(require_selection=False).send("demo", SID, MID, TEXT)["status"], "accepted")
        self.assertEqual(len(self.rpc.starts()), before)
        explicit = self.chat()
        self.assertEqual(explicit.send("demo", SID, MID, TEXT,
                                       selection=self.selection(catalog["catalog_id"])), {"error": "invalid_request"})
        self.assertEqual(len(self.rpc.starts()), before)

    def test_unknown_schema_and_corrupt_receipt_fail_closed_without_retry(self):
        chat = self.chat(require_selection=False)
        self.assertEqual(chat.send("demo", SID, MID, TEXT)["status"], "accepted")
        path, record = self.record_for()
        record["schema"] = 99
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self.chat(require_selection=False).send("demo", SID, MID, TEXT), {"error": "unavailable"})
        path.write_text("{corrupt", encoding="utf-8")
        self.assertEqual(self.chat(require_selection=False).send("demo", SID, MID, TEXT), {"error": "unavailable"})
        self.assertEqual(len(self.rpc.starts()), 1)


if __name__ == "__main__":
    unittest.main()
