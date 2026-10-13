"""Blind INV-PSTAB-01 browser acceptance for visible quota time markers."""
import base64
import unittest
from playwright.sync_api import expect

import limits_dashboard_blind_support as s
import test_control_web_limits_dashboard_browser_red as harness


DOUBLE = 'Ориентир ×2'
TRIPLE = 'Ориентир ×3'


class QuotaMarkerContrastRED(unittest.TestCase):
    setUpClass = classmethod(harness.LimitsBrowserRED.setUpClass.__func__)
    setUp = harness.LimitsBrowserRED.setUp
    tearDown = harness.LimitsBrowserRED.tearDown
    tab = harness.LimitsBrowserRED.tab
    panel = harness.LimitsBrowserRED.panel

    def open_fixture(self):
        # elapsed=1d puts ×2 inside the 35% spent fill and ×3 on the empty
        # portion. The same marker pixels therefore face both track colors.
        self.backend.limits_value = s.overview(elapsed=s.DAY, remaining=65)
        self.page.goto(self.fixture.origin)
        self.tab('Лимиты').click()
        expect(self.panel().get_by_role('progressbar')).to_be_visible()
        return self.panel().get_by_role('progressbar'), [
            self.panel().get_by_role('meter', name=DOUBLE, exact=True),
            self.panel().get_by_role('meter', name=TRIPLE, exact=True),
        ]

    def rendered_pixels(self):
        encoded = base64.b64encode(self.page.screenshot()).decode('ascii')
        return self.page.evaluate('''async encoded => {
          const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
          const bitmap = await createImageBitmap(new Blob([bytes], {type: 'image/png'}));
          const canvas = document.createElement('canvas');
          canvas.width = bitmap.width; canvas.height = bitmap.height;
          const context = canvas.getContext('2d'); context.drawImage(bitmap, 0, 0);
          return {width: canvas.width, height: canvas.height,
            data: Array.from(context.getImageData(0, 0, canvas.width, canvas.height).data)};
        }''', encoded)

    @staticmethod
    def pixel(image, x, y):
        offset = (round(y) * image['width'] + round(x)) * 4
        return image['data'][offset:offset + 3]

    @staticmethod
    def luminance(rgb):
        channels = [v / 255 for v in rgb]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]

    def assert_dark_boundary(self, bar, marker, filled):
        box = marker.bounding_box()
        track = bar.bounding_box()
        image = self.rendered_pixels()
        # Probe inner edge pixels against the nearby track outside the marker.
        # This measures rendered pixels, so a declared outline that is clipped
        # or hidden cannot satisfy the contract.
        x0, y0 = box['x'], box['y']
        width, height = box['width'], box['height']
        self.assertGreater(width, 0, 'Marker must have a visible footprint')
        self.assertGreater(height, 0, 'Marker must have a visible footprint')
        outer = []
        inner = []
        for y in range(max(0, round(y0)), min(image['height'], round(y0 + height))):
            for x in range(max(0, round(x0)), min(image['width'], round(x0 + width))):
                lum = self.luminance(self.pixel(image, x, y))
                edge = (x <= x0 + 1 or x >= x0 + width - 2 or
                        y <= y0 + 1 or y >= y0 + height - 2)
                (outer if edge else inner).append(lum)
        dark_edges = sum(lum < .12 for lum in outer)
        bright_interior = [lum for lum in inner if lum > .2]
        # An outline must remain visible against the marker's own interior too:
        # the empty track is intentionally dark, so testing only against the
        # track would mistake a black edge that disappears into it for contrast.
        self.assertGreaterEqual(dark_edges, 2,
                                'Marker needs a rendered dark edge around its visible shape')
        self.assertGreaterEqual(len(bright_interior), 2,
                                'Marker interior must remain visible inside its dark boundary')
        contrast = (max(bright_interior) + .05) / (min(outer) + .05)
        self.assertGreaterEqual(contrast, 3,
                                'Dark marker edge must contrast with the marker interior')
        center = x0 + width / 2
        spent_edge = track['x'] + track['width'] * .35
        self.assertEqual(center < spent_edge, filled,
                         'Fixture must expose each marker on its intended quota segment')

    def test_x2_x3_keep_position_and_shape_with_dark_edges_on_fill_and_empty_track(self):
        bar, markers = self.open_fixture()
        expected = (2 / 7, 3 / 7)
        shape = []
        for width in (360, 1280):
            self.page.set_viewport_size(dict(width=width, height=900))
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
            track = bar.bounding_box()
            self.assertGreater(track['width'], 100)
            for index, marker in enumerate(markers):
                expect(marker).to_be_visible()
                box = marker.bounding_box()
                center = box['x'] + box['width'] / 2
                self.assertAlmostEqual(center, track['x'] + track['width'] * expected[index], delta=4,
                                       msg='Time marker must stay at its elapsed-time position')
                self.assertGreaterEqual(box['x'], -1)
                self.assertLessEqual(box['x'] + box['width'], width + 1)
                current_shape = (round(box['width'], 1), round(box['height'], 1))
                if width == 360:
                    shape.append(current_shape)
                else:
                    self.assertAlmostEqual(current_shape[0], shape[index][0], delta=1,
                                           msg='Marker shape size must not change with viewport width')
                    self.assertAlmostEqual(current_shape[1], shape[index][1], delta=1,
                                           msg='Marker shape size must not change with viewport width')
                self.assert_dark_boundary(bar, marker, filled=(index == 0))
            self.assertEqual(float(bar.get_attribute('aria-valuenow')), 35,
                             'Elapsed marker rendering must not change the 35% spent value')

    def test_x2_x3_remain_readable_in_forced_colors(self):
        bar, markers = self.open_fixture()
        self.page.emulate_media(forced_colors='active')
        for index, marker in enumerate(markers):
            expect(marker).to_be_visible()
            self.assert_dark_boundary(bar, marker, filled=(index == 0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
