"""Source-blind contract tests for the read-only AttentionOverview composer.

Fixtures below are synthetic and perform no filesystem, native, or network IO.
"""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "_control_web_attention.py"
_spec = importlib.util.spec_from_file_location("_control_web_attention", MODULE_PATH)
_module = importlib.util.module_from_spec(_spec) if _spec else None
if _spec and _spec.loader and MODULE_PATH.exists():
    _spec.loader.exec_module(_module)
else:
    _module = None

I32, E32, H64 = "b" * 32, "c" * 32, "a" * 64
SID = "11111111-1111-4111-8111-111111111111"
QID = "22222222-2222-4222-8222-222222222222"
ROOT = "/var/tmp/attention-synthetic"
NOW = 1_700_000_000


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class FakeView:
    def __init__(self, allowed=True, current=True):
        self.allowed, self.is_current = allowed, current
        self.calls = []
        self.snapshot_value = {
            "schema": 1, "principal": "operator", "epoch": E32,
            "revision": 1, "registry_epoch": I32, "registry_revision": 1,
            "context_id": H64, "route_id": H64, "route_epoch": I32,
            "route_revision": 1, "owner_only": True,
        }
        self.binding = {"project": "demo", "root": ROOT,
                        "registry_epoch": I32, "registry_revision": 1}

    def snapshot(self, *, deadline):
        self.calls.append("snapshot")
        return dict(self.snapshot_value)

    def resolve_project(self, project, view_snapshot, *, deadline):
        self.calls.append("resolve")
        return dict(self.binding) if project == "demo" else None

    def authorize(self, project_binding, view_snapshot, *, deadline):
        self.calls.append("authorize")
        return self.allowed and project_binding == self.binding

    def current(self, view_snapshot, *, deadline):
        self.calls.append("current")
        return self.is_current


class FakeSource:
    def __init__(self, records, *, state="fresh", complete=True, epoch=I32,
                 revision=1, reason=None, source="task_registry", coverage=None):
        self.calls = 0
        self.value = {
            "schema": 1, "source": source, "epoch": epoch,
            "revision": revision, "observed_at": NOW if epoch else None,
            "state": state, "complete": complete, "reason": reason,
            "coverage": coverage or {
                "scope": "task_registry", "registry_epoch": I32,
                "registry_revision": 1, "context_ids": [], "route_ids": [],
                "session_set_revision": None, "global_complete": True,
                "supported_methods": [],
            },
            "records": records,
        }

    def snapshot(self, *, deadline):
        self.calls += 1
        return self.value


def question(*, kind="info", status="open", answered=False, delivery=False,
             blocking="unknown"):
    return {"qid": QID, "kind": kind, "status": status,
            "answered": answered, "pending_delivery": delivery,
            "blocking": blocking, "native_key": None}


def task(*, engine="claude", linked=False, questions=None, result=None,
         registry_id=H64, agent="synthetic-task", incarnation=I32,
         label="Synthetic task", project="demo"):
    binding = {"project": project, "root": ROOT, "registry_epoch": I32,
               "registry_revision": 1}
    session = None
    if linked:
        session = {"project_binding": binding, "context_id": H64,
                   "context_kind": "legacy_unbound", "route_id": H64,
                   "route_epoch": I32, "route_revision": 1, "vendor": "codex",
                   "sid": SID, "label": "Synthetic Codex",
                   "context_label": "Synthetic context", "identity_epoch": I32,
                   "identity_generation": 1}
    return {"registry_id": registry_id, "agent": agent, "incarnation": incarnation,
            "generation": 1, "attempt_id": "attempt-1", "project_binding": binding,
            "session_binding": session, "label": label, "engine": engine,
            "questions": list(questions or []), "result": result}


def activity_for(record, *, run_state="executing", blocked=False,
                 turn_status="inProgress"):
    return {"session_binding": record["session_binding"], "turn_id": "turn-1",
            "turn_status": turn_status, "run_state": run_state, "blocked": blocked,
            "task_key": digest({"kind": "attention_task", "registry_id": record["registry_id"],
                                "agent": record["agent"], "incarnation": record["incarnation"]}),
            "task_generation": 1, "attempt_id": "attempt-1"}


def make_overview(records, *, view=None, task_source=None, activity_source=None,
                  callback_source=None):
    if _module is None:
        return None
    view = view or FakeView()
    task_source = task_source or FakeSource(records)
    return _module.AttentionOverview(
        task_source, activity_source=activity_source,
        callback_source=callback_source, view=view,
        monotonic=lambda: 0.0, wall_clock=lambda: NOW,
    ), view, task_source


