"""Author regressions for queue draft and reader ownership; independent tests stay frozen."""
import unittest
from playwright.sync_api import expect
import test_control_web_native_queue_browser_blind as fixture


class QueueUIAuthor(unittest.TestCase):
    for name in ('setUpClass','setUp','tearDown','select','until','send_button','hold_send','send','queue_request'):
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
