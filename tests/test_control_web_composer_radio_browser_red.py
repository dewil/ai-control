"""INV-WATT-10: independent native radio acceptance; synthetic HTTP only."""
import re
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect
import test_control_web_native_queue_browser_blind as h


class ComposerRadioBrowserRED(unittest.TestCase):
    setUpClass = classmethod(h.NativeQueueBrowserBlind.setUpClass.__func__)
    setUp = h.NativeQueueBrowserBlind.setUp
    tearDown = h.NativeQueueBrowserBlind.tearDown
    select = h.NativeQueueBrowserBlind.select
    until = h.NativeQueueBrowserBlind.until
    hold_send = h.NativeQueueBrowserBlind.hold_send
    send = h.NativeQueueBrowserBlind.send
    send_button = h.NativeQueueBrowserBlind.send_button

    def radios(self):
        group = self.page.get_by_role('group', name=re.compile('Отправ|Режим', re.I)).or_(
            self.page.get_by_role('radiogroup', name=re.compile('Отправ|Режим', re.I)))
        expect(group).to_have_count(1)
        queue = group.get_by_role('radio', name='В очередь', exact=True)
        direct = group.get_by_role('radio', name='Сразу', exact=True)
        for radio in (queue, direct):
            expect(radio).to_be_visible()
            self.assertEqual(radio.evaluate('e => e.tagName+":"+e.type'), 'INPUT:radio')
        expect(group.get_by_role('radio')).to_have_count(2)
        return queue, direct

    def no_effects(self, before):
        changed = self.requests[before:]
        self.assertEqual([r for r in changed if 'attachment' in r[1]], [],
                         'Text-only radio change must not discover or stage attachments')
        self.assertEqual([r for r in changed if r[0] not in ('GET', 'HEAD')], [],
                         'Radio change must not send or enqueue')

    def test_native_group_default_keyboard_touch_and_draft_caret_at_320px(self):
        # INV-WATT-10. No substitution of model/effort selects.
        self.select(); queue, direct = self.radios(); expect(queue).to_be_checked()
        draft = self.page.locator('textarea'); draft.fill('draft Ω unchanged')
        draft.evaluate('e => e.setSelectionRange(3, 7)')
        before = len(self.requests)
        queue.focus(); queue.press('ArrowRight'); expect(direct).to_be_checked()
        direct.press('ArrowLeft'); expect(queue).to_be_checked()
        direct.focus(); direct.press('Space'); expect(direct).to_be_checked()
        for radio in (queue, direct):
            radio.click(); expect(radio).to_be_checked()
            expect(draft).to_have_value('draft Ω unchanged')
            self.assertEqual(draft.evaluate('e => [e.selectionStart,e.selectionEnd]'), [3,7])
        self.no_effects(before)
        self.page.set_viewport_size(dict(width=320,height=900))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),321)
        for radio in (queue,direct):
            # Native input may be small; its associated label is the touch target.
            box = radio.evaluate('e => {const l=e.labels?.[0]||e; const b=l.getBoundingClientRect(); return {w:b.width,h:b.height,x:b.x,right:b.right}}')
            self.assertGreaterEqual(box['w'],44); self.assertGreaterEqual(box['h'],44)
            self.assertGreaterEqual(box['x'],-1); self.assertLessEqual(box['right'],321)
        model = self.page.get_by_role('combobox', name='Модель',exact=True,include_hidden=True)
        effort = self.page.get_by_role('combobox', name='Уровень размышления',exact=True,include_hidden=True)
        expect(model).to_have_count(1); expect(effort).to_have_count(1)

    def test_unsupported_queue_disabled_explained_direct_default_no_attachment_discovery(self):
        # INV-WATT-10: unavailable option remains explicit.
        self.backend.supported=False; self.select(); queue,direct=self.radios()
        expect(queue).to_be_disabled(); expect(direct).to_be_checked()
        expect(self.page.get_by_text(re.compile('Очеред.*не поддерж|Очеред.*недоступ',re.I)).first).to_be_visible()
        before=len(self.requests);direct.click();direct.press('Space');self.no_effects(before)

    def test_pending_and_unknown_mode_change_preserves_payload_draft_and_never_replays(self):
        # INV-WATT-10: request snapshot cannot follow subsequent radio changes.
        held=self.hold_send();self.select();queue,direct=self.radios()
        self.send('immutable pending draft');self.until(lambda:len(held)==1)
        request=held[0].request;payload=request.post_data_json
        self.assertEqual(urlsplit(request.url).path,'/api/session-queue')
        self.assertEqual(payload['text'],'immutable pending draft')
        self.assertNotIn('selection',payload,'Native queue preserves existing session settings contract')
        before=len(self.requests)
        if direct.is_enabled():direct.click()
        self.no_effects(before)
        held[0].fulfill(status=503,json=dict(status='delivery_unknown',message_id=payload['message_id'],queued_submission_id=None))
        expect(self.page.locator('textarea')).to_have_value('immutable pending draft')
        before=len(self.requests)
        if queue.is_enabled():queue.click()
        if direct.is_enabled():direct.click()
        self.page.wait_for_timeout(100);self.no_effects(before)
        self.assertEqual(len(held),1)
        self.assertEqual(request.post_data_json,payload)

    def test_direct_radio_keeps_old_text_route_and_selection(self):
        # INV-WATT-10: radio switch creates no message; submit uses old schema.
        held=self.hold_send();self.select();_,direct=self.radios();before=len(self.requests)
        direct.click();self.no_effects(before)
        model=self.page.get_by_role('combobox',name='Модель',exact=True,include_hidden=True)
        for summary in model.locator('xpath=ancestor::details[not(@open)]/summary').all():summary.click()
        model.select_option(label='Model Alpha')
        self.page.get_by_role('combobox',name='Уровень размышления',exact=True).select_option(label='high')
        self.send('direct text only')
        self.until(lambda:len(held)==1)
        request=held[0].request
        self.assertEqual(urlsplit(request.url).path,'/api/session-send')
        self.assertEqual(set(request.post_data_json),{'project','sid','message_id','text','selection'})
        self.assertEqual(request.post_data_json['selection'],dict(catalog_id='a'*64,model_id='model-alpha',effort='high'))
        self.assertEqual(request.post_data_json['text'],'direct text only')
