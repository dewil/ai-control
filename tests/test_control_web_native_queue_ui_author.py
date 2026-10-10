"""Author regressions for queue draft and reader ownership; independent tests stay frozen."""
import unittest
from playwright.sync_api import expect
import test_control_web_native_queue_browser_blind as fixture


class QueueUIAuthor(unittest.TestCase):
    for name in ('setUpClass','setUp','tearDown','select','until','send_button','hold_send','send','queue_request','user_history'):
        locals()[name]=fixture.NativeQueueBrowserBlind.__dict__[name]

    def test_queued_explicit_model_refusal_preserves_draft_without_wire(self):
        self.select()
        model=self.page.get_by_role('combobox',name='Модель',exact=True,include_hidden=True)
        for summary in model.locator('xpath=ancestor::details[not(@open)]/summary').all():summary.click()
        model.select_option(label='Model Alpha')
        self.page.get_by_role('combobox',name='Уровень размышления',exact=True).select_option(label='high')
        self.send('Unsent queue override draft')
        expect(self.page.locator('textarea')).to_have_value('Unsent queue override draft')
        expect(self.page.locator('#send-status')).to_contain_text('Сразу')
        self.assertEqual([r for r in self.requests if r[0]=='POST'],[])

    def test_lease_queue_refresh_preserves_focused_reader_and_scroll(self):
        self.backend.queue_rows[fixture.live.SID]=[fixture.q.public_row('mac-long','mac-long-client','Long native queue row '+('read carefully '*700))]
        self.page.clock.install()
        self.select()
        article=self.page.get_by_text('Queue browser streamed ready A',exact=True).locator('xpath=ancestor::article')
        article.evaluate('(element)=>{element.tabIndex=-1;element.focus();window.scrollTo(0,100)}')
        before=article.bounding_box()['y']
        self.backend.queue_rows[fixture.live.SID].append(fixture.q.public_row('mac-later','mac-later-client','Later native queue marker'))
        self.page.clock.fast_forward(11000)
        self.until(lambda:len([r for r in self.requests if r[1]=='/api/session-queue'])>=2)
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate('document.activeElement.textContent.includes("Queue browser streamed ready A")'),True)
        expect(self.page.locator('#history-new')).to_be_visible()
        self.assertLessEqual(abs(article.bounding_box()['y']-before),2)

    def test_opaque_observational_disappearance_removes_pending_without_local_status_command(self):
        text='Mac opaque observational item'
        self.backend.queue_rows[fixture.live.SID]=[fixture.q.public_row('opaque-qid','opaque-Mac-client',text)]
        self.page.clock.install();self.select()
        expect(self.page.get_by_text(text,exact=True)).to_have_count(1)
        self.backend.queue_rows[fixture.live.SID]=[]
        self.page.clock.fast_forward(11000)
        expect(self.page.get_by_text(text,exact=True)).to_have_count(0)
        expect(self.page.get_by_role('button',name='Проверить доставку',exact=True)).to_have_count(0)
        self.assertFalse(any(r[1]=='/api/session-send-status' for r in self.requests))
        self.assertEqual([r for r in self.requests if r[0]=='POST'],[])

    def test_own_history_proof_supersedes_queued_ACK_without_unknown_lock(self):
        held=self.hold_send();self.select();self.send();payload=self.queue_request(held)
        self.user_history(payload['message_id'],fixture.q.TEXT)
        expect(self.page.get_by_text('Authoritative queued history proof',exact=True)).to_have_count(1)
        expect(self.page.locator('#send-status')).to_contain_text('принято')
        held[0].fulfill(status=200,json=dict(status='queued',message_id=payload['message_id'],queued_submission_id='gone-native-row'))
        expect(self.page.locator('textarea')).to_have_value('')
        expect(self.page.locator('#send-status')).to_contain_text('принято')
        self.assertTrue(self.page.locator('#chat-send').is_enabled())


