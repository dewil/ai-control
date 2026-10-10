"""User-approved snapshot-transfer HTTP contract, independent local backend."""
import json
import unittest
import native_queue_blind_support as s
import test_control_web_native_queue_http_broker_blind as core
from test_control_web_session_chat_contract import ORIGIN


class NativeQueueTransferHTTPBlind(unittest.TestCase):
    login=core.NativeQueueHTTPBlind.login
    headers=core.NativeQueueHTTPBlind.headers
    def setUp(self):
        core.NativeQueueHTTPBlind.setUp(self)
        self.path='/api/session-queue-send-now';self.state='accepted'
        self.payload=dict(project='demo',sid=s.SID,queued_submission_id='mac-native-row',action_id=s.ACTION,
                          snapshot_text='Exact displayed snapshot',expected_turn_id='native-active-turn-A')
        self.backend.value.update(active_turn_id=self.payload['expected_turn_id'],send_now_supported=True,send_now_reason=None)
        def send_now(project,sid,qid,action,snapshot,expected):
            self.backend.calls.append(('send_now',project,sid,qid,action,snapshot,expected))
            return dict(status=self.state,message_id=action,queued_submission_id=qid,
                        turn_id=expected if self.state=='accepted' else None,reason=None)
        self.backend.session_queue_send_now=send_now

    def test_exact_snapshot_request_and_opaque_turn_ID_forward_to_owner(self):
        self.login();response=self.client.post(self.path,json=self.payload,headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),dict(status='accepted',message_id=s.ACTION,queued_submission_id='mac-native-row',turn_id='native-active-turn-A',reason=None))
        self.assertEqual(self.backend.calls,[('send_now','demo',s.SID,'mac-native-row',s.ACTION,'Exact displayed snapshot','native-active-turn-A')])

    def test_missing_auth_Origin_CSRF_and_malformed_DTO_have_zero_effects(self):
        self.assertEqual(self.client.post(self.path,json=self.payload,headers={'Origin':ORIGIN}).status_code,401)
        self.login()
        for headers in [{},{'Origin':ORIGIN},{'X-CSRF-Token':self.csrf},{'Origin':ORIGIN,'X-CSRF-Token':'wrong'},
                        {'Origin':'https://evil.example.test','X-CSRF-Token':self.csrf}]:
            with self.subTest(headers=list(headers)):
                self.assertEqual(self.client.post(self.path,json=self.payload,headers=headers).status_code,403)
        bad=[{**self.payload,'account':'private'},{**self.payload,'snapshot_text':'  '},
             {**self.payload,'snapshot_text':'x'*16001},{**self.payload,'expected_turn_id':True},
             {**self.payload,'action_id':'mac-non-uuid'},
             {key:value for key,value in self.payload.items() if key!='snapshot_text'}]
        for body in bad:
            with self.subTest(keys=list(body)):self.assertEqual(self.client.post(self.path,json=body,headers=self.headers()).status_code,422)
        raw=json.dumps(self.payload)[:-1]+',"snapshot_text":"silent replacement"}'
        self.assertEqual(self.client.post(self.path,content=raw,headers={**self.headers(),'Content-Type':'application/json'}).status_code,422)
        self.assertEqual(self.backend.calls,[])

    def test_unknown_503_and_held_changed_200_preserve_honest_action_DTO(self):
        self.login()
        for state in ['delivery_unknown','held','changed']:
            self.state=state
            with self.subTest(status=state):
                response=self.client.post(self.path,json=self.payload,headers=self.headers())
                self.assertEqual(response.status_code,503 if state=='delivery_unknown' else 200,response.text)
                self.assertEqual(response.json()['status'],state)
