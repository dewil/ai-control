"""USN migration: global summary recovery is independent of navigator filter.

Old filter->chat selectionGeneration coupling is superseded by INV-USN01/07.
Keep bounded retry, current filter/chat/draft and readonly response fences.
"""
import unittest
import test_control_web_read_recovery_browser as fixture


class SummarySelectionRecovery(unittest.TestCase):
    setUpClass=classmethod(fixture.ReadRecoveryBrowserContract.setUpClass.__func__)
    stop_server=classmethod(fixture.ReadRecoveryBrowserContract.stop_server.__func__)
    setUp=fixture.ReadRecoveryBrowserContract.setUp
    tearDown=fixture.ReadRecoveryBrowserContract.tearDown
    control=fixture.ReadRecoveryBrowserContract.control
    tile=fixture.ReadRecoveryBrowserContract.tile
    project_filter=fixture.ReadRecoveryBrowserContract.project_filter
    select_project=fixture.ReadRecoveryBrowserContract.select_project
    selected_filter=fixture.ReadRecoveryBrowserContract.selected_filter
    open_session=fixture.ReadRecoveryBrowserContract.open_session
    verify_assets=fixture.ReadRecoveryBrowserContract.verify_assets
    login=fixture.ReadRecoveryBrowserContract.login

    def select(self,name):
        self.select_project(name)
        self.page.wait_for_timeout(100)
        self.assertEqual(self.selected_filter(),name)

    def test_filter_change_during_first_unknown_summary_allows_bounded_global_retry(self):
        self.select('high')
        before_url=self.page.url
        held=[]
        def handler(route):
            held.append(route)
            if len(held)>1: route.fulfill(status=200,json=fixture.summaries())
        self.page.route('**/api/session-project-summary*',handler)
        refresh=self.page.get_by_role('button',name='Обновить проекты',exact=True)
        refresh.click(); self.page.wait_for_timeout(100)
        self.assertEqual(len(held),1)
        self.select('loww')
        held[0].fulfill(status=200,json=fixture.summaries('unknown'))
        self.page.wait_for_timeout(350)
        self.assertEqual(len(held),2,'A filter change is not a chat/auth reset; global summary may recover once')
        self.assertEqual(self.selected_filter(),'loww')
        self.assertEqual(self.page.url,before_url,'Metadata/filter must not select chat or change URL')
        self.assertFalse(any('/api/session-history' in url for method,url in self.network))
        self.assertFalse(any(method=='POST' for method,url in self.network))
        self.assertTrue(refresh.is_enabled())

    def test_filter_change_during_second_summary_preserves_existing_chat_draft_and_releases_loading(self):
        self.select('high'); self.open_session()
        self.page.get_by_text('CLOUD SYNTHETIC HISTORY',exact=True).wait_for()
        composer=self.page.locator('textarea'); composer.fill('Summary-independent chat draft')
        before_url=self.page.url
        calls=[]; held=[]
        def handler(route):
            calls.append(route.request.url)
            if len(calls)==1: route.fulfill(status=200,json=fixture.summaries('unknown'))
            else: held.append(route)
        self.page.route('**/api/session-project-summary*',handler)
        refresh=self.page.get_by_role('button',name='Обновить проекты',exact=True)
        refresh.click(); self.page.wait_for_timeout(200)
        self.assertEqual(len(calls),2); self.assertEqual(len(held),1)
        self.select('loww')
        network_at_response=len(self.network)
        held[0].fulfill(status=200,json=fixture.summaries(high=88888,low=77777))
        self.page.wait_for_timeout(350)
        self.assertEqual(len(calls),2,'Global recovery remains bounded')
        self.assertEqual(self.selected_filter(),'loww')
        self.assertEqual(self.page.url,before_url)
        self.assertEqual(composer.input_value(),'Summary-independent chat draft')
        self.page.get_by_text('CLOUD SYNTHETIC HISTORY',exact=True).wait_for()
        self.assertFalse(any('/api/session-history' in url for method,url in self.network[network_at_response:]))
        self.assertFalse(any(method=='POST' for method,url in self.network))
        self.assertTrue(refresh.is_enabled(),'Recovery must release its owned loading state')


if __name__=='__main__':
    unittest.main(verbosity=2)
