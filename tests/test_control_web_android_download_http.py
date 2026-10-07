"""Independent INV-AND-12 FR-AND-07 US-AND-004 public channel HTTP contracts."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from test_control_web_contract import Backend, load_feature, PASSWORD, SECRET, ORIGIN

PREFIX = '/download/android/'
UPDATE_ORIGIN = 'https://llm-web.dewil.ru:18443'


def manifest(code=1, name='0.1.0', payload=b'synthetic APK one'):
    return dict(versionCode=code, versionName=name,
                apkUrl=UPDATE_ORIGIN + PREFIX + f'ai-control-{code}.apk',
                sha256=hashlib.sha256(payload).hexdigest())


class AndroidDownloadHTTPContract(unittest.TestCase):
    def setUp(self):
        self.web = load_feature(self, '_control_web.py')
        self.tmp = tempfile.TemporaryDirectory(prefix='android-download-http-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.feed = self.root / 'public'
        self.feed.mkdir()
        self.backend = Backend()
        self.config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
                           totp_secret=SECRET, secure_cookie=True,
                           android_download_dir=str(self.feed))

    def client(self, config=None, owner_only=True):
        client = TestClient(self.web.create_app(config or self.config, self.backend,
                           clock=lambda: 1800000000, owner_only=owner_only), base_url=ORIGIN)
        self.addCleanup(client.close)
        return client

    def publish(self, code=1, name='0.1.0', payload=b'synthetic APK one'):
        doc = manifest(code, name, payload)
        (self.feed / f'ai-control-{code}.apk').write_bytes(payload)
        self.write_manifest(doc)
        return doc

    def write_manifest(self, doc):
        (self.feed / 'version.json').write_text(json.dumps(doc), encoding='utf-8')

    def get(self, client, path, status):
        response = client.get(path, follow_redirects=False)
        self.assertEqual(response.status_code, status, response.text[:300])
        self.assertNotIn('location', response.headers, 'download route cannot auth-redirect')
        self.assertNotIn('set-cookie', response.headers, 'public download cannot create auth cookie')
        self.assertNotIn(PASSWORD, response.text)
        self.assertNotIn(SECRET, response.text)
        self.assertNotIn(str(self.root), response.text)
        return response

    def test_anonymous_landing_feed_and_apk_have_public_cache_and_mime(self):
        doc = self.publish()
        client = self.client()
        landing = self.get(client, PREFIX, 200)
        self.assertIn('text/html', landing.headers.get('content-type', ''))
        self.assertIn('no-store', landing.headers.get('cache-control', ''))
        feed = self.get(client, PREFIX + 'version.json', 200)
        self.assertEqual(feed.json(), doc)
        self.assertIn('application/json', feed.headers.get('content-type', ''))
        self.assertIn('no-store', feed.headers.get('cache-control', ''))
        apk = self.get(client, PREFIX + 'ai-control-1.apk', 200)
        self.assertEqual(apk.content, b'synthetic APK one')
        self.assertEqual(apk.headers.get('content-type'), 'application/vnd.android.package-archive')
        disposition = apk.headers.get('content-disposition', '')
        self.assertIn('attachment', disposition)
        self.assertIn('ai-control-1.apk', disposition)
        self.assertIn('immutable', apk.headers.get('cache-control', ''))
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(list(client.cookies), [])

    def test_public_download_is_independent_of_owner_only_mode(self):
        self.publish()
        client = self.client(owner_only=False)
        for path in (PREFIX, PREFIX + 'version.json', PREFIX + 'ai-control-1.apk'):
            self.get(client, path, 200)
        self.assertEqual(self.backend.calls, [])

    def test_absent_configuration_disables_routes_without_auth_redirect(self):
        config = dict(self.config)
        del config['android_download_dir']
        client = self.client(config)
        for path in (PREFIX, PREFIX + 'version.json', PREFIX + 'ai-control-1.apk'):
            self.get(client, path, 404)

    def test_configured_missing_directory_is_empty_channel(self):
        config = dict(self.config, android_download_dir=str(self.root / 'not-created'))
        client = self.client(config)
        self.get(client, PREFIX, 200)
        self.get(client, PREFIX + 'version.json', 404)
        self.get(client, PREFIX + 'ai-control-1.apk', 404)

    def test_configured_missing_manifest_is_empty_channel(self):
        client = self.client()
        self.get(client, PREFIX, 200)
        self.get(client, PREFIX + 'version.json', 404)
        self.get(client, PREFIX + 'ai-control-1.apk', 404)

    def test_manifest_pointer_changes_without_app_restart_old_apk_stays_available(self):
        self.publish()
        client = self.client()
        self.assertEqual(self.get(client, PREFIX + 'version.json', 200).json()['versionCode'], 1)
        self.publish(2, '0.2.0', b'synthetic APK two')
        self.assertEqual(self.get(client, PREFIX + 'version.json', 200).json()['versionCode'], 2)
        self.assertEqual(self.get(client, PREFIX + 'ai-control-1.apk', 200).content, b'synthetic APK one')
        self.assertEqual(self.get(client, PREFIX + 'ai-control-2.apk', 200).content, b'synthetic APK two')

    def test_unknown_and_noncanonical_names_do_not_expose_existing_files(self):
        self.publish()
        names = ['private.txt', '.env', 'version.json.bak', 'ai-control-0.apk',
                 'ai-control-01.apk', 'ai-control--1.apk', 'ai-control-2147483648.apk',
                 'ai-control-1.APK', 'ai-control-1.apk.bak', 'anything.apk']
        for name in names:
            (self.feed / name).write_bytes(b'private fixture must not be served')
        client = self.client()
        for name in names:
            with self.subTest(name=name):
                self.get(client, PREFIX + name, 404)

    def test_missing_apk_invalidates_published_feed_without_false_download_link(self):
        self.write_manifest(manifest())
        client = self.client()
        self.get(client, PREFIX + 'version.json', 503)
        self.get(client, PREFIX, 200)
        self.get(client, PREFIX + 'ai-control-1.apk', 404)

    def test_direct_symlink_feed_and_apk_are_not_followed(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'private outside fixture')
        (self.feed / 'version.json').symlink_to(outside)
        (self.feed / 'ai-control-1.apk').symlink_to(outside)
        client = self.client()
        self.get(client, PREFIX + 'version.json', 404)
        self.get(client, PREFIX + 'ai-control-1.apk', 404)

    def test_symlink_configured_directory_is_not_followed(self):
        self.publish()
        link = self.root / 'linked-public'
        link.symlink_to(self.feed, target_is_directory=True)
        client = self.client(dict(self.config, android_download_dir=str(link)))
        for path in (PREFIX + 'version.json', PREFIX + 'ai-control-1.apk'):
            self.get(client, path, 404)

    def test_manifest_pointing_to_symlink_or_nonregular_apk_fails_closed(self):
        self.write_manifest(manifest())
        apk = self.feed / 'ai-control-1.apk'
        target = self.root / 'outside'
        target.write_bytes(b'outside fixture')
        client = self.client()
        for kind in ('symlink', 'directory'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    apk.symlink_to(target)
                else:
                    apk.mkdir()
                try:
                    self.get(client, PREFIX + 'version.json', 503)
                    self.get(client, PREFIX, 200)
                    self.get(client, PREFIX + 'ai-control-1.apk', 404)
                finally:
                    if apk.is_symlink():
                        apk.unlink()
                    else:
                        apk.rmdir()

    def test_encoded_and_double_encoded_traversal_cannot_escape_static_root(self):
        (self.root / 'private.txt').write_bytes(b'private outside fixture')
        client = self.client()
        paths = ['%2e%2e/private.txt', '%252e%252e/private.txt', '%2e%2e%2fprivate.txt',
                 '%252e%252e%252fprivate.txt', 'ai-control-1.apk%2f..%2fprivate.txt',
                 '%2Fetc%2Fpasswd', '..%5cprivate.txt']
        for suffix in paths:
            with self.subTest(suffix=suffix):
                response = self.get(client, PREFIX + suffix, 404)
                self.assertNotIn('private outside fixture', response.text)

    def test_malformed_manifest_types_urls_hashes_and_names_fail_closed(self):
        self.publish()
        valid = manifest()
        variants = [dict(valid, versionCode=value) for value in (0, -1, True, '1', 1.0, 2147483648)]
        variants += [{key: value for key, value in valid.items() if key != missing} for missing in valid]
        variants += [dict(valid, versionName=value) for value in ('', ' ', 'x' * 65, 1, None)]
        variants += [dict(valid, sha256=value) for value in ('A' * 64, 'a' * 63, 'z' * 64, None)]
        variants += [dict(valid, apkUrl=url) for url in (
            ORIGIN + PREFIX + 'ai-control-1.apk',
            'https://foreign.invalid' + PREFIX + 'ai-control-1.apk',
            UPDATE_ORIGIN + PREFIX + 'ai-control-01.apk',
            UPDATE_ORIGIN + PREFIX + 'ai-control-2.apk',
            UPDATE_ORIGIN + PREFIX + 'ai-control-1.apk?q=1',
            UPDATE_ORIGIN + PREFIX + 'ai-control-1.apk#fragment',
            'https://name@llm-web.dewil.ru:18443' + PREFIX + 'ai-control-1.apk',
            UPDATE_ORIGIN + PREFIX + '%2e%2e/ai-control-1.apk')]
        client = self.client()
        for index, doc in enumerate(variants):
            with self.subTest(index=index):
                self.write_manifest(doc)
                self.get(client, PREFIX + 'version.json', 503)
                self.get(client, PREFIX, 200)

    def test_invalid_utf8_duplicate_keys_oversize_and_noninteger_lexemes_rejected(self):
        self.publish()
        valid = json.dumps(manifest()).encode()
        payloads = [b'\xff', b'{', b'[]', valid + b' {}', b' ' * 16385 + valid,
                    valid.replace(b'"versionCode": 1', b'"versionCode": 1, "versionCode": 2'),
                    valid.replace(b'"versionCode": 1', b'"versionCode": 01'),
                    valid.replace(b'"versionCode": 1', b'"versionCode": 1e0')]
        client = self.client()
        for payload in payloads:
            with self.subTest(size=len(payload)):
                (self.feed / 'version.json').write_bytes(payload)
                self.get(client, PREFIX + 'version.json', 503)
                self.get(client, PREFIX, 200)

    def test_nonfinite_unknown_values_and_unpaired_surrogates_are_invalid_json(self):
        self.publish()
        valid = manifest()
        variants = [dict(valid, unknown=value) for value in
                    (float('nan'), float('inf'), float('-inf'))]
        variants += [dict(valid, versionName='\ud800'),
                     dict(valid, unknown={'nested': ['\udfff']})]
        client = self.client()
        for index, doc in enumerate(variants):
            with self.subTest(index=index):
                # JSON escapes make even isolated surrogate fixtures ASCII bytes.
                payload = json.dumps(doc, ensure_ascii=True).encode('ascii')
                (self.feed / 'version.json').write_bytes(payload)
                self.get(client, PREFIX + 'version.json', 503)
                self.get(client, PREFIX, 200)

    @unittest.skipIf(os.geteuid() == 0, 'root bypasses real permission-denied fixture')
    def test_unreadable_manifest_returns_generic_operational_error(self):
        self.publish()
        path = self.feed / 'version.json'
        path.chmod(0)
        try:
            client = self.client()
            self.get(client, PREFIX + 'version.json', 503)
            self.get(client, PREFIX, 503)
        finally:
            path.chmod(0o600)

    def test_unknown_manifest_fields_do_not_break_valid_release(self):
        doc = self.publish()
        doc['ignored'] = {'url': 'https://foreign.invalid/ignored'}
        self.write_manifest(doc)
        self.get(self.client(), PREFIX + 'version.json', 200)


if __name__ == '__main__':
    unittest.main()
