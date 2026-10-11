"""Additional reader and owner-boundary regressions for cached limits."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import cached_limits_backend_blind_support as s
from test_control_web_session_chat_contract import feature


class CachedLimitsAuthorTests(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_broker')
        self.temp = tempfile.TemporaryDirectory(dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.digest = self.base / 'digest.json'
        self.alp = self.base / 'alp.json'
        self.reader = self.module.CachedLimitsReader(str(self.digest), str(self.alp))

    def write(self, path, value):
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def test_nonfinite_json_exponent_rejects_whole_file_independently(self):
        # INV-WLIM-21: JSON numeric overflow is nonfinite even without NaN syntax.
        self.write(self.alp, s.alp())
        self.digest.write_text(json.dumps(s.bot())[:-1] + ',"ignored":1e999}')
        self.digest.chmod(0o600)
        items = self.reader.snapshot(s.NOW)
        self.assertTrue(all(item['status'] == 'unavailable' for item in items if item['node_id'] == 'llm'))
        self.assertEqual(next(item for item in items if item['provider'] == 'codex')['status'], 'ok')

    def test_duration_bounds_fractional_minutes_and_unknown_anchor(self):
        # INV-WLIM-23: category names never supply an unknown duration.
        self.write(self.digest, s.bot())
        for duration, expected in ((59, None), (60, 1), (90, 1.5), (31536000, 525600),
                                   (31536001, None), (True, None)):
            with self.subTest(duration=duration):
                account = s.alp_account()
                account['windows'][0]['duration_seconds'] = duration
                self.write(self.alp, s.alp(account))
                source = next(item for item in self.reader.snapshot(s.NOW) if item['provider'] == 'codex')
                window = source['windows'][0]
                self.assertEqual(window['duration_minutes'], expected)
                self.assertEqual(window['anchor'], None if expected is None else 'derived_reset_and_duration')
                wrapper = s.wrapper(source)
                self.assertEqual(self.module.limits_result(wrapper), wrapper)

    def test_owner_boundary_rejects_arbitrary_window_buckets_and_wrong_provenance(self):
        # INV-WLIM-21: normalized fields cannot smuggle raw provider labels.
        value = s.wrapper(s.source('kimi'))
        value['cached_sources'][0]['windows'][0]['id'] = 'kimi:five_hour'
        self.assertEqual(self.module.limits_result(value), value)
        for edit in ('bucket', 'basis'):
            with self.subTest(edit=edit):
                changed = s.wrapper(s.source('kimi'))
                changed['cached_sources'][0]['windows'][0]['id'] = 'kimi:five_hour'
                if edit == 'bucket':
                    changed['cached_sources'][0]['windows'][0].update(bucket='private_provider_label', id='private_provider_label')
                else:
                    changed['cached_sources'][0]['observation_basis'] = 'provider_capture'
                self.assertEqual(self.module.limits_result(changed), {'error': 'unavailable'})

    def test_reader_uses_argument_clock_after_atomic_replacement_on_warm_reads(self):
        # INV-WLIM-20 INV-WLIM-22: a warm read does not freeze age or old bytes.
        self.write(self.digest, s.bot())
        self.write(self.alp, s.alp())
        first = self.reader.snapshot(s.NOW)
        replacement = self.base / 'next.json'
        updated = s.bot()
        updated['snapshot']['yandex']['balance'] = -2
        self.write(replacement, updated)
        replacement.replace(self.digest)
        second = self.reader.snapshot(s.NOW + 2700)
        old = next(item for item in first if item['provider'] == 'yandex')
        new = next(item for item in second if item['provider'] == 'yandex')
        self.assertEqual((old['status'], old['prepaid']['balance']), ('ok', 9.25))
        self.assertEqual((new['status'], new['prepaid']['balance'], new['age_seconds']), ('stale', -2, 2720))

    def test_native_failures_leave_typed_fallback_and_file_sources_on_cold_and_warm_reads(self):
        # INV-WLIM-20: repeated native errors do not hide independently read caches.
        from unittest.mock import patch
        class BrokenChat:
            def limits_overview(self):
                raise RuntimeError(s.PRIVATE)
        self.write(self.digest, s.bot())
        backend = self.module.RegistryBackend(str(self.base), str(self.base), sessions=BrokenChat(),
                                              cached_limits_reader=self.reader)
        for now in (s.NOW, s.NOW + 2700):
            with self.subTest(now=now), patch.object(self.module.time, 'time', return_value=now):
                result = backend.limits_overview()
                self.assertEqual(result['schema'], 2)
                self.assertEqual(result['server_now'], now)
                self.assertEqual(result['native']['schema'], 1)
                self.assertEqual({item['provider'] for item in result['native']['sources']}, {'codex', 'claude'})
                self.assertTrue(all(item['status'] == 'unavailable' for item in result['native']['sources']))
                self.assertEqual(next(item for item in result['cached_sources'] if item['provider'] == 'kimi')['status'],
                                 'ok' if now == s.NOW else 'stale')
                self.assertNotIn(s.PRIVATE, json.dumps(result))

    def test_alp_observation_after_export_is_unavailable_without_hiding_other_sources(self):
        # INV-WLIM-23: collection cannot occur after its enclosing export.
        import limits_dashboard_blind_support as native
        class Chat:
            def limits_overview(self):
                return native.overview()
        self.write(self.digest, s.bot())
        account = s.alp_account(observed_at=s.stamp(s.NOW - 10))
        other = s.alp_account('claude', observed_at=s.stamp(s.NOW - 20))
        exported = s.alp(account, other)
        exported['exported_at'] = s.stamp(s.NOW - 20)
        self.write(self.alp, exported)
        backend = self.module.RegistryBackend(str(self.base), str(self.base), sessions=Chat(),
                                              cached_limits_reader=self.reader)
        result = backend.limits_overview()
        self.assertEqual(result['native'], native.overview())
        invalid = next(item for item in result['cached_sources'] if item['node_id'] == 'alp' and item['provider'] == 'codex')
        self.assertEqual((invalid['status'], invalid['reason'], invalid['windows']),
                         ('unavailable', 'invalid_snapshot', []))
        self.assertEqual((invalid['observed_at'], invalid['age_seconds'], invalid['observation_basis']),
                         (None, None, 'unknown'))
        self.assertEqual((invalid['identity'], invalid['account_ref']), ('collector_mapped', s.hashed()))
        healthy = [item for item in result['cached_sources'] if item is not invalid]
        self.assertEqual(len(healthy), 4)
        self.assertTrue(all(item['status'] == 'ok' for item in healthy))

    def test_cli_exposes_cache_paths_only_on_owner_broker_subcommand(self):
        # INV-WLIM-21: HTTP/web callers cannot choose owner file paths.
        cli = Path(__file__).resolve().parents[1] / 'bin' / 'ai-control-web'
        for command, expected in (('broker', True), ('web', False)):
            result = subprocess.run([str(cli), command, '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            for flag in ('--limits-digest-cache', '--limits-alp-cache'):
                self.assertEqual(flag in result.stdout, expected)


if __name__ == '__main__':
    unittest.main()
