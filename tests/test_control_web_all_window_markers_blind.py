"""Blind INV-WLIM-28/29 acceptance using only public synthetic browser fixtures."""
from copy import deepcopy
import re
import unittest

from playwright.sync_api import expect

import cached_limits_ui_blind_support as v2
import limits_dashboard_blind_support as native
import test_control_web_limits_dashboard_browser_red as harness


NORMAL = 'Обычный ×1'
DOUBLE = 'Ориентир ×2'
TRIPLE = 'Ориентир ×3'


class AllWindowMarkersBlind(unittest.TestCase):
    setUpClass = classmethod(harness.LimitsBrowserRED.setUpClass.__func__)
    setUp = harness.LimitsBrowserRED.setUp
    tearDown = harness.LimitsBrowserRED.tearDown
    tab = harness.LimitsBrowserRED.tab
    panel = harness.LimitsBrowserRED.panel

    def open_value(self, value):
        self.backend.limits_value = deepcopy(value)
        self.page.goto(self.fixture.origin)
        with self.page.expect_response(lambda r: r.url.endswith('/api/limits-overview')) as pending:
            self.tab('Лимиты').click()
        self.assertEqual(pending.value.status, 200, 'Public synthetic DTO must pass the frozen validator')
        expect(self.panel()).to_be_visible()

    def card(self, provider, node='llm'):
        cards = self.panel().get_by_role('article').filter(has_text=provider)
        cards = cards.filter(has_text='ALP') if node == 'alp' else cards.filter(has_not_text='ALP')
        expect(cards).to_have_count(1)
        return cards

    def assert_marker(self, marker, percent):
        expect(marker).to_be_visible()
        self.assertEqual(float(marker.get_attribute('aria-valuemin')), 0)
        maximum = float(marker.get_attribute('aria-valuemax'))
        self.assertGreater(maximum, 0)
        actual = float(marker.get_attribute('aria-valuenow')) / maximum * 100
        self.assertAlmostEqual(actual, percent, delta=.2)
        description = ' '.join(filter(None, (marker.get_attribute('aria-label'),
                                              marker.get_attribute('aria-valuetext'),
                                              marker.get_attribute('title')))).lower()
        self.assertTrue(any(x in description for x in ('прош', 'elapsed', 'мин', 'час', 'дн', 'minute', 'hour', 'day')),
                        'Accessible marker description must state elapsed time/window duration')

    def assert_marker_on_spend_track(self, marker):
        geometry = marker.evaluate('''marker => {
          const row = marker.closest('.lm-window');
          const bar = row && row.querySelector('[role="progressbar"]');
          if (!row || !bar) return null;
          const m = marker.getBoundingClientRect(), b = bar.getBoundingClientRect();
          return {marker: m.left + m.width/2, left: b.left, width: b.width,
                  value: Number(marker.getAttribute('aria-valuenow')),
                  maximum: Number(marker.getAttribute('aria-valuemax'))};
        }''')
        self.assertIsNotNone(geometry, 'Elapsed marker and spent bar must share a quota-window track')
        expected = geometry['left'] + geometry['width'] * geometry['value'] / geometry['maximum']
        self.assertAlmostEqual(geometry['marker'], expected, delta=3,
                               msg='Marker pixel position must match its normalized elapsed fraction')

    def synthetic_response(self, value):
        # Use only for schema-shaped negative/expired fixtures the backend
        # rejects before the display boundary; ordinary cases use open_value.
        self.page.route('**/api/limits-overview',
                        lambda route, request: route.fulfill(status=200, json=value))
        self.page.goto(self.fixture.origin)
        self.tab('Лимиты').click()
        expect(self.panel()).to_be_visible()

    def test_native_codex_weekly_elapsed_markers_share_spend_scale_and_acceleration_only_weekly(self):
        value = native.overview(elapsed=3.5 * native.DAY, remaining=75)
        self.open_value(value)
        card = self.card('Codex')
        bar = card.get_by_role('progressbar')
        expect(bar).to_have_count(1)
        self.assertEqual(float(bar.get_attribute('aria-valuenow')), 25)
        meters = card.get_by_role('meter')
        # INV-WATT-11 supersedes the previous two-marker Codex weekly contract.
        expect(meters).to_have_count(3)
        self.assert_marker(meters.nth(0), 50)
        self.assert_marker(meters.nth(1), 100)
        self.assert_marker(meters.nth(2), 100)
        scale = card.locator('.lm-scale')
        expect(scale).to_have_count(1)
        track = bar.bounding_box()
        endpoints = scale.evaluate('''scale => {
          const leaves = [...scale.querySelectorAll('*')].filter(e => !e.children.length);
          const label = (pattern) => {
            const el = leaves.find(e => pattern.test((e.textContent || '').trim()));
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {center: r.left + r.width/2};
          };
          return {start: label(/^0$/), end: label(/^7\\s*(?:дней|дн)$/i)};
        }''')
        self.assertIn('start', endpoints, 'Weekly scale must label its zero endpoint')
        self.assertIn('end', endpoints, 'Weekly scale must label its seven-day endpoint')
        self.assertIsNotNone(endpoints['start'], 'Zero endpoint must be an individual scale label')
        self.assertIsNotNone(endpoints['end'], 'Seven-day endpoint must be an individual scale label')
        self.assertAlmostEqual(endpoints['start']['center'], track['x'], delta=3)
        self.assertAlmostEqual(endpoints['end']['center'], track['x'] + track['width'], delta=3)
        expect(card.get_by_text(NORMAL, exact=True)).to_be_visible()
        expect(card.get_by_text(DOUBLE, exact=True)).to_be_visible()
        expect(card.get_by_text(TRIPLE, exact=True)).to_be_visible()

    def test_kimi_short_and_weekly_windows_receive_normal_markers_and_spend_is_independent(self):
        self.open_value(v2.overview())
        card = self.card('Kimi')
        bars = card.get_by_role('progressbar')
        expect(bars).to_have_count(4)
        meters = card.get_by_role('meter')
        expect(meters).to_have_count(2)
        self.assert_marker(meters.nth(0), 20)
        self.assert_marker(meters.nth(1), 100 / 7)
        self.assertEqual([float(bar.get_attribute('aria-valuenow')) for bar in bars.all()], [0, 25, 60, 100])
        for marker in meters.all():
            self.assert_marker_on_spend_track(marker)
        for width in (320, 360):
            self.page.set_viewport_size(dict(width=width, height=900))
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
            for marker in meters.all():
                box = marker.bounding_box()
                self.assertGreaterEqual(box['x'], -1)
                self.assertLessEqual(box['x'] + box['width'], width + 1)

    def test_claude_native_and_alp_short_weekly_windows_are_covered(self):
        native_value = native.overview()
        started = native.NOW - 120 * 60
        native_value['sources'][1] = dict(
            node_id='llm', provider='claude', account_id=native.identity('synthetic-claude'),
            identity='native_reported', status='ok', captured_at=native.NOW, age_seconds=0,
            plan='Pro', windows=[dict(id='five_hour:primary', bucket='five_hour',
                duration_minutes=300, remaining_percent=75, resets_at=started+300*60,
                window_started_at=started, anchor='derived_reset_and_duration')], error=None)
        alp_claude = v2.alp('claude')
        alp_claude['windows'].append(v2.window('claude', 'five_hour', 60, 300))
        self.open_value(v2.overview([alp_claude], native_value=native_value))
        # Both native and ALP fixture origins must retain their separate rows.
        local = self.card('Claude')
        expect(local.get_by_role('progressbar')).to_have_count(1)
        expect(local.get_by_role('meter')).to_have_count(1)
        self.assert_marker(local.get_by_role('meter').first, 40)
        remote = self.card('Claude', node='alp')
        expect(remote.get_by_role('meter')).to_have_count(2)
        bars = remote.get_by_role('progressbar')
        expect(bars).to_have_count(2)
        self.assertEqual(float(bars.nth(0).get_attribute('aria-valuenow')), 40)
        self.assertEqual(float(bars.nth(1).get_attribute('aria-valuenow')), 40)

    def test_native_codex_nonweekly_has_one_normal_marker_and_unknown_spend_keeps_time(self):
        # Use the exact public V1 fixture with a valid short-window duration.
        self.open_value(native.overview(elapsed=120 * 60, remaining=75, duration=300))
        card = self.card('Codex')
        expect(card.get_by_role('progressbar')).to_have_count(1)
        markers = card.get_by_role('meter')
        expect(markers).to_have_count(1)
        self.assert_marker(markers.first, 40)
        self.assert_marker_on_spend_track(markers.first)
        expect(card.get_by_text(DOUBLE, exact=True)).to_have_count(0)

        self.open_value(native.overview(elapsed=120 * 60, remaining=None, duration=300))
        card = self.card('Codex')
        expect(card.get_by_role('progressbar')).to_have_count(0)
        markers = card.get_by_role('meter')
        expect(markers).to_have_count(1)
        self.assert_marker(markers.first, 40)

    def test_elapsed_marker_moves_at_start_middle_and_just_before_reset_without_changing_spend(self):
        duration = 7 * native.DAY
        for elapsed in (-60, 0, 3.5 * native.DAY, duration - 60):
            with self.subTest(elapsed=elapsed):
                value = native.overview(elapsed=elapsed, remaining=13, duration=10080)
                self.open_value(value)
                card = self.card('Codex')
                markers = card.get_by_role('meter')
                # INV-WATT-11: all three retain this same valid weekly anchor.
                expect(markers).to_have_count(3)
                self.assert_marker(markers.nth(0), elapsed / duration * 100)
                self.assert_marker(markers.nth(1), max(0, min(100, 2 * elapsed / duration * 100)))
                self.assert_marker(markers.nth(2), max(0, min(100, 3 * elapsed / duration * 100)))
                self.assertEqual(float(card.get_by_role('progressbar').get_attribute('aria-valuenow')), 87)
        expired = v2.overview(native_value=native.overview(
            elapsed=duration + 60, remaining=13, duration=10080))
        self.synthetic_response(expired)
        card = self.card('Codex')
        expect(card.get_by_role('meter')).to_have_count(0)
        expect(card.get_by_text(re.compile('истек|expired', re.I))).to_be_visible()

    def test_missing_or_inconsistent_anchors_and_money_balance_do_not_fake_elapsed_time(self):
        value = v2.overview()
        window = value['cached_sources'][0]['windows'][0]
        window['window_started_at'] = None
        window['anchor'] = None
        self.synthetic_response(value)
        # The short window lacks a trusted anchor; its independent weekly
        # window remains valid and must keep its marker.
        expect(self.card('Kimi').get_by_role('meter')).to_have_count(1)
        self.page.unroute('**/api/limits-overview')
        self.open_value(v2.overview())
        expect(self.card('OpenRouter').get_by_role('meter')).to_have_count(0)

    def test_inconsistent_start_end_pair_does_not_fake_elapsed_time(self):
        value = v2.overview()
        value['cached_sources'][0]['windows'][0]['resets_at'] += 60
        self.synthetic_response(value)
        # The closed backend contract rejects this contradictory derived
        # anchor pair. The UI must not turn the rejected payload into markers.
        expect(self.panel().get_by_role('meter')).to_have_count(0)

    def test_stale_snapshot_keeps_its_stale_label_and_is_not_called_fresh(self):
        value = v2.overview()
        source = value['cached_sources'][0]
        source.update(status='stale', age_seconds=3000, observed_at=v2.NOW-3000)
        self.synthetic_response(value)
        card = self.card('Kimi')
        expect(card.get_by_text(re.compile('Устарел|stale', re.I))).to_be_visible()


if __name__ == '__main__':
    unittest.main()
