"""Real local HTTP + same-UID Unix broker core boundaries; no native services."""
from copy import deepcopy
import importlib
import json
import os
import tempfile
from pathlib import Path
import unittest
from fastapi.testclient import TestClient
import native_queue_blind_support as s
from test_control_web_session_chat_contract import ORIGIN, PASSWORD, SECRET, feature
import test_control_web_session_models_http_broker as old


class NativeQueueHTTPBlind(unittest.TestCase):
    def setUp(self):
        self.web=feature(self,'_control_web');self.backend=s.QueueBackend();self.now=1800000000
        self.temp=tempfile.TemporaryDirectory(prefix='queue-http-blind-',dir='/var/tmp');self.addCleanup(self.temp.cleanup)
        replay=Path(self.temp.name)/'totp.json';replay.write_text('{"last_step":-1}');replay.chmod(0o600)
        config=dict(origin=ORIGIN,username='owner',password_hash=self.web.hash_password(PASSWORD),totp_secret=SECRET,
                    session_ttl=60,secure_cookie=True,totp_state_path=str(replay))
        self.client=TestClient(self.web.create_app(config,self.backend,clock=lambda:self.now),base_url=ORIGIN)
        self.addCleanup(self.client.close)
        self.path=f'/api/session-queue?project=demo&sid={s.SID}'
        self.payload=dict(project='demo',sid=s.SID,message_id=s.MID,text=s.TEXT)
        self.cancel_payload=dict(project='demo',sid=s.SID,queued_submission_id=s.QID,action_id=s.ACTION)
    def login(self):
        response=self.client.post('/api/login',json=dict(username='owner',password=PASSWORD,totp=self.web.totp_code(SECRET,self.now)),headers={'Origin':ORIGIN})
        self.assertEqual(response.status_code,200,response.text)
        self.csrf=self.client.get('/api/session').json()['csrf']
    def headers(self):return {'Origin':ORIGIN,'X-CSRF-Token':self.csrf}

    def test_supported_native_rows_exact_read_DTO_no_store_and_busy_sendnow_unavailable(self):
        # INV-SQUEUE-01 INV-SQUEUE-04 INV-SQUEUE-08; approved transfer adds a route,
        # while this inactive-turn fixture still honestly advertises disabled.
        self.login();response=self.client.get(self.path)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),s.queue_dto());self.assertIn('no-store',response.headers.get('cache-control',''))
        self.assertFalse(response.json()['send_now_supported'])
        self.assertEqual(self.backend.calls,[('queue','demo',s.SID)])

    def test_unauthenticated_and_expired_sessions_never_reach_queue(self):
        # INV-SQUEUE-01
        for method,path,payload in [('get',self.path,None),('post','/api/session-queue',self.payload),('post','/api/session-queue-cancel',self.cancel_payload)]:
            with self.subTest(path=path):
                response=getattr(self.client,method)(path,**({'json':payload,'headers':{'Origin':ORIGIN}} if payload else {}))
                self.assertEqual(response.status_code,401)
        self.login();self.now+=61
        self.assertEqual(self.client.get(self.path).status_code,401);self.assertEqual(self.backend.calls,[])

    def test_query_rejects_unknown_duplicate_and_private_scope_inputs(self):
        # INV-SQUEUE-01
        self.login()
        for suffix in ['&account=private','&socket=/private/socket','&root=/private','&sid='+s.OTHER,'&project=other']:
            with self.subTest(suffix=suffix):self.assertEqual(self.client.get(self.path+suffix).status_code,422)
        self.assertEqual(self.backend.calls,[])

    def test_foreign_Origin_rejected_and_absent_get_Origin_allowed(self):
        # INV-SQUEUE-01
        self.login();self.assertEqual(self.client.get(self.path,headers={'Origin':'https://evil.example.test'}).status_code,403)
        self.assertEqual(self.backend.calls,[])
        self.assertEqual(self.client.get(self.path).status_code,200)

    def test_enqueue_and_Mac_cancel_forward_only_exact_public_arguments(self):
        # INV-SQUEUE-02 INV-SQUEUE-05
        self.login();response=self.client.post('/api/session-queue',json=self.payload,headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),dict(status='queued',message_id=s.MID,queued_submission_id=s.QID))
        response=self.client.post('/api/session-queue-cancel',json=self.cancel_payload,headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),dict(status='cancelled',message_id=s.ACTION,queued_submission_id=s.QID))
        self.assertEqual(self.backend.calls,[('enqueue','demo',s.SID,s.MID,s.TEXT,None),('cancel','demo',s.SID,s.QID,s.ACTION)])

    def test_mutations_require_both_Origin_and_fresh_CSRF(self):
        # INV-SQUEUE-01
        self.login()
        for path,payload in [('/api/session-queue',self.payload),('/api/session-queue-cancel',self.cancel_payload)]:
            for headers in [{},{'Origin':ORIGIN},{'X-CSRF-Token':self.csrf},{'Origin':ORIGIN,'X-CSRF-Token':'wrong'},
                            {'Origin':'https://evil.example.test','X-CSRF-Token':self.csrf}]:
                with self.subTest(path=path,headers=list(headers)):self.assertEqual(self.client.post(path,json=payload,headers=headers).status_code,403)
        self.assertEqual(self.backend.calls,[])

    def test_mutation_DTO_rejects_extra_scope_types_and_duplicate_JSON_keys(self):
        # INV-SQUEUE-01 INV-SQUEUE-02 INV-SQUEUE-05
        self.login()
        cases=[('/api/session-queue',{**self.payload,'account':'private'}),('/api/session-queue',{**self.payload,'sid':s.SID[:8]}),
               ('/api/session-queue',{**self.payload,'text':'  '}),('/api/session-queue',{**self.payload,'message_id':True}),
               ('/api/session-queue-cancel',{**self.cancel_payload,'text':'front-end snapshot'}),
               ('/api/session-queue-cancel',{**self.cancel_payload,'queued_submission_id':7}),
               ('/api/session-queue-cancel',{**self.cancel_payload,'action_id':'not-uuid'})]
        for path,payload in cases:
            with self.subTest(path=path,keys=list(payload)):self.assertEqual(self.client.post(path,json=payload,headers=self.headers()).status_code,422)
        raw=json.dumps(self.payload)[:-1]+',"message_id":"'+s.OTHER+'"}'
        response=self.client.post('/api/session-queue',content=raw,headers={**self.headers(),'Content-Type':'application/json'})
        self.assertEqual(response.status_code,422);self.assertEqual(self.backend.calls,[])

    def test_existing_send_status_exposes_queued_schema_and_honest_cancel_results(self):
        # INV-SQUEUE-05 INV-SQUEUE-08
        self.login();response=self.client.get(f'/api/session-send-status?project=demo&sid={s.SID}&message_id={s.MID}')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),dict(status='queued',message_id=s.MID,queued_submission_id=s.QID))
        for state in ['changed','delivery_unknown']:
            self.backend.cancel_status=state
            response=self.client.post('/api/session-queue-cancel',json=self.cancel_payload,headers=self.headers())
            # Owner's explicit clarification: POST unknown uses existing chat503,
            # GET receipt reconciliation remains200; changed is a normal200.
            self.assertEqual(response.status_code,503 if state=='delivery_unknown' else 200,response.text)
            self.assertEqual(response.json()['status'],state)


