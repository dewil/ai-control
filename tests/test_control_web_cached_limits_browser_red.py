"""Independent cached-limits browser acceptance from frozen d38acf3 contract.

Runtime JS/Python bodies are not inspected. Actual authenticated HTTP, browser
semantics, pixel fill and geometry exercise synthetic public DTOs only.
"""
import base64
from copy import deepcopy
import re
import unittest

from playwright.sync_api import expect

import cached_limits_ui_blind_support as v2
import limits_dashboard_blind_support as native
import test_control_web_limits_dashboard_browser_red as harness


class CachedLimitsBrowserRED(unittest.TestCase):
    # Module-qualified reuse deliberately avoids inherited/imported TestCases:
    # unittest must discover only these eight acceptance methods in this module.
    setUpClass = classmethod(harness.LimitsBrowserRED.setUpClass.__func__)
    setUp = harness.LimitsBrowserRED.setUp
    tearDown = harness.LimitsBrowserRED.tearDown
    tab = harness.LimitsBrowserRED.tab
    panel = harness.LimitsBrowserRED.panel
    until = harness.LimitsBrowserRED.until
    gets = harness.LimitsBrowserRED.gets
    meters = harness.LimitsBrowserRED.meters
    assert_marker_values = harness.LimitsBrowserRED.assert_marker_values

    def open_value(self, value):
        self.backend.limits_value = deepcopy(value)
        self.page.goto(self.fixture.origin)
        with self.page.expect_response(lambda r: r.url.endswith('/api/limits-overview')) as pending:
            self.tab('Лимиты').click()
        self.assertEqual(pending.value.status, 200,
                         'Actual authenticated limits route must accept the exact public schema, including V2')
        expect(self.panel()).to_be_visible()

    def card(self, provider, node='llm'):
        # HTML contract supplies this container; each public source is a card.
        cards = self.page.locator('#limits-cards > *').filter(
            has_text=re.compile(provider, re.I))
        if node == 'alp':
            cards = cards.filter(has_text=re.compile(r'\bALP\b', re.I))
        else:
            cards = cards.filter(has_not_text=re.compile(r'\bALP\b', re.I))
        expect(cards).to_have_count(1)
        expect(cards).to_be_visible()
        return cards

    def spent(self, card, values):
        bars = card.get_by_role('progressbar')
        expect(bars).to_have_count(len(values))
        for bar, value in zip(bars.all(), values):
            expect(bar).to_be_visible()
            self.assertEqual(float(bar.get_attribute('aria-valuemin')), 0)
            self.assertEqual(float(bar.get_attribute('aria-valuemax')), 100)
            self.assertEqual(float(bar.get_attribute('aria-valuenow')), value,
                             'Accessible progress is spent, never remaining')

    def no_markers(self, card):
        expect(card.get_by_role('meter')).to_have_count(0)

    def pixel_row(self, bar):
        encoded = base64.b64encode(bar.screenshot(scale='css')).decode('ascii')
        return self.page.evaluate('''async encoded => {
          const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
          const bitmap=await createImageBitmap(new Blob([bytes],{type:'image/png'}));
          const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
          const c=canvas.getContext('2d');c.drawImage(bitmap,0,0);
          return Array.from(c.getImageData(0,Math.floor(bitmap.height/4),bitmap.width,1).data);
        }''', encoded)

    def test_v1_native_route_regression_keeps_spend_reset_and_weekly_markers(self):
        # INV-WLIM-20 INV-WLIM-24: old callers and the frontend still accept V1.
        self.open_value(native.overview(remaining=75))
        self.spent(self.card('Codex'), [25])
        self.assert_marker_values(1)
        expect(self.card('Codex').get_by_text(re.compile(r'75\s*%')).first).to_be_visible()
        expect(self.card('Codex').get_by_text(re.compile('Сброс', re.I)).first).to_be_visible()
        self.assertEqual(self.backend.limits_value['sources'][0]['windows'][0]['resets_at'], native.NOW+6*native.DAY)

    def test_v2_keeps_native_and_distinguishes_three_bot_origins_ages_and_missing_alp(self):
        # INV-WLIM-20 INV-WLIM-22 INV-WLIM-24
        self.open_value(v2.overview())
        self.spent(self.card('Codex'), [25])
        self.assert_marker_values(1)
        expect(self.card('Codex').get_by_text(re.compile('native|натив|App Server', re.I)).first).to_be_visible()
        for provider, minutes in (('Kimi', 2), ('OpenRouter', 4), ('Yandex|Яндекс', 7)):
            with self.subTest(provider=provider):
                card = self.card(provider)
                expect(card.get_by_text('Кеш бота · аккаунт не указан', exact=True)).to_be_visible()
                self.assertRegex(card.inner_text(), r'(?i)LLM')
                self.assertRegex(card.inner_text(), rf'(?i)(?<!\d){minutes}\s*(?:мин|м\b)|{minutes*60}\s*(?:сек|с\b)')
                self.assertNotRegex(card.inner_text(), r'\b[0-9a-f]{8,64}\b')
        for provider in ('Claude', 'Codex'):
            card = self.card(provider, 'alp')
            self.assertRegex(card.inner_text(), r'(?i)не подключ|недоступ')
            self.spent(card, [])
        self.assertNotRegex(self.panel().inner_text(), r'(?i)общий баланс|суммарн|итого')
        unavailable = native.overview()
        unavailable['coverage']['partial'] = True
        unavailable['sources'] = [native.unavailable('codex', 'source_unavailable'),
                                  native.unavailable('claude', 'source_unavailable')]
        self.open_value(v2.overview(native_value=unavailable))
        self.spent(self.card('Codex'), [])
        self.assertRegex(self.card('Codex').inner_text(), r'(?i)недоступ|не подключ')
        self.spent(self.card('OpenRouter'), [25])
        self.spent(self.card('Kimi'), [0, 25, 60, 100])

    def test_kimi_four_spent_windows_stay_readable_at_320_and_360_without_codex_markers(self):
        # INV-WLIM-22 INV-WLIM-24: month totals do not invent duration or anchors.
        self.open_value(v2.overview())
        for width in (320, 360):
            with self.subTest(width=width):
                self.page.set_viewport_size(dict(width=width, height=900))
                kimi = self.card('Kimi')
                self.spent(kimi, [0, 25, 60, 100])
                self.no_markers(kimi)
                for remaining in (100, 75, 40, 0):
                    self.assertRegex(kimi.inner_text(), rf'(?<!\d){remaining}\s*%')
                self.assert_marker_values(1)
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width+1)
                for provider in ('Kimi', 'OpenRouter', 'Yandex|Яндекс'):
                    card = self.card(provider)
                    box = card.bounding_box()
                    self.assertGreaterEqual(box['x'], -1)
                    self.assertLessEqual(box['x']+box['width'], width+1)
                    text_boxes = card.evaluate('''e=>{
                      const out=[], walk=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);
                      while(walk.nextNode()){
                        const n=walk.currentNode;if(!n.textContent.trim())continue;
                        const style=getComputedStyle(n.parentElement);
                        if(style.display==='none'||style.visibility==='hidden')continue;
                        const range=document.createRange();range.selectNodeContents(n);
                        for(const r of range.getClientRects())if(r.width&&r.height)
                          out.push({left:r.left,right:r.right,font:parseFloat(style.fontSize)});
                      }return out;
                    }''')
                    self.assertTrue(text_boxes, 'Provider labels and monetary values must render')
                    for text in text_boxes:
                        self.assertGreaterEqual(text['left'], -1)
                        self.assertLessEqual(text['right'], width+1, 'Labels and values must wrap without clipping')
                        self.assertGreaterEqual(text['font'], 10)
                for bar in kimi.get_by_role('progressbar').all():
                    self.assertGreater(bar.bounding_box()['width'], 100)
                native_card = self.card('Codex')
                track = native_card.get_by_role('progressbar').bounding_box()
                for label, day in ((harness.NORMAL, 1), (harness.DOUBLE, 2)):
                    mark = native_card.get_by_role('meter', name=label, exact=True).bounding_box()
                    self.assertAlmostEqual(mark['x']+mark['width']/2,
                                           track['x']+track['width']*day/7, delta=4)
                    self.assertGreaterEqual(mark['y']+mark['height']/2, track['y']-2)
                    self.assertLessEqual(mark['y']+mark['height']/2, track['y']+track['height']+2)
        unknown = v2.kimi()
        unknown['windows'][0].update(remaining_percent=None, resets_at=v2.NOW-1)
        unknown['windows'][1].update(remaining_percent=None, resets_at=None,
                                     window_started_at=None, anchor=None)
        self.open_value(v2.overview([unknown]))
        self.spent(self.card('Kimi'), [60, 100])
        self.assertRegex(self.card('Kimi').inner_text(), r'(?i)неизвестно')
        self.no_markers(self.card('Kimi'))

    def test_prepaid_currency_history_estimate_debt_unknown_scale_and_actual_fill(self):
        # INV-WLIM-22 INV-WLIM-24: monetary scales are independent of wall time.
        rows = {}
        for balance, spent in ((100, 0), (75, 25), (0, 100)):
            self.open_value(v2.overview([v2.prepaid(balance=balance), v2.prepaid('yandex', balance=375, scale=500)]))
            usd, rub = self.card('OpenRouter'), self.card('Yandex|Яндекс')
            self.spent(usd, [spent]); self.spent(rub, [25])
            self.assertRegex(rub.inner_text(), r'(?<!\d)375(?:[.,]00)?\s*(?:RUB|₽|руб)|(?:RUB|₽|руб)\s*375(?!\d)')
            for card, currency in ((usd, r'USD|\$'), (rub, r'RUB|₽|руб')):
                self.assertRegex(card.inner_text(), currency)
                self.assertRegex(card.inner_text(), r'1[.,]25')
                self.assertRegex(card.inner_text(), r'8[.,]5(?:0)?')
                self.assertRegex(card.inner_text(), r'(?i)день|сутк')
                self.assertRegex(card.inner_text(), r'(?i)недел')
                self.assertRegex(card.inner_text(), r'(?i)оценка')
                self.assertRegex(card.inner_text(), r'4[.,]5(?:0)?')
                self.no_markers(card)
            self.assertRegex(usd.inner_text(), rf'(?<!\d){balance}(?:[.,]00)?\s*(?:USD|\$)|(?:USD|\$)\s*{balance}(?!\d)')
            rows[spent] = self.pixel_row(usd.get_by_role('progressbar'))
        def changed(reference, current):
            return [x for x in range(4, len(reference)//4-4)
                    if sum(abs(reference[x*4+c]-current[x*4+c]) for c in range(3)) > 45]
        self.assertEqual(len(rows[0]), len(rows[100]))
        full, quarter = changed(rows[0], rows[100]), changed(rows[0], rows[25])
        self.assertGreater(len(full), len(rows[0])//4*.6, 'Actual fill must change beyond the number label')
        self.assertAlmostEqual(len(quarter)/len(full), .25, delta=.08)
        self.assertLess(sum(quarter)/len(quarter), len(rows[0])//4*.4, 'Spent fill begins at the left')
        debt = v2.prepaid('yandex', balance=-12.5, scale=500)
        unknown = v2.prepaid(balance=75, scale=None)
        unknown['prepaid'].update(spend_day=None, spend_week=None, burn_per_day=None, forecast_days=None)
        self.open_value(v2.overview([debt, unknown]))
        self.spent(self.card('Yandex|Яндекс'), [100])
        self.assertRegex(self.card('Yandex|Яндекс').inner_text(), r'(?i)отрицательный баланс')
        self.assertRegex(self.card('Yandex|Яндекс').inner_text(), r'[-−]12[.,]5')
        self.spent(self.card('OpenRouter'), [])
        self.assertRegex(self.card('OpenRouter').inner_text(), r'(?i)недостаточно истории')
        self.assertNotRegex(self.card('OpenRouter').inner_text(), r'(?i)(?:день|недел)[^\n]*\b0(?:[.,]00)?\b')

    def test_error_nodata_and_stale_sources_keep_last_known_separate_from_current(self):
        # INV-WLIM-20 INV-WLIM-22 INV-WLIM-24: one error cannot erase other sources.
        for state in ('error', 'nodata', 'stale'):
            with self.subTest(state=state):
                rub = v2.prepaid('yandex', balance=375, age=2701 if state == 'stale' else 420)
                rub.update(status='stale' if state == 'stale' else 'unavailable',
                           reason=None if state == 'stale' else 'source_error')
                if state != 'stale':
                    rub['prepaid'] = None
                    rub['last_known'] = dict(currency='RUB', balance=12.34, observed_at=v2.NOW-v2.DAY)
                self.open_value(v2.overview([v2.kimi(), v2.prepaid(), rub]))
                card = self.card('Yandex|Яндекс')
                self.spent(self.card('Codex'), [25]); self.spent(self.card('OpenRouter'), [25])
                self.spent(self.card('Kimi'), [0, 25, 60, 100])
                if state == 'stale':
                    self.assertRegex(card.inner_text(), r'(?i)устарел|stale')
                else:
                    self.spent(card, [])
                    self.assertRegex(card.inner_text(), r'(?i)недоступ|ошиб|нет данных')
                    self.assertRegex(card.inner_text(), r'(?i)последн|ранее|известн')
                    self.assertRegex(card.inner_text(), r'12[.,]34')
                    self.assertNotRegex(card.inner_text(), r'(?im)^\s*(?:текущий\s+)?баланс\s*[:·]?\s*12[.,]34')
                    self.assertNotRegex(card.inner_text(), r'(?<!\d)0\s*%')

    def test_alp_mapped_accounts_have_tick_provenance_and_codex_only_weekly_markers(self):
        # INV-WLIM-20 INV-WLIM-24: synthetic export proves rendering, not live acceptance.
        self.open_value(v2.overview([v2.alp('claude'), v2.alp('codex')]))
        for provider in ('Claude', 'Codex'):
            card = self.card(provider, 'alp')
            self.spent(card, [40])
            self.assertRegex(card.inner_text(), r'Экспорт ALP')
            self.assertRegex(card.inner_text(), r'(?i)время начала сбора')
            self.assertRegex(card.inner_text(), r'b{8,64}')
            self.assertNotRegex(card.inner_text(), r'(?i)native.reported|подтвержд[её]н.*native')
        self.no_markers(self.card('Claude', 'alp'))
        alp = self.card('Codex', 'alp')
        for label, expected in ((harness.NORMAL, 1), (harness.DOUBLE, 2)):
            meter = alp.get_by_role('meter', name=label, exact=True)
            expect(meter).to_be_visible()
            self.assertAlmostEqual(float(meter.get_attribute('aria-valuenow')), expected, delta=.002)
        self.spent(self.card('Codex'), [25])

    def test_v2_foreground_age_uses_server_clock_and_stales_while_refresh_is_pending(self):
        # INV-WLIM-22 INV-WLIM-24: provider age does not reset to HTTP receipt time.
        self.page.clock.install(time=v2.NOW*1000+10*365*v2.DAY*1000)
        self.open_value(v2.overview([v2.prepaid(age=2640)]))
        card = self.card('OpenRouter')
        self.assertNotRegex(card.inner_text(), r'(?i)устарел|stale')
        self.assertRegex(card.inner_text(), r'44\s*(?:мин|м\b)|2640\s*(?:сек|с\b)')
        held = []
        self.page.route('**/api/limits-overview', lambda route: held.append(route))
        self.page.clock.fast_forward(61000)
        self.until(lambda: len(held) == 1)
        self.assertRegex(card.inner_text(), r'(?i)устарел|stale')
        self.spent(card, [25])
        self.page.clock.fast_forward(120000)
        self.assertEqual(len(held), 1, 'Refresh is single flight')

    def test_v2_hidden_android_stop_and_failed_reload_preserve_chat_draft(self):
        # INV-WLIM-20 INV-WLIM-24: existing lifecycle and chat survive schema2.
        self.page.clock.install()
        self.open_value(v2.overview())
        self.spent(self.card('OpenRouter'), [25])
        self.page.locator('#chat-draft').evaluate("e=>{e.value='synthetic draft survives cached-source error';e.dispatchEvent(new Event('input',{bubbles:true}))}")
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
        before = len(self.gets())
        self.page.clock.fast_forward(300000); self.page.wait_for_timeout(50)
        self.assertEqual(len(self.gets()), before, 'Hidden browser must stop limits polling')
        self.backend.limits_failure = RuntimeError('synthetic cache read unavailable')
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('pageshow'))")
        self.until(lambda: len(self.gets()) == before+1)
        self.page.wait_for_timeout(80)
        expect(self.page.locator('#chat-draft')).to_have_value('synthetic draft survives cached-source error')
        self.page.evaluate('aiControlAndroidSuspend({protocol:2,serial:1})')
        before = len(self.gets())
        self.page.clock.fast_forward(600000); self.page.wait_for_timeout(50)
        self.assertEqual(len(self.gets()), before, 'Android background must stop limits polling')
        self.backend.limits_failure = None
        self.page.evaluate('aiControlAndroidResume({protocol:2,serial:2,phase:"admit"})')
        self.page.evaluate('aiControlAndroidResume({protocol:2,serial:3,phase:"activate",admissionSerial:2})')
        self.until(lambda: len(self.gets()) == before+1)
        self.spent(self.card('OpenRouter'), [25])
        expect(self.page.locator('#chat-draft')).to_have_value('synthetic draft survives cached-source error')


if __name__ == '__main__':
    unittest.main()
