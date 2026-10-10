"""Additive independent support DTO tests from public spec71473b6, no source oracle."""
from copy import deepcopy
import json
from pathlib import Path
import uuid
import native_queue_blind_support as q
import navigation_start_blind_support as s

class QueueStartBlockersModuleBlind(s.ModuleCase):
    def unknown(self,qid=q.QID,action=q.ACTION,sid=q.SID,chat=None):
        self.rpc.read_id=sid;self.rpc.queue_pages[None]['data']=[q.native_row(qid=qid)]
        self.rpc.start_failure=TimeoutError('Synthetic ACK lost')
        result=self.invoke('start_queued','demo',sid,qid,action,chat=chat)
        self.assertEqual(result['status'],'delivery_unknown');return result
    def eligible(self,chat=None,sid=q.SID,expected=None):
        result=self.invoke('queue_start_support','demo',sid,chat=chat)
        self.assertEqual(set(result),{'schema','supported','reason','blocked_queue_ids'})
        self.assertEqual((result['schema'],result['supported'],result['reason']),(1,True,None))
        self.assertEqual(set(result['blocked_queue_ids']),set(expected or []))
        self.assertEqual(len(result['blocked_queue_ids']),len(set(result['blocked_queue_ids'])))
        return result
    def receipt_bytes(self):return {str(path):path.read_bytes() for path in self.records()}

    def test_support_contains_exact_unknown_qid_across_restart_rotation_and_native_absence(self):
        # INV-QSTART-04 INV-QSTART-05 INV-QSTART-06 INV-QSTART-08
        self.unknown();before=deepcopy(self.rpc.calls);files=self.receipt_bytes()
        self.eligible(expected=[q.QID]);self.assertEqual(self.receipt_bytes(),files)
        self.rpc.queue_pages[None]['data']=[]
        for changes in [dict(transport_generation=4,context_generation=8),dict(context_id='b'*64,context_generation=9)]:
            self.rpc.context.update(changes);self.eligible(chat=self.new_chat(),expected=[q.QID])
            self.assertEqual(self.receipt_bytes(),files,'Support changed durable unknown receipts')
        self.assertEqual(self.wire_starts(),[dict(threadId=q.SID,queuedSubmissionId=q.QID)])
        self.assertNotIn('thread/resume',[name for name,_ in self.rpc.calls[len(before):]])
        serialized=json.dumps(self.eligible(expected=[q.QID]))
        for private in [q.ACTION,q.MID,str(self.project),'a'*64,'b'*64,q.TEXT]:self.assertNotIn(private,serialized)

    def test_support_is_per_SID_and_other_qid_remains_startable(self):
        # INV-QSTART-04 INV-QSTART-06
        self.unknown(qid='other-SID-only',action=s.NEXT,sid=q.OTHER)
        self.rpc.read_id=q.SID;self.eligible(expected=[])
        self.unknown();self.eligible(expected=[q.QID])
        self.rpc.read_id=q.OTHER;self.eligible(sid=q.OTHER,expected=['other-SID-only'])
        self.rpc.read_id=q.SID;self.rpc.start_failure=None
        self.rpc.queue_pages[None]['data']=[q.native_row(qid='safe-other-qid')]
        result=self.start_action(action=str(uuid.uuid4()),qid='safe-other-qid',chat=self.new_chat())
        self.assertEqual(result['status'],'started');self.eligible(expected=[q.QID])

    def test_same_SID_different_canonical_root_gets_no_foreign_blockers(self):
        # INV-QSTART-04 INV-QSTART-06
        self.unknown();self.eligible(expected=[q.QID])
        other=self.base/'another-project';other.mkdir(mode=0o700)
        self.bound_root=other;self.rpc.root=other
        self.rpc.list_response['data'][0]['cwd']=str(other)
        self.eligible(chat=self.new_chat(),expected=[])
        self.assertEqual(len(self.wire_starts()),1)

    def test_unrelated_unknown_send_receipt_is_not_queue_start_blocker(self):
        # INV-QSTART-04 INV-QSTART-06 INV-QSTART-08
        self.rpc.start_error=TimeoutError('Synthetic ordinary send ACK lost')
        self.assertEqual(self.chat.send('demo',q.SID,q.MID,'Ordinary message')['status'],'delivery_unknown')
        self.eligible(expected=[])
        self.assertEqual(self.invoke('send_status','demo',q.SID,q.MID)['status'],'delivery_unknown')
        self.assertEqual(self.wire_starts(),[])

    def test_corrupt_or_unreadable_unknown_scan_never_returns_eligible_subset(self):
        # INV-QSTART-04 INV-QSTART-08
        self.unknown();self.eligible(expected=[q.QID])
        candidates=[path for path in self.records() if q.ACTION.encode() in path.read_bytes()]
        self.assertTrue(candidates,'Synthetic durable action file must exist')
        path=candidates[0];original=path.read_bytes();path.write_bytes(b'{broken')
        result=self.support();self.assertEqual(result,{'error':'unavailable'})
        self.assertEqual(path.read_bytes(),b'{broken','Support reset corrupt receipt')
        path.write_bytes(original);self.eligible(chat=self.new_chat(),expected=[q.QID])
        outside=self.base/'outside-record';outside.write_bytes(original);outside.chmod(0o600)
        path.unlink();path.symlink_to(outside)
        self.assertEqual(self.support(),{'error':'unavailable'})
        self.assertEqual(outside.read_bytes(),original)
        self.assertEqual(len(self.wire_starts()),1)
