"""Server-derived unknown blockers survive fresh browser context, public spec71473b6."""
from copy import deepcopy
from urllib.parse import urlsplit,parse_qs
import unittest
from playwright.sync_api import expect
import live_sse_blind_support as live
import native_queue_blind_support as q
import test_control_web_navigation_start_browser_blind as existing

class QueueStartBlockersBrowserBlind(unittest.TestCase):
    setUpClass=classmethod(existing.NavigationStartBrowserBlind.setUpClass.__func__)
    setUp=existing.NavigationStartBrowserBlind.setUp
    tearDown=existing.NavigationStartBrowserBlind.tearDown
    until=existing.NavigationStartBrowserBlind.until
    select=existing.NavigationStartBrowserBlind.select
    start_button=existing.NavigationStartBrowserBlind.start_button
    pins_title=existing.NavigationStartBrowserBlind.pins_title
    dialog=existing.NavigationStartBrowserBlind.dialog
    navposts=existing.NavigationStartBrowserBlind.navposts

    def fresh_context(self):
        self.context.close();self.context=self.browser.new_context(viewport=dict(width=360,height=900));self.addCleanup(self.context.close)
        name,value=self.fixture.cookie.split('=',1);self.context.add_cookies([dict(name=name,value=value,url=self.fixture.origin)])
        self.page=self.context.new_page();self.page.set_default_timeout(2500);self.requests=[]
        self.page.on('request',lambda r:self.requests.append((r.method,urlsplit(r.url).path,r.post_data)))
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))

    def test_fresh_context_restores_unknown_from_support_only_other_qid_can_start(self):
        # INV-QSTART-04 INV-QSTART-06 INV-QSTART-07 INV-QSTART-08
        self.backend.start_state='delivery_unknown';self.select()
        self.assertTrue(self.start_button().is_enabled(),'Four-field eligible support DTO must enable an unblocked native row')
        self.dialog().get_by_role('button',name=existing.CONFIRM).click()
        self.until(lambda:len([call for call in self.backend.nav_calls if call[0]=='start'])==1)
        self.assertFalse(self.start_button().is_enabled())
        action=next(call[4] for call in self.backend.nav_calls if call[0]=='start')
        storage=self.page.evaluate('JSON.stringify({local:Object.entries(localStorage),session:Object.entries(sessionStorage),name:window.name,url:location.href})')
        for receipt in [action,'native-selected-row']:self.assertNotIn(receipt,storage,'Action receipt persisted in browser storage/name/URL')
        self.backend.queue_rows[live.SID].append(q.public_row('independent-qid','independent-native-client','Independent native queue text'))
        self.fresh_context();self.select()
        self.assertTrue(any(method=='GET' and path=='/api/session-queue-start' for method,path,_body in self.requests))
        self.assertFalse(self.start_button().is_enabled(),'Fresh browser must use durable support blockers, without old JS receipt')
        self.assertEqual(self.navposts(),[],'Fresh context/reload replayed start')
        self.assertEqual(len([call for call in self.backend.nav_calls if call[0]=='start']),1)
        other=self.page.get_by_text('Independent native queue text',exact=True).locator('xpath=ancestor::*[.//button][1]').get_by_role('button',name=existing.START)
        self.assertEqual(other.count(),1);self.assertTrue(other.is_enabled(),'Unknown receipt must block only its exact qid')
        self.backend.start_state='started';other.click();dialog=self.page.get_by_role('dialog');expect(dialog).to_be_visible()
        self.assertEqual(self.navposts(),[],'Opening another qid confirmation sent request')
        dialog.get_by_role('button',name=existing.CONFIRM).click()
        self.until(lambda:len([call for call in self.backend.nav_calls if call[0]=='start'])==2)
        calls=[call for call in self.backend.nav_calls if call[0]=='start']
        self.assertEqual([call[3] for call in calls],['native-selected-row','independent-qid'])
        expect(self.page.get_by_text('Selected current native queue text',exact=True)).to_have_count(1)

    def test_late_support_blockers_cannot_cross_selected_SID(self):
        # INV-QSTART-04 INV-QSTART-06 INV-QSTART-07
        held=[]
        def hold_A(route):
            if parse_qs(urlsplit(route.request.url).query).get('sid')==[live.SID]:held.append(route)
            else:route.continue_()
        self.backend.queue_rows[live.OTHER]=[q.public_row('native-selected-row','other-client','Other session native queued text')]
        self.page.route('**/api/session-queue-start?*',hold_A);self.select();self.until(lambda:len(held)>=1)
        self.page.get_by_role('button',name='LIVE synthetic B',exact=False).click()
        expect(self.page.get_by_text('Queue browser B history',exact=True)).to_have_count(1)
        row=self.page.get_by_text('Other session native queued text',exact=True)
        expect(row).to_have_count(1);button=row.locator('xpath=ancestor::*[.//button][1]').get_by_role('button',name=existing.START)
        self.assertEqual(button.count(),1);expect(button).to_be_enabled()
        self.page.locator('textarea').fill('Other SID retained draft')
        held[0].fulfill(status=200,json=dict(schema=1,supported=True,reason=None,blocked_queue_ids=['native-selected-row']))
        self.page.wait_for_timeout(100);expect(button).to_be_enabled()
        self.assertEqual(self.page.locator('textarea').input_value(),'Other SID retained draft')
        self.assertEqual(self.navposts(),[])
