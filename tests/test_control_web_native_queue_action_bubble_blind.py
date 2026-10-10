"""One INV-WSESS-45 regression for transfer's new action UUID correlation."""
from copy import deepcopy
import unittest
from playwright.sync_api import expect
import live_sse_blind_support as live
import native_queue_blind_support as q
import test_control_web_native_queue_transfer_browser_blind as ui
from test_control_web_native_queue_transfer_blind import TARGET,SNAPSHOT


class NativeQueueActionBubbleBlind(unittest.TestCase):
    setUpClass=classmethod(ui.NativeQueueTransferBrowserBlind.setUpClass.__func__)
    setUp=ui.NativeQueueTransferBrowserBlind.setUp
    tearDown=ui.NativeQueueTransferBrowserBlind.tearDown
    until=ui.NativeQueueTransferBrowserBlind.until
    select=ui.NativeQueueTransferBrowserBlind.select
    pending_action=ui.NativeQueueTransferBrowserBlind.pending_action
    open_dialog=ui.NativeQueueTransferBrowserBlind.open_dialog

    def test_accepted_transfer_placeholder_merges_only_its_action_history_once(self):
        original=self.backend.session_queue_send_now
        def accepted_and_deleted(project,sid,qid,action,snapshot,expected):
            result=original(project,sid,qid,action,snapshot,expected)
            self.backend.queue_rows[sid]=[row for row in self.backend.queue_rows[sid] if row['queued_submission_id']!=qid]
            return result
        self.backend.session_queue_send_now=accepted_and_deleted
        self.select();dialog,_preview=self.open_dialog()
        dialog.get_by_role('button',name=ui.CONFIRM).click()
        self.until(lambda:len(self.transfer_calls)==1)
        action_id=self.transfer_calls[0][3]
        self.assertEqual(self.backend.queue_rows[live.SID],[])
        bubbles=self.page.locator('.chat-items article.chat-message').filter(has=self.page.get_by_text(SNAPSHOT,exact=True))
        expect(bubbles).to_have_count(1,timeout=3000)
        expect(self.page.get_by_role('button',name='Отправить сейчас',exact=True)).to_have_count(0)

        stamp=int(self.page.evaluate('Date.now()/1000'))
        value=live.history('Same text with another identity reached native history')
        value['turns'][0]['id']='different-native-turn'
        value['turns'][0]['items'].append(dict(id='different-client-user',role='user',text=SNAPSHOT,
            client_id=q.OTHER,truncated=False,timestamp=stamp,time_precision='item'))
        self.backend.value=deepcopy(value);self.fixture.transport.emit(live.snapshot(2,value=value))
        expect(self.page.get_by_text('Same text with another identity reached native history',exact=True)).to_have_count(1)
        expect(bubbles).to_have_count(2,timeout=3000)

        value['turns'].append(dict(id=TARGET,status='completed',items=[dict(id='native-action-user',role='user',text=SNAPSHOT,
            client_id=action_id,truncated=False,timestamp=stamp,time_precision='item'),
            dict(id='action-proof-marker',role='assistant',text='Exact action history reached UI',truncated=False,timestamp=stamp,time_precision='item')]))
        self.backend.value=deepcopy(value);self.fixture.transport.emit(live.snapshot(3,value=value))
        expect(self.page.get_by_text('Exact action history reached UI',exact=True)).to_have_count(1)
        expect(bubbles).to_have_count(2,timeout=3000)
        self.fixture.transport.emit(live.snapshot(4,value=value));self.page.wait_for_timeout(100)
        expect(bubbles).to_have_count(2)
        self.assertEqual(len([request for request in self.requests if request[0]=='POST']),1)
