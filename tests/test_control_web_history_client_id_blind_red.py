"""INV-WSESS-46 source-blind actual SessionChat public projection oracle."""
import json
from pathlib import Path
import tempfile
import unittest
from test_control_web_session_chat_contract import RPC, SID, TURN, MID, feature

def user(mid,text='Synthetic user text'):
    return {'id':'native-user-item','type':'userMessage','clientId':mid,'content':[{'type':'text','text':text}]}

class HistoryClientIdBlind(unittest.TestCase):
    def setUp(self):
        self.module=feature(self,'_control_web_sessions')
        self.tmp=tempfile.TemporaryDirectory(prefix='history-client-id-',dir='/var/tmp');self.addCleanup(self.tmp.cleanup)
        self.project=Path(self.tmp.name)/'project';self.project.mkdir(mode=0o700)
        self.rpc=RPC(self.project)
        self.chat=self.module.SessionChat(self.rpc,lambda name:str(self.project),lambda:['demo'],str(Path(self.tmp.name)/'receipts'))
    def history(self,items,cursor=None):
        self.rpc.pages={None:{'data':[{'id':TURN,'status':'completed','items':items}],'nextCursor':'older'},
                        'older':{'data':[{'id':TURN,'status':'completed','items':items}],'nextCursor':None}}
        return self.chat.history('demo',SID,cursor)
    def test_INV46_canonical_id_latest_and_older_keep_native_identity(self):
        for cursor in (None,'older'):
            with self.subTest(cursor=cursor):
                result=self.history([user(MID)],cursor)
                self.assertIn('turns',result)
                item=result['turns'][0]['items'][0]
                self.assertEqual(item.get('client_id'),MID,'Canonical client UUID lost in history projections')
                self.assertEqual(item['id'],'native-user-item')
                self.assertNotIn('clientId',item)
    def test_INV46_optional_invalid_ids_omitted_nonstring_refused(self):
        for value in (None,'','native-client-id',MID.upper().replace('2','A',1),MID[:8]):
            with self.subTest(value=value):
                result=self.history([user(value)])
                self.assertIn('turns',result)
                self.assertNotIn('client_id',result['turns'][0]['items'][0])
        for value in (False,42,{},[]):
            with self.subTest(value=value):self.assertEqual(self.history([user(value)]),{'error':'unavailable'})
        agent={'id':'native-agent','type':'agentMessage','clientId':MID,'text':'Synthetic reply'}
        self.assertNotIn('client_id',self.history([agent])['turns'][0]['items'][0])
    def test_INV46_clipped_prefix_keeps_correlation_and_existing_budget(self):
        items=[dict(user(MID,'x'*9000),id='u-'+str(i)) for i in range(18)]
        result=self.history(items)
        self.assertIn('turns',result)
        projected=[i for t in result['turns'] for i in t['items']]
        self.assertTrue(projected)
        self.assertTrue(all(i.get('client_id')==MID for i in projected),'Budget clipping lost client ID')
        self.assertTrue(all(len(i['text'])<=8000 for i in projected))
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()),96*1024)
        self.assertTrue(result['truncated'] or any(i['truncated'] for i in projected))

if __name__=='__main__':unittest.main()
