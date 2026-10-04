"""Blind registry interoperability additions; no implementation imports at collection."""
import unittest
import test_control_web_broker_contract as fixtures

# Reuse only fixture helpers; do not inherit and duplicate the base test suite.
class RegistryInteropContract(unittest.TestCase):
    setUp = fixtures.BrokerContract.setUp
    write = fixtures.BrokerContract.write
    runner = fixtures.BrokerContract.runner
    snapshot = fixtures.BrokerContract.snapshot

    # INV-WEB-05: trusted registry metadata is not an unavailable task or global outage.
    def test_metadata_does_not_hide_existing_task(self):
        (self.registry/'.locks').mkdir(mode=0o700)
        (self.registry/'.locks'/'synthetic.lock').write_text('')
        (self.registry/'README').write_text('Registry metadata')
        (self.registry/'.index.json').write_text('{"version":1}')
        for path in (self.registry/'README', self.registry/'.index.json', self.registry/'.locks'/'synthetic.lock'):
            path.chmod(0o600)
        result = self.backend.snapshot()
        self.assertNotIn('error',result)
        self.assertEqual([task['agent'] for task in result['tasks']],['task-one'])
        self.assertFalse(result['tasks'][0].get('unavailable'),result)

    # INV-WEB-05: malformed agent specification must remain visibly unavailable.
    def test_corrupt_spec_is_visible_instead_of_empty_inventory(self):
        (self.agent/'spec.yaml').write_text('{')
        result = self.backend.snapshot()
        self.assertNotIn('error',result)
        matching=[task for task in result['tasks'] if task.get('agent')=='task-one']
        self.assertEqual(len(matching),1,result)
        self.assertTrue(matching[0].get('unavailable'),result)

if __name__ == '__main__':
    unittest.main(verbosity=2)
