"""INV-PART-01/03/04/07 real local HTTP and same-UID Unix broker boundary RED."""
from copy import deepcopy
import importlib
import inspect
import json
import os
import socket
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import live_sse_blind_support as live
import test_control_web_session_models_http_broker as old
import participation_blind_support as s


class ParticipationBackend(live.Backend):
    def __init__(self):
        super().__init__();self.part_calls=[];self.overview=s.overview_dto();self.selected=s.questions_dto()
        self.answer_value=s.action_dto();self.error=None
    def participation_overview(self):
        self.part_calls.append(('overview',));return deepcopy(self.error or self.overview)
    def session_questions(self,project,sid):
        self.part_calls.append(('questions',project,sid));return deepcopy(self.error or self.selected)
    def session_question_answer(self,project,sid,epoch,interaction_id,action_id,answers):
        self.part_calls.append(('answer',project,sid,epoch,interaction_id,action_id,deepcopy(answers)))
        result=deepcopy(self.error or self.answer_value)
        if 'action_id' in result:result['action_id']=action_id
        return result


class ParticipationHTTPBlind(unittest.TestCase):
    def setUp(self):
        with patch.object(live,'Backend',ParticipationBackend):self.fixture=live.Fixture(session_store=True)
        self.addCleanup(self.fixture.stop);self.login=self.fixture.login();self.backend=self.fixture.backend
        self.body=dict(project='demo',sid=s.SID,epoch=s.EPOCH,interaction_id=s.HANDLE,action_id=s.ACTION,answers=deepcopy(s.ANSWER))
        self.routes=[('GET','/api/participation-overview',None),
            ('GET','/api/session-questions?project=demo&sid='+s.SID,None),
            ('POST','/api/session-question-answer',self.body)]
    def request(self,path,method='GET',body=None,cookie=True,headers=None):
        connection,response=self.fixture.request(path,method=method,body=body,cookie=cookie,
            headers=headers if headers is not None else [('Origin',self.fixture.origin),('X-CSRF-Token',self.login['csrf'])])
        raw=response.read();connection.close()
        try:value=json.loads(raw)
        except (json.JSONDecodeError,UnicodeDecodeError):value={'non_json':True}
        return response,value

    def test_INV_PART_01_owner_GETs_exact_DTO_no_store_and_no_mutation(self):
        # INV-PART-01
        for path,expected in [(self.routes[0][1],self.backend.overview),(self.routes[1][1],self.backend.selected)]:
            response,value=self.request(path)
            self.assertEqual(response.status,200);self.assertEqual(value,expected)
            self.assertIn('no-store',response.getheader('cache-control',''))
        self.assertEqual(self.backend.part_calls,[('overview',),('questions','demo',s.SID)])

    def test_INV_PART_01_owner_only_ALL_routes_reject_verified_nonowner_before_backend(self):
        # INV-PART-01
        self.assertTrue(self.fixture.session_store_supported,'Existing public session_store fixture required')
        record=self.fixture.sessions[self.fixture.cookie.split('=',1)[1]]
        for principal in [None,'project',1,True,{'principal':'owner'}]:
            if principal is None:record.pop('principal',None)
            else:record['principal']=principal
            for method,path,body in self.routes:
                with self.subTest(principal_type=type(principal).__name__,path=path):
                    response,value=self.request(path,method,body)
                    self.assertEqual(response.status,403);self.assertEqual(value,{'error':'forbidden'})
        self.assertEqual(self.backend.part_calls,[])

    def test_INV_PART_01_ALL_routes_require_current_auth_before_backend(self):
        # INV-PART-01
        for method,path,body in self.routes:
            response,_=self.request(path,method,body,cookie=False)
            self.assertEqual(response.status,401)
        self.fixture.now+=3601
        for method,path,body in self.routes:self.assertEqual(self.request(path,method,body)[0].status,401)
        self.assertEqual(self.backend.part_calls,[])

    def test_INV_PART_01_answer_requires_exact_origin_and_CSRF_before_backend(self):
        # INV-PART-01
        for headers in [[],[('Origin',self.fixture.origin)],
            [('X-CSRF-Token',self.login['csrf'])],
            [('Origin','https://evil.invalid'),('X-CSRF-Token',self.login['csrf'])],
            [('Origin',self.fixture.origin),('X-CSRF-Token','wrong')]]:
            response,_=self.request('/api/session-question-answer','POST',self.body,headers=headers)
            self.assertEqual(response.status,403)
        self.assertEqual(self.backend.part_calls,[])

    def test_INV_PART_03_exact_answer_arguments_and_closed_unknown_DTO_preserved(self):
        # INV-PART-03 INV-PART-04
        self.backend.answer_value=s.action_dto('closed','delivery_unknown')
        response,value=self.request('/api/session-question-answer','POST',self.body)
        self.assertEqual(response.status,200);self.assertEqual(value,self.backend.answer_value)
        self.assertEqual(self.backend.part_calls,[('answer','demo',s.SID,s.EPOCH,s.HANDLE,s.ACTION,s.ANSWER)])

    def test_INV_PART_03_closed_fields_and_nativeID_never_accepted_from_browser(self):
        # INV-PART-03
        for body in [{**self.body,'native_id':7},{**self.body,'method':'arbitrary/response'},
            {**self.body,'socket':'/private'},{**self.body,'root':'/private'},
            {**self.body,'account':'private'},{**self.body,'epoch':'A'*32},
            {**self.body,'answers':[]},{**self.body,'action_id':True},
            {**self.body,'answers':{'choice':{'answers':['x'*8001]}}},
            {**self.body,'answers':{'choice':{'answers':['\U0001f600'*8000+'x']}}}]:
            with self.subTest(keys=list(body)):
                self.assertEqual(self.request('/api/session-question-answer','POST',body)[0].status,422)
        self.assertEqual(self.backend.part_calls,[])

    def test_INV_PART_03_duplicate_JSON_keys_rejected_before_backend(self):
        # INV-PART-03
        import http.client
        raw=json.dumps(self.body)[:-1]+',"action_id":"'+s.ACTION2+'"}'
        nested=json.dumps(self.body).replace('"Exact option A"]','"Exact option A"],"answers":["Exact option B"]')
        for value in [raw,nested]:
            connection=http.client.HTTPConnection('127.0.0.1',self.fixture.port,timeout=3)
            connection.request('POST','/api/session-question-answer',body=value,headers={
                'Cookie':self.fixture.cookie,'Origin':self.fixture.origin,'X-CSRF-Token':self.login['csrf'],
                'Content-Type':'application/json'})
            response=connection.getresponse();response.read();connection.close()
            self.assertEqual(response.status,422)
        self.assertEqual(self.backend.part_calls,[])

    def test_INV_PART_01_GET_unknown_duplicate_scope_fields_fail_before_backend(self):
        # INV-PART-01
        for path in ['/api/participation-overview?project=demo','/api/participation-overview?account=x',
            self.routes[1][1]+'&sid='+s.OTHER,self.routes[1][1]+'&socket=/private',
            '/api/session-questions?project=demo&sid=short']:
            self.assertEqual(self.request(path)[0].status,422)
        self.assertEqual(self.backend.part_calls,[])

    def test_INV_PART_01_no_approval_reply_or_arbitrary_rpc_route(self):
        # INV-PART-01
        for path in ['/api/session-approval-answer','/api/session-approval-response',
                     '/api/session-callback-response','/api/participation-response']:
            response,_=self.request(path,'POST',dict(project='demo',sid=s.SID,id=7,result={'decision':'accept'}))
            self.assertIn(response.status,[404,405])
        self.assertEqual(self.backend.part_calls,[])

    def test_INV_PART_07_POST_stream_bound_and_backend_error_mapping(self):
        # INV-PART-07
        oversized={**self.body,'answers':{'choice':{'answers':['x'*65537]}}}
        self.assertEqual(self.request('/api/session-question-answer','POST',oversized)[0].status,422)
        self.assertEqual(self.backend.part_calls,[])
        for error,status in [('invalid_request',422),('stale',409),('forbidden',403),('unavailable',503)]:
            self.backend.error={'error':error}
            response,value=self.request('/api/session-question-answer','POST',self.body)
            self.assertEqual(response.status,status);self.assertEqual(value,{'error':error})


