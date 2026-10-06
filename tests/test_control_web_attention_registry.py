"""Source-blind RED for the owner-only TASK registry attention adapter.

Only synthetic private files are used.  No native RPC, user registry, auth or
production config is read.  Adapter symbols are guarded so an unimplemented
public seam reports an assertion failure instead of an import/fixture error.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BROKER_PATH = ROOT / "bin" / "_control_web_broker.py"
_spec = importlib.util.spec_from_file_location("_registry_attention_broker", BROKER_PATH)
_broker = importlib.util.module_from_spec(_spec) if _spec else None
if _spec and _spec.loader:
    _spec.loader.exec_module(_broker)
else:
    _broker = None

INC = "a" * 32
QID = "11111111-1111-4111-8111-111111111111"
NOW = 1_800_000_000.0
DEADLINE = 10.0


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def put_json(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    path.chmod(mode)


def valid_control(generation=1, incarnation=INC):
    return {
        "schema": 1, "seq": 0, "desired": "running", "generation": generation,
        "incarnation": incarnation, "session_id": None, "started_at": None,
        "deadline_extension_h": 0, "mission_base": None,
        "lease": {"state": "active", "start_attempt_id": "attempt-1",
                  "gen_base": None, "socket": "synthetic.sock", "unit": "synthetic.unit",
                  "main_pid": 123, "pid_start": 456, "granted_at": "2026-10-06T00:00:00Z",
                  "renewed_at": "2026-10-06T00:00:00Z", "ttl_s": 300},
        "acceptance": {"status": "pending", "artifact": None, "verdict_by": None,
                       "checked_at": None, "note": None, "check_job": None, "check_runs": []},
        "attention": None, "hold": None, "handoff": None,
    }


def valid_state(generation=1, attempt="attempt-1"):
    return {"schema": 1, "generation": generation, "attempt_id": attempt,
            "phase": "working", "status_line": "synthetic", "agent_claim": "running",
            "claim_artifact": None, "session_id": "synthetic-session",
            "iteration_started_at": "2026-10-06T00:00:00Z",
            "last_progress_at": "2026-10-06T00:00:00Z", "next_wakeup_at": None,
            "iterations": 1, "cost_usd": 0}


class RegistryAttentionSourceBlindTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="attention-registry-red-", dir="/var/tmp"))
        self.tmp.chmod(0o700)
        self.project = self.tmp / "project"
        self.project.mkdir(mode=0o700)
        self.registry = self.tmp / "registry"
        self.registry.mkdir(mode=0o700)
        self.config = self.tmp / "projects.json"
        put_json(self.config, {"demo": str(self.project)})
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def adapter_types(self):
        self.assertIsNotNone(_broker, "public broker module should load")
        names = ("OwnerProjectMap", "OwnerRegisteredGrants",
                 "RegistryAttentionView", "RegistryAttentionSource")
        missing = [name for name in names if not callable(getattr(_broker, name, None))]
        self.assertEqual(missing, [],
                         "registry-attention contract RED: missing public adapter seam(s): " + ", ".join(missing))
        return tuple(getattr(_broker, name) for name in names)

    def project_map(self, *, path=None, monotonic=lambda: 1.0, runner=None):
        OwnerProjectMap, _, _, _ = self.adapter_types()
        kwargs = {"monotonic": monotonic}
        if runner is not None:
            kwargs["runner"] = runner
        return OwnerProjectMap(str(path or self.config), **kwargs)

    def capture(self, project_map):
        return project_map.capture(deadline=DEADLINE)

    def add_task(self, *, project=None, incarnation=INC, control=None, state=None,
                 question=None, result=None):
        agent = self.registry / "synthetic-task"
        agent.mkdir(mode=0o700)
        spec = {"type": "task", "engine": "claude", "project": str(project or self.project),
                "name": "Synthetic registry task"}
        put_json(agent / "spec.yaml", spec)
        put_json(agent / "control.json", control or valid_control(incarnation=incarnation))
        put_json(agent / "state.1.json", state or valid_state())
        if question is not None:
            put_json(agent / "questions" / (question.get("qid", QID) + ".json"), question)
        if result is not None:
            put_json(agent / "done.json", result)
        return agent

    def view_and_source(self, *, grants=None, monotonic=lambda: 1.0):
        _, OwnerRegisteredGrants, RegistryAttentionView, RegistryAttentionSource = self.adapter_types()
        projects = self.project_map(monotonic=monotonic)
        grants = grants or OwnerRegisteredGrants(owner_only=True)
        view = RegistryAttentionView(str(self.registry), projects=projects,
                                     grants=grants, monotonic=monotonic)
        source = RegistryAttentionSource(view, monotonic=monotonic,
                                        wall_clock=lambda: NOW)
        return projects, grants, view, source

    def test_project_capture_is_atomic_immutable_and_detects_config_replacement(self):
        project2 = self.tmp / "project2"
        project2.mkdir(mode=0o700)
        put_json(self.config, {"zeta": {"path": str(self.project), "integrate": "none"},
                               "alpha": str(project2)})
        project_map = self.project_map()
        first = self.capture(project_map)
        self.assertRegex(first.epoch, r"^[0-9a-f]{32}$")
        self.assertGreaterEqual(first.revision, 0)
        self.assertRegex(first.identity, r"^[0-9a-f]{64}$")
        self.assertEqual([(row["project"], row["root"]) for row in first.entries],
                         [("alpha", str(project2)), ("zeta", str(self.project))])
        self.assertTrue(all(set(row) == {"project", "root", "root_identity"}
                            and len(row["root_identity"]) == 64 for row in first.entries))
        with self.assertRaises((TypeError, AttributeError)):
            first.entries[0]["root"] = "/var/tmp/forged"

        replacement = self.tmp / "projects-new.json"
        put_json(replacement, {"alpha": str(self.project)})
        os.replace(replacement, self.config)
        self.assertIs(project_map.current(first, deadline=DEADLINE), False,
                      "captured map must not survive pathname/inode replacement")
        second = self.capture(project_map)
        self.assertNotEqual(first.epoch, second.epoch)
        self.assertNotEqual(first.identity, second.identity)

    def test_constructor_is_lazy_and_does_not_create_missing_authority_paths(self):
        OwnerProjectMap, OwnerRegisteredGrants, RegistryAttentionView, RegistryAttentionSource = self.adapter_types()
        missing_config = self.tmp / "not-created-projects.json"
        missing_registry = self.tmp / "not-created-registry"
        projects = OwnerProjectMap(str(missing_config), monotonic=lambda: 1.0)
        grants = OwnerRegisteredGrants(owner_only=True)
        view = RegistryAttentionView(str(missing_registry), projects=projects,
                                     grants=grants, monotonic=lambda: 1.0)
        RegistryAttentionSource(view, monotonic=lambda: 1.0, wall_clock=lambda: NOW)
        self.assertFalse(missing_config.exists())
        self.assertFalse(missing_registry.exists())


    def test_project_map_rejects_duplicate_alias_and_does_not_fallback_to_old_capture(self):
        project_map = self.project_map()
        old = self.capture(project_map)
        self.config.write_text(json.dumps({"demo": str(self.project)})[:-1] +
                                ',"demo":"/var/tmp/forged"}', encoding="utf-8")
        self.config.chmod(0o600)
        with self.assertRaises(Exception):
            self.capture(project_map)
        self.assertIs(project_map.current(old, deadline=DEADLINE), False,
                      "a malformed current map cannot authorize the previous capture")

    def test_default_grant_capture_is_owner_and_uses_same_complete_alias_snapshot(self):
        project2 = self.tmp / "project2"
        project2.mkdir(mode=0o700)
        put_json(self.config, {"zeta": str(self.project), "alpha": {"path": str(project2)}})
        _, OwnerRegisteredGrants, _, _ = self.adapter_types()
        project_map = self.project_map()
        project_capture = self.capture(project_map)
        grants = OwnerRegisteredGrants(owner_only=True)
        grant_capture = grants.capture(project_capture, deadline=DEADLINE)
        self.assertEqual(grant_capture.principal, "owner")
        self.assertIs(grant_capture.owner_only, True)
        self.assertEqual(grant_capture.epoch, project_capture.epoch)
        self.assertEqual(grant_capture.revision, project_capture.revision)
        self.assertEqual(tuple(grant_capture.projects), ("alpha", "zeta"))
        self.assertIs(grants.current(grant_capture, project_capture, deadline=DEADLINE), True)

    def test_current_root_path_replacement_revokes_the_old_map_capture(self):
        project_map = self.project_map()
        captured = self.capture(project_map)
        old = self.tmp / "old-project"
        os.replace(self.project, old)
        self.project.mkdir(mode=0o700)
        self.assertIs(project_map.current(captured, deadline=DEADLINE), False,
                      "canonical root pathname must still identify the held directory")

    def test_yaml_parser_is_bounded_and_deadline_is_shared_with_runner(self):
        # YAML reaches only this synthetic injected runner; no external process runs.
        self.config.write_text("demo: /var/tmp/synthetic-project\n", encoding="utf-8")
        self.config.chmod(0o600)
        now = [0.0]
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            now[0] = 6.0
            return type("Completed", (), {"returncode": 0,
                    "stdout": json.dumps({"demo": "/var/tmp/synthetic-project"}),
                    "stderr": ""})()
        project_map = self.project_map(monotonic=lambda: now[0], runner=runner)
        with self.assertRaises(Exception):
            project_map.capture(deadline=5.0)
        self.assertEqual(len(calls), 1)
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["yq", "-p=yaml", "-o=json", ".", "-"])
        self.assertIs(kwargs.get("shell"), False)
        self.assertIs(kwargs.get("capture_output"), True)
        self.assertLessEqual(kwargs.get("timeout", 6), 5.0)

    def test_view_first_failure_and_explicit_nonowner_never_call_registry_source(self):
        self.add_task(question={"qid": QID, "kind": "info", "status": "open"})
        _, OwnerRegisteredGrants, RegistryAttentionView, RegistryAttentionSource = self.adapter_types()
        attention_module_path = ROOT / "bin" / "_control_web_attention.py"
        spec = importlib.util.spec_from_file_location("_attention_registry_composer", attention_module_path)
        composer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(composer)

        calls = []
        class Source:
            def snapshot(inner, *, deadline):
                calls.append("source")
                return {"schema": 1}

        projects = self.project_map()
        disabled = OwnerRegisteredGrants(owner_only=False)
        denied_view = RegistryAttentionView(str(self.registry), projects=projects,
                                            grants=disabled, monotonic=lambda: 1.0)
        result = composer.AttentionOverview(Source(), view=denied_view,
                    monotonic=lambda: 1.0, wall_clock=lambda: NOW).snapshot()
        self.assertEqual(result, {"error": "forbidden"})
        self.assertEqual(calls, [], "non-owner authority must fail before source access")

        self.config.write_text("{malformed", encoding="utf-8")
        self.config.chmod(0o600)
        unavailable_view = RegistryAttentionView(str(self.registry), projects=projects,
                          grants=OwnerRegisteredGrants(owner_only=True), monotonic=lambda: 1.0)
        result = composer.AttentionOverview(Source(), view=unavailable_view,
                    monotonic=lambda: 1.0, wall_clock=lambda: NOW).snapshot()
        self.assertEqual(result, {"error": "unavailable"})
        self.assertEqual(calls, [], "invalid owner map must be unavailable before source access")

    def test_source_without_active_capture_is_diagnostic_and_does_not_capture_view(self):
        _, _, _, RegistryAttentionSource = self.adapter_types()
        class View:
            calls = 0
            def snapshot(self, *, deadline):
                self.calls += 1
                raise AssertionError("source must not start a view capture")
        view = View()
        source = RegistryAttentionSource(view, monotonic=lambda: 1.0,
                                         wall_clock=lambda: NOW)
        diagnostic = source.snapshot(deadline=DEADLINE)
        self.assertEqual(view.calls, 0)
        self.assertEqual(diagnostic["state"], "unavailable")
        self.assertFalse(diagnostic["complete"])
        self.assertEqual(diagnostic["coverage"]["scope"], "none")
        self.assertEqual(diagnostic["records"], [])
        self.assertNotIn(str(self.tmp), repr(diagnostic), "diagnostic DTO must not expose private paths")

    def test_valid_registry_record_keeps_incarnation_attempt_question_and_result_provenance(self):
        question = {"qid": QID, "kind": "permission", "status": "open"}
        commit = "b" * 40
        done = {"envelope_key": "synthetic-envelope-1", "state": "accepted",
                "finalized": True, "commit_sha": commit}
        put_json(self.config, {"zeta": str(self.project), "alpha": {"path": str(self.project)}})
        self.add_task(question=question, result=done)
        _, _, view, source = self.view_and_source()
        view_snapshot = view.snapshot(deadline=DEADLINE)
        self.assertTrue(type(view_snapshot) is dict or hasattr(view_snapshot, "owner_only"))
        snapshot = source.snapshot(deadline=DEADLINE)
        self.assertEqual(snapshot["state"], "fresh")
        self.assertIs(snapshot["complete"], True)
        self.assertEqual(len(snapshot["records"]), 1)
        record = snapshot["records"][0]
        self.assertEqual(record["agent"], "synthetic-task")
        self.assertEqual(record["incarnation"], INC)
        self.assertEqual(record["generation"], 1)
        self.assertEqual(record["attempt_id"], "attempt-1")
        self.assertIsNone(record["session_binding"])
        self.assertEqual(record["project_binding"]["project"], "alpha",
                         "canonical-root collisions choose lexical first current allowed alias")
        self.assertEqual(record["project_binding"]["root"], str(self.project))
        self.assertEqual(record["questions"], [{"qid": QID, "kind": "permission",
                         "status": "open", "answered": False, "pending_delivery": False,
                         "blocking": "unknown", "native_key": None}])
        task_key = digest({"kind": "attention_task", "registry_id": record["registry_id"],
                           "agent": record["agent"], "incarnation": INC})
        result_key = digest({"kind": "attention_result", "task_key": task_key,
                             "envelope_key": done["envelope_key"], "commit_sha": commit})
        self.assertEqual(record["result"], {"generation": hashlib.sha256(
                         ("done-gen:" + done["envelope_key"] + ":" + commit).encode()).hexdigest()[:8],
                         "state": "accepted", "finalized": True, "result_key": result_key})

    def test_generation_or_attempt_drift_excludes_labels_and_reasons_as_incomplete(self):
        self.add_task(question={"qid": QID, "kind": "info", "status": "open"})
        _, _, view, source = self.view_and_source()
        view.snapshot(deadline=DEADLINE)
        good = source.snapshot(deadline=DEADLINE)
        self.assertEqual(len(good["records"]), 1)
        agent = self.registry / "synthetic-task"
        put_json(agent / "control.json", valid_control(generation=2))
        put_json(agent / "state.2.json", valid_state(generation=2, attempt="different-attempt"))
        view.snapshot(deadline=DEADLINE)
        drifted = source.snapshot(deadline=DEADLINE)
        self.assertFalse(drifted["complete"])
        self.assertEqual(drifted["reason"], "binding_incomplete")
        self.assertEqual(drifted["records"], [])
        self.assertNotIn("Synthetic registry task", repr(drifted))

    def test_aggregate_metadata_budget_reports_limit_instead_of_complete_partial_scan(self):
        # Valid JSON with trailing whitespace stays within the public 64 KiB
        # per-file cap while 270 owned synthetic specs exceed the 16 MiB shared
        # metadata budget.  No single task or parser fixture is oversized.
        self.adapter_types()
        spec_prefix = json.dumps({"type": "task", "engine": "claude",
                                  "project": str(self.project), "name": "Synthetic"},
                                 separators=(",", ":")).encode("utf-8")
        spec_payload = spec_prefix + b" " * (63_000 - len(spec_prefix))
        for index in range(270):
            agent = self.registry / ("task-%04d" % index)
            agent.mkdir(mode=0o700)
            spec_path = agent / "spec.yaml"
            spec_path.write_bytes(spec_payload)
            spec_path.chmod(0o600)
            put_json(agent / "control.json", valid_control())
            put_json(agent / "state.1.json", valid_state())
        _, _, view, source = self.view_and_source()
        view.snapshot(deadline=DEADLINE)
        snapshot = source.snapshot(deadline=DEADLINE)
        self.assertFalse(snapshot["complete"],
                         "aggregate metadata budget exhaustion cannot become complete-empty or complete-partial")
        self.assertEqual((snapshot["state"], snapshot["reason"]), ("incomplete", "limit"))
        self.assertFalse(snapshot["coverage"]["global_complete"])


if __name__ == "__main__":
    unittest.main()
