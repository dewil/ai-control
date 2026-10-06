"""Public HTTP/broker INV-WSESS-18 transport, synthetic backend only."""
import importlib
from pathlib import Path
import sys
import unittest
from fastapi.testclient import TestClient
import test_control_web_session_chat_broker as broker_fixture

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bin'))
ORIGIN='https://summary.example.test'
PASSWORD='synthetic-summary-transport-password'
SECRET='JBSWY3DPEHPK3PXP'
SUMMARY={'projects':[{'name':'demo','session_count':12,'last_activity':123,'summary_state':'fresh','as_of':1800000000}]}


class Backend(broker_fixture.Backend):
    def session_project_summary(self):
        self.record('summary')
        return SUMMARY


class SummaryHTTPContract(unittest.TestCase):
    def setUp(self):
        self.web=importlib.import_module('_control_web'); self.backend=Backend(); self.now=1800000000
        self.client=TestClient(self.web.create_app({'origin':ORIGIN,'password_hash':self.web.hash_password(PASSWORD),
            'totp_secret':SECRET,'session_ttl':60,'secure_cookie':True},self.backend,clock=lambda:self.now),base_url=ORIGIN)
        self.addCleanup(self.client.close)
    def login(self):
        response=self.client.post('/api/login',json={'username': 'owner', 'password':PASSWORD,'totp':self.web.totp_code(SECRET,self.now)},headers={'Origin':ORIGIN})
        self.assertEqual(response.status_code,200)
    def test_INV_WSESS_18_http_requires_auth_and_never_calls_backend_before_login(self):
        self.assertEqual(self.client.get('/api/session-project-summary').status_code,401)
        self.assertEqual(self.backend.calls,[])
    def test_INV_WSESS_18_http_fixed_summary_no_store_and_no_history_actions(self):
        self.login(); response=self.client.get('/api/session-project-summary')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),SUMMARY)
        self.assertIn('no-store',response.headers.get('cache-control',''))
        self.assertEqual(self.backend.calls,[('summary',)])
    def test_INV_WSESS_18_http_rejects_scope_paths_and_all_parameters(self):
        self.login()
        self.assertEqual(self.client.get('/api/session-project-summary').status_code,200,'Summary route must exist before negative query checks')
        self.backend.calls.clear()
        for query in ('project=demo','cwd=/private','refresh=true','path=/private','project=demo&project=other'):
            with self.subTest(query=query): self.assertEqual(self.client.get('/api/session-project-summary?'+query).status_code,422)
        self.assertEqual(self.backend.calls,[])


class SummaryBrokerContract(unittest.TestCase):
    start=broker_fixture.BrokerContract.start
    shutdown=broker_fixture.BrokerContract.shutdown
    wire=broker_fixture.BrokerContract.wire
    def setUp(self):
        broker_fixture.BrokerContract.setUp(self); self.backend=Backend()
    def test_INV_WSESS_18_fixed_summary_op_roundtrip_and_strict_extra_fields(self):
        self.start(); self.assertEqual(self.wire({'op':'session_project_summary'}),SUMMARY)
        self.assertEqual(self.backend.calls,[('summary',)])
        for extra in ({'project':'demo'},{'cwd':'/private'},{'refresh':True}):
            self.assertEqual(self.wire({'op':'session_project_summary',**extra}),{'error':'invalid_request'})
        self.assertEqual(self.backend.calls,[('summary',)])
    def test_INV_WSESS_18_socket_client_fixed_method_no_payload_scope(self):
        self.start(); client=self.module.SocketBackend(self.socket_path)
        method=getattr(client,'session_project_summary',None)
        self.assertTrue(callable(method),'Public fixed broker client summary method required')
        self.assertEqual(method(),SUMMARY)
        self.assertEqual(self.backend.calls,[('summary',)])

if __name__=='__main__': unittest.main(verbosity=2)
