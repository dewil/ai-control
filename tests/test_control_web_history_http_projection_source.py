"""Actual authenticated HTTP history route and broker gate public DTO evidence."""
import unittest
import test_control_web_session_chat_contract as contract

class HistoryHTTPProjectionSource(unittest.TestCase):
    setUp=contract.SessionHTTPContract.setUp
    login=contract.SessionHTTPContract.login
    def fetch(self,outcome):
        self.backend.session_history=lambda project,sid,cursor:outcome
        return self.client.get(f'/api/session-history?project=demo&sid={contract.SID}',headers={'Origin':contract.ORIGIN})
    def settings(self):return {'schema':1,'scope':'configured_or_persisted','source':'thread_read','model':'producer-model','effort':'custom effort','age_ms':123,'expires_in_ms':14877}
    def test_http_ordinary_preserves_session_settings_and_user_client_id(self):
        self.assertEqual(self.fetch({'turns':[]}).status_code,401);self.login()
        outcome={'turns':[{'id':contract.TURN,'status':'completed','items':[{'id':'native-user','role':'user','text':'Synthetic canonical text','truncated':False,'client_id':contract.MID}]}],'next_cursor':None,'truncated':False,'recent_sends':[],'session_settings':self.settings()}
        response=self.fetch(outcome);self.assertEqual(response.status_code,200);self.assertEqual(response.json(),outcome)
        self.assertIn('no-store',response.headers['cache-control'])
    def test_http_controlled_unavailable_gate_keeps_valid_settings_and_drops_invalid(self):
        self.login();base={'history_state':'unavailable','reason':'unavailable','recent_sends':[{'status':'delivery_unknown','message_id':contract.MID,'turn_id':None}]}
        valid={**base,'session_settings':self.settings()};self.assertEqual(self.fetch(valid).json(),valid)
        invalid={**base,'session_settings':{**self.settings(),'extra':'not-authorized'}}
        response=self.fetch(invalid);self.assertEqual(response.status_code,200);self.assertEqual(response.json(),base)

if __name__=='__main__':unittest.main()
