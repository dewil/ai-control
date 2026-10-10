"""Author current-view status/read-only interop controls for the new queue command."""
import unittest
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import expect
import test_control_web_navigation_start_browser_blind as blind


class QueueStartBrowserAuthor(unittest.TestCase):
    setUpClass=classmethod(blind.NavigationStartBrowserBlind.setUpClass.__func__)
    setUp=blind.NavigationStartBrowserBlind.setUp
    tearDown=blind.NavigationStartBrowserBlind.tearDown
    until=blind.NavigationStartBrowserBlind.until
    select=blind.NavigationStartBrowserBlind.select
    navposts=blind.NavigationStartBrowserBlind.navposts
    start_button=blind.NavigationStartBrowserBlind.start_button
    dialog=blind.NavigationStartBrowserBlind.dialog

    def test_unknown_manual_status_survives_same_page_reselection_without_replay(self):
        self.backend.start_state='delivery_unknown';self.select()
        self.dialog().get_by_role('button',name=blind.CONFIRM).click()
        check=self.page.get_by_role('button',name='Проверить статус запуска',exact=True)
        expect(check).to_be_visible()
        action=next(call[4] for call in self.backend.nav_calls if call[0]=='start')
        self.page.get_by_role('button',name='LIVE synthetic B',exact=False).click()
        expect(self.page.get_by_text('Queue browser B history',exact=True)).to_have_count(1)
        self.page.get_by_role('button',name='LIVE synthetic A',exact=False).click()
        expect(check).to_be_visible()
        reads=[]
        def status(route):reads.append(parse_qs(urlsplit(route.request.url).query));route.continue_()
        self.page.route('**/api/session-send-status?*',status)
        check.click();self.until(lambda:len(reads)==1)
        self.assertEqual(reads[0]['message_id'],[action])
        self.assertEqual(len([call for call in self.backend.nav_calls if call[0]=='start']),1)
        self.assertFalse(self.start_button().is_enabled())

    def test_unknown_command_blocks_only_its_qid(self):
        self.backend.start_state='delivery_unknown'
        self.backend.queue_rows[blind.live.SID].append(blind.q.public_row('other-qid','opaque-mac-second','Another queued native row'))
        self.select();self.dialog().get_by_role('button',name=blind.CONFIRM).click()
        expect(self.page.get_by_role('button',name='Проверить статус запуска',exact=True)).to_be_visible()
        self.assertFalse(self.start_button().is_enabled())
        other=self.page.get_by_text('Another queued native row',exact=True).locator('xpath=ancestor::*[.//button][1]').get_by_role('button',name=blind.START)
        expect(other).to_be_enabled()
        self.assertEqual(len([call for call in self.backend.nav_calls if call[0]=='start']),1)
