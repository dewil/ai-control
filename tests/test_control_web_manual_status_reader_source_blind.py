"""Independent INV45 manual receipt completion must preserve unrelated reader anchor.

Public diagnostic supplied only a trigger; oracle derives ±8px from approved INV45.
Actual DOM and existing synthetic HTTP fixture; no source/future fix inspection.
"""
import re,unittest
from playwright.sync_api import expect
import test_control_web_ux_package_blind_red as fixture
from test_control_web_chat_width_browser import SID

class ManualStatusReaderSourceBlind(unittest.TestCase):
    setUpClass=classmethod(fixture.WebUXBlindBrowser.setUpClass.__func__)
    setUp=fixture.WebUXBlindBrowser.setUp
    tearDown=fixture.WebUXBlindBrowser.tearDown
    control=fixture.WebUXBlindBrowser.control
    calls=fixture.WebUXBlindBrowser.calls
    open=fixture.WebUXBlindBrowser.open
    def test_INV45_status_completion_keeps_unrelated_canonical_reader_anchor(self):
        self.page.set_viewport_size({'width':390,'height':500});self.open()
        prefix='[Synthetic anchor link](https://example.test/)\n\n'+'Initial readable line\n'*25+'\n\nStable reader tail '
        self.control(send_delay=.1)
        self.page.locator('textarea').fill(prefix+'0');self.page.locator('#chat-send').click()
        self.page.locator('#send-status').filter(has_text=re.compile('принят',re.I)).wait_for()
        self.control(canonical=True,canonical_text=prefix);self.page.locator('#chat-refresh').click()
        canonical=self.page.locator('#chat-items article').filter(has=self.page.get_by_role('link',name='Synthetic anchor link')).first
        expect(canonical).not_to_have_attribute('data-local-outgoing','true')
        self.control(send_delay=.1,send_status='delivery_unknown',canonical=True,canonical_text=prefix)
        self.page.locator('textarea').fill('Separate unknown attempt');self.page.locator('#chat-send').click()
        expect(self.page.locator('#send-check')).to_be_visible()
        canonical.get_by_role('link',name='Synthetic anchor link').focus()
        changed='[Synthetic anchor link](https://example.test/)\n\n'+'Expanded canonical line\n'*60+'\n\nStable reader tail '
        self.control(canonical=True,canonical_text=changed,checked_status='accepted')
        self.page.locator('#chat-refresh').evaluate('e=>e.click()');expect(self.page.locator('#chat-refresh')).to_be_enabled()
        self.assertNotIn('Expanded canonical',canonical.inner_text(),'Fixture must establish a deferred unrelated canonical mutation')
        held=[];self.page.route('**/api/session-send-status?*',lambda route:held.append(route))
        self.page.locator('#send-check').click()
        self.page.wait_for_timeout(50);self.assertEqual(len(held),1)
        draft=self.page.locator('textarea');draft.fill('Synthetic preserved unsent draft');draft.evaluate('e=>e.focus({preventScroll:true})')
        tail=canonical.get_by_text('Stable reader tail 0',exact=True)
        tail.evaluate('e=>window.scrollTo(0,window.scrollY+e.getBoundingClientRect().top-40)')
        before=tail.bounding_box()['y'];history_calls=len(self.calls('history'));mid=self.calls('send')[-1]['message_id']
        held[0].fulfill(json={'status':'accepted','message_id':mid,'turn_id':SID})
        expect(self.page.locator('#send-status')).to_contain_text(re.compile('принят',re.I));self.page.wait_for_timeout(100)
        self.assertEqual(len(self.calls('history')),history_calls,'Manual status completion must not fetch additional history')
        self.assertEqual(len(self.calls('send')),2,'Manual status is read-only and cannot resend')
        self.assertEqual(draft.input_value(),'Synthetic preserved unsent draft');self.assertTrue(draft.evaluate('e=>e===document.activeElement'))
        after=tail.bounding_box()['y'];self.assertLessEqual(abs(after-before),8,f'Unrelated reader paragraph jumped {after-before}px during receipt completion')

if __name__=='__main__':unittest.main()
