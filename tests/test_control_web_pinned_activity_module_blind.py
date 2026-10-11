"""Independent RED: INV-WPIN01/02 producer and native wire deadlines."""
from copy import deepcopy
import json
import math
from pathlib import Path
import threading
import time
import unittest
import uuid
from unittest.mock import patch
import native_queue_blind_support as q
import navigation_start_blind_support as nav
import pinned_activity_blind_support as a
import test_control_web_session_chat_contract as wire


class PinnedActivityModuleBlind(nav.ModuleCase):
    def setUp(self):
        super().setUp();self.rpc=a.ActivityRPC(self.project);self.chat=self.new_chat();self.pin_result=self.pin()
        self.rpc.calls.clear();self.rpc.fenced_calls.clear();self.rpc.reading=True
    def row(self):
        result=self.pins();self.assertEqual(result.get('schema'),2,'INV-WPIN02 producer must emit schema2')
        self.assertEqual(set(result),{'schema','server_now','items'});self.assertEqual(len(result['items']),1)
        self.assertIsInstance(result['server_now'],(int,float));self.assertNotIsInstance(result['server_now'],bool)
        self.assertTrue(math.isfinite(result['server_now']));self.assertGreaterEqual(result['server_now'],0)
        self.assertEqual(set(result['items'][0]),set(nav.pin_item())|a.FIELDS)
        return result['items'][0],result
    def test_native_metadata_read_is_fenced_readonly_and_store_bytes_unchanged(self):
        # INV-WPIN01 INV-WPIN02
        self.rpc.metadata[q.SID]=dict(updatedAt=1700000000,status=dict(type='active',activeFlags=['waitingOnApproval','waitingOnUserInput']))
        before={str(p):p.read_bytes() for p in self.pin_path.rglob('*') if p.is_file()}
        row,result=self.row();self.assertEqual(row['status'],'active');self.assertEqual(row['waits'],['approval','question'])
        self.assertEqual(row['last_activity'],1700000000);self.assertEqual(row['activity_state'],'fresh')
        self.assertLessEqual(1700000000,row['observed_at']);self.assertLessEqual(row['observed_at'],result['server_now'])
        self.assertEqual(self.rpc.calls_for('thread/read'),[dict(threadId=q.SID,includeTurns=False)])
        self.assertEqual(self.mutation_methods(),[]);self.assertEqual(set(self.rpc.methods()),{'thread/read'})
        self.assertTrue(all(0<t<=.250 for t in self.rpc.timeouts),'Every metadata call needs a <=250ms timeout')
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.pin_path.rglob('*') if p.is_file()})
        self.assertNotIn(str(self.base),json.dumps(result));self.assertNotIn('activeFlags',json.dumps(result))
    def test_known_statuses_wait_order_and_unknown_flags_are_not_disclosed(self):
        # INV-WPIN02
        for state,flags,wanted in [('idle',None,'idle'),('notLoaded',None,'notLoaded'),('systemError',None,'systemError'),
            ('active',[],'active'),('active',['waitingOnUserInput','privateFlag','waitingOnApproval'],'active'),
            ('invented',None,'unknown'),('active','waitingOnApproval','unknown'),('active',[7],'unknown')]:
            with self.subTest(state=state,flags=flags):
                status={'type':state}
                if flags is not None:status['activeFlags']=flags
                self.rpc.metadata[q.SID]=dict(status=status,updatedAt=1700000000)
                row,_=self.row();self.assertEqual(row['status'],wanted);self.assertEqual(row['last_activity'],1700000000)
                self.assertEqual(row['waits'],['approval','question'] if flags==['waitingOnUserInput','privateFlag','waitingOnApproval'] else [])
    def test_only_finite_native_updatedAt_in_range_not_fallback_or_future(self):
        # INV-WPIN02
        for value in [None,True,'1700000000',-1,float('nan'),float('inf'),253402300800,time.time()+86400]:
            with self.subTest(timestamp=repr(value)):
                self.rpc.metadata[q.SID]=dict(updatedAt=value,createdAt=1700000000,status=dict(type='idle'),observed_at=1700000000)
                row,_=self.row();self.assertIsNone(row['last_activity']);self.assertEqual(row['status'],'idle');self.assertEqual(row['activity_state'],'fresh');self.assertIsNotNone(row['observed_at'])
        self.rpc.metadata[q.SID]=dict(updatedAt=0,status=dict(type='idle'))
        self.assertEqual(self.row()[0]['last_activity'],0)
    def test_partial_failure_and_successful_unknown_replace_previous_native_snapshot(self):
        # INV-WPIN01 INV-WPIN02
        self.rpc.reading=False;self.rpc.read_id=q.OTHER;second=self.pin(sid=q.OTHER);self.rpc.reading=True
        self.rpc.metadata={q.SID:dict(updatedAt=1700000000,status=dict(type='idle')),q.OTHER:TimeoutError('Synthetic private timeout')}
        result=self.pins();self.assertEqual(result.get('schema'),2)
        rows={row['pin_id']:row for row in result['items']};good=rows[self.pin_result['pin_id']];bad=rows[second['pin_id']]
        self.assertEqual(good['last_activity'],1700000000);self.assertEqual(good['status'],'idle')
        self.assertEqual({k:bad[k] for k in a.FIELDS},dict(status='unknown',waits=[],last_activity=None,observed_at=None,activity_state='unavailable'))
        self.assertTrue(bad['available']);self.assertNotIn('private timeout',json.dumps(result))
        self.rpc.metadata[q.SID]=TimeoutError('Synthetic next failure')
        rows=self.pins()['items'];self.assertTrue(all(row['last_activity'] is None for row in rows),'No server activity cache after failure')
    def test_foreign_identity_and_final_authority_changes_hide_every_activity_field(self):
        # INV-WPIN01 INV-WPIN02
        foreign=self.base/'foreign';foreign.mkdir()
        for change in [dict(id=q.OTHER),dict(cwd=str(foreign))]:
            with self.subTest(change=change):
                self.rpc.metadata[q.SID]=dict(updatedAt=1700000000,status=dict(type='active',activeFlags=[]),**change)
                row,_=self.row();self.assertEqual(row,a.unknown(self.pin_result['pin_id'],available=False))
        self.rpc.metadata[q.SID]=dict(updatedAt=1700000000,status=dict(type='idle'))
        self.rpc.after_read=lambda sid:self.rpc.context.update(context_generation=8)
        self.assertEqual(self.row()[0],a.unknown(self.pin_result['pin_id'],available=False))
        self.rpc.after_read=None;self.rpc.context['context_generation']=9;self.chat=self.new_chat()
        self.rpc.after_read=lambda sid:setattr(self,'bound_root',foreign)
        self.assertEqual(self.row()[0],a.unknown(self.pin_result['pin_id'],available=False))
    def test_absolute_six_second_phase_budget_preserves_earlier_success_and_caps24(self):
        # INV-WPIN01
        self.rpc.reading=False
        for index in range(23):
            sid=str(uuid.UUID(int=(4<<76)|(8<<60)|index+1));self.rpc.read_id=sid;self.pin(sid=sid)
        self.rpc.reading=True;self.rpc.calls.clear();clock=[100.0]
        self.rpc.after_read=lambda sid:clock.__setitem__(0,clock[0]+1.1)
        # A synthetic clock jump tests the absolute budget without six seconds of sleeping.
        with patch('time.monotonic',side_effect=lambda:clock[0]):result=self.pins()
        self.assertEqual(result.get('schema'),2);reads=self.rpc.calls_for('thread/read')
        self.assertGreater(len(reads),0);self.assertLessEqual(len(reads),6,'Metadata phase continued after six-second absolute budget')
        self.assertLessEqual(len(reads),24);self.assertEqual(len(result['items']),24)
        self.assertTrue(any(row['activity_state']=='fresh' for row in result['items']))
        self.assertTrue(any(row['activity_state']=='unavailable' for row in result['items']))


