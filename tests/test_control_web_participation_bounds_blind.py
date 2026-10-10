"""Additional frozen bounds and invalidation effects: INV-PART-03/04/05/07."""
import json
import time
from unittest.mock import patch
from participation_blind_support import *


class ParticipationBoundsBlind(WireCase):
    def test_INV_PART_07_entry_overflow_revokes_actions_without_eviction_replay(self):
        # INV-PART-04 INV-PART-07
        dto,row=self.capture();self.assertEqual(self.answer(dto,row)['state'],'sent')
        self.wait_for(lambda:len(self.native.replies())==1)
        for identifier in range(2000,3026):self.native.emit(callback(identifier))
        self.synchronize();current=self.questions()
        self.assertTrue(current['coverage']['partial']);self.assertIn('limit',current['coverage']['reasons'])
        self.assertFalse(any(r['state']=='actionable' for r in current['questions']))
        self.answer(dto,row);self.answer(dto,row,action=ACTION2)
        time.sleep(.03);self.assertEqual(len(self.native.replies()),1)
        self.assertEqual(self.native.connections,1,'Overflow forced reconnect to recover exhausted authority')
        self.assertNotIn('thread/resume',self.native.methods())

    def test_INV_PART_07_retained_byte_overflow_not_only_entry_count(self):
        # INV-PART-07
        self.questions()
        value=form();value['questions'][0]['question']='x'*16000
        for identifier in range(1000,1140):self.native.emit(callback(identifier,value))
        self.synchronize();dto=self.questions()
        self.assertTrue(dto['coverage']['partial']);self.assertIn('limit',dto['coverage']['reasons'])
        self.assertFalse(any(r['state']=='actionable' for r in dto['questions']))
        self.assertLessEqual(len(json.dumps(dto,ensure_ascii=False,separators=(',',':')).encode()),96*1024)
        self.assertLessEqual(len(dto['questions']),16)
        self.assert_read_only()

    def test_INV_PART_07_selected_projection_truncation_never_resolves_omitted_pending(self):
        # INV-PART-05 INV-PART-07
        self.questions()
        for identifier in range(20):self.native.emit(callback(identifier))
        self.synchronize();dto=self.questions()
        self.assertLessEqual(len(dto['questions']),16)
        self.assertTrue(dto['coverage']['partial']);self.assertIn('limit',dto['coverage']['reasons'])
        self.assertFalse(any(r['state']=='closed' for r in dto['questions']))
        self.assert_read_only()

    def test_INV_PART_05_config_context_reset_revokes_old_handle(self):
        # INV-PART-05
        dto,row=self.capture();before=self.rpc.model_context()
        self.native.emit(dict(method='config/updated',params={}))
        self.wait_for(lambda:self.rpc.model_context()['context_generation']!=before['context_generation'])
        self.assertNotEqual(self.answer(dto,row).get('state'),'sent')
        self.assertFalse(any(r['state']=='actionable' for r in self.questions().get('questions',[])))
        self.assert_read_only()

    def test_INV_PART_05_thread_close_revokes_pending_authority(self):
        # INV-PART-05
        dto,row=self.capture();self.native.emit(dict(method='thread/closed',params=dict(threadId=SID)))
        self.synchronize()
        self.assertNotEqual(self.answer(dto,row).get('state'),'sent')
        self.assert_read_only()

    def test_INV_PART_05_new_turn_closes_blocking_preserves_nonblocking(self):
        # INV-PART-05
        self.questions();self.native.emit(callback(7));self.native.emit(callback(8,form(blocking=False)))
        dto=self.wait_for(lambda:(d if len((d:=self.questions()).get('questions',[]))==2 else None))
        self.native.emit(dict(method='turn/started',params=dict(threadId=SID,
            turn=dict(id='new-turn',status='inProgress',items=[]))))
        self.synchronize();now=self.questions()
        by_blocking={q['is_blocking']:q for q in now['questions']}
        self.assertNotEqual(by_blocking[True]['state'],'actionable')
        self.assertEqual(by_blocking[False]['state'],'actionable')
        self.assert_read_only()

    def test_INV_PART_04_resolved_after_attempted_before_possible_write_honest_closed(self):
        # INV-PART-04
        from websockets.sync.client import ClientConnection
        dto,row=self.capture();original=ClientConnection.send
        def before_write(connection,payload,*args,**kwargs):
            if 'method' not in json.loads(payload):self.native.resolved();time.sleep(.05)
            return original(connection,payload,*args,**kwargs)
        with patch.object(ClientConnection,'send',before_write):result=self.answer(dto,row)
        self.assertEqual((result['state'],result['reason']),('closed',None))
        self.answer(dto,row);self.answer(dto,row,action=ACTION2)
        time.sleep(.03);self.assertLessEqual(len(self.native.replies()),1)
        self.assertNotIn('applied',json.dumps(result).lower())

    def test_INV_PART_03_retained_frame_above_128KiB_has_no_action_or_callback_error(self):
        # INV-PART-03 INV-PART-07
        self.questions();value=form();value['questions'][0]['question']='x'*(128*1024+1)
        self.native.emit(callback(90,value));time.sleep(.08)
        dto=self.questions()
        self.assertFalse(any(row['state']=='actionable' for row in dto.get('questions',[])))
        self.assertEqual(self.native.replies(),[],'Over-limit callback received unauthorized JSON-RPC response/error')
        self.assertNotIn('thread/resume',self.native.methods())

    def test_INV_PART_01_grant_revoked_during_proof_no_answer_dispatch(self):
        # INV-PART-01 INV-PART-03 INV-PART-05
        dto,row=self.capture();self.native.hold_reads=True;self.native.read_gate.clear();self.native.read_entered.clear()
        results=[];errors=[]
        def dispatch():
            try:results.append(self.answer(dto,row))
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=dispatch);worker.start()
        try:
            self.assertTrue(self.native.read_entered.wait(1),'Current root/grant proof absent before dispatch')
            self.grants=[]
        finally:self.native.read_gate.set();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.assertNotEqual(results[0].get('state'),'sent')
        self.assert_read_only()
