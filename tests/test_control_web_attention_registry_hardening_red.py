"""Source-blind RED cases for registry metadata hardening (synthetic files only)."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BROKER_PATH = ROOT / "bin" / "_control_web_broker.py"
_spec = importlib.util.spec_from_file_location("_attention_hardening_broker", BROKER_PATH)
_broker = importlib.util.module_from_spec(_spec) if _spec else None
if _spec and _spec.loader:
    _spec.loader.exec_module(_broker)
else:
    _broker = None

INC = "a" * 32
DEADLINE = 10.0


def put(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    path.chmod(mode)


def control(generation=1):
    return {"schema": 1, "seq": 0, "desired": "running", "generation": generation,
            "incarnation": INC, "session_id": None, "started_at": None,
            "deadline_extension_h": 0, "mission_base": None,
            "lease": {"state": "active", "start_attempt_id": "attempt-1",
                      "gen_base": None, "socket": "synthetic.sock", "unit": "synthetic.unit",
                      "main_pid": 123, "pid_start": 456, "granted_at": "2026-10-06T00:00:00Z",
                      "renewed_at": "2026-10-06T00:00:00Z", "ttl_s": 300},
            "acceptance": {"status": "pending", "artifact": None, "verdict_by": None,
                           "checked_at": None, "note": None, "check_job": None, "check_runs": []},
            "attention": None, "hold": None, "handoff": None}


def state(attempt="attempt-1"):
    return {"schema": 1, "generation": 1, "attempt_id": attempt, "phase": "working",
            "status_line": "synthetic", "agent_claim": "running", "claim_artifact": None,
            "session_id": "synthetic-session", "iteration_started_at": "2026-10-06T00:00:00Z",
            "last_progress_at": "2026-10-06T00:00:00Z", "next_wakeup_at": None,
            "iterations": 1, "cost_usd": 0}


class RegistryHardeningRed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="attention-hardening-red-", dir="/var/tmp"))
        self.tmp.chmod(0o700)
        self.project = self.tmp / "project"
        self.project.mkdir(mode=0o700)
        self.registry = self.tmp / "registry"
        self.registry.mkdir(mode=0o700)
        self.config = self.tmp / "projects.json"
        put(self.config, {"demo": str(self.project)})
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def seams(self):
        self.assertIsNotNone(_broker, "public broker module should load")
        names = ("OwnerProjectMap", "OwnerRegisteredGrants", "RegistryAttentionView",
                 "RegistryAttentionSource")
        missing = [n for n in names if not callable(getattr(_broker, n, None))]
        self.assertEqual(missing, [], "registry-attention hardening RED: missing public seam(s): " +
                         ", ".join(missing))
        return tuple(getattr(_broker, n) for n in names)

    def source(self):
        ProjectMap, Grants, View, Source = self.seams()
        projects = ProjectMap(str(self.config), monotonic=lambda: 1.0)
        view = View(str(self.registry), projects=projects,
                    grants=Grants(owner_only=True), monotonic=lambda: 1.0)
        source = Source(view, monotonic=lambda: 1.0, wall_clock=lambda: 1_800_000_000.0)
        return view, source

    def add_task(self, ctl=None, st=None):
        agent = self.registry / "synthetic-task"
        agent.mkdir(mode=0o700)
        put(agent / "spec.yaml", {"type": "task", "engine": "claude",
                                  "project": str(self.project), "name": "Synthetic"})
        put(agent / "control.json", ctl if ctl is not None else control())
        if st is not None:
            put(agent / "state.1.json", st)
        else:
            put(agent / "state.1.json", state())
        return agent

    def test_completed_lease_preserves_only_matching_current_attempt(self):
        self.add_task()
        view, source = self.source()
        view.snapshot(deadline=DEADLINE)
        baseline = source.snapshot(deadline=DEADLINE)
        self.assertEqual(len(baseline["records"]), 1)

        agent = self.registry / "synthetic-task"
        ctl = control()
        ctl["lease"]["state"] = "none"
        put(agent / "control.json", ctl)
        view.snapshot(deadline=DEADLINE)
        retained = source.snapshot(deadline=DEADLINE)
        self.assertEqual(len(retained["records"]), 1,
                         "completed lease retains same generation/attempt provenance")
        self.assertEqual(retained["records"][0]["attempt_id"], "attempt-1")

        put(agent / "state.1.json", state("different-attempt"))
        view.snapshot(deadline=DEADLINE)
        foreign = source.snapshot(deadline=DEADLINE)
        self.assertFalse(foreign["complete"])
        self.assertIn(foreign["reason"], ("binding_incomplete", "foreign_writer"))
        self.assertEqual(foreign["records"], [])

        (agent / "state.1.json").unlink()
        view.snapshot(deadline=DEADLINE)
        missing = source.snapshot(deadline=DEADLINE)
        self.assertFalse(missing["complete"])
        self.assertEqual(missing["records"], [])

    def test_optional_provider_metadata_is_validated_not_ignored(self):
        # Public ai-agent-io validates these optional fields when present.
        self.add_task()
        agent = self.registry / "synthetic-task"
        for field, invalid in (("provider_binding", {"unexpected": True}),
                               ("provider_context", {"unexpected": True})):
            with self.subTest(field=field):
                ctl = control()
                ctl[field] = invalid
                put(agent / "control.json", ctl)
                view, source = self.source()
                view.snapshot(deadline=DEADLINE)
                snapshot = source.snapshot(deadline=DEADLINE)
                self.assertFalse(snapshot["complete"], field + " validation error cannot be ignored")
                self.assertEqual(snapshot["records"], [])

    def test_control_metadata_strict_types_identity_duplicates_owner_and_symlink(self):
        self.add_task()
        agent = self.registry / "synthetic-task"
        view, source = self.source()
        invalid_controls = []
        for field, value in (("schema", True), ("seq", True), ("generation", True)):
            ctl = control(); ctl[field] = value
            invalid_controls.append((field, json.dumps(ctl, separators=(",", ":"))))
        ctl = control(); del ctl["incarnation"]
        invalid_controls.append(("missing-incarnation", json.dumps(ctl, separators=(",", ":"))))
        raw = json.dumps(control(), separators=(",", ":"))
        invalid_controls.append(("duplicate-key", raw[:-1] + ',"seq":9}'))
        for label, raw in invalid_controls:
            with self.subTest(label=label):
                (agent / "control.json").write_text(raw, encoding="utf-8")
                (agent / "control.json").chmod(0o600)
                view.snapshot(deadline=DEADLINE)
                snapshot = source.snapshot(deadline=DEADLINE)
                self.assertFalse(snapshot["complete"], label)
                self.assertEqual(snapshot["records"], [])
        put(agent / "control.json", control(), mode=0o622)
        view.snapshot(deadline=DEADLINE)
        unsafe_mode = source.snapshot(deadline=DEADLINE)
        self.assertFalse(unsafe_mode["complete"], "owner-writable metadata is rejected")
        self.assertEqual(unsafe_mode["records"], [])
        (agent / "control.json").unlink()
        target = self.tmp / "control-target.json"
        put(target, control())
        (agent / "control.json").symlink_to(target)
        view.snapshot(deadline=DEADLINE)
        symlink = source.snapshot(deadline=DEADLINE)
        self.assertFalse(symlink["complete"], "metadata symlink is rejected")
        self.assertEqual(symlink["records"], [])

    def test_yaml_alias_duplicate_json_from_synthetic_runner_is_rejected(self):
        # The runner is synthetic and returns duplicate JSON object keys so the
        # adapter's strict decoder must reject parser output rather than choose last-wins.
        self.config.write_text("demo: &root " + json.dumps(str(self.project)) +
                               "\nother: *root\n", encoding="utf-8")
        self.config.chmod(0o600)
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return type("Completed", (), {"returncode": 0,
                "stdout": '{"demo":' + json.dumps(str(self.project)) +
                          ',"demo":"/var/tmp/forged"}', "stderr": ""})()
        ProjectMap, _, _, _ = self.seams()
        project_map = ProjectMap(str(self.config), runner=runner, monotonic=lambda: 1.0)
        with self.assertRaises(Exception, msg="duplicate-key JSON emitted for YAML aliases is rejected"):
            project_map.capture(deadline=DEADLINE)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["yq", "-p=yaml", "-o=json", ".", "-"])
        self.assertIs(calls[0][1].get("shell"), False)
        self.assertIs(calls[0][1].get("capture_output"), True)


if __name__ == "__main__":
    unittest.main()
