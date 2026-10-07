"""Blind bounded malformed-body contract, including parser recursion boundary.

Only public HTTP contracts and synthetic fixture data; no runtime source read.
APP_CONTRACT_ROOT selects an authored candidate for readonly execution.
"""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from test_control_web_login_name_red import Backend, ORIGIN, PASSWORD, SECRET

ROOT = Path(os.environ.get('APP_CONTRACT_ROOT', Path(__file__).resolve().parents[1]))


class AppDeepJSONContract(unittest.TestCase):
    # INV-APP-01 INV-APP-02 INV-APP-03
    def setUp(self):
        spec = importlib.util.spec_from_file_location('_control_web_body_boundary_blind', ROOT / 'bin/_control_web.py')
        self.web = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.web)
        self.directory = tempfile.TemporaryDirectory(dir='/var/tmp', prefix='app-json-boundary-blind-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)
        replay = self.root / 'replay.json'
        replay.write_text('{"last_step":-1}')
        replay.chmod(0o600)
        config = dict(origin=ORIGIN, username='dwl', password_hash=self.web.hash_password(PASSWORD),
            totp_secret=SECRET, totp_state_path=str(replay), session_ttl=10800,
            android_auth_db=str(self.root / 'grant.sqlite'))
        self.backend = Backend()
        self.client = TestClient(self.web.create_app(config, self.backend, clock=lambda: 1800000000),
            base_url=ORIGIN, raise_server_exceptions=False)
        # Raw bytes avoid constructing recursive Python objects or changing recursionlimit.
        # Use 60000 levels, still below the 128KiB byte limit, to exceed
        # elevated parser recursion limits without changing process state.
        self.deep = b'[' * 60000 + b'0' + b']' * 60000
        self.assertLess(len(self.deep), 128 * 1024)

    def invalid(self, endpoint, body):
        self.assertLess(len(body), 128 * 1024)
        response = self.client.post('/api/app/' + endpoint, content=body,
            headers={'Origin': ORIGIN, 'Authorization': 'Bearer ' + 'A' * 43},
            follow_redirects=False)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json(), {'error': 'invalid_request'})
        self.assertEqual(response.headers.get('cache-control'), 'no-store')
        self.assertNotIn('set-cookie', response.headers)
        self.assertNotIn('location', response.headers)
        self.assertEqual(self.backend.calls, [])
        self.assertFalse((self.root / 'grant.sqlite').exists(), 'body rejection precedes grant access')
        self.assertEqual((self.root / 'replay.json').read_text(), '{"last_step":-1}')

    def test_deep_wrong_type_login_field_is_bounded_invalid_request(self):
        self.invalid('login', b'{"username":"dwl","password":' + self.deep + b',"totp":"123456"}')

    def test_deep_wrong_type_foreground_field_is_bounded_invalid_request(self):
        self.invalid('session', b'{"foreground_open":' + self.deep + b'}')

    def test_deep_non_object_logout_is_bounded_invalid_request(self):
        self.invalid('logout', self.deep)


if __name__ == '__main__':
    unittest.main()
