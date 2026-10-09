"""Author regressions for owner export cancellation and cleanup honesty.

INV-DEVBUS-10: independent frozen suites remain unchanged. All config,
Projection and Observer objects here are synthetic; no transport is opened.
"""
import asyncio
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

import live_devbus_blind_support as support


class OwnerRuntimeRegression(unittest.TestCase):
    def test_dynamic_redactor_import_without_bin_on_sys_path_performs_no_owner_IO(self):
        code = '''
import importlib.util, os, pathlib, sys
from unittest.mock import patch
path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('_synthetic_owner_redactor', path)
module = importlib.util.module_from_spec(spec)
with patch.object(os, 'open', side_effect=AssertionError('Owner config IO at import')):
    spec.loader.exec_module(module)
assert callable(module.redact)
assert module.redact('Bearer synthetic-value') == 'Bearer ***'
'''
        path = Path(__file__).resolve().parents[1] / 'bin' / '_control_web_broker.py'
        result = subprocess.run([sys.executable, '-I', '-c', code, str(path)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def runtime(self, *, observer=None, projection=None):
        from _control_web_broker import DevbusRuntime
        class Observer:
            async def start(self):
                pass
            async def stop(self):
                pass
        runtime = DevbusRuntime(config_loader=lambda: (support.config(), None),
            projection_factory=projection or (lambda **_: support.ProjectionData(support.empty())),
            observer_factory=lambda *_: (observer or Observer()), dependency_probe=lambda: True)
        return runtime

    def test_export_timeout_while_queued_releases_token_after_loop_resumes(self):
        runtime = self.runtime()
        entered, release = threading.Event(), threading.Event()
        runtime.start()
        try:
            def hold_loop():
                entered.set()
                release.wait(4)
            runtime._loop.call_soon_threadsafe(hold_loop)
            self.assertTrue(entered.wait(1))
            self.assertEqual(runtime.snapshot(), {'error': 'unavailable'})
            self.assertEqual(runtime.snapshot(), {'error': 'busy'})
            release.set()
            deadline = time.monotonic() + 2
            while runtime.snapshot() == {'error': 'busy'} and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(runtime.snapshot(), support.empty())
        finally:
            release.set()
            runtime.stop()

    def test_stop_failure_is_sanitized_and_never_reported_clean(self):
        class Observer:
            async def start(self):
                pass
            async def stop(self):
                raise RuntimeError('synthetic-private-detail')
        runtime = self.runtime(observer=Observer())
        runtime.start()
        with self.assertRaisesRegex(RuntimeError, '^devbus cleanup unavailable$'):
            runtime.stop()
        self.assertFalse(runtime._thread.is_alive())
        with self.assertRaisesRegex(RuntimeError, '^devbus cleanup unavailable$'):
            runtime.stop()

    def test_stop_rejects_snapshot_before_async_cleanup_finishes(self):
        entered, released = threading.Event(), threading.Event()
        class Observer:
            async def start(self):
                pass
            async def stop(self):
                entered.set()
                while not released.is_set():
                    await asyncio.sleep(.01)
        runtime = self.runtime(observer=Observer())
        runtime.start()
        try:
            runtime.request_stop()
            self.assertTrue(entered.wait(1))
            self.assertEqual(runtime.snapshot()['connection'],
                             {'state': 'disconnected', 'reason': 'unavailable'})
        finally:
            released.set()
            runtime.stop()

    def test_failed_projection_setup_is_terminal_without_factory_retry(self):
        calls = []
        def projection(**_):
            calls.append(1)
            raise RuntimeError('synthetic-private-detail')
        runtime = self.runtime(projection=projection)
        runtime.start()
        runtime.start()
        self.assertEqual(calls, [1])
        self.assertEqual(runtime.snapshot()['connection'],
                         {'state': 'disconnected', 'reason': 'unavailable'})
        runtime.stop()

    def test_noncompliant_stop_keeps_loop_alive_and_reports_bounded_failure(self):
        entered, release = threading.Event(), threading.Event()
        class Observer:
            async def start(self):
                pass
            async def stop(self):
                entered.set()
                while not release.is_set():
                    try:
                        await asyncio.sleep(.01)
                    except asyncio.CancelledError:
                        # Deliberately adversarial fixture ignores cancellation;
                        # it must never turn an alive loop into clean success.
                        pass
        runtime = self.runtime(observer=Observer())
        runtime.start()
        try:
            start = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, '^devbus cleanup unavailable$'):
                runtime.stop()
            self.assertTrue(entered.is_set())
            self.assertLess(time.monotonic() - start, 12.5)
            self.assertTrue(runtime._thread.is_alive())
            self.assertFalse(runtime._loop.is_closed())
        finally:
            release.set()
            runtime.stop()


if __name__ == '__main__':
    unittest.main()
