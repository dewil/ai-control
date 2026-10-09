"""Author regressions for independently reported DEPLOY22 gate failure windows."""
import os
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch
import deploy22_blind_support as s


class GateRollbackAuthor(s.ControllerFixture):
    # INV-DEPLOY-21: after-state forward gate failure still permits package-before rollback.
    def test_recover_after4_unit_fault_restores_raw_before16(self):
        self.dependency_after()
        raw, before, after, _, checkpoint = self.make_journal(accepted_after=True)
        fault = self.unit.read_bytes() + b'# synthetic after-state unit fault\n'
        self.unit.write_bytes(fault)
        self.signed(files=after, base=before)
        with self.assertRaises(self.api.Rejected):
            self.deploy().run()
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertFalse((self.checkpoints / 'pending.json').exists())
        self.assertEqual(self.unit.read_bytes(), fault)
        self.assertEqual((checkpoint / 'accepted.json').read_bytes(), raw)
        self.assertEqual(len(self.stops()), 2)

    # INV-DEPLOY-21: publish->clear gate failure rolls back using the still-durable journal.
    def test_unit_fault_after_publish_before_clear_restores_raw_before16(self):
        self.dependency_after()
        self.signed()
        raw = self.state.read_bytes()
        controller = self.deploy()
        publish = controller.publish
        faults = []

        def publish_then_fault(value):
            publish(value)
            faults.append(self.unit.read_bytes() + b'# synthetic publish-clear unit fault\n')
            self.unit.write_bytes(faults[-1])

        with patch.object(controller, 'publish', side_effect=publish_then_fault):
            with self.assertRaises(self.api.Rejected):
                controller.run()
        self.assertEqual(len(faults), 1)
        self.assertEqual(self.tree(), self.before16)
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertFalse((self.checkpoints / 'pending.json').exists())
        self.assertEqual(self.unit.read_bytes(), faults[0])
        self.assertTrue(controller.rollback_used)
        self.assertEqual(len(self.stops()), 4)


class ProcessDeath(BaseException):
    pass


class RollbackStatusAuthor(s.BootstrapFixture):
    def setUp(self):
        self.prepare()

    # INV-DEPLOY-25: completed rollback is a refused operation through both entry layers.
    def test_rollback_resume_entry_and_wrapper_refuse_without_receipt(self):
        builder = s.source_module(self, 'ai-control-live-bootstrap-packet.py')
        inputs = dict(bootstrap_template=(s.ROOT / 'deployment/ai-control-live-bootstrap.py').read_bytes(),
                      wrapper_template=(s.ROOT / 'deployment/ai-control-live-bootstrap-wrapper.py').read_bytes(),
                      helper=self.new_helper, wheel=s.WHEEL.read_bytes(),
                      unit_before=self.before_unit, unit_after=self.after_unit)
        packet = builder.build_packet(inputs, self.bindings)
        self.op.PACKET_MANIFEST_SNAPSHOT = packet['manifest.json']
        self.op.PACKET_SHA256 = s.sha(packet['manifest.json'])
        self.smoke_result = subprocess.CompletedProcess([], 1, b'', b'')
        real_rename = os.rename

        def die_after_rollback_rename(source, destination, *args, **kwargs):
            result = real_rename(source, destination, *args, **kwargs)
            if Path(os.fspath(destination)).name == '.ai-control-live22-info.stage':
                raise ProcessDeath()
            return result

        with patch.object(os, 'rename', side_effect=die_after_rollback_rename):
            with self.assertRaises(ProcessDeath):
                self.invoke()
        self.assertTrue(self.paths['BOOTSTRAP_PENDING'].exists())
        self.assertFalse(self.receipt.exists())
        wrapper = s.module_bytes(packet['wrapper.py'], 'deploy22_author_wrapper_rollback')
        # Execute actual verified bootstrap code. The fixture's source-final paths
        # and runner are synthetic bindings, applied only to the loaded test module.
        real_exec = __import__('builtins').exec
        results = []

        def bind_synthetic_runtime(code, globals=None, locals=None, **kwargs):
            result = real_exec(code, globals, locals, **kwargs)
            if isinstance(code, types.CodeType) and 'bootstrap' in code.co_names and 'PACKET_SHA256' in code.co_names:
                globals.update(self.paths)
                globals['run_command'] = self.command
                globals['KEY_SHA256'] = s.sha(self.key.read_bytes())
                operation = globals['bootstrap']

                # entry() calls the actual bootstrap; the wrapper callback runs
                # that same entry and propagates its nonzero status.
                entry = globals['entry']
                def through_entry():
                    globals['bootstrap'] = operation
                    try:
                        status = entry()
                    finally:
                        globals['bootstrap'] = through_entry
                    results.append(status)
                    if status != 0:
                        raise ValueError('Bootstrap entry refused')
                globals['bootstrap'] = through_entry
            return result

        with self.root_boundary(), patch('builtins.exec', side_effect=bind_synthetic_runtime):
            status = wrapper.run_packet(packet['manifest.json'], packet['bootstrap.py'])
        self.assertEqual(results, [1])
        self.assertEqual(status, 1)
        self.assertEqual(self.state.read_bytes(), self.initial_state)
        self.assertEqual(self.helper.read_bytes(), s.pinned_source())
        self.assertEqual(self.unit.read_bytes(), self.before_unit)
        self.assertFalse(self.paths['DEP_PACKAGE'].exists())
        self.assertFalse(self.paths['DEP_INFO'].exists())
        self.assertFalse(self.paths['BOOTSTRAP_PENDING'].exists())
        self.assertFalse(self.receipt.exists())


if __name__ == '__main__':
    unittest.main()
