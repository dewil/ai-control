"""INV-CAP-07/08 fixed capability DTO, authenticated HTTP and owner wire."""
import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from fastapi.testclient import TestClient
from test_control_web_session_chat_contract import ORIGIN, PASSWORD, SECRET, SID
import test_control_web_session_models_http_broker as models_fixture
from test_control_web_read_capabilities_support import ROOT, expected_capabilities


class Backend:
    def __init__(self): self.calls=[];self.outcome=expected_capabilities()
    def snapshot(self): return {'tasks':[]}
    def session_capabilities(self,project,sid):
        self.calls.append(('session_capabilities',project,sid));return copy.deepcopy(self.outcome)


class CapabilitiesHTTPBlind(unittest.TestCase):
    def setUp(self):
        self.web=importlib.import_module('_control_web');self.backend=Backend();self.now=1800000000;self.records={}
        config={'origin':ORIGIN,'password_hash':self.web.hash_password(PASSWORD),'totp_secret':SECRET,'session_ttl':60,'secure_cookie':True}
        self.client=TestClient(self.web.create_app(config,self.backend,clock=lambda:self.now,session_store=self.records),base_url=ORIGIN)
        self.addCleanup(self.client.close);self.path='/api/session-capabilities?project=demo&sid='+SID

    def login(self):
        result=self.client.post('/api/login',json={'username':'owner','password':PASSWORD,'totp':self.web.totp_code(SECRET,self.now)},headers={'Origin':ORIGIN})
        self.assertEqual(result.status_code,200)

    def test_authentication_is_checked_before_capability_backend(self):
        result=self.client.get(self.path);self.assertEqual(result.status_code,401)
        self.assertEqual(result.json(),{'error':'unauthorized'});self.assertEqual(self.backend.calls,[])

    def test_exact_safe_dto_and_no_store_without_old_api_extra_fields(self):
        self.login();result=self.client.get(self.path)
        self.assertEqual(result.status_code,200);self.assertEqual(result.json(),expected_capabilities())
        self.assertIn('no-store',result.headers.get('cache-control',''))
        self.assertEqual(self.backend.calls,[('session_capabilities','demo',SID)])

    def test_expired_and_revoked_current_cookie_cannot_read_capabilities(self):
        self.login();self.now+=61
        self.assertEqual(self.client.get(self.path).status_code,401);self.assertEqual(self.backend.calls,[])
        self.now=1800000100;self.login();self.records.clear()
        self.assertEqual(self.client.get(self.path).status_code,401);self.assertEqual(self.backend.calls,[])

    def test_foreign_origin_and_fetch_metadata_never_dispatch(self):
        self.login()
        for headers in ({'Origin':'https://foreign.example.test'},{'Origin':'null'},{'Sec-Fetch-Site':'cross-site'}):
            with self.subTest(headers=headers):self.assertEqual(self.client.get(self.path,headers=headers).status_code,403)
        self.assertEqual(self.backend.calls,[])

    def test_exact_query_shape_rejects_repeat_extra_scope_and_bad_sid(self):
        self.login()
        invalid=['/api/session-capabilities','/api/session-capabilities?project=demo',self.path+'&extra=x',
            self.path+'&sid='+SID,self.path+'&project=demo','/api/session-capabilities?project=../private&sid='+SID,
            '/api/session-capabilities?project=demo&sid='+SID[:8]]
        for path in invalid:
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,422)
        self.assertEqual(self.backend.calls,[])

    def test_access_errors_keep_existing_closed_envelopes(self):
        self.login()
        for error,status in (('invalid_request',422),('forbidden',403),('stale',409),('unavailable',503)):
            with self.subTest(error=error):
                self.backend.outcome={'error':error};result=self.client.get(self.path)
                self.assertEqual(result.status_code,status);self.assertEqual(result.json(),{'error':error})

    def test_strict_output_rejects_private_extra_keys_bool_schema_and_inconsistent_capabilities(self):
        self.login();base=expected_capabilities()
        variants=[base|{'private_path':'SYNTHETIC_PRIVATE_NATIVE_PATH'},base|{'schema':True},base|{'read_status':'guessed'},
            base|{'version_source':'binary_attested'},base|{'native_version':None},base|{'native_version':'raw codex/0.999.0 /path'},
            base|{'operations':base['operations']|{'extra_operation':{'supported':True,'reason':None}}}]
        for operation in ({'supported':'true','reason':None},{'supported':True,'reason':'not_observed'},
                          {'supported':False,'reason':None},{'supported':False,'reason':'future_reason'},
                          {'supported':True,'reason':None,'private':True}):
            changed=copy.deepcopy(base);changed['operations']['sessions_read']=operation;variants.append(changed)
        for value in variants:
            with self.subTest(dto=value):
                self.backend.outcome=value;result=self.client.get(self.path)
                self.assertEqual(result.status_code,503);self.assertEqual(result.json(),{'error':'unavailable'})
                self.assertNotIn('SYNTHETIC_PRIVATE',result.text)

    def test_null_version_and_observed_history_valid_dtos_are_preserved(self):
        self.login()
        for dto in (expected_capabilities(None),expected_capabilities(history=True)):
            with self.subTest(dto=dto):
                self.backend.outcome=dto;result=self.client.get(self.path)
                self.assertEqual(result.status_code,200);self.assertEqual(result.json(),dto)


