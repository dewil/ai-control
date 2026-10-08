"""Independent browser RED for INV-WSESS-19 visible activity and cloud layout."""
# Accepted INV-WSESS-47..50 (2026-10-08-spec-live-observability-package.md):
# canonical captions/chips and native disclosures replace the previous labels/layout.

from datetime import datetime, timezone
import re
import time
import unittest
from zoneinfo import ZoneInfo

import test_control_web_project_cloud_browser as fixture


class ProjectCloudVisibleActivityLayoutRed(fixture.ProjectCloudBrowserContract):
    # Reuse only the existing synthetic browser lifecycle and helpers.
    test_INV_WSESS_19_count_sort_numeric_bounded_size_keyboard_selection_and_widths = None
    test_INV_WSESS_19_activity_groups_ties_and_only_sort_enum_persists = None
    test_INV_WSESS_19_valid_and_unavailable_deeplinks_use_exact_project_and_sid = None
    test_INV_WSESS_19_refresh_reflows_without_losing_focus_selection_or_viewport = None
    test_INV_WSESS_19_summary_failure_keeps_authoritative_projects_and_honest_unknown = None
    test_INV_WSESS_19_selected_project_becoming_unavailable_clears_history_and_late_response = None

    def test_known_null_unknown_and_unavailable_activity_are_visible_and_truthful(self):
        rows = fixture.project_rows()
        now = int(time.time())
        for row in rows:
            if row['summary_state'] in ('fresh', 'stale'):
                row['as_of'] = now
        high = next(row for row in rows if row['name'] == 'high')
        high['last_activity'] = now - 60
        stale = next(row for row in rows if row['name'] == 'stle')
        stale['last_activity'] = now - 3600
        self.control(projects=rows)
        self.page.add_init_script(f"Date.now=()=>{(now + 120) * 1000};")
        self.page.reload()
        self.page.get_by_role('button', name='Сессии', exact=True).or_(self.page.get_by_role('tab', name='Сессии', exact=True)).click()
        self.page.wait_for_timeout(150)

        high_tile = self.tile('high')
        high_tile.focus()
        high_tile.press('Space')
        self.assertEqual(high_tile.get_attribute('aria-pressed'), 'true')
        high_time = high_tile.locator('time')
        self.assertEqual(high_time.count(), 1, 'Known activity has a semantic time element')
        self.assertTrue(high_time.is_visible(), 'Precise activity detail appears on keyboard focus')
        exact = datetime.fromtimestamp(now - 60, timezone.utc).astimezone(ZoneInfo('Europe/Moscow'))
        expected_date = exact.strftime('%d.%m.%Y')
        self.assertRegex(high_time.get_attribute('title') or '', re.escape(expected_date))
        self.assertRegex(high_time.get_attribute('title') or '', exact.strftime('%H:%M'))
        summary_exact = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo('Europe/Moscow'))
        self.assertRegex(high_tile.get_attribute('title') or '', re.escape(summary_exact.strftime('%d.%m.%Y')))
        self.assertRegex(high_tile.get_attribute('title') or '', summary_exact.strftime('%H:%M'))
        self.assertEqual(self.page.get_by_role('button', name=re.compile(r'high.*' + re.escape(expected_date), re.I)).count(), 1,
                         'Project button accessible name includes the exact date')
        self.assertRegex(self.tile('stle').inner_text(), '(?i)устар|stale')
        self.assertEqual(self.tile('zero').locator('time').count(), 0, 'Confirmed null activity has no fabricated time')
        self.assertIn('—', self.tile('zero').inner_text())
        self.assertRegex(self.tile('zero').get_attribute('aria-label'), '(?i)нет активност|no activity')
        unknown = self.tile('unkn').inner_text().lower()
        unavailable = self.tile('down').inner_text().lower()
        self.assertIn('?', unknown)
        self.assertRegex(self.tile('unkn').get_attribute('aria-label'), '(?i)неизвест|unknown')
        self.assertIn('недост.', unavailable)
        self.assertRegex(self.tile('down').get_attribute('aria-label'), '(?i)недоступ|unavailable')
        self.assertNotEqual(unknown, unavailable, 'Unknown and unavailable metadata have distinct explanations')

        before = list(self.network)
        self.tile('stle').hover()
        self.tile('high').focus()
        self.assertEqual(self.network, before, 'Activity rendering and disclosure add no network request')
        self.assertFalse(any(call['method'] == 'history' for call in self.calls()))

    def test_cloud_uses_wide_desktop_workspace_and_wraps_on_mobile(self):
        self.tile('high').focus()
        self.tile('high').press('Space')
        group = self.tile('high').locator('xpath=ancestor::*[@role="group" and (@aria-label or @aria-labelledby)]')
        self.assertEqual(group.count(), 1, 'Project cloud remains a labelled group')

        self.page.set_viewport_size({'width': 1280, 'height': 900})
        group_box = group.bounding_box()
        self.assertIsNotNone(group_box)
        self.assertGreaterEqual(group_box['width'], 900, 'Cloud spans the available desktop workspace')
        boxes = [self.tile(name).bounding_box() for name in ('loww', 'high', 'tiec', 'tieb', 'zero', 'stle')]
        row_counts = {}
        for box in boxes:
            row = round(box['y'] / 8)
            row_counts[row] = row_counts.get(row, 0) + 1
        self.assertGreaterEqual(max(row_counts.values()), 2, 'At least two project buttons share a desktop row')

        session = self.page.get_by_role('button', name='Cloud synthetic session', exact=False)
        session.wait_for(state='visible')
        self.assertLessEqual(group_box['y'] + group_box['height'], session.bounding_box()['y'] + 2,
                             'Project cloud sits above the session list and chat workspace')
        session.click()
        composer = self.page.get_by_role('textbox').last
        composer.wait_for(state='visible')
        self.assertTrue(composer.is_enabled(), 'Chat composer remains usable below the cloud')

        self.page.set_viewport_size({'width': 390, 'height': 844})
        # INV43 closes Projects after confirmed history selection; expose it before geometry checks.
        self.page.locator('#projects-toggle').click()
        self.tile('high').wait_for(state='visible')
        self.assertLessEqual(max(self.page.evaluate('document.documentElement.scrollWidth'),
                                 self.page.evaluate('document.body.scrollWidth')), 390,
                             'Mobile cloud and chat do not cause horizontal page overflow')
        mobile_boxes = [self.tile(name).bounding_box() for name in ('loww', 'high', 'tiec', 'tieb', 'zero', 'stle')]
        self.assertTrue(all(box['x'] >= -1 and box['x'] + box['width'] <= 391 for box in mobile_boxes),
                        'Project buttons wrap within the mobile viewport')
        mobile_rows = {round(box['y'] / 8) for box in mobile_boxes}
        self.assertGreater(len(mobile_rows), 1, 'Cloud wraps naturally at mobile width')
        self.assertEqual(self.tile('high').get_attribute('aria-pressed'), 'true')


if __name__ == '__main__':
    import json
    import sys
    if len(sys.argv) == 4 and sys.argv[1] == '--serve':
        from test_control_web_project_cloud_browser import serve
        from pathlib import Path
        serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main()
