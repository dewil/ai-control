"""Author semantic RED for cached GET latency and exact completion witness."""
from participation_blind_support import *


class ParticipationSourceAuthor(WireCase):
    def test_cold_overview_get_does_not_wait_for_native_read_proof(self):
        self.native.hold_reads=True;self.native.read_gate.clear()
        try:
            started=time.monotonic();value=self.overview();elapsed=time.monotonic()-started
            self.assertLess(elapsed,.5,'Global GET synchronously waited for native RPC')
            self.assertIn('coverage',value)
            self.assertTrue(value['coverage']['partial'])
            self.assert_read_only()
        finally:self.native.read_gate.set()

    def test_due_refresh_overview_get_returns_cached_projection_without_native_wait(self):
        first=self.wait_for(lambda:next((r for r in self.overview().get('rows',[]) if r['sid']==SID),None))
        self.native.hold_reads=True;self.native.read_gate.clear()
        try:
            time.sleep(5.1)
            started=time.monotonic();value=self.overview();elapsed=time.monotonic()-started
            self.assertLess(elapsed,.5,'Stale-cadence GET synchronously performed source refresh')
            self.assertIn('coverage',value)
            for row in value['rows']:
                self.assertEqual(row['freshness']['observed_at'],first['freshness']['observed_at'])
            self.assert_read_only()
        finally:self.native.read_gate.set()

    def test_later_nonempty_commentary_blocks_older_final_answer_readiness(self):
        self.native.turns=[dict(id=TURN,status='completed',items=[
            dict(id='older-final',type='agentMessage',phase='final_answer',text='Earlier final'),
            dict(id='later-commentary',type='agentMessage',phase='commentary',text='Later commentary')])]
        self.assertIn('turns',self.chat.history('demo',SID))
        row=self.wait_for(lambda:next((r for r in self.overview().get('rows',[]) if r['sid']==SID),None))
        self.assertIsNotNone(row['result'])
        self.assertFalse(row['result']['ready'],'Earlier final ignored later nonempty producer agentMessage')
        self.assert_read_only()

    def test_rpc_close_stops_the_single_owner_worker_and_closed_get_is_inert(self):
        before={thread for thread in threading.enumerate() if thread.name=='control-participation-source'}
        self.native.hold_reads=True;self.native.read_gate.clear();self.native.read_entered.clear()
        try:
            self.overview();self.overview();self.questions()
            self.assertTrue(self.native.read_entered.wait(1))
            active={thread for thread in threading.enumerate() if thread.name=='control-participation-source'}-before
            self.assertEqual(len(active),1,'Concurrent scopes created multiple owner refresh workers')
            self.rpc.close()
            self.assertFalse(any(thread.is_alive() for thread in active),'Owner worker survived transport lifecycle close')
            calls=list(self.native.methods())
            self.assertEqual(self.overview(),{'error':'unavailable'})
            self.chat.close();self.chat.close()
            self.assertEqual(self.native.methods(),calls)
        finally:self.native.read_gate.set()
