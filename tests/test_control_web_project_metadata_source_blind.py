"""INV42 metadata>=12px, independently inherited writer role after SOURCE-02.

Frozen against integrated e50985d before author correction. Real DOM, synthetic cloud.
"""
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
        for width in (320,390,1280):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':900})
                detail=self.page.locator('.project-activity-detail');expect(detail.first).to_be_visible()
                observed=detail.evaluate_all('els=>els.filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().height).map(e=>({text:e.textContent,font:parseFloat(getComputedStyle(e).fontSize)}))')
                self.assertTrue(observed,'Fixture must render actual activity metadata')
                self.assertTrue(all(row['font']>=12 for row in observed),f'INV42 metadata minimum12px violated at{width}px: {observed}')

if __name__=='__main__':unittest.main()
