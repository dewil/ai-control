"""Independent INV-SQUEUE-01..05,07,09; native0.161 schema fixtures only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import time
import native_queue_blind_support as s


class NativeQueueModuleBlind(s.QueueModuleCase):
    def test_enqueue_uses_native_add_only_inherit_and_durable_digest_before_wire(self):
        # INV-SQUEUE-02 INV-SQUEUE-03 INV-SQUEUE-07 INV-SQUEUE-09
        self.rpc.before_add=lambda:self.assert_reservation(s.MID)
        result=self.enqueue()
        self.assertEqual(result,dict(status='queued',message_id=s.MID,queued_submission_id=s.QID))
        calls=self.rpc.calls_for('thread/queue/add');self.assertEqual(len(calls),1)
        self.assertEqual(set(calls[0]),{'threadId','input','clientUserMessageId'})
        self.assertEqual((calls[0]['threadId'],calls[0]['clientUserMessageId']),(s.SID,s.MID))
        self.assertEqual(len(calls[0]['input']),1);self.assertEqual((calls[0]['input'][0]['type'],calls[0]['input'][0]['text']),('text',s.TEXT))
        self.assertEqual(calls[0]['input'][0].get('text_elements',[]),[])
        self.assertEqual(self.mutation_methods(),['thread/queue/add'])
        self.assertNotIn('thread/resume',self.rpc.methods())
        self.assertTrue(any(method=='thread/queue/list' for method in self.rpc.methods()),'Capability proof must be read-only list')
        self.assert_reservation(s.MID)

    def test_exact_uuid_retry_restart_and_payload_mismatch_never_readds(self):
        # INV-SQUEUE-02
        first=self.enqueue();self.assertEqual(self.enqueue(),first)
        restarted=self.new_chat()
        self.assertEqual(self.invoke('enqueue','demo',s.SID,s.MID,s.TEXT,chat=restarted),first)
        self.assertEqual(self.enqueue(text='Different immutable payload'),{'error':'invalid_request'})
        self.assertEqual(len(self.rpc.calls_for('thread/queue/add')),1)

    def test_simultaneous_clients_reserve_one_native_add(self):
        # INV-SQUEUE-02: distinct SessionChat objects, shared real receipt directory.
        self.rpc.add_gate.clear();second=self.new_chat()
        with ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(self.enqueue)
            self.assertTrue(self.rpc.add_entered.wait(2),'Enqueue never reached native add')
            two=pool.submit(self.invoke,'enqueue','demo',s.SID,s.MID,s.TEXT,chat=second)
            time.sleep(.03);self.assertEqual(len(self.rpc.calls_for('thread/queue/add')),1)
            self.rpc.add_gate.set()
            for result in [one.result(3),two.result(3)]:self.assertIn(result['status'],['queued','delivery_unknown'])
        self.assertEqual(len(self.rpc.calls_for('thread/queue/add')),1)

    def test_add_ACK_loss_absence_restart_never_authorizes_replay(self):
        # INV-SQUEUE-02 INV-SQUEUE-03
        self.rpc.add_error=TimeoutError('Synthetic add ACK loss')
        self.assertEqual(self.enqueue()['status'],'delivery_unknown')
        self.rpc.queue_pages[None]['data']=[];self.rpc.add_error=None
        self.assertEqual(self.invoke('enqueue','demo',s.SID,s.MID,s.TEXT,chat=self.new_chat())['status'],'delivery_unknown')
        self.assertEqual(self.invoke('send_status','demo',s.SID,s.MID)['status'],'delivery_unknown')
        self.assertEqual(len(self.rpc.calls_for('thread/queue/add')),1)
        self.assertNotIn('turn/start',self.rpc.methods())

    def test_unknown_reconciles_exact_queue_then_history_without_second_add(self):
        # INV-SQUEUE-02 INV-SQUEUE-08: authoritative history outranks an existing native row.
        self.rpc.add_error=TimeoutError('Synthetic add ACK loss');self.enqueue()
        queued=self.invoke('send_status','demo',s.SID,s.MID)
        self.assertEqual((queued['status'],queued['queued_submission_id']),('queued',s.QID))
        self.rpc.history_message()
        accepted=self.invoke('send_status','demo',s.SID,s.MID)
        self.assertEqual((accepted['status'],accepted['turn_id']),('accepted',s.TURN))
        self.assertEqual(self.enqueue()['status'],'accepted','Replay must not downgrade accepted proof to queued ACK')
        self.assertEqual(len(self.rpc.calls_for('thread/queue/add')),1)

    def test_payload_mismatch_and_ambiguous_rows_remain_unknown_conflict(self):
        # INV-SQUEUE-02 INV-SQUEUE-04 INV-SQUEUE-08
        self.rpc.add_error=TimeoutError('Synthetic lost ACK');self.enqueue()
        for rows in [[s.native_row(text='Wrong clientID payload')],
                     [s.native_row(),s.native_row('second-native-id')]]:
            with self.subTest(rows=len(rows)):
                self.rpc.queue_pages[None]['data']=deepcopy(rows)
                result=self.invoke('send_status','demo',s.SID,s.MID)
                self.assertEqual((result['status'],result.get('reason')),('delivery_unknown','conflict'))
        self.assertEqual(self.mutation_methods(),['thread/queue/add'])

    def test_list_includes_Mac_rows_in_native_order_and_no_private_paths(self):
        # INV-SQUEUE-01 INV-SQUEUE-03 INV-SQUEUE-04
        rows=[s.native_row('mac-first','mac-not-a-uuid','Mac synthetic input'),s.native_row()]
        self.rpc.queue_pages[None]['data']=rows
        result=self.queue()
        self.assertEqual(result,s.queue_dto([s.public_row('mac-first','mac-not-a-uuid','Mac synthetic input'),s.public_row()]))
        self.assertNotIn(str(self.base),json.dumps(result));self.assertEqual(self.mutation_methods(),[])
        self.assertNotIn('thread/resume',self.rpc.methods())

    def test_bounded_four_page_partial_retains_visible_cancel_authority(self):
        # INV-SQUEUE-04 INV-SQUEUE-05: partial is not corrupt; visible Mac row can be cancelled.
        self.rpc.queue_pages={}
        for page in range(4):
            self.rpc.queue_pages[None if page==0 else 'c'+str(page)]=dict(data=[s.native_row(f'n-{page}-{i}',f'mac-{page}-{i}','text') for i in range(64)],nextCursor='c'+str(page+1))
        result=self.queue();self.assertTrue(result['partial']);self.assertEqual(len(result['rows']),256)
        self.assertEqual(len(self.rpc.calls_for('thread/queue/list')),4)
        self.assertTrue(all(params['limit']==64 and params['threadId']==s.SID for params in self.rpc.calls_for('thread/queue/list')))
        self.assertEqual(self.cancel('n-0-0')['status'],'cancelled')
        self.assertEqual(self.rpc.calls_for('thread/queue/delete'),[dict(threadId=s.SID,queuedSubmissionId='n-0-0')])

    def test_corrupt_duplicate_cycle_and_nontext_never_authorize_delete(self):
        # INV-SQUEUE-04 INV-SQUEUE-05
        cases=[
          {None:dict(data=[s.native_row(),s.native_row()],nextCursor=None)},
          {None:dict(data=[s.native_row(),s.native_row('other-id')],nextCursor=None)},
          {None:dict(data=[s.native_row()],nextCursor='loop'),'loop':dict(data=[],nextCursor='loop')},
          {None:dict(data=[dict(id=s.QID,clientUserMessageId=s.MID,input=[dict(type='localImage',path='/synthetic/never-public.png')])],nextCursor=None)},
          {None:dict(data=[s.native_row(text='x'*16001)],nextCursor=None)},
        ]
        for pages in cases:
            with self.subTest(case=repr(pages)[:60]):
                self.rpc.queue_pages=deepcopy(pages);self.rpc.calls.clear()
                result=self.cancel()
                self.assertIn(result.get('error'),['unavailable','stale','invalid_request'])
                self.assertEqual(self.rpc.calls_for('thread/queue/delete'),[])

    def test_transport_list_failure_is_unavailable_not_unsupported_or_empty(self):
        # INV-SQUEUE-04
        self.rpc.queue_pages[None]=TimeoutError('Synthetic read failure')
        result=self.queue()
        self.assertTrue(result.get('error') in ['unavailable','stale'] or result.get('reason') in ['unavailable','stale'])
        self.assertNotEqual(result.get('reason'),'unsupported_queue')
        self.assertFalse(result.get('supported',False));self.assertEqual(self.mutation_methods(),[])

    def test_wrong_root_full_thread_and_generation_fence_before_native_mutation(self):
        # INV-SQUEUE-01 INV-SQUEUE-04
        self.rpc.queue_pages[None]['data']=[s.native_row()]
        self.rpc.read_id=s.OTHER
        self.assertEqual(self.enqueue(),{'error':'stale'});self.assertEqual(self.mutation_methods(),[])
        self.rpc.read_id=s.SID
        self.rpc.after_queue=lambda:self.rpc.context.update(context_generation=8)
        result=self.cancel();self.assertIn(result.get('error'),['stale','unavailable'])
        self.assertEqual(self.rpc.calls_for('thread/queue/delete'),[])
        queue_calls=[call for call in self.rpc.fenced_calls if call[0].startswith('thread/queue/')]
        self.assertTrue(queue_calls,'Queue operations must use call_in_generation')

    def test_explicit_override_rejected_before_add_and_old_version_stays_unsupported(self):
        # INV-SQUEUE-07
        selection=dict(catalog_id='b'*64,model_id='ui-model',effort='high')
        self.assertEqual(self.enqueue(selection=selection),{'error':'queue_unsupported_selection'})
        self.assertEqual(self.mutation_methods(),[])
        self.rpc.context['native_version']='0.160.0'
        result=self.queue()
        self.assertEqual((result['supported'],result['reason'],result['rows']), (False,'unsupported_queue',[]))
        self.assertFalse(result['send_now_supported']);self.assertEqual(self.mutation_methods(),[])

    def test_cancel_Mac_row_independent_of_edits_and_own_action_receipt(self):
        # INV-SQUEUE-05 INV-SQUEUE-09
        self.rpc.queue_pages[None]['data']=[s.native_row(mid='mac-correlation'),s.native_row('untouched','mac-other','Other order')]
        def concurrent_edit():
            self.assert_reservation(s.ACTION)
            self.rpc.queue_pages[None]['data'][0]['input'][0]['text']='Edited elsewhere immediately before native delete'
        self.rpc.before_delete=concurrent_edit
        result=self.cancel();self.assertEqual(result,dict(status='cancelled',message_id=s.ACTION,queued_submission_id=s.QID))
        self.assertEqual(self.cancel(),result)
        self.assertEqual(self.cancel('untouched'),{'error':'invalid_request'})
        self.assertEqual(len(self.rpc.calls_for('thread/queue/delete')),1)
        self.assertEqual([row['id'] for row in self.rpc.queue_pages[None]['data']],['untouched'])
        self.assertNotIn('text',result,'Native deleted bool cannot attest deleted text/version')

    def test_cancel_false_and_lost_ACK_preserve_distinct_non_replayable_results(self):
        # INV-SQUEUE-05
        self.rpc.queue_pages[None]['data']=[s.native_row()];self.rpc.deleted=False
        first=self.cancel();self.assertEqual(first['status'],'changed');self.assertEqual(self.cancel(),first)
        self.assertEqual(len(self.rpc.calls_for('thread/queue/delete')),1)
        self.rpc.deleted=True;self.rpc.delete_error=TimeoutError('Synthetic delete ACK loss')
        second_action='77777777-7777-4777-8777-777777777777'
        unknown=self.cancel(action=second_action);self.assertEqual(unknown['status'],'delivery_unknown')
        replay=self.invoke('cancel_queued','demo',s.SID,s.QID,second_action,chat=self.new_chat())
        self.assertEqual(replay,unknown);self.assertEqual(len(self.rpc.calls_for('thread/queue/delete')),2)
        self.assertFalse({'turn/start','turn/steer','thread/queue/start'}&set(self.rpc.methods()))
