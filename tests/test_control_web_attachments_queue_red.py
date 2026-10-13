"""Independent WATT queue boundary: nontext is visible, never text-only transfer.

Uses frozen synthetic public queue schemas and existing public SessionChat API.
No spool implementation reads; positive attachment delivery belongs to native proof.
"""
import json
import native_queue_blind_support as s
from test_control_web_native_queue_transfer_blind import TransferRPC, TARGET, SNAPSHOT


class AttachmentQueueRed(s.QueueModuleCase):
    def setUp(self):
        super().setUp();self.rpc=TransferRPC(self.project)
        self.addCleanup(self.rpc.steer_gate.set);self.chat=self.new_chat()
        self.private_path=str(self.base/'never-import-from-native.png')
        self.row=dict(id=s.QID,clientUserMessageId=s.MID,input=[
            dict(type='text',text=SNAPSHOT),dict(type='localImage',path=self.private_path)])
        self.rpc.queue_pages[None]['data']=[self.row]

    def test_external_nontext_queue_row_is_visible_safe_summary_not_empty_or_unsupported(self):
        # INV-WATT-06 INV-WATT-07: native paths are data, not import authority.
        result=self.queue()
        self.assertTrue(result.get('supported',False),result)
        self.assertEqual(len(result['rows']),1,result)
        row=result['rows'][0]
        self.assertEqual(row['queued_submission_id'],s.QID)
        self.assertEqual(row['message_id'],s.MID)
        self.assertTrue(row.get('attachments') or row.get('native_summary'),
                        'Nontext native input must have an honest visible summary')
        self.assertNotIn(self.private_path,json.dumps(result))
        self.assertEqual(self.mutation_methods(),[])

    def test_unbound_nontext_summary_never_authorizes_text_only_snapshot_transfer(self):
        # INV-WATT-07: same text is insufficient; no canonical pinned identity.
        result=self.invoke('send_queued_now','demo',s.SID,s.QID,s.ACTION,SNAPSHOT,TARGET)
        self.assertEqual(result.get('status'),'held',result)
        self.assertEqual(result.get('reason'),'unavailable',result)
        self.assertEqual(self.mutation_methods(),[],
                         'Held must not delete queue, steer, start, or fallback dispatch')
