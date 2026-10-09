"""INV-DEVBUS-07 INV-DEVBUS-10: loop ownership and actual owner wire."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import live_devbus_blind_support as s


class BridgeBlind(unittest.TestCase):
    def setUp(self):
        self.Runtime = s.seam(self, "_control_web_broker", "DevbusRuntime")
        self.trace = []; self.runtimes = []; self.gates = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for gate in self.gates: gate.set()
        for runtime in self.runtimes: runtime.stop()

    def record(self, name): self.trace.append((name, threading.get_ident(), asyncio.get_running_loop()))

    def runtime(self, **changes):
        parent = self
        class Projection(s.ProjectionData):
            def __init__(inner, *args, **kwargs): parent.record("projection"); super().__init__(s.empty())
            def snapshot(inner, task=None, agent=None): parent.record("snapshot"); return super().snapshot(task, agent)
            def connection(inner, state, **kwargs): parent.record("connection"); return super().connection(state, **kwargs)
        class Observer:
            def __init__(inner, projection, connect): parent.record("observer"); inner.projection = projection
            async def start(inner): parent.record("start"); inner.projection.connection("live")
            async def stop(inner): parent.record("stop")
        arguments = dict(config_loader=lambda:(s.config(), None), projection_factory=Projection,
                         observer_factory=Observer, connect_factory=lambda _:None, dependency_probe=lambda:True)
        arguments.update(changes); runtime = self.Runtime(**arguments); self.runtimes.append(runtime); return runtime

    def test_construct_has_no_factory_io_and_one_loop_for_all_operations(self):
        runtime = self.runtime(); self.assertEqual(self.trace, [])
        runtime.start(); runtime.start()
        self.assertEqual(runtime.snapshot(), s.empty()); self.assertEqual(runtime.snapshot(task="task1"), s.empty())
        runtime.stop(); runtime.stop()
        names = [row[0] for row in self.trace]
        self.assertEqual(names.count("projection"), 1); self.assertEqual(names.count("observer"), 1)
        self.assertEqual(names.count("start"), 1); self.assertEqual(names.count("stop"), 1)
        self.assertEqual(len({row[1] for row in self.trace}), 1); self.assertEqual(len({id(row[2]) for row in self.trace}), 1)
        self.assertNotEqual(self.trace[0][1], threading.get_ident())

    def test_disabled_and_invalid_config_start_no_loop_or_dependency_probe(self):
        probes = []
        for reason in (None, "invalid_config"):
            runtime = self.runtime(config_loader=lambda:(s.config(False), reason), dependency_probe=lambda:probes.append(1))
            runtime.start(); value = runtime.snapshot(); runtime.stop()
            self.assertEqual(value["connection"]["state"], "disabled" if reason is None else "disconnected")
            if reason: self.assertEqual(value["connection"]["reason"], reason)
        self.assertEqual(self.trace, []); self.assertEqual(probes, [])

    def test_dependency_probe_exact_bool_and_exception(self):
        for probe, expected in ((lambda:False, "dependency_unavailable"), (lambda:1, "unavailable"),
                                (lambda:(_ for _ in ()).throw(RuntimeError("synthetic-private")), "unavailable")):
            calls = []
            def recorded(): calls.append(1); return probe()
            runtime = self.runtime(dependency_probe=recorded); runtime.start(); runtime.start()
            self.assertEqual(runtime.snapshot()["connection"], {"state":"disconnected", "reason":expected})
            self.assertEqual(calls, [1]); runtime.stop()
        self.assertEqual(self.trace, [])

    def test_failed_setup_terminal_no_late_observer_or_new_cleanup_thread(self):
        gate = threading.Event(); self.gates.append(gate)
        def slow_projection(*args, **kwargs):
            self.record("blocked_setup"); gate.wait(3); return s.ProjectionData(s.empty())
        runtime = self.runtime(projection_factory=slow_projection)
        started = time.monotonic(); runtime.start(); self.assertLess(time.monotonic() - started, 1.35)
        runtime.start(); gate.set(); time.sleep(.15)
        self.assertNotIn("observer", [row[0] for row in self.trace]); self.assertNotIn("start", [row[0] for row in self.trace])
        self.assertEqual(len({row[1] for row in self.trace}), 1)
        self.assertEqual(runtime.snapshot()["connection"], {"state":"disconnected", "reason":"unavailable"})

    def test_accepted_Observer_slow_connect_is_not_setup_timeout(self):
        accepted, _ = s.accepted_modules(); entered = threading.Event(); cancelled = threading.Event(); connects = []
        async def slow_connect(config):
            connects.append(1); entered.set()
            try: await asyncio.sleep(4)
            finally: cancelled.set()
        runtime = self.runtime(projection_factory=accepted.Projection, observer_factory=accepted.Observer, connect_factory=slow_connect)
        started = time.monotonic(); runtime.start(); self.assertLess(time.monotonic() - started, 1.35)
        self.assertTrue(entered.wait(1)); time.sleep(1.1); runtime.start()
        self.assertIn(runtime.snapshot()["connection"]["state"], ("connecting", "disconnected"))
        self.assertEqual(connects, [1]); runtime.stop(); self.assertTrue(cancelled.is_set())

    def test_timeout_keeps_export_token_until_actual_loop_work_finishes(self):
        gate = threading.Event(); entered = threading.Event(); self.gates.append(gate); calls = []
        class Blocking(s.ProjectionData):
            def __init__(inner, *a, **k): super().__init__(s.empty())
            def snapshot(inner, task=None, agent=None):
                calls.append((task, agent)); entered.set(); gate.wait(4); return super().snapshot(task, agent)
        runtime = self.runtime(projection_factory=Blocking); runtime.start()
        first = runtime.snapshot(); self.assertTrue(entered.is_set())
        self.assertTrue(first.get("error") in ("busy", "unavailable") or first.get("connection", {}).get("reason") == "unavailable")
        start = time.monotonic(); second = runtime.snapshot(task="task1"); self.assertLess(time.monotonic()-start, .25)
        self.assertTrue(second.get("error") in ("busy", "unavailable") or second.get("connection", {}).get("reason") == "unavailable")
        gate.set(); time.sleep(.2); self.assertEqual(calls, [(None, None)], "Caller timeout queued a second export")

    def test_RegistryBackend_validates_runtime_DTO_and_collapses_exception(self):
        module = importlib.import_module("_control_web_broker")
        with tempfile.TemporaryDirectory(prefix="bus-registry-", dir="/var/tmp") as temporary:
            class Runtime:
                def snapshot(inner, task=None, agent=None): return s.empty() | {"private": "synthetic"}
            try: backend = module.RegistryBackend(temporary, str(s.ROOT / "bin"), devbus=Runtime())
            except TypeError: self.fail("PUBLIC-SEAM PREREQUISITE: RegistryBackend devbus keyword absent")
            method = getattr(backend, "devbus_overview", None)
            self.assertTrue(callable(method), "PUBLIC-SEAM PREREQUISITE: RegistryBackend.devbus_overview absent")
            self.assertEqual(method(), {"error":"unavailable"})


class BusWireBlind(s.SocketCase):
    def test_actual_bus_op_exact_DTO(self):
        self.assertEqual(self.wire(self.bus_payload()), self.backend.bus_value)
        self.assertEqual(len(self.backend.bus_calls), 1)

    def test_malformed_known_op_never_dispatches(self):
        valid = self.bus_payload()
        malformed = [dict(op="devbus_overview"), valid | {"task":True}, valid | {"agent":"bad.id"}, valid | {"extra":1}]
        for value in malformed: self.assertEqual(self.wire(value), {"error":"unavailable"})
        self.assertEqual(self.backend.bus_calls, [])

    def test_denied_peer_receives_no_private_reply_or_dispatch(self):
        import os
        path = str(Path(self.temp.name) / "denied.sock"); stop = threading.Event(); errors=[]
        def run():
            try: self.broker.serve_broker(path,self.backend,os.getuid()+1,stop_event=stop)
            except Exception as error: errors.append(type(error).__name__)
        worker=threading.Thread(target=run,daemon=True);worker.start()
        try:
            # bind creates the pathname before listen; this no-request probe sends no private payload.
            deadline=time.monotonic()+2;ready=False
            while not errors and time.monotonic()<deadline:
                try:
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
                        probe.settimeout(.1);probe.connect(path)
                    ready=True;break
                except (FileNotFoundError,ConnectionRefusedError):time.sleep(.01)
            self.assertTrue(ready,'Denied-peer socket must be listening before the one real request');self.assertEqual(errors,[])
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
                peer.settimeout(1);peer.connect(path)
                try:
                    peer.sendall(s.canonical(self.bus_payload())+b"\n");data=peer.recv(131073)
                except (ConnectionResetError,BrokenPipeError):data=b""
            # Existing allowed_uid wire contract permits only the generic
            # forbidden reply; no observer DTO or request dispatch is allowed.
            self.assertIn(data,(b"",b'{"error":"forbidden"}\n'))
            self.assertEqual(self.backend.bus_calls,[])
        finally:stop.set();worker.join(3)

    def test_bus_reservation_busy_before_general_worker(self):
        self.assertEqual(self.wire(self.bus_payload()), self.backend.bus_value, "Bus op prerequisite")
        self.backend.bus_calls.clear(); self.backend.bus_gate.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.wire, self.bus_payload()); self.assertTrue(self.backend.wait_bus(1))
            start = time.monotonic(); self.assertEqual(self.wire(self.bus_payload(), timeout=1), {"error":"busy"})
            self.assertLess(time.monotonic()-start, .8); self.assertEqual(self.wire(dict(op="snapshot"), timeout=1), {"tasks":[]})
            self.backend.bus_gate.set(); self.assertEqual(first.result(3), self.backend.bus_value)

    def test_SocketBackend_canonical_oldwire_only_unsupported(self):
        client = self.broker.SocketBackend(self.path); method = getattr(client, "devbus_overview", None)
        self.assertTrue(callable(method), "PUBLIC-SEAM PREREQUISITE: SocketBackend.devbus_overview absent")
        path = str(Path(self.temp.name) / "old.sock"); listener = socket.socket(socket.AF_UNIX); listener.bind(path); listener.listen(4)
        self.addCleanup(listener.close); received = []
        outcomes = [{"error":"invalid_or_stale"}, {"error":"stale"}, {"error":"unavailable"}]
        def run():
            for outcome in outcomes:
                connection, _ = listener.accept()
                with connection:
                    data = b""
                    while b"\n" not in data: data += connection.recv(131073)
                    received.append(__import__("json").loads(data.split(b"\n")[0])); connection.sendall(s.canonical(outcome)+b"\n")
        old = self.broker.SocketBackend(path); worker = threading.Thread(target=run, daemon=True); worker.start()
        for expected in ("unsupported", "unavailable", "unavailable"):
            self.assertEqual(old.devbus_overview(), {"error":expected})
        worker.join(2); self.assertFalse(worker.is_alive()); self.assertEqual(received, [self.bus_payload()] * 3)
