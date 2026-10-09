"""Independent anonymous download contract; synthetic APK bytes, no signing claim."""
# Accepted INV-WSESS-47..50 (2026-10-08-spec-live-observability-package.md):
# canonical captions/chips and native disclosures replace the previous labels/layout.

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from test_control_web_login_name_red import load_web, Backend, ORIGIN, PASSWORD, SECRET


class AppDownloadContract(unittest.TestCase):
    # INV-APP-05 INV-APP-08
    def setUp(self):
        self.web = load_web(self)
        self.directory = tempfile.TemporaryDirectory(prefix='app-download-blind-', dir='/var/tmp')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.backend = Backend()
        self.config = dict(origin=ORIGIN, username='dwl', password_hash=self.web.hash_password(PASSWORD),
            totp_secret=SECRET, android_download_dir=str(self.root))
        self.client = self.new_client()

    def new_client(self, config=None):
        return TestClient(self.web.create_app(self.config if config is None else config,
            self.backend, clock=lambda: 1800000000), base_url=ORIGIN)

    def publish(self, code=3, name='0.1.2', **changes):
        data = b'synthetic-not-a-signed-apk-' + str(code).encode()
        apk = self.root / f'ai-control-{code}.apk'
        apk.write_bytes(data)
        manifest = dict(versionCode=code, versionName=name,
            apkUrl=f'https://llm-web.dewil.ru:18443/download/android/ai-control-{code}.apk',
            sha256=hashlib.sha256(data).hexdigest())
        manifest.update(changes)
        (self.root / 'version.json').write_text(json.dumps(manifest))
        return manifest, data

    def get(self, path):
        r = self.client.get(path, follow_redirects=False)
        self.assertNotIn('location', r.headers)
        self.assertNotIn('set-cookie', r.headers)
        self.assertEqual(self.backend.calls, [])
        self.assertNotIn(str(self.root), r.text if 'apk' not in r.headers.get('content-type', '') else '')
        return r

    def test_permanent_panel_download_link_present_before_login(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('/download/android/', r.text)
        self.assertIn('Андроид', r.text)

    def test_configured_empty_and_absent_download_contract(self):
        r = self.get('/download/android/')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn('Версия еще не опубликована', r.text)
        self.assertEqual(r.headers.get('cache-control'), 'no-store')
        for path in ('/download/android/version.json', '/download/android/ai-control-3.apk'):
            self.assertEqual(self.get(path).status_code, 404)
        absent = self.new_client({k: v for k, v in self.config.items() if k != 'android_download_dir'})
        for path in ('/download/android/', '/download/android/version.json', '/download/android/ai-control-3.apk'):
            r = absent.get(path, follow_redirects=False)
            self.assertEqual(r.status_code, 404)
            self.assertNotIn('location', r.headers)

    def test_anonymous_release_feed_landing_apk_cache_and_upgrade(self):
        manifest, data = self.publish()
        r = self.get('/download/android/')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers.get('cache-control'), 'no-store')
        self.assertIn('/download/android/ai-control-3.apk', r.text)
        r = self.get('/download/android/version.json')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), manifest)
        self.assertEqual(r.headers.get('cache-control'), 'no-store')
        self.assertIn('application/json', r.headers.get('content-type', ''))
        r = self.get('/download/android/ai-control-3.apk')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.content, data)
        self.assertEqual(r.headers.get('content-type'), 'application/vnd.android.package-archive')
        self.assertIn('immutable', r.headers.get('cache-control', ''))
        self.assertIn('attachment', r.headers.get('content-disposition', ''))
        self.assertIn('ai-control-3.apk', r.headers.get('content-disposition', ''))
        next_manifest, _ = self.publish(4, 'next-synthetic')
        self.assertEqual(self.get('/download/android/version.json').json(), next_manifest)
        self.assertIn('/download/android/ai-control-4.apk', self.get('/download/android/').text)
        self.assertEqual(self.get('/download/android/ai-control-3.apk').content, data)

    def test_broken_feed_and_symlink_never_publish_download_link(self):
        self.publish()
        apk = self.root / 'ai-control-3.apk'
        apk.unlink()
        for kind in ('missing', 'symlink', 'directory'):
            with self.subTest(kind=kind):
                if apk.is_symlink():
                    apk.unlink()
                elif apk.is_dir():
                    apk.rmdir()
                if kind == 'symlink':
                    apk.symlink_to(self.root / 'version.json')
                elif kind == 'directory':
                    apk.mkdir()
                r = self.get('/download/android/version.json')
                self.assertEqual(r.status_code, 503, r.text)
                r = self.get('/download/android/')
                self.assertEqual(r.status_code, 200, r.text)
                self.assertNotIn('href="/download/android/ai-control-3.apk"', r.text)
                self.assertEqual(self.get('/download/android/ai-control-3.apk').status_code, 404)
                if kind == 'symlink':
                    apk.unlink()
                elif kind == 'directory':
                    apk.rmdir()

    def test_invalid_strict_manifests_fail_closed(self):
        valid, _ = self.publish()
        variants = [dict(valid, versionCode=True), dict(valid, versionCode=0),
            dict(valid, versionCode=2147483648), dict(valid, versionName=''),
            dict(valid, versionName='x' * 65), dict(valid, sha256='A' * 64),
            dict(valid, apkUrl='https://evil.example/download/android/ai-control-3.apk'),
            dict(valid, apkUrl=valid['apkUrl'] + '?secret=x'),
            dict(valid, apkUrl=valid['apkUrl'] + '#x')]
        raw = [json.dumps(v) for v in variants]
        raw += ['{"versionCode":3,"versionCode":3}', json.dumps(valid) + '{}',
            '{"versionCode":03}', '{"versionCode":3e0}', 'x' * (16 * 1024 + 1)]
        for body in raw:
            with self.subTest(body=body[:80]):
                (self.root / 'version.json').write_text(body)
                self.assertEqual(self.get('/download/android/version.json').status_code, 503)
                r = self.get('/download/android/')
                self.assertEqual(r.status_code, 200, r.text)
                self.assertNotIn('href="/download/android/ai-control-3.apk"', r.text)

    def test_canonical_filename_traversal_and_manifest_symlink_denial(self):
        self.publish()
        for suffix in ('ai-control-03.apk', 'ai-control-0.apk', 'ai-control-2147483648.apk',
            'other.apk', 'private.json', '%2e%2e%2fversion.json', '%252e%252e%252fversion.json'):
            with self.subTest(path=suffix):
                self.assertEqual(self.get('/download/android/' + suffix).status_code, 404)
        manifest = self.root / 'version.json'
        manifest.unlink()
        manifest.symlink_to(self.root / 'ai-control-3.apk')
        self.assertEqual(self.get('/download/android/version.json').status_code, 404)


if __name__ == '__main__':
    unittest.main()