class AttentionOverviewContractTests(unittest.TestCase):
    def overview(self, *args, **kwargs):
        self.assertIsNotNone(_module,
            "AttentionOverview contract RED: bin/_control_web_attention.py is missing")
        return make_overview(*args, **kwargs)

    def test_view_grant_is_checked_before_any_source_export(self):
        source = FakeSource([task(questions=[question()])])
        view = FakeView(allowed=False)
        overview, _, _ = self.overview([], view=view, task_source=source)
        result = overview.snapshot()
        self.assertEqual(source.calls, 0, "denied view must fail before source export")
        self.assertEqual(result, {"error": "forbidden"})
        self.assertNotIn("Synthetic task", repr(result))

    def test_claude_task_stays_unlinked_and_does_not_inflate_session_counts(self):
        record = task(engine="claude", linked=True, questions=[question()])
        overview, _, _ = self.overview([record])
        result = overview.snapshot()
        self.assertEqual(result["pool"]["known_sessions"], 0)
        self.assertEqual(result["pool"]["question"], 0)
        self.assertEqual(len(result["unlinked_tasks"]), 1)
        self.assertEqual(len(result["reasons"]), 1)
        reason = result["reasons"][0]
        self.assertIsNone(reason["session_key"])
        self.assertIsNotNone(reason["task_key"])
        self.assertEqual(reason["target"]["kind"], "task")

    def test_fresh_exact_execution_and_blocking_priority_preserve_reasons(self):
        record = task(engine="codex", linked=True,
                      questions=[question(kind="permission", blocking="current")])
        record["registry_id"] = "d" * 64
        record["agent"] = "codex-task"
        running = activity_for(record)
        activity = FakeSource([running], source="activity", coverage={
            "scope": "declared_sessions", "registry_epoch": I32,
            "registry_revision": 1, "context_ids": [H64], "route_ids": [H64],
            "session_set_revision": E32, "global_complete": False,
            "supported_methods": [],
        })
        overview, _, _ = self.overview([record], activity_source=activity)
        result = overview.snapshot()
        self.assertEqual(result["pool"]["decision"], 1)
        self.assertEqual(result["pool"]["running"], 0,
                         "current blocked execution cannot count as running")
        self.assertEqual(result["sessions"][0]["primary_state"], "decision")
        self.assertIn("waiting", result["sessions"][0]["activity_state"])
        self.assertEqual(len(result["reasons"]), 1)

        record["questions"][0]["blocking"] = "independent"
        activity.value["records"] = [activity_for(record)]
        result = overview.snapshot()
        self.assertEqual(result["pool"]["running"], 1,
                         "independent question must retain separately proved execution")
        self.assertEqual(result["pool"]["decision"], 1)
        self.assertEqual(result["sessions"][0]["primary_state"], "decision")

    def test_answer_delivery_and_finalized_result_have_distinct_durable_reasons(self):
        delivery = question(kind="info", status="closed", answered=True,
                            delivery=True)
        result_row = {"generation": "1234abcd", "state": "requested",
                      "finalized": True, "result_key": "e" * 64}
        overview, _, _ = self.overview([task(questions=[delivery], result=result_row)])
        result = overview.snapshot()
        self.assertEqual(result["pool"]["known_sessions"], 0)
        self.assertEqual(result["pool"]["question"], 0)
        kinds = {reason["kind"] for reason in result["reasons"]}
        self.assertEqual(kinds, {"delivery_pending", "completed"})
        self.assertEqual(len(result["unlinked_tasks"][0]["reason_ids"]), 2)
        self.assertFalse(result["complete"])

    def test_stale_source_retains_verified_reason_as_stale_without_resolving_it(self):
        source = FakeSource([task(questions=[question()])])
        overview, _, _ = self.overview([], task_source=source)
        first = overview.snapshot()
        self.assertEqual(len(first["reasons"]), 1)
        source.value.update(state="disconnected", complete=False,
                            reason="disconnected", records=[])
        second = overview.snapshot()
        self.assertEqual({r["reason_id"] for r in second["reasons"]},
                         {r["reason_id"] for r in first["reasons"]})
        self.assertEqual(second["reasons"][0]["state"], "stale")
        self.assertFalse(second["complete"])
        self.assertEqual(second["sources"]["task_registry"]["state"], "disconnected")
        source.value.update(state="fresh", complete=True, reason=None,
                            records=[])
        third = overview.snapshot()
        self.assertEqual(third["reasons"], [],
                         "only a complete fresh omission resolves a durable reason")

    def test_unknown_project_binding_is_omitted_before_labels_and_counts(self):
        record = task(questions=[question()], label="Sensitive synthetic label")
        record["project_binding"]["root"] = "/var/tmp/wrong-root"
        overview, _, _ = self.overview([record])
        result = overview.snapshot()
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["unlinked_tasks"], [])
        self.assertEqual(result["pool"]["known_sessions"], 0)
        self.assertNotIn("Sensitive synthetic label", repr(result))
        self.assertEqual(result["sources"]["task_registry"]["reason"],
                         "binding_incomplete")

    def test_plain_integer_revisions_and_final_view_fence_are_enforced(self):
        source = FakeSource([task(questions=[question()])])
        source.value["revision"] = True
        overview, _, _ = self.overview([], task_source=source)
        result = overview.snapshot()
        self.assertEqual(result.get("error"), "invalid_source")
        self.assertNotIn("Synthetic task", repr(result))

        source.value["revision"] = 1
        overview, view, _ = self.overview([task(questions=[question()])],
                                          task_source=source)
        view.is_current = False
        stale_view = overview.snapshot()
        self.assertEqual(stale_view, {"error": "stale"})
        self.assertNotIn("reasons", stale_view)


if __name__ == "__main__":
    unittest.main()
