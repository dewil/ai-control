"""Independent browser RED for compact stable UI and viewport preservation."""
from copy import deepcopy
import re
import unittest

from playwright.sync_api import expect
from unittest.mock import patch

import live_sse_blind_support as live
import participation_blind_support as part
import test_control_web_attention_priority_browser_blind as attention
import test_control_web_pinned_activity_browser_blind as pinned
import pinned_activity_blind_support as pins


def with_rows(backend, rows):
    backend.overview['rows'] = rows
    backend.overview['revision'] += 1
    backend.overview['generated_at'] += 1


def item_history(count=24):
    value = live.history('Reader synthetic first')
    value['turns'][0]['items'] = [dict(id=f'reader-{i}', role='assistant',
        text=f'Activity reader {i}\n' + ('long line\n' * 12), truncated=False,
        timestamp=1770000000+i, time_precision='item') for i in range(count)]
    return value


class CompactOverviewBrowserBlind(unittest.TestCase):
    """Real Chromium geometry and public overview polling with synthetic backend."""
    setUpClass = classmethod(attention.AttentionPriorityBrowserBlind.setUpClass.__func__)
    setUp = attention.AttentionPriorityBrowserBlind.setUp
    tearDown = attention.AttentionPriorityBrowserBlind.tearDown
    until = attention.AttentionPriorityBrowserBlind.until
    open_panel = attention.AttentionPriorityBrowserBlind.open_panel

    def test_CUI01_CUI04_two_badge_geometry_touch_targets_and_no_phone_overflow(self):
        self.backend.overview['rows'] = [attention.row(1, live.SID, 'Compact',
            activity='active', waits=['question'], questions=[dict(
                interaction_id=part.HANDLE, state='actionable', blocking=True)],
            result=dict(turn_id=part.TURN, item_id=attention.READY_ITEM,
                status='completed', ready=True, completed_at=1800000000))]
        self.open_panel()
        row = self.page.locator('#participation-list .participation-row').filter(has_text='Compact')
        expect(row).to_be_visible()
        badges = row.locator('p').inner_text()
        self.assertIn('Вопрос', badges)
        self.assertIn('ответ', badges.lower())
        for width, height_limit in ((1280, 100), (360, 160)):
            with self.subTest(width=width):
                self.page.set_viewport_size(dict(width=width, height=900))
                box = row.bounding_box()
                self.assertIsNotNone(box)
                self.assertLessEqual(box['height'], height_limit,
                    f'simple row with two badges is {box["height"]:.1f}px high at {width}px')
                for button in row.get_by_role('button').all():
                    if button.is_visible():
                        rect = button.bounding_box()
                        self.assertIsNotNone(rect)
                        self.assertGreaterEqual(rect['width'], 44, 'visible touch target narrower than 44px')
                        self.assertGreaterEqual(rect['height'], 44, 'visible touch target shorter than 44px')
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width+1,
                                     f'document overflows at {width}px')
        self.page.set_viewport_size(dict(width=320, height=900))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 321,
                             'document overflows at 320px')

    def test_CUI02_unchanged_row_node_focus_and_manual_other_disclosure_survive_update(self):
        self.page.clock.install()
        self.open_panel()
        listing = self.page.locator('#participation-list')
        other = listing.locator('details.participation-other')
        self.assertEqual(other.count(), 1)
        other.evaluate('el=>el.open=true')
        stable = listing.locator('.participation-row').filter(has_text='Priority approval and question')
        action = stable.get_by_role('button', name='Открыть вопрос', exact=True)
        action.focus()
        stable.evaluate('e=>window.compactStableRow=e')
        other.evaluate('e=>window.compactOtherDisclosure=e')
        self.backend.overview['rows'][2]['label'] = 'Updated unrelated ready row'
        self.backend.overview['revision'] += 1
        self.backend.overview['generated_at'] += 1
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('Updated unrelated ready row', exact=True).count() == 1)
        self.assertTrue(stable.evaluate('e=>e.isConnected && e===window.compactStableRow'),
                        'unchanged (project,sid) row DOM identity was replaced')
        self.assertTrue(action.evaluate('e=>e.isConnected && e===document.activeElement'),
                        'ordinary refresh stole focus from a row action')
        self.assertTrue(other.evaluate('e=>e.isConnected && e===window.compactOtherDisclosure && e.open'),
                        'manual other disclosure state was lost')

    def test_CUI03_overview_insert_remove_and_removed_anchor_keep_reader_position(self):
        self.page.clock.install()
        base = [attention.row(i+1, f'{i+10:08d}-0000-4000-8000-{i+10:012d}',
            f'Overview row {i:02d}', activity='idle') for i in range(28)]
        self.backend.overview['rows'] = base
        self.open_panel()
        anchor = self.page.get_by_text('Overview row 17', exact=True)
        anchor.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
        before = anchor.bounding_box()['y']
        added = attention.row(99, '99999999-9999-4999-8999-999999999999',
                              'Inserted above reader', activity='active')
        with_rows(self.backend, [added, *base])
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('Inserted above reader', exact=True).count() == 1)
        self.assertLessEqual(abs(anchor.bounding_box()['y']-before), 3,
                             'overview insertion above the reader moved the visible anchor')
        before = anchor.bounding_box()['y']
        with_rows(self.backend, base)
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('Inserted above reader', exact=True).count() == 0)
        self.assertLessEqual(abs(anchor.bounding_box()['y']-before), 3,
                             'overview removal above the reader moved the visible anchor')

        neighbor = self.page.get_by_text('Overview row 18', exact=True)
        neighbor_y = neighbor.bounding_box()['y']
        remaining = [row for row in base if row['label'] != 'Overview row 17']
        with_rows(self.backend, remaining)
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('Overview row 17', exact=True).count() == 0)
        self.assertLessEqual(abs(neighbor.bounding_box()['y']-neighbor_y), 3,
                             'removing the scroll anchor did not retain the surviving neighboring row')

    def test_CUI03_user_scroll_during_delayed_overview_fetch_wins(self):
        self.page.clock.install()
        base = [attention.row(i+1, f'{i+10:08d}-0000-4000-8000-{i+10:012d}',
            f'Delayed row {i:02d}', activity='idle') for i in range(25)]
        self.backend.overview['rows'] = base
        self.open_panel()
        held = []
        self.page.route(re.compile(r'/api/participation-overview(?:\?.*)?$'), lambda route: held.append(route))
        with_rows(self.backend, [attention.row(80, '88888888-8888-4888-8888-888888888888',
            'Delayed inserted row', activity='active'), *base])
        self.page.clock.fast_forward(6000)
        self.until(lambda:len(held) == 1, 'synthetic overview request did not pause')
        user_anchor = self.page.get_by_text('Delayed row 18', exact=True)
        user_anchor.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
        user_y = user_anchor.bounding_box()['y']
        held[0].fulfill(status=200, json=deepcopy(self.backend.overview))
        self.until(lambda:self.page.get_by_text('Delayed inserted row', exact=True).count() == 1)
        self.assertLessEqual(abs(user_anchor.bounding_box()['y']-user_y), 3,
                             'response restored stale pre-fetch scroll after the user moved')

    def test_CUI03_removed_scroll_anchor_falls_back_to_surviving_neighbor(self):
        self.page.clock.install()
        base = [attention.row(i+1, f'{i+10:08d}-0000-4000-8000-{i+10:012d}',
            f'Removal row {i:02d}', activity='idle') for i in range(28)]
        self.backend.overview['rows'] = base
        self.open_panel()
        anchor = self.page.get_by_text('Removal row 17', exact=True)
        neighbor = self.page.get_by_text('Removal row 18', exact=True)
        anchor.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
        neighbor_y = neighbor.bounding_box()['y']
        with_rows(self.backend, [row for row in base if row['label'] != 'Removal row 17'])
        self.page.clock.fast_forward(6000)
        self.until(lambda:anchor.count() == 0)
        self.assertLessEqual(abs(neighbor.bounding_box()['y']-neighbor_y), 3,
                             'when the anchor disappears, the surviving neighbor was not retained')