class PinnedActivityNativeWireBlind(unittest.TestCase):
    setUp=wire.InteractiveRPCContract.setUp
    server=wire.InteractiveRPCContract.server
    receive=wire.InteractiveRPCContract.receive
    handshake=wire.InteractiveRPCContract.handshake
    client=wire.InteractiveRPCContract.client
    def test_production_InteractiveRPC_metadata_timeout_is_per_call_250ms(self):
        # INV-WPIN01: a fake honoring timeout cannot prove the production wire deadline.
        project=Path(self.tmp.name)/'project';project.mkdir(mode=0o700);armed=threading.Event();seen=threading.Event()
        def handler(ws):
            self.handshake(ws,native_version='0.161.0')
            while True:
                try:request=self.receive(ws)
                except Exception:return
                self.assertEqual(request['method'],'thread/read');self.assertFalse(request['params']['includeTurns'])
                if armed.is_set():
                    seen.set();time.sleep(.65)
                try:ws.send(json.dumps(dict(id=request['id'],result=dict(thread=dict(id=q.SID,cwd=str(project),name='Wire pin',status=dict(type='idle'),updatedAt=1700000000)))))
                except Exception:return
        self.server(handler);rpc=self.client()
        chat=self.module.SessionChat(rpc,lambda alias:str(project),lambda:['demo'],str(Path(self.tmp.name)/'receipts'),pin_store=str(Path(self.tmp.name)/'pins'))
        self.assertTrue(chat.pin('owner','demo',q.SID)['pinned']);armed.set();started=time.monotonic();result=chat.pins('owner');elapsed=time.monotonic()-started
        self.assertTrue(seen.wait(.1),'pins never reached the native metadata wire')
        self.assertLess(elapsed,.55,'Production RPC used its one-second default instead of <=250ms metadata bound')
        self.assertEqual(result.get('schema'),2);self.assertEqual(result['items'][0]['activity_state'],'unavailable');self.assertEqual(self.server_errors,[])
