"""Author storage/wire regressions using public queue APIs and actual OS faults."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import native_queue_blind_support as s
import test_control_web_native_queue_transfer_blind as transfer
import test_control_web_native_queue_core_author as core


class TransferPersistenceAuthor(s.QueueModuleCase):
    def setUp(self):
        super().setUp();self.rpc=transfer.TransferRPC(self.project);self.chat=self.new_chat()
    def transfer(self,chat=None):
        return self.invoke('send_queued_now','demo',s.SID,s.QID,s.ACTION,transfer.SNAPSHOT,transfer.TARGET,chat=chat)

    def test_terminal_atomic_write_failure_keeps_unknown_and_recovery_without_repeat(self):
        real=os.replace;hit=[]
        def fail(src,dst,*args,**kwargs):
            if self.rpc.calls_for('turn/steer') and not hit:
                hit.append(True);raise OSError('Synthetic private persistence failure')
            return real(src,dst,*args,**kwargs)
        with patch('os.replace',fail):result=self.transfer()
        self.assertEqual(hit,[True]);self.assertEqual(result['status'],'delivery_unknown')
        self.assertEqual(self.invoke('send_status','demo',s.SID,s.ACTION)['status'],'delivery_unknown')
        self.assertEqual(self.queue()['recovery'][0]['text'],transfer.SNAPSHOT)
        self.assertEqual(self.transfer(chat=self.new_chat())['status'],'delivery_unknown')
        self.assertEqual(self.mutation_methods(),['thread/queue/delete','turn/steer'])

    def test_original_enqueue_held_shadow_and_lost_ACK_association_are_payload_fenced(self):
        for mismatch in (False,True):
            with self.subTest(mismatch=mismatch):
                self.rpc=transfer.TransferRPC(self.project);self.chat=self.new_chat()
                mid='77777777-7777-4777-8777-777777777777' if mismatch else s.MID
                self.rpc.queue_pages[None]['data']=[];self.rpc.add_error=TimeoutError('Synthetic lost add ACK')
                self.assertEqual(self.enqueue(mid=mid)['status'],'delivery_unknown')
                if mismatch:self.rpc.queue_pages[None]['data'][0]['input'][0]['text']='Reused clientID different payload'
                self.rpc.after_delete=lambda:setattr(self.rpc,'active_turn',transfer.SUCCESSOR)
                action='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' if mismatch else s.ACTION
                snapshot='Reused clientID different payload' if mismatch else s.TEXT
                result=self.invoke('send_queued_now','demo',s.SID,s.QID,action,snapshot,transfer.TARGET)
                self.assertEqual(result['status'],'held')
                original=self.invoke('send_status','demo',s.SID,mid)
                self.assertEqual(original['status'],'delivery_unknown' if mismatch else 'held')
                self.assertEqual(len(self.rpc.calls_for('thread/queue/add')),1)
                self.assertEqual(self.rpc.calls_for('turn/steer'),[])

    def test_known_qid_mismatch_transfer_never_confirms_original_enqueue(self):
        self.rpc.queue_pages[None]['data']=[];self.enqueue()
        self.rpc.queue_pages[None]['data']=[s.native_row('different-qid',s.MID,s.TEXT)]
        result=self.invoke('send_queued_now','demo',s.SID,'different-qid',s.ACTION,s.TEXT,transfer.TARGET)
        self.assertEqual(result['status'],'accepted')
        original=self.invoke('send_status','demo',s.SID,s.MID)
        self.assertEqual(original['status'],'delivery_unknown')

    def test_active_proof_failure_does_not_disable_native_queue_or_private_recovery(self):
        module=self.module
        class Fault(transfer.TransferRPC):
            fail=False
            def __call__(inner,method,params):
                if method=='thread/turns/list' and inner.fail:
                    raise module.RPCRejected('Synthetic active read unavailable',-32601)
                return super().__call__(method,params)
        self.rpc=Fault(self.project);self.chat=self.new_chat()
        self.rpc.fail=True
        result=self.queue();self.assertTrue(result['supported']);self.assertEqual(len(result['rows']),1)
        self.assertFalse(result['send_now_supported']);self.assertEqual(result['send_now_reason'],'unavailable')
        self.rpc.fail=False;self.rpc.after_delete=lambda:setattr(self.rpc,'active_turn',transfer.SUCCESSOR)
        self.assertEqual(self.transfer()['status'],'held');self.rpc.fail=True
        result=self.queue();self.assertTrue(result['supported']);self.assertEqual(result['recovery'][0]['text'],transfer.SNAPSHOT)
        self.assertEqual(self.mutation_methods(),['thread/queue/delete'])

    def test_extended_transfer_record_limit_does_not_broaden_legacy_digest_records(self):
        self.rpc.queue_pages[None]['data']=[];self.assertEqual(self.enqueue()['status'],'queued')
        record=next(self.receipts.rglob(s.MID+'.json'));value=json.loads(record.read_text())
        value['padding']='x'*5000;record.write_text(json.dumps(value));record.chmod(0o600)
        before=list(self.mutation_methods())
        self.assertEqual(self.enqueue(),{'error':'unavailable'})
        self.assertEqual(self.mutation_methods(),before)


class TransferWireAuthor(unittest.TestCase):
    for name in ('setUp','start','shutdown','wire'):locals()[name]=getattr(core.QueueWireAuthor,name)
    def test_actual_recovery_projection_preserves_complete_rows_with_truthful_partial(self):
        self.backend.value=s.queue_dto([])
        text='🙂'*16000
        self.backend.value['recovery']=[dict(action_id=f'{i:08x}-dddd-4ddd-8ddd-dddddddddddd',
            queued_submission_id='q-'+str(i),text=text,status='held',reason='target_changed') for i in range(4)]
        self.start();result=self.wire(dict(op='session_queue',project='demo',sid=s.SID))
        self.assertNotIn('error',result);self.assertTrue(result['partial']);self.assertGreater(len(result['recovery']),0)
        self.assertLess(len(result['recovery']),4);self.assertEqual(result['recovery'][0]['text'],text)
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()),96*1024)


class TransferStatusHTTPAuthor(unittest.TestCase):
    import test_control_web_native_queue_transfer_http_blind as http
    setUp=http.NativeQueueTransferHTTPBlind.setUp
    login=http.NativeQueueTransferHTTPBlind.login
    headers=http.NativeQueueTransferHTTPBlind.headers
    def test_read_status_preserves_transfer_unknown_200_with_no_mutation(self):
        self.login()
        dto=dict(status='delivery_unknown',message_id=s.ACTION,queued_submission_id=s.QID,turn_id=None,reason=None)
        self.backend.session_send_status=lambda project,sid,mid:dto
        response=self.client.get('/api/session-send-status?project=demo&sid='+s.SID+'&message_id='+s.ACTION)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json(),dto)
        self.assertEqual(self.backend.calls,[])
