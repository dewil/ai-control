"""INV-NRUN-08: independent owner HTTP and private broker boundary RED."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import node_launch_red_support as s


class NodeLaunchHttpRed(s.HttpCase):
    def test_exact_owner_DTOs_commit_only_and_no_store(self):
        for path, method, body, expected, headers in (
            ('/api/node-tasks/overview','GET',None,s.overview(),()),
            ('/api/node-tasks/'+s.TASK,'GET',None,s.detail(),()),
            ('/api/node-tasks','POST',s.BODY,dict(schema=1,task=s.summary()),self.post_headers())):
            with self.subTest(path=path):
                response, value = self.response(path, method=method, body=body, headers=headers)
                self.assertEqual(response.status,200,'Approved node HTTP route is absent')
                self.assertEqual(value,expected)
                self.assertIn('no-store',response.getheader('cache-control',''))
        self.assertEqual(len(self.backend.node_calls),3,'Three fixed HTTP methods must dispatch')
        self.assertTrue(all(row['principal']=='owner' for row in self.backend.node_calls))
        self.assertEqual(self.backend.node_calls[-1], dict(op='submit',principal='owner',**s.BODY))

    def test_missing_expired_and_nonowner_before_backend(self):
        self.assert_error(401,'unauthorized',cookie=False)
        key=self.fixture.cookie.split('=',1)[1]
        for principal in (None,'project',True,1,{'principal':'owner'}):
            self.fixture.sessions[key]['principal']=principal
            self.assert_error(403,'forbidden')
        self.fixture.sessions[key]['principal']='owner'; self.fixture.now+=3601
        self.assert_error(401,'unauthorized')
        self.assertEqual(self.backend.node_calls,[])

    def test_origin_fetch_duplicate_headers_denied_before_backend(self):
        for headers in ([('Origin','https://evil.invalid')], [('Origin','null')],
                        [('Origin',self.fixture.origin)]*2, [('Sec-Fetch-Site','same-site')]):
            with self.subTest(headers=headers): self.assert_error(403,'forbidden',headers=headers)
        for headers in (self.post_headers()+[('Origin',self.fixture.origin)],
                        self.post_headers()+[('X-CSRF-Token',self.csrf)],
                        self.post_headers()[1:], self.post_headers()[:1]+self.post_headers()[2:]):
            self.assert_error(403,'forbidden',path='/api/node-tasks',method='POST',body=s.BODY,headers=headers)
        self.assertEqual(self.backend.node_calls,[])

    def test_queries_UUIDs_and_unknown_fields_rejected(self):
        for path in ('/api/node-tasks/overview?x=1','/api/node-tasks/'+s.TASK+'?x=1',
                     '/api/node-tasks/'+s.TASK.upper(),'/api/node-tasks/not-a-uuid'):
            with self.subTest(path=path): self.assert_error(422,'invalid_request',path=path)
        for body in (s.BODY|{'principal':'owner'},s.BODY|{'node_id':'other'},s.BODY|{'prompt':''},
                     s.BODY|{'prompt':'x'*32769},s.BODY|{'request_id':True},s.BODY|{'prompt':'\0'},
                     s.BODY|{'cwd':'/tmp'},s.BODY|{'model':'override'}):
            self.assert_error(422,'invalid_request',path='/api/node-tasks',method='POST',body=body,headers=self.post_headers())
        self.assertEqual(self.backend.node_calls,[])

    def test_strict_JSON_and_raw_body_limit(self):
        duplicate=s.bus.canonical(s.BODY)[:-1]+b',"prompt":"synthetic second value"}'
        for raw in (duplicate,b'{"prompt":NaN}',b'{"prompt":Infinity}',
                    b'\xff',b'[]',b'{"prompt":"\\ud800"}',b'{} trailing'):
            with self.subTest(raw=raw):
                self.assert_error(422,'invalid_request',path='/api/node-tasks',method='POST',raw=raw,headers=self.post_headers())
        self.assert_error(413,'invalid_request',path='/api/node-tasks',method='POST',raw=b' '*131073,headers=self.post_headers())
        self.assert_error(422,'invalid_request',path='/api/node-tasks',method='POST',raw=s.bus.canonical(s.BODY),
                          headers=[('Origin',self.fixture.origin),('X-CSRF-Token',self.csrf),('Content-Type','text/plain')])
        self.assertEqual(self.backend.node_calls,[])

    def test_backend_error_mapping_and_private_failures(self):
        for code,status in (('conflict',409),('capacity',429),('not_found',404),('not_ready',409),('storage',503),('unavailable',503)):
            self.backend.node_values['submit']={'error':code}
            self.assert_error(status,code,path='/api/node-tasks',method='POST',body=s.BODY,headers=self.post_headers())
        for value in (RuntimeError('synthetic private exception'),{'error':'unknown','detail':'private'},
                      s.overview()|{'credentials':'synthetic'},None):
            self.backend.node_values['overview']=value
            self.assert_error(503,'unavailable')

    def test_malformed_and_oversized_DTOs_fail_closed(self):
        for mutate in (lambda v:v['node'].update(capacity='idle'),lambda v:v.update(usage=12),
                       lambda v:v['tasks'][0].update(prompt_preview='🙂'*65),
                       lambda v:v.update(tasks=v['tasks']*51),lambda v:v['node'].update(reason='private-error')):
            value=s.overview(); mutate(value); self.backend.node_values['overview']=value
            self.assert_error(503,'unavailable')
        self.backend.node_values['submit']={'schema':1,'task':s.summary()|{'task_id':'b2222222-2222-4222-8222-222222222222'}}
        self.assert_error(503,'unavailable',path='/api/node-tasks',method='POST',body=s.BODY,headers=self.post_headers())
        value=s.detail(); value['prompt']='full prompt forbidden'; self.backend.node_values['get']=value
        self.assert_error(503,'unavailable',path='/api/node-tasks/'+s.TASK)
        value=s.detail(); value['result']={'text':'🙂'*16000,'executor':'codex'}; self.backend.node_values['get']=value
        self.assert_error(503,'unavailable',path='/api/node-tasks/'+s.TASK)

    def test_exact_body_retry_preserves_UUID_after_503(self):
        self.backend.node_values['submit']={'error':'unavailable'}
        self.assert_error(503,'unavailable',path='/api/node-tasks',method='POST',body=s.BODY,headers=self.post_headers())
        self.backend.node_values['submit']={'schema':1,'task':s.summary()}
        response,value=self.response('/api/node-tasks',method='POST',body=s.BODY,headers=self.post_headers())
        self.assertEqual(response.status,200); self.assertEqual(value['task']['task_id'],s.TASK)
        self.assertEqual(self.backend.node_calls[0],self.backend.node_calls[1])

    def test_auth_revoked_while_call_pending_fences_success(self):
        self.backend.node_gate.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.response)
            entered=self.backend.wait_node(1)
            if not entered:
                self.backend.node_gate.set(); future.result()
            self.assertTrue(entered,'Public node dispatch prerequisite')
            self.fixture.sessions.clear(); self.backend.node_gate.set()
            response,value=future.result(3)
        self.assertEqual(response.status,401); self.assertEqual(value,{'error':'unauthorized'})


class NodeLaunchBrokerRed(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='node-launch-broker-red-',dir='/var/tmp'); self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'broker.sock'); self.backend=s.Backend(); self.stop=threading.Event(); self.errors=[]
        broker=importlib.import_module('_control_web_broker')
        def run():
            try: broker.serve_broker(self.path,self.backend,os.getuid(),stop_event=self.stop)
            except Exception as error: self.errors.append(type(error).__name__)
        self.worker=threading.Thread(target=run,daemon=True); self.worker.start(); self.addCleanup(self.cleanup)
        deadline=time.monotonic()+3
        while not Path(self.path).exists() and not self.errors and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual(self.errors,[]); self.assertTrue(Path(self.path).exists())

    def cleanup(self):
        self.backend.node_gate.set(); self.stop.set(); self.worker.join(5)
        self.assertFalse(self.worker.is_alive(),'Bounded fake broker cleanup')

    def wire(self,request):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
            peer.settimeout(4); peer.connect(self.path); peer.sendall(s.bus.canonical(request)+b'\n')
            data=b''
            while b'\n' not in data:
                block=peer.recv(262145)
                if not block: break
                data+=block
                self.assertLessEqual(len(data),262145)
        return data,json.loads(data.split(b'\n')[0])

    def test_fixed_ops_exact_principal_and_submit_fields(self):
        for request,expected in ((dict(op='node_tasks_overview',principal='owner'),s.overview()),
            (dict(op='node_task_get',principal='owner',task_id=s.TASK),s.detail()),
            (dict(op='node_task_submit',principal='owner',**s.BODY),dict(schema=1,task=s.summary()))):
            with self.subTest(op=request['op']): self.assertEqual(self.wire(request)[1],expected)

    def test_broker_revalidates_owner_fields_UUID_and_prompt(self):
        base=dict(op='node_task_submit',principal='owner',**s.BODY)
        for request,code in ((base|{'principal':'project'},'forbidden'),(base|{'request_id':s.TASK.upper()},'invalid_request'),
                             (base|{'prompt':'x'*32769},'invalid_request'),(base|{'subject':'devbus.commands.other'},'invalid_request')):
            with self.subTest(request=list(request)): self.assertEqual(self.wire(request)[1],{'error':code})
        self.assertEqual(self.backend.node_calls,[])

    def test_detail_large_Unicode_reply_and_legacy_limit_stays_128KiB(self):
        value=s.detail(); value['result']={'text':'🙂'*14900,'executor':'codex'}
        self.backend.node_values['get']=value
        wire,result=self.wire(dict(op='node_task_get',principal='owner',task_id=s.TASK))
        self.assertEqual(result,value,'Valid bounded Unicode detail must survive actual broker wire')
        self.assertLessEqual(len(wire),96*1024)
        self.backend.snapshot=lambda:{'tasks':['🙂'*40000]}
        self.assertEqual(self.wire({'op':'snapshot'})[1],{'error':'unavailable'})

    def test_single_reserved_node_operation_slot(self):
        self.backend.node_gate.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self.wire,dict(op='node_tasks_overview',principal='owner'))
            entered=self.backend.wait_node(1)
            if not entered:
                self.backend.node_gate.set(); pending.result()
            self.assertTrue(entered,'Public node broker dispatch prerequisite')
            result=self.wire(dict(op='node_task_get',principal='owner',task_id=s.TASK))[1]
            self.backend.node_gate.set(); pending.result(3)
        self.assertIn(result,({'error':'busy'},{'error':'unavailable'}))
        self.assertEqual(len(self.backend.node_calls),1)
