"""INV-DEVBUS-06: supplementary SOURCE-read regressions, not blind RED."""
import importlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from test_control_web_devbus_red import wire, NOW

class Safety(unittest.TestCase):
    def setUp(self):
        self.p=importlib.import_module('_control_web_devbus').Projection(clock=lambda:NOW)

    def ingest(self,payload):
        return self.p.ingest(wire('completed',payload=payload),'devbus.events.worker1',1)

    def test_bearer_inside_authorization_assignment_is_removed(self):
        self.ingest({'text':'Authorization: Bearer synthetic-private-value'})
        self.assertNotIn('synthetic-private-value',json.dumps(self.p.snapshot()))

    def test_producer_truncation_is_preserved(self):
        self.ingest({'text':'short result','output_truncated':True})
        self.assertTrue(self.p.snapshot()['tasks'][0]['output_truncated'])

    def test_exact_envelope_rejects_unknown_fields(self):
        value=json.loads(wire())
        value['extra']='not-v1'
        self.assertFalse(self.p.ingest(json.dumps(value).encode(),'devbus.events.worker1',1))

    def test_control_characters_cannot_reach_display(self):
        self.ingest({'text':'a\x00b\x1bc\nd\te'})
        text=self.p.snapshot()['tasks'][0]['result']
        self.assertNotIn('\x00',text)
        self.assertNotIn('\x1b',text)
        self.assertIn('\n',text)
        self.assertIn('\t',text)
