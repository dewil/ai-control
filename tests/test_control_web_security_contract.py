"""Blind security additions: durable replay and bounded hostile HTTP input."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from test_control_web_contract import Backend, load_feature, PASSWORD, SECRET, ORIGIN, QID

# INV-WEB-01 INV-WEB-02 INV-WEB-05 INV-WEB-06 INV-WEB-08
class DurableWebSecurity(unittest.TestCase):
    def setUp(self):
        self.web = load_feature(self, '_control_web.py')
        previous = os.umask(0o077)
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix='control-web-security-', dir='/var/tmp')
        finally:
            os.umask(previous)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root/'totp-state.json'
        self.state.write_text(json.dumps({'last_step': -1}))
        self.state.chmod(0o600)
        self.now = 1800000000
        self.backend = Backend()
        self.config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
            totp_secret=SECRET, session_ttl=3600, secure_cookie=True,
            totp_state_path=str(self.state))
    def new_client(self):
        return TestClient(self.web.create_app(self.config, self.backend, clock=lambda: self.now), base_url=ORIGIN)
    def login(self, client):
        return client.post('/api/login', json={'username': 'owner', 'password': PASSWORD, 'totp': self.web.totp_code(SECRET, self.now)}, headers={'Origin': ORIGIN})
    def safe_error(self, response, status):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(set(response.json()), {'error'})
        self.assertIsInstance(response.json()['error'],str)
        self.assertNotIn(SECRET,response.text)
        self.assertNotIn(PASSWORD,response.text)
    def test_INV_WEB_01_consumed_login_step_survives_app_restart(self):
        first=self.new_client()
        self.assertEqual(self.login(first).status_code,200)
        restarted=self.new_client()
        self.safe_error(self.login(restarted),401)
        self.now+=30
        self.assertEqual(self.login(restarted).status_code,200)
        self.assertEqual(self.backend.calls,[])
    def test_INV_WEB_01_06_reject_step_durable_before_writer_even_on_failure(self):
        client=self.new_client()
        login=self.login(client)
        self.assertEqual(login.status_code,200)
        self.now+=30
        observed=[]
        def rejecting_writer(agent,generation,decision,comment):
            observed.append(json.loads(self.state.read_text())['last_step'])
            return {'error':'unavailable'}
        self.backend.verdict=rejecting_writer
        response=client.post('/api/verdict',json={'agent':'task-one','generation':'deadbeef','decision':'reject','comment':'Needs work','confirmed':True,'totp':self.web.totp_code(SECRET,self.now)},headers={'Origin':ORIGIN,'X-CSRF-Token':login.json()['csrf']})
        self.safe_error(response,503)
        self.assertEqual(observed,[self.now//30], 'reject reached writer before consumed step persisted')
        self.safe_error(self.login(self.new_client()),401)
        self.now+=30
        self.assertEqual(self.login(self.new_client()).status_code,200)
    def test_INV_WEB_01_08_corrupt_state_refuses_startup(self):
        for contents in ('{','[]','{"last_step":"synthetic-secret"}'):
            with self.subTest(contents=contents):
                self.state.write_text(contents)
                with self.assertRaises((ValueError,RuntimeError,OSError)) as raised:
                    self.new_client()
                self.assertNotIn('synthetic-secret',str(raised.exception))
                self.assertNotIn(SECRET,str(raised.exception))
    def test_INV_WEB_01_08_symlink_state_refuses_startup(self):
        outside=self.root/'private-state.json'
        outside.write_text('{"last_step":-1}')
        outside.chmod(0o600)
        self.state.unlink()
        self.state.symlink_to(outside)
        with self.assertRaises((ValueError,RuntimeError,OSError)):
            self.new_client()
        self.assertEqual(outside.read_text(),'{"last_step":-1}')
    def test_INV_WEB_02_non_ascii_csrf_safe_rejection(self):
        client=self.new_client()
        self.assertEqual(self.login(client).status_code,200)
        response=client.post('/api/answer',json={'agent':'task-one','qid':QID,'decision':'text','text':'Human answer'},headers=[(b'Origin',ORIGIN.encode('ascii')),(b'X-CSRF-Token',b'\xc3\xa9')])
        self.safe_error(response,403)
        self.assertEqual(self.backend.calls,[])
    def test_INV_WEB_05_oversized_http_body_safe_rejection(self):
        client=self.new_client()
        login=self.login(client)
        self.assertEqual(login.status_code,200)
        for route,payload in [('/api/answer',{'agent':'task-one','qid':QID,'decision':'text','text':'x'*131073}),('/api/verdict',{'agent':'task-one','generation':'deadbeef','decision':'accept','comment':'x'*131073,'confirmed':True})]:
            with self.subTest(route=route):
                response=client.post(route,content=json.dumps(payload).encode(),headers={'Origin':ORIGIN,'X-CSRF-Token':login.json()['csrf'],'Content-Type':'application/json'})
                self.safe_error(response,422)
        self.assertEqual(self.backend.calls,[])

if __name__ == '__main__':
    unittest.main(verbosity=2)
