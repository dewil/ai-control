"""Author regressions for bounded proof and immutable callback answer ownership."""
from participation_blind_support import *


class ParticipationOwnerAuthor(WireCase):
    def test_completed_pool_refresh_stays_under_32_native_calls(self):
        self.native.loaded=[f'{index:08x}-1111-4111-8111-111111111111' for index in range(80)]
        self.native.turns=[dict(id=TURN,status='completed',items=[
            dict(id='final',type='agentMessage',phase='final_answer',text='Bounded answer')])]
        before=len(self.native.frames)
        value=self.overview()
        self.assertIn('rows',value)
        self.assertIn('limit',value['coverage']['reasons'])
        self.assertLessEqual(len(self.native.frames)-before,32)
        self.assert_read_only()

    def test_action_uuid_cannot_bind_to_a_second_callback(self):
        dto,first=self.capture(7)
        self.native.emit(callback(8))
        current=self.wait_for(lambda:(d if len((d:=self.questions())['questions'])==2 else None))
        second=next(q for q in current['questions'] if q['interaction_id']!=first['interaction_id'])
        self.assertEqual(self.answer(dto,first)['state'],'sent')
        self.assertEqual(self.answer(current,second),{'error':'invalid_request'})
        self.wait_for(lambda:len(self.native.replies())==1)
        self.assertEqual(len(self.native.replies()),1)

    def test_malformed_fields_do_not_disconnect_or_recover_reused_native_id(self):
        self.questions()
        self.native.emit(callback(20,form(threadId=[])))
        self.native.emit(callback(21,form(questions=None)))
        self.native.connection.send(json.dumps(callback(22,form(questions=[dict(id='bad',header='',question='\ud800',isOther=False,isSecret=False,options=None)])), ensure_ascii=True))
        self.native.emit(callback(23,form(questions=[dict(id='huge',header='',question='x'*(128*1024+1),isOther=False,isSecret=False,options=None)])))
        self.native.emit(callback(23))
        self.synchronize()
        value=self.questions()
        self.assertFalse(any(row['state']=='actionable' for row in value['questions']))
        self.assertEqual(self.native.connections,1)
        self.assert_read_only()

    def test_resolved_before_reserve_still_binds_consumed_action_digest(self):
        dto,row=self.capture()
        self.native.resolved();self.synchronize()
        self.assertEqual(self.answer(dto,row)['state'],'closed')
        self.assertEqual(self.answer(dto,row,answers={'choice':{'answers':['Exact option B']}}),
                         {'error':'invalid_request'})
        self.assert_read_only()

    def test_reply_deadline_cannot_be_late_local_sent_or_replayed(self):
        from websockets.sync.client import ClientConnection
        from unittest.mock import patch
        dto,row=self.capture();original=ClientConnection.send
        self.rpc.timeout=.1
        def late(connection,payload,*args,**kwargs):
            if 'method' not in json.loads(payload):time.sleep(.2)
            return original(connection,payload,*args,**kwargs)
        with patch.object(ClientConnection,'send',late):result=self.answer(dto,row)
        self.assertEqual(result['state'],'delivery_unknown')
        self.assertEqual(result['reason'],'delivery_unknown')
        self.answer(dto,row);self.answer(dto,row,action=ACTION2)
        self.assertEqual(len(self.native.replies()),0)

    def test_oversized_unknown_callback_payload_not_retained_as_private_identity(self):
        import gc
        import tracemalloc
        self.questions()
        payload=callback(100,method='future/'+'x'*(512*1024))
        gc.collect();tracemalloc.start()
        try:
            before=tracemalloc.get_traced_memory()[0]
            for identifier in range(100,124):
                payload['id']=identifier;self.native.emit(payload)
            self.synchronize();gc.collect()
            retained=tracemalloc.get_traced_memory()[0]-before
            # Serialized 2MiB cap plus interpreter/transport bookkeeping margin.
            self.assertLess(retained,4*1024*1024)
            self.assert_read_only()
        finally:tracemalloc.stop()

    def test_callback_outside_bounded_current_native_turns_has_no_controls(self):
        self.questions()
        self.native.emit(callback(30,form(turnId='foreign-blocking-turn')))
        self.native.emit(callback(31,form(blocking=False,turnId='foreign-nonblocking-turn')))
        self.synchronize()
        self.assertFalse(any(row['state']=='actionable' for row in self.questions()['questions']))
        self.assert_read_only()

    def test_context_reset_cannot_rebind_consumed_action_uuid_to_new_callback(self):
        dto,row=self.capture()
        self.assertEqual(self.answer(dto,row)['state'],'sent')
        before=self.rpc.model_context()['context_generation']
        self.native.emit(dict(method='config/updated',params={}))
        self.wait_for(lambda:self.rpc.model_context()['context_generation']!=before)
        self.assertIn('turns',self.chat.history('demo',SID))
        fresh,new_row=self.capture(8)
        self.assertEqual(self.answer(fresh,new_row),{'error':'invalid_request'})
        self.wait_for(lambda:len(self.native.replies())==1)
        self.assertEqual(len(self.native.replies()),1)
