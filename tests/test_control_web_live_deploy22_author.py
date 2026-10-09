"""Author regressions for independently reported DEPLOY22 gate failure windows."""
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


if __name__ == '__main__':
    unittest.main()
