"""Independent browser RED for compact stable UI and viewport preservation."""
from copy import deepcopy
import re
import time
import unittest

from playwright.sync_api import expect
from unittest.mock import patch

import live_sse_blind_support as live
import participation_blind_support as part
import test_control_web_attention_priority_browser_blind as attention
import test_control_web_project_cloud_browser as project_cloud
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

    def place_visible_anchor(self, locator):
        expect(locator).to_be_visible()
        locator.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
        expect(locator).to_be_visible()
        rect = locator.bounding_box()
        self.assertIsNotNone(rect, 'reader anchor must have rendered geometry')
        height = self.page.viewport_size['height']
        self.assertGreater(rect['y']+rect['height'], 0, 'reader anchor is below the viewport')
        self.assertLess(rect['y'], height, 'reader anchor is above the viewport')
        return rect['y']

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
            f'Overview row {i:02d}', activity='active', running='confirmed') for i in range(28)]
        self.backend.overview['rows'] = base
        self.open_panel()
        anchor = self.page.get_by_text('Overview row 17', exact=True)
        before = self.place_visible_anchor(anchor)
        added = attention.row(99, '99999999-9999-4999-8999-999999999999',
                              'Inserted above reader', activity='active')
        with_rows(self.backend, [added, *base])
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('Inserted above reader', exact=True).count() == 1)
        expect(anchor).to_be_visible()
        self.assertLessEqual(abs(anchor.bounding_box()['y']-before), 3,
                             'overview insertion above the reader moved the visible anchor')
        before = anchor.bounding_box()['y']
        with_rows(self.backend, base)
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('Inserted above reader', exact=True).count() == 0)
        expect(anchor).to_be_visible()
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
            f'Delayed row {i:02d}', activity='active', running='confirmed') for i in range(25)]
        self.backend.overview['rows'] = base
        self.open_panel()
        held = []
        self.page.route(re.compile(r'/api/participation-overview(?:\?.*)?$'), lambda route: held.append(route))
        with_rows(self.backend, [attention.row(80, '88888888-8888-4888-8888-888888888888',
            'Delayed inserted row', activity='active'), *base])
        self.page.clock.fast_forward(6000)
        self.until(lambda:len(held) == 1, 'synthetic overview request did not pause')
        user_anchor = self.page.get_by_text('Delayed row 18', exact=True)
        user_y = self.place_visible_anchor(user_anchor)
        held[0].fulfill(status=200, json=deepcopy(self.backend.overview))
        self.until(lambda:self.page.get_by_text('Delayed inserted row', exact=True).count() == 1)
        expect(user_anchor).to_be_visible()
        self.assertLessEqual(abs(user_anchor.bounding_box()['y']-user_y), 3,
                             'response restored stale pre-fetch scroll after the user moved')

    def test_CUI03_removed_scroll_anchor_falls_back_to_surviving_neighbor(self):
        self.page.clock.install()
        base = [attention.row(i+1, f'{i+10:08d}-0000-4000-8000-{i+10:012d}',
            f'Removal row {i:02d}', activity='active', running='confirmed') for i in range(28)]
        self.backend.overview['rows'] = base
        self.open_panel()
        anchor = self.page.get_by_text('Removal row 17', exact=True)
        neighbor = self.page.get_by_text('Removal row 18', exact=True)
        self.place_visible_anchor(anchor)
        expect(neighbor).to_be_visible()
        neighbor_y = neighbor.bounding_box()['y']
        with_rows(self.backend, [row for row in base if row['label'] != 'Removal row 17'])
        self.page.clock.fast_forward(6000)
        self.until(lambda:anchor.count() == 0)
        expect(neighbor).to_be_visible()
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


