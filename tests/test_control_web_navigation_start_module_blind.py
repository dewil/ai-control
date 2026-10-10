"""Independent PIN/QSTART RED from frozen65a271c6 specs, no source inspection."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import uuid
from unittest.mock import patch
import native_queue_blind_support as q
import navigation_start_blind_support as s

class PinnedSessionsBlind(s.ModuleCase):
    def test_identity_title_independent_replay_order_and_durable_unpin(self):
        # INV-PIN-01 INV-PIN-03 INV-PIN-05
        first=self.pin();self.assertEqual(set(first),{'schema','pin_id','pinned'});uuid.UUID(first['pin_id'])
        self.assertTrue(first['pinned']);self.rpc.title='Renamed verified title'
        self.assertEqual(self.pin(),first)
        self.rpc.read_id=q.OTHER;second=self.pin(sid=q.OTHER)
        self.assertNotEqual(first['pin_id'],second['pin_id'])
        self.rpc.read_id=q.SID
        rows=self.pins(chat=self.new_chat())['items']
        self.assertEqual([row['pin_id'] for row in rows],[second['pin_id'],first['pin_id']])
        self.assertEqual(self.unpin(first['pin_id']),dict(schema=1,pin_id=first['pin_id'],pinned=False))
        self.assertEqual(self.unpin(first['pin_id']),dict(schema=1,pin_id=first['pin_id'],pinned=False))
        self.assertEqual(self.mutation_methods(),[]);self.assertNotIn('thread/resume',self.rpc.methods())

    def test_unit_principal_namespaces_have_disjoint_storage(self):
        # INV-PIN-02: local preference namespaces, production admits owner only.
        a=self.pin();b=self.pin(principal='second-owner')
        self.assertNotEqual(a['pin_id'],b['pin_id'])
        self.assertEqual([x['pin_id'] for x in self.pins()['items']],[a['pin_id']])
        self.assertEqual([x['pin_id'] for x in self.pins('second-owner')['items']],[b['pin_id']])
        self.unpin(b['pin_id']);self.assertEqual(len(self.pins('second-owner')['items']),1)

    def test_root_namespace_or_grant_drift_only_opaque_unavailable(self):
        # INV-PIN-01 INV-PIN-04 INV-PIN-07
        pin=self.pin();expected=s.pin_item(pin['pin_id'],available=False)
        self.rpc.context.update(context_id='b'*64,context_generation=8)
        self.assertEqual(self.pins()['items'],[expected])
        self.rpc.context.update(context_id='a'*64,context_generation=9)
        self.bound_root=self.base/'remapped';self.bound_root.mkdir(mode=0o700)
        self.assertEqual(self.pins()['items'],[expected])
        self.assertNotIn(str(self.base),json.dumps(self.pins()))
        self.unpin(pin['pin_id']);self.assertEqual(self.pins()['items'],[])

    def test_offline_unpin_ignores_unrelated_unknown_send_and_start(self):
        # INV-PIN-03 INV-PIN-05 INV-PIN-07: no receipt coupling.
        pin=self.pin();self.rpc.start_failure=TimeoutError('Synthetic ACK lost')
        self.assertEqual(self.start_action()['status'],'delivery_unknown')
        self.rpc.start_error=TimeoutError('Synthetic unrelated send ACK lost')
        self.chat.send('demo',q.SID,q.MID,'Unrelated user input')
        def offline(*args,**kwargs):raise AssertionError('Offline unpin must not read native')
        before=deepcopy(self.rpc.calls)
        with patch.object(type(self.rpc),'__call__',offline):
            self.assertEqual(self.unpin(pin['pin_id'])['pinned'],False)
        self.assertEqual(self.rpc.calls,before)
        self.assertEqual(self.invoke('send_status','demo',q.SID,q.MID)['status'],'delivery_unknown')
        self.assertEqual(self.start_action(chat=self.new_chat())['status'],'delivery_unknown')

    def test_compatible_unknown_native_read_can_pin_without_mutation(self):
        # INV-PIN-03
        self.rpc.context.update(native_version='0.999.0')
        result=self.pin();self.assertTrue(result['pinned']);self.assertEqual(len(self.pins()['items']),1)
        self.assertEqual(self.mutation_methods(),[]);self.assertNotIn('thread/resume',self.rpc.methods())

    def test_capacity_and_corrupt_private_storage_fail_without_reset(self):
        # INV-PIN-06
        for index in range(24):
            sid=str(uuid.UUID(int=(4<<76)|(8<<60)|index+1));self.rpc.read_id=sid
            self.assertTrue(self.pin(sid=sid)['pinned'])
        before=self.pins();sid=str(uuid.uuid4());self.rpc.read_id=sid
        self.assertIn('error',self.pin(sid=sid));self.assertEqual(self.pins(),before)
        paths=list(self.pin_path.rglob('*.json'));self.assertTrue(paths,'Public injected private store must contain durable JSON')
        for path in paths:
            self.assertEqual(path.stat().st_mode&0o777,0o600);self.assertLessEqual(path.stat().st_size,128*1024)
        target=paths[0];target.write_bytes(b'{broken');self.assertEqual(self.pins(),{'error':'unavailable'})
        self.assertEqual(target.read_bytes(),b'{broken','Corruption must not reset preferences')

    def test_unsafe_symlink_hardlink_and_repository_store_refused(self):
        # INV-PIN-06
        self.assertIn('pin_store',__import__('inspect').signature(self.module.SessionChat).parameters,'Isolated pin_store test seam missing')
        outside=self.base/'outside';outside.mkdir(mode=0o700)
        for kind in ['symlink','repo']:
            path=self.base/('unsafe-'+kind)
            if kind=='symlink':path.symlink_to(outside,target_is_directory=True)
            else:path.mkdir(mode=0o700);(path/'.git').mkdir()
            self.pin_path=path;result=self.pin(chat=self.new_chat());self.assertEqual(result,{'error':'unavailable'})
        self.pin_path=self.base/'safe';self.assertTrue(self.pin(chat=self.new_chat())['pinned'])
        target=next(self.pin_path.rglob('*.json'));os.link(target,self.base/'linked')
        self.assertEqual(self.pins(chat=self.new_chat()),{'error':'unavailable'})

    def test_atomic_write_failure_retains_previous_pin(self):
        # INV-PIN-05 INV-PIN-06
        first=self.pin();self.rpc.read_id=q.OTHER
        with patch('os.replace',side_effect=OSError('Synthetic fs failure')),patch('os.rename',side_effect=OSError('Synthetic fs failure')):
            self.assertEqual(self.pin(sid=q.OTHER),{'error':'unavailable'})
        self.rpc.read_id=q.SID
        self.assertEqual([row['pin_id'] for row in self.pins(chat=self.new_chat())['items']],[first['pin_id']])

class NativeQueueStartBlind(s.ModuleCase):
    def test_exact_fenced_selected_row_typed_ACK_and_replay(self):
        # INV-QSTART-01 INV-QSTART-03 INV-QSTART-05 INV-QSTART-06
        self.assertEqual(self.support(),dict(schema=1,supported=True,reason=None,blocked_queue_ids=[]))
        self.rpc.before_wire=lambda:self.assert_reservation(q.ACTION)
        result=self.start_action();self.assertEqual(result,self.start_result())
        self.assertEqual(self.wire_starts(),[dict(threadId=q.SID,queuedSubmissionId=q.QID)])
        self.assertEqual(self.mutation_methods(),['thread/queue/start']);self.assertNotIn('thread/resume',self.rpc.methods())
        self.assertIn(('thread/queue/start',self.wire_starts()[0],3,7),self.rpc.fenced_calls)
        self.assertEqual(self.start_action(chat=self.new_chat()),result);self.assertEqual(len(self.wire_starts()),1)

    def test_busy_missing_unloaded_unknown_version_prevent_wire(self):
        # INV-QSTART-01 INV-QSTART-02
        self.rpc.metadata_status={'type':'active','activeFlags':[]}
        self.assertEqual(self.start_action(),self.start_result('busy',reason='not_idle'));self.assertEqual(self.wire_starts(),[])
        self.rpc.metadata_status={'type':'idle'};self.rpc.queue_pages[None]['data']=[]
        self.assertEqual(self.start_action(action=s.NEXT),self.start_result('changed',action=s.NEXT,reason='row_missing'))
        for state,version in [('notLoaded','0.161.0'),('idle','0.999.0')]:
            self.rpc.metadata_status={'type':state};self.rpc.context['native_version']=version
            self.assertIn('error',self.start_action(action=str(uuid.uuid4())))
        self.assertEqual(self.mutation_methods(),[]);self.assertNotIn('thread/resume',self.rpc.methods())

    def test_malformed_ACK_and_native_poststart_RPC_error_are_unknown(self):
        # INV-QSTART-02 INV-QSTART-05: RPC storage failure can follow native effect.
        for index,ack in enumerate([{}, {'turn':{'id':q.TURN}}, {'turn':{'id':False,'status':'inProgress','items':[]}},
                                  {'turn':{'id':q.TURN,'status':'invented','items':[]}}]):
            self.rpc.start_ack=ack;action=str(uuid.uuid4());qid='ack-'+str(index)
            self.rpc.queue_pages[None]['data']=[q.native_row(qid=qid)]
            self.assertEqual(self.start_action(action=action,qid=qid)['status'],'delivery_unknown')
        self.rpc.queue_pages[None]['data']=[q.native_row()]
        self.rpc.start_failure=self.module.RPCRejected('Synthetic storage failed after start',-32600)
        self.assertEqual(self.start_action()['status'],'delivery_unknown')
        self.assertEqual(len(self.wire_starts()),5)

    def test_unknown_qid_guard_survives_restart_generation_and_context_rotation(self):
        # INV-QSTART-03 INV-QSTART-04 INV-QSTART-06 INV-QSTART-08
        self.rpc.start_failure=TimeoutError('Synthetic ACK loss')
        self.assertEqual(self.start_action()['status'],'delivery_unknown')
        for context in [dict(transport_generation=4,context_generation=8),dict(context_id='b'*64,context_generation=9)]:
            self.rpc.context.update(context)
            result=self.start_action(action=str(uuid.uuid4()),chat=self.new_chat())
            self.assertEqual(result['status'],'delivery_unknown');self.assertEqual(len(self.wire_starts()),1)
        self.rpc.start_failure=None;self.rpc.queue_pages[None]['data']=[q.native_row(qid='different-qid')]
        self.assertEqual(self.start_action(action=s.NEXT,qid='different-qid',chat=self.new_chat())['status'],'started')
        self.assertEqual(len(self.wire_starts()),2)

    def test_old_queue_clientID_history_and_missing_row_cannot_promote_unknown(self):
        # INV-QSTART-04 INV-QSTART-05
        self.rpc.start_failure=TimeoutError('Synthetic ACK loss');self.start_action()
        self.rpc.history_message(mid=q.MID);self.rpc.queue_pages[None]['data']=[]
        result=self.invoke('send_status','demo',q.SID,q.ACTION)
        self.assertEqual(result['status'],'delivery_unknown');self.assertIsNone(result['turn_id'])
        self.queue();self.assertEqual(self.start_action(chat=self.new_chat())['status'],'delivery_unknown')
        self.assertEqual(len(self.wire_starts()),1)

    def test_parallel_UUID_one_winner_and_changed_payload_rejected(self):
        # INV-QSTART-03
        self.rpc.gate.clear()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.start_action);self.assertTrue(self.rpc.entered.wait(2))
            second=pool.submit(self.start_action,chat=self.new_chat());self.rpc.gate.set()
            for future in [first,second]:self.assertIn(future.result(3)['status'],['started','delivery_unknown'])
        self.assertEqual(len(self.wire_starts()),1)
        self.assertEqual(self.start_action(qid='different-qid'),{'error':'invalid_request'})

    def test_crash_after_reservation_never_replays_and_postwire_write_crash_unknown(self):
        # INV-QSTART-03 INV-QSTART-08
        def crash():self.assert_reservation(q.ACTION);raise s.Crash()
        self.rpc.before_wire=crash
        with self.assertRaises(s.Crash):self.start_action()
        self.rpc.before_wire=None
        self.assertEqual(self.start_action(chat=self.new_chat())['status'],'delivery_unknown')
        self.assertEqual(len(self.wire_starts()),1)

    def test_final_context_and_root_guard_refuse_publication_and_other_receipts_untouched(self):
        # INV-QSTART-05 INV-QSTART-06
        self.rpc.start_error=TimeoutError('Synthetic unrelated send')
        self.chat.send('demo',q.SID,q.MID,'Unrelated receipt')
        self.rpc.after_wire=lambda:self.rpc.context.update(context_generation=8)
        self.assertEqual(self.start_action()['status'],'delivery_unknown')
        self.assertEqual(self.invoke('send_status','demo',q.SID,q.MID)['status'],'delivery_unknown')
        history=self.invoke('history','demo',q.SID)
        self.assertFalse(any(x.get('message_id')==q.ACTION for x in history.get('recent_sends',[])))

    def test_context_or_canonical_root_change_after_listing_blocks_wire(self):
        # INV-QSTART-01 INV-QSTART-06
        self.rpc.after_queue=lambda:self.rpc.context.update(context_generation=8)
        self.assertIn('error',self.start_action());self.assertEqual(self.wire_starts(),[])
        self.rpc.after_queue=None;self.rpc.context['context_generation']=9;self.chat=self.new_chat()
        remapped=self.base/'second-root';remapped.mkdir(mode=0o700)
        self.rpc.after_queue=lambda:setattr(self,'bound_root',remapped)
        self.assertIn('error',self.start_action(action=s.NEXT));self.assertEqual(self.wire_starts(),[])

    def test_postwire_atomic_receipt_crash_cannot_repeat_start(self):
        # INV-QSTART-03 INV-QSTART-08
        hit=[]
        def boundary(real):
            def wrapped(src,dst,*args,**kwargs):
                target=Path(os.fsdecode(dst))
                if kwargs.get('dst_dir_fd') is not None:
                    target=Path(os.readlink('/proc/self/fd/'+str(kwargs['dst_dir_fd'])))/target
                if self.wire_starts() and self.receipts in target.parents and not hit:
                    hit.append(True);raise s.Crash()
                return real(src,dst,*args,**kwargs)
            return wrapped
        with patch('os.replace',boundary(os.replace)),patch('os.rename',boundary(os.rename)):
            with self.assertRaises(s.Crash):self.start_action()
        self.assertTrue(hit,'Final receipt atomic store boundary was not reached')
        self.assertEqual(self.start_action(chat=self.new_chat())['status'],'delivery_unknown')
        self.assertEqual(len(self.wire_starts()),1)


import unittest
import test_control_web_session_chat_contract as chat_contract

class NativeQueueStartWireBlind(unittest.TestCase):
    setUp=chat_contract.InteractiveRPCContract.setUp
    server=chat_contract.InteractiveRPCContract.server
    receive=chat_contract.InteractiveRPCContract.receive
    handshake=chat_contract.InteractiveRPCContract.handshake
    client=chat_contract.InteractiveRPCContract.client
    def test_exact_queue_start_allowlist_on_reviewed_connection_no_replay(self):
        # INV-QSTART-01 INV-QSTART-03
        def handler(ws):
            self.handshake(ws,native_version='0.161.0')
            request=self.receive(ws)
            self.assertEqual(request['method'],'thread/queue/start')
            self.assertEqual(request['params'],dict(threadId=q.SID,queuedSubmissionId=q.QID))
            ws.close()
        self.server(handler);rpc=self.client()
        with self.assertRaises(Exception):rpc('thread/queue/start',dict(threadId=q.SID,queuedSubmissionId=q.QID))
        self.assertEqual(sum(frame.get('method')=='thread/queue/start' for frame in self.frames),1)
        self.assertEqual(self.server_errors,[])
