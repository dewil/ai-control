"""INV42 metadata>=12px, independently inherited writer role after SOURCE-02.

Frozen against integrated e50985d before author correction. Real DOM, synthetic cloud.
"""
# Accepted INV-WSESS-48 (2026-10-08-spec-live-observability-package.md):
# exact activity lives in selected-project details; short badges stay in chips.

import re
import unittest
from playwright.sync_api import expect
import test_control_web_project_cloud_browser as cloud

class ProjectMetadataSourceBlind(unittest.TestCase):
    setUpClass=classmethod(cloud.ProjectCloudBrowserContract.setUpClass.__func__)
    stop_server=classmethod(cloud.ProjectCloudBrowserContract.stop_server.__func__)
    setUp=cloud.ProjectCloudBrowserContract.setUp
    tearDown=cloud.ProjectCloudBrowserContract.tearDown
    control=cloud.ProjectCloudBrowserContract.control
    def test_INV42_project_activity_metadata_readable_at_supported_viewports(self):
        project=self.page.get_by_role('button',name=re.compile(r'^high(?:\b|\s)'))
        project.focus(); project.press('Space')
        summary=self.page.locator('summary').filter(has_text='Сведения о проекте high')
        summary.focus(); summary.press('Enter')
        region=self.page.get_by_role('region',name='Сведения о проекте high',exact=True)
        expect(region).to_be_visible()
        for width in (320,390,1280):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':900})
                # Public keyboard/touch disclosure exposes exact activity; all visible badges remain readable too.
                detail=region.get_by_text(re.compile(r'Последняя активность:|Сводка на')).or_(self.page.get_by_role('group',name='Проекты',exact=True).locator('time'))
                expect(region.get_by_text(re.compile(r'Последняя активность:'))).to_be_visible()
                observed=detail.evaluate_all('els=>els.filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().height&&getComputedStyle(e).visibility!=="hidden").map(e=>({text:e.textContent,font:parseFloat(getComputedStyle(e).fontSize)}))')
                self.assertTrue(observed,'Fixture must render actual activity metadata')
                self.assertTrue(all(row['font']>=12 for row in observed),f'INV42 metadata minimum12px violated at{width}px: {observed}')

if __name__=='__main__':unittest.main()
