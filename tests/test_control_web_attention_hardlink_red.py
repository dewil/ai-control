"""Focused INV-WATTN-01/02/03 hard-link boundary regressions (synthetic only)."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BROKER_PATH = ROOT / "bin" / "_control_web_broker.py"
COMPOSER_PATH = ROOT / "bin" / "_control_web_attention.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


broker = load_module("_attention_hardlink_broker", BROKER_PATH)
composer = load_module("_attention_hardlink_composer", COMPOSER_PATH)

INC = "a" * 32
QID = "11111111-1111-4111-8111-111111111111"
DEADLINE = 10.0
NOW = 1_800_000_000.0


def put_json(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    path.chmod(mode)


def valid_control():
    return {"schema": 1, "seq": 0, "desired": "running", "generation": 1,
            "incarnation": INC, "session_id": None, "started_at": None,
            "deadline_extension_h": 0, "mission_base": None,
            "lease": {"state": "active", "start_attempt_id": "attempt-1",
                      "gen_base": None, "socket": "synthetic.sock", "unit": "synthetic.unit",
                      "main_pid": 123, "pid_start": 456, "granted_at": "2026-10-06T00:00:00Z",
                      "renewed_at": "2026-10-06T00:00:00Z", "ttl_s": 300},
            "acceptance": {"status": "pending", "artifact": None, "verdict_by": None,
                           "checked_at": None, "note": None, "check_job": None, "check_runs": []},
            "attention": None, "hold": None, "handoff": None}


def valid_state():
    return {"schema": 1, "generation": 1, "attempt_id": "attempt-1",
            "phase": "working", "status_line": "synthetic", "agent_claim": "running",
            "claim_artifact": None, "session_id": "synthetic-session",
            "iteration_started_at": "2026-10-06T00:00:00Z",
            "last_progress_at": "2026-10-06T00:00:00Z", "next_wakeup_at": None,
            "iterations": 1, "cost_usd": 0}


class AttentionHardlinkRed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="attention-hardlink-red-", dir="/var/tmp"))
        self.tmp.chmod(0o700)
        self.project = self.tmp / "project"
        self.project.mkdir(mode=0o700)
        self.registry = self.tmp / "registry"
        self.registry.mkdir(mode=0o700)
        self.config = self.tmp / "projects.json"
        self.write_map()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def write_map(self, *, linked=False):
        put_json(self.config, {"demo": str(self.project)})
        if linked:
            second = self.tmp / "projects-alias.json"
            os.link(self.config, second)
            self.assertEqual(self.config.stat().st_nlink, 2)

    def adapter(self):
        self.assertIsNotNone(broker, "frozen public broker module should load")
        names = ("OwnerProjectMap", "OwnerRegisteredGrants", "RegistryAttentionView",
                 "RegistryAttentionSource")
        missing = [name for name in names if not callable(getattr(broker, name, None))]
        self.assertEqual(missing, [], "hardlink regression requires frozen public adapter classes")
        self.assertIsNotNone(composer, "frozen public composer module should load")
        return tuple(getattr(broker, name) for name in names)

    def view_source(self):
        ProjectMap, Grants, View, Source = self.adapter()
        projects = ProjectMap(str(self.config), monotonic=lambda: 1.0)
        view = View(str(self.registry), projects=projects,
                    grants=Grants(owner_only=True), monotonic=lambda: 1.0)
        source = Source(view, monotonic=lambda: 1.0, wall_clock=lambda: NOW)
        return view, source

    def add_task(self, name, *, hardlink=None):
        agent = self.registry / name
        agent.mkdir(mode=0o700)
        spec = {"type": "task", "engine": "claude", "project": str(self.project),
                "name": "Synthetic registry task"}
        put_json(agent / "spec.yaml", spec)
        put_json(agent / "control.json", valid_control())
        put_json(agent / "state.1.json", valid_state())
        if hardlink is not None:
            os.link(agent / hardlink, self.tmp / (name + "-second-link"))
            self.assertEqual((agent / hardlink).stat().st_nlink, 2)
        self.assertGreaterEqual(self.project.stat().st_nlink, 2)
        self.assertGreaterEqual(self.registry.stat().st_nlink, 2)
        return agent

    def test_hardlinked_owner_project_map_fails_view_first_without_source_call(self):
        self.write_map(linked=True)
        self.add_task("task-map-unreachable")
        ProjectMap, Grants, View, _ = self.adapter()
        projects = ProjectMap(str(self.config), monotonic=lambda: 1.0)
        view = View(str(self.registry), projects=projects,
                    grants=Grants(owner_only=True), monotonic=lambda: 1.0)
        calls = []
        class Source:
            def snapshot(inner, *, deadline):
                calls.append("source")
                return {"schema": 1}
        overview = composer.AttentionOverview(Source(), view=view,
                    monotonic=lambda: 1.0, wall_clock=lambda: NOW)
        result = overview.snapshot()
        self.assertEqual((result, calls), ({"error": "unavailable"}, []),
                         "INV-WATTN-01/03: linked map is unavailable before source call")

    def test_hardlinked_task_spec_or_control_excludes_whole_record(self):
        for index, filename in enumerate(("spec.yaml", "control.json")):
            with self.subTest(filename=filename):
                name = "task-linked-" + str(index)
                agent = self.add_task(name, hardlink=filename)
                view, source = self.view_source()
                view.snapshot(deadline=DEADLINE)
                snapshot = source.snapshot(deadline=DEADLINE)
                records = snapshot["records"]
                has_untrusted_label = any(record.get("label") == "Synthetic registry task"
                                           for record in records)
                self.assertEqual((snapshot["state"], snapshot["reason"], snapshot["complete"],
                                  len(records), has_untrusted_label),
                                 ("incomplete", "invalid_source", False, 0, False),
                                 "INV-WATTN-02: linked metadata excludes record and label")
                self.assertFalse(snapshot["coverage"]["global_complete"])
                self.assertNotIn("Synthetic registry task", repr(snapshot),
                                 "untrusted label/reasons/counts cannot leak from linked metadata")
                shutil.rmtree(agent)

    def test_warm_hardlink_failure_retains_only_authorized_stale_reason_then_revocation_clears(self):
        # One persistent composer exercises public retention and current-view reauthorization.
        agent = self.add_task("task-warm-cache")
        put_json(agent / "questions" / (QID + ".json"),
                 {"qid": QID, "kind": "info", "status": "open"})
        view, source = self.view_source()
        overview = composer.AttentionOverview(source, view=view,
                    monotonic=lambda: 1.0, wall_clock=lambda: NOW)

        first = overview.snapshot()
        self.assertEqual(len(first["reasons"]), 1)
        prior_id = first["reasons"][0]["reason_id"]
        self.assertEqual(first["reasons"][0]["state"], "pending")

        os.link(agent / "control.json", self.tmp / "warm-cache-control-link")
        self.assertEqual((agent / "control.json").stat().st_nlink, 2)
        second = overview.snapshot()
        registry_source = second["sources"]["task_registry"]
        self.assertEqual((registry_source["state"], registry_source["reason"],
                          registry_source["complete"],
                          [reason["reason_id"] for reason in second["reasons"]],
                          [reason["state"] for reason in second["reasons"]], second["complete"]),
                         ("incomplete", "invalid_source", False, [prior_id], ["stale"], False),
                         "unsafe source must retain only the prior authorized reason as stale")

        # Current project authority is now revoked. The composer may safely refuse
        # the whole view or return an empty protected projection, but cannot retain
        # cached TASK labels/reasons under the earlier authorization.
        put_json(self.config, {})
        third = overview.snapshot()
        if "error" in third:
            self.assertIn(third["error"], ("stale", "unavailable"))
        else:
            self.assertEqual(third["reasons"], [])
            self.assertEqual(third["unlinked_tasks"], [])
            self.assertEqual(third["pool"], {"known_sessions": 0, "running": 0,
                             "decision": 0, "question": 0, "completed": 0})


if __name__ == "__main__":
    unittest.main()
