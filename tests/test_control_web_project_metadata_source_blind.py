"""INV42 metadata>=12px, independently inherited writer role after SOURCE-02.

Frozen against integrated e50985d before author correction. Real DOM, synthetic cloud.
"""
# Accepted INV-WSESS-48 (2026-10-08-spec-live-observability-package.md):
# exact activity lives in selected-project details; short badges stay in chips.

import re
import unittest
from playwright.sync_api import expect
from control_browser_helpers import choose_project, session_navigator
import test_control_web_project_cloud_browser as cloud

class ProjectMetadataSourceBlind(unittest.TestCase):
    setUpClass=classmethod(cloud.ProjectCloudBrowserContract.setUpClass.__func__)
    stop_server=classmethod(cloud.ProjectCloudBrowserContract.stop_server.__func__)
    setUp=cloud.ProjectCloudBrowserContract.setUp
    tearDown=cloud.ProjectCloudBrowserContract.tearDown
    control=cloud.ProjectCloudBrowserContract.control
    verify_assets=cloud.ProjectCloudBrowserContract.verify_assets

    def test_INV42_project_activity_metadata_readable_at_supported_viewports(self):
        # INV-USN02/04 replaces activity tiles/details with the project filter
        # and compact per-session project/vendor metadata. Preserve readability
        # on that public surface; do not require removed project disclosures.
        choose_project(self.page, 'high')
        for width in (320,390,1280):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':900})
                listing=session_navigator(self.page)
                row=listing.get_by_role('listitem').or_(listing.get_by_role('option')).filter(has_text='Cloud synthetic session')
                expect(row).to_have_count(1)
                metadata=row.get_by_text(re.compile(r'^high\s*·'))
                expect(metadata).to_be_visible()
                self.assertGreaterEqual(metadata.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)'),12,
                                        'Compact project/vendor metadata must remain readable')
                project=self.page.get_by_role('combobox',name='Проект',exact=True)
                self.assertGreaterEqual(project.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)'),12,
                                        'Project choice must remain readable')
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width+1)

if __name__=='__main__':unittest.main()
