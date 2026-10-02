#!/usr/bin/env python3
"""Independent FR-KIMI-LIMITS regression tests; no live requests."""
import copy
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'bin/claude-agent-limits-digest'
loader = importlib.machinery.SourceFileLoader('digest_authoritative_tests', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

RESET = '2026-10-02T18:00:00Z'

def window(duration=300, unit='TIME_UNIT_MINUTE', used='100', limit='100'):
    return {'window': {'duration': duration, 'timeUnit': unit},
            'detail': {'limit': limit, 'used': used, 'resetTime': RESET}}

class AuthoritativeKimiTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        override = patch.object(m, 'KIMI_HOME', str(self.home), create=True)
        override.start()
        self.addCleanup(override.stop)
        (self.home / 'credentials').mkdir()
        (self.home / 'config.toml').write_text('''[providers."managed:kimi-code"]
base_url = "https://api.kimi.ai/coding/v1"
[providers."managed:kimi-code".oauth]
storage = "file"
key = "oauth/test-kimi"
oauth_host = "https://auth.kimi.ai"
''')
        (self.home / 'credentials/test-kimi.json').write_text(json.dumps({
            'access_token': 'SECRET', 'refresh_token': 'SECRET-REFRESH',
            'expires_at': time.time() + 3600}))
        self.legacy = {'limit_5h': {'used_ratio': 0, 'reset_time': '2026-10-01T18:00:00Z'},
                       'limit_month_total': {'used_ratio': 0.12, 'reset_time': '2026-11-02T00:00:00Z'}}

    def build(self, body):
        with patch.object(m, 'http_get', return_value=(200, body)):
            return m.build_kimi()

    def assert_error(self, body):
        result = self.build(body)
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('five_hour', result)

    def test_new_limits_override_stale_zero_and_reset_preserve_month(self):
        result = self.build({'limits': [window()], 'usages': self.legacy})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['five_hour']['remaining'], 0)
        self.assertIn('2026-10-02', result['five_hour']['resets_at'])
        self.assertEqual(result['month_total']['remaining'], 88)

    def test_new_only_limits_are_valid_and_overuse_clamps(self):
        result = self.build({'limits': [window(used='150')]})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['five_hour']['remaining'], 0)
        self.assertNotIn('month_total', result)

    def test_legacy_fallback_remains_available(self):
        legacy = copy.deepcopy(self.legacy)
        legacy['limit_5h']['used_ratio'] = 0.043
        result = self.build({'usages': legacy})
        self.assertEqual(result['status'], 'ok')
        self.assertAlmostEqual(result['five_hour']['remaining'], 95.7)
        self.assertEqual(result['month_total']['remaining'], 88)

    def test_window_units_and_seven_day_mapping(self):
        cases = [(18000, 'TIME_UNIT_SECOND', 'five_hour'),
                 (300, 'TIME_UNIT_MINUTE', 'five_hour'),
                 (5, 'TIME_UNIT_HOUR', 'five_hour'),
                 (604800, 'TIME_UNIT_SECOND', 'seven_day'),
                 (10080, 'TIME_UNIT_MINUTE', 'seven_day'),
                 (168, 'TIME_UNIT_HOUR', 'seven_day'),
                 (7, 'TIME_UNIT_DAY', 'seven_day')]
        for duration, unit, key in cases:
            with self.subTest(duration=duration, unit=unit):
                result = self.build({'limits': [window(duration, unit, used='25')]})
                self.assertEqual(result['status'], 'ok')
                self.assertEqual(result[key]['remaining'], 75)
                self.assertNotIn('seven_day' if key == 'five_hour' else 'five_hour', result)

    def test_invalid_known_window_never_falls_back_to_zero(self):
        invalid_details = [None, {}, {'limit': '100'},
                           {'limit': 0, 'used': 0}, {'limit': -1, 'used': 0},
                           {'limit': True, 'used': 0}, {'limit': 'NaN', 'used': 0},
                           {'limit': 'Infinity', 'used': 0},
                           {'limit': '100', 'used': True},
                           {'limit': '100', 'used': -1},
                           {'limit': '100', 'used': 'NaN'},
                           {'limit': '100', 'used': 'Infinity'}]
        for detail in invalid_details:
            with self.subTest(detail=detail):
                entry = window()
                entry['detail'] = detail
                self.assert_error({'limits': [entry], 'usages': self.legacy})

    def test_conflicting_duplicates_fail_even_with_legacy(self):
        self.assert_error({'limits': [window(), window(5, 'TIME_UNIT_HOUR', used='25')],
                           'usages': self.legacy})

    def test_unknown_only_cannot_be_presented_as_five_hour(self):
        self.assert_error({'limits': [window(2, 'TIME_UNIT_HOUR')]})
        self.assert_error({'usages': {'unknown_limit': {'used_ratio': 0.5}}})

    def test_render_and_signature_reflect_exhaustion(self):
        exhausted = self.build({'limits': [window()], 'usages': self.legacy})
        fresh = self.build({'usages': self.legacy})
        panel = m.render({'snapshot': {'kimi': exhausted}})
        self.assertIn('Kimi Code', panel)
        self.assertIn('100.0%', panel)
        self.assertNotEqual(m.digits_signature({'kimi': exhausted}),
                            m.digits_signature({'kimi': fresh}))
        self.assertNotIn('SECRET', panel + json.dumps(exhausted))

if __name__ == '__main__':
    unittest.main()
