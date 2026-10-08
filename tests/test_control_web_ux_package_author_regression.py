"""Author supplemental INV-WSESS-43/45 races using only synthetic public fixtures."""
import unittest
import re
import test_control_web_ux_package_blind_red as fixture
from playwright.sync_api import expect
from test_control_web_chat_width_browser import SID

class WebUXAuthorRegression(unittest.TestCase):
    setUpClass=classmethod(fixture.WebUXBlindBrowser.setUpClass.__func__)
    setUp=fixture.WebUXBlindBrowser.setUp
    tearDown=fixture.WebUXBlindBrowser.tearDown
    control=fixture.WebUXBlindBrowser.control
    calls=fixture.WebUXBlindBrowser.calls
    open=fixture.WebUXBlindBrowser.open
    toggle=fixture.WebUXBlindBrowser.toggle
    local=fixture.WebUXBlindBrowser.local
    send=fixture.WebUXBlindBrowser.send
    poll=fixture.WebUXBlindBrowser.poll

    def test_INV43_reload_valid_and_missing_deep_link(self):
        self.open();self.toggle().click()
        self.page.reload();self.page.locator('#chat-panel').wait_for(state='visible')
        self.page.get_by_text('Fixture readable message 23',exact=True).wait_for()
        self.assertEqual(self.toggle().get_attribute('aria-expanded'),'false')
        self.page.goto(self.url+'?project=demo&sid=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
        self.page.get_by_text('Сессия из ссылки не найдена среди доступных сессий. Выберите другую из списка.',exact=True).wait_for()
        self.assertEqual(self.toggle().get_attribute('aria-expanded'),'true')

    def test_INV45_history_before_ack_never_resurrects_local(self):
        self.open();self.control(send_delay=2,canonical=True)
        self.send();self.page.wait_for_timeout(200)
        self.page.locator('#chat-refresh').click()
        self.page.get_by_text('Canonical redacted 0',exact=True).wait_for()
        self.assertEqual(self.local().count(),0)
        self.page.wait_for_timeout(2200)
        self.assertEqual(self.local().count(),0)
        self.assertEqual(len(self.calls('send')),1)

    def test_INV45_manual_status_updates_retained_unknown_entry(self):
        self.open();self.control(send_delay=1,send_status='delivery_unknown',checked_status='accepted')
        self.send();self.page.wait_for_timeout(1300)
        self.assertIn('Доставка неизвестна',self.local().inner_text())
        self.page.locator('#send-check').click()
        self.page.wait_for_timeout(250)
        self.assertIn('Принято',self.local().inner_text())
        self.assertEqual(len(self.calls('send')),1)
        self.assertEqual(len(self.calls('status')),1)

    def test_INV45_ack_preserves_focus_in_local_markdown(self):
        self.open();self.control(send_delay=1)
        self.page.locator('textarea').fill('[Synthetic link](https://example.test/)')
        self.page.locator('#chat-send').click()
        link=self.local().get_by_role('link',name='Synthetic link');link.focus()
        self.page.wait_for_timeout(1300)
        self.assertTrue(link.evaluate('e=>e===document.activeElement'))
        self.assertIn('Принято',self.local().inner_text())

    def test_INV45_malformed_json_correlation_is_not_a_uuid(self):
        self.open();self.control(send_delay=1)
        mid=self.send();self.page.wait_for_timeout(1300)
        self.control(canonical=True,client_id=[mid])
        before=len(self.calls('history'));self.page.locator('#chat-refresh').click()
        expect(self.page.locator('#chat-refresh')).to_be_enabled()
        self.assertGreater(len(self.calls('history')),before)
        self.assertEqual(self.local().count(),1,'JSON array must not coerce to a UUID')

    def test_INV45_same_scope_return_before_ack_updates_local_status(self):
        self.open();self.control(send_delay=2)
        self.send()
        self.page.get_by_role('button',name=re.compile('^Other UX')).click()
        self.page.get_by_text('Fixture readable message 23',exact=True).wait_for()
        self.session.click();self.page.get_by_text('Fixture readable message 23',exact=True).wait_for()
        self.page.wait_for_timeout(2400)
        self.assertIn('Принято',self.local().inner_text())
        self.assertEqual(len(self.calls('send')),1)

    def test_INV45_canonical_same_content_preserves_link_node_and_reader_anchor(self):
        self.page.set_viewport_size({'width':390,'height':500});self.open();self.control(send_delay=1)
        prefix='[Synthetic canonical link](https://example.test/)\n'+'Readable synthetic line\n'*25+'Tail '
        self.page.locator('textarea').fill(prefix+'0');self.page.locator('#chat-send').click()
        self.page.wait_for_timeout(1300)
        link=self.local().get_by_role('link',name='Synthetic canonical link');link.focus()
        self.page.evaluate('window.savedSyntheticFocus=document.activeElement')
        self.local().evaluate('e=>window.scrollTo(0,window.scrollY+e.getBoundingClientRect().top-20)')
        before=link.bounding_box()['y'];self.control(canonical=True,canonical_text=prefix);self.poll()
        canonical=self.page.locator('#chat-items article').filter(has=self.page.get_by_role('link',name='Synthetic canonical link'))
        self.assertEqual(self.local().count(),0)
        self.assertTrue(self.page.evaluate('document.activeElement===window.savedSyntheticFocus'),'Same safe canonical link must retain DOM identity/focus')
        after=canonical.get_by_role('link',name='Synthetic canonical link').bounding_box()['y']
        self.assertLessEqual(abs(after-before),8,'Local reader anchor must remap to canonical item')

    def test_INV45_canonical_redaction_removes_old_focused_link_and_uses_safe_focus(self):
        self.open();self.control(send_delay=1)
        self.page.locator('textarea').fill('[Synthetic private link](https://example.test/)')
        self.page.locator('#chat-send').click();self.page.wait_for_timeout(1300)
        self.local().get_by_role('link',name='Synthetic private link').focus()
        self.control(canonical=True);self.poll()
        self.assertEqual(self.local().count(),0)
        self.assertEqual(self.page.get_by_role('link',name='Synthetic private link').count(),0)
        self.assertIn('Canonical redacted 0',self.page.locator('#chat-items').inner_text())
        self.assertTrue(self.page.locator('#chat-items article').filter(has_text='Canonical redacted 0').evaluate('e=>e===document.activeElement'))

    def test_INV45_z_logout_discards_local_text_without_resending(self):
        self.open();self.control(send_delay=1)
        self.send('Synthetic logout-only outgoing text')
        self.page.locator('#logout').click();self.page.locator('#login').wait_for(state='visible')
        self.page.wait_for_timeout(1300)
        self.assertEqual(self.local().count(),0)
        self.assertNotIn('Synthetic logout-only outgoing text',self.page.locator('body').inner_text())
        self.assertEqual(len(self.calls('send')),1)

if __name__=='__main__':unittest.main()