class QueueRecoveryShadowUIAuthor(unittest.TestCase):
    for name in ('setUpClass','setUp','tearDown','select','until','send_button','send','user_history'):
        locals()[name]=fixture.NativeQueueBrowserBlind.__dict__[name]

    def seed_held(self,unrelated=False):
        self.backend.queue_rows[fixture.live.SID]=[]
        value=fixture.live.history()
        value['recent_sends']=[dict(status='delivery_unknown',message_id=fixture.q.MID,turn_id=None)]
        if unrelated:value['recent_sends'].append(dict(status='delivery_unknown',message_id=fixture.q.ACTION,turn_id=None))
        self.backend.value=value
        original=self.backend.session_queue
        def queue(project,sid):
            result=original(project,sid);result['recovery']=[dict(action_id='99999999-9999-4999-8999-999999999999',
                queued_submission_id='own-held-qid',text=fixture.q.TEXT,status='held',reason='target_changed')]
            return result
        self.backend.session_queue=queue
        self.status_calls=[]
        def status(project,sid,mid):
            self.status_calls.append(mid)
            if mid==fixture.q.MID:return dict(status='held',message_id=mid,queued_submission_id='own-held-qid',turn_id=None,reason='target_changed')
            return dict(status='delivery_unknown',message_id=mid,turn_id=None)
        self.backend.session_send_status=status

    def test_reload_own_unknown_held_copy_then_explicit_new_UUID_send(self):
        self.seed_held();self.select()
        self.page.evaluate('window.copyUUIDs=0;const original=crypto.randomUUID.bind(crypto);crypto.randomUUID=()=>{copyUUIDs++;return original()};undefined')
        self.page.get_by_role('button',name='В черновик',exact=True).click()
        self.until(lambda:self.page.locator('#chat-send').is_enabled())
        self.assertEqual(self.status_calls,[fixture.q.MID]);self.assertEqual(self.page.evaluate('copyUUIDs'),0)
        self.assertEqual([r for r in self.requests if r[0]=='POST'],[])
        late=fixture.live.history('Late old unknown history')
        late['recent_sends']=[dict(status='delivery_unknown',message_id=fixture.q.MID,turn_id=None)]
        self.fixture.transport.emit(fixture.live.snapshot(2,value=late))
        expect(self.page.get_by_text('Late old unknown history',exact=True)).to_have_count(1)
        self.assertTrue(self.page.locator('#chat-send').is_enabled())
        self.send_button().click();self.until(lambda:len(self.backend.enqueue_calls)==1)
        self.assertNotEqual(self.backend.enqueue_calls[0][2],fixture.q.MID)
        self.assertEqual(self.backend.enqueue_calls[0][3],fixture.q.TEXT)

    def test_copy_held_does_not_clear_an_unrelated_unknown_blocker(self):
        self.seed_held(unrelated=True);self.select();self.page.get_by_role('button',name='В черновик',exact=True).click()
        self.until(lambda:len(self.status_calls)==2)
        expect(self.page.locator('textarea')).to_have_value(fixture.q.TEXT)
        self.assertFalse(self.page.locator('#chat-send').is_enabled())
        self.assertEqual([r for r in self.requests if r[0]=='POST'],[])

    def test_confirmed_cancel_retires_only_matching_original_status_despite_late_unknown(self):
        self.page.clock.install();self.select();self.send();expect(self.page.locator('textarea')).to_have_value('')
        mid=self.backend.enqueue_calls[0][2]
        row=self.page.get_by_text(fixture.q.TEXT,exact=True).locator('xpath=ancestor::*[.//button][1]')
        row.get_by_role('button',name='Отменить',exact=True).click()
        expect(self.page.locator('#send-status')).to_contain_text('Отменено')
        late=fixture.live.history('Late cancelled original unknown history')
        late['recent_sends']=[dict(status='delivery_unknown',message_id=mid,turn_id=None)]
        self.fixture.transport.emit(fixture.live.snapshot(2,value=late))
        expect(self.page.get_by_text('Late cancelled original unknown history',exact=True)).to_have_count(1)
        expect(self.page.locator('#send-status')).to_contain_text('Отменено')
        self.backend.queue_rows[fixture.live.SID]=[fixture.q.public_row('queue-'+mid,mid,fixture.q.TEXT)]
        self.page.clock.fast_forward(11000)
        expect(self.page.get_by_text(fixture.q.TEXT,exact=True)).to_have_count(0)
        expect(self.page.locator('#send-status')).to_contain_text('Отменено')
        self.send('Explicit fresh message after confirmed cancel')
        self.until(lambda:len(self.backend.enqueue_calls)==2)
        self.assertNotEqual(self.backend.enqueue_calls[1][2],mid)
        self.assertEqual(len(self.backend.cancel_calls),1)
