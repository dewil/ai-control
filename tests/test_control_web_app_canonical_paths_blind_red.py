"""Independent canonical app/download HTTP paths; no runtime source inspected.

APP_CONTRACT_ROOT selects a readonly authored candidate for public API calls.
Synthetic APK fixture does not claim signing or device acceptance.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from test_control_web_login_name_red import Backend, ORIGIN, PASSWORD, SECRET

ROOT = Path(os.environ.get('APP_CONTRACT_ROOT', Path(__file__).resolve().parents[1]))


class CanonicalAppPaths(unittest.TestCase):
    # INV-APP-01 INV-APP-02 INV-APP-03 INV-APP-05 INV-APP-08
    def setUp(self):
        spec = importlib.util.spec_from_file_location('_control_web_canonical_blind', ROOT / 'bin/_control_web.py')
        self.web = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.web)
        self.directory = tempfile.TemporaryDirectory(dir='/var/tmp', prefix='app-canonical-blind-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)
        replay = self.root / 'replay.json'
        replay.write_text('{"last_step":-1}')
        replay.chmod(0o600)
        catalog = self.root / 'catalog'
        catalog.mkdir()
        data = b'synthetic-not-signed-apk'
        (catalog / 'ai-control-3.apk').write_bytes(data)
        (catalog / 'version.json').write_text(json.dumps(dict(versionCode=3, versionName='0.1.2',
            apkUrl='https://llm-web.dewil.ru:18443/download/android/ai-control-3.apk',
            sha256=hashlib.sha256(data).hexdigest())))
        config = dict(origin=ORIGIN, username='dwl', password_hash=self.web.hash_password(PASSWORD),
            totp_secret=SECRET, totp_state_path=str(replay), session_ttl=10800,
            android_auth_db=str(self.root / 'grant.sqlite'), android_download_dir=str(catalog))
        self.backend = Backend()
        self.client = TestClient(self.web.create_app(config, self.backend, clock=lambda: 1800000000), base_url=ORIGIN)

    def denied_path(self, response):
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn('location', response.headers)
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(response.headers.get('cache-control'), 'no-store')
        self.assertEqual(self.backend.calls, [])

    def test_app_login_trailing_slash_is_not_an_alias(self):
        response = self.client.post('/api/app/login/', json=dict(username='dwl', password=PASSWORD,
            totp=self.web.totp_code(SECRET, 1800000000)), headers={'Origin': ORIGIN}, follow_redirects=False)
        self.denied_path(response)

    def test_app_session_trailing_slash_is_not_an_alias(self):
        response = self.client.post('/api/app/session/', json={'foreground_open': False},
            headers={'Origin': ORIGIN, 'Authorization': 'Bearer ' + 'A' * 43}, follow_redirects=False)
        self.denied_path(response)

    def test_app_logout_trailing_slash_is_not_an_alias(self):
        response = self.client.post('/api/app/logout/', json={},
            headers={'Origin': ORIGIN, 'Authorization': 'Bearer ' + 'A' * 43}, follow_redirects=False)
        self.denied_path(response)

    def test_manifest_trailing_slash_is_not_an_alias(self):
        self.denied_path(self.client.get('/download/android/version.json/', follow_redirects=False))

    def test_apk_trailing_slash_is_not_an_alias(self):
        self.denied_path(self.client.get('/download/android/ai-control-3.apk/', follow_redirects=False))

    def test_landing_double_slash_is_not_an_alias(self):
        self.denied_path(self.client.get('/download/android//', follow_redirects=False))

    def test_canonical_landing_keeps_required_trailing_slash(self):
        response = self.client.get('/download/android/', follow_redirects=False)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('location', response.headers)
        self.assertIn('/download/android/ai-control-3.apk', response.text)

    def test_existing_web_login_redirect_behavior_is_preserved(self):
        response = self.client.post('/api/login/', json={}, headers={'Origin': ORIGIN}, follow_redirects=False)
        self.assertEqual(response.status_code, 307, response.text)
        self.assertEqual(response.headers['location'], ORIGIN + '/api/login')


if __name__ == '__main__':
    unittest.main()
