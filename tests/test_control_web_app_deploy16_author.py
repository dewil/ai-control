"""Author fault probes supplement the immutable independent contract suites."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import test_control_web_app_deploy16_blind_red as core
import test_control_web_app_deploy16_operations_blind_red as ops


class RecoveryProbes(core.Deploy16):
    # Inherited independent tests also execute, but are not counted as new coverage.
    historical_fresh16_tests = core.Deploy16.historical_fresh16_tests | {
        'test_same_instance_new_invocation_recovers_retained_budget_exhaustion',
    }
    def test_current_helper_legacy13_recovery_pairs_preserve_all_absences(self):
        # INV-DEPLOY-16: exercise actual new helper, including state-zero semantics.
        for schema in (1, 2):
            for present in (False, True):
                if schema == 1 and present:
                    continue
                with self.subTest(schema=schema, configured_present=present):
                    for p in set(core.FULL16) - set(core.fixture.LEGACY_MODES):
                        (self.target / p).unlink(missing_ok=True)
                    before = dict(self.base)
                    raw = self.api.encode(dict(schema=1, release_id=0, manifest_sha256=None,
                                               files=self.hashes(before))) + b'\n'
                    self.write(self.state, raw, 0o600)
                    after = dict(self.current if schema == 2 else self.base)
                    after['bin/_control_web.css'] += b'legacy signed after'
                    after_state = self.state_value(after, schema, 1)
                    checkpoint = self.checkpoints / ('legacy-' + str(schema) + str(present))
                    checkpoint.mkdir(mode=0o700)
                    for p, data in before.items():
                        self.write(checkpoint / Path(p).name, data, 0o600)
                    self.write(checkpoint / 'accepted.json', raw, 0o600)
                    value = dict(schema=schema, before=json.loads(raw), after=after_state,
                                 checkpoint=checkpoint.name)
                    self.write(self.checkpoints / 'pending.json', json.dumps(value).encode(), 0o600)
                    self.write(self.target / 'bin/_control_web.css', after['bin/_control_web.css'])
                    if present:
                        self.write(self.target / core.fixture.NEW_LEAF, after[core.fixture.NEW_LEAF])
                    self.release()
                    (self.stage / 'release.sig').write_bytes(bytes(64))
                    self.run_recovery()
                    self.assertEqual(self.state.read_bytes(), raw)
                    self.assertEqual(self.tree(), before)
                    self.assertFalse((self.checkpoints / 'pending.json').exists())

    def test_actual_pending_state_schema_pair_and_checkpoint_validation(self):
        # INV-DEPLOY-16: unknown schemas/pairs preserve every byte and journal.
        for change in ('version', 'pair', 'checkpoint'):
            with self.subTest(change=change):
                self.journal(self.before14, 2, self.before16)
                path = self.checkpoints / 'pending.json'
                value = json.loads(path.read_bytes())
                if change == 'version':
                    value['schema'] = 4
                elif change == 'pair':
                    value['schema'] = 2
                else:
                    value['checkpoint'] = '../escaped'
                path.write_text(json.dumps(value))
                raw = path.read_bytes()
                self.refused()
                self.assertEqual(path.read_bytes(), raw)

    def test_old_and_new_controller_share_exact_flock_inode(self):
        # INV-DEPLOY-17: old4ead serializes new controller using checkpoints/lock.
        lock = self.checkpoints / 'lock'
        self.write(lock, b'', 0o600)
        import fcntl
        fd = os.open(lock, os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        status_read, status_write = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(fd)
            os.close(status_read)
            try:
                self.release()
                (self.stage / 'release.sig').write_bytes(bytes(64))
                self.deploy().run()
            except self.api.Rejected:
                os.write(status_write, b'refused-after-lock')
            finally:
                os._exit(0)
        os.close(status_write)
        try:
            import select
            self.assertEqual(select.select([status_read], [], [], 0.15)[0], [])
            fcntl.flock(fd, fcntl.LOCK_UN)
            self.assertTrue(select.select([status_read], [], [], 4)[0])
            self.assertEqual(os.read(status_read, 100), b'refused-after-lock')
            _, status = os.waitpid(child, 0)
            self.assertEqual(os.WEXITSTATUS(status), 0)
        finally:
            os.close(fd)
            os.close(status_read)

    def test_same_instance_new_invocation_recovers_retained_budget_exhaustion(self):
        # INV-DEPLOY-16: exhaustion does not silently reset until next invocation.
        raw = self.journal(self.before14, 2, self.before16)
        self.write(self.target / core.AUTH, self.before16[core.AUTH])
        self.signed(self.before16)
        original = self.runner
        starts = []
        def fail_third_start(args):
            result = original(args)
            if args[1] == 'start':
                starts.append(args[2])
                if len(starts) == 3:
                    raise RuntimeError('synthetic one-time new install failure')
            return result
        self.runner = fail_third_start
        controller = self.deploy()
        with self.assertRaises(self.api.RollbackFailed):
            controller.run()
        self.assertEqual(len(starts), 3)
        self.assertTrue(controller.rollback_used)
        self.assertTrue(controller.pending.exists())
        self.assertEqual(self.state.read_bytes(), raw)
        (self.stage / 'release.sig').write_bytes(bytes(64))
        with self.assertRaises(self.api.Rejected):
            controller.run()
        self.assertEqual(len(starts), 5)
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertEqual(self.tree(), self.before14)
        self.assertFalse(controller.pending.exists())
        with self.assertRaises(self.api.Rejected):
            controller.run()
        self.assertEqual(len(starts), 5)
        self.assertFalse(controller.rollback_used)

    def test_rollback_validation_failure_consumes_budget_before_sideeffects(self):
        # INV-DEPLOY-16/20: only a pending transaction can exercise rollback validation.
        raw = self.journal(self.before14, 2, self.before16)
        pending = self.checkpoints / 'pending.json'
        pending_raw = pending.read_bytes()
        journal = json.loads(pending_raw)
        before_tree = self.tree()
        controller = self.deploy()
        calls = []
        def unknown_tree(*args):
            calls.append(True)
            raise self.api.Rejected('synthetic unknown tree')
        controller.interrupted_tree = unknown_tree
        for _ in range(2):
            with self.assertRaises(self.api.RollbackFailed):
                controller.rollback(journal['before'], self.before14, journal['after'], raw)
            self.assertTrue(controller.rollback_used)
            self.assertEqual(self.state.read_bytes(), raw)
            self.assertEqual(self.tree(), before_tree)
            self.assertEqual(pending.read_bytes(), pending_raw)
        self.assertEqual(calls, [True])
        self.assertFalse(self.calls)


class BootstrapProbes(ops.BootstrapContracts):
    def test_kill_after_marker_and_after_helper_replace_recover(self):
        # INV-DEPLOY-17: retained durable proof reauthorizes only reviewed bytes.
        for boundary in ('marker', 'helper'):
            with self.subTest(boundary=boundary):
                self.prepare('ai-control-app-bootstrap.py')
                genuine = os.replace
                class Crash(BaseException):
                    pass
                def killed(source, destination, *args, **kwargs):
                    path = Path(destination)
                    if not path.is_absolute():
                        path = Path(os.readlink('/proc/self/fd/' + str(kwargs['dst_dir_fd']))) / path
                    result = genuine(source, destination, *args, **kwargs)
                    if path == self.paths['BOOTSTRAP_MARKER'] and boundary == 'marker':
                        raise Crash()
                    if path == self.paths['HELPER'] and boundary == 'helper':
                        raise Crash()
                    return result
                with patch('os.replace', side_effect=killed), self.assertRaises(Crash):
                    self.op.bootstrap()
                self.assertTrue(self.paths['BOOTSTRAP_MARKER'].exists())
                state = self.state.read_bytes()
                self.op.bootstrap()
                self.assertFalse(self.paths['BOOTSTRAP_MARKER'].exists())
                self.assertEqual(self.state.read_bytes(), state)
                self.assertEqual(self.paths['HELPER'].read_bytes(), self.paths['NEW_HELPER'].read_bytes())
                self.op.bootstrap()

    def test_unknown_marker_checkpoint_and_hardlinked_candidate_are_preserved(self):
        # INV-DEPLOY-17
        self.paths['BOOTSTRAP_MARKER'].write_bytes(b'{"schema":7}')
        self.paths['BOOTSTRAP_MARKER'].chmod(0o600)
        self.refuse_without_mutation(self.op.bootstrap)
        self.paths['BOOTSTRAP_MARKER'].unlink()
        os.link(self.paths['NEW_HELPER'], self.root/'candidate-hardlink')
        self.refuse_without_mutation(self.op.bootstrap)

    def test_trust_key_reread_refuses_drift_before_helper_replacement(self):
        # INV-DEPLOY-17: durable marker never authorizes a changed trust anchor.
        genuine = self.op.write
        before = self.paths['HELPER'].read_bytes()
        def key_changed(path, *args):
            result = genuine(path, *args)
            if path == self.paths['BOOTSTRAP_MARKER']:
                self.paths['KEY'].write_bytes(b'changed synthetic trust anchor')
            return result
        self.op.write = key_changed
        with self.assertRaises(ValueError):
            self.op.bootstrap()
        self.assertEqual(self.paths['HELPER'].read_bytes(), before)
        self.assertTrue(self.paths['BOOTSTRAP_MARKER'].exists())
        self.assertFalse(self.commands)


class ConfigProbes(ops.ConfigContracts):
    def prepare(self, filename):
        super().prepare(filename)
        # Normative metadata; frozen writer fixes the same umask fixture separately.
        self.paths['CATALOG_ROOT'].chmod(0o755)
        self.paths['CATALOG'].chmod(0o750)

    def test_kill_after_config_replace_recovers_with_private_before_and_grants(self):
        # INV-DEPLOY-18: successful provisional config finalized, grants untouched.
        self.write(self.paths['AUTH_DB'], b'original runtime grant bytes', 0o600)
        genuine = os.replace
        class Crash(BaseException):
            pass
        def killed(source, destination, *args, **kwargs):
            path = Path(destination)
            if not path.is_absolute():
                path = Path(os.readlink('/proc/self/fd/' + str(kwargs['dst_dir_fd']))) / path
            result = genuine(source, destination, *args, **kwargs)
            if path == self.paths['AUTH_CONFIG']:
                raise Crash()
            return result
        with patch('os.replace', side_effect=killed), self.assertRaises(Crash):
            self.op.configure()
        self.assertTrue(self.paths['CONFIG_MARKER'].exists())
        # Model service state after process kill, without relying on fake runtime repair.
        self.service_active = True
        self.op.configure()
        self.assertFalse(self.paths['CONFIG_MARKER'].exists())
        self.assertEqual(self.paths['AUTH_DB'].read_bytes(), b'original runtime grant bytes')
        proofs = list(self.paths['CONFIG_CHECKPOINTS'].glob('operation-*'))
        self.assertEqual((proofs[0]/'auth.before').read_bytes(), self.auth_raw)

    def test_effective_unit_refusal_and_identity_drift_precede_stop(self):
        # INV-DEPLOY-18
        original = self.op.run_command
        def changed(argv, *, timeout=40):
            result = original(argv, timeout=timeout)
            if 'ProtectSystem' in argv:
                return subprocess.CompletedProcess(argv, 0, stdout='no\n', stderr='')
            return result
        self.op.run_command = changed
        self.refuse_without_mutation(self.op.configure)
        self.assertFalse([c for c in self.commands if c[1] == 'stop'])
        self.op.run_command = original
        self.op.account_identity = lambda name: (os.getuid()+1, os.getgid())
        self.refuse_without_mutation(self.op.configure)
    def test_rollback_requires_inactive_before_any_restore_write(self):
        # INV-DEPLOY-18: failed stop proof retains after/marker instead of racing writers.
        original = self.op.run_command
        rollback_started = []
        def unsafe_restart(argv, *, timeout=40):
            if argv[1] == 'start':
                rollback_started.append(True)
                raise subprocess.TimeoutExpired(argv[0], 40)
            result = original(argv, timeout=timeout)
            if rollback_started and argv[1] == 'is-active':
                return subprocess.CompletedProcess(argv, 0, stdout='active\n', stderr='')
            return result
        self.op.run_command = unsafe_restart
        with self.assertRaises(ValueError):
            self.op.configure()
        expected = self.config | {'android_auth_db': str(self.paths['AUTH_DB']),
                                  'android_download_dir': str(self.paths['CATALOG'])}
        self.assertEqual(json.loads(self.paths['AUTH_CONFIG'].read_bytes()), expected)
        self.assertTrue(self.paths['CONFIG_MARKER'].exists())
        self.assertEqual(len(rollback_started), 1)


class Config16Probes(ops.OperationsFixture):
    def setUp(self):
        self.prepare('ai-control-app-config.py')
        self.write(self.paths['HELPER'], self.paths['NEW_HELPER'].read_bytes(), 0o755)
        self.install_accepted(self.before16, 3, 6)
        self.op.EXPECTED_ACCEPTED_SHA256 = ops.fixture.sha(self.state.read_bytes())
        self.write(self.paths['AUTH_DB'], b'unchanged persistent grants', 0o600)

    def test_exact16_wrongmode_and_extra_map_are_refused_without_repair(self):
        leaf = self.target/core.AUTH
        leaf.chmod(0o755)
        self.refuse_without_mutation(self.op.accepted_package)
        self.assertEqual(leaf.stat().st_mode & 0o777, 0o755)
        leaf.chmod(0o644)
        state = json.loads(self.state.read_bytes())
        state['files']['bin/unreviewed'] = 'a'*64
        self.state.write_bytes(json.dumps(state).encode())
        self.op.EXPECTED_ACCEPTED_SHA256 = ops.fixture.sha(self.state.read_bytes())
        self.refuse_without_mutation(self.op.accepted_package)
        self.assertFalse(self.commands)

    def test_bootstrap_still_refuses_accepted16_before_service_mutation(self):
        source = ops.fixture.ROOT/'deployment/ai-control-app-bootstrap.py'
        spec = importlib.util.spec_from_file_location('author_strict_bootstrap', source)
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        for name in ('TARGET','STATE','ROOT_UID','ROOT_GID','EXPECTED_ACCEPTED_SHA256'):
            setattr(bootstrap, name, getattr(self.op, name))
        self.refuse_without_mutation(bootstrap.accepted14)
        self.assertFalse(self.commands)

    def test_known16_failed_rollback_then_separate_retry_preserves_before_replay_grants(self):
        protected = self.protected()
        replay = Path(self.config['totp_state_path']).read_bytes()
        def fail_start(argv):
            if argv[1] == 'start':
                raise subprocess.TimeoutExpired(argv[0], 40)
        self.command_failure = fail_start
        with self.assertRaises(ValueError):
            self.op.configure()
        self.assertEqual(self.paths['AUTH_CONFIG'].read_bytes(), self.auth_raw)
        self.assertTrue(self.paths['CONFIG_MARKER'].exists())
        self.command_failure = None
        self.op.configure()
        self.assertFalse(self.paths['CONFIG_MARKER'].exists())
        # This invocation completes recovery; a separate invocation performs migration.
        self.assertEqual(self.paths['AUTH_CONFIG'].read_bytes(), self.auth_raw)
        self.op.configure()
        self.assertEqual(json.loads(self.paths['AUTH_CONFIG'].read_bytes()), self.config | {
            'android_auth_db':str(self.paths['AUTH_DB']), 'android_download_dir':str(self.paths['CATALOG'])})
        self.assertEqual(Path(self.config['totp_state_path']).read_bytes(), replay)
        self.assertEqual(self.paths['AUTH_DB'].read_bytes(), b'unchanged persistent grants')
        for name in ('STATE','HELPER','KEY'):
            self.assertEqual(self.protected()[name], protected[name])


class PublisherProbes(ops.PublisherContracts):
    def prepare(self, filename):
        super().prepare(filename)
        self.paths['CATALOG_ROOT'].chmod(0o755)
        self.paths['CATALOG'].chmod(0o750)
        original = self.op.run_command
        def tools(argv, *, timeout=40):
            if Path(argv[0]).name in ('aapt', 'aapt2'):
                raw = Path(argv[-1]).read_bytes()
                code = 4 if raw.endswith(b'code4') else 3
                return subprocess.CompletedProcess(argv, 0, stdout=
                    "package: name='ru.dewil.aicontrol' versionCode='"+str(code)+"' versionName='0.1.2'\nminSdkVersion:'26'\n", stderr='')
            return original(argv, timeout=timeout)
        self.op.run_command = tools

    def test_monotonic_next_release_and_retained_before_cas_rollback(self):
        # INV-DEPLOY-19: N->N+1; only explicit verified CAS lowers server feed.
        first = self.publish()
        before = self.paths['FEED'].read_bytes()
        self.apk.write_bytes(self.apk.read_bytes()+b'code4')
        metadata = {'version_code': 4, 'sha256': self.op.digest(self.apk.read_bytes())}
        second = self.publish(**metadata)
        after = self.paths['FEED'].read_bytes()
        self.assertEqual(json.loads(after)['versionCode'], 4)
        self.assertIsNone(self.op.rollback(self.op.digest(after), second))
        self.assertEqual(self.paths['FEED'].read_bytes(), before)
        self.assertTrue((self.paths['CATALOG']/'ai-control-4.apk').exists())
        self.assertIsNone(self.op.rollback(self.op.digest(after), second))

    def test_kill_after_immutable_apk_and_after_feed_switch_recovers_exactly(self):
        # INV-DEPLOY-19: no early feed; after-switch verified exact no-op.
        class Crash(BaseException):
            pass
        original = self.op.retain_proof
        def kill_before_feed(*args):
            raise Crash()
        self.op.retain_proof = kill_before_feed
        with self.assertRaises(Crash):
            self.publish()
        self.assertFalse(self.paths['FEED'].exists())
        self.assertEqual((self.paths['CATALOG']/'ai-control-3.apk').read_bytes(), self.apk.read_bytes())
        self.op.retain_proof = original
        genuine = os.replace
        def kill_after_feed(source, destination, *args, **kwargs):
            path = Path(destination)
            if not path.is_absolute():
                path = Path(os.readlink('/proc/self/fd/'+str(kwargs['dst_dir_fd']))) / path
            result = genuine(source, destination, *args, **kwargs)
            if path == self.paths['FEED']:
                raise Crash()
            return result
        with patch('os.replace', side_effect=kill_after_feed), self.assertRaises(Crash):
            self.publish()
        after = self.paths['FEED'].read_bytes()
        self.publish()
        self.assertEqual(self.paths['FEED'].read_bytes(), after)
        self.assertGreaterEqual(len(list(self.paths['PUBLICATION_PROOFS'].glob('publication-*'))), 2)

    def test_metadata_signature_nonfinite_duplicate_and_unsafe_apk_refusals(self):
        # INV-DEPLOY-19
        genuine = self.op.run_command
        def wrong_signature(argv, *, timeout=40):
            if Path(argv[0]).name == 'apksigner':
                return subprocess.CompletedProcess(argv, 0, stdout='Signer #1 certificate SHA-256 digest: '+'f'*64+'\n', stderr='')
            return genuine(argv, timeout=timeout)
        self.op.run_command = wrong_signature
        self.refuse_without_mutation(self.publish)
        self.op.run_command = genuine
        os.link(self.apk, self.root/'linked-input.apk')
        self.refuse_without_mutation(self.publish)
        (self.root/'linked-input.apk').unlink()
        self.publish()
        actual = self.paths['FEED'].read_bytes()
        for raw in (actual.replace(b'"versionCode":3',b'"versionCode":3,"versionCode":3'),
                    actual.replace(b'"versionCode":3',b'"versionCode":NaN'), actual+b' trailing'):
            self.paths['FEED'].write_bytes(raw)
            self.refuse_without_mutation(self.publish)
        self.paths['FEED'].write_bytes(actual)

    def test_second_publisher_waits_same_catalog_lock(self):
        # INV-DEPLOY-19: flock covers snapshot/proof/immutable APK/feed switch.
        import fcntl
        import select
        self.write(self.paths['PUBLISH_LOCK'], b'', 0o600)
        fd = os.open(self.paths['PUBLISH_LOCK'], os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        read_end, write_end = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(fd)
            os.close(read_end)
            try:
                self.publish()
                os.write(write_end, b'published')
            finally:
                os._exit(0)
        os.close(write_end)
        try:
            self.assertEqual(select.select([read_end], [], [], 0.15)[0], [])
            self.assertFalse(self.paths['FEED'].exists())
            fcntl.flock(fd, fcntl.LOCK_UN)
            self.assertTrue(select.select([read_end], [], [], 4)[0])
            self.assertEqual(os.read(read_end, 100), b'published')
            _, status = os.waitpid(child, 0)
            self.assertEqual(os.WEXITSTATUS(status), 0)
        finally:
            os.close(fd)
            os.close(read_end)


if __name__ == '__main__':
    unittest.main()