class ParticipationBrokerBlind(unittest.TestCase):
    start=old.SessionModelsBroker.start
    shutdown=old.SessionModelsBroker.shutdown
    wire=old.SessionModelsBroker.wire
    def setUp(self):
        old.SessionModelsBroker.setUp(self);self.backend=ParticipationBackend()
        self.requests=[dict(op='participation_overview'),dict(op='session_questions',project='demo',sid=s.SID),
            dict(op='session_question_answer',project='demo',sid=s.SID,epoch=s.EPOCH,interaction_id=s.HANDLE,action_id=s.ACTION,answers=deepcopy(s.ANSWER))]
    def test_INV_PART_01_fixed_ops_roundtrip_over_actual_owner_socket(self):
        # INV-PART-01
        self.start()
        for request,expected in zip(self.requests,[self.backend.overview,self.backend.selected,self.backend.answer_value]):
            self.assertEqual(self.wire(request),expected)
        self.assertEqual(self.backend.part_calls,[('overview',),('questions','demo',s.SID),
            ('answer','demo',s.SID,s.EPOCH,s.HANDLE,s.ACTION,s.ANSWER)])
    def test_INV_PART_01_SocketBackend_fixed_public_names(self):
        # INV-PART-01
        self.start();client=self.module.SocketBackend(self.socket_path)
        for name,args,expected in [('participation_overview',(),self.backend.overview),
            ('session_questions',('demo',s.SID),self.backend.selected),
            ('session_question_answer',('demo',s.SID,s.EPOCH,s.HANDLE,s.ACTION,s.ANSWER),self.backend.answer_value)]:
            call=getattr(client,name,None);self.assertTrue(callable(call),'Missing public SocketBackend.'+name)
            self.assertEqual(call(*args),expected)
    def test_INV_PART_01_registry_delegates_exact_owner_methods(self):
        # INV-PART-01
        class Chat:
            def participation_overview(inner):return self.backend.participation_overview()
            def questions(inner,*args):return self.backend.session_questions(*args)
            def answer_question(inner,*args):return self.backend.session_question_answer(*args)
        registry=self.base/'registry';registry.mkdir(mode=0o700)
        backend=self.module.RegistryBackend(str(registry),str(s.ROOT/'bin'),sessions=Chat())
        for name,args in [('participation_overview',()),('session_questions',('demo',s.SID)),
            ('session_question_answer',('demo',s.SID,s.EPOCH,s.HANDLE,s.ACTION,s.ANSWER))]:
            call=getattr(backend,name,None);self.assertTrue(callable(call),'Missing public RegistryBackend.'+name);call(*args)
        self.assertEqual(self.backend.part_calls,[('overview',),('questions','demo',s.SID),
            ('answer','demo',s.SID,s.EPOCH,s.HANDLE,s.ACTION,s.ANSWER)])
    def test_INV_PART_01_wrong_peer_UID_and_arbitrary_callback_no_backend(self):
        # INV-PART-01
        original=self.module.serve_broker
        def wrong_uid(path,backend,uid,**kwargs):return original(path,backend,uid+1,**kwargs)
        with patch.object(self.module,'serve_broker',wrong_uid):
            self.start()
            for request in self.requests:
                try:result=self.wire(request)
                except (ConnectionResetError,EOFError,json.JSONDecodeError):result={'error':'forbidden'}
                self.assertIn('error',result)
        self.assertEqual(self.backend.part_calls,[])
    def test_INV_PART_03_closed_op_shapes_reject_duplicate_and_arbitrary_response(self):
        # INV-PART-03
        self.start();answer=self.requests[-1]
        invalid=[{**r,'root':'/private'} for r in self.requests]+[
            {**answer,'id':7},{**answer,'method':'item/tool/requestUserInput'},
            {**answer,'result':{'answers':s.ANSWER}},
            {**answer,'epoch':'short'},{**answer,'sid':True},
            dict(op='callback_response',id=7,result={'answers':s.ANSWER}),
            (json.dumps(answer)[:-1]+',"action_id":"'+s.ACTION2+'"}').encode()]
        for request in invalid:self.assertIn('error',self.wire(request))
        self.assertEqual(self.backend.part_calls,[])
