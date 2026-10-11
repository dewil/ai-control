"""Independent meaningful RED for accepted limits spec, native/HTTP/Unix seams.

Written before runtime implementation; synthetic inputs only, no vendor access.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import limits_dashboard_blind_support as s
import live_sse_blind_support as live
from test_control_web_session_chat_contract import feature
import test_control_web_session_models_http_broker as broker_fixture


class LimitsNativeRED(unittest.TestCase):
    def setUp(self):
        self.module=feature(self,'_control_web_sessions')
        self.temp=tempfile.TemporaryDirectory(prefix='limits-blind-',dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name); self.base.chmod(0o700)
        self.rpc=s.LimitsRPC(); self.addCleanup(self.rpc.gate.set)
        self.now=float(s.NOW)
        self.chat=self.new_chat()

    def new_chat(self):
        return self.module.SessionChat(self.rpc,lambda _:str(self.base),lambda:[],
            str(self.base/'receipts'),model_context=self.rpc.model_context,model_clock=lambda:self.now)

    def invoke(self):
        method=getattr(self.chat,'limits_overview',None)
        self.assertTrue(callable(method),'INV-WLIM-10: SessionChat.limits_overview public seam missing')
        with patch.object(self.module.time,'time',lambda:self.now):
            return method()

    def codex(self,value):
        self.assertEqual(set(value),{'schema','server_now','coverage','sources'})
        self.assertEqual(value['schema'],1)
        self.assertEqual(set(value['coverage']),{'scope','partial'})
        self.assertEqual(value['coverage']['scope'],'llm_native_only')
        self.assertIs(type(value['coverage']['partial']),bool)
        self.assertIs(type(value['sources']),list)
        for source in value['sources']:
            self.assertEqual(set(source),s.SOURCE_KEYS)
            for window in source['windows']: self.assertEqual(set(window),s.WINDOW_KEYS)
        matches=[source for source in value['sources'] if source['provider']=='codex']
        self.assertEqual(len(matches),1)
        return matches[0]

    def unavailable(self,value,error):
        source=self.codex(value)
        self.assertEqual((source['status'],source['identity'],source['account_id'],source['windows'],source['error']),
                         ('unavailable','unknown',None,[],error))

    def test_native_verbatim_identity_and_exact_safe_DTO(self):
        # INV-WLIM-10 INV-WLIM-11 INV-WLIM-13
        value=self.invoke(); source=self.codex(value)
        self.assertEqual(source['account_id'],s.identity())
        self.assertNotEqual(source['account_id'],s.identity(s.ACCOUNT.strip()))
        self.assertEqual((source['node_id'],source['identity'],source['status'],source['plan']),
                         ('llm','native_reported','ok','Plus'))
        weekly=next(w for w in source['windows'] if w['id']=='codex:primary')
        self.assertEqual(weekly,dict(id='codex:primary',bucket='codex',duration_minutes=10080,
            remaining_percent=75,resets_at=s.NOW+6*s.DAY,window_started_at=s.NOW-s.DAY,
            anchor='derived_reset_and_duration'))
        self.assertGreaterEqual(self.rpc.prepares,1)
        self.assertEqual(len(self.rpc.calls),1)
        call=self.rpc.calls[0]
        self.assertEqual((call['method'],call['params'],call['transport_generation'],call['context_generation']),
                         ('account/rateLimits/read',{'excludeResetCreditDetails':True},3,7))
        self.assertTrue(0<call['timeout']<=4,'One bounded native read deadline')
        claude=[x for x in value['sources'] if x['provider']=='claude']
        self.assertEqual(len(claude),1)
        self.assertEqual((claude[0]['status'],claude[0]['windows'],claude[0]['account_id']),('unavailable',[],None))
        self.assertNotIn(s.ACCOUNT,json.dumps(value))

    def test_missing_invalid_or_control_character_native_identity_never_exports_windows(self):
        # INV-WLIM-10: identity comes from this very response.
        for account in (None,'',7,True,'a'*257,'with\nnewline','nul\x00byte'):
            with self.subTest(kind=repr(account)[:30]):
                self.rpc.value=s.native(account);self.chat=self.new_chat()
                self.unavailable(self.invoke(),'identity_unavailable')

    def test_two_accounts_replace_snapshot_atomically_without_relabel(self):
        # INV-WLIM-10 INV-WLIM-13
        first=self.codex(self.invoke());self.assertEqual(first['account_id'],s.identity())
        self.now+=61
        self.rpc.value=s.native('account-B'); self.rpc.value['rateLimitsByLimitId']['codex']['primary']['usedPercent']=99
        second=self.codex(self.invoke())
        self.assertEqual(second['account_id'],s.identity('account-B'))
        self.assertEqual(second['windows'][0]['remaining_percent'],1)
        self.assertEqual(first['account_id'],s.identity())
        self.assertEqual(first['windows'][0]['remaining_percent'],75)

    def test_cache_hit_still_rechecks_context_and_has_new_server_time(self):
        # INV-WLIM-10 INV-WLIM-11
        first=self.invoke();reads=self.rpc.context_reads;self.now+=30
        second=self.invoke();a=self.codex(first);b=self.codex(second)
        self.assertEqual(len(self.rpc.calls),1,'TTL60 prevents redundant native calls')
        self.assertGreater(self.rpc.context_reads,reads,'Cache hits require current context proof')
        self.assertEqual(second['server_now']-first['server_now'],30)
        self.assertEqual(b['captured_at'],a['captured_at'])
        self.assertEqual(b['age_seconds'],30)
        self.now+=31;self.invoke();self.assertEqual(len(self.rpc.calls),2)

    def test_cached_context_mismatch_immediately_discards_identity_and_windows(self):
        # INV-WLIM-10: mismatch must not freshen/relabel the old entry.
        self.invoke();self.rpc.context['context_generation']+=1
        self.unavailable(self.invoke(),'context_changed')
        self.assertEqual(len(self.rpc.calls),1,'Mismatch on serve fails closed before another read')

    def test_cold_generation_drift_one_read_only_retry_with_one_deadline(self):
        # INV-WLIM-10: exactly one startup retry, all calls remain reads.
        def drift_once(rpc):
            time.sleep(.12)
            rpc.context['context_generation']+=1;rpc.after_read=None
        self.rpc.after_read=drift_once
        self.assertEqual(self.codex(self.invoke())['status'],'ok')
        self.assertEqual(len(self.rpc.calls),2)
        self.assertEqual([x['context_generation'] for x in self.rpc.calls],[7,8])
        self.assertLessEqual(self.rpc.calls[1]['timeout'],self.rpc.calls[0]['timeout'])
        self.assertGreaterEqual(self.rpc.calls[0]['timeout']-self.rpc.calls[1]['timeout'],.08,
                                'Retry must spend the original deadline, never reset four seconds')
        self.assertTrue(all(x['method']=='account/rateLimits/read' for x in self.rpc.calls))

    def test_repeated_midflight_drift_stops_after_second_read_no_old_windows(self):
        # INV-WLIM-10 INV-WLIM-16
        self.rpc.after_read=lambda rpc:rpc.context.__setitem__('transport_generation',rpc.context['transport_generation']+1)
        self.unavailable(self.invoke(),'context_changed')
        self.assertEqual(len(self.rpc.calls),2)

    def test_source_failure_never_revives_previous_account_snapshot(self):
        # INV-WLIM-11
        self.invoke();self.now+=61;self.rpc.failure=RuntimeError(s.PRIVATE)
        value=self.invoke();self.unavailable(value,'source_unavailable')
        self.assertNotIn(s.PRIVATE,json.dumps(value))
        self.assertNotIn(s.ACCOUNT,json.dumps(value))

    def test_singleflight_concurrent_calls_share_one_read(self):
        # INV-WLIM-11: gate makes overlap observable, rather than relying on speed.
        self.rpc.gate.clear()
        with ThreadPoolExecutor(max_workers=4) as pool:
            method=getattr(self.chat,'limits_overview',None)
            self.assertTrue(callable(method),'SessionChat.limits_overview missing')
            futures=[pool.submit(method) for _ in range(4)]
            self.assertTrue(self.rpc.entered.wait(1),'Native read did not enter synthetic gate')
            time.sleep(.05);self.rpc.gate.set()
            values=[future.result(timeout=2) for future in futures]
        self.assertEqual(len(self.rpc.calls),1)
        self.assertTrue(all(self.codex(value)['account_id']==s.identity() for value in values))

    def test_expired_reset_is_unknown_remaining_not_fake_replenishment(self):
        # INV-WLIM-11
        self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(used=0,reset=s.NOW))})
        window=self.codex(self.invoke())['windows'][0]
        self.assertIsNone(window['remaining_percent'])
        self.assertEqual(window['resets_at'],s.NOW)
        self.assertIsNone(window['window_started_at']);self.assertIsNone(window['anchor'])

    def test_reset_expiring_inside_TTL_is_reprojected_without_another_native_read(self):
        # INV-WLIM-11: cache retains observed usage, never stale recovery promises.
        self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(reset=s.NOW+10,duration=300))})
        first=self.codex(self.invoke())['windows'][0]
        self.assertEqual(first['remaining_percent'],75);self.assertIsNotNone(first['anchor'])
        self.now+=11
        second=self.codex(self.invoke())['windows'][0]
        self.assertEqual(len(self.rpc.calls),1,'Expiry inside TTL needs projection, not another native call')
        self.assertIsNone(second['remaining_percent']);self.assertIsNone(second['anchor'])
        self.assertIsNone(second['window_started_at']);self.assertEqual(second['resets_at'],s.NOW+10)

    def test_unknown_reset_preserves_snapshot_percent_but_no_anchor(self):
        # INV-WLIM-11
        self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(used=20,reset=None))})
        window=self.codex(self.invoke())['windows'][0]
        self.assertEqual(window['remaining_percent'],80)
        self.assertIsNone(window['resets_at']);self.assertIsNone(window['window_started_at']);self.assertIsNone(window['anchor'])

    def test_percentage_endpoints_and_finite_fractional_reset_preserve_units(self):
        # INV-WLIM-11: remaining is subtraction only, never a usage multiplier.
        for used,remaining in ((0,100),(100,0),(12.5,87.5)):
            with self.subTest(used=used):
                reset=s.NOW+3600.5
                self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(used=used,reset=reset,duration=300))})
                self.chat=self.new_chat();window=self.codex(self.invoke())['windows'][0]
                self.assertEqual(window['remaining_percent'],remaining)
                self.assertEqual(window['resets_at'],reset)
                self.assertEqual(window['window_started_at'],reset-18000)

    def test_malformed_percent_bool_nonfinite_and_out_of_range_are_null(self):
        # INV-WLIM-11
        for used in (True,False,'25',-1,101,float('nan'),float('inf'),None):
            with self.subTest(used=repr(used)):
                self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(used=used))});self.chat=self.new_chat()
                self.assertIsNone(self.codex(self.invoke())['windows'][0]['remaining_percent'])
        self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(used=12.5))});self.chat=self.new_chat()
        self.assertEqual(self.codex(self.invoke())['windows'][0]['remaining_percent'],87.5)

    def test_duration_is_exact_integer_and_anchor_requires_nonnegative_start(self):
        # INV-WLIM-11: 300.0 and True must never acquire a window anchor.
        for duration in (True,False,10080.0,'10080',0,-1,525601,None):
            with self.subTest(duration=repr(duration)):
                self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(duration=duration))});self.chat=self.new_chat()
                window=self.codex(self.invoke())['windows'][0]
                self.assertIsNone(window['duration_minutes']);self.assertIsNone(window['window_started_at']);self.assertIsNone(window['anchor'])
                self.assertEqual(window['remaining_percent'],75)
        self.now=10;self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(duration=1,reset=20))});self.chat=self.new_chat()
        window=self.codex(self.invoke())['windows'][0]
        self.assertEqual(window['duration_minutes'],1);self.assertIsNone(window['anchor'])

    def test_reset_rejects_bool_string_nonfinite_and_invalid_bounds(self):
        # INV-WLIM-11
        for reset in (True,'1800003600',-1,253402300800,float('nan'),float('inf')):
            with self.subTest(reset=repr(reset)):
                self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(reset=reset))});self.chat=self.new_chat()
                window=self.codex(self.invoke())['windows'][0]
                self.assertIsNone(window['resets_at']);self.assertIsNone(window['anchor'])
                self.assertEqual(window['remaining_percent'],75)

    def test_bucket_bound_invalid_ids_and_unknown_secrets_are_stripped(self):
        # INV-WLIM-11 INV-WLIM-13
        buckets={f'bucket{i}':dict(primary=s.native_window(),secondary=s.native_window(duration=300),
            credits={'balance':s.PRIVATE},email=s.PRIVATE,limitName=s.PRIVATE) for i in range(10)}
        buckets.update({'<script>':dict(primary=s.native_window()),'юникод':dict(primary=s.native_window()),'x'*65:dict(primary=s.native_window())})
        self.rpc.value=s.native(buckets=buckets)
        self.rpc.value.update(email=s.PRIVATE,rateLimitUpsell={'html':s.PRIVATE},rateLimitResetCredits={'credits':[s.PRIVATE]})
        value=self.invoke();source=self.codex(value)
        self.assertLessEqual(len(source['windows']),16)
        self.assertEqual(len({w['bucket'] for w in source['windows']}),8)
        self.assertIs(value['coverage']['partial'],True)
        self.assertNotIn(s.PRIVATE,json.dumps(value));self.assertNotIn('<script>',json.dumps(value))
        for window in source['windows']:self.assertRegex(window['bucket'],r'^[A-Za-z0-9_-]{1,64}$')

    def test_native_versions_exact_read_allowlist_does_not_enable_future_versions(self):
        # INV-WLIM-10; queue mutation version fences are covered by unchanged core tests.
        for version in ('0.161.0','0.162.1'):
            with self.subTest(version=version):
                self.rpc.context['native_version']=version;self.chat=self.new_chat()
                self.assertEqual(self.codex(self.invoke())['status'],'ok')
        for version in ('0.160.0','0.162.0','0.163.0','future',None,True):
            with self.subTest(version=version):
                self.rpc.context['native_version']=version;self.chat=self.new_chat();before=len(self.rpc.calls)
                self.unavailable(self.invoke(),'unsupported');self.assertEqual(len(self.rpc.calls),before)

    def test_empty_multi_bucket_uses_legacy_id_without_duplicate_snapshot(self):
        # INV-WLIM-11: frozen fallback precedence, without reading implementation.
        for mapping in (None,{}):
            with self.subTest(mapping=mapping):
                self.rpc.value=s.native();self.rpc.value['rateLimitsByLimitId']=mapping
                self.rpc.value['rateLimits']['limitId']='reviewed_bucket';self.chat=self.new_chat()
                windows=self.codex(self.invoke())['windows']
                self.assertEqual({w['bucket'] for w in windows},{'reviewed_bucket'})
                self.assertEqual(len(windows),2)
        self.rpc.value=s.native(buckets={'explicit':dict(primary=s.native_window())})
        self.chat=self.new_chat()
        self.assertEqual([w['id'] for w in self.codex(self.invoke())['windows']],['explicit:primary'])

    def test_plan_allowlist_and_conflicting_bucket_plans(self):
        # INV-WLIM-11: raw strings cannot become public plan labels.
        for native_plan,expected in (('free','Free'),('plus','Plus'),('pro','Pro'),('team','Team'),
                                     ('business','Business'),('enterprise','Enterprise'),('unknown','unknown'),
                                     ('prolite',None),(s.PRIVATE,None),(True,None)):
            with self.subTest(plan=native_plan):
                self.rpc.value=s.native(buckets={'codex':dict(primary=s.native_window(),planType=native_plan)})
                self.chat=self.new_chat();self.assertEqual(self.codex(self.invoke())['plan'],expected)
        self.rpc.value=s.native(buckets={'a':dict(primary=s.native_window(),planType='plus'),
                                        'b':dict(primary=s.native_window(),planType='pro')})
        self.chat=self.new_chat();self.assertIsNone(self.codex(self.invoke())['plan'])


class LimitsHTTPRED(unittest.TestCase):
    def setUp(self):
        original=live.Backend;live.Backend=s.LimitsBackend
        try:self.fixture=live.Fixture(session_store=True)
        finally:live.Backend=original
        self.addCleanup(self.fixture.stop);self.backend=self.fixture.backend

    def request(self,suffix='',**kwargs):
        connection,response=self.fixture.request('/api/limits-overview'+suffix,**kwargs)
        body=response.read();connection.close()
        return response,json.loads(body)

    def test_owner_web_cookie_exact_safe_DTO_no_store(self):
        # INV-WLIM-12
        self.fixture.login();response,value=self.request()
        self.assertEqual(response.status,200)
        self.assertEqual(value,self.backend.limits_value)
        self.assertIn('no-store',response.getheader('cache-control',''))
        self.assertEqual(len(self.backend.limits_calls),1)

    def test_anonymous_expired_and_nonowner_never_reach_backend(self):
        # INV-WLIM-12: principal checked at every serve, including a previous success.
        response,_=self.request(cookie=False);self.assertEqual(response.status,401)
        self.fixture.login()
        key=self.fixture.cookie.split('=',1)[1]
        for principal in (None,'reviewer',True,1,{'principal':'owner'}):
            with self.subTest(principal=principal):
                record=self.fixture.sessions[key]
                if principal is None:record.pop('principal',None)
                else:record['principal']=principal
                response,_=self.request();self.assertEqual(response.status,403)
        self.fixture.sessions[key]['principal']='owner';self.fixture.now+=3601
        response,_=self.request();self.assertEqual(response.status,401)
        self.assertEqual(self.backend.limits_calls,[])

    def test_owner_app_grant_and_revocation_use_existing_admission(self):
        # INV-WLIM-12: app cookie is bound to a real private synthetic grant DB.
        token=self.fixture.login(app=True)['device_token']
        response,value=self.request();self.assertEqual(response.status,200)
        self.assertEqual(value,self.backend.limits_value)
        auth=importlib.import_module('_control_web_android_auth')
        store=auth.DeviceGrantStore(self.fixture.directory/'devices.sqlite',lambda:self.fixture.now)
        device=store.admit(token,foreground_open=False);self.assertIsInstance(device,str);store.revoke(device)
        response,_=self.request();self.assertEqual(response.status,401)
        self.assertEqual(len(self.backend.limits_calls),1)

    def test_unexpected_or_duplicate_query_and_foreign_origin_rejected(self):
        # INV-WLIM-12
        self.fixture.login()
        for suffix in ('?account=other','?source=claude','?socket=/private','?path=/private','?x=1&x=2','?project=demo'):
            with self.subTest(suffix=suffix):self.assertEqual(self.request(suffix)[0].status,422)
        response,_=self.request(headers=[('Origin','https://evil.example.invalid')]);self.assertEqual(response.status,403)
        self.assertEqual(self.backend.limits_calls,[])

    def test_backend_exception_or_bad_DTO_never_exports_private_details(self):
        # INV-WLIM-12
        self.fixture.login()
        for value in ({'error':s.PRIVATE},{**s.overview(),'private':s.PRIVATE}, {'schema':True},None):
            with self.subTest(kind=type(value).__name__):
                self.backend.limits_value=value;response,body=self.request()
                self.assertGreaterEqual(response.status,500);self.assertLess(response.status,600)
                self.assertNotIn(s.PRIVATE,json.dumps(body));self.assertIn('no-store',response.getheader('cache-control',''))
        self.backend.limits_failure=RuntimeError(s.PRIVATE);response,body=self.request()
        self.assertGreaterEqual(response.status,500);self.assertNotIn(s.PRIVATE,json.dumps(body))


class LimitsBrokerRED(unittest.TestCase):
    start=broker_fixture.SessionModelsBroker.start
    shutdown=broker_fixture.SessionModelsBroker.shutdown
    wire=broker_fixture.SessionModelsBroker.wire
    def setUp(self):
        broker_fixture.SessionModelsBroker.setUp(self);self.backend=s.LimitsBackend()

    def test_fixed_noargs_operation_and_SocketBackend_roundtrip(self):
        # INV-WLIM-12
        self.start();self.assertEqual(self.wire({'op':'limits_overview'}),self.backend.limits_value)
        client=self.module.SocketBackend(self.socket_path);method=getattr(client,'limits_overview',None)
        self.assertTrue(callable(method),'SocketBackend.limits_overview missing')
        self.assertEqual(method(),self.backend.limits_value)
        self.assertEqual(len(self.backend.limits_calls),2)

    def test_broker_extra_fields_and_duplicate_operation_rejected(self):
        # INV-WLIM-12
        self.start()
        for request in ({'op':'limits_overview','account':'other'},{'op':'limits_overview','socket':'/private'},
                        {'op':'limits_overview','project':'demo'},b'{"op":"limits_overview","op":"snapshot"}'):
            with self.subTest(kind=type(request).__name__):self.assertEqual(self.wire(request).get('error'),'invalid_request')
        self.assertEqual(self.backend.limits_calls,[])

    def test_wrong_peer_uid_still_rejected_without_native_read(self):
        # INV-WLIM-10 INV-WLIM-12
        original=self.module.serve_broker
        def denied(path,backend,uid,**kwargs):return original(path,backend,uid+1,**kwargs)
        with patch.object(self.module,'serve_broker',denied):
            self.start()
            try:value=self.wire({'op':'limits_overview'})
            except (ConnectionResetError,EOFError,json.JSONDecodeError):value={'error':'forbidden'}
        self.assertIn(value.get('error'),('forbidden','unavailable','invalid_request'))
        self.assertEqual(self.backend.limits_calls,[])

    def test_registry_backend_exposes_only_noargs_chat_projection(self):
        # INV-WLIM-12
        registry=self.base/'registry';registry.mkdir(mode=0o700)
        class Chat:
            def __init__(self):self.calls=0
            def limits_overview(self):self.calls+=1;return s.overview()
        chat=Chat();backend=self.module.RegistryBackend(str(registry),str(live.ROOT/'bin'),sessions=chat)
        method=getattr(backend,'limits_overview',None);self.assertTrue(callable(method),'RegistryBackend.limits_overview missing')
        self.assertEqual(method(),s.overview());self.assertEqual(chat.calls,1)


if __name__=='__main__':unittest.main()
