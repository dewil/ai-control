"""Independent nodes25 root-operation DESIGN/RED; synthetic private files only.

No implementation/body under test consulted, no root channel executed, no real
systemctl or owner config read. Existing Deploy fixture/API is reused unchanged.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import deploy22_blind_support as s
import test_control_node_deploy25_red as nd

ARTIFACTS = ('helper.before', 'helper.after', 'broker-unit.before',
             'broker-unit.after', 'accepted.before', 'live-receipt.before',
             'attachments-receipt.before')
PHASES = ('journal', 'helper', 'unit', 'receipt', 'verified')


class NodesBootstrapRED(s.ControllerFixture):
    install_state = nd.NodeDeploy25RED.install_state
    tree = nd.NodeDeploy25RED.tree
    for name in ('crypto', 'write', 'hashes', 'stops', 'deploy', 'accepted',
                 'dependency_after'):
        locals()[name] = getattr(s.ControllerFixture, name)
    runner = s.ControllerFixture.runner

    def setUp(self):
        super().setUp()
        self.after23 = {**self.after22, 'bin/_control_web_attachments.py': b'# signed synthetic attachment\n'}
        self.after25 = {**self.after23, **{leaf: ('# signed synthetic ' + leaf + '\n').encode() for leaf in nd.NODE_LEAVES}}
        self.install_state(self.after23, 5, 7)
        self.dependency_after()
        self.oldunit = self.unit.read_bytes()
        self.nodeunit = self.oldunit.replace(b'[Service]\n', b'[Service]\n' + nd.NODE_LINE, 1)
        self.attachment = self.state.parent / 'attachments-bootstrap-complete.json'
        self.nodes = self.state.parent / 'nodes-bootstrap-complete.json'
        self.api.ATTACHMENT_RECEIPT = self.attachment
        self.api.NODE_RECEIPT = self.nodes
        live = json.loads(self.receipt.read_bytes())
        live['helper_sha256'] = s.sha(s.accepted22_source())
        self.oldlive = s.canonical(live)
        self.write(self.receipt, self.oldlive, 0o600)
        self.attachment_value = dict(schema=1, operation='attachments23-bootstrap',
            prior_helper_sha256=live['helper_sha256'], prior_receipt_sha256=s.sha(self.oldlive),
            accepted_before_sha256='a' * 64, packet_sha256='b' * 64)
        self.new_helper = self.helper.read_bytes()
        self.old_helper = self.new_helper + b'\n# synthetic separately reviewed prior helper\n'
        self.write(self.helper, self.old_helper, 0o755)
        self.attachment_value['helper_sha256'] = s.sha(self.old_helper)
        self.oldattachment = s.canonical(self.attachment_value)
        self.write(self.attachment, self.oldattachment, 0o600)
        self.before_state = self.state.read_bytes()
        self.before_tree = self.tree()
        self.pending = self.state.parent / 'nodes-bootstrap-pending.json'
        self.lock = self.checkpoints / 'lock'
        self.write(self.lock, b'', 0o600)
        self.paths = dict(HELPER=self.helper, BROKER_UNIT=self.unit, ACCEPTED=self.state,
            LIVE_RECEIPT=self.receipt, ATTACHMENT_RECEIPT=self.attachment,
            NODE_RECEIPT=self.nodes, LOCK=self.lock, CHECKPOINTS=self.checkpoints,
            PENDING=self.pending, PACKAGE_PENDING=self.checkpoints / 'pending.json',
            CONFIG_PENDING=self.state.parent / 'config-pending.json')
        self.packet = self.root / 'nodes-packet'
        self.packet.mkdir(mode=0o700)
        self.payload = dict(zip(ARTIFACTS, (self.old_helper, self.new_helper,
            self.oldunit, self.nodeunit, self.before_state, self.oldlive, self.oldattachment)))
        for name, data in self.payload.items():
            self.write(self.packet / name, data, 0o600)
        self.manifest = dict(schema=1, operation='nodes25-bootstrap', accepted_release_id=7,
            files={name: dict(sha256=s.sha(data), size=len(data)) for name, data in self.payload.items()})
        self.manifest_raw = s.canonical(self.manifest)
        self.write(self.packet / 'manifest.json', self.manifest_raw, 0o600)
        self.receipt_value = dict(schema=1, operation='nodes25-bootstrap',
            prior_receipt_sha256=s.sha(self.oldattachment),
            prior_helper_sha256=s.sha(self.old_helper), helper_sha256=s.sha(self.new_helper),
            prior_unit_sha256=s.sha(self.oldunit), unit_sha256=s.sha(self.nodeunit),
            accepted_before_sha256=s.sha(self.before_state), packet_sha256=s.sha(self.manifest_raw))
        self.receipt_raw = s.canonical(self.receipt_value)
        self.reloads = 0
        self.fail_reload = None
        # Fixture validation runs before checking the planned public seam.
        self.deploy().read_state()
        self.deploy().live_gate()
        self.deploy().match(self.hashes(self.before_tree))
        path = s.ROOT / 'deployment/ai-control-nodes-bootstrap.py'
        self.assertTrue(path.is_file(), 'INV-NBOOT-01 planned root bootstrap module absent; implementation prerequisite')
        spec = importlib.util.spec_from_file_location('node_bootstrap_red_api', path)
        self.bootstrap_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bootstrap_api)
        self.pin = patch.object(self.bootstrap_api, 'EXPECTED_PACKET_SHA256', s.sha(self.manifest_raw))
        self.pin.start(); self.addCleanup(self.pin.stop)

    def run_command(self, argv):
        self.assertEqual(argv[0], '/usr/bin/systemctl')
        self.assertNotIn(argv[1], ('stop', 'start', 'restart'))
        if argv == ['/usr/bin/systemctl', 'daemon-reload']:
            self.reloads += 1
            self.calls.append(list(argv))
            if self.fail_reload == self.reloads:
                raise RuntimeError('synthetic reload failure')
            return ''
        return s.ControllerFixture.runner(self, argv)

    def operation(self, hook=None):
        deploy = self.deploy()
        deploy.runner = self.run_command
        return self.bootstrap_api.NodesBootstrap(self.packet, paths=self.paths,
            runner=self.run_command, owner_uid=os.getuid(), helper_api=self.api,
            deploy=deploy, checkpoint_hook=hook)

    def immutable(self):
        self.assertEqual(self.state.read_bytes(), self.before_state)
        self.assertEqual(self.tree(), self.before_tree)
        self.assertEqual(self.receipt.read_bytes(), self.oldlive)
        self.assertEqual(self.attachment.read_bytes(), self.oldattachment)

    def restored(self):
        self.immutable()
        self.assertEqual(self.helper.read_bytes(), self.old_helper)
        self.assertEqual(self.unit.read_bytes(), self.oldunit)
        self.assertFalse(os.path.lexists(self.nodes))
        self.assertFalse(os.path.lexists(self.pending))

    def seed_prefix(self, mask):
        checkpoint = self.checkpoints / ('nodes-helper-synthetic-' + str(mask))
        checkpoint.mkdir(mode=0o700)
        for leaf in ('manifest.json',) + ARTIFACTS:
            self.write(checkpoint / leaf, (self.packet / leaf).read_bytes(), 0o600)
        journal = dict(schema=1, operation='nodes25-bootstrap',
            packet_sha256=s.sha(self.manifest_raw), checkpoint=checkpoint.name)
        self.write(self.pending, s.canonical(journal), 0o600)
        self.write(self.helper, self.new_helper if mask & 1 else self.old_helper, 0o755)
        self.write(self.unit, self.nodeunit if mask & 2 else self.oldunit, 0o644)
        if mask & 4:
            self.write(self.nodes, self.receipt_raw, 0o600)
        return checkpoint

    def test_forward_changes_only_helper_unit_receipt_and_reloads_without_restart(self):
        # INV-NBOOT-01/03.
        self.assertEqual(self.operation().run(), {'status': 'extended'})
        self.immutable()
        self.assertEqual(self.helper.read_bytes(), self.new_helper)
        self.assertEqual(self.unit.read_bytes(), self.nodeunit)
        self.assertEqual(self.helper.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.unit.stat().st_mode & 0o777, 0o644)
        self.assertEqual(json.loads(self.nodes.read_bytes()), self.receipt_value)
        self.assertEqual(self.nodes.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.reloads, 1)
        self.assertFalse(self.pending.exists())
        self.assertFalse(any(row[1] in ('start', 'stop', 'restart') for row in self.calls))

    def test_checkpoint_and_pending_are_durable_before_first_mutation(self):
        # INV-NBOOT-03: checkpoint independent bytes precede helper replacement.
        observed = []
        def hook(phase):
            observed.append(phase)
            if phase == 'journal':
                self.assertEqual(self.helper.read_bytes(), self.old_helper)
                self.assertEqual(self.unit.read_bytes(), self.oldunit)
                journal = json.loads(self.pending.read_bytes())
                checkpoint = self.checkpoints / journal['checkpoint']
                self.assertEqual({item.name for item in checkpoint.iterdir()}, set(ARTIFACTS) | {'manifest.json'})
                for name in ARTIFACTS:
                    self.assertEqual((checkpoint / name).read_bytes(), self.payload[name])
                    self.assertEqual((checkpoint / name).stat().st_mode & 0o777, 0o600)
                self.assertEqual(checkpoint.stat().st_mode & 0o777, 0o700)
        self.operation(hook).run()
        self.assertEqual(observed, list(PHASES))

    def test_each_durable_forward_failure_restores_all_three_changed_objects(self):
        # INV-NBOOT-04: receipt publication/verification also require rollback.
        for fault in PHASES:
            with self.subTest(phase=fault):
                def hook(phase):
                    if phase == fault:
                        raise RuntimeError('synthetic interruption')
                with self.assertRaises(ValueError):
                    self.operation(hook).run()
                self.restored()

    def test_all_eight_owned_partial_prefixes_recover_without_accepted_mutation(self):
        # INV-NBOOT-04: interrupted forward and interrupted rollback prefixes.
        for mask in range(8):
            with self.subTest(prefix=mask):
                checkpoint = self.seed_prefix(mask)
                before = self.reloads
                self.assertEqual(self.operation().recover(), {'status': 'recovered'})
                self.restored()
                self.assertEqual(self.reloads, before + 1)
                self.assertEqual((checkpoint / 'accepted.before').read_bytes(), self.before_state)

    def test_reload_failure_rolls_back_and_rollback_failure_retains_pending(self):
        # INV-NBOOT-04: one rollback budget, never recursive repair.
        self.fail_reload = 1
        with self.assertRaises(ValueError):
            self.operation().run()
        self.restored()
        self.assertEqual(self.reloads, 2)
        self.seed_prefix(7)
        self.fail_reload = self.reloads + 1
        with self.assertRaises(self.bootstrap_api.RollbackFailed):
            self.operation().recover()
        self.assertTrue(self.pending.exists())
        self.immutable()

    def test_existing_shared_lock_contention_refuses_before_runner_or_mutation(self):
        # INV-NBOOT-02: share deploy lock, never create a competing lock inode.
        inode = self.lock.stat().st_ino
        with self.lock.open('r+b') as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.calls.clear()
            with self.assertRaises(ValueError):
                self.operation().run()
        self.restored()
        self.assertEqual(self.lock.stat().st_ino, inode)
        self.assertEqual(self.calls, [])

    def test_wrong_trust_pin_or_packet_hash_refuses_without_journal(self):
        # INV-NBOOT-02: a self-consistent unreviewed manifest has no authority.
        with patch.object(self.bootstrap_api, 'EXPECTED_PACKET_SHA256', 'a' * 64):
            with self.assertRaises(ValueError): self.operation().run()
        self.restored()
        self.write(self.packet / 'helper.after', self.new_helper + b'# drift', 0o600)
        with self.assertRaises(ValueError): self.operation().run()
        self.restored()
        self.assertEqual(self.reloads, 0)

    def test_before_helper_unit_state_or_prior_receipt_drift_refuses_without_repair(self):
        # INV-NBOOT-02: each protected anchor matters independently.
        for path in (self.helper, self.unit, self.state, self.receipt, self.attachment):
            with self.subTest(anchor=path.name):
                raw, mode = path.read_bytes(), path.stat().st_mode & 0o777
                self.write(path, raw + b'\n', mode)
                with self.assertRaises(ValueError): self.operation().run()
                self.assertEqual(path.read_bytes(), raw + b'\n')
                self.assertFalse(self.pending.exists())
                self.write(path, raw, mode)
        self.restored()
        self.assertEqual(self.reloads, 0)

    def test_unit_candidate_extra_privilege_delta_rejected_even_with_rehashed_packet(self):
        # INV-NBOOT-02: packet hash alone cannot authorize additional unit scope.
        changed = self.nodeunit + b'\nReadWritePaths=/\n'
        self.write(self.packet / 'broker-unit.after', changed, 0o600)
        self.manifest['files']['broker-unit.after'] = dict(sha256=s.sha(changed), size=len(changed))
        raw = s.canonical(self.manifest)
        self.write(self.packet / 'manifest.json', raw, 0o600)
        with patch.object(self.bootstrap_api, 'EXPECTED_PACKET_SHA256', s.sha(raw)):
            with self.assertRaises(ValueError): self.operation().run()
        self.restored()
        self.assertEqual(self.reloads, 0)

    def test_unsafe_packet_leaf_symlink_hardlink_or_mode_refuses(self):
        # INV-NBOOT-02: physical file safety, not JSON-only validation.
        leaf = self.packet / 'helper.after'
        original = leaf.read_bytes()
        for variant in ('mode', 'symlink', 'hardlink'):
            with self.subTest(variant=variant):
                if variant == 'mode': leaf.chmod(0o644)
                elif variant == 'symlink':
                    copy = self.root / 'outside-helper'; self.write(copy, original, 0o600)
                    leaf.unlink(); leaf.symlink_to(copy)
                else:
                    os.link(leaf, self.root / 'hard-helper')
                with self.assertRaises(ValueError): self.operation().run()
                self.restored()
                if variant == 'hardlink': (self.root / 'hard-helper').unlink()
                if variant == 'symlink': leaf.unlink(); self.write(leaf, original, 0o600)
                leaf.chmod(0o600)

    def test_existing_foreign_receipt_is_not_overwritten_or_adopted(self):
        # INV-NBOOT-02/05: malformed existing proof never falls back to old path.
        self.write(self.nodes, b'foreign owned receipt', 0o600)
        with self.assertRaises(ValueError): self.operation().run()
        self.assertEqual(self.nodes.read_bytes(), b'foreign owned receipt')
        self.assertEqual(self.helper.read_bytes(), self.old_helper)
        self.assertEqual(self.unit.read_bytes(), self.oldunit)
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.reloads, 0)

    def test_recovery_refuses_foreign_delta_or_corrupt_backup_preserving_journal(self):
        # INV-NBOOT-04: restore only known prefixes, never guessed foreign bytes.
        checkpoint = self.seed_prefix(7)
        self.write(self.helper, b'foreign helper drift', 0o755)
        with self.assertRaises(ValueError): self.operation().recover()
        self.assertEqual(self.helper.read_bytes(), b'foreign helper drift')
        self.assertTrue(self.pending.exists())
        self.write(self.helper, self.new_helper, 0o755)
        self.write(checkpoint / 'helper.before', b'corrupt backup', 0o600)
        with self.assertRaises(ValueError): self.operation().recover()
        self.assertTrue(self.pending.exists())
        self.assertEqual(self.helper.read_bytes(), self.new_helper)
        self.immutable()

    def test_exact_repeat_preserves_inode_bytes_and_does_not_reload(self):
        # INV-NBOOT-05: repeated root payload is read-only verification.
        self.operation().run()
        paths = (self.helper, self.unit, self.nodes, self.state, self.receipt, self.attachment)
        before = [(path.read_bytes(), path.stat().st_ino) for path in paths]
        self.calls.clear(); reloads = self.reloads
        self.assertEqual(self.operation().run(), {'status': 'already_extended'})
        self.assertEqual([(path.read_bytes(), path.stat().st_ino) for path in paths], before)
        self.assertEqual(self.reloads, reloads)
        self.assertFalse(any(row[1] in ('daemon-reload', 'start', 'stop', 'restart') for row in self.calls))

    def test_repeat_after_signed_release_advances_accepted_state_keeps_historical_anchor(self):
        # INV-NBOOT-05: historical bootstrap hash is not mutable release identity.
        self.operation().run()
        self.install_state(self.after25, 6, 8)
        advanced = self.state.read_bytes()
        code = self.tree()
        self.assertNotEqual(s.sha(advanced), self.receipt_value['accepted_before_sha256'])
        self.assertEqual(self.operation().run(), {'status': 'already_extended'})
        self.assertEqual(self.state.read_bytes(), advanced)
        self.assertEqual(self.tree(), code)
        self.assertEqual(json.loads(self.nodes.read_bytes()), self.receipt_value)
        self.assertEqual(self.reloads, 1)
        self.assertEqual(self.receipt.read_bytes(), self.oldlive)
        self.assertEqual(self.attachment.read_bytes(), self.oldattachment)

    def test_missing_node_config_and_package_markers_do_not_trigger_provisioning(self):
        # INV-NBOOT-01/02: no owner config/bootstrap side effects.
        self.assertNotIn('CONFIG_PATH', self.paths)
        for path in (self.paths['PACKAGE_PENDING'], self.paths['CONFIG_PENDING']):
            self.write(path, b'foreign pending transaction', 0o600)
            with self.assertRaises(ValueError): self.operation().run()
            self.assertEqual(path.read_bytes(), b'foreign pending transaction')
            self.assertFalse(self.pending.exists())
            path.unlink()
        before = {str(path.relative_to(self.root)) for path in self.root.rglob('*')}
        self.operation().run()
        after = {str(path.relative_to(self.root)) for path in self.root.rglob('*')}
        self.assertFalse(any('node-tasks.json' in name for name in after - before))
        self.immutable()


if __name__ == '__main__':
    unittest.main()
