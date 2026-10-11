"""Independent INV-WLIM-17/18 acceptance from the spend-overlay specification.

Only public DTO fixtures, browser semantics and rendered geometry are inspected.
"""
import base64
import re
import unittest

from playwright.sync_api import expect, sync_playwright

import limits_dashboard_blind_support as s
import live_sse_blind_support as live


NORMAL = 'Обычный ×1'
DOUBLE = 'Ориентир ×2'


class LimitsSpendOverlayBrowserRED(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)
        if cls.browser.version != '153.0.8010.12':
            raise RuntimeError('Chromium153 fixture drift; no skip')

    def setUp(self):
        original = live.Backend
        live.Backend = s.LimitsBackend
        try:
            self.fixture = live.Fixture(session_store=True)
        finally:
            live.Backend = original
        self.addCleanup(self.fixture.stop)
        self.fixture.login()
        self.backend = self.fixture.backend
        self.context = self.browser.new_context(viewport={'width': 360, 'height': 900})
        self.addCleanup(self.context.close)
        name, value = self.fixture.cookie.split('=', 1)
        self.context.add_cookies([dict(name=name, value=value, url=self.fixture.origin)])
        self.page = self.context.new_page()
        self.page.set_default_timeout(2500)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def open(self):
        self.page.goto(self.fixture.origin)
        tab = self.page.get_by_role('tab', name='Лимиты', exact=True).or_(
            self.page.get_by_role('button', name='Лимиты', exact=True))
        expect(tab).to_be_visible()
        tab.click()
        self.panel = self.page.get_by_role('tabpanel', name='Лимиты', exact=True)
        expect(self.panel.get_by_text(re.compile('Codex', re.I)).first).to_be_visible()

    def pixel_row(self, bar):
        encoded = base64.b64encode(bar.screenshot(scale='css')).decode('ascii')
        return self.page.evaluate('''async encoded => {
          const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
          const bitmap = await createImageBitmap(new Blob([bytes], {type: 'image/png'}));
          const canvas = document.createElement('canvas');
          canvas.width = bitmap.width; canvas.height = bitmap.height;
          const context = canvas.getContext('2d'); context.drawImage(bitmap, 0, 0);
          return Array.from(context.getImageData(0, Math.floor(bitmap.height / 4), bitmap.width, 1).data);
        }''', encoded)

    def test_spend_zero_quarter_full_is_labelled_and_fills_actual_short_window_track(self):
        # INV-WLIM-17 INV-WLIM-18: nonweekly windows have spend, without markers.
        rows = {}
        for remaining, spent in ((100, 0), (75, 25), (0, 100)):
            self.backend.limits_value = s.overview(elapsed=0, remaining=remaining, duration=300)
            self.open()
            bar = self.panel.get_by_role('progressbar')
            expect(bar).to_be_visible()
            rows[spent] = self.pixel_row(bar)
            with self.subTest(remaining=remaining, spent=spent):
                self.assertEqual(float(bar.get_attribute('aria-valuemin')), 0)
                self.assertEqual(float(bar.get_attribute('aria-valuemax')), 100)
                self.assertEqual(float(bar.get_attribute('aria-valuenow')), spent,
                                 'Progressbar must expose spent=100-remaining, independently of elapsed time')
                expect(self.panel.get_by_text(re.compile('Израсходовано', re.I)).first).to_be_visible()
                expect(self.panel.get_by_text(re.compile(rf'(?<!\d){spent}\s*%')).first).to_be_visible()
                expect(self.panel.get_by_text(re.compile(rf'(?<!\d){remaining}\s*%')).first).to_be_visible()
                expect(self.panel.get_by_role('meter', name=NORMAL, exact=True)).to_have_count(0)
                expect(self.panel.get_by_role('meter', name=DOUBLE, exact=True)).to_have_count(0)
                if remaining == 0:
                    expect(self.panel.get_by_text(re.compile('Исчерпан', re.I)).first).to_be_visible()
            self.assertEqual(self.backend.limits_value['sources'][0]['windows'][0]['remaining_percent'], remaining)
        self.assertEqual(len(rows[0]), len(rows[25]))
        self.assertEqual(len(rows[0]), len(rows[100]))

        def changed(reference, current):
            return [x for x in range(4, len(reference) // 4 - 4)
                    if sum(abs(reference[4*x+c] - current[4*x+c]) for c in range(3)) > 45]

        full = changed(rows[0], rows[100])
        quarter = changed(rows[0], rows[25])
        self.assertGreater(len(full), len(rows[0]) // 4 * .6,
                           'Spent 0/100 must change the rendered fill, beyond its label')
        self.assertAlmostEqual(len(quarter) / len(full), .25, delta=.08,
                               msg='Remaining75 must visibly fill one quarter of the spent track')
        self.assertGreater(len(quarter), 0)
        self.assertLess(sum(quarter) / len(quarter), len(rows[0]) // 4 * .4,
                        'Spent25 must fill from the left, not erase the right quarter of a remaining bar')

    def test_unknown_and_expired_have_no_fabricated_spend(self):
        # INV-WLIM-17: expired known numeric input is also unknown.
        for state in ('unknown', 'expired'):
            with self.subTest(state=state):
                self.backend.limits_value = s.overview(remaining=None)
                if state == 'expired':
                    self.page.clock.install()
                    self.backend.limits_value = s.overview(elapsed=0, remaining=75, duration=300)
                    self.backend.limits_value['sources'][0]['windows'][0].update(
                        resets_at=s.NOW + 30, window_started_at=s.NOW + 30 - 300*60)
                self.open()
                if state == 'expired':
                    expect(self.panel.get_by_role('progressbar')).to_be_visible()
                    held = []
                    self.page.route('**/api/limits-overview', lambda route: held.append(route))
                    self.page.clock.fast_forward(61000)
                expect(self.panel.get_by_text('Неизвестно', exact=True).first).to_be_visible()
                expect(self.panel.get_by_role('progressbar')).to_have_count(0)
                self.assertNotRegex(self.panel.inner_text(), r'(?<!\d)(?:0|25|100)\s*%')
                if state == 'expired':
                    expect(self.panel.get_by_text('Окно истекло, ожидаем новые данные', exact=True)).to_be_visible()
                    for route in held:
                        route.abort()
                    self.page.unroute('**/api/limits-overview')

    def test_weekly_time_markers_overlay_spend_track_at_mobile_widths(self):
        # INV-WLIM-17 INV-WLIM-18: compare markers to the spend bar itself,
        # not to a separate timeline or a permissive common card ancestor.
        for width in (320, 360):
            for elapsed_days in (0, 1, 3.5):
                with self.subTest(width=width, elapsed_days=elapsed_days):
                    self.page.set_viewport_size(dict(width=width, height=900))
                    self.backend.limits_value = s.overview(elapsed=elapsed_days*s.DAY, remaining=75)
                    self.open()
                    bar = self.panel.get_by_role('progressbar')
                    expect(bar).to_be_visible()
                    track = bar.bounding_box()
                    self.assertGreater(track['width'], 100)
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    self.assertGreaterEqual(track['x'], -1)
                    self.assertLessEqual(track['x'] + track['width'], width + 1)
                    expect(self.panel.get_by_text(re.compile(r'7\s*(?:дней|дн\b)')).first).to_be_visible()
                    for label, value in ((NORMAL, min(7, elapsed_days)), (DOUBLE, min(7, 2*elapsed_days))):
                        marker = self.panel.get_by_role('meter', name=label, exact=True)
                        expect(marker).to_be_visible()
                        expect(self.panel.get_by_text(label, exact=True).first).to_be_visible()
                        self.assertEqual(float(marker.get_attribute('aria-valuemin')), 0)
                        self.assertEqual(float(marker.get_attribute('aria-valuemax')), 7)
                        self.assertAlmostEqual(float(marker.get_attribute('aria-valuenow')), value, delta=.002)
                        box = marker.bounding_box()
                        center_x = box['x'] + box['width']/2
                        center_y = box['y'] + box['height']/2
                        self.assertAlmostEqual(center_x, track['x'] + track['width']*value/7, delta=4,
                                               msg='Time marker must use the same horizontal scale as spend')
                        self.assertGreaterEqual(center_y, track['y'] - 2,
                                                'Time marker must overlap the spend track vertically')
                        self.assertLessEqual(center_y, track['y'] + track['height'] + 2,
                                             'Time marker must overlap the spend track vertically')
                        self.assertGreaterEqual(center_x, -1)
                        self.assertLessEqual(center_x, width + 1)
                    self.assertEqual(float(bar.get_attribute('aria-valuenow')), 25,
                                     'Fixed remaining75 must stay spent25 while the time markers move')

    def test_weekly_without_anchor_keeps_spend_without_invented_time_markers(self):
        # INV-WLIM-17 INV-WLIM-18
        self.backend.limits_value = s.overview(remaining=75, anchor=False)
        self.backend.limits_value['sources'][0]['windows'][0]['resets_at'] = None
        self.open()
        bar = self.panel.get_by_role('progressbar')
        expect(bar).to_be_visible()
        self.assertEqual(float(bar.get_attribute('aria-valuenow')), 25)
        expect(self.panel.get_by_role('meter', name=NORMAL, exact=True)).to_have_count(0)
        expect(self.panel.get_by_role('meter', name=DOUBLE, exact=True)).to_have_count(0)


if __name__ == '__main__':
    unittest.main()
