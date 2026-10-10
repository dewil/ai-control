"""INV-CAP-01/02/04/06/08: real configured paths and closed read proofs."""
import copy
import json
import time
from types import MappingProxyType
import unittest
from unittest.mock import patch
from test_control_web_read_capabilities_support import NativeCase, READS, SID, MID, TURN, OTHER, OP, expected_capabilities, turn


class ReadContextBlind(NativeCase):
    def test_read_shape_unknown_null_and_reviewed_catalog_gate_remain_distinct(self):
        # INV-CAP-01/05: shape compatibility never grants mutation/catalog authority.
        reason = self.require(self.sessions.SessionChat, '_read_context_reason')
        base = {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound', 'context_id': 'a'*64,
                'transport_generation': 0, 'context_generation': 0, 'native_version': '0.999.0'}
        for version in ('0.999.0', '1.0.0-rc.1', None, '0.160.0', '0.161.0'):
            with self.subTest(version=version):
                context = dict(base, native_version=version)
                self.assertIsNone(reason(context))
                if version in ('0.160.0', '0.161.0'): self.assertIsNone(self.sessions.SessionChat._catalog_reason(context))
                else: self.assertIsNotNone(self.sessions.SessionChat._catalog_reason(context))
        for field, value in (('schema', True), ('schema', 1.0), ('context_id', 'bad'),
            ('transport_generation', True), ('context_generation', -1), ('context_generation', 1.5),
            ('native_version', True), ('native_version', 'codex/0.999.0'), ('native_version', '1.2'),
            ('context_kind', 'bound'), ('context_kind', 'unverified_bound')):
            with self.subTest(field=field, value=value): self.assertEqual(reason(dict(base, **{field:value})), 'unverified_context')
        self.assertEqual(reason(dict(base, vendor='other')), 'unsupported_vendor')
        self.assertEqual(reason(base | {'private_extra': True}), 'unverified_context')

    def test_projects_registry_read_never_requires_native_version_or_connection(self):
        # INV-CAP-01: configured creator exists, but registry projects do not connect.
        self.assertEqual(self.chat.projects(), {'projects': [{'name':'demo'}]})
        self.assertEqual(self.native.frames, [])

    def test_unknown_actual_configured_cache_identity_and_overlay_remain_readable(self):
        # INV-CAP-01: real ConfiguredSessionCreate and real private origin store.
        identity = self.invoke(lambda: self.creator.cache_identity(deadline=time.monotonic()+2))
        self.assertEqual(identity.context['native_version'], '0.999.0')
        self.assertEqual(identity.context['context_id'], self.rpc.receipt_context()['context_id'])
        result = self.invoke(lambda: self.creator.overlay('demo', deadline=time.monotonic()+2))
        self.assertEqual(set(result), {'sessions','truncated'}); self.assertFalse(result['truncated'])
        self.assertEqual(result['sessions'], [{'sid':SID,'project':'demo','vendor':'codex','context_mode':'configured',
            'title':'Native safe title','status':'idle','updated_at':1700000000}])
        self.assertTrue({'thread/loaded/list','thread/read'} <= set(self.native.methods()))
        self.assert_read_only()

    def test_unknown_list_and_summary_use_actual_configured_overlay_not_fake_creator(self):
        self.native.native.list_response = {'data': [], 'nextCursor': None}
        result = self.invoke(lambda: self.chat.list_sessions('demo', 0))
        self.assertEqual(result, {'rows':[{'sid':SID,'title':'Native safe title','status':'idle','vendor':'codex'}], 'has_more':False})
        summary = self.invoke(self.chat.project_summary)
        self.assertEqual(summary['projects'][0]['session_count'], 1)
        self.assertTrue({'thread/list','thread/loaded/list','thread/read'} <= set(self.native.methods()))
        self.assert_read_only()

    def test_unknown_history_and_live_snapshot_keep_settings_without_model_selection(self):
        result = self.invoke(lambda: self.chat.history('demo', SID))
        self.assertIn('turns', result)
        self.assertEqual(result['turns'][0]['items'][0]['text'], 'assistant reply')
        self.assertIn('session_settings',result)
        settings = result['session_settings']; self.assertEqual(settings['scope'], 'configured_or_persisted')
        self.assertEqual(settings['model'], 'safe-configured-model'); self.assertEqual(settings['effort'], 'safe-custom-effort')
        live = self.invoke(lambda: self.chat.live_snapshot('demo', SID))
        self.assertEqual(set(live), {'schema','scope_id','history'}); self.assertIn('turns', live['history'])
        catalog = self.invoke(lambda: self.chat.models('demo', SID))
        self.assertEqual(catalog['selection_support'], 'unavailable'); self.assertEqual(catalog['rows'], [])
        self.assertNotIn('model/list', self.native.methods()); self.assert_read_only()

    def test_missing_reported_version_still_reads_list_and_history_with_real_creator(self):
        self.native.agent = None
        result = self.invoke(lambda: self.chat.list_sessions('demo', 0)); self.assertIn('rows',result); self.assertEqual(len(result['rows']), 1)
        history = self.invoke(lambda: self.chat.history('demo', SID)); self.assertIn('turns', history)
        self.assertIsNone(self.rpc.model_context()['native_version']); self.assert_read_only()

    def test_failed_items_read_does_not_disable_registry_or_compatible_list(self):
        # INV-CAP-08: no resume fallback; unavailable configured variant is honest.
        def unsupported(ws, request, result):
            if request['method']=='thread/items/list':
                ws.send(json.dumps({'id':request['id'],'error':{'code':-32601,'message':'Synthetic unsupported items'}}))
                return False
        self.native.before_reply = unsupported
        failed = self.invoke(lambda: self.chat.history('demo', SID))
        self.assertTrue(failed in ({'error':'unavailable'},{'error':'stale'}) or failed.get('history_state')=='unavailable', failed)
        self.assertNotIn('turns', failed)
        self.assertEqual(self.chat.projects(), {'projects':[{'name':'demo'}]})
        listed=self.chat.list_sessions('demo',0); self.assertIn('rows',listed); self.assertEqual(len(listed['rows']),1)
        self.assert_read_only()

    def test_loaded_origin_and_unavailable_history_proof_accept_unknown_read_context(self):
        origin = self.invoke(lambda: self.creator.loaded_origin('demo', SID, deadline=time.monotonic()+2))
        self.assertIsNotNone(origin); self.assertEqual(origin.context['native_version'], '0.999.0')
        proof = self.invoke(lambda: self.creator.unavailable_history('demo', SID, deadline=time.monotonic()+2))
        self.assertIsNotNone(proof); self.assertEqual(proof.context['native_version'], '0.999.0')
        self.assert_read_only()

    def test_wrong_thread_id_or_root_never_exports_history(self):
        for changes in ({'id':OTHER},{'cwd':str(self.rebound)}):
            with self.subTest(changes=changes):
                self.native.thread_changes = changes
                self.assert_closed(self.invoke(lambda: self.chat.history('demo',SID)))
                self.assertIn('thread/read',self.native.methods()); self.assert_read_only()

    def test_root_remap_during_read_is_rechecked_before_publication(self):
        fired=[]
        def remap(ws, request, result):
            if request['method']=='thread/items/list' and not fired:
                fired.append(True); self.active_root=self.rebound
        self.native.before_reply=remap
        self.assert_closed(self.invoke(lambda:self.chat.history('demo',SID)))
        self.assertEqual(fired,[True], 'Unknown read must reach the actual read proof before this final-root fault')
        self.assert_read_only()

    def test_bound_context_and_invalid_generations_remain_unverified(self):
        context=self.prepare()
        for changes in ({'context_kind':'bound'}, {'transport_generation':True}, {'context_generation':-1}, {'context_id':'bad'}):
            with self.subTest(changes=changes):
                changed=dict(context,**changes); before=list(self.native.methods())
                with patch.object(self.rpc,'prepare_context',return_value=changed),patch.object(self.rpc,'model_context',return_value=changed):
                    chat=self.sessions.SessionChat(self.rpc,self.resolve,lambda:['demo'],str(self.send_path),
                        configured_creator=self.creator,model_context=self.rpc.model_context)
                    self.assert_closed(self.invoke(lambda:chat.history('demo',SID)))
                self.assertEqual(self.native.methods(),before)

    def test_unknown_malformed_history_and_duplicate_item_ids_are_not_empty_success(self):
        samples=[{'data':'invalid','nextCursor':None},
                 {'data':[{'id':TURN,'status':'future-control-state','items':[]}],'nextCursor':None},
                 {'data':[turn(turn_id=TURN),turn(turn_id=OTHER)],'nextCursor':None}]
        for value in samples:
            with self.subTest(response=value):
                self.native.native.pages[None]=copy.deepcopy(value)
                result=self.invoke(lambda:self.chat.history('demo',SID))
                self.assert_closed(result); self.assertNotIn('turns',result)
                self.assertIn('thread/turns/list',self.native.methods()); self.assert_read_only()

    def test_notification_invalidates_captured_read_and_next_operation_can_recapture(self):
        for method in ('account/updated','config/updated'):
            with self.subTest(notification=method):
                fired=[]
                def notify(ws, request, result):
                    if request['method']=='thread/list' and not fired:
                        fired.append(True); ws.send(json.dumps({'method':method,'params':{}}))
                self.native.before_reply=notify
                self.assert_closed(self.invoke(lambda:self.chat.list_sessions('demo',0)))
                self.assertEqual(fired,[True])
                self.native.before_reply=None
                listed=self.chat.list_sessions('demo',0); self.assertIn('rows',listed); self.assertEqual(len(listed['rows']),1)
                self.assert_read_only()

    def test_multipage_list_never_reconnects_into_a_mixed_generation_result(self):
        first={'id':SID,'cwd':str(self.root),'name':'First','status':{'type':'idle'},'updatedAt':1700000000,'source':'cli','archived':False}
        second=dict(first,id=OTHER,name='Second')
        self.native.list_pages={None:{'data':[first],'nextCursor':'next'},'next':{'data':[second],'nextCursor':None}}
        fired=[]
        def disconnect(ws,request,result):
            if request['method']=='thread/list' and not fired:
                fired.append(True);ws.send(json.dumps({'id':request['id'],'result':result}));ws.close();return False
        self.native.before_reply=disconnect
        self.assert_closed(self.invoke(lambda:self.chat.list_sessions('demo',0)))
        self.assertEqual(fired,[True]);self.assertEqual(self.native.connections,1,'Captured read reconnected mid-pagination')
        self.assert_read_only()

    def test_repeated_items_cursor_is_bounded_and_never_partial_history_success(self):
        calls=[]
        def repeat(ws,request,result):
            if request['method']=='thread/items/list':calls.append(True);result['nextCursor']='repeat'
        self.native.before_reply=repeat
        result=self.invoke(lambda:self.chat.history('demo',SID));self.assert_closed(result)
        self.assertTrue(calls);self.assertLessEqual(len(calls),3);self.assert_read_only()

    def test_capabilities_exact_unknown_dto_has_no_hidden_history_probe_then_observes_own_history(self):
        # INV-CAP-07: reported version is not proof of history or queue support.
        method=self.require(self.chat,'capabilities')
        value=self.invoke(lambda:method('demo',SID)); self.assertEqual(value,expected_capabilities())
        self.assertIn('thread/read',self.native.methods(),'Capability DTO requires actual fresh thread proof')
        self.assertNotIn('thread/turns/list',self.native.methods()); self.assertNotIn('thread/items/list',self.native.methods())
        self.assert_read_only(); self.assertIn('turns',self.chat.history('demo',SID))
        self.assertEqual(self.invoke(lambda:method('demo',SID)),expected_capabilities(history=True))
        for private in (str(self.base),'private-native-path','userAgent'):
            self.assertNotIn(private,json.dumps(value))
        for changes in ({'id':OTHER},{'cwd':str(self.rebound)}):
            self.native.thread_changes=changes
            self.assert_closed(self.invoke(lambda:method('demo',SID)))

    def test_capability_history_observation_is_not_reused_after_context_notification(self):
        method=self.require(self.chat,'capabilities')
        self.assertIn('turns',self.chat.history('demo',SID)); self.assertTrue(method('demo',SID)['operations']['history_read']['supported'])
        old=self.rpc.model_context()['context_generation']
        self.native.ws.send(json.dumps({'method':'account/updated','params':{}}))
        deadline=time.monotonic()+1
        while self.rpc.model_context()['context_generation']==old and time.monotonic()<deadline:time.sleep(.01)
        self.assertGreater(self.rpc.model_context()['context_generation'],old)
        self.assertEqual(method('demo',SID)['operations']['history_read'],{'supported':None,'reason':'not_observed'})
        self.assert_read_only()
