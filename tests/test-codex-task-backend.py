"""Independent CXTASK-BACKEND contract tests; no native or remote effects."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from _codex_task_backend import BackendError, CodexTaskBackend
from _codex_task_bridge import BridgeError, TaskBinding, CodexTaskBridge


INCARNATION = "0123456789abcdef0123456789abcdef"
OPERATION = "12345678-1234-4234-8234-123456789abc"
ATTEMPT = "attempt-1"
GENERATION = 7


def save_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class BackendContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.agent = self.root / "registry/agents/taskone"
        self.agents = self.agent.parent
        self.locks = [self.agent / "questions/.lock", self.agent / "done.lock",
                      self.agents / ".locks/new-task-taskone.lock", self.agent / ".lock",
                      self.agent / "inbox/.inbox.lock"]
        for directory in (self.agent, self.agent / "questions", self.agent / "inbox",
                          self.agent / "inbox/inflight", self.agents / ".locks"):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
        for path in self.locks:
            path.touch(mode=0o600)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith("GIT_"):
                del self.env[key]
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / "config"),
                        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT="0")
        self.project = self.root / "project"
        self.project.mkdir()
        self.git("init", cwd=self.project)
        self.git("config", "user.name", "Fixture", cwd=self.project)
        self.git("config", "user.email", "fixture@example.invalid", cwd=self.project)
        self.git("config", "core.hooksPath", str(self.root / "no-hooks"), cwd=self.project)
        (self.project / "tracked.txt").write_text("baseline\n")
        self.git("add", "tracked.txt", cwd=self.project)
        self.git("commit", "-m", "fixture baseline", cwd=self.project)
        self.base = self.git("rev-parse", "HEAD", cwd=self.project).strip()
        self.git("worktree", "add", "-b", "task/taskone-" + INCARNATION[:8],
                 str(self.agent / "work"), cwd=self.project)
        self.spec = dict(engine="codex", type="event", runtime="drain",
                         workspace="worktree", project=str(self.project))
        (self.agent / "spec.yaml").write_text("\n".join(f"{k}: {v}" for k, v in self.spec.items()) + "\n")
        (self.agent / "spec.yaml").chmod(0o600)
        self.control = dict(schema=1, incarnation=INCARNATION, generation=GENERATION,
                            desired="running", hold=None, mission_base=self.base,
                            acceptance={"status": "pending"},
                            lease={"state": "active", "start_attempt_id": ATTEMPT},
                            seq=0, session_id=None, attention=None, handoff=None)
        self.operation = dict(schema=1, operation_id=OPERATION,
                              task_incarnation=INCARNATION, generation=GENERATION,
                              attempt_id=ATTEMPT, thread_id="thread-1", turn_id="turn-1", status="active")
        self.inflight = dict(key="event-1", meta={"codex_operation": self.operation})
        self.control_path = self.agent / "control.json"
        self.inflight_path = self.agent / "inbox/inflight/event-1.json"
        self.save_authority()
        self.binding = TaskBinding(INCARNATION, "event-1", str(self.agent), "thread-1", "turn-1")
        self.clock = FakeClock()
        self.backend = self.new_backend()
        self.environment = mock.patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout

    def save_authority(self):
        save_json(self.control_path, self.control)
        save_json(self.inflight_path, self.inflight)

    def new_backend(self, **kwargs):
        return CodexTaskBackend(self.binding, GENERATION, ATTEMPT, OPERATION,
                                clock=self.clock, spec_reader=lambda agent_dir, **kw: dict(self.spec), **kwargs)

    def guard(self):
        return self.backend.guard(self.binding, deadline=110.0)

    def write(self, tool="task_ask", args=None):
        return self.backend.write(self.binding, tool, args or {"question": "Proceed?"}, deadline=110.0)

    def evidence(self):
        return sorted(self.agent.glob("questions/*.json")) + list(self.agent.glob("done.json"))

    def denied(self):
        before = [(p, p.read_bytes()) for p in self.evidence()]
        with self.assertRaises(BackendError):
            with self.guard():
                self.write()
        self.assertEqual(before, [(p, p.read_bytes()) for p in self.evidence()])

    # FR-CXBACK-01 INV-CXBACK-01
    def test_exact_control_authority(self):
        mutations = {"schema": 2, "incarnation": "f" * 32, "generation": 8,
                     "desired": "stopped", "hold": "pause", "mission_base": "short",
                     "lease": {"state": "inactive", "start_attempt_id": ATTEMPT},
                     "acceptance": {"status": "accepted"}}
        for field, bad in mutations.items():
            with self.subTest(field=field):
                original = self.control[field]
                self.control[field] = bad
                self.save_authority()
                self.denied()
                self.control[field] = original
        self.control["lease"]["start_attempt_id"] = "stale"
        self.save_authority()
        self.denied()

    def test_all_operation_identity_fields(self):
        for field, bad in dict(schema=2, operation_id=str(uuid.uuid4()), task_incarnation="f" * 32,
                               generation=8, attempt_id="stale", thread_id="other", turn_id="other",
                               status="finished").items():
            with self.subTest(field=field):
                old = self.operation[field]
                self.operation[field] = bad
                self.save_authority()
                self.denied()
                self.operation[field] = old
        for status in ("revoked", "prepared", "unknown"):
            self.operation["status"] = status
            self.save_authority()
            self.denied()

    def test_envelope_key_and_scope(self):
        self.inflight["key"] = "other"
        self.save_authority()
        self.denied()
        self.inflight["key"] = "event-1"
        self.save_authority()
        for field, value in dict(engine="claude", type="mission", runtime="direct", workspace="project",
                                 project="relative").items():
            with self.subTest(field=field):
                old = self.spec[field]
                self.spec[field] = value
                self.denied()
                self.spec[field] = old
        del self.spec["engine"]
        self.denied()

    def test_revise_and_extra_metadata_allowed(self):
        self.control["acceptance"]["status"] = "revise"
        self.inflight["meta"]["extra"] = "permitted"
        self.save_authority()
        with self.guard() as admitted:
            self.assertIs(admitted, True)
        self.assertEqual(self.evidence(), [])

    # FR-CXBACK-02 INV-CXBACK-02
    def test_all_locks_held_until_guard_exit(self):
        with self.guard():
            for path in self.locks:
                with path.open("r+") as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in self.locks:
            with path.open("r+") as other:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_busy_locks_fail_nonblocking(self):
        for path in self.locks:
            with self.subTest(path=path), path.open("r+") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                started = time.monotonic()
                self.denied()
                self.assertLess(time.monotonic() - started, 1.0)

    def test_missing_lock_not_created(self):
        for path in self.locks:
            with self.subTest(path=path):
                path.unlink()
                self.denied()
                self.assertFalse(path.exists())
                path.touch(mode=0o600)

    def test_unsafe_files_fail_closed(self):
        for path in (self.control_path, self.inflight_path, self.agent / "spec.yaml", *self.locks):
            original = path.read_bytes()
            with self.subTest(path=path, mode="writable"):
                path.chmod(0o666)
                self.denied()
                path.chmod(0o600)
            with self.subTest(path=path, mode="hardlink"):
                alias = self.root / "alias"
                os.link(path, alias)
                self.denied()
                alias.unlink()
            with self.subTest(path=path, mode="symlink"):
                target = self.root / "target"
                path.rename(target)
                path.symlink_to(target)
                self.denied()
                path.unlink()
                target.rename(path)
            self.assertEqual(path.read_bytes(), original)

    def test_corrupt_duplicate_and_oversize_authority(self):
        for path in (self.control_path, self.inflight_path):
            original = path.read_bytes()
            for payload in ('{"schema":1,"schema":1}', '{broken', '[]', 'x' * (1024 * 1024 + 1)):
                with self.subTest(path=path, size=len(payload)):
                    path.write_text(payload)
                    self.denied()
            path.write_bytes(original)

    def test_direct_reentrant_other_thread_and_after_guard_denied(self):
        with self.assertRaises(BackendError):
            self.write()
        with self.guard():
            with self.assertRaises(BackendError):
                with self.guard():
                    pass
            errors = []
            def elsewhere():
                try:
                    self.write()
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=elsewhere)
            thread.start()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], BackendError)
            with self.assertRaises(BackendError):
                self.new_backend().write(self.binding, "task_ask", {"question": "Q"}, deadline=110)
        with self.assertRaises(BackendError):
            self.write()
        self.assertEqual(self.evidence(), [])

    def test_replaced_lock_refused_before_effect(self):
        with self.guard():
            path = self.agent / ".lock"
            path.rename(self.root / "old-lock")
            path.touch(mode=0o600)
            with self.assertRaises(BackendError):
                self.write()
        self.assertEqual(self.evidence(), [])

    # FR-CXBACK-03 INV-CXBACK-03
    def test_real_question_and_environment_cannot_redirect(self):
        alternate = self.root / "wrong-agent"
        alternate.mkdir()
        with mock.patch.dict(os.environ, {"CLAUDE_AGENT_DIR": str(alternate), "CLAUDE_AGENT_EVENT_KEY": "wrong"}):
            with self.guard():
                result = self.write(args={"question": "Proceed?", "options": ["Yes", "No"], "context": "Details"})
        qid = result["qid"]
        self.assertEqual(str(uuid.UUID(qid)), qid)
        evidence = json.loads((self.agent / f"questions/{qid}.json").read_text())
        self.assertEqual(evidence["qid"], qid)
        self.assertEqual(evidence["envelope_key"], "event-1")
        self.assertEqual(evidence["question"], "Proceed?")
        self.assertEqual(evidence["status"], "open")
        self.assertEqual(list(alternate.iterdir()), [])

    def test_question_singleton_and_corrupt_evidence(self):
        with self.guard():
            self.write()
        before = [(p, p.read_bytes()) for p in self.evidence()]
        with self.assertRaises(BackendError):
            with self.guard():
                self.write(args={"question": "Another question?"})
        self.assertEqual(before, [(p, p.read_bytes()) for p in self.evidence()])
        before[0][0].write_text('{broken')
        with self.assertRaises(BackendError):
            with self.guard():
                self.write()

    def test_real_done_requested_safe_worktree_and_capping(self):
        summary = "<" * 2000
        with self.guard():
            self.assertEqual(self.write("task_done", {"summary": summary}), {"requested": True})
        done = json.loads((self.agent / "done.json").read_text())
        self.assertEqual(done["state"], "requested")
        self.assertEqual(done["workspace"], "worktree")
        self.assertEqual(done["envelope_key"], "event-1")
        self.assertIs(done["finalized"], False)
        self.assertLessEqual(len(done["summary"]), 1500)
        self.assertNotIn("<", done["summary"])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.project).strip(), self.base)
        self.assertTrue((self.agent / "work/.git").is_file())

    def test_dirty_worktree_refuses_done(self):
        (self.agent / "work/tracked.txt").write_text("dirty\n")
        with self.assertRaises(BackendError):
            with self.guard():
                self.write("task_done", {"summary": "Ready"})
        self.assertFalse((self.agent / "done.json").exists())

    def test_wrong_branch_refuses_done(self):
        self.git("checkout", "-b", "unrelated", cwd=self.agent / "work")
        with self.assertRaises(BackendError):
            with self.guard():
                self.write("task_done", {"summary": "Ready"})
        self.assertFalse((self.agent / "done.json").exists())

    def done_fixture(self, state="requested"):
        return dict(workspace="worktree", envelope_key="previous-event", summary="old",
                    finalized=False, requested_at="2026-10-03T00:00:00Z", state=state)

    def test_requested_ownership_transfer(self):
        save_json(self.agent / "done.json", self.done_fixture())
        with self.guard():
            self.write("task_done", {"summary": "new"})
        done = json.loads((self.agent / "done.json").read_text())
        self.assertEqual(done["envelope_key"], "event-1")
        self.assertEqual(done["state"], "requested")
        self.assertIs(done["finalized"], False)

    def test_terminal_or_corrupt_done_refuses_guard(self):
        for state in ("accepted", "rejected", "integrated", "cleaned", "archived", "cancelled", "unknown"):
            with self.subTest(state=state):
                save_json(self.agent / "done.json", self.done_fixture(state))
                self.denied()
        (self.agent / "done.json").write_text('{broken')
        self.denied()

    def test_authority_rechecked_before_write(self):
        with self.guard():
            self.operation["status"] = "revoked"
            self.save_authority()
            with self.assertRaises(BackendError):
                self.write()
        self.assertEqual(self.evidence(), [])

    def test_direct_arguments_validated(self):
        for tool, args in (("other", {}), ("task_ask", {}), ("task_ask", {"question": " "}),
                           ("task_ask", {"question": "Q", "path": "/tmp"}),
                           ("task_ask", {"question": "Q", "options": ["same", "same"]}),
                           ("task_done", {"summary": None}), ("task_done", {"summary": "x" * 4097})):
            with self.subTest(tool=tool, args=args), self.guard():
                with self.assertRaises(BackendError):
                    self.backend.write(self.binding, tool, args, deadline=110)
        self.assertEqual(self.evidence(), [])

    # FR-CXBACK-04 INV-CXBACK-04
    def test_constructor_inert(self):
        before = sorted(str(p) for p in self.root.rglob("*"))
        with mock.patch("subprocess.run", side_effect=AssertionError("unexpected subprocess")):
            self.new_backend()
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))

    def test_constructor_identity_validation(self):
        for generation, attempt, operation in ((True, ATTEMPT, OPERATION), (0, ATTEMPT, OPERATION),
                                                (7, " ", OPERATION), (7, "a/b", OPERATION),
                                                (7, "a\\b", OPERATION), (7, "x" * 257, OPERATION),
                                                (7, ATTEMPT, "not-uuid")):
            with self.subTest(generation=generation, attempt=attempt, operation=operation):
                with self.assertRaises(BackendError):
                    CodexTaskBackend(self.binding, generation, attempt, operation)

    def test_deadlines_invalid_expired_and_during_guard(self):
        for deadline in (99.0, float("inf"), float("nan")):
            with self.subTest(deadline=deadline), self.assertRaises(BackendError):
                with self.backend.guard(self.binding, deadline=deadline):
                    pass
        with self.guard():
            self.clock.now = 111
            with self.assertRaises(BackendError):
                self.write()
        self.assertEqual(self.evidence(), [])

    def test_reader_errors_are_static(self):
        secret_marker = "sensitive-payload-NEVER-EXPOSE"
        def broken(agent_dir, *, deadline):
            raise RuntimeError(secret_marker)
        self.backend = CodexTaskBackend(self.binding, GENERATION, ATTEMPT, OPERATION,
                                        clock=self.clock, spec_reader=broken)
        with self.assertRaises(BackendError) as caught:
            with self.guard():
                pass
        self.assertNotIn(secret_marker, str(caught.exception))

    def bridge(self):
        return CodexTaskBridge(self.root / "bridge-state", self.binding,
                               guard=self.backend.guard, writer=self.backend.write, clock=self.clock)

    def request(self, rpc_id=1, call_id="call-1", question="Proceed?"):
        return dict(id=rpc_id, method="item/tool/call", params=dict(threadId="thread-1", turnId="turn-1",
                    callId=call_id, tool="task_ask", arguments={"question": question}))

    def test_bridge_real_writer_receipt_and_reopen_replay(self):
        response = self.bridge().handle(self.request(), deadline=110)
        self.assertTrue(response["result"]["success"])
        result = json.loads(response["result"]["contentItems"][0]["text"])
        self.assertTrue((self.agent / f"questions/{result['qid']}.json").exists())
        before = [(p, p.read_bytes()) for p in self.evidence()]
        replay = self.bridge().handle(self.request(rpc_id=2), deadline=110)
        self.assertEqual(replay["id"], 2)
        self.assertEqual(replay["result"], response["result"])
        self.assertEqual(before, [(p, p.read_bytes()) for p in self.evidence()])

    def test_bridge_replay_revoked_and_conflict_refuse(self):
        bridge = self.bridge()
        bridge.handle(self.request(), deadline=110)
        before = [(p, p.read_bytes()) for p in self.evidence()]
        with self.assertRaises(BridgeError):
            bridge.handle(self.request(question="Changed"), deadline=110)
        self.operation["status"] = "revoked"
        self.save_authority()
        with self.assertRaises(BridgeError):
            self.bridge().handle(self.request(rpc_id=3), deadline=110)
        self.assertEqual(before, [(p, p.read_bytes()) for p in self.evidence()])

    def test_missing_identity_files_refuse_without_recreation(self):
        for path in (self.control_path, self.inflight_path, self.agent / "spec.yaml"):
            original = path.read_bytes()
            path.unlink()
            self.denied()
            self.assertFalse(path.exists())
            path.write_bytes(original)
            path.chmod(0o600)

    def test_private_directory_permissions_and_replacement(self):
        for path in (self.agent, self.agent / "questions", self.agent / "inbox",
                     self.agent / "inbox/inflight", self.agents, self.agents / ".locks"):
            with self.subTest(path=path):
                path.chmod(0o777)
                self.denied()
                path.chmod(0o700)
        with self.guard():
            questions = self.agent / "questions"
            questions.rename(self.agent / "old-questions")
            questions.mkdir(mode=0o700)
            (questions / ".lock").touch(mode=0o600)
            with self.assertRaises(BackendError):
                self.write()
        self.assertEqual(self.evidence(), [])

    def test_wrong_binding_is_denied(self):
        wrong = TaskBinding(INCARNATION, "event-1", str(self.agent), "thread-1", "other-turn")
        with self.assertRaises(BackendError):
            with self.backend.guard(wrong, deadline=110):
                pass
        with self.guard():
            with self.assertRaises(BackendError):
                self.backend.write(wrong, "task_ask", {"question": "Q"}, deadline=110)
        self.assertEqual(self.evidence(), [])

    def test_control_and_spec_changes_rechecked(self):
        with self.guard():
            self.control["generation"] += 1
            self.save_authority()
            with self.assertRaises(BackendError):
                self.write()
        self.control["generation"] = GENERATION
        self.save_authority()
        with self.guard():
            self.spec["engine"] = "claude"
            with self.assertRaises(BackendError):
                self.write()
        self.assertEqual(self.evidence(), [])

    def test_reader_expiry_cannot_admit_or_write(self):
        def slow(agent_dir, *, deadline):
            self.clock.now = deadline + 1
            return dict(self.spec)
        self.backend = CodexTaskBackend(self.binding, GENERATION, ATTEMPT, OPERATION,
                                        clock=self.clock, spec_reader=slow)
        self.denied()

    def test_bridge_unknown_writer_outcome_never_repeats(self):
        calls = []
        def unknown(binding, tool, arguments, *, deadline):
            calls.append(tool)
            self.backend.write(binding, tool, arguments, deadline=deadline)
            raise RuntimeError("uncertain effect")
        bridge = CodexTaskBridge(self.root / "bridge-state", self.binding,
                                 guard=self.backend.guard, writer=unknown, clock=self.clock)
        with self.assertRaises(BridgeError):
            bridge.handle(self.request(), deadline=110)
        self.assertEqual(len(self.evidence()), 1)
        before = [(p, p.read_bytes()) for p in self.evidence()]
        with self.assertRaises(BridgeError):
            self.bridge().handle(self.request(rpc_id=2), deadline=110)
        self.assertEqual(calls, ["task_ask"])
        self.assertEqual(before, [(p, p.read_bytes()) for p in self.evidence()])

    def test_shared_locked_helper_expired_deadline_has_no_effect(self):
        from _agent_question_io import create_question_locked
        from _agent_done_io import request_done_locked
        for callback in (lambda: create_question_locked(str(self.agent), "event-1", "info", "Q",
                                                        strict=True, deadline=99, clock=self.clock),
                         lambda: request_done_locked(str(self.agent), "event-1", "Ready",
                                                     strict=True, deadline=99, clock=self.clock)):
            with self.assertRaises(Exception):
                callback()
        self.assertEqual(self.evidence(), [])


if __name__ == "__main__":
    unittest.main()
