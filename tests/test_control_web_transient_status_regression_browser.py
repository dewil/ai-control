"""Focused INV-WSESS-16 regression cases using the public synthetic fixture."""
import re
import time
import unittest

import test_control_web_transient_send_status_browser as fixture


class TransientStatusRegressionBrowserContract(unittest.TestCase):
    # Reuse setup and helpers without inheriting/rerunning the existing suite.
    stop_server = classmethod(fixture.TransientSendStatusBrowserContract.stop_server.__func__)
    setUp = fixture.TransientSendStatusBrowserContract.setUp
    tearDown = fixture.TransientSendStatusBrowserContract.tearDown
    open_history = fixture.TransientSendStatusBrowserContract.open_history
    history_requests = fixture.TransientSendStatusBrowserContract.history_requests
    control = fixture.TransientSendStatusBrowserContract.control
    send = fixture.TransientSendStatusBrowserContract.send
    slot = fixture.TransientSendStatusBrowserContract.slot
    accepted = fixture.TransientSendStatusBrowserContract.accepted
    calls = fixture.TransientSendStatusBrowserContract.calls
    seed = fixture.TransientSendStatusBrowserContract.seed
    disclosure = fixture.TransientSendStatusBrowserContract.disclosure

    @classmethod
    def setUpClass(cls):
        fixture.TransientSendStatusBrowserContract.setUpClass.__func__(cls)

    def test_INV_WSESS_16_history_unknown_seed_only_appears_in_problem_details(self):
        self.control(seeds=[self.seed(901, 'delivery_unknown')])
        self.open_history()
        self.assertEqual(self.slot().inner_text().strip(), '',
                         'History seed cannot invent a current local attempt')
        details = self.disclosure(1)
        self.assertEqual(details.get_by_role('button', name='Проверить доставку', exact=True).count(), 1)

    def test_INV_WSESS_16_switch_back_within_five_seconds_does_not_reannounce(self):
        self.open_history()
        self.slot().evaluate("""el => {
            window.acceptedStatusEvents = 0;
            new MutationObserver(() => {
                if (/принято/i.test(el.textContent)) window.acceptedStatusEvents++;
            }).observe(el, {childList:true, subtree:true, characterData:true});
        }""")
        started = time.monotonic()
        self.send('Synthetic accepted, switch back before expiry')
        self.assertTrue(self.accepted(), 'Local accepted transition is visible')
        first_count = self.page.evaluate('window.acceptedStatusEvents')
        self.assertGreater(first_count, 0, 'First accepted transition must enter the polite slot')

        self.page.get_by_role('button', name=re.compile('Second synthetic session')).click()
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.session.click()
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.page.wait_for_timeout(100)
        self.assertLess(time.monotonic() - started, 5,
                        'Return must occur inside the original five-second lifetime')
        self.assertTrue(self.accepted(), 'The original accepted lifetime has not elapsed')
        self.assertEqual(self.page.evaluate('window.acceptedStatusEvents'), first_count,
                         'Returning cannot announce an already observed accepted transition again')

    def test_INV_WSESS_16_manual_status_failure_remains_visible(self):
        self.control(send_status='delivery_unknown')
        self.open_history()
        self.send('Synthetic attempt whose manual check fails')
        self.assertFalse(self.accepted())
        check = self.page.get_by_role('button', name='Проверить доставку', exact=True)
        self.assertGreater(check.count(), 0, 'Unknown current attempt exposes its manual check')

        # Remove the synthetic receipt so the existing status endpoint returns
        # its deterministic stale error; this stays inside the test fixture.
        fixture.private_json(self.evidence / 'receipts.json', [])
        self.control(seeds=[])
        check.first.click()
        self.page.wait_for_timeout(300)
        self.assertTrue(check.first.is_enabled(), 'Failed check ends its pending state')
        status_calls = [row for row in self.calls() if row['method'] == 'status']
        self.assertEqual(len(status_calls), 1, 'The test exercises one manual status GET')
        self.assertIn('Эта отправка больше недоступна для проверки.', self.slot().inner_text(),
                      'Manual status GET failure must remain visible after rendering settles')
