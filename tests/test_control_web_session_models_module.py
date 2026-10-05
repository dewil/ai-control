"""Synthetic INV-WSESS-24 tests derived from the frozen public spec only."""
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from test_control_web_session_chat_contract import SID, feature

CONTEXT = {
    "schema": 1,
    "vendor": "codex",
    "context_kind": "legacy_unbound",
    "context_id": "a" * 64,
    "transport_generation": 3,
    "context_generation": 7,
    "native_version": "0.160.0",
}


def native_model(model_id="gpt-ui", wire="gpt-wire", **overrides):
    row = {
        "id": model_id,
        "model": wire,
        "displayName": "Synthetic model",
        "description": "Synthetic catalog fixture",
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


class ModelRPC:
    """Only records synthetic method calls; never connects to native services."""
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.pages = {None: {"data": [native_model()], "nextCursor": None}}
        self.thread_id = SID
        self.thread_root = root
    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method in ("thread/read", "thread/resume"):
            return {"thread": {"id": self.thread_id, "cwd": str(self.thread_root)}}
        if method == "model/list":
            return self.pages[params.get("cursor")]
        raise AssertionError("Unexpected synthetic RPC: " + method)
    def methods(self):
        return [method for method, _ in self.calls]
    def model_calls(self):
        return [params for method, params in self.calls if method == "model/list"]


class SessionModelsModule(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, "_control_web_sessions")
        self.tmp = tempfile.TemporaryDirectory(prefix="web-session-models-", dir="/var/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.root = self.base / "project"
        self.root.mkdir(mode=0o700)
        self.rpc = ModelRPC(self.root)
        self.now = [100.0]
        self.context = dict(CONTEXT)
        self.get_context = lambda: dict(self.context)

    def chat(self):
        cls = self.module.SessionChat
        self.assertTrue(callable(getattr(cls, "models", None)),
                        "SessionChat.models(project, sid) is required by INV-WSESS-24")
        params = inspect.signature(cls).parameters
        self.assertIn("model_context", params,
                      "SessionChat must expose the trusted model_context getter seam")
        self.assertIn("model_clock", params,
                      "SessionChat must expose the model_clock seam")
        def resolve(alias):
            if alias != "demo":
                raise ValueError("synthetic invalid project")
            return str(self.root)
        return cls(self.rpc, resolve, lambda: ["demo"], str(self.base / "receipts"),
                   model_context=self.get_context, model_clock=lambda: self.now[0])

    def unavailable(self, reason):
        result = self.chat().models("demo", SID)
        self.assertEqual(result["selection_support"], "unavailable")
        self.assertEqual(result["reason"], reason)
        self.assertIsNone(result["catalog_id"])
        self.assertEqual(result["expires_in_ms"], 0)
        self.assertEqual(result["rows"], [])

    def test_available_catalog_is_exact_safe_projection_and_fixed_first_page_params(self):
        self.rpc.pages = {None: {"data": [native_model(), native_model("hidden", hidden=True)], "nextCursor": None}}
        result = self.chat().models("demo", SID)
        self.assertEqual(set(result), {"schema", "vendor", "context_kind", "selection_support", "reason", "catalog_id", "expires_in_ms", "rows"})
        self.assertEqual((result["schema"], result["vendor"], result["context_kind"]), (1, "codex", "legacy_unbound"))
        self.assertEqual((result["selection_support"], result["reason"]), ("available", None))
        self.assertRegex(result["catalog_id"], r"^[0-9a-f]{64}$")
        self.assertGreaterEqual(result["expires_in_ms"], 1)
        self.assertLessEqual(result["expires_in_ms"], 60000)
        self.assertEqual(result["rows"], [{"id": "gpt-ui", "label": "Synthetic model", "efforts": ["low", "high"], "default_effort": "low", "is_default": True}])
        self.assertEqual(self.rpc.model_calls(), [{"limit": 64, "includeHidden": False}])
        self.assertNotIn("gpt-wire", json.dumps(result))
        self.assertEqual(self.rpc.methods().count("thread/resume"), 0)
        self.assertFalse({"thread/turns/list", "turn/start"} & set(self.rpc.methods()))

    def test_full_uuid_and_project_root_thread_proof_precede_catalog_rpc(self):
        chat = self.chat()
        self.assertEqual(chat.models("demo", SID)["selection_support"], "available")
        self.assertIn(("thread/read", {"threadId": SID, "includeTurns": False}), self.rpc.calls)
        self.assertLess(self.rpc.methods().index("thread/read"), self.rpc.methods().index("model/list"))
        before = len(self.rpc.model_calls())
        for bad_sid in (SID[:8], SID.upper()):
            self.assertEqual(chat.models("demo", bad_sid), {"error": "invalid_request"})
        self.assertEqual(len(self.rpc.model_calls()), before)
        self.rpc.thread_id = "44444444-4444-4444-8444-444444444444"
        result = self.chat().models("demo", SID)
        self.assertEqual(result, {"error": "stale"})
        self.assertNotIn("model/list", self.rpc.methods())

    def test_unknown_vendor_is_unavailable_and_does_not_probe_native_catalog(self):
        self.context["vendor"] = "unknown-provider"
        self.unavailable("unsupported_vendor")
        self.assertNotIn("model/list", self.rpc.methods())

    def test_unverified_bound_context_never_falls_back_to_legacy_catalog(self):
        for kind in ("unverified_bound", "verified_bound"):
            with self.subTest(kind=kind):
                self.context.update(vendor="codex", context_kind=kind, context_id="b" * 64)
                self.rpc.calls.clear()
                self.unavailable("unverified_context")
                self.assertNotIn("model/list", self.rpc.methods())

    def test_unknown_or_malformed_native_version_is_unavailable_without_probe(self):
        for version in (None, "0.160.1", "unknown"):
            with self.subTest(version=version):
                self.context["native_version"] = version
                self.rpc.calls.clear()
                self.unavailable("unsupported_capability")
                self.assertNotIn("model/list", self.rpc.methods())

    def test_malformed_context_schema_generation_or_identity_is_unavailable(self):
        bad_contexts = [
            {**CONTEXT, "schema": True},
            {**CONTEXT, "context_id": "not-a-digest"},
            {**CONTEXT, "transport_generation": True},
            {**CONTEXT, "context_generation": -1},
            {**CONTEXT, "vendor": "codex", "context_kind": "legacy_unbound", "native_version": "0.160.0", "transport_generation": 1},
        ]
        for bad in bad_contexts:
            with self.subTest(bad=bad):
                self.context = dict(bad)
                self.rpc.calls.clear()
                self.unavailable("unverified_context")
                self.assertNotIn("model/list", self.rpc.methods())

    def test_cursor_pagination_uses_exact_params_and_projects_all_pages(self):
        self.rpc.pages = {
            None: {"data": [native_model("one", "wire-one")], "nextCursor": "opaque-next"},
            "opaque-next": {"data": [native_model("two", "wire-two", isDefault=False)], "nextCursor": None},
        }
        result = self.chat().models("demo", SID)
        self.assertEqual([row["id"] for row in result["rows"]], ["one", "two"])
        self.assertEqual(self.rpc.model_calls(), [
            {"limit": 64, "includeHidden": False},
            {"limit": 64, "includeHidden": False, "cursor": "opaque-next"},
        ])
        self.assertNotIn("wire-one", json.dumps(result))
        self.assertNotIn("wire-two", json.dumps(result))

    def test_page_loop_returns_unavailable_without_partial_rows(self):
        self.rpc.pages = {None: {"data": [native_model()], "nextCursor": "same"}, "same": {"data": [native_model("two")], "nextCursor": "same"}}
        self.unavailable("catalog_unavailable")
        self.assertLessEqual(len(self.rpc.model_calls()), 3)

    def test_page_limit_is_sixteen_and_never_returns_partial_catalog(self):
        self.rpc.pages = {None: {"data": [], "nextCursor": "c0"}}
        for i in range(16):
            self.rpc.pages[f"c{i}"] = {"data": [native_model(f"row-{i}")], "nextCursor": f"c{i+1}"}
        self.unavailable("catalog_unavailable")
        self.assertEqual(len(self.rpc.model_calls()), 16)
        self.assertTrue(all(call["limit"] == 64 and call["includeHidden"] is False for call in self.rpc.model_calls()))

    def test_total_native_row_limit_is_checked_before_hidden_filtering(self):
        self.rpc.pages = {None: {"data": [native_model(f"row-{i}", hidden=True) for i in range(257)], "nextCursor": None}}
        self.unavailable("catalog_unavailable")
        self.assertEqual(len(self.rpc.model_calls()), 1)

    def test_encoded_native_json_budget_rejects_oversize_without_partial_rows(self):
        row = native_model()
        row["description"] = "x" * (1024 * 1024)
        self.rpc.pages = {None: {"data": [row], "nextCursor": None}}
        self.unavailable("catalog_unavailable")

    def test_duplicate_ui_or_wire_identifiers_reject_whole_catalog(self):
        for rows in ([native_model("same", "wire-1"), native_model("same", "wire-2")],
                     [native_model("ui-1", "same-wire"), native_model("ui-2", "same-wire")]):
            with self.subTest(rows=rows):
                self.rpc.pages = {None: {"data": rows, "nextCursor": None}}
                self.unavailable("catalog_unavailable")

    def test_all_rows_validate_hidden_and_effort_default_capabilities(self):
        invalid_rows = [
            native_model(hidden=True, displayName=object()),
            native_model(supportedReasoningEfforts=[]),
            native_model(supportedReasoningEfforts=[{"reasoningEffort": "low", "description": "x"}, {"reasoningEffort": "low", "description": "y"}]),
            native_model(defaultReasoningEffort="unsupported"),
            native_model(isDefault=1),
            native_model(model="wirevalue"),
        ]
        for row in invalid_rows:
            with self.subTest(row=row):
                self.rpc.pages = {None: {"data": [row], "nextCursor": None}}
                self.unavailable("catalog_unavailable")

    def test_empty_catalog_has_specific_unavailable_reason(self):
        self.rpc.pages = {None: {"data": [], "nextCursor": None}}
        self.unavailable("empty_catalog")

    def test_cache_ttl_refresh_and_context_generation_are_isolated(self):
        chat = self.chat()
        first = chat.models("demo", SID)
        calls = len(self.rpc.model_calls())
        self.assertEqual(chat.models("demo", SID)["catalog_id"], first["catalog_id"])
        self.assertEqual(len(self.rpc.model_calls()), calls)
        self.now[0] += 60.001
        refreshed = chat.models("demo", SID)
        self.assertNotEqual(refreshed["catalog_id"], first["catalog_id"])
        self.context["context_generation"] += 1
        changed = chat.models("demo", SID)
        self.assertNotEqual(changed["catalog_id"], refreshed["catalog_id"])
        for index in range(1, 34):
            self.context.update(context_id=f"{index:064x}", context_generation=index)
            self.assertEqual(chat.models("demo", SID)["selection_support"], "available")
        self.context.update(context_id=CONTEXT["context_id"], context_generation=CONTEXT["context_generation"] + 1)
        evicted = chat.models("demo", SID)
        self.assertNotEqual(evicted["catalog_id"], changed["catalog_id"])
        self.assertEqual(len(self.rpc.model_calls()), calls + 36)

    def test_cache_rechecks_project_and_thread_proof_on_each_read(self):
        chat = self.chat()
        self.assertEqual(chat.models("demo", SID)["selection_support"], "available")
        self.rpc.thread_id = "44444444-4444-4444-8444-444444444444"
        before = len(self.rpc.model_calls())
        self.assertEqual(chat.models("demo", SID), {"error": "stale"})
        self.assertEqual(len(self.rpc.model_calls()), before)
        self.assertGreaterEqual(self.rpc.methods().count("thread/read"), 2)


if __name__ == "__main__":
    unittest.main()
