"""USN migration of legacy project-cloud browser checks; synthetic HTTP only.

Project tiles, size sorting, and inline activity metadata are superseded by the
unified authorized project filter and session list. Keep authority, selection,
responsive geometry, and no-unrequested-history checks on the public controls.
"""
import re
import unittest

from playwright.sync_api import expect
import test_control_web_project_cloud_browser as fixture


class ProjectCloudVisibleActivityLayoutRed(fixture.ProjectCloudBrowserContract):
    # The original fixture's count-sized tile sorting cases no longer describe
    # the product surface; these tests keep its security and layout intent.
    test_INV_WSESS_19_count_sort_numeric_bounded_size_keyboard_selection_and_widths = None
    test_INV_WSESS_19_activity_groups_ties_and_only_sort_enum_persists = None
    test_INV_WSESS_19_valid_and_unavailable_deeplinks_use_exact_project_and_sid = None
    test_INV_WSESS_19_refresh_reflows_without_losing_focus_selection_or_viewport = None
    test_INV_WSESS_19_summary_failure_keeps_authoritative_projects_and_honest_unknown = None
    test_INV_WSESS_19_selected_project_becoming_unavailable_clears_history_and_late_response = None

    def test_project_filter_keeps_unknown_distinct_from_unavailable_without_opening_history(self):
        project = self.project_filter()
        options = project.locator('option')
        for name in ('loww', 'high', 'zero', 'stle', 'unkn'):
            expect(options.filter(has_text=re.compile(r'^' + re.escape(name) + r'(?:\s|$)'))).to_have_count(1)
        unavailable = options.filter(has_text=re.compile(r'^down(?:\s|$)'))
        self.assertEqual(unavailable.count(), 0,
                         'Authoritatively unavailable project is omitted from selectable filters')
        self.assertFalse(options.filter(has_text=re.compile(r'^unkn(?:\s|$)')).is_disabled(),
                         'Unknown activity does not imply unavailable project')
        self.select_project('high')
        self.assertEqual(self.selected_filter(), 'high')
        self.assertFalse(any(call['method'] == 'history' for call in self.calls()),
                         'Project filter cannot select a session or request its history')

    def test_session_list_and_chat_fit_desktop_and_mobile_drawer(self):
        self.select_project('high')
        self.open_session()
        expect(self.page.get_by_text('CLOUD SYNTHETIC HISTORY', exact=True)).to_be_visible()
        self.page.set_viewport_size({'width': 1280, 'height': 900})
        listing = self.page.get_by_role('list', name=re.compile('Сессии', re.I)).or_(
            self.page.get_by_role('listbox', name=re.compile('Сессии', re.I)))
        expect(listing).to_be_visible()
        row = listing.get_by_role('listitem').or_(listing.get_by_role('option')).filter(has_text='Cloud synthetic session')
        expect(row).to_have_count(1)
        for width in (1280, 390, 360, 320):
            self.page.set_viewport_size({'width': width, 'height': 844})
            if width < 1024 and not listing.is_visible():
                trigger = self.page.get_by_role('button', name=re.compile(r'^Сессии(?:\s*[·•]\s*внимание\s*\d+)?$|^Открыть список сессий$', re.I))
                expect(trigger).to_be_visible(); trigger.click()
            expect(listing).to_be_visible()
            self.assertLessEqual(self.page.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)'), width + 1)
            if row.is_visible():
                box = row.bounding_box()
                self.assertIsNotNone(box)
                self.assertGreaterEqual(box['height'], 44, 'Session rows retain a touch-sized target')
        self.assertFalse(any(method == 'POST' for method, url in self.network))

    def test_filter_remains_independent_of_open_chat_and_draft(self):
        self.select_project('high')
        self.open_session()
        reader = self.page.get_by_text('CLOUD SYNTHETIC HISTORY', exact=True)
        expect(reader).to_be_visible()
        composer = self.page.locator('textarea')
        composer.fill('Synthetic filter-independent draft')
        before_url = self.page.url
        before_history = len([call for call in self.calls() if call['method'] == 'history'])
        self.select_project('loww')
        self.assertEqual(self.selected_filter(), 'loww')
        self.assertEqual(self.page.url, before_url)
        expect(reader).to_be_visible()
        self.assertEqual(composer.input_value(), 'Synthetic filter-independent draft')
        self.assertEqual(len([call for call in self.calls() if call['method'] == 'history']), before_history,
                         'Changing the project filter cannot replace the selected chat or reread its history')
