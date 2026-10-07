"""Auxiliary fault-injection regressions for SOURCE S-04/S-05 cleanup.

These implementation-author checks supplement the independent HTTP contracts.
Only synthetic private files/connections are used.
"""
import asyncio
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_control_web_login_name_red import load_web, Backend, ORIGIN, PASSWORD, SECRET

ROOT = Path(__file__).resolve().parents[1]


class AppResourceCleanup(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir='/var/tmp', prefix='app-resource-cleanup-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)
        self.web = load_web(self)

    def store(self):
        spec = importlib.util.spec_from_file_location('_app_cleanup_store', ROOT / 'bin/_control_web_android_auth.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, module.DeviceGrantStore(self.root / 'grants.sqlite', lambda: 1800000000)

    def test_post_connect_validation_failure_closes_connection(self):
        module, store = self.store()
        for exception in (ValueError('synthetic unsafe storage'), RuntimeError('synthetic validation failure')):
            with self.subTest(exception=type(exception).__name__):
                real = sqlite3.connect(self.root / 'grants.sqlite')
                self.addCleanup(real.close)
                connection = Mock(wraps=real)
                with patch.object(module.sqlite3, 'connect', return_value=connection), \
                     patch.object(store, '_validate_storage', side_effect=[None, exception]):
                    with self.assertRaises(type(exception)):
                        store._connect()
                connection.close.assert_called_once_with()
                with self.assertRaises(sqlite3.ProgrammingError):
                    real.execute('SELECT 1')

    def download(self, *, fstat_failure=False):
        config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
                      totp_secret=SECRET, android_download_dir=str(self.root))
        app = self.web.create_app(config, Backend(), clock=lambda: 1800000000)
        endpoint = next(route.endpoint for route in app.routes if route.path == '/download/android/{filename}')
        path = self.root / 'ai-control-3.apk'
        path.write_bytes(b'synthetic APK descriptor fixture')
        real = path.open('rb')
        self.addCleanup(real.close)
        stream = Mock(wraps=real)
        helper = SimpleNamespace(open_file=Mock(return_value=stream),
                                 FeedMissing=type('FeedMissing', (Exception,), {}),
                                 FeedUnavailable=type('FeedUnavailable', (Exception,), {}))
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
        with patch('importlib.util.spec_from_file_location', return_value=spec), \
             patch('importlib.util.module_from_spec', return_value=helper):
            if fstat_failure:
                with patch.object(self.web.os, 'fstat', side_effect=OSError('synthetic stat failure')):
                    response = endpoint('ai-control-3.apk')
            else:
                response = endpoint('ai-control-3.apk')
        helper.open_file.assert_called_once_with(str(self.root), 'ai-control-3.apk')
        return response, stream, real

    def test_apk_fstat_failure_closes_descriptor_and_returns_unavailable(self):
        try:
            response, stream, real = self.download(fstat_failure=True)
        except OSError:
            self.fail("APK stat failure must return an unavailable response")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.body, b'{"error":"unavailable"}')
        stream.close.assert_called_once_with()
        self.assertTrue(real.closed)

    def test_apk_cancellation_before_first_chunk_closes_descriptor_once(self):
        response, stream, real = self.download()
        async def send(message):
            self.assertEqual(message['type'], 'http.response.start')
            raise asyncio.CancelledError
        async def receive():
            return {'type': 'http.disconnect'}
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send))
        stream.read.assert_not_called()
        stream.close.assert_called_once_with()
        self.assertTrue(real.closed)

    def test_apk_success_closes_descriptor_once_after_exact_bytes(self):
        response, stream, real = self.download()
        messages = []
        async def send(message):
            messages.append(message)
        async def receive():
            return {'type': 'http.disconnect'}
        asyncio.run(response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send))
        self.assertEqual(b''.join(m.get('body', b'') for m in messages), b'synthetic APK descriptor fixture')
        stream.close.assert_called_once_with()
        self.assertTrue(real.closed)


if __name__ == '__main__':
    unittest.main()
