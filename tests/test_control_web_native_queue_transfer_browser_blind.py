"""Approved in-page snapshot confirmation and manual recovery UI RED."""
from copy import deepcopy
import re
from urllib.parse import urlsplit
import unittest
from playwright.sync_api import expect
import live_sse_blind_support as live
import native_queue_blind_support as q
import test_control_web_native_queue_browser_blind as core
from test_control_web_native_queue_transfer_blind import TARGET,SUCCESSOR,SNAPSHOT

CONFIRM=re.compile(r'^(Подтвердить|Отправить|Отправить сейчас|Да, отправить)$',re.I)


class NativeQueueTransferBrowserBlind(unittest.TestCase):
    setUpClass=classmethod(core.NativeQueueBrowserBlind.setUpClass.__func__)
    until=core.NativeQueueBrowserBlind.until
    select=core.NativeQueueBrowserBlind.select
    tearDown=core.NativeQueueBrowserBlind.tearDown
    def setUp(self):
        core.NativeQueueBrowserBlind.setUp(self)
        self.recovery_rows={live.SID:[],live.OTHER:[]};self.transfer_calls=[]
        original=self.backend.session_queue
        def queue(project,sid):
            value=original(project,sid);value.update(active_turn_id=TARGET,send_now_supported=True,
                send_now_reason=None,recovery=deepcopy(self.recovery_rows.get(sid,[])))
            return value
        self.backend.session_queue=queue
        def send_now(project,sid,qid,action,snapshot,expected):
            self.transfer_calls.append((project,sid,qid,action,snapshot,expected))
            return dict(status='accepted',message_id=action,queued_submission_id=qid,turn_id=expected,reason=None)
        self.backend.session_queue_send_now=send_now
        self.backend.queue_rows[live.SID]=[q.public_row('mac-transfer-id','mac-transfer-client',SNAPSHOT)]
        self.native_dialogs=[];self.page.on('dialog',lambda dialog:(self.native_dialogs.append(dialog.type),dialog.dismiss()))
    def pending_action(self,text=SNAPSHOT):
        expect(self.page.get_by_text(text,exact=True)).to_have_count(1)
        row=self.page.get_by_text(text,exact=True).locator('xpath=ancestor::*[.//button][1]')
        action=row.get_by_role('button',name='Отправить сейчас',exact=True)
        self.assertEqual(action.count(),1,'Busy native row requires explicit send-now action');return action
    def open_dialog(self,text=SNAPSHOT):
        self.pending_action(text).click();dialog=self.page.get_by_role('dialog')
        expect(dialog).to_be_visible();self.assertEqual(dialog.get_attribute('aria-modal'),'true')
        expect(dialog.get_by_text(re.compile('Будет отправлен показанный текст',re.I)).first).to_be_visible()
        expect(dialog.get_by_text(re.compile('Изменения.*Mac.*могут.*не.*попасть',re.I|re.S)).first).to_be_visible()
        preview=dialog.get_by_text(text,exact=True)
        if not preview.count():
            preview=dialog.get_by_role('textbox');self.assertEqual(preview.count(),1);self.assertEqual(preview.input_value(),text)
        else:self.assertEqual(preview.text_content(),text)
        self.assertEqual(self.native_dialogs,[],'Owner chose accessible DOM dialog, never window.confirm')
        return dialog,preview
    def posts(self):return [request for request in self.requests if request[0]=='POST']

    def test_confirmation_captures_shown_snapshot_and_late_ACK_cannot_touch_other_draft(self):
        # INV-SQUEUE-06A/B: explicit confirm, captured row/turn/snapshot/action.
        held=[];self.page.route('**/api/session-queue-send-now',lambda route:held.append(route))
        self.select();dialog,_preview=self.open_dialog();self.assertEqual(self.posts(),[],'Opening/selecting dialog must not send')
        self.backend.queue_rows[live.SID][0]['text']='Concurrent newer Mac text'
        confirm=dialog.get_by_role('button',name=CONFIRM);self.assertEqual(confirm.count(),1);confirm.click()
        self.until(lambda:len(held)==1);payload=held[0].request.post_data_json
        self.assertEqual(set(payload),{'project','sid','queued_submission_id','action_id','snapshot_text','expected_turn_id'})
        self.assertEqual((payload['project'],payload['sid'],payload['queued_submission_id'],payload['snapshot_text'],payload['expected_turn_id']),('demo',live.SID,'mac-transfer-id',SNAPSHOT,TARGET))
        self.assertRegex(payload['action_id'],r'^[0-9a-f-]{36}$')
        self.page.get_by_role('button',name='LIVE synthetic B',exact=False).click()
        expect(self.page.get_by_text('Queue browser B history',exact=True)).to_have_count(1)
        self.page.locator('textarea').fill('Unrelated B unsent draft')
        held[0].fulfill(status=200,json=dict(status='accepted',message_id=payload['action_id'],queued_submission_id='mac-transfer-id',turn_id=TARGET,reason=None))
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.locator('textarea').input_value(),'Unrelated B unsent draft')
        expect(self.page.get_by_text(SNAPSHOT,exact=True)).to_have_count(0)
        self.assertEqual(len(self.posts()),1)

    def test_escape_cancel_and_mobile_scrollable_preview_never_send(self):
        # INV-SQUEUE-06A: compatible role-based DOM dialog, not a specific tag/CSS.
        text=('Operator selected long snapshot line\n'*250)
        self.backend.queue_rows[live.SID]=[q.public_row('mac-long-id','mac-long-client',text)]
        self.select()
        for width in [320,360]:
            self.page.set_viewport_size(dict(width=width,height=900));dialog,preview=self.open_dialog(text)
            self.assertEqual(self.posts(),[])
            box=dialog.bounding_box();self.assertIsNotNone(box)
            self.assertGreaterEqual(box['x'],-1);self.assertLessEqual(box['x']+box['width'],width+1)
            scrollable=preview.evaluate('''element=>{let node=element;while(node){const style=getComputedStyle(node);if(/auto|scroll/.test(style.overflowY)&&node.scrollHeight>node.clientHeight+1)return true;if(node.matches('[role="dialog"],dialog'))break;node=node.parentElement;}return false;}''')
            self.assertTrue(scrollable,'Full selected text needs a bounded scrollable preview')
            for button in dialog.get_by_role('button').all():
                control=button.bounding_box();self.assertIsNotNone(control)
                self.assertGreaterEqual(control['x'],-1);self.assertLessEqual(control['x']+control['width'],width+1)
                self.assertGreaterEqual(control['y'],-1);self.assertLessEqual(control['y']+control['height'],901)
            self.page.keyboard.press('Escape');expect(dialog).to_have_count(0)
        self.assertEqual(self.posts(),[]);self.assertEqual(self.transfer_calls,[])

    def test_held_recovery_restores_after_reload_copy_to_draft_has_zero_network_action(self):
        # INV-SQUEUE-06E: recovery is diagnostic data, never another automatic queue.
        self.backend.queue_rows[live.SID]=[]
        self.recovery_rows[live.SID]=[dict(action_id=q.ACTION,queued_submission_id='deleted-held-id',text=SNAPSHOT,status='held',reason='target_changed')]
        self.select();expect(self.page.get_by_text(SNAPSHOT,exact=True)).to_have_count(1)
        self.select();expect(self.page.get_by_text(SNAPSHOT,exact=True)).to_have_count(1)
        before=len(self.posts())
        self.page.evaluate("window.recoveryCopyUUIDs=0;const originalUUID=crypto.randomUUID.bind(crypto);crypto.randomUUID=()=>{recoveryCopyUUIDs++;return originalUUID()};undefined")
        self.page.get_by_role('button',name='В черновик',exact=True).click()
        expect(self.page.locator('textarea')).to_have_value(SNAPSHOT)
        self.assertEqual(self.page.evaluate('recoveryCopyUUIDs'),0,'Copying recovery text must not create a new delivery action UUID')
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.posts()),before,'Recovery copy sent/requeued/deleted or minted a new action')
        self.assertEqual(self.transfer_calls,[]);self.assertEqual(self.backend.enqueue_calls,[])
