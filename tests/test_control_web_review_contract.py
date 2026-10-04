"""Independent blind review regression contracts; only synthetic secret patterns."""
import concurrent.futures
import hashlib
import json
import subprocess
import unittest
import test_control_web_broker_contract as registry_fixtures
import test_control_web_security_contract as auth_fixtures
from test_control_web_contract import QID

# INV-WEB-01 INV-WEB-02: shared durable state must be reread under a stable lock.
class SharedReplayContract(unittest.TestCase):
    setUp = auth_fixtures.DurableWebSecurity.setUp
    new_client = auth_fixtures.DurableWebSecurity.new_client
    login = auth_fixtures.DurableWebSecurity.login
    def test_two_apps_created_before_login_reject_same_step(self):
        first,second=self.new_client(),self.new_client()
        self.assertEqual(self.login(first).status_code,200)
        self.assertEqual(self.login(second).status_code,401)
    def test_concurrent_apps_only_one_consumes_same_step(self):
        clients=[self.new_client(),self.new_client()]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            statuses=list(executor.map(lambda client:self.login(client).status_code,clients))
        self.assertEqual(sorted(statuses),[200,401])

# INV-WEB-04 INV-WEB-05 INV-WEB-06: honest first-answer delivery and safe projection.
class RegistryReviewContract(unittest.TestCase):
    setUp = registry_fixtures.BrokerContract.setUp
    runner = registry_fixtures.BrokerContract.runner
    write = registry_fixtures.BrokerContract.write
    snapshot = registry_fixtures.BrokerContract.snapshot
    def saved(self,published=None):
        self.write('questions/'+QID+'.json',dict(qid=QID,kind='info',status='open',question='Question',
            envelope_key='request-1',asked_at=1,answer='original answer',answered_at='2026-10-04T00:00:00Z',
            answered_by='web',event_published_at=published))
    def test_saved_pending_new_text_is_already_after_original_published(self):
        self.saved()
        result=self.backend.answer('task-one',QID,'text','different new answer')
        self.assertEqual(result,{'status':'already'})
        record=json.loads((self.agent/'questions'/f'{QID}.json').read_text())
        self.assertEqual(record['answer'],'original answer')
        self.assertTrue(record['event_published_at'])
    def test_racing_original_answer_cannot_confirm_client_new_text(self):
        def racing_writer(args,**kwargs):
            self.saved('2026-10-04T00:00:01Z')
            return subprocess.CompletedProcess(args,0,'','')
        self.backend=self.mod.RegistryBackend(str(self.registry),str(self.bin),runner=racing_writer)
        self.assertEqual(self.backend.answer('task-one',QID,'text','different new answer'),{'status':'already'})
    def test_recover_uses_fixed_argv_and_keeps_original(self):
        self.saved()
        result=self.backend.answer('task-one',QID,'recover','')
        self.assertEqual(result,{'status':'already'})
        self.assertEqual(self.calls[-1][0],[str(self.bin/'claude-agent-answer'),str(self.agent),'--qid',QID,'--recover','--by','web'])
        self.assertEqual(json.loads((self.agent/'questions'/f'{QID}.json').read_text())['answer'],'original answer')
    def test_answered_pending_projection_readonly_saved_original(self):
        self.saved()
        question=self.snapshot()[0]['questions'][0]
        self.assertTrue(question['answered'])
        self.assertTrue(question['pending_delivery'])
        self.assertEqual(question['saved_answer'],'original answer')
        self.assertEqual(question.get('allowed_decisions',[]),[])
        self.saved('2026-10-04T00:00:01Z')
        question=self.snapshot()[0]['questions'][0]
        self.assertTrue(question['answered'])
        self.assertFalse(question['pending_delivery'])
    def test_known_credentials_redacted_across_text_projection(self):
        token='sk-ant-api03-'+'A'*80
        self.write('spec.yaml',{'type':'task','engine':'claude','name':token})
        self.write('state.g1.json',{'phase':'waiting','status_line':token})
        self.saved()
        question=json.loads((self.agent/'questions'/f'{QID}.json').read_text())
        question.update(question=token,answer=token)
        self.write('questions/'+QID+'.json',question)
        self.write('done.json',{'state':'requested','finalized':True,'envelope_key':'request-1','commit_sha':None,'summary':token})
        projected=self.backend.snapshot()
        self.assertNotIn(token,json.dumps(projected))
        self.assertEqual(projected['tasks'][0]['agent'],'task-one')
    def test_null_commit_hash_generation_uses_empty_string(self):
        self.write('done.json',{'state':'requested','finalized':True,'envelope_key':'request-1','commit_sha':None,'summary':'No git'})
        expected=hashlib.sha256(b'done-gen:request-1:').hexdigest()[:8]
        self.assertEqual(self.snapshot()[0]['result']['generation'],expected)
    def test_invalid_canonical_native_callback_never_offers_approve(self):
        self.write('spec.yaml',{'type':'task','engine':'codex','name':'task-one'})
        invalids={'generation':True,'request_id':True,'operation_id':'not-uuid','task_incarnation':'A'*32,
            'payload_fingerprint':'short','method':'shell/execute','status':'answered','thread_id':''}
        for field,value in invalids.items():
            with self.subTest(field=field):
                callback=registry_fixtures.canonical_callback()
                callback[field]=value
                self.write('questions/'+QID+'.json',dict(qid=QID,kind='permission',status='open',question='Approve?',envelope_key='request-1',asked_at=1,engine='codex',native_callback=callback))
                task=self.snapshot()[0]
                if not task.get('unavailable'):
                    for question in task.get('questions',[]):
                        self.assertNotIn('approve',question.get('allowed_decisions',[]))

if __name__ == '__main__':
    unittest.main(verbosity=2)
