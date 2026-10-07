"""Independent accepted16 config incident contract, synthetic-only public seams.

Uses the corrected accepted-R5 frontend/broker profiles in the original fixture.
No bootstrap, signed deployment, state reset, provider or production auth actions.
"""
import copy
import json
import os
import unittest
import test_control_web_app_deploy16_operations_blind_red as operations


class Accepted16ConfigIncident(operations.OperationsFixture):
    def setUp(self):
        self.prepare('ai-control-app-config.py')
        self.write(self.paths['HELPER'], self.paths['NEW_HELPER'].read_bytes(), 0o755)
        self.install_accepted(self.before16, 3, 8)
        self.op.EXPECTED_ACCEPTED_SHA256 = operations.fixture.sha(self.state.read_bytes())
        self.write(self.paths['AUTH_DB'], b'synthetic persistent grant authority', 0o600)
        self.replay = operations.Path(self.config['totp_state_path'])
        self.original_state = self.state.read_bytes()
        self.original_tree = self.hashes(self.tree())
        self.original_replay = self.replay.read_bytes()
        self.original_db = self.paths['AUTH_DB'].read_bytes()

    def assert_preserved(self):
        self.assertEqual(self.state.read_bytes(), self.original_state)
        self.assertEqual(self.hashes(self.tree()), self.original_tree)
        self.assertEqual(self.replay.read_bytes(), self.original_replay)
        self.assertEqual(self.paths['AUTH_DB'].read_bytes(), self.original_db)

    def accepted_scope_seam(self):
        method = getattr(self.op, 'accepted_package', None)
        self.assertTrue(callable(method), 'AVAILABILITY: frozen accepted_package public seam absent')
        return method

    def refuse_scope_without_repair(self, method):
        before_tree = self.hashes(self.tree())
        def metadata():
            return {p: tuple(getattr(os.lstat(self.target/p), key) for key in
                    ('st_dev','st_ino','st_mode','st_nlink','st_uid','st_gid','st_size','st_mtime_ns','st_ctime_ns'))
                    for p in operations.core.FULL16 if os.path.lexists(self.target/p)}
        before_metadata = metadata()
        self.refuse_without_mutation(method)
        self.assertEqual(self.hashes(self.tree()), before_tree)
        self.assertEqual(metadata(), before_metadata, 'Rejected scope proof repaired target metadata')

    def configure_successfully(self):
        try:
            result = self.op.configure()
        except ValueError:
            self.fail('Known pinned exact16 config migration was refused')
        self.assertIsNone(result)

    def test_known16_config_migration_preserves_accepted_tree_replay_grants_and_unknown_fields(self):
        # INV-DEPLOY-18: accepted16 recovery authorization, bootstrap still strictly14.
        protected = self.protected()
        self.configure_successfully()
        expected = copy.deepcopy(self.config)
        expected.update(android_auth_db=str(self.paths['AUTH_DB']), android_download_dir=str(self.paths['CATALOG']))
        self.assertEqual(json.loads(self.paths['AUTH_CONFIG'].read_bytes()), expected)
        self.assert_preserved()
        for name in ('STATE','HELPER','KEY'):
            self.assertEqual(self.protected()[name], protected[name])
        self.assertFalse(self.paths['CONFIG_MARKER'].exists())
        self.assertEqual(self.paths['AUTH_CONFIG'].stat().st_mode & 0o777, 0o600)

    def test_accepted_package_returns_exact_raw16_and_pin_scope_hash_link_drift_refuse(self):
        # INV-DEPLOY-13 / INV-DEPLOY-18: closed map and literal whole-state authority.
        method = self.accepted_scope_seam()
        try:
            actual = method()
        except ValueError:
            self.fail('Valid exact16 raw accepted proof was refused')
        self.assertEqual(actual, self.original_state)
        self.refuse_scope_without_repair(self.op.accepted14)
        with self.subTest(drift='wrong accepted pin'):
            self.op.EXPECTED_ACCEPTED_SHA256 = 'f'*64
            self.refuse_scope_without_repair(method)
        self.op.EXPECTED_ACCEPTED_SHA256 = operations.fixture.sha(self.original_state)
        with self.subTest(drift='schema3 mixed14'):
            mixed = json.loads(self.original_state)
            mixed['files'].pop(operations.core.AUTH)
            self.state.write_bytes(json.dumps(mixed).encode())
            self.op.EXPECTED_ACCEPTED_SHA256 = operations.fixture.sha(self.state.read_bytes())
            self.refuse_scope_without_repair(method)
        self.state.write_bytes(self.original_state)
        self.op.EXPECTED_ACCEPTED_SHA256 = operations.fixture.sha(self.original_state)
        leaf = self.target/operations.core.DOWNLOAD
        original = leaf.read_bytes()
        with self.subTest(drift='unknown target hash'):
            leaf.write_bytes(b'unreviewed app module')
            self.refuse_scope_without_repair(method)
        leaf.write_bytes(original)
        with self.subTest(drift='target symlink'):
            retained = self.root/'retained-download'
            retained.write_bytes(original)
            leaf.unlink()
            leaf.symlink_to(retained)
            self.refuse_scope_without_repair(method)
        self.assertFalse(self.commands, 'Accepted proof mutated service state')

    def test_same_pin16_pending_config_recovers_from_checked_before_without_replay_rewind(self):
        # INV-DEPLOY-18: valid marker created through public configure, no guessed schema.
        pid = os.fork()
        if pid == 0:
            def interrupt_first_start(argv):
                if operations.Path(argv[0]).name == 'systemctl' and argv[1] == 'start':
                    os._exit(73)
            self.command_failure = interrupt_first_start
            try:
                self.op.configure()
            except BaseException:
                os._exit(75)
            os._exit(74)
        waited, status = os.waitpid(pid, 0)
        self.assertEqual(waited, pid)
        self.assertTrue(os.WIFEXITED(status))
        self.assertEqual(os.WEXITSTATUS(status), 73, 'Exact16 config did not reach durable pending before start')
        marker_path = self.paths['CONFIG_MARKER']
        self.assertTrue(marker_path.is_file())
        marker = json.loads(marker_path.read_bytes())
        self.assertEqual(marker['accepted_sha256'], operations.fixture.sha(self.original_state))
        self.assertEqual(marker['before_sha256'], operations.fixture.sha(self.auth_raw))
        self.assertNotEqual(marker['after_sha256'], marker['before_sha256'])
        checkpoint = self.paths['CONFIG_CHECKPOINTS']/marker['checkpoint']
        self.assertEqual((checkpoint/'auth.before').read_bytes(), self.auth_raw)
        # Current auth is after; the caller's authority remains the verified BEFORE digest.
        self.assertEqual(operations.fixture.sha(self.paths['AUTH_CONFIG'].read_bytes()), marker['after_sha256'])
        self.configure_successfully()
        self.assertFalse(marker_path.exists())
        self.assert_preserved()
        self.assertLessEqual(len(self.commands), 12)

    def test_existing_package_bootstrap_or_unknown_config_marker_blocks16_without_writes(self):
        # INV-DEPLOY-18: accepting known16 does not bypass any marker authority gate.
        for name in ('PACKAGE_PENDING','BOOTSTRAP_MARKER','CONFIG_MARKER'):
            with self.subTest(marker=name):
                path = self.paths[name]
                self.write(path, b'{malformed retained evidence', 0o600)
                self.refuse_without_mutation(self.op.configure)
                self.assertEqual(path.read_bytes(), b'{malformed retained evidence')
                self.assert_preserved()
                path.unlink()
        self.assertFalse(self.commands)


if __name__ == '__main__':
    unittest.main()
