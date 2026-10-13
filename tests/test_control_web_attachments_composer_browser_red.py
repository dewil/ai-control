"""INV-WATT-08/10 browser inputs and frozen public stage response DTOs."""
import re
import unittest
from playwright.sync_api import expect
from control_browser_helpers import session_navigator
import test_control_web_native_queue_browser_blind as h

class AttachmentsComposerBrowserRED(unittest.TestCase):
    setUpClass=classmethod(h.NativeQueueBrowserBlind.setUpClass.__func__)
    setUp=h.NativeQueueBrowserBlind.setUp
    tearDown=h.NativeQueueBrowserBlind.tearDown
    select=h.NativeQueueBrowserBlind.select
    until=h.NativeQueueBrowserBlind.until

    def paste(self,files=True,text=''):
        return self.page.locator('textarea').evaluate('''(e,{files,text}) => {
            e.focus();const d=new DataTransfer();
            if(files)d.items.add(new File([new Uint8Array([0,1,255,2])],'<fixture>.bin',{type:'application/octet-stream'}));
            if(text)d.setData('text/plain',text);
            const ev=new ClipboardEvent('paste',{clipboardData:d,bubbles:true,cancelable:true});
            e.dispatchEvent(ev);return ev.defaultPrevented;
        }''',dict(files=files,text=text))

    def test_chooser_multiple_any_type_and_cancel_keeps_draft(self):
        # INV-WATT-08: real chooser is independent of clipboard support.
        self.select();draft=self.page.locator('textarea');draft.fill('chooser draft')
        file=self.page.locator('input[type=file]');expect(file).to_have_count(1)
        self.assertTrue(file.evaluate('e=>e.multiple'))
        self.assertIn(file.get_attribute('accept'),(None,''))
        self.assertFalse(file.is_visible(),'File input is controlled by the paperclip')
        clip=self.page.get_by_role('button',name=re.compile('Прикреп|Влож|файл',re.I))
        expect(clip).to_have_count(1)
        before=len(self.requests)
        with self.page.expect_file_chooser() as pending:clip.click()
        pending.value.set_files([])
        expect(draft).to_have_value('chooser draft')
        self.assertEqual([r for r in self.requests[before:] if r[0]!='GET'],[])

    def test_file_paste_retains_escaped_chip_and_never_auto_sends_during_stage(self):
        # INV-WATT-08: original bytes staged only, no implicit native execution.
        held=[];self.page.route(re.compile('/api/session-attachment-(?:options|begin|chunk|finish|status)'),lambda r:held.append(r))
        self.select();self.page.locator('textarea').fill('mixed draft')
        self.paste(text='pasted text')
        expect(self.page.get_by_text('<fixture>.bin',exact=True)).to_be_visible()
        self.assertEqual(self.page.locator('fixture').count(),0,'Filename must render as text, not HTML')
        self.assertIn('mixed draft',self.page.locator('textarea').input_value())
        self.assertIn('pasted text',self.page.locator('textarea').input_value())
        self.assertEqual([r for r in self.requests if r[0]=='POST' and re.search('/api/session-(?:send|queue|enqueue)',r[1])],[])
        self.assertEqual(self.backend.direct_calls,[]);self.assertEqual(self.backend.enqueue_calls,[])
        chip=self.page.get_by_text('<fixture>.bin',exact=True).locator('xpath=ancestor::*[.//button][1]')
        remove=chip.get_by_role('button',name=re.compile('Удал|Убр|Remove',re.I));expect(remove).to_be_visible()
        remove.click();expect(self.page.get_by_text('<fixture>.bin',exact=True)).to_have_count(0)
        for route in held:route.abort()

    def test_plain_text_paste_does_not_prevent_browser_default_or_discover_attachments(self):
        # INV-WATT-08/10: synthetic event checks cancellation; real insertText is
        # browser default surrogate because dispatchEvent doesn't insert text.
        self.select();draft=self.page.locator('textarea');draft.fill('before ')
        draft.evaluate('e=>e.setSelectionRange(e.value.length,e.value.length)')
        before=len(self.requests)
        self.assertFalse(self.paste(files=False,text='/tmp/path-is-only-text.pdf'))
        self.page.keyboard.insert_text('/tmp/path-is-only-text.pdf')
        expect(draft).to_have_value('before /tmp/path-is-only-text.pdf')
        self.assertEqual([r for r in self.requests[before:] if 'attachment' in r[1]],[])
        self.assertEqual(self.backend.direct_calls,[]);self.assertEqual(self.backend.enqueue_calls,[])

    def stage_routes(self,hold_finish=False):
        import hashlib,time
        aid='88888888-8888-4888-8888-888888888888'
        self.finish_held=[];self.stage_requests=[];self.stage_bytes=bytearray()
        def stage(route):
            from urllib.parse import urlsplit
            path=urlsplit(route.request.url).path;self.stage_requests.append(route.request)
            if path.endswith('options'):
                route.fulfill(status=200,json=dict(available=True,images=True,files=True,direct=True,queue=True,max_files=8,max_file_bytes=20971520,max_message_bytes=41943040,chunk_bytes=49152,reason=None));return
            if path.endswith('discard'):
                route.fulfill(status=200,json=dict(attachment_id=aid,state='discarded'));return
            if path.endswith('begin'):self.stage_size=route.request.post_data_json['size']
            if path.endswith('chunk'):self.stage_bytes.extend(route.request.post_data_buffer)
            if path.endswith('finish') and hold_finish:self.finish_held.append(route);return
            sealed=path.endswith('finish')
            route.fulfill(status=200,json=dict(attachment_id=aid,state='sealed' if sealed else 'receiving',bytes=len(self.stage_bytes),size=self.stage_size,sha256=hashlib.sha256(self.stage_bytes).hexdigest() if sealed else None,expires_at=int(time.time())+1800,mode='file'))
        self.page.route(re.compile('/api/session-attachment-(?:options|begin|chunk|finish|status|discard)'),stage)
        return aid

    def choose_file(self):
        file=self.page.locator('input[type=file]');expect(file).to_have_count(1)
        file.set_input_files(dict(name='synthetic-proof.bin',mimeType='application/octet-stream',buffer=b'\x00\x01\xff\x02'))
        expect(self.page.get_by_text('synthetic-proof.bin',exact=True)).to_be_visible()

    def test_late_seal_response_cannot_attach_A_file_to_B_draft(self):
        # INV-WATT-08: late stage ownership is fullSID + captured draft.
        import hashlib,time
        aid=self.stage_routes(hold_finish=True);self.select();self.choose_file()
        self.until(lambda:len(self.finish_held)==1)
        session_navigator(self.page);self.page.get_by_role('button',name='LIVE synthetic B',exact=False).click()
        expect(self.page.get_by_text('Queue browser B history',exact=True)).to_be_visible()
        draft=self.page.locator('textarea');draft.fill('private B draft')
        self.finish_held[0].fulfill(status=200,json=dict(attachment_id=aid,state='sealed',bytes=4,size=4,sha256=hashlib.sha256(b'\x00\x01\xff\x02').hexdigest(),expires_at=int(time.time())+1800,mode='file'))
        self.page.wait_for_timeout(100)
        expect(draft).to_have_value('private B draft')
        expect(self.page.get_by_text('synthetic-proof.bin',exact=True)).to_have_count(0)
        self.assertEqual(self.backend.direct_calls,[]);self.assertEqual(self.backend.enqueue_calls,[])

    def test_unknown_attachment_send_locks_manifest_and_never_retries(self):
        # INV-WATT-04/08: unknown retains exact IDs and cannot be bypassed.
        aid=self.stage_routes();held=[]
        self.page.route(re.compile('/api/session-(?:send|enqueue)-attachments$'),lambda r:held.append(r))
        self.select();self.choose_file()
        expect(self.page.get_by_text(re.compile('Загружено')).first).to_be_visible()
        self.page.locator('textarea').fill('file draft')
        self.page.get_by_role('button',name=h.SEND).click();self.until(lambda:len(held)==1)
        request=held[0].request;payload=request.post_data_json
        self.assertEqual(payload['attachment_ids'],[aid]);self.assertEqual(payload['text'],'file draft')
        held[0].fulfill(status=503,json=dict(message_id=payload['message_id'],status='delivery_unknown',turn_id=None,queued_submission_id=None))
        expect(self.page.locator('textarea')).to_have_value('file draft')
        expect(self.page.get_by_text('synthetic-proof.bin',exact=True)).to_be_visible()
        chip=self.page.get_by_text('synthetic-proof.bin',exact=True).locator('xpath=ancestor::*[.//button][1]')
        remove=chip.get_by_role('button',name=re.compile('Удал|Убр|Remove',re.I))
        self.assertTrue(remove.count()==0 or not remove.is_enabled(),'Unknown manifest must not be editable')
        button=self.page.get_by_role('button',name=h.SEND);expect(button).to_be_disabled()
        self.page.wait_for_timeout(150);self.assertEqual(len(held),1)
        self.assertEqual(request.post_data_json,payload)
