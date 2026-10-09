"""INV-DEVBUS-08 INV-DEVBUS-10: real CLI signal ordering, synthetic factories."""
import importlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import live_devbus_blind_support as s


LAUNCHER = r'''
import asyncio, importlib, json, os, pathlib, runpy, sys, threading, time
runtime, directory = map(pathlib.Path, sys.argv[1:3]); sys.path.insert(0, str(runtime/'bin'))
sys.path.insert(1, sys.argv[3]); sys.path.insert(2, sys.argv[4])
import live_devbus_blind_support as fixture
broker=importlib.import_module('_control_web_broker')
real_runtime=getattr(broker,'DevbusRuntime',None)
fixture_only=len(sys.argv)>5 and sys.argv[5]=='fixture-only'
if real_runtime is None and not fixture_only:
    (directory/'prerequisite').write_text('DevbusRuntime absent'); sys.exit(42)
lock=threading.Lock()
def record(name):
    with lock, (directory/'trace.jsonl').open('a') as handle:
        handle.write(json.dumps(dict(name=name,at=time.monotonic(),thread=threading.get_ident()))+'\n')
class Observer:
    def __init__(self,projection,connect): record('observer_construct')
    async def start(self): record('observer_start')
    async def stop(self): record('observer_stop')
def runtime_factory(*args,**kwargs):
    kwargs.update(config_loader=lambda:(fixture.config(),None),
       projection_factory=lambda *a,**k:fixture.ProjectionData(fixture.empty()),
       observer_factory=Observer,connect_factory=lambda _:None,dependency_probe=lambda:True)
    return real_runtime(*args,**kwargs)
if real_runtime is not None: broker.DevbusRuntime=runtime_factory
# Public legacy method keeps a genuine general worker alive during signal.
original=broker.RegistryBackend.snapshot
def pending_writer(self):
    record('legacy_enter')
    deadline=time.monotonic()+8
    while not (directory/'release').exists() and time.monotonic()<deadline: time.sleep(.01)
    record('legacy_finish'); return {'tasks':[]}
broker.RegistryBackend.snapshot=pending_writer
sys.argv=[str(runtime/'bin/ai-control-web'),'broker','--registry',str(directory/'registry'),
 '--bin-dir',str(runtime/'bin'),'--socket',str(directory/'broker.sock'),
 '--allowed-uid',str(os.getuid()),'--codex-socket',str(directory/'synthetic-codex.sock'),
 '--session-receipts',str(directory/'receipts')]
try: runpy.run_path(str(runtime/'bin/ai-control-web'),run_name='__main__')
finally: record('cli_finally')
'''


