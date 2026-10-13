"""Independent upload recovery RED: empty ACK and stale capability refresh.

Only public attachment DTOs and the browser are inspected. No native/provider calls.
"""
import hashlib
import re
import time
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect
import test_control_web_attachments_composer_browser_red as h
import test_control_web_native_queue_browser_blind as queue


class AttachmentUploadRecoveryBrowserRED(unittest.TestCase):
    setUpClass=classmethod(h.AttachmentsComposerBrowserRED.setUpClass.__func__)
    setUp=h.AttachmentsComposerBrowserRED.setUp
    tearDown=h.AttachmentsComposerBrowserRED.tearDown
    select=h.AttachmentsComposerBrowserRED.select
    until=h.AttachmentsComposerBrowserRED.until
    choose_file=h.AttachmentsComposerBrowserRED.choose_file

    def mock_stage(self, *, empty_chunk=False, available=True):
        self.operations=[];self.payloads=[];self.uploaded=bytearray()
        self.available=available;self.stage_size=4
        self.aid='88888888-8888-4888-8888-888888888888'
        def route(request_route):
            request=request_route.request;kind=urlsplit(request.url).path.rsplit('-',1)[-1]
            self.operations.append((request.method,kind))
            if kind=='options':
                request_route.fulfill(status=200,json=dict(available=self.available,images=self.available,files=self.available,direct=self.available,queue=self.available,max_files=8,max_file_bytes=20971520,max_message_bytes=41943040,chunk_bytes=49152,reason=None if self.available else 'unavailable'));return
            if kind=='begin':
                self.payloads.append(request.post_data_json);self.stage_size=request.post_data_json['size']
            if kind=='chunk':
                self.uploaded.extend(request.post_data_buffer)
                if empty_chunk:
                    request_route.fulfill(status=200,content_type='application/json',body='');return
            if kind=='status':self.payloads.append(request.post_data_json)
            sealed=kind=='finish'
            request_route.fulfill(status=200,json=dict(attachment_id=self.aid,state='sealed' if sealed else 'receiving',bytes=len(self.uploaded),size=self.stage_size,sha256=hashlib.sha256(self.uploaded).hexdigest() if sealed else None,expires_at=int(time.time())+1800,mode='file'))
        self.page.route(re.compile('/api/session-attachment-(?:options|begin|chunk|finish|status|discard)'),route)

    def chip(self):
        return self.page.get_by_text('synthetic-proof.bin',exact=True).locator('xpath=ancestor::*[.//button][1]')

    def retry(self):
        return self.page.get_by_role('button',name='Проверить загрузку',exact=True)

    def assert_no_execution(self):
        self.assertEqual(self.backend.direct_calls,[]);self.assertEqual(self.backend.enqueue_calls,[])
        self.assertEqual([r for r in self.requests if re.search(r'/api/session-(?:send|enqueue)-attachments$',r[1])],[])

    def test_empty_chunk_ack_has_safe_russian_error_and_manual_status_finishes_without_reupload(self):
        # INV-WATT-08: opaque transport error remains recoverable, not redispatched.
        self.mock_stage(empty_chunk=True);self.select();self.choose_file()
        self.until(lambda:self.operations.count(('PUT','chunk'))==1)
        expect(self.retry()).to_be_visible()
        text=self.chip().inner_text()
        self.assertNotRegex(text,r'(?i)\b(?:json|response|syntaxerror|stack|unexpected|failed to execute)\b',
                            'Upload errors must not expose browser parser/Response diagnostics')
        self.assertRegex(text,r'(?i)(загруз|ответ|провер|ошиб|не удалось|неизвест)',
                         'The chip must explain failed upload in Russian')
        expect(self.page.get_by_role('button',name=queue.SEND)).to_be_disabled()
        before=list(self.operations);self.page.wait_for_timeout(200)
        self.assertEqual(self.operations,before,'Uncertain chunk must not retry automatically')
        self.assert_no_execution()
        begin=self.payloads[0].copy();self.retry().click()
        expect(self.page.get_by_text('Загружено',exact=True)).to_be_visible()
        self.assertEqual(self.operations.count(('POST','begin')),1)
        self.assertEqual(self.operations.count(('PUT','chunk')),1,'Status already confirmed all bytes; duplicate chunk prohibited')
        self.assertEqual(self.operations.count(('POST','status')),1)
        self.assertEqual(self.operations.count(('POST','finish')),1)
        self.assertEqual(self.payloads[0],begin)
        self.assertEqual(self.payloads[1],dict(attachment_id=self.aid))
        self.assertEqual(bytes(self.uploaded),b'\x00\x01\xff\x02')
        self.assert_no_execution()

    def test_manual_retry_refreshes_unavailable_options_then_stages_original_file_once(self):
        # INV-WATT-08: a cold unavailable observation is not permanent capability.
        self.mock_stage(available=False);self.select();self.choose_file()
        expect(self.retry()).to_be_visible()
        self.assertIn(('GET','options'),self.operations)
        expect(self.page.get_by_role('button',name=queue.SEND)).to_be_disabled()
        before=list(self.operations);self.available=True;self.page.wait_for_timeout(200)
        self.assertEqual(self.operations,before,'Capability recovery must wait for explicit user retry')
        self.retry().click()
        expect(self.page.get_by_text('Загружено',exact=True)).to_be_visible()
        after=self.operations[len(before):]
        self.assertEqual(after[0],('GET','options'),'Manual retry must read fresh options before any stage mutation')
        self.assertEqual(self.operations.count(('POST','begin')),1)
        self.assertEqual(self.operations.count(('PUT','chunk')),1)
        self.assertEqual(self.operations.count(('POST','finish')),1)
        self.assertEqual(self.payloads[0]['name'],'synthetic-proof.bin')
        self.assertRegex(self.payloads[0]['message_id'],r'^[0-9a-f-]{36}$')
        self.assertRegex(self.payloads[0]['upload_id'],r'^[0-9a-f-]{36}$')
        self.assertEqual(bytes(self.uploaded),b'\x00\x01\xff\x02')
        self.assert_no_execution()