class NativeQueueBrokerBlind(unittest.TestCase):
    # Reuse only bounded socket lifecycle helpers, no inherited model test cases.
    start=old.SessionModelsBroker.start
    shutdown=old.SessionModelsBroker.shutdown
    wire=old.SessionModelsBroker.wire
    def setUp(self):old.SessionModelsBroker.setUp(self);self.backend=s.QueueBackend()
    def test_registry_backend_forwards_only_public_queue_arguments(self):
        # INV-SQUEUE-01 INV-SQUEUE-05; override inherited case with core seams.
        class Chat:
            def __init__(self):self.calls=[]
            def queue(self,project,sid):self.calls.append(('queue',project,sid));return s.queue_dto()
            def enqueue(self,project,sid,mid,text,selection=None):self.calls.append(('enqueue',project,sid,mid,text,selection));return dict(status='queued',message_id=mid,queued_submission_id=s.QID)
            def cancel_queued(self,project,sid,qid,action):self.calls.append(('cancel',project,sid,qid,action));return dict(status='cancelled',message_id=action,queued_submission_id=qid)
        registry=self.base/'registry';registry.mkdir(mode=0o700);chat=Chat()
        backend=self.module.RegistryBackend(str(registry),str(s.ROOT/'bin'),sessions=chat)
        for name,args,status in [('session_queue',('demo',s.SID),None),('session_enqueue',('demo',s.SID,s.MID,s.TEXT),'queued'),('session_queue_cancel',('demo',s.SID,s.QID,s.ACTION),'cancelled')]:
            with self.subTest(method=name):
                target=getattr(backend,name,None);self.assertTrue(callable(target),'Public RegistryBackend queue seam missing')
                result=target(*args)
                if status:self.assertEqual(result['status'],status)
                else:self.assertEqual(result,s.queue_dto())
        self.assertEqual(chat.calls,[('queue','demo',s.SID),('enqueue','demo',s.SID,s.MID,s.TEXT,None),('cancel','demo',s.SID,s.QID,s.ACTION)])
    def test_owner_allowlisted_queue_operations_roundtrip_public_DTO(self):
        # Override legacy test with the queue operation (same real Unix boundary).
        self.start();self.assertEqual(self.wire(dict(op='session_queue',project='demo',sid=s.SID)),s.queue_dto())
        self.assertEqual(self.wire(dict(op='session_enqueue',project='demo',sid=s.SID,message_id=s.MID,text=s.TEXT))['status'],'queued')
        self.assertEqual(self.wire(dict(op='session_queue_cancel',project='demo',sid=s.SID,queued_submission_id=s.QID,action_id=s.ACTION))['status'],'cancelled')
    def test_owner_rejects_extra_missing_wrong_and_duplicate_fields_before_backend(self):
        self.start()
        good=dict(op='session_queue_cancel',project='demo',sid=s.SID,queued_submission_id=s.QID,action_id=s.ACTION)
        for request in [{**good,'socket':'/private'}, {**good,'account':'private'}, {**good,'queued_submission_id':True},
                        {**good,'action_id':'short'}, {key:value for key,value in good.items() if key!='sid'},
                        json.dumps(good)[:-1]+',"sid":"'+s.OTHER+'"}']:
            with self.subTest(shape=type(request).__name__):
                if isinstance(request,str):request=request.encode()
                self.assertEqual(self.wire(request).get('error'),'invalid_request')
        self.assertEqual(self.backend.calls,[])
    def test_socket_backend_exposes_fixed_session_queue_operation(self):
        self.start();client=self.module.SocketBackend(self.socket_path)
        method=getattr(client,'session_queue',None);self.assertTrue(callable(method),'SocketBackend.session_queue missing')
        self.assertEqual(method('demo',s.SID),s.queue_dto())
    def test_wrong_peer_UID_never_reaches_backend(self):
        original=self.module.serve_broker
        def wrong_uid(path,backend,uid,**kwargs):return original(path,backend,uid+1,**kwargs)
        from unittest.mock import patch
        with patch.object(self.module,'serve_broker',wrong_uid):
            self.start()
            try:result=self.wire(dict(op='session_queue',project='demo',sid=s.SID))
            except (ConnectionResetError,EOFError,json.JSONDecodeError):result={'error':'forbidden'}
        self.assertIn(result.get('error'),['forbidden','unavailable','invalid_request']);self.assertEqual(self.backend.calls,[])
