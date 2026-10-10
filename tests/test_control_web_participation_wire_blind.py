"""Independent semantic RED for INV-PART-01..07; real local Unix RPC wire."""
from copy import deepcopy
import json
import threading
import time
from unittest.mock import patch
from participation_blind_support import *


class ParticipationWireBlind(WireCase):
    def test_INV_PART_01_reads_never_resume_reply_or_error_approval_unknown_callback(self):
        # INV-PART-01
        self.questions();self.overview()
        self.native.emit(callback(41,dict(threadId=SID,turnId=TURN,itemId='approval',
            command='synthetic approval command private'),method='item/commandExecution/requestApproval'))
        self.native.emit(callback(42,dict(threadId=SID),method='future/arbitraryRequest'))
        self.synchronize()
        for _ in range(3):
            dto=self.questions();self.overview()
            self.assertFalse(any(q['state']=='actionable' for q in dto['questions']))
            self.assertNotIn('synthetic approval command private',json.dumps(dto))
        self.assert_read_only()

    def test_INV_PART_03_exact_native_typed_ID_7_string7_and_large_int64(self):
        # INV-PART-03
        self.questions()
        for identifier in (7,'7',9223372036854775807): self.native.emit(callback(identifier))
        dto=self.wait_for(lambda:(d if len((d:=self.questions()).get('questions',[]))==3 else None))
        handles=[r['interaction_id'] for r in dto['questions']]
        self.assertEqual(len(set(handles)),3,'Typed IDs collapsed into one browser handle')
        for index,row in enumerate(dto['questions']):
            self.assertEqual(row['state'],'actionable')
            result=self.answer(dto,row,action=[ACTION,ACTION2,HANDLE][index])
            self.assertEqual(result['state'],'sent')
        self.wait_for(lambda:len(self.native.replies())==3)
        replies=self.native.replies()
        self.assertEqual({(type(r['id']),r['id']) for r in replies},
            {(int,7),(str,'7'),(int,9223372036854775807)})
        for reply in replies:
            self.assertEqual(set(reply),{'id','result'})
            self.assertEqual(reply['result'],{'answers':ANSWER})
        public=json.dumps(dto)
        self.assertNotIn('9223372036854775807',public)
        self.assertNotIn(str(self.project),public)

    def test_INV_PART_03_bool_float_IDs_and_method_conflicts_never_actionable(self):
        # INV-PART-03
        self.questions()
        for identifier in (True,1.5): self.native.emit(callback(identifier))
        self.native.emit(callback(91,method='future/arbitraryRequest'))
        self.native.emit(callback(91))
        self.synchronize();dto=self.questions()
        self.assertFalse(any(q['state']=='actionable' for q in dto['questions']))
        self.assert_read_only()

    def test_INV_PART_03_repeated_ID_changed_payload_revokes_original_form(self):
        # INV-PART-03
        dto,row=self.capture()
        value=form();value['questions'][0]['question']='Different native payload'
        self.native.emit(callback(7,value));self.synchronize()
        now=self.questions()
        self.assertFalse(any(q['state']=='actionable' for q in now['questions']))
        result=self.answer(dto,row)
        self.assertNotEqual(result.get('state'),'sent')
        self.assert_read_only()

    def test_INV_PART_03_secret_redacted_and_overlimit_question_native_only(self):
        # INV-PART-03
        variants=[]
        secret=form();secret['questions'][0].update(isSecret=True,question='SYNTHETIC_SECRET_PROMPT');variants.append(secret)
        oversized=form();oversized['questions'][0]['question']='x'*16385;variants.append(oversized)
        labels=form();labels['questions'][0]['options'][0]['label']='x'*1025;variants.append(labels)
        many=form();many['questions']=many['questions']*4;variants.append(many)
        self.questions()
        for index,value in enumerate(variants):self.native.emit(callback(100+index,value))
        self.synchronize();dto=self.questions()
        self.assertFalse(any(q['state']=='actionable' for q in dto['questions']))
        self.assertNotIn('SYNTHETIC_SECRET_PROMPT',json.dumps(dto))
        for row in dto['questions']:
            self.assertEqual(row['questions'],[],'Native-only form exposed partial answer controls')
        self.assert_read_only()

    def test_INV_PART_03_exact_label_answer_keys_unicode_and_byte_limits_before_reserve(self):
        # INV-PART-03
        dto,row=self.capture()
        invalid=[{}, {'extra':{'answers':['Exact option A']}},
            {'choice':{'answers':['0']}}, {'choice':{'answers':['exact option a']}},
            {'choice':{'answers':['Exact option A','Exact option B']}},
            {'choice':{'answers':['Exact option A'],'extra':True}},
            {'choice':{'answers':['x'*8001]}}, {'choice':{'answers':['\ud800']}},
            {'choice':{'answers':['Exact option A']},'extra':{'answers':['x']}}]
        for answer in invalid:
            with self.subTest(answer_shape=list(answer)):
                self.assertEqual(self.answer(dto,row,answers=answer),{'error':'invalid_request'})
        self.assert_read_only()
        self.assertEqual(self.answer(dto,row)['state'],'sent','Rejected validation consumed valid action UUID')
        self.wait_for(lambda:len(self.native.replies())==1)

    def test_INV_PART_03_free_text_requires_nonempty_and_preserves_exact_text(self):
        # INV-PART-03
        params=form();params['questions'][0].update(isOther=True,options=None)
        dto,row=self.capture(params=params)
        for value in ('',' \n '):
            self.assertEqual(self.answer(dto,row,answers={'choice':{'answers':[value]}}),{'error':'invalid_request'})
        text='  exact synthetic free text\n'
        self.assertEqual(self.answer(dto,row,answers={'choice':{'answers':[text]}})['state'],'sent')
        self.wait_for(lambda:len(self.native.replies())==1)
        self.assertEqual(self.native.replies()[0]['result'],{'answers':{'choice':{'answers':[text]}}})

    def test_INV_PART_04_same_UUID_replay_changed_digest_and_other_UUID_first_write_once(self):
        # INV-PART-04
        dto,row=self.capture()
        first=self.answer(dto,row)
        self.assertEqual(first['state'],'sent')
        self.assertEqual(self.answer(dto,row),first)
        self.assertEqual(self.answer(dto,row,answers={'choice':{'answers':['Exact option B']}}),{'error':'invalid_request'})
        self.answer(dto,row,action=ACTION2)
        self.wait_for(lambda:len(self.native.replies())==1)
        time.sleep(.03)
        self.assertEqual(len(self.native.replies()),1)
        self.assertNotIn('applied',json.dumps(first).lower())

    def test_INV_PART_04_concurrent_different_UUIDs_write_at_most_once(self):
        # INV-PART-04
        dto,row=self.capture();barrier=threading.Barrier(2);results=[];errors=[]
        def send(action):
            try:barrier.wait(2);results.append(self.answer(dto,row,action=action))
            except BaseException as error:errors.append(error)
        workers=[threading.Thread(target=send,args=(action,)) for action in (ACTION,ACTION2)]
        for worker in workers:worker.start()
        for worker in workers:worker.join(3);self.assertFalse(worker.is_alive())
        self.assertEqual(errors,[])
        self.wait_for(lambda:len(self.native.replies())>=1)
        self.assertEqual(len(self.native.replies()),1)
        self.assertTrue(all(r.get('state') in ['sent','delivery_unknown','closed'] for r in results))

    def test_INV_PART_04_unknown_before_possible_write_consumes_UUID_without_retry(self):
        # INV-PART-04
        from websockets.sync.client import ClientConnection
        dto,row=self.capture();original=ClientConnection.send;attempts=[]
        def fail(connection,payload,*args,**kwargs):
            value=json.loads(payload)
            if 'method' not in value:
                attempts.append(value);raise OSError('Synthetic ambiguous transport write')
            return original(connection,payload,*args,**kwargs)
        with patch.object(ClientConnection,'send',fail):
            result=self.answer(dto,row)
            self.assertEqual(result['state'],'delivery_unknown')
            self.answer(dto,row);self.answer(dto,row,action=ACTION2)
        self.assertEqual(len(attempts),1)
        self.assertEqual(self.native.replies(),[])
        self.assertNotIn('Synthetic ambiguous',json.dumps(result))

    def test_INV_PART_04_throw_after_actual_write_never_replays(self):
        # INV-PART-04
        from websockets.sync.client import ClientConnection
        dto,row=self.capture();original=ClientConnection.send;attempts=[]
        def fail_after(connection,payload,*args,**kwargs):
            value=json.loads(payload);outcome=original(connection,payload,*args,**kwargs)
            if 'method' not in value:
                attempts.append(value);raise OSError('Synthetic lost send return')
            return outcome
        with patch.object(ClientConnection,'send',fail_after):result=self.answer(dto,row)
        self.assertEqual(result['state'],'delivery_unknown')
        self.answer(dto,row);self.answer(dto,row,action=ACTION2)
        self.wait_for(lambda:len(self.native.replies())==1)
        self.assertEqual(len(attempts),1)
        self.assertEqual(len(self.native.replies()),1)

    def test_INV_PART_05_resolved_before_reserve_zero_wire_and_tombstone_beats_duplicate(self):
        # INV-PART-05
        dto,row=self.capture();self.native.resolved();self.synchronize()
        result=self.answer(dto,row)
        self.assertEqual(result['state'],'closed')
        self.native.emit(callback());self.synchronize()
        self.assertFalse(any(q['state']=='actionable' for q in self.questions()['questions']))
        self.answer(dto,row);self.answer(dto,row,action=ACTION2)
        self.assert_read_only()

    def test_INV_PART_05_resolved_before_any_callback_beats_late_request(self):
        # INV-PART-05
        self.questions();self.native.resolved();self.native.emit(callback());self.synchronize()
        self.assertFalse(any(q['state']=='actionable' for q in self.questions()['questions']))
        self.assert_read_only()

    def test_INV_PART_05_resolved_while_proof_pending_receiver_not_blocked(self):
        # INV-PART-05
        dto,row=self.capture();self.native.hold_reads=True;self.native.read_gate.clear();self.native.read_entered.clear()
        results=[];worker=threading.Thread(target=lambda:results.append(self.answer(dto,row)))
        worker.start()
        try:
            self.assertTrue(self.native.read_entered.wait(1),'Answer must recheck current binding before dispatch')
            self.native.resolved()
            started=time.monotonic();closed=self.closed()
            self.assertLess(time.monotonic()-started,.8,'Proof worker blocked receiver/projection')
            self.assertEqual(closed['questions'][0]['state'],'closed')
        finally:self.native.read_gate.set();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertEqual(results[0]['state'],'closed')
        self.assert_read_only()

    def test_INV_PART_04_resolved_during_successful_send_never_claims_winner(self):
        # INV-PART-04
        from websockets.sync.client import ClientConnection
        dto,row=self.capture();original=ClientConnection.send
        def resolved_after_write(connection,payload,*args,**kwargs):
            out=original(connection,payload,*args,**kwargs)
            if 'method' not in json.loads(payload):self.native.resolved();time.sleep(.05)
            return out
        with patch.object(ClientConnection,'send',resolved_after_write):result=self.answer(dto,row)
        self.assertEqual(result['state'],'closed');self.assertIsNone(result['reason'])
        self.wait_for(lambda:len(self.native.replies())==1)
        self.assertNotIn('applied',json.dumps(result).lower());self.assertNotIn('winner',json.dumps(result).lower())

    def test_INV_PART_04_closed_with_unknown_preserves_both_axes_and_no_retry(self):
        # INV-PART-04
        from websockets.sync.client import ClientConnection
        dto,row=self.capture();original=ClientConnection.send
        def unknown_resolved(connection,payload,*args,**kwargs):
            out=original(connection,payload,*args,**kwargs)
            if 'method' not in json.loads(payload):
                self.native.resolved();time.sleep(.05);raise OSError('Synthetic uncertain return')
            return out
        with patch.object(ClientConnection,'send',unknown_resolved):result=self.answer(dto,row)
        self.assertEqual((result['state'],result['reason']),('closed','delivery_unknown'))
        replay=self.answer(dto,row)
        self.assertEqual((replay['state'],replay['reason']),('closed','delivery_unknown'))
        self.answer(dto,row,action=ACTION2)
        self.wait_for(lambda:len(self.native.replies())==1)
        self.assertEqual(len(self.native.replies()),1)

    def test_INV_PART_05_blocking_terminal_closes_nonblocking_survives(self):
        # INV-PART-05
        self.questions();self.native.emit(callback(7));self.native.emit(callback(8,form(blocking=False)))
        dto=self.wait_for(lambda:(d if len((d:=self.questions()).get('questions',[]))==2 else None))
        ids={row['is_blocking']:row['interaction_id'] for row in dto['questions']}
        self.native.terminal();self.synchronize()
        current=self.questions();states={q['interaction_id']:q['state'] for q in current['questions']}
        self.assertNotEqual(states[ids[True]],'actionable')
        self.assertEqual(states[ids[False]],'actionable')
        row=next(q for q in current['questions'] if q['interaction_id']==ids[False])
        self.assertEqual(self.answer(current,row)['state'],'sent')
        self.wait_for(lambda:len(self.native.replies())==1)
        self.assertEqual(self.native.replies()[0]['id'],8)

    def test_INV_PART_05_missing_isBlocking_is_native_only_and_terminal_cannot_guess(self):
        # INV-PART-05
        params=form();del params['isBlocking']
        dto,row=self.capture(params=params)
        self.assertEqual(row['state'],'native_only');self.assertIsNone(row['is_blocking'])
        self.native.terminal();self.synchronize()
        current=self.questions()['questions'][0]
        self.assertEqual(current['state'],'native_only')
        self.assert_read_only()

    def test_INV_PART_01_root_and_grants_rechecked_before_export_and_answer(self):
        # INV-PART-01
        dto,row=self.capture();self.bound_root=self.base/'different';self.bound_root.mkdir(mode=0o700)
        self.assertFalse(any(q['state']=='actionable' for q in self.questions().get('questions',[])))
        self.assertNotEqual(self.answer(dto,row).get('state'),'sent')
        self.grants=[]
        self.assertEqual(self.overview().get('rows'),[])
        self.assert_read_only()

    def test_INV_PART_05_disconnect_reconnect_invalidates_captured_authority(self):
        # INV-PART-05
        dto,row=self.capture();self.native.connection.close()
        self.wait_for(lambda:self.rpc.model_context() is None or
            self.rpc.model_context().get('native_version') is None)
        result=self.answer(dto,row)
        self.assertNotEqual(result.get('state'),'sent')
        self.synchronize();self.questions()
        self.assertEqual(self.native.replies(),[])
        self.assertNotIn('thread/resume',self.native.methods())

    def test_INV_PART_07_owner_restart_changes_epoch_old_handle_cannot_write(self):
        # INV-PART-07
        dto,row=self.capture();self.chat=self.make_chat();new=self.questions()
        self.assertNotEqual(new['epoch'],dto['epoch'])
        self.assertEqual(self.answer(dto,row),{'error':'stale'})
        self.assert_read_only()
