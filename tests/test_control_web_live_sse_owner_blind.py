"""LIVE owner/broker public adapter checks; imports allowed, implementation unread."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from copy import deepcopy
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import live_sse_blind_support as s
from test_control_web_session_chat_contract import RPC, turn
from test_control_web_session_models_module import CONTEXT

class LiveOwnerBlind(unittest.TestCase):
    def setUp(self):
        self.module=importlib.import_module('_control_web_sessions')
        self.temp=tempfile.TemporaryDirectory(prefix='live-owner-blind-',dir='/var/tmp'); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.root.chmod(0o700); self.project=self.root/'project';self.project.mkdir(mode=0o700)
        self.rpc=RPC(self.project);self.context=dict(CONTEXT)
        self.chat=self.module.SessionChat(self.rpc,lambda _:str(self.project),lambda:['demo','ALP','7r'],
            str(self.root/'receipts'),model_context=lambda:dict(self.context))

    def method(self):
        result=getattr(self.chat,'live_snapshot',None)
        self.assertTrue(callable(result),'PUBLIC-SEAM PREREQUISITE: SessionChat.live_snapshot absent; not a missing-import semantic RED')
        return result

    def test_existing_actual_history_timing_inventory_before_live_freeze(self):
        result=self.chat.history('demo',s.SID); self.assertIn('turns',result)
        items=result['turns'][0]['items'];self.assertGreater(len(items),0)
        self.assertEqual(set(items[0]),{'id','role','text','truncated','timestamp','time_precision'})
        self.assertIn(items[0]['time_precision'],('item','turn','unknown'))
        self.assertFalse(self.rpc.starts())

    def test_live_private_envelope_and_no_writer(self):
        value=self.method()('demo',s.SID)
        self.assertEqual(set(value),{'schema','scope_id','history'});self.assertEqual(value['schema'],1)
        self.assertRegex(value['scope_id'],r'\A[0-9a-f]{64}\Z')
        actual=deepcopy(value['history']);expected=self.chat.history('demo',s.SID)
        for projection in (actual,expected):
            if 'session_settings' in projection:
                projection['session_settings'].pop('age_ms',None)
                projection['session_settings'].pop('expires_in_ms',None)
        self.assertEqual(actual,expected,'Only producer age/remaining timing may differ between fresh owner reads')
        self.assertNotIn(str(self.project),json.dumps(value));self.assertNotIn(self.context['context_id'],json.dumps(value))
        self.assertFalse(self.rpc.starts());self.assertFalse({'thread/resume','model/list'}&{m for m,p in self.rpc.calls})

    def test_wrong_thread_and_context_change_fail_without_old_history(self):
        live=self.method();self.rpc.read_id=s.OTHER
        self.assertEqual(live('demo',s.SID),{'error':'unavailable'});self.assertFalse(self.rpc.starts())
        self.rpc.read_id=s.SID
        original=self.rpc
        def changing(method,params):
            value=original(method,params)
            if method=='thread/items/list':self.context['context_generation']+=1
            return value
        chat=self.module.SessionChat(changing,lambda _:str(self.project),lambda:['demo'],str(self.root/'changed-receipts'),
            model_context=lambda:dict(self.context))
        self.assertEqual(chat.live_snapshot('demo',s.SID),{'error':'unavailable'})

    def test_aggregate_real_InteractiveRPC_deadline5s(self):
        self.method() # Interface prerequisite separately identifiable on baseline.
        from websockets.sync.server import unix_serve
        socket_path=str(self.root/'rpc.sock');methods=[];timeouts=[];server_errors=[]
        native=RPC(self.project)
        def handler(ws):
            try:
                initial=json.loads(ws.recv(timeout=2));self.assertEqual(initial['method'],'initialize')
                ws.send(json.dumps({'id':initial['id'],'result':{}}));json.loads(ws.recv(timeout=2))
                while True:
                    request=json.loads(ws.recv(timeout=8));methods.append(request['method'])
                    time.sleep(2)
                    ws.send(json.dumps({'id':request['id'],'result':native(request['method'],request['params'])}))
            except Exception as error:
                # Closing the real client at deadline is expected; no assertion gets swallowed.
                if isinstance(error,AssertionError):server_errors.append(str(error))
        server=unix_serve(handler,socket_path);os.chmod(socket_path,0o600)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        self.addCleanup(worker.join,3);self.addCleanup(server.shutdown)
        class RecordingRPC(self.module.InteractiveRPC):
            def call(inner,method,params,timeout=None):
                timeouts.append(timeout);return super().call(method,params,timeout=timeout)
            def call_in_generation(inner,method,params,*,transport_generation,context_generation,timeout=None):
                timeouts.append(timeout)
                return super().call_in_generation(method,params,transport_generation=transport_generation,
                    context_generation=context_generation,timeout=timeout)
        rpc=RecordingRPC(socket_path,timeout=10);self.addCleanup(rpc.close)
        chat=self.module.SessionChat(rpc,lambda _:str(self.project),lambda:['demo'],str(self.root/'wire-receipts'),
            model_context=rpc.model_context)
        start=time.monotonic();value=chat.live_snapshot('demo',s.SID);elapsed=time.monotonic()-start
        self.assertEqual(value,{'error':'unavailable'});self.assertGreaterEqual(elapsed,4.7);self.assertLess(elapsed,6.2)
        self.assertGreaterEqual(len(timeouts),2);self.assertTrue(all(t is not None and 0<t<=5 for t in timeouts))
        self.assertGreater(timeouts[0],timeouts[-1]);self.assertFalse({'turn/start','thread/resume'}&set(methods))
        self.assertEqual(server_errors,[])

class LiveBrokerBlind(unittest.TestCase):
    def setUp(self):
        self.module=importlib.import_module('_control_web_broker')
        self.temp=tempfile.TemporaryDirectory(prefix='live-broker-blind-',dir='/var/tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root.chmod(0o700);self.path=str(self.root/'broker.sock')
        self.backend=s.Backend();self.stop=threading.Event();self.errors=[]
        def serve():
            try:self.module.serve_broker(self.path,self.backend,os.getuid(),stop_event=self.stop)
            except Exception as error:self.errors.append(type(error).__name__)
        self.worker=threading.Thread(target=serve,daemon=True);self.worker.start();self.addCleanup(self.cleanup)
        # bind() creates the pathname before listen(); probe readiness without sending an op.
        deadline=time.monotonic()+3;ready=False
        while not self.errors and time.monotonic()<deadline:
            try:
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
                    probe.settimeout(.1);probe.connect(self.path)
                ready=True;break
            except (FileNotFoundError,ConnectionRefusedError):time.sleep(.01)
        self.assertEqual(self.errors,[]);self.assertTrue(ready,'Actual private socket listening prerequisite')

    def cleanup(self):
        self.backend.gate.set();self.stop.set();self.worker.join(3)
        if self.worker.is_alive():raise RuntimeError('Synthetic broker did not stop')

    def wire(self,payload,timeout=8):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout);sock.connect(self.path);sock.sendall(s.encoded(payload)+b'\n')
            data=b''
            while b'\n' not in data:
                chunk=sock.recv(128*1024+1)
                if not chunk:break
                data+=chunk;self.assertLessEqual(len(data),128*1024)
            return json.loads(data.split(b'\n')[0])

    def payload(self):return dict(op='session_live_snapshot',project='demo',sid=s.SID)

    def test_actual_new_op_returns_envelope_instead_of_old_unknown_op(self):
        value=self.wire(self.payload());self.assertEqual(value,{'schema':1,'scope_id':'1'*64,'history':self.backend.value})
        self.assertEqual(len(self.backend.calls),1)

    def test_known_live_malformed_never_invalid_or_stale(self):
        for change in ({'sid':'bad'},{'project':'../demo'},{'cursor':None},{'op':'session_live_snapshot','extra':1}):
            with self.subTest(change=change):
                value=self.wire(self.payload()|change);self.assertEqual(value,{'error':'unavailable'})
        self.assertEqual(self.backend.calls,[])

    def test_live_reservation_busy_nonblocking_before_general_worker(self):
        self.assertEqual(self.wire(self.payload()).get('schema'),1,'Actual broker new-op admission prerequisite')
        self.backend.calls.clear();self.backend.gate.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(self.wire,self.payload());self.assertTrue(self.backend.wait_calls(1))
            start=time.monotonic();second=self.wire(self.payload(),timeout=1)
            self.assertEqual(second,{'error':'busy'});self.assertLess(time.monotonic()-start,.8)
            self.assertEqual(self.wire({'op':'snapshot'},timeout=1),{'tasks':[]})
            self.assertEqual(self.backend.maximum,1);self.backend.gate.set();self.assertEqual(first.result(3)['schema'],1)

    def test_SocketBackend_exact_old_wire_only_maps_unsupported(self):
        # Independent synthetic old-wire peer, not the new broker and not an owner failure.
        path=str(self.root/'old.sock');listener=socket.socket(socket.AF_UNIX);listener.bind(path);listener.listen(4)
        self.addCleanup(listener.close);outcomes=[{'error':'invalid_or_stale'},{'error':'stale'},{'error':'unavailable'}];received=[]
        def old_server():
            for outcome in outcomes:
                connection,_=listener.accept()
                with connection:
                    data=b''
                    while b'\n' not in data:data+=connection.recv(131073)
                    received.append(json.loads(data.split(b'\n')[0]));connection.sendall(s.encoded(outcome)+b'\n')
        client=self.module.SocketBackend(path);method=getattr(client,'session_live_snapshot',None)
        self.assertTrue(callable(method),'PUBLIC-SEAM PREREQUISITE: SocketBackend.session_live_snapshot absent')
        worker=threading.Thread(target=old_server,daemon=True);worker.start();self.addCleanup(worker.join,2)
        for expected in ('unsupported','unavailable','unavailable'):
            self.assertEqual(method('demo',s.SID),{'error':expected})
        self.assertEqual(received,[self.payload()]*3)

    def test_RegistryBackend_forwards_exact_public_live_envelope(self):
        registry=self.root/'registry';registry.mkdir(mode=0o700)
        class Chat:
            calls=[]
            def live_snapshot(inner,project,sid):
                inner.calls.append((project,sid));return {'schema':1,'scope_id':'1'*64,'history':s.history()}
        chat=Chat();backend=self.module.RegistryBackend(str(registry),str(s.ROOT/'bin'),sessions=chat)
        method=getattr(backend,'session_live_snapshot',None)
        self.assertTrue(callable(method),'PUBLIC-SEAM PREREQUISITE: RegistryBackend.session_live_snapshot absent')
        self.assertEqual(method('demo',s.SID),{'schema':1,'scope_id':'1'*64,'history':s.history()})
        self.assertEqual(chat.calls,[('demo',s.SID)])
