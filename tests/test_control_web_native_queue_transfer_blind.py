"""Independent transfer RED: approved snapshot semantics, real private receipts.

Only public SessionChat seams/native0.161 schemas; no product source inspection.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
import native_queue_blind_support as s

TARGET='native-active-turn-A'
SUCCESSOR='native-successor-turn-B'
SNAPSHOT='Exact operator-displayed snapshot'
MAC='mac-client-correlation-not-uuid'


class SyntheticCrash(BaseException):pass


class TransferRPC(s.QueueRPC):
    def __init__(self,root):
        super().__init__(root);self.active_turn=TARGET;self.queue_pages[None]['data']=[s.native_row(mid=MAC,text=SNAPSHOT)]
        self.after_delete=None;self.before_steer=None;self.steer_error=None;self.history_items=[]
        self.steer_entered=__import__('threading').Event();self.steer_gate=__import__('threading').Event();self.steer_gate.set()
    def turns(self):
        return [dict(id=self.active_turn,status='inProgress',items=deepcopy(self.history_items))] if self.active_turn else []
    def __call__(self,method,params):
        if method=='thread/read':
            self.metadata_status=dict(type='active',activeFlags=[]) if self.active_turn else dict(type='idle')
            result=super().__call__(method,params)
            if params.get('includeTurns'):result['thread']['turns']=deepcopy(self.turns())
            return result
        if method=='thread/turns/list':
            self.calls.append((method,deepcopy(params)));rows=deepcopy(self.turns())
            for row in rows:self.item_sources[row['id']]=deepcopy(row['items'])
            if params.get('itemsView')=='notLoaded':rows=[{**row,'items':[]} for row in rows]
            return dict(data=rows,nextCursor=None)
        if method=='thread/queue/delete':
            value=super().__call__(method,params)
            if self.after_delete:self.after_delete()
            return value
        if method=='turn/steer':
            self.calls.append((method,deepcopy(params)))
            if self.before_steer:self.before_steer()
            self.steer_entered.set()
            if not self.steer_gate.wait(3):raise TimeoutError('Synthetic bounded steer ACK loss')
            if self.steer_error:raise self.steer_error
            if params['expectedTurnId']!=self.active_turn:raise RuntimeError('Synthetic native JSONRPC target rejection; not nondelivery proof')
            return dict(turnId=self.active_turn)
        return super().__call__(method,params)


class NativeQueueTransferBlind(s.QueueModuleCase):
    def setUp(self):
        super().setUp();self.rpc=TransferRPC(self.project);self.addCleanup(self.rpc.steer_gate.set)
        self.chat=self.new_chat()
    def transfer(self,action=s.ACTION,qid=s.QID,snapshot=SNAPSHOT,target=TARGET,chat=None):
        return self.invoke('send_queued_now','demo',s.SID,qid,action,snapshot,target,chat=chat)
    def payload_files(self,text=SNAPSHOT):
        def contains(value):
            if isinstance(value,str):return value==text
            if isinstance(value,dict):return any(contains(v) for v in value.values())
            if isinstance(value,list):return any(contains(v) for v in value)
            return False
        found=[]
        if self.receipts.exists():
            for path in self.receipts.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    try:
                        raw=path.read_bytes()
                        if text.encode('utf-8') in raw:found.append(path);continue
                        value=json.loads(raw)
                    except (OSError,UnicodeError,ValueError):continue
                    if contains(value):found.append(path)
        return found
    def assert_private_snapshot(self,text=SNAPSHOT):
        files=self.payload_files(text);self.assertTrue(files,'Recovery snapshot must be durable below injected receipt_root before native mutation')
        for path in files:
            self.assertEqual(path.stat().st_uid,os.getuid());self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertLessEqual(path.stat().st_size,128*1024)
            current=path.parent
            while current!=self.receipts.parent:
                self.assertFalse(current.is_symlink());self.assertEqual(current.stat().st_mode&0o777,0o700);current=current.parent
        return files
    def recovery(self):return self.queue()['recovery']
    def assert_unknown_replay(self,action=s.ACTION):
        before=deepcopy(self.mutation_methods());result=self.transfer(action=action,chat=self.new_chat())
        self.assertEqual(result['status'],'delivery_unknown');self.assertEqual(self.mutation_methods(),before)
        self.assertEqual(self.recovery()[0]['text'],SNAPSHOT)
        return result

    def test_busy_snapshot_reserved_before_delete_then_one_expected_turn_steer(self):
        # INV-SQUEUE-06A/B/C/D/F
        self.rpc.before_delete=self.assert_private_snapshot;self.rpc.before_steer=self.assert_private_snapshot
        result=self.transfer()
        self.assertEqual(result,dict(status='accepted',message_id=s.ACTION,queued_submission_id=s.QID,turn_id=TARGET,reason=None))
        self.assertEqual(self.mutation_methods(),['thread/queue/delete','turn/steer'])
        self.assertNotIn('thread/resume',self.rpc.methods(),'Send-now read proofs must never load/start another native context')
        params=self.rpc.calls_for('turn/steer')[0]
        self.assertEqual(set(params),{'threadId','input','expectedTurnId','clientUserMessageId'})
        # SOURCE correction: wire correlation belongs to this transfer action;
        # original opaque Mac clientID remains association metadata only.
        self.assertEqual((params['threadId'],params['expectedTurnId'],params['clientUserMessageId']),(s.SID,TARGET,s.ACTION))
        self.assertEqual(len(params['input']),1);self.assertEqual((params['input'][0]['type'],params['input'][0]['text']),('text',SNAPSHOT))
        self.assertEqual(self.payload_files(),[],'Accepted terminal tombstone must remove plaintext')
        self.assertEqual(self.recovery(),[])
        self.assertEqual(self.transfer(),result);self.assertEqual(len(self.rpc.calls_for('turn/steer')),1)

    def test_native_edit_after_confirmation_sends_exact_displayed_snapshot(self):
        # INV-SQUEUE-06A: expressly accepted by user; no fabricated deleted-version CAS.
        self.rpc.queue_pages[None]['data'][0]['input'][0]['text']='Newer concurrent Mac edit'
        self.assertEqual(self.transfer()['status'],'accepted')
        self.assertEqual(self.rpc.calls_for('turn/steer')[0]['input'][0]['text'],SNAPSHOT)

    def test_deleted_false_or_ambiguous_ACK_never_steers_and_replay_preserves_result(self):
        # INV-SQUEUE-06C
        self.rpc.deleted=False;changed=self.transfer();self.assertEqual(changed['status'],'changed')
        self.assertEqual(self.payload_files(),[]);self.assertEqual(self.rpc.calls_for('turn/steer'),[])
        self.assertEqual(self.transfer(),changed)
        self.rpc.deleted=True;self.rpc.delete_error=TimeoutError('Synthetic delete ACK loss')
        action='77777777-7777-4777-8777-777777777777'
        unknown=self.transfer(action=action);self.assertEqual(unknown['status'],'delivery_unknown')
        before=len(self.rpc.calls_for('thread/queue/delete'))
        self.assertEqual(self.transfer(action=action,chat=self.new_chat()),unknown)
        self.assertEqual(len(self.rpc.calls_for('thread/queue/delete')),before);self.assertEqual(self.rpc.calls_for('turn/steer'),[])
        self.assert_private_snapshot()

    def test_target_change_before_delete_is_terminal_changed_and_retains_native_row(self):
        # INV-SQUEUE-06B/E
        self.rpc.active_turn=SUCCESSOR
        result=self.transfer();self.assertEqual(result['status'],'changed')
        self.assertEqual(self.mutation_methods(),[]);self.assertEqual(self.payload_files(),[])
        self.assertEqual(self.rpc.queue_pages[None]['data'][0]['id'],s.QID)

    def test_mandatory_target_reproof_after_delete_returns_held_before_wire(self):
        # Owner clarification: second fresh target proof is mandatory before reserve/wire.
        self.rpc.after_delete=lambda:setattr(self.rpc,'active_turn',SUCCESSOR)
        result=self.transfer();self.assertEqual((result['status'],result['reason']),('held','target_changed'))
        self.assertEqual(self.mutation_methods(),['thread/queue/delete'])
        rows=self.recovery();self.assertEqual(len(rows),1);self.assertEqual((rows[0]['text'],rows[0]['status']),(SNAPSHOT,'held'))
        self.assert_private_snapshot()

    def test_target_race_after_last_proof_native_rejection_is_unknown_no_successor(self):
        # INV-SQUEUE-06B/D: a JSONRPC rejection is not generic nondelivery proof.
        self.rpc.before_steer=lambda:setattr(self.rpc,'active_turn',SUCCESSOR)
        result=self.transfer();self.assertEqual(result['status'],'delivery_unknown')
        params=self.rpc.calls_for('turn/steer');self.assertEqual(len(params),1);self.assertEqual(params[0]['expectedTurnId'],TARGET)
        self.assertFalse({'turn/start','thread/queue/start','thread/queue/add'}&set(self.rpc.methods()))
        self.assert_unknown_replay()

    def test_same_action_payload_mismatch_concurrent_clients_never_repeat_mutations(self):
        # INV-SQUEUE-06C
        self.rpc.steer_gate.clear();second=self.new_chat()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.transfer);self.assertTrue(self.rpc.steer_entered.wait(2),'Transfer never reached guarded steer')
            two=pool.submit(self.transfer,chat=second);time.sleep(.03)
            self.assertEqual(len(self.rpc.calls_for('thread/queue/delete')),1);self.assertEqual(len(self.rpc.calls_for('turn/steer')),1)
            self.rpc.steer_gate.set()
            for result in [first.result(3),two.result(3)]:self.assertIn(result['status'],['accepted','delivery_unknown'])
        before=deepcopy(self.mutation_methods())
        self.assertEqual(self.transfer(snapshot='Different action payload'),{'error':'invalid_request'})
        self.assertEqual(self.mutation_methods(),before)

    def test_crash_with_predelete_intent_never_speculates_delete_on_restart(self):
        # INV-SQUEUE-06C/D
        def crash():self.assert_private_snapshot();raise SyntheticCrash()
        self.rpc.before_delete=crash
        with self.assertRaises(SyntheticCrash):self.transfer()
        self.rpc.before_delete=None;self.assert_unknown_replay()
        self.assertEqual(self.rpc.calls_for('turn/steer'),[])

    def test_crash_after_steer_reservation_never_replays_wire_after_restart(self):
        # INV-SQUEUE-06D
        def crash():self.assert_private_snapshot();raise SyntheticCrash()
        self.rpc.before_steer=crash
        with self.assertRaises(SyntheticCrash):self.transfer()
        self.rpc.before_steer=None;self.assert_unknown_replay()
        self.assertEqual(len(self.rpc.calls_for('turn/steer')),1)

    def test_native_steer_ACK_loss_retains_snapshot_and_raw_error_is_not_public(self):
        # INV-SQUEUE-06D/E/F
        self.rpc.steer_error=TimeoutError('synthetic-private-native-error-detail')
        result=self.transfer();self.assertEqual(result['status'],'delivery_unknown')
        self.assertNotIn('synthetic-private-native-error-detail',json.dumps(result));self.assert_private_snapshot()
        self.assert_unknown_replay();self.assertEqual(len(self.rpc.calls_for('turn/steer')),1)

    def test_atomic_persistence_crash_after_delete_or_steer_does_not_replay(self):
        # INV-SQUEUE-06C/D/F: actual filesystem fault boundary, no private schema guessing.
        for phase in ['delete','steer']:
            with self.subTest(phase=phase):
                self.rpc=TransferRPC(self.project);self.chat=self.new_chat()
                action='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' if phase=='delete' else 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
                hit=[]
                def boundary(real):
                    def interrupted(src,dst,*args,**kwargs):
                        target=Path(os.fsdecode(dst))
                        if kwargs.get('dst_dir_fd') is not None:target=Path(os.readlink('/proc/self/fd/'+str(kwargs['dst_dir_fd'])))/target
                        eligible=bool(self.rpc.calls_for('thread/queue/delete')) and (phase=='delete' or bool(self.rpc.calls_for('turn/steer')))
                        if eligible and not hit and self.receipts in target.parents:
                            hit.append(True);raise SyntheticCrash()
                        return real(src,dst,*args,**kwargs)
                    return interrupted
                with patch('os.replace',boundary(os.replace)),patch('os.rename',boundary(os.rename)):
                    with self.assertRaises(SyntheticCrash):self.transfer(action=action)
                self.assertTrue(hit,'Atomic recovery persistence was not exercised')
                before=deepcopy(self.mutation_methods());result=self.transfer(action=action,chat=self.new_chat())
                self.assertEqual(result['status'],'delivery_unknown');self.assertEqual(self.mutation_methods(),before)
                self.assert_private_snapshot()

    def test_recovery_record_corruption_or_symlink_refuses_new_delete(self):
        # INV-SQUEUE-06F
        self.rpc.after_delete=lambda:setattr(self.rpc,'active_turn',SUCCESSOR)
        self.assertEqual(self.transfer()['status'],'held');path=self.assert_private_snapshot()[0]
        original=path.read_bytes();outside=self.base/'unrelated-fixture';outside.write_bytes(original);outside.chmod(0o600)
        for kind in ['corrupt','symlink']:
            with self.subTest(kind=kind):
                if path.is_symlink():path.unlink()
                if kind=='corrupt':path.write_text('{corrupt')
                else:path.unlink();path.symlink_to(outside)
                self.rpc.active_turn=TARGET;self.rpc.queue_pages[None]['data']=[s.native_row('safe-new-id',MAC,SNAPSHOT)]
                before=len(self.rpc.calls_for('thread/queue/delete'))
                action='cccccccc-cccc-4ccc-8ccc-cccccccccccc' if kind=='corrupt' else 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
                result=self.transfer(action=action,qid='safe-new-id')
                self.assertNotEqual(result.get('status'),'accepted');self.assertEqual(len(self.rpc.calls_for('thread/queue/delete')),before)
                self.assertEqual(outside.read_bytes(),original)

    def test_unicode_snapshot_and_64_retained_payload_limit_fail_before_delete(self):
        # INV-SQUEUE-06F
        self.rpc.after_delete=lambda:setattr(self.rpc,'active_turn',SUCCESSOR)
        text='🙂'*16000
        self.assertEqual(self.transfer(snapshot=text)['status'],'held');self.assert_private_snapshot(text)
        for index in range(1,64):
            self.rpc.active_turn=TARGET;self.rpc.queue_pages[None]['data']=[s.native_row('q-'+str(index),'mac-'+str(index),'small snapshot')]
            action=f'{index:08x}-dddd-4ddd-8ddd-dddddddddddd'
            self.assertEqual(self.transfer(action=action,qid='q-'+str(index),snapshot='small snapshot')['status'],'held')
        self.assertEqual(len(self.recovery()),64)
        self.rpc.active_turn=TARGET;self.rpc.queue_pages[None]['data']=[s.native_row('overflow',MAC,SNAPSHOT)]
        before=len(self.rpc.calls_for('thread/queue/delete'))
        result=self.transfer(action='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',qid='overflow')
        self.assertNotEqual(result.get('status'),'accepted');self.assertEqual(len(self.rpc.calls_for('thread/queue/delete')),before)
        self.assertEqual(self.rpc.queue_pages[None]['data'][0]['id'],'overflow')

    def test_known_Control_enqueue_receipt_no_longer_phantom_queued_after_transfer(self):
        # INV-SQUEUE-02 INV-SQUEUE-06E
        self.rpc.queue_pages[None]['data']=[];self.enqueue()
        self.assertEqual(self.transfer(snapshot=s.TEXT)['status'],'accepted')
        status=self.invoke('send_status','demo',s.SID,s.MID)
        self.assertEqual((status['status'],status['turn_id']),('accepted',TARGET))
        self.assertEqual(len(self.rpc.calls_for('thread/queue/add')),1)

    def test_Mac_history_proof_promotes_unknown_action_and_removes_recovery_text(self):
        # INV-SQUEUE-06D/E: native opaque clientID, exact immutable snapshot.
        self.rpc.steer_error=TimeoutError('Synthetic steer ACK loss');self.assertEqual(self.transfer()['status'],'delivery_unknown')
        self.rpc.history_items=[dict(id='native-steer-user',type='userMessage',clientId=s.ACTION,content=[dict(type='text',text=SNAPSHOT)])]
        before=deepcopy(self.mutation_methods());self.queue()
        result=self.transfer(chat=self.new_chat());self.assertEqual((result['status'],result['turn_id']),('accepted',TARGET))
        self.assertEqual(self.mutation_methods(),before);self.assertEqual(self.payload_files(),[]);self.assertEqual(self.recovery(),[])

    def test_context_change_after_delete_blocks_steer_and_hides_other_scope_recovery(self):
        # INV-SQUEUE-01 INV-SQUEUE-06F: never migrate an action to another context.
        self.rpc.after_delete=lambda:self.rpc.context.update(context_id='b'*64,context_generation=8)
        result=self.transfer()
        self.assertTrue(result.get('status') in ['held','delivery_unknown'] or result.get('error') in ['unavailable','stale'])
        self.assertEqual(self.rpc.calls_for('turn/steer'),[])
        current=self.queue()
        self.assertNotIn(SNAPSHOT,json.dumps(current),'Recovery text crossed admitted context boundary')
