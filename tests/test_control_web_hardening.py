"""Additional author security regressions; never changes independent tests."""
import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from test_control_web_contract import load_feature, Backend, ORIGIN, PASSWORD, SECRET


class Hardening(unittest.TestCase):
    def setUp(self):
        self.web = load_feature(self, '_control_web.py')
        self.now = 1800000000
        self.config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD), totp_secret=SECRET)
    def client(self):
        return TestClient(self.web.create_app(self.config, Backend(), clock=lambda:self.now),base_url=ORIGIN)
    def login(self, client):
        return client.post('/api/login',json={'password':PASSWORD,'totp':self.web.totp_code(SECRET,self.now)},headers={'Origin':ORIGIN})
    def test_replay_survives_application_restart(self):
        with tempfile.TemporaryDirectory(dir='/var/tmp',prefix='web-replay-') as directory:
            os.chmod(directory,0o700)
            self.config['totp_state_path']=str(Path(directory)/'replay.json')
            Path(self.config['totp_state_path']).write_text('{"last_step":-1}')
            Path(self.config['totp_state_path']).chmod(0o600)
            self.assertEqual(self.login(self.client()).status_code,200)
            self.assertEqual(self.login(self.client()).status_code,401)
    def test_nonascii_csrf_is_safe_refusal(self):
        client=self.client()
        self.assertEqual(self.login(client).status_code,200)
        response=client.post('/api/logout',json={},headers=[(b'origin',ORIGIN.encode()),(b'x-csrf-token',b'\xff')])
        self.assertEqual(response.status_code,403)
        self.assertEqual(response.json(),{'error':'forbidden'})
