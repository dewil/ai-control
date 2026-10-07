"""Independent fault probes for test-only readiness handoff; no auth norm change."""
import json
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
import test_control_web_android_download_browser as fixture

class ReadyJsonFaultProbe(unittest.TestCase):
    def test_partial_ready_waits_for_complete_document(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'ready.json'
            path.write_text('{')
            complete={'url':'http://127.0.0.1:1234','disabled_url':'http://127.0.0.1:1235'}
            def finish():
                time.sleep(.06)
                path.write_text(json.dumps(complete))
            writer=threading.Thread(target=finish);writer.start()
            try:
                started=time.monotonic()
                self.assertEqual(fixture.wait_ready_json(path,types.SimpleNamespace(poll=lambda:None),timeout=1),complete)
                self.assertGreaterEqual(time.monotonic()-started,.04)
            finally: writer.join()

    def test_missing_partial_and_wrong_complete_documents_expire(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'ready.json'
            for content in (None,'{','{}','{"url":"wrong","disabled_url":"wrong"}'):
                with self.subTest(content=content):
                    path.unlink(missing_ok=True)
                    if content is not None:path.write_text(content)
                    started=time.monotonic()
                    with self.assertRaisesRegex(RuntimeError,'readiness timed out'):
                        fixture.wait_ready_json(path,types.SimpleNamespace(poll=lambda:None),timeout=.08)
                    self.assertLess(time.monotonic()-started,1)

    def test_failed_fixture_never_announces_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError,'fixture failed'):
                fixture.wait_ready_json(Path(temporary)/'ready.json',types.SimpleNamespace(poll=lambda:19),timeout=.08)

class HeldSessionVisibilityFaultProbe(unittest.TestCase):
    stop_server=classmethod(fixture.AndroidDownloadBrowserContract.stop_server.__func__)
    @classmethod
    def setUpClass(cls):
        fixture.AndroidDownloadBrowserContract.setUpClass.__func__(cls)

    def test_pending_session_times_out_until_original_response_is_released(self):
        from playwright.sync_api import TimeoutError as BrowserTimeout
        context=self.browser.new_context();self.addCleanup(context.close)
        page=context.new_page();held=[]
        def hold(route):
            held.append((route,route.fetch()))
        page.route('**/api/session',hold)
        page.goto(self.disabled_url)
        deadline=time.monotonic()+5
        while not held and time.monotonic()<deadline:page.wait_for_timeout(20)
        self.assertEqual(len(held),1,'Fault probe must intercept session readiness request')
        password=page.locator('input[type=password]')
        with self.assertRaises(BrowserTimeout):password.wait_for(state='visible',timeout=150)
        self.assertFalse(password.is_visible(),'Pending session must not already report login ready')
        route,response=held[0];route.fulfill(response=response)
        password.wait_for(state='visible',timeout=5000)
        self.assertTrue(password.is_visible())

if __name__=='__main__':unittest.main()
