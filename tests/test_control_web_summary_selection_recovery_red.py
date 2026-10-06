"""Blind37f76a3 summary recovery must fence current project selection.

Actual synthetic browser routes/DOM; existing frozen helper namespace only.
No implementation reads, auth mutation, native provider or external network.
"""
import unittest
import test_control_web_read_recovery_browser as fixture


class SummarySelectionRecovery(unittest.TestCase):
    setUpClass = classmethod(fixture.ReadRecoveryBrowserContract.setUpClass.__func__)
    stop_server = classmethod(fixture.ReadRecoveryBrowserContract.stop_server.__func__)
    setUp = fixture.ReadRecoveryBrowserContract.setUp
    tearDown = fixture.ReadRecoveryBrowserContract.tearDown
    control = fixture.ReadRecoveryBrowserContract.control
    tile = fixture.ReadRecoveryBrowserContract.tile
    login = fixture.ReadRecoveryBrowserContract.login

    def select(self, name):
        self.tile(name).click()
        self.page.wait_for_timeout(100)
        self.assertEqual(self.tile(name).get_attribute('aria-pressed'), 'true')

    def test_selection_change_during_first_unknown_summary_prevents_retry_and_old_apply(self):
        self.select('high')
        before_high = self.tile('high').inner_text()
        before_low = self.tile('loww').inner_text()
        held = []
        def handler(route):
            held.append(route)
            if len(held) > 1:
                # Finish an illegal extra request so failing assertions do not
                # leave Playwright's deferred route callback pending at teardown.
                route.fulfill(status=200, json=fixture.summaries())
        self.page.route('**/api/session-project-summary*', handler)
        self.page.get_by_role('button', name='Обновить проекты', exact=True).click()
        self.page.wait_for_timeout(100)
        self.assertEqual(len(held), 1, 'first actual summary GET must reach deferred fixture')
        self.select('loww')
        held[0].fulfill(status=200, json=fixture.summaries('unknown'))
        self.page.wait_for_timeout(300)
        self.assertEqual(len(held), 1, 'changed selection forbids dispatching old summary recovery GET')
        self.assertEqual(self.tile('high').inner_text(), before_high)
        self.assertEqual(self.tile('loww').inner_text(), before_low)
        self.assertEqual(self.tile('loww').get_attribute('aria-pressed'), 'true')
        self.assertTrue(self.page.get_by_role('button', name='Обновить проекты', exact=True).is_enabled())

    def test_selection_change_during_second_summary_discards_old_counts_and_releases_loading(self):
        self.select('high')
        calls = []
        held = []
        def handler(route):
            calls.append(route.request.url)
            if len(calls) == 1:
                route.fulfill(status=200, json=fixture.summaries('unknown'))
            else:
                held.append(route)
        self.page.route('**/api/session-project-summary*', handler)
        refresh = self.page.get_by_role('button', name='Обновить проекты', exact=True)
        refresh.click()
        self.page.wait_for_timeout(200)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(held), 1, 'second actual summary GET must reach deferred fixture')
        before_high = self.tile('high').inner_text()
        before_low = self.tile('loww').inner_text()
        self.select('loww')
        held[0].fulfill(status=200, json=fixture.summaries(high=88888, low=77777))
        self.page.wait_for_timeout(300)
        self.assertEqual(len(calls), 2, 'invalidated old invocation may not add another retry')
        self.assertEqual(self.tile('high').inner_text(), before_high, 'old retry counts must not apply')
        self.assertEqual(self.tile('loww').inner_text(), before_low, 'old retry must not reflow current project counts')
        self.assertNotIn('88888', self.page.locator('body').inner_text())
        self.assertNotIn('77777', self.page.locator('body').inner_text())
        self.assertEqual(self.tile('loww').get_attribute('aria-pressed'), 'true')
        self.assertTrue(refresh.is_enabled(), 'invalidated recovery must release its owned loading state')


if __name__ == '__main__':
    unittest.main(verbosity=2)