class CompactPinsBrowserBlind(unittest.TestCase):
    """Pins refresh uses the existing synthetic public endpoint fixture."""
    setUpClass = classmethod(pinned.PinnedActivityBrowserBlind.setUpClass.__func__)
    setUp = pinned.PinnedActivityBrowserBlind.setUp
    tearDown = pinned.PinnedActivityBrowserBlind.tearDown
    until = pinned.PinnedActivityBrowserBlind.until
    select = pinned.PinnedActivityBrowserBlind.select
    visible = pinned.PinnedActivityBrowserBlind.visible
    refresh = pinned.PinnedActivityBrowserBlind.refresh
    pins_title = pinned.PinnedActivityBrowserBlind.pins_title
    pin_block = pinned.PinnedActivityBrowserBlind.pin_block

    def test_CUI03_pin_refresh_above_reader_respects_user_scroll_during_async_fetch(self):
        self.select()
        history = item_history()
        self.backend.value = history
        self.fixture.transport.emit(live.snapshot(2, value=history))
        anchor = self.page.get_by_text(re.compile('Activity reader 14'))
        expect(anchor).to_have_count(1)
        anchor.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
        before = anchor.bounding_box()['y']
        self.value = pins.dto([pins.item(title='Pins refreshed above reader',
            last_activity=pins.NOW-1), pins.item(pin_id='55555555-5555-4555-8555-555555555555',
            sid=live.OTHER, title='Second synthetic pin')])
        held = []
        self.page.unroute(pinned.PINS_ROUTE)
        self.page.route(pinned.PINS_ROUTE, lambda route: held.append(route))
        self.visible()
        self.until(lambda:len(held) == 1)
        # A fresh user action after request start supersedes the saved position.
        user_anchor = self.page.get_by_text(re.compile('Activity reader 20'))
        user_anchor.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
        user_y = user_anchor.bounding_box()['y']
        held[0].fulfill(status=200, json=deepcopy(self.value))
        expect(self.pin_block().get_by_text('Pins refreshed above reader', exact=True)).to_be_visible()
        self.assertLessEqual(abs(user_anchor.bounding_box()['y']-user_y), 3,
                             'pins response overrode user scroll with a stale captured position')

