"""Bounded SOURCE correction RED: action/turn/phase/payload evidence fences.

No implementation reads or private record keys. Public flows establish phases;
native0.161 fixture data provides both valid and adversarial history evidence.
"""
from copy import deepcopy
import native_queue_blind_support as s
import test_control_web_native_queue_transfer_blind as frozen
from test_control_web_native_queue_transfer_blind import TransferRPC,SyntheticCrash,TARGET,SUCCESSOR,SNAPSHOT,MAC


def user_item(identifier,client,text=SNAPSHOT):
    return dict(id=identifier,type='userMessage',clientId=client,content=[dict(type='text',text=text)])


class CorrelationRPC(TransferRPC):
    def __init__(self,root):super().__init__(root);self.extra_history=[]
    def turns(self):return super().turns()+deepcopy(self.extra_history)


class NativeQueueTransferCorrelationBlind(s.QueueModuleCase):
    # Borrow only public fixture helpers, not the frozen test methods.
    transfer=frozen.NativeQueueTransferBlind.transfer
    payload_files=frozen.NativeQueueTransferBlind.payload_files
    assert_private_snapshot=frozen.NativeQueueTransferBlind.assert_private_snapshot
    def setUp(self):
        super().setUp();self.rpc=CorrelationRPC(self.project);self.addCleanup(self.rpc.steer_gate.set)
        self.chat=self.new_chat()
    def attempted_unknown(self):
        self.rpc.steer_error=TimeoutError('Synthetic possible-wire ACK loss')
        result=self.transfer();self.assertEqual(result['status'],'delivery_unknown')
        self.assertEqual(len(self.rpc.calls_for('turn/steer')),1);self.assert_private_snapshot()
    def history(self,items,turn_id=TARGET):
        if turn_id==self.rpc.active_turn:self.rpc.history_items=deepcopy(items)
        else:self.rpc.extra_history=[dict(id=turn_id,status='completed',items=deepcopy(items))]
    def assert_retained(self,status='delivery_unknown',reason=None):
        before=deepcopy(self.mutation_methods());value=self.queue()
        rows=[row for row in value['recovery'] if row['action_id']==s.ACTION]
        files=self.payload_files()
        self.assertEqual(len(rows),1,f'Ineligible historical evidence erased action recovery: rows={len(rows)}, snapshot_files={len(files)}')
        self.assertEqual((rows[0]['status'],rows[0]['text']),(status,SNAPSHOT))
        if reason is not None:self.assertEqual(rows[0]['reason'],reason)
        self.assertEqual(self.mutation_methods(),before,'Read reconciliation performed a native mutation')
        self.assert_private_snapshot()

    def test_old_original_clientID_same_turn_cannot_prove_this_transfer(self):
        self.attempted_unknown()
        self.history([user_item('old-original-message',MAC)])
        self.assert_retained()

    def test_action_clientID_in_wrong_turn_cannot_confirm_or_remove_snapshot(self):
        self.attempted_unknown()
        # Both old and new correlations expose implementations missing either gate.
        self.history([user_item('old-original',MAC),user_item('wrong-action',s.ACTION)],'unrelated-completed-turn')
        self.assert_retained()

    def test_intent_without_steer_attempt_never_accepts_even_exact_action_history(self):
        def crash():self.assert_private_snapshot();raise SyntheticCrash()
        self.rpc.before_delete=crash
        with self.assertRaises(SyntheticCrash):self.transfer()
        self.rpc.before_delete=None
        self.assertEqual(self.rpc.calls_for('turn/steer'),[])
        self.history([user_item('legacy-original',MAC),user_item('unattempted-action',s.ACTION)])
        self.assert_retained()

    def test_held_without_steer_reservation_does_not_consume_matching_history(self):
        self.rpc.after_delete=lambda:setattr(self.rpc,'active_turn',SUCCESSOR)
        self.assertEqual(self.transfer()['status'],'held');self.assertEqual(self.rpc.calls_for('turn/steer'),[])
        self.history([user_item('legacy-original',MAC),user_item('unattempted-action',s.ACTION)],TARGET)
        self.assert_retained(status='held',reason='target_changed')

    def test_duplicate_action_matches_are_unknown_conflict_without_cleanup(self):
        self.attempted_unknown()
        self.history([user_item('legacy-original',MAC),user_item('action-one',s.ACTION),user_item('action-two',s.ACTION)])
        self.assert_retained(reason='conflict')

    def test_action_payload_conflict_cannot_be_overruled_by_old_original_match(self):
        self.attempted_unknown()
        self.history([user_item('legacy-original',MAC),user_item('conflicting-action',s.ACTION,'Different action payload')])
        self.assert_retained(reason='conflict')

    def original_receipt_then_transfer(self,*,lost_ack,current_text):
        self.rpc.queue_pages[None]['data']=[]
        self.rpc.add_error=TimeoutError('Synthetic enqueue ACK loss') if lost_ack else None
        enqueue=self.enqueue();self.assertEqual(enqueue['status'],'delivery_unknown' if lost_ack else 'queued')
        if lost_ack:self.assertIsNone(enqueue.get('queued_submission_id'))
        else:self.assertEqual(enqueue['queued_submission_id'],s.QID)
        self.rpc.add_error=None;self.rpc.queue_pages[None]['data'][0]['input'][0]['text']=current_text
        self.rpc.after_delete=lambda:setattr(self.rpc,'active_turn',SUCCESSOR)
        held=self.transfer(snapshot=s.TEXT);self.assertEqual(held['status'],'held')
        before=deepcopy(self.mutation_methods());original=self.invoke('send_status','demo',s.SID,s.MID)
        self.assertEqual(self.mutation_methods(),before);return original

    def test_lost_add_ACK_reused_clientID_and_snapshot_claim_cannot_bind_wrong_native_payload(self):
        result=self.original_receipt_then_transfer(lost_ack=True,current_text='Different native row sharing original clientID')
        self.assertEqual(result['status'],'delivery_unknown','Unbound original receipt was falsely retired by a snapshot claim')
        self.assertIsNone(result.get('queued_submission_id'))

    def test_lost_add_ACK_current_native_payload_proof_can_bind_original(self):
        result=self.original_receipt_then_transfer(lost_ack=True,current_text=s.TEXT)
        self.assertEqual((result['status'],result['queued_submission_id']),('held',s.QID))

    def test_known_original_qid_still_allows_native_edit_snapshot_semantics(self):
        result=self.original_receipt_then_transfer(lost_ack=False,current_text='Newer concurrent Mac edit')
        self.assertEqual((result['status'],result['queued_submission_id']),('held',s.QID))