class CapabilitiesBrokerBlind(unittest.TestCase):
    for name in ('start','shutdown','wire'): locals()[name]=getattr(models_fixture.SessionModelsBroker,name)
    def setUp(self):
        self.module=importlib.import_module('_control_web_broker')
        temp=tempfile.TemporaryDirectory(prefix='cap-broker-blind-',dir='/var/tmp');self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.base.chmod(0o700);self.socket_path=str(self.base/'broker.sock')
        self.backend=Backend();self.stop=threading.Event();self.errors=[];self.worker=None

    def test_fixed_owner_operation_returns_exact_dto_and_no_other_dispatch(self):
        self.start();value=self.wire({'op':'session_capabilities','project':'demo','sid':SID})
        self.assertEqual(value,expected_capabilities());self.assertEqual(self.backend.calls,[('session_capabilities','demo',SID)])

    def test_broker_rejects_extra_duplicate_and_bad_scope_before_backend(self):
        self.start()
        requests=[{'op':'session_capabilities','project':'demo','sid':SID,'rpc_method':'thread/resume'},
            {'op':'session_capabilities','project':'demo'}, {'op':'session_capabilities','project':'../private','sid':SID},
            {'op':'session_capabilities','project':'demo','sid':True},
            ('{"op":"session_capabilities","project":"demo","sid":"'+SID+'","sid":"'+SID+'"}').encode()]
        for request in requests:
            with self.subTest(request=request):self.assertEqual(set(self.wire(request)),{'error'})
        self.assertEqual(self.backend.calls,[])

    def test_socket_backend_exposes_only_fixed_capabilities_call(self):
        self.start();client=self.module.SocketBackend(self.socket_path);method=getattr(client,'session_capabilities',None)
        self.assertTrue(callable(method),'PUBLIC-SEAM PREREQUISITE: SocketBackend.session_capabilities')
        self.assertEqual(method('demo',SID),expected_capabilities());self.assertEqual(self.backend.calls,[('session_capabilities','demo',SID)])

    def test_registry_backend_forwards_project_sid_to_actual_public_chat_seam(self):
        calls=[]
        class Chat:
            def capabilities(inner,project,sid):calls.append((project,sid));return expected_capabilities()
        registry=self.base/'registry';registry.mkdir(mode=0o700)
        backend=self.module.RegistryBackend(str(registry),str(ROOT/'bin'),sessions=Chat())
        method=getattr(backend,'session_capabilities',None)
        self.assertTrue(callable(method),'PUBLIC-SEAM PREREQUISITE: RegistryBackend.session_capabilities')
        self.assertEqual(method('demo',SID),expected_capabilities());self.assertEqual(calls,[('demo',SID)])

    def test_owner_output_validator_does_not_forward_private_capability_fields(self):
        self.start();self.backend.outcome=expected_capabilities()|{'private_native':'SYNTHETIC_PRIVATE'}
        result=self.wire({'op':'session_capabilities','project':'demo','sid':SID})
        self.assertEqual(result,{'error':'unavailable'});self.assertNotIn('SYNTHETIC_PRIVATE',json.dumps(result))
