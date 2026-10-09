"""INV-DEPLOY-23 compiled pins and actual data-only production serializer."""
from copy import deepcopy
import unittest
import deploy22_blind_support as s

class SourceFinalInventoryBlind(s.ControllerFixture):
    def serializer(self):
        method=getattr(self.api,'canonical_inventory',None)
        self.assertTrue(callable(method),'PUBLIC-SEAM PREREQUISITE: controller canonical_inventory missing')
        return method

    def test_actual_controller_serializer_matches_independent_full_rows(self):
        method=self.serializer();independent=s.rows()
        self.assertEqual(method(list(reversed(independent))),s.canonical(independent))
        self.assertEqual(s.sha(method(independent)),s.INVENTORY_SHA)
        self.assertIs(type(self.api.WHEEL_MEMBERS),tuple);self.assertEqual(list(self.api.WHEEL_MEMBERS),independent)
        self.assertEqual(self.api.WHEEL_SHA256,s.WHEEL_SHA);self.assertEqual(self.api.WHEEL_SIZE,82408)
        self.assertEqual(self.api.WHEEL_INVENTORY_SHA256,s.INVENTORY_SHA)

    def test_actual_serializer_uses_observed_not_compiled_hash_size_mode(self):
        method=self.serializer();original=s.rows()
        for field,value in (('sha256','a'*64),('size',100),('install_mode',0o600)):
            changed=deepcopy(original);changed[0][field]=value
            self.assertNotEqual(s.sha(method(changed)),s.INVENTORY_SHA,field)

    def test_actual_serializer_closed_shape_bool_duplicate_type_refusals(self):
        method=self.serializer();original=s.rows()
        for changed in ([original[0],original[0]],[dict(original[0],size=True)],[dict(original[0],path='../escape')],
            [dict(original[0],extra=1)],[dict(original[0],archive_mode='420')]):
            with self.subTest(kind=list(changed[0].keys())):
                with self.assertRaises(ValueError):method(changed)

    def test_controller_bootstrap_pins_and_full29map_identical(self):
        bootstrap=s.source_module(self,'ai-control-live-bootstrap.py');self.serializer()
        for name,value in (('WHEEL_SHA256',s.WHEEL_SHA),('WHEEL_SIZE',82408),('WHEEL_INVENTORY_SHA256',s.INVENTORY_SHA)):
            self.assertEqual(getattr(self.api,name),value);self.assertEqual(getattr(bootstrap,name),value)
        self.assertEqual(list(self.api.WHEEL_MEMBERS),s.rows());self.assertEqual(list(bootstrap.WHEEL_MEMBERS),s.rows())
        self.assertEqual(bootstrap.canonical_inventory(s.rows()),self.api.canonical_inventory(s.rows()))
