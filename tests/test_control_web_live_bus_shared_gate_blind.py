"""INV-WSESS-51 INV-DEVBUS-10: actual combined4-worker owner budget.

Independent integration gap coverage; frozen LIVE-only tests stay unchanged.
"""
from concurrent.futures import ThreadPoolExecutor
import socket
import threading
import time
import live_devbus_blind_support as s


class SharedGateBlind(s.SocketCase):
    def admit_prerequisites(self):
        self.assertEqual(self.wire(dict(op="session_live_snapshot", project="demo", sid=s.live.SID)).get("schema"), 1)
        self.assertEqual(self.wire(self.bus_payload()), self.backend.bus_value, "Actual BUS op integration prerequisite")
        self.backend.calls.clear(); self.backend.bus_calls.clear()

    def test_live_bus_plus_two_legacy_workers_leave_no_fifth_waitqueue(self):
        self.admit_prerequisites(); self.backend.gate.clear(); self.backend.bus_gate.clear()
        legacy_gate = self.backend.legacy_gate = threading.Event(); condition = threading.Condition()
        active = 0; maximum = 0; entries = []
        def held_snapshot():
            nonlocal active, maximum
            with condition:
                active += 1; maximum = max(maximum, active); entries.append(time.monotonic()); condition.notify_all()
            try:
                if not legacy_gate.wait(8): return {"error":"unavailable"}
                return {"tasks":[]}
            finally:
                with condition: active -= 1; condition.notify_all()
        self.backend.snapshot = held_snapshot
        with ThreadPoolExecutor(max_workers=4) as pool:
            live = pool.submit(self.wire, dict(op="session_live_snapshot", project="demo", sid=s.live.SID))
            bus = pool.submit(self.wire, self.bus_payload())
            self.assertTrue(self.backend.wait_calls(1)); self.assertTrue(self.backend.wait_bus(1))
            old_a = pool.submit(self.wire, dict(op="snapshot")); old_b = pool.submit(self.wire, dict(op="snapshot"))
            with condition: self.assertTrue(condition.wait_for(lambda:len(entries)==2, 2), "Two remaining general workers must enter")
            for payload in (dict(op="session_live_snapshot", project="demo", sid=s.live.SID), self.bus_payload(), dict(op="snapshot")):
                start = time.monotonic(); self.assertEqual(self.wire(payload, timeout=1), {"error":"busy"})
                self.assertLess(time.monotonic()-start, .8, "Saturation allocated a waitqueue instead of prompt busy")
            self.assertEqual((self.backend.active, self.backend.bus_active, active), (1,1,2))
            self.assertEqual(maximum, 2); self.assertEqual(len(entries), 2)
            self.backend.gate.set(); self.backend.bus_gate.set(); legacy_gate.set()
            self.assertEqual(live.result(3)["schema"], 1); self.assertEqual(bus.result(3), self.backend.bus_value)
            self.assertEqual(old_a.result(3), {"tasks":[]}); self.assertEqual(old_b.result(3), {"tasks":[]})

    def test_disconnect_keeps_both_reservations_until_worker_finishes(self):
        self.admit_prerequisites(); self.backend.gate.clear(); self.backend.bus_gate.clear()
        peers = []
        for value in (dict(op="session_live_snapshot", project="demo", sid=s.live.SID), self.bus_payload()):
            peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); peer.connect(self.path)
            peer.sendall(s.canonical(value)+b"\n"); peers.append(peer)
        self.assertTrue(self.backend.wait_calls(1)); self.assertTrue(self.backend.wait_bus(1))
        for peer in peers: peer.close()
        time.sleep(.1)
        for value in (dict(op="session_live_snapshot", project="demo", sid=s.live.SID), self.bus_payload()):
            self.assertEqual(self.wire(value, timeout=1), {"error":"busy"})
        self.assertEqual(len(self.backend.calls), 1); self.assertEqual(len(self.backend.bus_calls), 1)
        self.backend.gate.set(); self.backend.bus_gate.set()
        deadline = time.monotonic()+2
        while (self.backend.active or self.backend.bus_active) and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual((self.backend.active, self.backend.bus_active), (0,0))
        self.assertEqual(self.wire(dict(op="session_live_snapshot", project="demo", sid=s.live.SID))["schema"], 1)
        self.assertEqual(self.wire(self.bus_payload()), self.backend.bus_value)