class DevbusShutdownBlind(unittest.TestCase):
    def test_actual_CLI_SIGTERM_starts_observer_stop_before_legacy_drain(self):
        self.signal_probe(observe_bus=True)

    def test_actual_CLI_fixture_private_RPC_worker_and_signal_cleanup(self):
        # Positive harness control on the immutable existing CLI; this claims
        # no BUS functionality when the new runtime API is not yet present.
        self.signal_probe(observe_bus=False)

    def signal_probe(self, *, observe_bus):
        # Missing seam is a prerequisite, not a failed socket/RPC fixture.
        if observe_bus: s.seam(self, "_control_web_broker", "DevbusRuntime")
        with tempfile.TemporaryDirectory(prefix="bus-cli-blind-", dir="/var/tmp") as temporary:
            directory = Path(temporary); (directory/"registry").mkdir(mode=0o700)
            launcher = directory/"launch.py"; launcher.write_text(LAUNCHER)
            accepted, _ = s.accepted_modules(); accepted_path = str(Path(accepted.__file__).parent)
            from websockets.sync.server import unix_serve
            methods = []; rpc_errors = []
            def synthetic_rpc(ws):
                try:
                    while True:
                        request = json.loads(ws.recv(timeout=12)); methods.append(request.get("method"))
                        if "id" in request: ws.send(json.dumps({"id":request["id"], "result":{}}))
                except Exception as error:
                    if isinstance(error, (AssertionError, json.JSONDecodeError)): rpc_errors.append(type(error).__name__)
            rpc_server = unix_serve(synthetic_rpc, str(directory/"synthetic-codex.sock"))
            (directory/"synthetic-codex.sock").chmod(0o600)
            rpc_worker = threading.Thread(target=rpc_server.serve_forever, daemon=True); rpc_worker.start()
            # Existing CLI may construct an InteractiveRPC, whose connection
            # target is always this isolated synthetic path, never default host.
            process = subprocess.Popen([sys.executable,str(launcher),str(s.ROOT),str(directory),
                str(Path(__file__).parent),accepted_path] + ([] if observe_bus else ["fixture-only"]),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            def rows():
                path=directory/"trace.jsonl"
                return [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []
            peer = None
            try:
                deadline=time.monotonic()+3
                while not (directory/"broker.sock").exists() and process.poll() is None and time.monotonic()<deadline: time.sleep(.01)
                self.assertIsNone(process.poll(), "HARNESS PREREQUISITE: real CLI synthetic RPC/setup failed")
                self.assertTrue((directory/"broker.sock").exists(), "Actual CLI must start broker socket")
                peer=socket.socket(socket.AF_UNIX);peer.connect(str(directory/"broker.sock"));peer.sendall(s.canonical(dict(op="snapshot"))+b"\n")
                deadline=time.monotonic()+2
                while not any(row["name"]=="legacy_enter" for row in rows()) and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(any(row["name"]=="legacy_enter" for row in rows()))
                if not observe_bus:
                    # Positive control proves only the real launcher/RPC/socket
                    # and worker fixture. Existing default SIGTERM may terminate
                    # directly; the pending-drain ordering is the separate RED.
                    (directory/"release").touch(); deadline=time.monotonic()+2
                    while not any(row["name"]=="legacy_finish" for row in rows()) and time.monotonic()<deadline:time.sleep(.01)
                    self.assertTrue(any(row["name"]=="legacy_finish" for row in rows()))
                signaled=time.monotonic();process.send_signal(signal.SIGTERM)
                if observe_bus:
                    deadline=time.monotonic()+2
                    while not any(row["name"]=="observer_stop" for row in rows()) and time.monotonic()<deadline:time.sleep(.01)
                    trace=rows();stops=[row for row in trace if row["name"]=="observer_stop"]
                    self.assertEqual(len(stops),1,"Signal must submit Observer.stop before held legacy worker drains")
                    self.assertLess(stops[0]["at"]-signaled,1.5)
                    self.assertFalse(any(row["name"]=="legacy_finish" for row in trace))
                if observe_bus:self.assertIsNone(process.poll(),"Pending legacy worker must remain governed by existing drain")
                (directory/"release").touch();process.wait(4)
                if observe_bus:self.assertEqual(process.returncode,0)
                else:self.assertIn(process.returncode,(0,-signal.SIGTERM))
                if observe_bus:self.assertEqual(sum(row["name"]=="observer_stop" for row in rows()),1)
                self.assertFalse(set(methods) & {"turn/start", "thread/resume"}); self.assertEqual(rpc_errors, [])
            finally:
                (directory/"release").touch()
                if peer:peer.close()
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(4)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                process.stderr.close()
                rpc_server.shutdown(); rpc_worker.join(3)

    def test_disabled_runtime_stop_is_idempotent_without_transport_IO(self):
        Runtime=s.seam(self,"_control_web_broker","DevbusRuntime")
        def forbidden(*args,**kwargs): self.fail("Disabled runtime created observer/transport")
        runtime=Runtime(config_loader=lambda:(s.config(False),None),projection_factory=forbidden,
            observer_factory=forbidden,connect_factory=forbidden,dependency_probe=forbidden)
        runtime.start();runtime.stop();runtime.stop()

    def test_stop_accepted_Observer_cancels_hung_transport_within_bridge_budget(self):
        Runtime=s.seam(self,"_control_web_broker","DevbusRuntime");accepted,_=s.accepted_modules()
        entered=threading.Event();closed=[]
        class Transport:
            async def info(self):return dict(first_seq=1,last_seq=1,ttl_seconds=60,max_bytes=1024)
            async def fetch(self):entered.set();await __import__('asyncio').Event().wait()
            async def pending(self):return 1
            async def close(self):closed.append(1)
        async def connect(config):return Transport()
        runtime=Runtime(config_loader=lambda:(s.config(),None),projection_factory=accepted.Projection,
            observer_factory=accepted.Observer,connect_factory=connect,dependency_probe=lambda:True)
        runtime.start()
        try:self.assertTrue(entered.wait(2));start=time.monotonic();runtime.stop();self.assertLess(time.monotonic()-start,12.5)
        finally:runtime.stop()
        self.assertEqual(closed,[1])
