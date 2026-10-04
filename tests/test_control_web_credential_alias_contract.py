"""Blind short credential alias masking contract; synthetic values only."""
import json
import unittest
import test_control_web_broker_contract as fixtures
from test_control_web_contract import QID

class CredentialAliasContract(unittest.TestCase):
    setUp = fixtures.BrokerContract.setUp
    write = fixtures.BrokerContract.write
    runner = fixtures.BrokerContract.runner

    # INV-WEB-05: all known credential aliases apply to every projected text field.
    def test_short_credential_aliases_are_masked_without_hiding_task(self):
        for alias in ('access_key','access-key','passwd','pwd'):
            with self.subTest(alias=alias):
                raw_value='fake42'
                text=f'{alias}={raw_value}'
                self.write('spec.yaml',{'type':'task','engine':'claude','name':text})
                self.write('state.g1.json',{'phase':'waiting','status_line':text})
                self.write('done.json',{'state':'requested','finalized':True,'envelope_key':'request-1','commit_sha':'a'*40,'summary':text})
                self.write('questions/'+QID+'.json',dict(qid=QID,kind='info',status='open',question=text,
                    envelope_key='request-1',asked_at=1,answer=text,answered_at='2026-10-04T00:00:00Z',
                    answered_by='web',event_published_at='2026-10-04T00:00:01Z'))
                result=self.backend.snapshot()
                self.assertNotIn('error',result)
                self.assertEqual(len(result['tasks']),1)
                task=result['tasks'][0]
                self.assertEqual(task['agent'],'task-one')
                self.assertFalse(task.get('unavailable'),result)
                self.assertNotIn(raw_value,json.dumps(result))
                # Inspect every public source projection, preventing drop-as-redaction.
                self.assertIn('***',task['name'])
                self.assertIn('***',task['status_line'])
                self.assertIn('***',task['result']['summary'])
                self.assertIn('***',task['questions'][0]['question'])
                self.assertIn('***',task['questions'][0]['saved_answer'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
