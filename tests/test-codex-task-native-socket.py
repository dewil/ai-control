#!/usr/bin/env python3
"""Blind real UNIX WebSocket transport: short endpoint and owned long host alias.

Uses only an existing websockets15.0.1 interpreter and own disposable server.
No connector replacement, native host/model/account/network call or install.
"""
import importlib.util
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

SERVER = '''import asyncio,json,os,pathlib,sys
from websockets.asyncio.server import unix_serve
socket_path,log_path=sys.argv[1:]
async def handler(connection):
 async for raw in connection:
  frame=json.loads(raw)
  with open(log_path,"a") as log:
   log.write(json.dumps(dict(method=frame.get("method")))+"\\n")
  if frame.get("method")=="initialize":
   await connection.send(json.dumps(dict(id=frame["id"],result={})))
async def main():
 async with unix_serve(handler,path=socket_path):
  os.chmod(socket_path,0o600)
  print("READY",flush=True)
  await asyncio.Future()
asyncio.run(main())
'''
CLIENT = '''import importlib,pathlib,sys,time
sys.path.insert(0,sys.argv[1])
kind,socket=sys.argv[2:]
if kind=="generic":
 from _codex_task_transport import CodexTaskRuntimeTransport
 transport=CodexTaskRuntimeTransport(socket,deadline=time.monotonic()+3,clock=time.monotonic)
else:
 runtime=importlib.import_module("_codex_task_runtime")
 assert callable(getattr(runtime,"transport_factory",None)), "trusted public transport_factory is required"
 transport=runtime.transport_factory(socket,deadline=time.monotonic()+3,clock=time.monotonic)
transport.close()
print("INITIALIZED_ONCE",flush=True)
'''


class NativeSocketContract(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='cxws-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.short = self.root / 's'
        self.log = self.root / 'handshake.jsonl'
        home = self.root / 'home'
        home.mkdir(mode=0o700)
        self.env = dict(PATH=os.environ.get('PATH', '/usr/bin:/bin'), HOME=str(home),
                        XDG_CONFIG_HOME=str(home / 'config'), CODEX_HOME=str(home / 'codex'),
                        LANG='C.UTF-8', PYTHONUTF8='1')
        if importlib.util.find_spec('websockets') is not None:
            import websockets
            self.python = Path(sys.executable) if websockets.__version__ == '15.0.1' else None
        else:
            self.python = None
        if self.python is None:
            self.python = Path.home() / '.local/share/ai-control/codex-venv/bin/python'
        self.assertTrue(self.python.is_file(), 'existing websockets15.0.1 interpreter is required; tests do not install')
        probe = subprocess.run([str(self.python), '-c', 'import websockets;print(websockets.__version__)'],
                               env=self.env, text=True, capture_output=True, timeout=5)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), '15.0.1')
        self.server = None
        self.addCleanup(self.stop_server)

    def stop_server(self):
        if self.server is not None:
            if self.server.poll() is None:
                self.server.terminate()
                try:
                    self.server.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.server.kill()
                    self.server.wait(timeout=2)
            self.server.stdout.close()
            self.server.stderr.close()

    def start_server(self):
        self.assertLess(len(os.fsencode(self.short)), 108)
        self.server = subprocess.Popen([str(self.python), '-c', SERVER, str(self.short), str(self.log)],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            stdin=subprocess.DEVNULL, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            selector.register(self.server.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=5), 'own UNIX server did not become ready')
            line = self.server.stdout.readline()
        self.assertEqual(line.strip(), 'READY', 'own UNIX server failed to start')
        self.assertEqual(self.short.stat().st_mode & 0o777, 0o600)

    def handshake(self, kind, socket):
        self.start_server()
        result = subprocess.run([str(self.python), '-c', CLIENT, str(ROOT / 'bin'), kind, str(socket)],
            env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=6)
        self.assertEqual(result.returncode, 0,
            'real default transport must connect and initialize owned UNIX endpoint: ' + result.stderr)
        self.assertEqual(result.stdout.strip(), 'INITIALIZED_ONCE')
        deadline = time.monotonic() + 2
        methods = []
        while time.monotonic() < deadline:
            if self.log.is_file():
                methods = [json.loads(line)['method'] for line in self.log.read_text().splitlines()]
                if len(methods) >= 2:
                    break
            time.sleep(0.01)
        self.assertEqual(methods, ['initialize', 'initialized'], 'factory must initialize exactly once')

    def test_existing_generic_transport_short_real_unix_endpoint(self):
        # Positive control using existing generic public constructor, no fake connector.
        self.handshake('generic', self.short)

    def test_default_factory_short_real_unix_endpoint(self):
        # INV-CXRUN-02/04
        self.assertTrue((ROOT / 'bin/_codex_task_runtime.py').is_file(), 'runtime public factory module is absent')
        self.handshake('factory', self.short)

    def test_default_factory_owned_long_host_alias_connects_short_target(self):
        # INV-CXRUN-02/04. Host-proved alias is transport input; AF_UNIX must
        # receive actual short endpoint, not the registered alias exceeding AF_UNIX capacity.
        self.assertTrue((ROOT / 'bin/_codex_task_runtime.py').is_file(), 'runtime public factory module is absent')
        directory = self.root / ('registered-state-' + 'a' * 32) / 'operations' / ('b' * 36) / 'host'
        directory.mkdir(parents=True, mode=0o700)
        for parent in directory.parents:
            if parent == self.root:
                break
            parent.chmod(0o700)
        alias = directory / 'server.sock'
        alias.symlink_to(self.short)
        self.assertGreater(len(os.fsencode(alias)), 108)
        self.assertEqual(alias.lstat().st_uid, os.getuid())
        self.handshake('factory', alias)
        self.assertEqual(alias.resolve(strict=True), self.short)


if __name__ == '__main__':
    unittest.main()
