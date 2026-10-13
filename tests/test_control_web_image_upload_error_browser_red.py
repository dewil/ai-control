"""Explicit unsupported-image error through the existing public upload seam."""
import re
import unittest
from playwright.sync_api import expect
import test_control_web_attachment_upload_recovery_browser_red as h
import test_control_web_native_queue_browser_blind as queue

class ImageUploadErrorBrowserRED(unittest.TestCase):
    setUpClass=classmethod(h.AttachmentUploadRecoveryBrowserRED.setUpClass.__func__)
    setUp=h.AttachmentUploadRecoveryBrowserRED.setUp
    tearDown=h.AttachmentUploadRecoveryBrowserRED.tearDown
    select=h.AttachmentUploadRecoveryBrowserRED.select
    until=h.AttachmentUploadRecoveryBrowserRED.until
    choose_file=h.AttachmentUploadRecoveryBrowserRED.choose_file
    mock_stage=h.AttachmentUploadRecoveryBrowserRED.mock_stage
    assert_no_execution=h.AttachmentUploadRecoveryBrowserRED.assert_no_execution

    def test_unsupported_image_finish_is_explicit_disabled_and_never_auto_retried(self):
        # INV-WATT-JPEG-SEF: permanent format refusal is not a generic outage.
        self.mock_stage();finishes=[]
        def finish(route):
            finishes.append(route.request)
            route.fulfill(status=422,json=dict(error='unsupported'))
        self.page.route('**/api/session-attachment-finish',finish)
        self.select();self.choose_file()
        expect(self.page.get_by_text('Формат изображения не поддерживается или файл повреждён.',exact=True)).to_be_visible()
        expect(self.page.get_by_role('button',name=queue.SEND)).to_be_disabled()
        self.assertEqual(len(finishes),1)
        before=list(self.operations);self.page.wait_for_timeout(200)
        self.assertEqual(self.operations,before);self.assertEqual(len(finishes),1)
        self.assert_no_execution()
