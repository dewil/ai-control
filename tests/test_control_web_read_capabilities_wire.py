"""INV-CAP-02/03/04/05/06: actual Unix wire and handshake projection."""
import json
import os
import socket
import struct
import time
import unittest
from unittest.mock import patch
from test_control_web_read_capabilities_support import NativeCase, READS, WRITES, SID, MID, TURN, OP, expected_capabilities


class NativeReadWireBlind(NativeCase):
    def fenced(self, method, params, context):
        return self.rpc.call_in_generation(method,params,transport_generation=context['transport_generation'],
            context_generation=context['context_generation'],timeout=1)

    def test_unknown_reported_token_is_preserved_without_raw_agent_suffix(self):
        # INV-CAP-06: parse independently of the reviewed operation versions.
        context=self.prepare(); self.assertEqual(context['native_version'],'0.999.0')
        self.assertEqual(set(context),{'schema','vendor','context_kind','context_id','transport_generation','context_generation','native_version'})
        self.assertNotIn('private-native-path',json.dumps(context)); self.assertNotIn('synthetic platform',json.dumps(context))

    def test_prerelease_and_missing_unparseable_version_are_honest(self):
        for agent,version in [('codex/1.2.3-rc.1 (synthetic)','1.2.3-rc.1'),
            ('codex/123456.123456.123456-abcdefghijklmnopqrstuvwxyz012345 (synthetic)',
             '123456.123456.123456-abcdefghijklmnopqrstuvwxyz012345'),
            (None,None),('unparseable /synthetic-private-path',None),('codex/1234567.2.3 (invalid)',None)]:
            with self.subTest(agent=agent):
                self.native.agent=agent
                rpc=self.sessions.InteractiveRPC(str(self.native.alias),timeout=1);self.addCleanup(rpc.close)
                context=rpc.prepare_context(timeout=1);self.assertEqual(context['native_version'],version)
                try:
                    result=rpc.call_in_generation('thread/read',{'threadId':SID,'includeTurns':False},
                        transport_generation=context['transport_generation'],context_generation=context['context_generation'],timeout=1)
                except Exception as error:self.fail('Validated parsed/null read refused: '+type(error).__name__)
                self.assertEqual(result['thread']['id'],SID)
                rpc.close()

    def test_every_fixed_read_method_works_in_unknown_captured_generation(self):
        # INV-CAP-04: five reviewed reads, not generic method discovery.
        context=self.prepare()
        requests=[('thread/list',{'cursor':None,'limit':20}),('thread/read',{'threadId':SID,'includeTurns':False}),
            ('thread/turns/list',{'threadId':SID,'cursor':None,'limit':4,'itemsView':'notLoaded'}),
            ('thread/items/list',{'threadId':SID,'turnId':TURN,'cursor':None,'limit':20}),
            ('thread/loaded/list',{'cursor':None,'limit':20})]
        for method,params in requests:
            with self.subTest(method=method):
                try: result=self.fenced(method,params,context)
                except Exception as error:self.fail('Unknown compatible read refused: '+type(error).__name__)
                self.assertIsInstance(result,dict)
        self.assertEqual(set(self.native.methods()),READS);self.assert_read_only();self.assertEqual(self.native.connections,1)

    def test_unknown_ordinary_and_fenced_mutations_refuse_before_wire(self):
        # INV-CAP-03: ordinary call without a generation is not a mutation bypass.
        context=self.prepare()
        mutations=[('thread/start',{'cwd':str(self.root)}),('thread/resume',{'threadId':SID}),
            ('thread/name/set',{'threadId':SID,'name':'Synthetic name'}),
            ('turn/start',{'threadId':SID,'input':[{'type':'text','text':'Synthetic text'}]}),
            ('model/list',{'cursor':None,'limit':20,'includeHidden':False}),
            ('turn/steer',{'threadId':SID,'turnId':TURN,'input':[]}),
            ('thread/queue/list',{'threadId':SID}),('thread/queue/add',{'threadId':SID}),('thread/queue/start',{'threadId':SID})]
        for mode in ('ordinary','fenced'):
            for method,params in mutations:
                with self.subTest(mode=mode,method=method):
                    self.rpc_rejected(lambda:self.rpc(method,params) if mode=='ordinary' else self.fenced(method,params,context))
        self.assertEqual(self.native.methods(),[])

    def test_null_version_read_is_compatible_but_both_write_paths_stay_closed(self):
        self.native.agent=None;context=self.prepare();self.assertIsNone(context['native_version'])
        try:value=self.fenced('thread/read',{'threadId':SID,'includeTurns':False},context)
        except Exception as error:self.fail('Null-version structural read refused: '+type(error).__name__)
        self.assertEqual(value['thread']['id'],SID)
        for mode in ('ordinary','fenced'):
            with self.subTest(mode=mode):
                self.rpc_rejected(lambda:self.rpc('turn/start',{'threadId':SID,'input':[]}) if mode=='ordinary' else self.fenced('turn/start',{'threadId':SID,'input':[]},context))
        self.assert_read_only()

    def test_unknown_method_config_and_account_are_not_read_discovery(self):
        context=self.prepare()
        for method in ('account/read','config/read','thread/arbitraryMutation','model/discover'):
            with self.subTest(method=method):
                self.rpc_rejected(lambda:self.rpc(method,{}));self.rpc_rejected(lambda:self.fenced(method,{},context))
        self.assertEqual(self.native.methods(),[])

    def test_known_reviewed_versions_retain_fixed_mutation_wire_contract(self):
        # INV-CAP-05: preserve both accepted versions without authorizing queue on unknown.
        for version in ('0.160.0','0.161.0'):
            with self.subTest(version=version):
                self.native.agent='codex/'+version+' (synthetic)'
                rpc=self.sessions.InteractiveRPC(str(self.native.alias),timeout=1);self.addCleanup(rpc.close)
                context=rpc.prepare_context(timeout=1);self.assertEqual(context['native_version'],version)
                for method,params in [('thread/start',{'cwd':str(self.root)}),('thread/name/set',{'threadId':SID,'name':'Synthetic title'})]:
                    rpc.call_in_generation(method,params,transport_generation=context['transport_generation'],context_generation=context['context_generation'],timeout=1)
                rpc.close()
        self.assertEqual(self.native.methods(),['thread/start','thread/name/set']*2)
        # Same actual configured/read fixture must be healthy on a reviewed version.
        self.native.native.list_response={'data':[],'nextCursor':None}
        identity=self.invoke(lambda:self.creator.cache_identity(deadline=time.monotonic()+2))
        self.assertEqual(identity.context['native_version'],'0.161.0')
        overlay=self.invoke(lambda:self.creator.overlay('demo',deadline=time.monotonic()+2))
        self.assertEqual(len(overlay['sessions']),1)
        listed=self.chat.list_sessions('demo',0);self.assertIn('rows',listed);self.assertEqual(len(listed['rows']),1)
        history=self.chat.history('demo',SID);self.assertIn('turns',history);self.assertIn('session_settings',history)


    def test_fenced_disconnected_read_never_reconnects_then_new_read_captures_upgrade(self):
        self.native.agent='codex/0.160.0 (synthetic)';captured=self.prepare();connections=self.native.connections
        self.native.ws.close();deadline=time.monotonic()+1
        while self.rpc.model_context() is not None and self.rpc.model_context().get('native_version') is not None and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(self.rpc.model_context() is None or self.rpc.model_context()['native_version'] is None)
        self.rpc_rejected(lambda:self.fenced('thread/read',{'threadId':SID,'includeTurns':False},captured))
        self.assertEqual(self.native.connections,connections)
        self.native.agent='codex/0.999.0 (upgraded synthetic)';fresh=self.prepare()
        self.assertGreater(fresh['transport_generation'],captured['transport_generation']);self.assertEqual(fresh['native_version'],'0.999.0')
        self.assertEqual(self.fenced('thread/read',{'threadId':SID,'includeTurns':False},fresh)['thread']['id'],SID)

    def test_context_notification_invalidates_old_fence_without_wire_send(self):
        context=self.prepare();before=list(self.native.methods())
        self.native.ws.send(json.dumps({'method':'config/updated','params':{}}));deadline=time.monotonic()+1
        while self.rpc.model_context()['context_generation']==context['context_generation'] and time.monotonic()<deadline:time.sleep(.01)
        self.assertGreater(self.rpc.model_context()['context_generation'],context['context_generation'])
        self.rpc_rejected(lambda:self.fenced('thread/read',{'threadId':SID,'includeTurns':False},context))
        self.assertEqual(self.native.methods(),before)

    def test_same_uid_peer_proof_precedes_initialize_even_for_unknown_read(self):
        original=socket.socket.getsockopt;checks=[]
        def wrong_peer(sock,level,option,*args):
            if level==socket.SOL_SOCKET and option==socket.SO_PEERCRED:
                checks.append(True);return struct.pack('3i',os.getpid(),os.getuid()+1,os.getgid())
            return original(sock,level,option,*args)
        with patch.object(socket.socket,'getsockopt',wrong_peer):
            with self.assertRaises(Exception):self.rpc('thread/read',{'threadId':SID,'includeTurns':False})
        self.assertTrue(checks);self.assertEqual(self.native.frames,[])

    def test_alias_retarget_during_handshake_does_not_publish_any_read(self):
        from test_control_web_read_capabilities_support import NativeServer
        directory=self.base/'second-native';directory.mkdir(mode=0o700)
        other=NativeServer(directory,self.root);self.addCleanup(other.stop)
        def retarget():
            self.native.alias.unlink();self.native.alias.symlink_to(other.path)
        self.native.on_connect=retarget
        with self.assertRaises(Exception):self.rpc('thread/read',{'threadId':SID,'includeTurns':False})
        self.assertEqual(self.native.frames,[])

    def test_plain_inherit_send_cannot_bypass_unknown_mutation_gate_without_configured_creator(self):
        # INV-CAP-03: an ordinary-call writer must not inherit the read-only exception.
        self.prepare();path=self.base/'plain-send-receipts'
        chat=self.sessions.SessionChat(self.rpc,self.resolve,lambda:['demo'],str(path),model_context=self.rpc.model_context)
        before=self.files();result=self.invoke(lambda:chat.send('demo',SID,MID,'Synthetic blocked inherit'))
        self.assert_closed(result);self.assertEqual(self.files(),before)
        self.assertFalse(WRITES & set(self.native.methods()),self.native.methods())

    def test_unknown_inherit_explicit_rename_and_configured_create_have_zero_dispatch_or_reserve(self):
        # INV-CAP-03/05: real configured origin read must not become write authority.
        self.prepare();before=self.files();start=len(self.native.frames)
        actions=[lambda:self.chat.send('demo',SID,MID,'Synthetic unreviewed inherit'),
                 lambda:self.chat.send('demo',SID,MID,'Synthetic selected',{'catalog_id':'a'*64,'model_id':'synthetic','effort':'low'}),
                 lambda:self.chat.rename('demo',SID,'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','Synthetic rename'),
                 lambda:self.creator.create('demo','cccccccc-cccc-4ccc-8ccc-cccccccccccc','configured','codex')]
        for index,action in enumerate(actions):
            with self.subTest(operation=index):
                try:result=action()
                except Exception as error:
                    code=getattr(error,'code',None);self.assertIn(code,('unavailable','stale','forbidden'));result={'error':code}
                self.assert_closed(result)
                self.assertEqual(self.files(),before,'Unsupported mutation reserved or published private state')
        self.assertFalse(WRITES & set(self.native.methods()),self.native.methods())
        self.assertFalse(any(frame.get('method')=='model/list' for frame in self.native.frames[start:]))
