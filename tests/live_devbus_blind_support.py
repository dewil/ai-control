"""Preparatory BUS data fixtures, DESIGN pending; no runtime import or IO.

Authority: BUS spec d96b8dd and immutable observer723048a. Synthetic DTOs
are public contract data, never production credentials or NATS configuration.
These helpers are not a frozen RED suite and make no acceptance claim.
"""
from copy import deepcopy
import asyncio
import importlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import live_sse_blind_support as live

ROOT = live.ROOT
_accepted = None

LIMIT = 98304
OBSERVER_COMMIT = "723048a6b9782632697fe81feb16a4c3d22acbd7"
ACCEPTED_TEST_BLOBS = {
    "tests/test_control_web_devbus_red.py": "93fd300e135074cf66792f9d45c93b50c9e4b345",
    "tests/test_control_web_devbus_review_red.py": "7e19f2abb56e67440aeafe8a954defc143cf3c57",
    "tests/test_control_web_devbus_scrub_red.py": "ea3576a4d90f62053212f58f79e7b6eee7d4336f",
    "tests/test_control_web_devbus_browser_red.py": "e3e55a7d172437c84a735610f298f64c4d3459f1",
    "tests/test_control_web_devbus_safety.py": "33d05b3ae01c4784695d59d85c3052a5a7e02ee4",
    "tests/test_control_web_devbus_nats_integration.py": "e6a57d737224a63759b218a6922d4bd4f0557727",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True, allow_nan=False).encode("utf-8")


def empty(*, known=False, state="live", reason=None):
    return dict(schema=1, connection=dict(state=state, reason=reason),
                coverage=dict(mode="window" if known else "unknown",
                              first_seq=1 if known else None,
                              last_seq=20000 if known else None,
                              ttl_seconds=86400 if known else None,
                              max_bytes=104857600 if known else None,
                              replay_complete=known, truncated=False, issues=[]),
                tasks=[], agents=[], events=[])


def event(sequence, *, task_id="task1", agent="worker1", message_id=None):
    return dict(message_id=message_id or "m" + str(sequence), task_id=task_id,
                agent=agent, kind="completed", event_at=None, sequence=sequence)


def task(index=1, *, result=None, transitions=(), output_truncated=False):
    return dict(task_id="task" + str(index), agent="worker1", state="completed",
                delivery="unknown", quality="unreviewed", event_at=None,
                submitted_at=None, duration_seconds=None, result=result, error=None,
                output_truncated=output_truncated, transitions=deepcopy(list(transitions)))


def agent(index=1, *, dense=False):
    return dict(agent="worker" + str(index), registered=True,
                capabilities=["cap" + str(i) + "x" * 70 for i in range(32)] if dense else [],
                executor="codex", version="v1", heartbeat_at=None,
                heartbeat_status="unknown")


def dense(*, task_count=128, event_count=512, transition_count=0,
          agent_count=0, dense_agents=False, result="🙂" * 4096, known=True):
    """Valid-cap adversarial input; adjust counts to isolate each clipping stage.

    Distinct public sequence ranks permit a spec-derived oldest-prefix oracle.
    No private fields or fabricated submission-time ranking are supplied.
    """
    if not (0 <= task_count <= 256 and 0 <= event_count <= 512
            and 0 <= transition_count <= 32 and 0 <= agent_count <= 128):
        raise ValueError("synthetic data exceeds accepted caps")
    value = empty(known=known)
    for index in range(1, task_count + 1):
        rows = [event((index - 1) * 32 + j + 1, task_id="task" + str(index))
                for j in range(transition_count)]
        value["tasks"].append(task(index, result=result, transitions=rows))
    value["events"] = [event(i + 1) for i in range(event_count)]
    value["agents"] = [agent(i + 1, dense=dense_agents) for i in range(agent_count)]
    return value


def mark_limited(value):
    """Expected truthful coverage after any clipping/surrogate replacement."""
    value["coverage"]["truncated"] = True
    value["coverage"]["issues"] = sorted(set(value["coverage"]["issues"]) | {"local_eviction"})
    value["coverage"]["mode"] = "partial" if value["coverage"]["first_seq"] is not None else "unknown"


def smallest_fitting_prefix(value, apply_prefix):
    """Independent exhaustive bounded test oracle, not production binary search.

    apply_prefix(candidate,count) returns false after its final allowed count.
    Return the first canonical-fitting candidate; None means next stage needed.
    Only handpicked moderate fixtures use this oracle, not full8192 stress data.
    """
    for count in range(1, 8193):
        candidate = deepcopy(value)
        if not apply_prefix(candidate, count):
            return None
        mark_limited(candidate)
        if len(canonical(candidate)) <= LIMIT:
            return count, candidate
    return None


class ProjectionData:
    """A documented snapshot seam double; always returns an independent copy."""
    def __init__(self, value):
        self.value = deepcopy(value)
        self.calls = []

    def connection(self, state, *, reason=None):
        self.value["connection"] = dict(state=state, reason=reason)

    def snapshot(self, task=None, agent=None):
        self.calls.append((task, agent))
        value = deepcopy(self.value)
        value["tasks"] = [row for row in value["tasks"]
                          if (task is None or row["task_id"] == task)
                          and (agent is None or row["agent"] == agent)]
        value["events"] = [row for row in value["events"]
                           if (task is None or row["task_id"] == task)
                           and (agent is None or row["agent"] == agent)]
        if agent is not None:
            value["agents"] = [row for row in value["agents"] if row["agent"] == agent]
        return value


