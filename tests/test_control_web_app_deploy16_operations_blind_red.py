"""Frozen public operations tests. Missing modules are AVAILABILITY RED only.

Behavioral assertions below must execute after source author supplies artifacts;
core deployment RED and pinned compatibility are in the adjacent blind suite.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_control_web_app_deploy16_blind_red as core
fixture = core.fixture

CERT = 'baa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce'


class OperationsFixture(unittest.TestCase):
    for _name in ('crypto', 'write', 'hashes', 'stops', 'runner', 'deploy', 'accepted', 'refused',
                  'tree', 'state_value', 'install_accepted'):
        locals()[_name] = getattr(core.Deploy16, _name)

    def prepare(self, filename):
        source = fixture.ROOT / 'deployment' / filename
        self.assertTrue(source.is_file(), 'AVAILABILITY ONLY: missing frozen public operation ' + filename)
        spec = importlib.util.spec_from_file_location('blind_op_' + filename.replace('-', '_'), source)
        self.op = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.op
        spec.loader.exec_module(self.op)
        core.Deploy16.setUp(self)
        self.paths = dict(TARGET=self.target, STATE=self.state, KEY=self.key,
            HELPER=self.root/'helper/ai-control-deploy', NEW_HELPER=self.root/'owner/candidate.py',
            LOCK=self.checkpoints/'lock', PACKAGE_PENDING=self.checkpoints/'pending.json',
            BOOTSTRAP_MARKER=self.state.parent/'bootstrap-pending.json',
            BOOTSTRAP_CHECKPOINTS=self.state.parent/'bootstrap-checkpoints',
            CONFIG_MARKER=self.state.parent/'config-pending.json',
            CONFIG_CHECKPOINTS=self.state.parent/'config-checkpoints',
            AUTH_CONFIG=self.root/'private-web/auth.json',
            AUTH_DB=self.root/'private-web/android-auth/device-grants.sqlite3',
            CATALOG_ROOT=self.root/'srv', CATALOG=self.root/'srv/android',
            FEED=self.root/'srv/android/version.json', PUBLISH_LOCK=self.root/'srv/android/.publish.lock',
            PUBLICATION_PROOFS=self.root/'private-publication')
        uid, gid = os.getuid(), os.getgid()
        for key, value in self.paths.items():
            if hasattr(self.op, key):
                setattr(self.op, key, value)
        for key, value in dict(ROOT_UID=uid, ROOT_GID=gid, OWNER_UID=uid, OWNER_GID=gid,
                              PANEL_UID=uid, PANEL_GID=gid).items():
            self.assertTrue(hasattr(self.op, key), 'Frozen identity constant absent: ' + key)
            setattr(self.op, key, value)
        self.op.account_identity = lambda name: (uid, gid)
        self.write(self.paths['HELPER'], fixture.SOURCE.read_bytes(), 0o755)
        self.write(self.paths['NEW_HELPER'], fixture.SOURCE.read_bytes()+b'\n# synthetic reviewed candidate\n', 0o755)
        self.paths['CATALOG_ROOT'].mkdir(mode=0o755)
        self.paths['CATALOG_ROOT'].chmod(0o755)
        self.paths['CATALOG'].mkdir(mode=0o750)
        self.paths['CATALOG'].chmod(0o750)
        self.assertEqual(self.paths['CATALOG_ROOT'].stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.paths['CATALOG'].stat().st_mode & 0o777, 0o750)
        self.paths['PUBLICATION_PROOFS'].mkdir(mode=0o700)
        self.config = dict(username='dwl', session_ttl=10800, origin='https://control.example.test',
            password_hash='synthetic unchanged hash', totp_secret='synthetic unchanged TOTP',
            totp_state_path=str(self.root/'private-web/replay.json'), secure_cookie=True,
            unknown={'nested': [1, None, False]})
        self.auth_raw = json.dumps(self.config, indent=2).encode()+b'\n'
        self.write(self.paths['AUTH_CONFIG'], self.auth_raw, 0o600)
        self.write(Path(self.config['totp_state_path']), b'{"last_step":60000000}', 0o600)
        pins = dict(EXPECTED_OLD_HELPER_SHA256=fixture.sha(self.paths['HELPER'].read_bytes()),
            EXPECTED_NEW_HELPER_SHA256=fixture.sha(self.paths['NEW_HELPER'].read_bytes()),
            EXPECTED_ACCEPTED_SHA256=fixture.sha(self.state.read_bytes()),
            EXPECTED_KEY_SHA256=fixture.sha(self.key.read_bytes()),
            EXPECTED_AUTH_SHA256=fixture.sha(self.auth_raw), EXPECTED_CERTIFICATE_SHA256=CERT)
        for name, value in pins.items():
            if hasattr(self.op, name):
                setattr(self.op, name, value)
        # Bootstrap/config reuse the durable existing accepted-R5 flock inode.
        self.write(self.paths['LOCK'], b'', 0o600)
        self.commands = []
        self.service_active = True
        self.after_stop = None
        self.command_failure = None
        self.op.run_command = self.command

    def command(self, argv, *, timeout=40):
        self.assertEqual(timeout, 40)
        self.assertIsInstance(argv, list)
        self.commands.append(list(argv))
        if self.command_failure:
            self.command_failure(argv)
        if Path(argv[0]).name == 'systemctl':
            self.assertIn(argv[1], ('show', 'is-active', 'stop', 'start'))
            self.assertTrue(any(s in argv for s in fixture.SERVICES))
            if argv[1] == 'stop':
                self.service_active = False
                if self.after_stop:
                    self.after_stop(argv)
            if argv[1] == 'start':
                self.service_active = True
            if argv[1] == 'is-active':
                return subprocess.CompletedProcess(argv, 0 if self.service_active else 3,
                    stdout='active\n' if self.service_active else 'inactive\n', stderr='')
            if argv[1] == 'show':
                frontend = fixture.SERVICES[0] in argv
                # Accepted R5 templates have distinct confinement contracts. The
                # broker owns native runtime writers and retains the R5 full/no profile.
                props = {'User': 'ai-panel' if frontend else 'dwl', 'Group': 'ai-panel',
                    'ProtectSystem': 'strict' if frontend else 'full',
                    'ProtectHome': 'yes' if frontend else 'no',
                    'ReadWritePaths': str(self.paths['AUTH_CONFIG'].parent) if frontend else '',
                    'InaccessiblePaths': '/data' if frontend else ''}
                requested = [argv[i+1] for i, x in enumerate(argv[:-1]) if x in ('-p', '--property')]
                output = '\n'.join(props.get(p, '') if '--value' in argv else p+'='+props.get(p, '') for p in requested)
                return subprocess.CompletedProcess(argv, 0, stdout=output+'\n', stderr='')
            return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')
        # Metadata verifier invocation is intentionally a command seam, no real signing keys.
        tool = Path(argv[0]).name
        self.assertIn(tool, ('aapt', 'aapt2', 'apksigner'), 'Unreviewed arbitrary executable')
        text = ("package: name='ru.dewil.aicontrol' versionCode='3' versionName='0.1.2'\nminSdkVersion:'26'\ntargetSdkVersion:'36'\n" if tool != 'apksigner'
                else 'Signer #1 certificate SHA-256 digest: '+CERT+'\n')
        return subprocess.CompletedProcess(argv, 0, stdout=text, stderr='')

    def existing_lock_drift_refuses_without_creation_or_repair(self, operation):
        # INV-DEPLOY-17 / INV-DEPLOY-18: existing root-private lock provenance.
        operation_name = operation.__name__
        with self.subTest(drift='missing lock'):
            lock = self.paths['LOCK']
            lock.unlink()
            before_paths = {p.relative_to(self.root) for p in self.root.rglob('*')}
            self.refuse_without_mutation(operation)
            self.assertFalse(lock.exists(), 'Operation manufactured missing accepted-R5 lock')
            self.assertEqual({p.relative_to(self.root) for p in self.root.rglob('*')}, before_paths)
            self.assertFalse(self.commands, 'Lock drift triggered service mutation')
        # A failed refusal must not contaminate the independent unsafe-parent case.
        self.setUp()
        operation = getattr(self.op, operation_name)
        with self.subTest(drift='parent0755'):
            lock = self.paths['LOCK']
            inode = lock.stat().st_ino
            lock.parent.chmod(0o755)
            before_paths = {p.relative_to(self.root) for p in self.root.rglob('*')}
            self.refuse_without_mutation(operation)
            self.assertEqual(lock.stat().st_ino, inode)
            self.assertEqual(lock.parent.stat().st_mode & 0o777, 0o755)
            self.assertEqual({p.relative_to(self.root) for p in self.root.rglob('*')}, before_paths)
            self.assertFalse(self.commands, 'Lock drift triggered service mutation')

    def protected(self):
        return {name: path.read_bytes() if path.is_file() else None for name, path in self.paths.items()
                if name in ('HELPER', 'STATE', 'KEY', 'AUTH_CONFIG', 'FEED')}

    def refuse_without_mutation(self, operation):
        before = self.protected()
        with self.assertRaises(ValueError):
            operation()
        self.assertEqual(self.protected(), before)


class BootstrapContracts(OperationsFixture):
    def setUp(self):
        self.prepare('ai-control-app-bootstrap.py')

    def test_missing_existing_lock_or_unsafe_parent_is_drift(self):
        self.existing_lock_drift_refuses_without_creation_or_repair(self.op.bootstrap)

    def test_wrong_new_pin_never_derives_authority_from_candidate(self):
        # INV-DEPLOY-17
        self.op.EXPECTED_NEW_HELPER_SHA256 = 'f'*64
        self.refuse_without_mutation(self.op.bootstrap)
        self.assertFalse(self.commands)

    def test_package_pending_and_malformed_marker_refuse_without_replacement(self):
        # INV-DEPLOY-17
        for name in ('PACKAGE_PENDING', 'BOOTSTRAP_MARKER', 'CONFIG_MARKER'):
            with self.subTest(marker=name):
                path = self.paths[name]
                self.write(path, b'{invalid', 0o600)
                self.refuse_without_mutation(self.op.bootstrap)
                self.assertEqual(path.read_bytes(), b'{invalid')
                path.unlink()

    def test_success_replaces_only_helper_preserving_raw_state_key_and_auth(self):
        # INV-DEPLOY-17
        before = self.protected()
        self.assertIsNone(self.op.bootstrap())
        self.assertEqual(self.paths['HELPER'].read_bytes(), self.paths['NEW_HELPER'].read_bytes())
        for name in ('STATE', 'KEY', 'AUTH_CONFIG'):
            self.assertEqual(self.protected()[name], before[name])
        self.assertFalse(self.paths['BOOTSTRAP_MARKER'].exists())
        self.assertFalse(self.commands, 'Bootstrap changed service state')

    def test_repeated_marker_accepted14_drift_is_terminal_refusal(self):
        # INV-DEPLOY-17 / DESIGN M1: oldscope remains untouched, evidence retained.
        checkpoint = self.paths['BOOTSTRAP_CHECKPOINTS']/'independent-bootstrap'
        checkpoint.mkdir(parents=True, mode=0o700)
        self.write(checkpoint/'helper.before', self.paths['HELPER'].read_bytes(), 0o600)
        marker = dict(schema=1, checkpoint=checkpoint.name,
            before_sha256=self.op.EXPECTED_OLD_HELPER_SHA256,
            after_sha256=self.op.EXPECTED_NEW_HELPER_SHA256,
            accepted_sha256=self.op.EXPECTED_ACCEPTED_SHA256)
        self.write(self.paths['BOOTSTRAP_MARKER'], json.dumps(marker).encode(), 0o600)
        # Legitimate accepted14-prime has new content and positive signed provenance.
        current = dict(self.before14)
        current['bin/_control_web.css'] += b'new legitimate14'
        self.install_accepted(current, 2, 8)
        raw_marker = self.paths['BOOTSTRAP_MARKER'].read_bytes()
        for _ in range(2):
            self.refuse_without_mutation(self.op.bootstrap)
            self.assertEqual(self.paths['BOOTSTRAP_MARKER'].read_bytes(), raw_marker)
            self.assertTrue(checkpoint.exists())
        self.assertFalse(self.commands)


class ConfigContracts(OperationsFixture):
    def setUp(self):
        self.prepare('ai-control-app-config.py')
        self.write(self.paths['HELPER'], self.paths['NEW_HELPER'].read_bytes(), 0o755)

    def test_missing_existing_lock_or_unsafe_parent_is_drift(self):
        self.existing_lock_drift_refuses_without_creation_or_repair(self.op.configure)

    def test_only_two_app_paths_append_all_other_values_preserved(self):
        # INV-DEPLOY-18
        replay = Path(self.config['totp_state_path']).read_bytes()
        try:
            result = self.op.configure()
        except ValueError:
            self.fail('Valid pinned config migration with accepted R5 unit profiles was refused')
        self.assertIsNone(result)
        after = json.loads(self.paths['AUTH_CONFIG'].read_bytes())
        expected = copy.deepcopy(self.config)
        expected.update(android_auth_db=str(self.paths['AUTH_DB']), android_download_dir=str(self.paths['CATALOG']))
        self.assertEqual(after, expected)
        self.assertEqual(Path(self.config['totp_state_path']).read_bytes(), replay)
        self.assertFalse(self.paths['CONFIG_MARKER'].exists())
        self.assertEqual(self.paths['AUTH_CONFIG'].stat().st_mode & 0o777, 0o600)

    def test_conflicting_path_and_unsafe_private_parent_refuse_preserving_config(self):
        # INV-DEPLOY-18
        config = {**self.config, 'android_auth_db': '/unapproved/location.sqlite3'}
        self.write(self.paths['AUTH_CONFIG'], json.dumps(config).encode(), 0o600)
        self.op.EXPECTED_AUTH_SHA256 = fixture.sha(self.paths['AUTH_CONFIG'].read_bytes())
        self.refuse_without_mutation(self.op.configure)
        self.write(self.paths['AUTH_CONFIG'], self.auth_raw, 0o600)
        self.op.EXPECTED_AUTH_SHA256 = fixture.sha(self.auth_raw)
        self.paths['AUTH_CONFIG'].parent.chmod(0o777)
        self.refuse_without_mutation(self.op.configure)
        self.assertEqual(self.paths['AUTH_CONFIG'].parent.stat().st_mode & 0o777, 0o777)

    def test_post_stop_digest_mismatch_restarts_once_and_creates_no_marker(self):
        # INV-DEPLOY-18 / DESIGN M2: active/User/Group health for BOTH services.
        changed = self.auth_raw+b' '
        def change_during_stop(argv):
            self.paths['AUTH_CONFIG'].write_bytes(changed)
        self.after_stop = change_during_stop
        with self.assertRaises(ValueError):
            self.op.configure()
        self.assertEqual(self.paths['AUTH_CONFIG'].read_bytes(), changed)
        self.assertFalse(self.paths['CONFIG_MARKER'].exists())
        self.assertFalse(self.paths['CONFIG_CHECKPOINTS'].exists())
        starts = [a for a in self.commands if a[1] == 'start']
        self.assertEqual(len(starts), 2)
        self.assertEqual({a[2] for a in starts}, set(fixture.SERVICES))
        health = self.commands[self.commands.index(starts[-1])+1:]
        self.assertEqual({a[2] for a in health if a[1] == 'is-active'}, set(fixture.SERVICES))
        for service in fixture.SERVICES:
            for prop in ('User', 'Group'):
                self.assertTrue(any(a[1] == 'show' and service in a and prop in a for a in health))

    def test_start_timeout_rolls_back_raw_config_retains_grants_and_evidence_if_retry_fails(self):
        # INV-DEPLOY-18 / DESIGN M5: one bounded rollback attempt, no DB rewind.
        self.write(self.paths['AUTH_DB'], b'synthetic existing grant authority', 0o600)
        count = []
        first_failure_index = []
        def fail_start(argv):
            if argv[1] == 'start':
                count.append(True)
                if not first_failure_index:
                    first_failure_index.append(len(self.commands)-1)
                raise subprocess.TimeoutExpired(argv[0], 40)
        self.command_failure = fail_start
        with self.assertRaises(ValueError):
            self.op.configure()
        self.assertEqual(self.paths['AUTH_CONFIG'].read_bytes(), self.auth_raw)
        self.assertEqual(self.paths['AUTH_DB'].read_bytes(), b'synthetic existing grant authority')
        self.assertTrue(self.paths['CONFIG_MARKER'].exists())
        self.assertLessEqual(len(count), 2)
        # Config rollback: stop2 + inactive2 + start2 + health6 <=12 calls / 480s.
        self.assertTrue(first_failure_index)
        self.assertLessEqual(len(self.commands)-first_failure_index[0]-1, 12)


class PublisherContracts(OperationsFixture):
    def setUp(self):
        self.prepare('publish-android-release.py')
        self.apk = self.root/'synthetic.apk'
        self.write(self.apk, b'synthetic APK verified by injected metadata tool', 0o600)
        self.metadata = dict(version_code=3, version_name='0.1.2', sha256=fixture.sha(self.apk.read_bytes()), certificate_sha256=CERT)

    def publish(self, **changes):
        return self.op.publish(self.apk, **(self.metadata | changes))

    def test_wrong_certificate_hash_and_nonpositive_code_never_switch_feed(self):
        # INV-DEPLOY-19
        for changes in ({'certificate_sha256':'0'*64}, {'sha256':'f'*64}, {'version_code':0}, {'version_code':True}, {'version_code':2147483648}):
            with self.subTest(changes=changes):
                self.refuse_without_mutation(lambda: self.publish(**changes))
                self.assertFalse(self.paths['FEED'].exists())

    def test_feed_switch_requires_durable_immutable_apk_and_empty_before_cas_rollback(self):
        # INV-DEPLOY-19: atomic feed comes after verified final APK, explicit empty rollback.
        genuine = os.replace
        switches = []
        def observed_replace(source, destination, *args, **kwargs):
            path = Path(destination)
            if not path.is_absolute() and kwargs.get('dst_dir_fd') is not None:
                path = Path(os.readlink('/proc/self/fd/'+str(kwargs['dst_dir_fd']))) / path
            if path == self.paths['FEED']:
                final = self.paths['CATALOG']/'ai-control-3.apk'
                self.assertTrue(final.is_file(), 'Publisher switched feed before immutable APK')
                self.assertEqual(fixture.sha(final.read_bytes()), self.metadata['sha256'])
                switches.append(True)
            return genuine(source, destination, *args, **kwargs)
        with patch('os.replace', side_effect=observed_replace):
            proof = self.publish()
        self.assertEqual(switches, [True])
        self.assertEqual(Path(proof).name, proof)
        raw_feed = self.paths['FEED'].read_bytes()
        self.assertIsNone(self.op.rollback(fixture.sha(raw_feed), proof))
        self.assertFalse(self.paths['FEED'].exists())
        self.assertTrue((self.paths['CATALOG']/'ai-control-3.apk').exists())
        self.assertTrue(self.paths['PUBLISH_LOCK'].exists())
        self.assertTrue((self.paths['PUBLICATION_PROOFS']/proof).exists())
        self.assertIsNone(self.op.rollback(fixture.sha(raw_feed), proof))

    def test_different_bytes_same_immutable_name_refuse_without_overwrite(self):
        # INV-DEPLOY-19
        final = self.paths['CATALOG']/'ai-control-3.apk'
        self.write(final, b'different retained immutable APK', 0o640)
        self.refuse_without_mutation(self.publish)
        self.assertEqual(final.read_bytes(), b'different retained immutable APK')

    def test_stale_rollback_proof_cannot_restore_after_newer_feed(self):
        # INV-DEPLOY-19: CAS refuses newer/unknown current, never blind rollback.
        proof = self.publish()
        old_digest = fixture.sha(self.paths['FEED'].read_bytes())
        current = self.paths['FEED'].read_bytes()+b' '
        self.paths['FEED'].write_bytes(current)
        self.refuse_without_mutation(lambda: self.op.rollback(old_digest, proof))
        self.assertEqual(self.paths['FEED'].read_bytes(), current)


if __name__ == '__main__':
    unittest.main()
