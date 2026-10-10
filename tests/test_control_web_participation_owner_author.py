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
