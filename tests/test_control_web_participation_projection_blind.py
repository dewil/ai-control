"""Producer-order, execution proof and bounded coverage: frozen INV-PART-01/02/06/07."""
from copy import deepcopy
import json
import time
from unittest.mock import patch
from participation_blind_support import *


class ParticipationProjectionBlind(WireCase):
    def row(self):
        return self.wait_for(lambda:next((r for r in self.overview().get('rows',[]) if r['sid']==SID),None),
            'Loaded, root-proved native SID missing from common overview')

    def prove_history(self):
        value=self.chat.history('demo',SID)
        self.assertIn('turns',value,'Public bounded history must supply native producer witness')

    def test_INV_PART_02_activeFlag_wait_coarse_active_is_not_execution_proof(self):
        # INV-PART-02
        self.native.turns=[]
        self.native.status=dict(type='active',activeFlags=['waitingOnApproval','waitingOnUserInput'])
        row=self.row()
        self.assertEqual(row['activity'],'active');self.assertEqual(row['running'],'unconfirmed')
        self.assertEqual(row['waits'],['approval','question']);self.assertEqual(row['questions'],[])
        self.assertTrue(self.overview()['coverage']['partial'])
        self.assert_read_only()

    def test_INV_PART_02_exact_inProgress_without_waits_confirms_running(self):
        # INV-PART-02
        self.native.status=dict(type='active',activeFlags=[])
        self.native.turns=[dict(id=TURN,status='inProgress',items=[])]
        self.prove_history();row=self.row()
        self.assertEqual(row['running'],'confirmed')
        self.assert_read_only()

    def test_INV_PART_02_nonblocking_question_does_not_hide_independent_execution(self):
        # INV-PART-02
        self.native.status=dict(type='active',activeFlags=[])
        self.native.turns=[dict(id=TURN,status='completed',items=[]),
            dict(id='latest-executing-turn',status='inProgress',items=[])]
        dto,q=self.capture(params=form(blocking=False))
        self.assertEqual(q['state'],'actionable')
        self.prove_history();row=self.row()
        self.assertEqual(row['running'],'confirmed')
        self.assertIn('question',row['waits'])
        self.assert_read_only()

    def test_INV_PART_06_latest_completed_commentary_is_not_ready(self):
        # INV-PART-06
        self.native.turns=[dict(id=TURN,status='completed',items=[
            dict(id='commentary',type='agentMessage',phase='commentary',text='Looks finished')])]
        self.prove_history();row=self.row()
        self.assertTrue(row['result'] is None or row['result']['ready'] is False)
        self.assert_read_only()

    def test_INV_PART_06_latest_completed_last_final_answer_item_is_exact_witness(self):
        # INV-PART-06
        self.native.turns=[dict(id=TURN,status='completed',items=[
            dict(id='first-final',type='agentMessage',phase='final_answer',text='First answer'),
            dict(id='commentary',type='agentMessage',phase='commentary',text='Later commentary'),
            dict(id='last-final',type='agentMessage',phase='final_answer',text='Last answer')],completedAt=1800000000)]
        self.prove_history();row=self.row()
        self.assertIsNotNone(row['result']);self.assertTrue(row['result']['ready'])
        self.assertEqual((row['result']['turn_id'],row['result']['item_id']),(TURN,'last-final'))
        self.assert_read_only()

    def test_INV_PART_06_older_completed_final_cannot_win_over_latest_inProgress(self):
        # INV-PART-06
        self.native.turns=[dict(id=TURN,status='completed',items=[
            dict(id='old-final',type='agentMessage',phase='final_answer',text='Old answer')]),
            dict(id='new-turn',status='inProgress',items=[
                dict(id='new-final-before-tools',type='agentMessage',phase='final_answer',text='Not terminal yet')])]
        self.prove_history();row=self.row()
        self.assertTrue(row['result'] is None or not row['result']['ready'])
        self.assert_read_only()

    def test_INV_PART_06_prose_no_phase_or_empty_final_is_not_native_completion(self):
        # INV-PART-06
        for item in [dict(id='no-phase',type='agentMessage',text='Task done. Review approved.'),
                     dict(id='empty-final',type='agentMessage',phase='final_answer',text='')]:
            with self.subTest(item=item['id']):
                self.native.turns=[dict(id=TURN,status='completed',items=[item])]
                self.prove_history();row=self.row()
                self.assertTrue(row['result'] is None or not row['result']['ready'])
                self.assertEqual(row['questions'],[])
        self.assert_read_only()

    def test_INV_PART_06_failed_and_interrupted_never_ready(self):
        # INV-PART-06
        for status in ['failed','interrupted']:
            self.native.turns=[dict(id=TURN,status=status,items=[
                dict(id='final',type='agentMessage',phase='final_answer',text='Partial answer')])]
            self.prove_history();row=self.row()
            if row['result'] is not None:
                self.assertEqual(row['result']['status'],status);self.assertFalse(row['result']['ready'])
        self.assert_read_only()

    def test_INV_PART_07_many_loaded_sessions_bounded_reads_and_partial_never_false_zero(self):
        # INV-PART-07
        self.native.loaded=[f'{index:08x}-1111-4111-8111-111111111111' for index in range(80)]
        before=len(self.native.frames);value=self.overview()
        # Cached GET may precede the shared worker's first loaded-set discovery.
        # Await an actual published row, retaining the original RPC baseline and
        # every coverage/budget assertion below; no synchronous GET IO is needed.
        if not value.get('rows'):
            value=self.wait_for(lambda:(d if (d:=self.overview()).get('rows') else None),
                'Background loaded-set projection was not published within its 5s budget', timeout=5)
        self.assertTrue(value['coverage']['partial'])
        self.assertIn('limit',value['coverage']['reasons'])
        self.assertLessEqual(len(self.native.frames)-before,32)
        self.assertLessEqual(len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()),96*1024)
        self.assertLessEqual(len(value['rows']),256)
        self.assert_read_only()

    def test_INV_PART_07_HTTP_projection_reads_do_not_refresh_old_observed_at(self):
        # INV-PART-07
        self.native.status=dict(type='active',activeFlags=[])
        self.prove_history();first=self.row();observed=first['freshness']['observed_at']
        self.native.hold_reads=True;self.native.read_gate.clear()
        try:
            time.sleep(15.1)
            value=self.overview()
            rows=[r for r in value.get('rows',[]) if r['sid']==SID]
            self.assertTrue(value['coverage']['partial'])
            for row in rows:
                self.assertEqual(row['freshness']['observed_at'],observed)
                self.assertNotEqual(row['freshness']['state'],'fresh')
                self.assertEqual(row['running'],'unconfirmed')
                self.assertTrue(row['result'] is None or not row['result']['ready'])
        finally:self.native.read_gate.set()
        self.assert_read_only()
