"""INV-CAP-07: a validated history observation belongs to root/fullsid/live context.

Independent public contracts only. No requirement for a multi-entry registry:
a single bounded last successful history observation is sufficient.
"""
import copy
import time
import unittest
from test_control_web_read_capabilities_support import NativeCase, SID, OTHER

NOT_OBSERVED = {'supported': None, 'reason': 'not_observed'}
OBSERVED = {'supported': True, 'reason': None}


class HistoryCapabilityScopeBlind(NativeCase):
    def capability(self, chat, project, sid):
        result=self.invoke(lambda:self.require(chat,'capabilities')(project,sid))
        self.assertIn('operations',result,'A scoped valid thread read must produce the fixed capability DTO')
        self.assertEqual(result['operations']['sessions_read'],OBSERVED)
        return result['operations']['history_read']

    def history_a(self, chat=None):
        chat=self.chat if chat is None else chat
        value=self.invoke(lambda:chat.history('demo',SID))
        self.assertIn('turns',value,'The source history must be validated before testing observation scope')
        self.assertEqual(self.capability(chat,'demo',SID),OBSERVED)
        return copy.deepcopy(self.rpc.model_context())

    def corrupt_b_item_wrapper(self):
        calls=[]
        def wrong_turn(ws,request,result):
            if request['method']=='thread/items/list' and request['params'].get('threadId')==OTHER:
                calls.append((request['params']['threadId'],request['params']['turnId']))
                result['data'][0]['turnId']='55555555-5555-4555-8555-555555555555'
        self.native.before_reply=wrong_turn
        return calls

    def test_successful_history_A_does_not_advertise_history_B_in_same_connection(self):
        context=self.history_a();before=[frame for frame in self.native.frames if frame.get('method') in ('thread/turns/list','thread/items/list')]
        self.assertEqual(self.capability(self.chat,'demo',OTHER),NOT_OBSERVED,
                         'History A cannot authorize history_read=true for unobserved fullsid B')
        after=[frame for frame in self.native.frames if frame.get('method') in ('thread/turns/list','thread/items/list')]
        self.assertEqual(after,before,'Capabilities must not probe B history to manufacture an observation')
        self.assertEqual(self.rpc.model_context(),context);self.assertEqual(self.native.connections,1)
        self.assert_read_only()

    def test_malformed_history_B_cannot_inherit_history_A_observation(self):
        context=self.history_a();calls=self.corrupt_b_item_wrapper()
        result=self.invoke(lambda:self.chat.history('demo',OTHER))
        self.assert_closed(result);self.assertNotIn('turns',result)
        self.assertEqual(len(calls),1,'The malformed B item wrapper must reach the actual validator')
        self.assertEqual(self.capability(self.chat,'demo',OTHER),NOT_OBSERVED,
                         'Rejected B history cannot publish or borrow a positive observation from A')
        self.assertEqual(self.rpc.model_context(),context);self.assert_read_only()

    def test_standalone_malformed_history_wrapper_is_rejected_and_not_advertised(self):
        # Independent control for the review's wrapper-projection concern.
        self.assertEqual(self.capability(self.chat,'demo',OTHER),NOT_OBSERVED)
        calls=self.corrupt_b_item_wrapper();result=self.invoke(lambda:self.chat.history('demo',OTHER))
        self.assert_closed(result);self.assertNotIn('turns',result);self.assertEqual(len(calls),1)
        self.assertEqual(self.capability(self.chat,'demo',OTHER),NOT_OBSERVED)
        self.assert_read_only()

    def test_fresh_transport_generation_invalidates_both_thread_observations(self):
        old=self.history_a();self.native.ws.close();deadline=time.monotonic()+1
        while self.rpc.model_context() is not None and time.monotonic()<deadline:time.sleep(.01)
        fresh=self.prepare()
        self.assertEqual(fresh['context_id'],old['context_id'])
        self.assertGreater(fresh['transport_generation'],old['transport_generation'])
        self.assertEqual(self.capability(self.chat,'demo',SID),NOT_OBSERVED)
        self.assertEqual(self.capability(self.chat,'demo',OTHER),NOT_OBSERVED)
        self.assertIn('turns',self.chat.history('demo',OTHER))
        self.assertEqual(self.capability(self.chat,'demo',OTHER),OBSERVED)
        # No assertion retaining A here: a bounded last-observation tuple is valid.
        self.assert_read_only()

    def test_canonical_root_remap_does_not_reuse_same_sid_live_context_observation(self):
        # A between-operation remap is distinct from an in-flight root race.
        # Use public plain SessionChat so the test isolates observation scope from
        # the configured-origin private-store namespace, which remains unchanged.
        chat=self.sessions.SessionChat(self.rpc,self.resolve,lambda:['demo'],str(self.base/'scope-receipts'),
            model_context=self.rpc.model_context)
        context=self.history_a(chat)
        self.active_root=self.rebound;self.native.thread_changes={'cwd':str(self.rebound)}
        self.assertEqual(self.capability(chat,'demo',SID),NOT_OBSERVED,
                         'Same sid/context at a freshly proved different canonical root has no history proof')
        self.assertEqual(self.rpc.model_context(),context);self.assert_read_only()


if __name__=='__main__':unittest.main()