class CompactProjectSummaryBrowserBlind(unittest.TestCase):
    """Project-summary endpoint uses the existing authenticated synthetic HTTP fixture."""
    setUpClass = classmethod(project_cloud.ProjectCloudBrowserContract.setUpClass.__func__)
    stop_server = classmethod(project_cloud.ProjectCloudBrowserContract.stop_server.__func__)
    setUp = project_cloud.ProjectCloudBrowserContract.setUp
    tearDown = project_cloud.ProjectCloudBrowserContract.tearDown
    control = project_cloud.ProjectCloudBrowserContract.control
    tile = project_cloud.ProjectCloudBrowserContract.tile
    def test_CUI03_project_summary_reflow_keeps_reader_anchor_focus_and_selection(self):
        self.page.set_viewport_size({'width': 360, 'height': 844})
        high = self.tile('high')
        high.click()
        expect(high).to_have_attribute('aria-pressed', 'true')
        session = self.page.get_by_role('button', name='Cloud synthetic session', exact=False)
        expect(session).to_be_visible()
        session.click()
        reader = self.page.get_by_text('CLOUD SYNTHETIC HISTORY', exact=True)
        expect(reader).to_be_visible()
        # Confirmed history selection collapses the cloud by design; expose it
        # again so refresh is a real visible user control during the scenario.
        self.page.locator('#projects-toggle').click()
        expect(self.tile('high')).to_be_visible()
        loww_tile = self.tile('loww')
        loww_before = loww_tile.bounding_box()

        # Change an existing project's count enough to reflow the expanded
        # mobile cloud above the chat reader.
        rows = project_cloud.project_rows()
        loww = next(row for row in rows if row['name'] == 'loww')
        loww['session_count'] = 1000
        held = []
        self.page.route('**/api/session-project-summary*', lambda route: held.append(route))
        self.control(projects=rows)
        refresh = self.page.get_by_role('button', name='Обновить проекты', exact=True)
        refresh.click()
        deadline = time.monotonic() + 3
        while not held and time.monotonic() < deadline:
            self.page.wait_for_timeout(20)
        self.assertEqual(len(held), 1, 'summary refresh did not reach deferred public fixture')

        # New user focus and reading position after request start must win over
        # any state captured before the project summary refresh began.
        composer = self.page.locator('textarea').last
        composer.fill('Synthetic project refresh draft')
        reader.evaluate("el=>el.scrollIntoView({block:'center',behavior:'instant'})")
        expect(reader).to_be_visible()
        reader_box = reader.bounding_box()
        self.assertGreater(reader_box['y']+reader_box['height'], 0, 'reader anchor is below viewport')
        self.assertLess(reader_box['y'], self.page.viewport_size['height'], 'reader anchor is above viewport')
        reader_y = reader_box['y']
        composer.evaluate('el=>el.focus({preventScroll:true})')
        self.assertTrue(composer.evaluate('el=>el===document.activeElement'))
        held[0].fulfill(status=200, json={'projects': rows})
        self.page.unroute('**/api/session-project-summary*')
        expect(reader).to_be_visible()
        loww_after = loww_tile.bounding_box()
        loww_grew = loww_after['width']*loww_after['height'] > loww_before['width']*loww_before['height']
        anchor_delta = abs(reader.bounding_box()['y']-reader_y)
        composer_kept_focus = composer.evaluate('el=>el===document.activeElement')
        draft_kept = composer.input_value() == 'Synthetic project refresh draft'
        high_still_selected = high.get_attribute('aria-pressed') == 'true'
        no_horizontal_overflow = self.page.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth) <= 361')
        self.tile('loww').click()
        explicit_selection_works = self.tile('loww').get_attribute('aria-pressed') == 'true'
        self.assertTrue(loww_grew, 'summary update did not reflow the changed project tile')
        self.assertLessEqual(anchor_delta, 3,
                             'project-summary reflow moved the visible chat reader anchor')
        self.assertTrue(composer_kept_focus, 'project-summary refresh stole focus from the active chat composer')
        self.assertTrue(draft_kept, 'project-summary refresh changed the active chat draft')
        self.assertTrue(high_still_selected, 'reflowing the cloud cleared the current project selection')
        self.assertTrue(explicit_selection_works, 'an explicit project selection stopped working after refresh')
        self.assertTrue(no_horizontal_overflow, 'project-summary reflow caused horizontal overflow at 360px')

