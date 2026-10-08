"""INV-WSESS-44 independent actual SessionChat oracle; approved218a05e only."""
import json, math, tempfile, unittest
from pathlib import Path
from test_control_web_session_chat_contract import RPC, SID, TURN, feature, turn
from test_control_web_session_models_module import CONTEXT

class SettingsRPC(RPC):
    def __init__(self,root):
        super().__init__(root);self.settings={'model':'producer-model','reasoningEffort':'custom effort'};self.hook=None
        self.pages['older']={'data':[turn()],'nextCursor':None}
    def __call__(self,method,params):
        result=super().__call__(method,params)
        if method=='thread/read':result['thread'].update(self.settings)
        if self.hook:self.hook(method)
        return result

class SessionSettingsBlind(unittest.TestCase):
    def setUp(self):
        self.module=feature(self,'_control_web_sessions');self.tmp=tempfile.TemporaryDirectory(prefix='model-settings-',dir='/var/tmp');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'project';self.root.mkdir(mode=0o700);self.rpc=SettingsRPC(self.root)
        self.context=dict(CONTEXT);self.now=100.;self.context_calls=0
    def get_context(self):self.context_calls+=1;return dict(self.context)
    def chat(self,trusted=True,getter=None):
        kwargs={'model_context':getter or self.get_context,'model_clock':lambda:self.now} if trusted else {}
        return self.module.SessionChat(self.rpc,lambda p:str(self.root),lambda:['demo'],str(Path(self.tmp.name)/'receipts'),**kwargs)
    def snapshot(self,result,model='producer-model',effort='custom effort',age=0):
        self.assertIn('turns',result,'Settings must not break existing history availability')
        self.assertEqual(result.get('session_settings'),{'schema':1,'scope':'configured_or_persisted','source':'thread_read','model':model,'effort':effort,'age_ms':age,'expires_in_ms':15000-age})
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()),96*1024)
    def test_positive_exact_projection_and_zero_extra_rpc(self):
        result=self.chat().history('demo',SID);self.snapshot(result)
        self.assertGreaterEqual(self.context_calls,3,'Context captured before proof, checked after proof and final publication')
        methods=[m for m,p in self.rpc.calls]
        self.assertEqual(methods.count('thread/read'),1)
        self.assertFalse({'model/list','thread/resume','turn/start'}&set(methods))
        self.assertNotIn(str(self.root),json.dumps(result));self.assertNotIn(CONTEXT['context_id'],json.dumps(result))
    def test_nullable_custom_and_unicode_codepoints_independent(self):
        for model,effort in [(None,'custom:X'),('producer-model',None),('😀'*256,'custom🚀'),(' model exact ',' effort exact ')]:
            with self.subTest(model=model,effort=effort):
                self.rpc.settings={'model':model,'reasoningEffort':effort};self.snapshot(self.chat().history('demo',SID),model,effort)
    def test_invalid_native_fields_do_not_poison_other_field(self):
        for invalid in [True,3,{},[],'','x'*257,'😀'*257,'bad\nvalue','bad\x00value','bad\ud800','token=synthetic-private-token-value']:
            for field in ['model','reasoningEffort']:
                with self.subTest(invalid=repr(invalid),field=field):
                    self.rpc.settings={'model':'producer-model','reasoningEffort':'custom effort',field:invalid}
                    self.snapshot(self.chat().history('demo',SID),None if field=='model' else 'producer-model',None if field=='reasoningEffort' else 'custom effort')
        self.rpc.settings={'model':'producer-model'};self.snapshot(self.chat().history('demo',SID),effort=None)
    def test_elapsed_rpc_floor_and_finite_expiry(self):
        for elapsed in [.123456,14.999,15.,16.,-1.,float('nan'),float('inf')]:
            with self.subTest(elapsed=elapsed):
                self.now=100.;self.rpc.hook=lambda method:self.advance(elapsed) if method=='thread/read' else None
                result=self.chat().history('demo',SID);self.assertIn('turns',result)
                if math.isfinite(elapsed) and 0<=elapsed<15:self.snapshot(result,age=math.floor((self.now-100)*1000))
                else:self.assertNotIn('session_settings',result)
    def test_clock_invalid_before_proof_or_expired_during_projection_omits_only_snapshot(self):
        for initial in [float('nan'),float('inf')]:
            self.now=initial;result=self.chat().history('demo',SID)
            self.assertIn('turns',result);self.assertNotIn('session_settings',result)
        self.now=100.;self.rpc.hook=lambda method:self.advance(16.) if method=='thread/items/list' else None
        result=self.chat().history('demo',SID);self.assertIn('turns',result);self.assertNotIn('session_settings',result)
    def advance(self,elapsed):self.now=100.+elapsed
    def test_context_before_after_and_final_changes_are_never_authority(self):
        mutations=[('transport_generation',4),('context_generation',8),('context_id','b'*64),('native_version','0.160.1'),('vendor','other'),('schema',True)]
        for phase in ['before','thread/read','thread/items/list']:
            for key,value in mutations:
                with self.subTest(phase=phase,key=key):
                    self.context=dict(CONTEXT);self.rpc.calls.clear()
                    if phase=='before':self.context[key]={'transport_generation':True,'context_generation':-1,'context_id':'not-a-digest'}.get(key,value)
                    self.rpc.hook=lambda method:self.context.update({key:value}) if method==phase else None
                    result=self.chat().history('demo',SID)
                    # Explicit model_context also owns receipts (existing INV26): never weaken its refusal.
                    if key in ('vendor','schema') or (phase=='before' and key!='native_version'):
                        self.assertEqual(result,{'error':'unavailable'})
                        if phase=='before':self.assertEqual(self.rpc.calls,[])
                    elif key=='context_id':self.assertEqual(result,{'error':'stale'})
                    else:self.assertIn('turns',result)
                    self.assertNotIn('session_settings',result)
        for key,value in [('schema',1.0),('context_generation',.5),('transport_generation',None),('context_id',None),('context_kind','unverified_bound')]:
            self.context={**CONTEXT,key:value};self.rpc.hook=None;self.rpc.calls.clear()
            self.assertEqual(self.chat().history('demo',SID),{'error':'unavailable'});self.assertEqual(self.rpc.calls,[])
        def broken():raise RuntimeError('synthetic disconnected')
        self.rpc.hook=None;self.rpc.calls.clear()
        self.assertEqual(self.chat(getter=broken).history('demo',SID),{'error':'unavailable'});self.assertEqual(self.rpc.calls,[])
    def test_plain_generic_history_older_and_bad_scope_unchanged(self):
        self.assertNotIn('session_settings',self.chat(trusted=False).history('demo',SID))
        result=self.chat().history('demo',SID,'older');self.assertIn('turns',result);self.assertNotIn('session_settings',result)
        self.rpc.read_id='44444444-4444-4444-8444-444444444444';self.assertEqual(self.chat().history('demo',SID),{'error':'stale'})
    def test_snapshot_included_in_clipped_projection_budget(self):
        self.rpc.pages[None]={'data':[{'id':TURN,'status':'completed','items':[{'id':'agent-'+str(i),'type':'agentMessage','text':'😀'*8000} for i in range(18)]}],'nextCursor':None}
        self.snapshot(self.chat().history('demo',SID))

if __name__=='__main__':unittest.main()
