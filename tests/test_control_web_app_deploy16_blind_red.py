#!/usr/bin/env python3
"""Independent INV-DEPLOY-12..19 contracts; synthetic signed bytes, no production IO.

Only public specs and the existing fixture's setup/public Deploy boundary were read.
A literal journal fixture is an independent oracle, not a call to internal validators.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy14_fixture', ROOT / 'tests/test-web-universal-deploy.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
AUTH = 'bin/_control_web_android_auth.py'
DOWNLOAD = 'bin/_control_web_android_download.py'
APP = (AUTH, DOWNLOAD)
FULL16 = {**fixture.MODES, AUTH: 0o644, DOWNLOAD: 0o644}


class Deploy16(unittest.TestCase):
    # Reuse only the narrow, accepted synthetic harness; do not inherit legacy tests.
    for _name in ('crypto', 'write', 'hashes', 'stops', 'runner', 'deploy', 'accepted', 'refused'):
        locals()[_name] = getattr(fixture.SignedDeploy, _name)

    def setUp(self):
        fixture.SignedDeploy.setUp(self)
        self.before14 = dict(self.current)
        self.before16 = {**self.before14, AUTH: b'# synthetic auth before\n', DOWNLOAD: b'# synthetic download before\n'}
        self.install_accepted(self.before14, 2, 7)

    def tree(self):
        return {p: (self.target / p).read_bytes() for p in FULL16
                if (self.target / p).is_file() and not (self.target / p).is_symlink()}

    def state_value(self, files, schema, number, digest='a' * 64):
        return dict(schema=schema, release_id=number, manifest_sha256=digest, files=self.hashes(files))

    def install_accepted(self, files, schema, number):
        for p, data in files.items():
            self.write(self.target / p, data, FULL16[p])
        value = self.state_value(files, schema, number)
        # Preserve deliberately noncanonical raw state across rollback.
        self.write(self.state, json.dumps(value, indent=2).encode() + b'\n', 0o600)
        self.initial_state = self.state.read_bytes()
        return value

    def release(self, number=8, files=None, base=None, **kwargs):
        return fixture.SignedDeploy.release(self, number, self.before16 if files is None else files,
            self.before14 if base is None else base, manifest_changes={'schema': 3}, **kwargs)

    def signed(self, files, number=8, base=None):
        # Existing fixture defaults new unknown paths to0644, as required here.
        return self.release(number, files, base)

    def journal(self, before, before_schema, after, accepted_after=False):
        shutil.rmtree(self.checkpoints / "release-independent16", ignore_errors=True)
        for p in APP:
            if os.path.lexists(self.target / p):
                (self.target / p).unlink()
        self.calls.clear()
        self.install_accepted(before, before_schema, 7)
        raw_before = self.state.read_bytes()
        before_state = json.loads(raw_before)
        after_state = self.state_value(after, 3, 8, 'b' * 64)
        checkpoint = self.checkpoints / 'release-independent16'
        checkpoint.mkdir(mode=0o700)
        for p, data in before.items():
            self.write(checkpoint / Path(p).name, data, 0o600)
        self.write(checkpoint / 'accepted.json', raw_before, 0o600)
        journal = dict(schema=3, before=before_state, after=after_state, checkpoint=checkpoint.name)
        self.write(self.checkpoints / 'pending.json', json.dumps(journal).encode(), 0o600)
        if accepted_after:
            self.write(self.state, json.dumps(after_state).encode(), 0o600)
        # Invalid signature prevents a new deployment after recovery has finished.
        self.signed(after, base=before)
        (self.stage / 'release.sig').write_bytes(bytes(64))
        return raw_before

    def run_recovery(self):
        with self.assertRaises(self.api.Rejected):
            self.deploy().run()

    def changed16(self):
        return {p: data + b'\n# independently signed after\n' for p, data in self.before16.items()}

    def test_exact16_modes_and_signed_state3(self):
        # INV-DEPLOY-12 / INV-DEPLOY-13
        self.assertEqual(self.api.MODES, FULL16)
        self.signed(self.before16)
        self.accepted(dict(result='installed', release_id=8))
        value = json.loads(self.state.read_bytes())
        self.assertEqual(set(value), {'schema', 'release_id', 'manifest_sha256', 'files'})
        self.assertEqual(value['schema'], 3)
        self.assertEqual(value['files'], self.hashes(self.before16))
        self.assertEqual(value['manifest_sha256'], fixture.sha((self.stage / 'release.json').read_bytes()))

    def test_first16_base14_healthy_repeat_and_two_forward16_releases(self):
        # INV-DEPLOY-13: same-ID comparison must precede historical base comparison.
        self.signed(self.before16)
        self.accepted(dict(result='installed', release_id=8))
        raw = self.state.read_bytes()
        self.calls.clear()
        self.accepted(dict(result='already_installed', release_id=8))
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertFalse(self.stops())
        self.assertFalse(any(c[1] == 'start' for c in self.calls))
        current = self.before16
        for number in (9, 10):
            after = dict(current)
            after[AUTH] += str(number).encode()
            after[DOWNLOAD] += str(number).encode()
            self.signed(after, number, current)
            self.accepted(dict(result='installed', release_id=number))
            self.assertEqual(self.hashes(self.tree()), self.hashes(after))
            self.accepted(dict(result='already_installed', release_id=number))
            current = after
        self.assertEqual(fixture.sha(fixture.SOURCE.read_bytes()), self.helper_hash)

    def test_same_id_unhealthy_is_refusal_without_repair(self):
        # INV-DEPLOY-13
        self.signed(self.before16)
        self.accepted(dict(result='installed', release_id=8))
        self.calls.clear()
        self.unhealthy = True
        self.refused()
        self.assertFalse(any(c[1] == 'start' for c in self.calls))

    def test_absence_of_each_new_leaf_is_required_before_any_stop(self):
        # INV-DEPLOY-14: even bytes equal to after are drift.
        for p in APP:
            with self.subTest(path=p):
                self.write(self.target / p, self.before16[p])
                self.signed(self.before16)
                self.refused()
                (self.target / p).unlink()

    def test_14_to_16_all_four_interrupted_presence_pairs_restore_raw14(self):
        # INV-DEPLOY-15 / INV-DEPLOY-16
        for present in ((), (AUTH,), (DOWNLOAD,), APP):
            with self.subTest(present=present):
                raw = self.journal(self.before14, 2, self.before16)
                for p in present:
                    self.write(self.target / p, self.before16[p])
                self.run_recovery()
                self.assertEqual(self.state.read_bytes(), raw)
                self.assertEqual(self.hashes(self.tree()), self.hashes(self.before14))
                for p in APP:
                    self.assertFalse(os.path.lexists(self.target / p))
                self.assertFalse((self.checkpoints / 'pending.json').exists())

    def test_16_to_16_all_app_before_after_pairs_and_old_leaf_mix_restore16(self):
        # INV-DEPLOY-15 / INV-DEPLOY-16
        after = self.changed16()
        for mask in range(4):
            with self.subTest(mask=mask):
                raw = self.journal(self.before16, 3, after)
                for i, p in enumerate(APP):
                    self.write(self.target / p, (after if mask & (1 << i) else self.before16)[p])
                self.write(self.target / 'bin/_control_web.css', after['bin/_control_web.css'])
                self.run_recovery()
                self.assertEqual(self.hashes(self.tree()), self.hashes(self.before16))
                self.assertEqual(self.state.read_bytes(), raw)
                self.assertFalse((self.checkpoints / 'pending.json').exists())

    def test_before16_missing_app_is_drift_and_retains_evidence(self):
        # INV-DEPLOY-15
        self.journal(self.before16, 3, self.changed16())
        (self.target / AUTH).unlink()
        self.refused()
        self.assertTrue((self.checkpoints / 'pending.json').exists())

    def test_unknown_app_hash_and_metadata_drift_retain_journal_without_repair(self):
        # INV-DEPLOY-15 / INV-DEPLOY-16
        self.journal(self.before14, 2, self.before16)
        self.write(self.target / DOWNLOAD, b'unrecognized bytes')
        self.refused()
        pending = (self.checkpoints / 'pending.json').read_bytes()
        self.write(self.target / DOWNLOAD, self.before16[DOWNLOAD], 0o600)
        self.refused()
        self.assertEqual((self.target / DOWNLOAD).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.checkpoints / 'pending.json').read_bytes(), pending)

    def test_accepted_after_exact_tree_finalizes_before_same_id_stage_check(self):
        # INV-DEPLOY-16: pending processing precedes same-ID no-op/signature checks.
        self.journal(self.before14, 2, self.before16, accepted_after=True)
        for p, data in self.before16.items():
            self.write(self.target / p, data, FULL16[p])
        raw_after = self.state.read_bytes()
        self.run_recovery()
        self.assertFalse((self.checkpoints / 'pending.json').exists())
        self.assertEqual(self.state.read_bytes(), raw_after)
        self.assertEqual(self.hashes(self.tree()), self.hashes(self.before16))
        self.assertFalse(self.stops())

    def test_accepted_after_unhealthy_pending_rolls_back_once_and_retains_on_failure(self):
        # INV-DEPLOY-16: published provisional after may roll back, bounded to one attempt.
        self.journal(self.before14, 2, self.before16, accepted_after=True)
        for p, data in self.before16.items():
            self.write(self.target / p, data, FULL16[p])
        self.unhealthy = True
        with self.assertRaises((self.api.Rejected, self.api.RollbackFailed)):
            self.deploy().run()
        self.assertTrue((self.checkpoints / 'pending.json').exists())
        self.assertLessEqual(sum(c[1] in ('stop', 'start', 'show', 'is-active') for c in self.calls), 16)
        self.assertLessEqual(sum(c[1] == 'start' for c in self.calls), 2)
        self.assertEqual(self.hashes(self.tree()), self.hashes(self.before14))

    def test_pending_recovery_consumes_single_rollback_budget_before_new_install_failure(self):
        # INV-DEPLOY-16: recovery consumes the single rollback budget for this invocation.
        raw = self.journal(self.before14, 2, self.before16)
        self.write(self.target / AUTH, self.before16[AUTH])
        # A subsequent authorized transaction may start, but cannot trigger a second rollback.
        self.signed(self.before16)
        original = self.runner
        starts = []
        def fail_only_if_second_transaction_starts(args):
            value = original(args)
            if args[1] == 'start':
                starts.append(args[2])
                if len(starts) == 3:
                    raise RuntimeError('synthetic staged-install start failure after completed recovery')
            return value
        self.runner = fail_only_if_second_transaction_starts
        caught = None
        try:
            self.deploy().run()
        except Exception as exc:
            caught = exc
        self.assertEqual(len(starts), 3, 'Invocation attempted a second rollback after consuming its budget')
        self.assertIsInstance(caught, self.api.RollbackFailed, 'Budget exhaustion must be explicit and retained')
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertEqual(self.hashes(self.tree()), self.hashes(self.before16))
        pending = self.checkpoints / 'pending.json'
        self.assertTrue(pending.exists(), 'Exhausted rollback budget discarded the new pending transaction')
        journal = json.loads(pending.read_bytes())
        self.assertEqual(journal['before'], json.loads(raw))
        self.assertEqual(journal['after']['files'], self.hashes(self.before16))
        self.assertTrue((self.checkpoints / journal['checkpoint']).is_dir())

    def test_recovery_timeout_retains_pending_and_never_retries_start(self):
        # INV-DEPLOY-16 / DESIGN M4: stop2 + start2 + health6 <=10 total calls.
        self.journal(self.before14, 2, self.before16)
        for p in APP:
            self.write(self.target / p, self.before16[p])
        original = self.runner
        def timeout_first_start(args):
            result = original(args)
            if args[1] == 'start':
                raise subprocess.TimeoutExpired('/usr/bin/systemctl', 40)
            return result
        self.runner = timeout_first_start
        with self.assertRaises((self.api.Rejected, self.api.RollbackFailed)):
            self.deploy().run()
        self.assertTrue((self.checkpoints / 'pending.json').exists())
        self.assertEqual(sum(c[1] == 'start' for c in self.calls), 1)
        self.assertLessEqual(len(self.calls), 10)
        self.assertEqual(self.hashes(self.tree()), self.hashes(self.before14))

    def test_bootstrap_or_config_marker_blocks_even_valid_signed16(self):
        # INV-DEPLOY-17 / INV-DEPLOY-18: malformed marker is a guard, not authorization.
        for name in ('bootstrap-pending.json', 'config-pending.json'):
            with self.subTest(marker=name):
                marker = self.state.parent / name
                self.write(marker, b'{malformed', 0o600)
                self.signed(self.before16)
                self.refused()
                self.assertEqual(marker.read_bytes(), b'{malformed')
                marker.unlink()

    def test_signed_payload_uses_verified_snapshot_despite_owner_stage_swap(self):
        # INV-DEPLOY-12 / INV-DEPLOY-13: signature covers exact saved bytes.
        self.signed(self.before16)
        original = self.runner
        swapped = []
        def swap_after_verification(args):
            if args[1] == 'stop' and not swapped:
                for p in APP:
                    (self.stage / p).write_bytes(b'unsigned replacement')
                swapped.append(True)
            return original(args)
        self.runner = swap_after_verification
        self.accepted(dict(result='installed', release_id=8))
        self.assertEqual(swapped, [True])
        self.assertEqual(self.hashes(self.tree()), self.hashes(self.before16))

    def test_install_renames_every_leaf_in_fixed16_order(self):
        # INV-DEPLOY-14: atomic individual leaves, fixed table order.
        self.signed(self.changed16())
        real_replace = os.replace
        installed = []
        def observed_replace(source, destination, *args, **kwargs):
            path = Path(destination)
            if not path.is_absolute() and kwargs.get('dst_dir_fd') is not None:
                path = Path(os.readlink('/proc/self/fd/' + str(kwargs['dst_dir_fd']))) / path
            result = real_replace(source, destination, *args, **kwargs)
            if path.is_relative_to(self.target):
                installed.append(str(path.relative_to(self.target)))
            return result
        with patch('os.replace', side_effect=observed_replace):
            self.accepted(dict(result='installed', release_id=8))
        self.assertEqual(installed, list(FULL16))

    def test_higher_id_historical_base14_is_refused_after16(self):
        # INV-DEPLOY-13: first-repeat exception cannot authorize a later stale base.
        self.signed(self.before16)
        self.accepted(dict(result='installed', release_id=8))
        self.signed(self.changed16(), 9, self.before14)
        self.refused()

    def test_accepted_after_mixed16_tree_rolls_back_to_before16(self):
        # INV-DEPLOY-16: provisional accepted-after is not a committed fence.
        after = self.changed16()
        raw = self.journal(self.before16, 3, after, accepted_after=True)
        self.write(self.target / AUTH, after[AUTH])
        self.run_recovery()
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertEqual(self.hashes(self.tree()), self.hashes(self.before16))
        self.assertFalse((self.checkpoints / 'pending.json').exists())

    def test_legacy_journal2_recovers14_with_new16_validator_and_bad_stage(self):
        # INV-DEPLOY-16: schema2 recovery must never enter the schema3-only map.
        raw = self.journal(self.before14, 2, self.before16)
        pending = self.checkpoints / 'pending.json'
        journal = json.loads(pending.read_bytes())
        after14 = dict(self.before14)
        after14['bin/_control_web.css'] += b'known legacy after'
        journal['schema'] = 2
        journal['after'] = self.state_value(after14, 2, 8, 'b' * 64)
        pending.write_bytes(json.dumps(journal).encode())
        self.write(self.target / 'bin/_control_web.css', after14['bin/_control_web.css'])
        self.run_recovery()
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertEqual(self.hashes(self.tree()), self.hashes(self.before14))
        self.assertFalse(pending.exists())
        for p in APP:
            self.assertFalse(os.path.lexists(self.target / p))


class AcceptedR5ConfigCompatibility(unittest.TestCase):
    def test_pinned_old14_extended_config_startup_login_ttl_and_preservation(self):
        # INV-DEPLOY-18: old accepted source, never the new app implementation.
        from fastapi.testclient import TestClient
        prior = os.umask(0o077)
        self.addCleanup(os.umask, prior)
        temporary = tempfile.TemporaryDirectory(prefix='deploy16-pinned-r5-', dir='/var/tmp')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        pin = '0ea544756765c68ee3fea262a8a77ab4d4b8fe41'
        for relative in fixture.MODES:
            result = subprocess.run(['/usr/bin/git', '-C', str(ROOT), 'show', pin + ':' + relative],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, 'Pinned accepted R5 artifact unavailable: ' + relative)
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(result.stdout)
        module_spec = importlib.util.spec_from_file_location('pinned_deploy16_r5_web', root / 'bin/_control_web.py')
        web = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(web)
        now = [1800000000]
        replay = root / 'synthetic-replay.json'
        replay.write_text('{"last_step":-1}')
        replay.chmod(0o600)
        password, secret = 'deploy16-synthetic-password', 'JBSWY3DPEHPK3PXP'
        config = dict(username='dwl', origin='https://control.example.test',
            password_hash=web.hash_password(password), totp_secret=secret,
            session_ttl=10800, secure_cookie=True, totp_state_path=str(replay),
            android_auth_db='/var/lib/ai-control-web/android-auth/device-grants.sqlite3',
            android_download_dir='/srv/ai-control-download/android',
            unknown_nested={'preserve': [True, None, 7, 'exact']})
        expected = copy.deepcopy(config)
        class Backend:
            def snapshot(self):
                return {'tasks': []}
        with TestClient(web.create_app(config, Backend(), clock=lambda: now[0]),
                        base_url=config['origin']) as client:
            self.assertEqual(client.get('/api/tasks').status_code, 401)
            response = client.post('/api/login', json={'username': 'dwl', 'password': password,
                'totp': web.totp_code(secret, now[0])}, headers={'Origin': config['origin']})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get('/api/tasks').status_code, 200)
            now[0] += 10799
            self.assertEqual(client.get('/api/tasks').status_code, 200)
            now[0] += 2
            self.assertEqual(client.get('/api/tasks').status_code, 401)
        self.assertEqual(config, expected)
        self.assertEqual(json.loads(replay.read_text())['last_step'], 1800000000 // 30)


if __name__ == '__main__':
    unittest.main()
