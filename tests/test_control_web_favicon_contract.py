"""Blind public favicon acceptance from specification cb7d8e4; synthetic config."""
import importlib
from html.parser import HTMLParser
import re
from pathlib import Path
import stat
import sys
import unittest
import xml.etree.ElementTree as ET
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
ORIGIN = 'https://control.example.test'


class HeadLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.in_head = True
        elif tag == 'link' and self.in_head:
            self.links.append(dict(attrs))
    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False


class Backend:
    def __init__(self):
        self.calls = []
    def snapshot(self):
        self.calls.append('snapshot')
        return {'tasks': []}
    def answer(self, *args):
        self.calls.append('answer')
        return {'error': 'unavailable'}
    def verdict(self, *args):
        self.calls.append('verdict')
        return {'error': 'unavailable'}


class FaviconContract(unittest.TestCase):
    def setUp(self):
        web = importlib.import_module('_control_web')
        self.backend = Backend()
        config = {'origin': ORIGIN, 'password_hash': web.hash_password('synthetic-icon-test-password'),
                  'totp_secret': 'JBSWY3DPEHPK3PXP', 'session_ttl': 60, 'secure_cookie': True}
        self.client = TestClient(web.create_app(config, self.backend), base_url=ORIGIN)

    def test_public_svg_exact_asset_mime_cache_and_source_mode(self):
        response = self.client.get('/favicon.svg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'].split(';', 1)[0], 'image/svg+xml')
        self.assertIn('no-store', response.headers.get('cache-control', ''))
        asset = ROOT / 'bin' / '_control_web.svg'
        self.assertTrue(asset.is_file(), 'Canonical SVG asset belongs to immutable root package')
        self.assertEqual(response.content, asset.read_bytes())
        self.assertEqual(stat.S_IMODE(asset.stat().st_mode), 0o644)
        self.assertEqual(self.backend.calls, [])

    def test_ordinary_ico_lookup_redirects_to_svg(self):
        response = self.client.get('/favicon.ico', follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers['location'], '/favicon.svg')
        self.assertEqual(self.backend.calls, [])

    def test_root_head_declares_local_svg_icon(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        head = HeadLinks()
        head.feed(response.text)
        icons = [attrs for attrs in head.links if 'icon' in attrs.get('rel', '').split()]
        self.assertTrue(any(attrs.get('href') == '/favicon.svg' and attrs.get('type') == 'image/svg+xml'
                            for attrs in icons), 'Head must declare its local SVG icon')
        self.assertEqual(self.backend.calls, [])

    def test_svg_has_no_active_embedded_html_or_external_resources(self):
        response = self.client.get('/favicon.svg')
        self.assertEqual(response.status_code, 200)
        self.assertNotRegex(response.text, re.compile(r'<!DOCTYPE|<!ENTITY|@import|url\s*\(', re.I))
        svg = ET.fromstring(response.content)
        self.assertEqual(svg.tag.rsplit('}', 1)[-1], 'svg')
        forbidden = {'script', 'foreignObject', 'iframe', 'object', 'embed', 'image', 'audio', 'video'}
        for node in svg.iter():
            tag = node.tag.rsplit('}', 1)[-1]
            self.assertNotIn(tag, forbidden)
            for name, value in node.attrib.items():
                local = name.rsplit('}', 1)[-1]
                self.assertFalse(local.lower().startswith('on'), 'No SVG event handlers')
                self.assertNotRegex(value, re.compile(r'javascript:|https?://|data:|@import|url\s*\(', re.I))
                if local in ('href', 'src'):
                    self.assertTrue(value.startswith('#'), 'Only local fragment references are permitted')
        self.assertEqual(self.backend.calls, [])

    def test_asset_manifest_includes_canonical_svg(self):
        manifest = ROOT / 'scripts.manifest'
        self.assertTrue(manifest.is_file())
        self.assertIn('_control_web.svg', manifest.read_text().split())

    def test_root_and_svg_csp_allow_only_same_origin_images_without_other_relaxations(self):
        expected = {
            'default-src': ["'none'"], 'script-src': ["'self'"],
            'style-src': ["'self'"], 'connect-src': ["'self'"],
            'base-uri': ["'none'"], 'frame-ancestors': ["'none'"],
            'form-action': ["'self'"], 'img-src': ["'self'"],
        }
        for path in ('/', '/favicon.svg'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                directives = [part.strip().split() for part in
                              response.headers.get('content-security-policy', '').split(';')
                              if part.strip()]
                names = [parts[0] for parts in directives]
                self.assertEqual(len(names), len(set(names)), 'No duplicate ambiguous CSP directives')
                self.assertEqual({parts[0]: parts[1:] for parts in directives}, expected,
                                 'Icon loading adds only img-src self to the existing strict policy')
        self.assertEqual(self.backend.calls, [])

    def test_favicon_path_is_not_an_owner_file_reader(self):
        for path in ('/favicon.svg/%2e%2e/owner-config', '/favicon.svg/private-owner-file'):
            response = self.client.get(path)
            self.assertIn(response.status_code, (404, 422))
            self.assertNotIn('synthetic-icon-test-password', response.text)
        self.assertEqual(self.backend.calls, [])


if __name__ == '__main__':
    unittest.main()
