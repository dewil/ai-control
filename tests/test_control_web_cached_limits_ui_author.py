"""Author browser coverage for the prepaid balance/base explanation.

Synthetic route fulfillment isolates the renderer from the separate cached
backend implementation. Frozen browser acceptance covers the actual API route.
"""
import json
import unittest

from playwright.sync_api import expect

import cached_limits_ui_blind_support as dto
import test_control_web_limits_dashboard_browser_red as harness


class CachedLimitsPrepaidUIAuthor(unittest.TestCase):
    setUpClass = classmethod(harness.LimitsBrowserRED.setUpClass.__func__)
    setUp = harness.LimitsBrowserRED.setUp
    tearDown = harness.LimitsBrowserRED.tearDown
    tab = harness.LimitsBrowserRED.tab
    open = harness.LimitsBrowserRED.open

    def test_balance_above_base_is_explained_without_changing_balance_spend_or_forecast(self):
        # INV-WLIM-24: clamp is a display scale; a larger balance remains money.
        self.page.route('**/api/limits-overview', lambda route: route.fulfill(
            content_type='application/json', body=json.dumps(self.value)))
        for balance, scale, spent, money in (
                (125, 100, 0, '125 USD'), (100, 100, 0, '100 USD'),
                (0, 100, 100, '0 USD'), (-12.5, 100, 100, '-12,5 USD'),
                (125, None, None, '125 USD')):
            with self.subTest(balance=balance, scale=scale):
                self.value = dto.overview([dto.prepaid(balance=balance, scale=scale)])
                self.open()
                card = self.page.locator('#limits-cards > *').filter(has_text='OpenRouter')
                expect(card).to_have_count(1)
                expect(card.get_by_text(money, exact=True)).to_be_visible()
                expect(card.get_by_text('Баланс выше базы расхода', exact=True)).to_have_count(
                    int(scale is not None and balance > scale))
                expect(card.get_by_text('Отрицательный баланс', exact=True)).to_have_count(
                    int(balance < 0))
                bars = card.get_by_role('progressbar')
                expect(bars).to_have_count(0 if spent is None else 1)
                if spent is not None:
                    expect(bars).to_have_attribute('aria-valuenow', str(spent))
                expect(card.get_by_role('meter')).to_have_count(0)
                expect(card.get_by_text('Оценка: хватит на 4,5 дн', exact=True)).to_be_visible()
