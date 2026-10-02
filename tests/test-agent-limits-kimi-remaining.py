#!/usr/bin/env python3
"""Independent alternate-counter regression tests, written from the spec."""
import importlib.util
from pathlib import Path
import unittest

fixture_path = Path(__file__).with_name('test-agent-limits-kimi-authoritative.py')
fixture_spec = importlib.util.spec_from_file_location('kimi_remaining_fixtures', fixture_path)
f = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(f)


def remaining_window(remaining='100', **extra):
    entry = f.window()
    entry['detail'].pop('used')
    entry['detail']['remaining'] = remaining
    entry['detail'].update(extra)
    return entry


class RemainingCounterTests(unittest.TestCase):
    setUp = f.AuthoritativeKimiTests.setUp
    build = f.AuthoritativeKimiTests.build
    assert_error = f.AuthoritativeKimiTests.assert_error

    def test_remaining_full_means_zero_used(self):
        result = self.build({'limits': [remaining_window()]})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['five_hour']['remaining'], 100)

    def test_remaining_quarter_overrides_legacy_zero(self):
        result = self.build({'limits': [remaining_window('25')], 'usages': self.legacy})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['five_hour']['remaining'], 25)
        self.assertIn('75.0%', f.m.render({'snapshot': {'kimi': result}}))

    def test_consistent_both_counters_are_valid(self):
        for used, remaining in [('75', '25'), ('0.3', '99.7')]:
            with self.subTest(used=used, remaining=remaining):
                result = self.build({'limits': [remaining_window(remaining, used=used)]})
                self.assertEqual(result['status'], 'ok')
                self.assertAlmostEqual(result['five_hour']['remaining'], float(remaining))

    def test_invalid_remaining_never_falls_back(self):
        for value in [None, True, False, 'NaN', float('nan'), 'Infinity', -1, '101', 'bad']:
            with self.subTest(remaining=value):
                self.assert_error({'limits': [remaining_window(value)], 'usages': self.legacy})

    def test_invalid_both_missing_and_mismatch_never_fall_back(self):
        entries = [remaining_window('25', used=None), remaining_window('25', used=True),
                   remaining_window('25', used='NaN'), remaining_window('25', used=-1),
                   remaining_window('25', used='74'), remaining_window('25', used='101')]
        neither = f.window()
        neither['detail'].pop('used')
        entries.append(neither)
        for entry in entries:
            with self.subTest(detail=entry['detail']):
                self.assert_error({'limits': [entry], 'usages': self.legacy})

    def test_equivalent_duplicate_counters_agree(self):
        equivalent = remaining_window('75')
        equivalent['window'] = {'duration': 5, 'timeUnit': 'TIME_UNIT_HOUR'}
        result = self.build({'limits': [f.window(used='25'), equivalent], 'usages': self.legacy})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['five_hour']['remaining'], 75)

    def test_unknown_panel_does_not_present_zero_usage(self):
        result = self.build({'limits': [remaining_window('NaN')], 'usages': self.legacy})
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('five_hour', result)
        panel = f.m.render({'snapshot': {'kimi': result}})
        self.assertIn('Kimi Code', panel)
        self.assertNotIn('0.0%', panel)


if __name__ == '__main__':
    unittest.main()
