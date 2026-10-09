"""Independent INV-WSESS-51/52 actual HTTP and scheduler RED; no source reads."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import http.client
import json
import re
import threading
import time
import unittest
import live_sse_blind_support as s

BASE = '?project=demo&sid='+s.SID

class LiveHTTPBlind(unittest.TestCase):
    def setUp(self):
        self.fixture = s.Fixture(); self.addCleanup(self.fixture.stop)
        self.fixture.login(); self.backend = self.fixture.backend

    def response(self, path='/api/session-live-snapshot', **kwargs):
        connection, response = self.fixture.request(path+BASE, **kwargs)
        self.addCleanup(connection.close)
        return response

    def expect_error(self, path, status, error, **kwargs):
        connection, response = self.fixture.request(path, **kwargs)
        try:
            self.assertEqual(response.status, status, 'Actual public route HTTP outcome')
            self.assertEqual(response.read(), s.encoded({'error':error}))
            self.assertEqual(response.getheader('cache-control'), 'no-store')
        finally: connection.close()

    def snapshot(self, **kwargs):
        response = self.response(**kwargs)
        self.assertEqual(response.status,200,'Actual snapshot route must exist and admit fresh owner proof')
        value = json.loads(response.read()); self.assert_snapshot(value)
        return value

    def assert_snapshot(self, value):
        self.assertEqual(set(value), {'schema','project','sid','epoch','revision','observation','source','observed_at','history'})
        self.assertIs(type(value['schema']),int); self.assertEqual(value['schema'],1)
        self.assertEqual((value['project'],value['sid'],value['source']),('demo',s.SID,'owner_history_poll'))
        self.assertRegex(value['epoch'],r'\A[0-9a-f]{32}\Z')
        for key in ('revision','observation'):
            self.assertIs(type(value[key]),int); self.assertGreaterEqual(value[key],1); self.assertLessEqual(value[key],2**53-1)
        self.assertIs(type(value['observed_at']),int); self.assertGreaterEqual(value['observed_at'],0)
        self.assertLessEqual(value['observed_at'],253402300799999)
        self.assertNotIn('scope_id',value); self.assertNotIn(str(self.fixture.directory),json.dumps(value))

    def stream(self, headers=None, sid=s.SID):
        connection,response=self.fixture.request('/api/session-events?project=demo&sid='+sid,
            headers=[('Accept','text/event-stream'),*(headers or [])])
        self.addCleanup(connection.close)
        self.assertEqual(response.status,200,'Actual SSE route must return200, not baseline404')
        return connection,response

    def test_authenticated_fresh_snapshot_exact_DTO(self):
        value=self.snapshot(); self.assertEqual(value['history'],self.backend.value)
        self.assertEqual(len(self.backend.calls),1)

    def test_initial_SSE_snapshot_before_updates_and_headers(self):
        _,response=self.stream()
        self.assertIn('text/event-stream',response.getheader('content-type'))
        self.assertEqual(response.getheader('cache-control'),'no-store')
        self.assertEqual(response.getheader('x-accel-buffering'),'no')
        first=s.event(response); self.assertEqual(first['event'],'snapshot'); self.assert_snapshot(first['data'])
        self.assertEqual(first['id'],first['data']['epoch']+':'+str(first['data']['revision']))
        self.backend.value=s.history('LIVE changed synthetic text')
        second=s.event(response); self.assertEqual(second['event'],'snapshot')
        self.assertGreater(second['data']['revision'],first['data']['revision'])
        self.assertEqual(second['data']['history'],self.backend.value)

    def test_auth_missing_arbitrary_expired_401_before_owner(self):
        for route in ('/api/session-events','/api/session-live-snapshot'):
            for cookie in (None,'control_session=synthetic-invalid-capability'):
                with self.subTest(route=route,cookie='absent' if cookie is None else 'invented'):
                    self.expect_error(route+BASE,401,'unauthorized',cookie=False,
                        headers=[('Accept','text/event-stream')]+([] if cookie is None else [('Cookie',cookie)]))
        self.assertEqual(self.backend.calls,[])
        self.fixture.now+=3601
        self.expect_error('/api/session-live-snapshot'+BASE,401,'unauthorized')
        self.assertEqual(self.backend.calls,[])

    def test_origin_fetch_guards_before_capacity_and_backend(self):
        for headers in ([('Origin','null')],[('Origin',self.fixture.origin+'/')],
            [('Origin',self.fixture.origin),('Origin',self.fixture.origin)],
            *[[('Sec-Fetch-Site',value)] for value in ('cross-site','same-site','none')]):
            with self.subTest(headers=headers):
                self.expect_error('/api/session-live-snapshot'+BASE,403,'forbidden',headers=headers)
        self.assertEqual(self.backend.calls,[])

    def test_query_LastEventID_strict_422_before_auth(self):
        invalid=('?project=demo&sid=bad',BASE+'&sid='+s.SID,BASE+'&project=demo',BASE+'&x=1',
            '?project=../demo&sid='+s.SID,'?project=demo&sid='+s.SID.upper())
        # Use a UUID with letters for uppercase spelling, rather than all-digitSID.
        invalid=invalid[:-1]+('?project=demo&sid=ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF',)
        for query in invalid:
            with self.subTest(query=query):
                self.expect_error('/api/session-events'+query,422,'invalid_request',cookie=False,headers=[('Accept','text/event-stream')])
        for identifier in ('bad','a'*32+':0','a'*32+':9007199254740992','A'*32+':1'):
            with self.subTest(identifier=identifier):
                self.expect_error('/api/session-events'+BASE,422,'invalid_request',cookie=False,
                    headers=[('Accept','text/event-stream'),('Last-Event-ID',identifier)])
        self.assertEqual(self.backend.calls,[])

    def test_current_validator_accepts_uppercase_and_leading_digit_alias(self):
        for alias in ('ALP','7r'):
            connection,response=self.fixture.request('/api/session-live-snapshot?project='+alias+'&sid='+s.SID)
            try:
                self.assertEqual(response.status,200); value=json.loads(response.read())
                self.assertEqual(value['project'],alias); self.assertEqual(self.backend.calls[-1]['project'],alias)
            finally:connection.close()

    def test_owner_failure_closed_and_unsupported_only_exact(self):
        for outcome,error in (({'error':'busy'},'unavailable'),({'error':'unavailable'},'unavailable'),
            ({'error':'unsupported'},'unsupported'),(RuntimeError('synthetic private failure'),'unavailable'),
            ({'schema':True,'scope_id':'1'*64,'history':s.history()},'unavailable')):
            with self.subTest(outcome=type(outcome).__name__,error=error):
                self.backend.outcome=outcome
                self.expect_error('/api/session-live-snapshot'+BASE,503,error)

    def test_utf8_compact_sorted_wire_and_history_budget(self):
        value=s.history('😀\\"\t'*600); items=value['turns'][0]['items']
        template=deepcopy(items[0]); template['text']='é'*3900
        items[:]=[dict(template,id='item-'+str(i)) for i in range(12)]
        self.assertLessEqual(len(s.encoded(value)),96*1024)
        self.backend.value=value
        response=self.response(); self.assertEqual(response.status,200)
        raw=response.read(); public=json.loads(raw); self.assert_snapshot(public)
        self.assertEqual(raw,s.encoded(public)); self.assertEqual(public['history'],value)
        self.assertLessEqual(len(raw)-len(s.encoded(value)),4096); self.assertLessEqual(len(raw),100*1024)
        self.backend.value['turns'][0]['items'][0]['text']='bad\ud800'
        self.expect_error('/api/session-live-snapshot'+BASE,503,'unavailable')

    def test_hash_excludes_only_settings_age_and_expires(self):
        first=self.snapshot(); self.backend.value['session_settings']=s.settings(age=100)
        second=self.snapshot(); self.assertEqual(second['revision'],first['revision'])
        self.assertGreater(second['observation'],first['observation']); self.assertEqual(second['epoch'],first['epoch'])
        changes=(lambda h:h['turns'][0]['items'][0].update(timestamp=1770000001),
            lambda h:h['turns'][0]['items'][0].update(time_precision='turn'),
            lambda h:h.update(truncated=True),lambda h:h['session_settings'].update(model='producer-B'),
            lambda h:h.update(recent_sends=[dict(status='delivery_unknown',message_id=s.OTHER,turn_id=None)]))
        for change in changes:
            change(self.backend.value); next_value=self.snapshot()
            self.assertGreater(next_value['revision'],second['revision']); second=next_value

    def test_unavailable_history_is_valid_but_unknown_fields_refused(self):
        self.backend.value={'history_state':'unavailable','reason':'unavailable','recent_sends':[]}
        value=self.snapshot(); self.assertEqual(value['history'],self.backend.value)
        self.backend.value['guessed_elapsed']=3
        self.expect_error('/api/session-live-snapshot'+BASE,503,'unavailable')

    def test_native_LastEventID_fresh_and_reset_branches(self):
        first=self.snapshot(); epoch=first['epoch']; revision=first['revision']
        for identifier,reason in ((epoch+':'+str(revision),None),(epoch+':'+str(revision+100),'reconnect'),('f'*32+':1','epoch_changed')):
            connection,response=self.stream([('Last-Event-ID',identifier)])
            initial=s.event(response)
            if reason:
                self.assertEqual(initial['event'],'reset'); self.assertNotIn('id',initial)
                self.assertEqual(initial['data']['reason'],reason); initial=s.event(response)
            self.assertEqual(initial['event'],'snapshot'); self.assertGreater(initial['data']['observation'],first['observation'])
            connection.close()

    def test_per_cookie_cap_includes_two_streams_and_renewal(self):
        self.stream(); self.stream()
        self.expect_error('/api/session-live-snapshot'+BASE,429,'unavailable')
        self.assertEqual(self.backend.maximum,1)

    def test_global8_cap_across_real_login_cookies(self):
        for _ in range(4):
            self.fixture.login(); self.stream(); self.stream()
        self.fixture.login(); self.expect_error('/api/session-live-snapshot'+BASE,429,'unavailable')
        self.assertEqual(self.backend.maximum,1)

    def test_read_start_cut_late_waiter_fresh_singleflight_mininterval(self):
        # Baseline assertion comes before concurrent harness: route404 is semantic.
        self.snapshot(); self.backend.calls.clear(); self.backend.gate.clear()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.snapshot)
            self.assertTrue(self.backend.wait_calls(1))
            first_start=self.backend.calls[0]['start']
            second=pool.submit(self.snapshot)
            time.sleep(.15); self.assertEqual(len(self.backend.calls),1)
            self.backend.gate.set(); a=first.result(8); b=second.result(8)
        self.assertGreater(b['observation'],a['observation'])
        self.assertEqual(self.backend.maximum,1); self.assertEqual(len(self.backend.calls),2)
        self.assertGreaterEqual(self.backend.calls[1]['start']-first_start,.99)

    def test_pending6s_timeout_does_not_cancel_actual_IO_or_create_thread(self):
        self.snapshot(); self.backend.calls.clear(); self.backend.gate.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            start=time.monotonic(); result=pool.submit(self.response)
            self.assertTrue(self.backend.wait_calls(1))
            response=result.result(8)
            self.assertEqual(response.status,503); self.assertEqual(response.read(),s.encoded({'error':'unavailable'}))
            elapsed=time.monotonic()-start; self.assertGreaterEqual(elapsed,5.8); self.assertLess(elapsed,7.5)
            self.assertEqual(self.backend.active,1,'Timed-out sync IO is still actual occupied work')
            self.assertEqual(len(self.backend.calls),1); self.backend.gate.set()

    def test_two_active_scopes_third429_no_speculative_owner_read(self):
        self.stream(sid=s.SID); self.stream(sid=s.OTHER)
        before=len(self.backend.calls)
        self.fixture.login()
        self.expect_error('/api/session-events?project=demo&sid='+s.THIRD,429,'unavailable',headers=[('Accept','text/event-stream')])
        self.assertEqual(len(self.backend.calls),before)

    def test_idle2s_reconnect_same_epoch_and12s_new_epoch_no_idle_IO(self):
        first=self.snapshot(); calls=len(self.backend.calls)
        time.sleep(2); self.assertEqual(len(self.backend.calls),calls)
        second=self.snapshot(); self.assertEqual(second['epoch'],first['epoch'])
        calls=len(self.backend.calls); time.sleep(10.5); self.assertEqual(len(self.backend.calls),calls)
        third=self.snapshot(); self.assertNotEqual(third['epoch'],second['epoch'])

    def test_periodic_failure_unavailable_close_without_old_queue(self):
        _,response=self.stream(); first=s.event(response); self.assertEqual(first['event'],'snapshot')
        self.backend.outcome={'error':'unavailable'}
        failed=s.event(response); self.assertEqual(failed['event'],'unavailable'); self.assertNotIn('id',failed)
        self.assertEqual(failed['data'],dict(schema=1,project='demo',sid=s.SID,error='unavailable'))
        self.assertIsNone(s.event(response))

    def test_unchanged_reads_have_no_snapshot_frames(self):
        connection,response=self.stream(); self.assertEqual(s.event(response)['event'],'snapshot')
        start=len(self.backend.calls); time.sleep(2.5)
        self.assertGreaterEqual(len(self.backend.calls),start+2)
        connection.sock.settimeout(.2)
        with self.assertRaises((TimeoutError,http.client.IncompleteRead)):
            s.event(response)

    def test_no_live_config_preserves_legacy_routes_but503_live(self):
        fixture=s.Fixture(configured=False); self.addCleanup(fixture.stop); fixture.login()
        connection,response=fixture.request('/api/session'); self.assertEqual(response.status,200); response.read(); connection.close()
        connection,response=fixture.request('/api/session-live-snapshot'+BASE)
        try:self.assertEqual(response.status,503); self.assertEqual(response.read(),s.encoded({'error':'unavailable'}))
        finally:connection.close()

    def test_owner_only_False_and_numeric1_are_forbidden(self):
        for gate in (False,1):
            fixture=s.Fixture(owner_only=gate); self.addCleanup(fixture.stop); fixture.login()
            connection,response=fixture.request('/api/session-live-snapshot'+BASE)
            try:self.assertEqual(response.status,403); self.assertEqual(response.read(),s.encoded({'error':'forbidden'}))
            finally:connection.close()

    def test_fair_round_robin_two_active_scopes_no_starvation(self):
        self.stream(sid=s.SID);self.stream(sid=s.OTHER)
        start=len(self.backend.calls);time.sleep(5)
        reads=self.backend.calls[start:];scopes=[row['sid'] for row in reads]
        self.assertGreaterEqual(scopes.count(s.SID),2);self.assertGreaterEqual(scopes.count(s.OTHER),2)
        self.assertFalse(any(a==b==c for a,b,c in zip(scopes,scopes[1:],scopes[2:])), 'One scope starves other eligible scope')
        self.assertEqual(self.backend.maximum,1)

    def test_eight_pending_reservations_coalesce_but_ninth429(self):
        self.snapshot();cookies=[]
        for _ in range(5):self.fixture.login();cookies.append(self.fixture.cookie)
        self.backend.calls.clear();self.backend.gate.clear()
        def read(cookie):
            connection,response=self.fixture.request('/api/session-live-snapshot'+BASE,cookie=False,headers=[('Cookie',cookie)])
            try:
                self.assertEqual(response.status,200);return json.loads(response.read())
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=8) as pool:
            first=pool.submit(read,cookies[0]);self.assertTrue(self.backend.wait_calls(1))
            remaining=[pool.submit(read,cookies[i//2]) for i in range(1,8)]
            time.sleep(.5)
            self.expect_error('/api/session-live-snapshot'+BASE,429,'unavailable',cookie=False,headers=[('Cookie',cookies[4])])
            self.assertEqual(len(self.backend.calls),1);self.backend.gate.set();initial=first.result(8)
            values=[future.result(8) for future in remaining]
        self.assertTrue(all(value['observation']>initial['observation'] for value in values))
        self.assertEqual(len({value['observation'] for value in values}),1,'All pre-cut pending same-scope requests coalesce one fresh observation')
        self.assertEqual(len(self.backend.calls),2);self.assertEqual(self.backend.maximum,1)

    def test_healthy_renewal_joins_next_periodic_read_without_accelerating(self):
        _,response=self.stream();s.event(response);first=self.backend.calls[-1]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.snapshot)
            time.sleep(.2);self.assertEqual(len(self.backend.calls),1,'Renewal must not accelerate periodic owner read')
            renewed=future.result(7)
        self.assertGreaterEqual(self.backend.calls[1]['start']-first['finish'],1.04)
        self.assertGreater(renewed['observation'],1);self.assertEqual(self.backend.maximum,1)

    def test_accepted_absent_or_exact_origin_and_same_origin_fetch(self):
        for headers in ([],[('Origin',self.fixture.origin)],[('Sec-Fetch-Site','same-origin')]):
            value=self.snapshot(headers=headers);self.assert_snapshot(value)

    def test_client_owner_header_claim_cannot_authenticate_arbitrary_cookie(self):
        self.expect_error('/api/session-live-snapshot'+BASE,401,'unauthorized',cookie=False,
            headers=[('Cookie','control_session=synthetic-invalid-capability'),('X-Principal','owner')])
        self.assertEqual(self.backend.calls,[])

    def test_actual_app_device_revoke_admission401_no_read(self):
        token=self.fixture.login(app=True)['device_token']
        auth=__import__('_control_web_android_auth')
        store=auth.DeviceGrantStore(self.fixture.directory/'devices.sqlite',lambda:self.fixture.now)
        device=store.admit(token,foreground_open=False);self.assertIsInstance(device,str)
        self.snapshot();before=len(self.backend.calls);store.revoke(device)
        self.expect_error('/api/session-live-snapshot'+BASE,401,'unauthorized')
        self.assertEqual(len(self.backend.calls),before)

    def test_two_cookies_same_device_share_two_slot_cap(self):
        token=self.fixture.login(app=True)['device_token'];self.stream()
        old=self.fixture.cookie;self.fixture.cookie=None
        connection,response=self.fixture.request('/api/app/session',method='POST',
            headers=[('Origin',self.fixture.origin),('Authorization','Bearer '+token)],body={'foreground_open':False})
        try:
            self.assertEqual(response.status,200);response.read()
            self.fixture.cookie=response.getheader('set-cookie').split(';',1)[0]
        finally:connection.close()
        self.assertNotEqual(self.fixture.cookie,old,'Distinct actual app-derived cookies needed for device grouping proof')
        self.stream();self.expect_error('/api/session-live-snapshot'+BASE,429,'unavailable')

    def test_waiting_stream_device_revoke_no_further_snapshot_yield(self):
        token=self.fixture.login(app=True)['device_token'];_,response=self.stream();s.event(response)
        auth=__import__('_control_web_android_auth')
        store=auth.DeviceGrantStore(self.fixture.directory/'devices.sqlite',lambda:self.fixture.now)
        device=store.admit(token,foreground_open=False);store.revoke(device)
        started=time.monotonic();self.backend.value=s.history('Must never yield after device revoke')
        following=s.event(response)
        self.assertTrue(following is None or following['event']=='unavailable')
        self.assertLess(time.monotonic()-started,2)

    def test_unknown_proof_cannot_evict_two_idle_retained_epochs(self):
        first=self.snapshot()
        connection,response=self.fixture.request('/api/session-live-snapshot?project=demo&sid='+s.OTHER)
        try:self.assertEqual(response.status,200);second=json.loads(response.read())
        finally:connection.close()
        self.backend.outcome={'error':'unavailable'}
        self.expect_error('/api/session-live-snapshot?project=demo&sid='+s.THIRD,503,'unavailable')
        self.backend.outcome=None
        renewed=self.snapshot();self.assertEqual(renewed['epoch'],first['epoch'])
        connection,response=self.fixture.request('/api/session-live-snapshot?project=demo&sid='+s.OTHER)
        try:self.assertEqual(response.status,200);self.assertEqual(json.loads(response.read())['epoch'],second['epoch'])
        finally:connection.close()

    def test_wedged_periodic_read_watchdog6s_closes_without_second_IO(self):
        connection,response=self.stream();s.event(response);self.backend.gate.clear()
        self.assertTrue(self.backend.wait_calls(2))
        started=time.monotonic();value=s.event(response)
        self.assertEqual(value['event'],'unavailable');self.assertLess(time.monotonic()-started,7)
        self.assertEqual(self.backend.active,1);self.assertEqual(self.backend.maximum,1)
        self.backend.gate.set();self.assertIsNone(s.event(response))

class LiveFactoryPrerequisites(unittest.TestCase):
    def test_public_session_store_seam(self):
        fixture=s.Fixture(session_store=True); self.addCleanup(fixture.stop)
        self.assertTrue(fixture.session_store_supported,'HARNESS PREREQUISITE: accepted public session_store keyword absent; not semantic RED')
        fixture.login(); self.assertEqual(len(fixture.sessions),1)
        record=next(iter(fixture.sessions.values())); self.assertEqual(record.get('principal'),'owner')
        for principal in (None,'nonowner'):
            if principal is None:record.pop('principal',None)
            else:record['principal']=principal
            connection,response=fixture.request('/api/session-live-snapshot'+BASE)
            try:self.assertEqual(response.status,403); self.assertEqual(response.read(),s.encoded({'error':'forbidden'}))
            finally:connection.close()
