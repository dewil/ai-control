"""Public queue/receipt and actual broker wire bounds; synthetic native only."""
import json
import unittest
import native_queue_blind_support as s
import test_control_web_native_queue_http_broker_blind as http
import test_control_web_session_models_http_broker as old


class QueueProjectionAuthor(s.QueueModuleCase):
    def test_large_projection_stays_inside_existing_broker_wire_with_truthful_partial(self):
        self.rpc.queue_pages[None]['data']=[s.native_row('q-'+str(i),'mac-'+str(i),'☃"\\'*2000) for i in range(64)]
        result=self.queue()
        self.assertNotIn('error',result)
        self.assertTrue(result['partial'])
        self.assertGreater(len(result['rows']),0)
        self.assertLess(len(result['rows']),64)
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()),96*1024)
        self.assertEqual([row['queued_submission_id'] for row in result['rows']],['q-'+str(i) for i in range(len(result['rows']))])
        self.assertEqual(self.cancel('q-63'),{'error':'stale'})
        self.assertEqual(self.rpc.calls_for('thread/queue/delete'),[])

    def test_queue_and_cancel_receipts_preserve_existing_history_schema(self):
        self.enqueue();self.cancel()
        history=self.invoke('history','demo',s.SID)
        self.assertNotIn('error',history)
        self.assertEqual(history['recent_sends'],[])
        self.assertNotIn('turn/start',self.rpc.methods())

    def test_manual_status_after_queue_disappearance_cannot_resurrect_stale_ACK(self):
        self.assertEqual(self.enqueue()['status'],'queued')
        self.rpc.queue_pages[None]['data']=[]
        result=self.invoke('send_status','demo',s.SID,s.MID)
        self.assertEqual(result['status'],'delivery_unknown')
        self.assertEqual(self.enqueue(chat=self.new_chat())['status'],'delivery_unknown')
        self.assertEqual(self.mutation_methods(),['thread/queue/add'])

    def test_confirmed_cancel_derives_original_status_without_replaying_enqueue(self):
        self.enqueue();self.assertEqual(self.cancel()['status'],'cancelled')
        self.assertEqual(self.invoke('send_status','demo',s.SID,s.MID)['status'],'cancelled')
        self.assertEqual(self.enqueue(chat=self.new_chat())['status'],'cancelled')
        self.assertEqual(self.mutation_methods(),['thread/queue/add','thread/queue/delete'])

    def test_enqueue_UUID_cannot_be_reused_as_direct_send(self):
        self.enqueue()
        self.assertEqual(self.invoke('send','demo',s.SID,s.MID,s.TEXT),{'error':'invalid_request'})
        self.assertEqual(self.mutation_methods(),['thread/queue/add'])

    def test_known_missing_list_method_is_unsupported_without_add_or_fallback(self):
        self.rpc.queue_pages[None]=self.module.RPCRejected('Synthetic method unavailable',-32601)
        self.assertEqual(self.queue()['reason'],'unsupported_queue')
        self.assertEqual(self.enqueue(),{'error':'unsupported_queue'})
        self.assertEqual(self.mutation_methods(),[])


class QueueWireAuthor(unittest.TestCase):
    setUp= http.NativeQueueBrokerBlind.setUp
    start=old.SessionModelsBroker.start
    shutdown=old.SessionModelsBroker.shutdown
    wire=old.SessionModelsBroker.wire

    def test_actual_unix_roundtrip_preserves_bounded_prefix_and_partial(self):
        self.backend.value=s.queue_dto([s.public_row('q-'+str(i),'mac-'+str(i),'☃"\\'*2000) for i in range(64)])
        self.start();value=self.wire(dict(op='session_queue',project='demo',sid=s.SID))
        self.assertNotIn('error',value);self.assertTrue(value['partial'])
        self.assertGreater(len(value['rows']),0)
        self.assertLessEqual(len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()),96*1024)