def accepted_modules():
    """Portable exact accepted modules, never the future broker/web source."""
    global _accepted
    if _accepted is None:
        _accepted = tempfile.TemporaryDirectory(prefix="bus-accepted-fixture-", dir="/var/tmp")
        directory = Path(_accepted.name)
        for name in ("_control_web_devbus.py", "_control_web_devbus_nats.py"):
            data = subprocess.check_output(["git", "-C", str(ROOT), "show", OBSERVER_COMMIT + ":bin/" + name])
            (directory / name).write_bytes(data)
        sys.path.append(str(directory))
    return importlib.import_module("_control_web_devbus"), importlib.import_module("_control_web_devbus_nats")


def seam(case, module, name):
    accepted_modules()
    subject = importlib.import_module(module)
    value = getattr(subject, name, None)
    case.assertTrue(callable(value), "PUBLIC-SEAM PREREQUISITE: " + module + "." + name + " absent")
    return value


def config(enabled=True):
    _, nats = accepted_modules()
    return nats.NatsConfig.from_env(dict(CONTROL_DEVBUS_ENABLED="1" if enabled else "0",
        CONTROL_DEVBUS_STREAM="DEVBUS", DEVBUS_NATS_URL="nats://127.0.0.1:4222",
        DEVBUS_NATS_TOKEN="synthetic-bus-token-not-a-real-secret"))


class BusBackend(live.Backend):
    def __init__(self):
        super().__init__(); self.bus_value = empty(); self.bus_value["tasks"] = [task(result="BUS synthetic result")]
        self.bus_calls = []; self.bus_outcome = None
        self.bus_gate = threading.Event(); self.bus_gate.set()
        self.bus_condition = threading.Condition(); self.bus_active = self.bus_maximum = 0

    def devbus_overview(self, task=None, agent=None):
        with self.bus_condition:
            self.bus_active += 1; self.bus_maximum = max(self.bus_maximum, self.bus_active)
            row = dict(task=task, agent=agent, start=time.monotonic(), finish=None)
            self.bus_calls.append(row); self.bus_condition.notify_all()
        try:
            if not self.bus_gate.wait(12): return {"error": "unavailable"}
            if isinstance(self.bus_outcome, Exception): raise self.bus_outcome
            if self.bus_outcome is not None: return deepcopy(self.bus_outcome)
            return ProjectionData(self.bus_value).snapshot(task, agent)
        finally:
            with self.bus_condition:
                self.bus_active -= 1; row["finish"] = time.monotonic(); self.bus_condition.notify_all()

    def wait_bus(self, count, timeout=3):
        with self.bus_condition:
            return self.bus_condition.wait_for(lambda: len(self.bus_calls) >= count, timeout)


class HttpCase(unittest.TestCase):
    def setUp(self):
        # Reuse the actual public app fixture. A public backend is injected
        # before serving; no replacement app/auth callback/closure inspection.
        original = live.Backend
        live.Backend = BusBackend
        try: self.fixture = live.Fixture(session_store=True)
        finally: live.Backend = original
        self.addCleanup(self.fixture.stop); self.fixture.login()
        self.backend = self.fixture.backend
        self.addCleanup(self.backend.bus_gate.set)

    def response(self, suffix="", **kwargs):
        connection, response = self.fixture.request("/api/devbus/overview" + suffix, **kwargs)
        data = response.read(); connection.close()
        return response, json.loads(data)

    def expect_error(self, status, error="unavailable", **kwargs):
        response, value = self.response(**kwargs)
        self.assertEqual(response.status, status, "Actual BUS route outcome")
        self.assertEqual(value, {"error": error})
        self.assertIn("no-store", response.getheader("cache-control", ""))


class SocketCase(unittest.TestCase):
    def setUp(self):
        import os
        accepted_modules(); self.broker = importlib.import_module("_control_web_broker")
        self.temp = tempfile.TemporaryDirectory(prefix="bus-socket-blind-", dir="/var/tmp"); self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "broker.sock")
        self.backend = BusBackend(); self.stop_event = threading.Event(); self.errors = []
        def run():
            try: self.broker.serve_broker(self.path, self.backend, os.getuid(), stop_event=self.stop_event)
            except Exception as error: self.errors.append(type(error).__name__)
        self.worker = threading.Thread(target=run, daemon=True); self.worker.start(); self.addCleanup(self.cleanup)
        deadline = time.monotonic() + 3; ready = False
        while not self.errors and time.monotonic() < deadline:
            try:
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe: probe.connect(self.path)
                ready = True; break
            except (FileNotFoundError,ConnectionRefusedError): time.sleep(.01)
        self.assertEqual(self.errors, []); self.assertTrue(ready, "Actual private socket listening prerequisite")

    def cleanup(self):
        self.backend.gate.set(); self.backend.bus_gate.set()
        if hasattr(self.backend, "legacy_gate"): self.backend.legacy_gate.set()
        self.stop_event.set(); self.worker.join(4)
        if self.worker.is_alive(): raise RuntimeError("Synthetic broker still alive after bounded cleanup")

    def wire(self, value, timeout=8):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(timeout); peer.connect(self.path); peer.sendall(canonical(value) + b"\n")
            data = b""
            while b"\n" not in data:
                piece = peer.recv(131073)
                if not piece: break
                data += piece
                self.assertLessEqual(len(data), 131072)
            return json.loads(data.split(b"\n")[0])

    @staticmethod
    def bus_payload(): return dict(op="devbus_overview", task=None, agent=None)
