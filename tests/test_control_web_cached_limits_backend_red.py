"""Independent INV-WLIM-20..23 RED from frozen cached-sources spec only.

Runtime bodies are deliberately unread. All input files are private synthetic
fixtures; existing HTTP/native fixtures are imported through their public seams.
"""
from copy import deepcopy
import importlib
import inspect
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import cached_limits_backend_blind_support as s
import limits_dashboard_blind_support as native
import live_sse_blind_support as live
from test_control_web_session_chat_contract import feature


class CachedReaderRED(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_broker')
        self.temp = tempfile.TemporaryDirectory(prefix='cached-limits-blind-', dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.base.chmod(0o700)
        self.digest = self.base/'digest.json'; self.alp = self.base/'alp.json'
        self.write(self.digest, s.bot(), 0o664)

    def write(self, path, value, mode=0o600, raw=False):
        path.write_text(value if raw else json.dumps(value)); path.chmod(mode)

    def reader(self, alp=False):
        cls = getattr(self.module, 'CachedLimitsReader', None)
        self.assertTrue(callable(cls), 'INV-WLIM-21: public CachedLimitsReader seam missing')
        return cls(str(self.digest), str(self.alp) if alp else None, clock=lambda: s.NOW+9999)

    def snapshot(self, alp=False):
        reader = self.reader(alp)
        with patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')), \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('process forbidden')):
            value = reader.snapshot(s.NOW)
        self.assertIs(type(value), list); self.assertLessEqual(len(value), 32)
        keys = []
        for item in value:
            self.assertEqual(set(item), s.SOURCE_KEYS)
            self.assertEqual(item['max_age_seconds'], 2700)
            keys.append((item['node_id'], item['provider'], item['account_ref']))
            for window in item['windows']: self.assertEqual(set(window), native.WINDOW_KEYS)
            if item['prepaid'] is not None: self.assertEqual(set(item['prepaid']), s.PREPAID_KEYS)
        self.assertEqual(len(keys), len(set(keys)))
        text = json.dumps(value, allow_nan=False)
        self.assertNotIn(s.PRIVATE, text); self.assertNotIn(str(self.base), text)
        return value

    def pick(self, value, provider, node='llm'):
        matches = [x for x in value if x['node_id']==node and x['provider']==provider]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_bot_projection_four_quota_windows_and_two_distinct_currencies(self):
        # INV-WLIM-21 INV-WLIM-22: legacy cache never acquires account authority.
        value = self.snapshot(); kimi = self.pick(value, 'kimi')
        self.assertEqual((kimi['identity'], kimi['account_ref'], kimi['origin']), ('unbound', None, 'bot_cache'))
        self.assertEqual((kimi['observed_at'], kimi['age_seconds'], kimi['observation_basis']),
                         (s.NOW-10, 10, 'snapshot_tick'))
        by_bucket = {w['bucket']: w for w in kimi['windows']}
        self.assertEqual(set(by_bucket), {'five_hour','seven_day','month_total','month_code'})
        for bucket, duration, remaining in [('five_hour',300,75),('seven_day',10080,50),
                                            ('month_total',None,25),('month_code',None,0)]:
            w = by_bucket[bucket]; self.assertEqual((w['duration_minutes'],w['remaining_percent']), (duration,remaining))
            self.assertEqual(w['resets_at'], s.NOW+3600)
        for provider, currency in [('openrouter','USD'),('yandex','RUB')]:
            item = self.pick(value, provider)
            self.assertEqual((item['status'],item['identity'],item['account_ref']), ('ok','unbound',None))
            self.assertEqual(item['prepaid']['currency'], currency)
            self.assertEqual(item['prepaid']['balance'], 9.25)
            self.assertEqual({k:item['prepaid'][k] for k in ('scale','scale_at','spend_day','spend_week','burn_per_day','forecast_days')},
                             dict(scale=10,scale_at=s.NOW-86400,spend_day=.5,spend_week=2,burn_per_day=.25,forecast_days=37))
            self.assertEqual((item['observed_at'],item['age_seconds']), (s.NOW-20,20))
        self.assertEqual(self.digest.stat().st_mode & 0o777, 0o664)
        placeholders = [self.pick(value,p,'alp') for p in ('codex','claude')]
        self.assertTrue(all((x['status'],x['reason'],x['identity'],x['account_ref']) ==
                            ('unavailable','missing_source','unknown',None) for x in placeholders))

    def test_prepaid_nodata_error_last_known_and_optional_invalid_metrics(self):
        # INV-WLIM-22: last_balance is never advertised as a current balance.
        for status in ('nodata','error'):
            with self.subTest(status=status):
                bot = s.bot(); bot['snapshot']['yandex'].update(status=status,last_balance=-1.5,last_at=s.stamp(s.NOW-200))
                self.write(self.digest, bot)
                item = self.pick(self.snapshot(),'yandex')
                self.assertEqual((item['status'],item['reason'],item['prepaid']), ('unavailable','source_error',None))
                self.assertEqual(item['last_known'], dict(currency='RUB',balance=-1.5,observed_at=s.NOW-200))
                self.assertEqual(self.pick(self.snapshot(),'openrouter')['status'],'ok')
        bot=s.bot(); bot['snapshot']['openrouter'].update(scale=0,spend_day=True,spend_week=-1,
                 burn_per_day='12',forecast_days=1e10)
        self.write(self.digest,bot); item=self.pick(self.snapshot(),'openrouter')
        self.assertEqual(item['prepaid']['balance'],9.25)
        for key in ('scale','spend_day','spend_week','burn_per_day','forecast_days'):
            self.assertIsNone(item['prepaid'][key])
        bot['snapshot']['yandex'].update(status='error',last_balance=3,last_at=s.stamp(s.NOW+1))
        self.write(self.digest,bot); self.assertIsNone(self.pick(self.snapshot(),'yandex')['last_known'])

    def test_bot_provenance_future_naive_missing_and_exact_stale_boundary(self):
        # INV-WLIM-22: delivery timestamp does not refresh old provider observations.
        for age, status in ((2699,'ok'),(2700,'stale'),(86400,'stale')):
            with self.subTest(age=age):
                bot=s.bot(); bot['snapshot']['openrouter']['captured_at']=s.stamp(s.NOW-age)
                self.write(self.digest,bot); item=self.pick(self.snapshot(),'openrouter')
                self.assertEqual((item['status'],item['age_seconds']), (status,age))
        for field, value in [('received_at',s.stamp(s.NOW+1)),('received_at','2027-01-15T08:00:00'),
                             ('received_at',None),('captured_at',s.stamp(s.NOW+1)),('captured_at',None)]:
            with self.subTest(field=field,value=value):
                bot=s.bot(); target=bot if field=='received_at' else bot['snapshot']; target[field]=value
                self.write(self.digest,bot)
                self.assertTrue(all(x['status']=='unavailable' for x in self.snapshot() if x['node_id']=='llm'))
        bot=s.bot(); bot['snapshot']['openrouter']['captured_at']=s.stamp(s.NOW+1)
        bot['snapshot'].pop('yandex'); self.write(self.digest,bot); value=self.snapshot()
        self.assertEqual(self.pick(value,'openrouter')['reason'],'invalid_snapshot')
        self.assertIsNone(self.pick(value,'openrouter')['prepaid'])
        self.assertEqual(self.pick(value,'yandex')['reason'],'missing_source')
        self.assertEqual(self.pick(value,'kimi')['status'],'ok')
        bot=s.bot(); bot['received_at']=s.stamp(s.NOW-40)
        bot['snapshot']['captured_at']=s.stamp(s.NOW-50)
        self.write(self.digest,bot); item=self.pick(self.snapshot(),'openrouter')
        self.assertEqual((item['status'],item['reason'],item['prepaid']),('unavailable','invalid_snapshot',None))

    def test_kimi_error_unknown_percent_and_reset_expiry_never_invent_zero(self):
        # INV-WLIM-22
        for remaining in (True,-1,101,'75',None):
            with self.subTest(remaining=remaining):
                bot=s.bot(); bot['snapshot']['kimi']['five_hour']['remaining']=remaining
                bot['snapshot']['kimi']['seven_day']['resets_at']=s.stamp(s.NOW)
                self.write(self.digest,bot); windows=self.pick(self.snapshot(),'kimi')['windows']
                for bucket in ('five_hour','seven_day'):
                    self.assertIsNone(next(w for w in windows if w['bucket']==bucket)['remaining_percent'])
        bot=s.bot(); bot['snapshot']['kimi']['status']='error'; self.write(self.digest,bot)
        item=self.pick(self.snapshot(),'kimi')
        self.assertEqual((item['status'],item['reason'],item['windows']), ('unavailable','source_error',[]))

    def test_file_permissions_type_owner_and_no_follow_are_enforced(self):
        # INV-WLIM-21: real files/links/FIFO; no blocking read from a named pipe.
        self.reader()
        for kind in ('worldwrite','symlink','fifo','directory','hardlink','foreign_owner'):
            with self.subTest(kind=kind):
                if self.digest.exists() or self.digest.is_symlink():
                    if self.digest.is_dir(): self.digest.rmdir()
                    else: self.digest.unlink()
                if kind=='symlink':
                    target=self.base/'target'; self.write(target,s.bot()); self.digest.symlink_to(target)
                elif kind=='fifo': os.mkfifo(self.digest,0o600)
                elif kind=='directory': self.digest.mkdir(mode=0o700)
                elif kind=='hardlink':
                    target=self.base/'linked'; self.write(target,s.bot()); os.link(target,self.digest)
                else: self.write(self.digest,s.bot(),0o666 if kind=='worldwrite' else 0o600)
                before=time.monotonic()
                context=patch.object(os,'geteuid',return_value=os.geteuid()+1) if kind=='foreign_owner' else patch.object(time,'sleep',side_effect=AssertionError('no wait'))
                def timed_out(*_): raise AssertionError('FIFO/unsafe file read exceeded one second')
                previous=signal.signal(signal.SIGALRM,timed_out)
                signal.setitimer(signal.ITIMER_REAL,1)
                try:
                    with context: value=self.snapshot()
                finally:
                    signal.setitimer(signal.ITIMER_REAL,0); signal.signal(signal.SIGALRM,previous)
                self.assertLess(time.monotonic()-before,1,'FIFO must be opened nonblocking')
                self.assertTrue(all(x['status']=='unavailable' for x in value if x['node_id']=='llm'))

    def test_json_duplicate_keys_nonfinite_and_size_fail_closed_alp_isolated(self):
        # INV-WLIM-21: each invalid file is independent of the other source.
        self.reader(True); self.write(self.alp,s.alp())
        for raw in ('{"snapshot":{},"snapshot":{}}','{"x":NaN}','{"x":Infinity}',
                    '[]','null','{"padding":"'+'x'*(1024*1024)+'"}'):
            with self.subTest(kind=raw[:30]):
                self.write(self.digest,raw,raw=True)
                value=self.snapshot(True)
                self.assertTrue(all(x['status']=='unavailable' for x in value if x['node_id']=='llm'))
                self.assertEqual(self.pick(value,'codex','alp')['status'],'ok')

    def test_atomic_replacement_exposes_whole_new_snapshot_without_touching_cache(self):
        # INV-WLIM-21 INV-WLIM-22
        reader=self.reader(); before=self.digest.read_bytes()
        self.assertEqual(self.pick(reader.snapshot(s.NOW),'openrouter')['prepaid']['balance'],9.25)
        self.assertEqual(self.digest.read_bytes(),before)
        next_value=s.bot(); next_value['snapshot']['openrouter']['balance']=4
        replacement=self.base/'next'; self.write(replacement,next_value,0o664); replacement.replace(self.digest)
        value=reader.snapshot(s.NOW)
        self.assertEqual(self.pick(value,'openrouter')['prepaid']['balance'],4)
        self.assertEqual(self.pick(value,'yandex')['prepaid']['balance'],9.25)

    def test_alp_uuid4_hash_tick_semantics_slots_and_duration_not_inferred(self):
        # INV-WLIM-23: owner reference and raw labels never reach the public DTO.
        windows=[dict(slot=slot,used_percent=25,reset=s.stamp(s.NOW+3600),duration_seconds=duration)
                 for slot,duration in [('five_hour',None),('seven_day',None),('scoped:sonnet',18000)]]
        self.write(self.alp,s.alp(s.alp_account('claude',windows=windows),s.alp_account()))
        value=self.snapshot(True); codex=self.pick(value,'codex','alp'); claude=self.pick(value,'claude','alp')
        self.assertEqual(codex['account_ref'],s.hashed())
        self.assertEqual(claude['account_ref'],s.hashed('claude'))
        self.assertEqual((codex['identity'],codex['observed_at'],codex['age_seconds'],codex['observation_basis']),
                         ('collector_mapped',s.NOW-30,30,'snapshot_tick'))
        self.assertEqual(codex['windows'][0]['bucket'],'primary')
        by_bucket={w['bucket']:w for w in claude['windows']}
        self.assertEqual(set(by_bucket),{'five_hour','seven_day','scoped_sonnet'})
        for bucket in ('five_hour','seven_day'):
            self.assertIsNone(by_bucket[bucket]['duration_minutes'])
            self.assertIsNone(by_bucket[bucket]['window_started_at'])
            self.assertIsNone(by_bucket[bucket]['anchor'])
        self.assertEqual(by_bucket['scoped_sonnet']['duration_minutes'],300)
        self.assertNotIn(s.REF,json.dumps(value)); self.assertNotIn('scoped:sonnet',json.dumps(value))

    def test_alp_status_age_old_delivery_and_future_skew_never_refresh_observation(self):
        # INV-WLIM-23: producer metadata has no authority over freshness.
        for status,observed,expected,reason in [('ok',s.NOW-2700,'stale',None),
                ('stale',s.NOW-1,'stale',None),('missing',None,'unavailable','missing_source'),
                ('unknown',None,'unavailable','source_error'),('reset_pending',s.NOW-30,'unavailable','reset_pending'),
                ('future',s.NOW+1,'unavailable','invalid_snapshot'),('ok',s.NOW+1,'unavailable','invalid_snapshot')]:
            with self.subTest(status=status,observed=observed):
                value=s.alp(s.alp_account(status=status,observed_at=s.stamp(observed) if observed else None))
                value['freshness']=dict(max_age_seconds=86400,future_skew_seconds=300)
                self.write(self.alp,value); item=self.pick(self.snapshot(True),'codex','alp')
                self.assertEqual((item['status'],item['reason']), (expected,reason))
                self.assertEqual(item['account_ref'],s.hashed())
                if expected=='unavailable': self.assertEqual(item['windows'],[])
                if observed is None or observed>s.NOW:
                    self.assertEqual((item['observed_at'],item['age_seconds'],item['observation_basis']), (None,None,'unknown'))
                else: self.assertEqual(item['age_seconds'],s.NOW-observed)

    def test_alp_strict_allowlist_refs_duplicates_bad_numbers_and_mode0600(self):
        # INV-WLIM-21 INV-WLIM-23
        self.reader(True)
        invalid=[]
        for ref in ('freeform',s.REF.upper(),'11111111-1111-1111-8111-111111111111',
                    '11111111-1111-4111-1111-111111111111'):
            invalid.append(s.alp(s.alp_account(ref=ref)))
        invalid.append(s.alp(s.alp_account(),s.alp_account()))
        invalid.append({**s.alp(),'credentials':s.PRIVATE})
        invalid.append(s.alp(s.alp_account(private=s.PRIVATE)))
        invalid.append({**s.alp(),'exported_at':s.stamp(s.NOW+1)})
        invalid.append({**s.alp(),'freshness':dict(max_age_seconds=True,future_skew_seconds=0)})
        invalid.append({**s.alp(),'accounts':[s.alp_account(ref=f'{i:08x}-1111-4111-8111-111111111111') for i in range(17)]})
        for value in invalid:
            with self.subTest(kind=str(value)[:60]):
                self.write(self.alp,value); items=self.snapshot(True)
                self.assertTrue(all(x['status']=='unavailable' for x in items if x['node_id']=='alp'))
                self.assertEqual(self.pick(items,'kimi')['status'],'ok')
        for mode in (0o640,0o644,0o664):
            with self.subTest(mode=oct(mode)):
                self.write(self.alp,s.alp(),mode); items=self.snapshot(True)
                self.assertTrue(all(x['status']=='unavailable' for x in items if x['node_id']=='alp'))
                self.assertEqual(self.alp.stat().st_mode & 0o777,mode)
        for used,reset in ((True,s.NOW+1),(-1,s.NOW+1),(101,s.NOW+1),(25,s.NOW)):
            with self.subTest(used=used,reset=reset):
                account=s.alp_account(); account['windows'][0].update(used_percent=used,reset=s.stamp(reset))
                self.write(self.alp,s.alp(account)); item=self.pick(self.snapshot(True),'codex','alp')
                self.assertIsNone(item['windows'][0]['remaining_percent'])


class CachedCompositionRED(unittest.TestCase):
    def setUp(self):
        self.module=feature(self,'_control_web_broker')
        self.temp=tempfile.TemporaryDirectory(prefix='cached-compose-blind-',dir='/var/tmp')
        self.addCleanup(self.temp.cleanup); self.base=Path(self.temp.name)

    def backend(self, chat, reader):
        self.assertIn('cached_limits_reader',inspect.signature(self.module.RegistryBackend).parameters,
                      'INV-WLIM-20: RegistryBackend reader injection missing')
        return self.module.RegistryBackend(str(self.base),str(live.ROOT/'bin'),sessions=chat,
                                           cached_limits_reader=reader)

    def test_registry_keeps_native_v1_and_uses_native_clock_for_cached_composition(self):
        # INV-WLIM-20
        calls=[]
        class Chat:
            def limits_overview(self): return native.overview()
        class Reader:
            def snapshot(self,now): calls.append(now); return [s.source()]
        legacy=self.module.RegistryBackend(str(self.base),str(live.ROOT/'bin'),sessions=Chat())
        self.assertEqual(legacy.limits_overview(),native.overview())
        value=self.backend(Chat(),Reader()).limits_overview()
        self.assertEqual(value,dict(schema=2,server_now=s.NOW,native=native.overview(),cached_sources=[s.source()]))
        self.assertEqual(calls,[s.NOW])
        class BrokenReader:
            def snapshot(self,now): raise RuntimeError(s.PRIVATE)
        isolated=self.backend(Chat(),BrokenReader()).limits_overview()
        self.assertEqual(isolated['native'],native.overview())
        self.assertNotIn(s.PRIVATE,json.dumps(isolated))

    def test_native_failure_keeps_typed_v1_unavailable_and_other_sources(self):
        # INV-WLIM-20
        calls=[]
        class Chat:
            def limits_overview(self): raise RuntimeError(s.PRIVATE)
        class Reader:
            def snapshot(self,now): calls.append(now); return [s.source()]
        backend=self.backend(Chat(),Reader())
        with patch.object(self.module.time,'time',return_value=s.NOW): value=backend.limits_overview()
        expected=dict(schema=1,server_now=s.NOW,coverage=dict(scope='llm_native_only',partial=True),
                      sources=[native.unavailable('codex','source_unavailable'),native.unavailable('claude','source_unavailable')])
        self.assertEqual(value['native'],expected); self.assertEqual(value['cached_sources'],[s.source()])
        self.assertEqual(value['server_now'],value['native']['server_now']); self.assertEqual(calls,[s.NOW])
        self.assertNotIn(s.PRIVATE,json.dumps(value))


class CachedOwnerValidatorRED(unittest.TestCase):
    def setUp(self): self.module=feature(self,'_control_web_broker')

    def accepted(self,value): self.assertEqual(self.module.limits_result(value),value)

    def rejected(self,value):
        result=self.module.limits_result(value)
        self.assertEqual(result,{'error':'unavailable'})
        self.assertNotIn(s.PRIVATE,json.dumps(result))

    def test_owner_validator_accepts_v1_and_exact_v2_money_quota_unknown(self):
        # INV-WLIM-20 INV-WLIM-21
        self.accepted(native.overview()); self.accepted(s.wrapper())
        debt=s.source(); debt['prepaid']['balance']=-1.5
        unknown=s.source('kimi',status='unavailable',reason='source_error',observed_at=None,
                         observation_basis='unknown',age_seconds=None,windows=[])
        self.accepted(s.wrapper(debt,unknown))
        historical=s.source('yandex',status='unavailable',reason='source_error',prepaid=None,
                            observed_at=None,age_seconds=None,observation_basis='unknown',
                            last_known=dict(currency='RUB',balance=2,observed_at=s.NOW-200))
        self.accepted(s.wrapper(historical))

    def test_owner_validator_exact_keys_types_counts_private_canaries_and_duplicates(self):
        # INV-WLIM-20 INV-WLIM-21: validate valid control before each corruption.
        valid=s.wrapper()
        mutations=[lambda v:v.update(private=s.PRIVATE),lambda v:v.update(schema=True),
            lambda v:v.update(server_now=s.NOW+1),lambda v:v['native'].update(private=s.PRIVATE),
            lambda v:v['cached_sources'][0].update(private=s.PRIVATE),
            lambda v:v['cached_sources'][0].update(account_ref='user@example.invalid'),
            lambda v:v['cached_sources'][0]['prepaid'].update(currency='EUR'),
            lambda v:v['cached_sources'][0]['prepaid'].update(private=s.PRIVATE),
            lambda v:v['cached_sources'][0].update(max_age_seconds=86400),
            lambda v:v['cached_sources'][0].update(node_id='private-host'),
            lambda v:v['cached_sources'][0].update(identity='native_reported'),
            lambda v:v['cached_sources'].append(deepcopy(v['cached_sources'][0])),
            lambda v:v.update(cached_sources=[s.source(account_ref=f'{i:064x}',identity='collector_mapped') for i in range(33)]),
            lambda v:v['cached_sources'][1]['windows'][0].update(label=s.PRIVATE),
            lambda v:v['cached_sources'][1].update(windows=v['cached_sources'][1]['windows']*9)]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                self.accepted(valid); value=deepcopy(valid); mutate(value); self.rejected(value)

    def test_owner_validator_provenance_nonfinite_and_money_bounds_fail_closed(self):
        # INV-WLIM-21 INV-WLIM-22 INV-WLIM-23
        edits=[('observed_at',s.NOW+1),('age_seconds',0),('age_seconds',True),('observed_at',float('nan'))]
        for key,new in edits:
            with self.subTest(key=key,value=new):
                value=s.wrapper(); self.accepted(value); value['cached_sources'][0][key]=new; self.rejected(value)
        for key,bad in [('balance',True),('balance',float('inf')),('balance',1e12+1),
                        ('scale',0),('spend_day',-1),('spend_week','2'),('forecast_days',1e9+1)]:
            with self.subTest(key=key,value=bad):
                value=s.wrapper(); self.accepted(value); value['cached_sources'][0]['prepaid'][key]=bad; self.rejected(value)


class CachedHTTPRED(unittest.TestCase):
    def setUp(self):
        original=live.Backend; live.Backend=native.LimitsBackend
        try: self.fixture=live.Fixture(session_store=True)
        finally: live.Backend=original
        self.addCleanup(self.fixture.stop); self.backend=self.fixture.backend
        self.backend.limits_value=s.wrapper()

    def request(self,**kwargs):
        connection,response=self.fixture.request('/api/limits-overview',**kwargs)
        body=json.loads(response.read()); connection.close(); return response,body

    def test_v2_http_owner_cookie_and_app_grant_preserve_wrapper_no_store(self):
        # INV-WLIM-20: authentication precedes collection in both existing flows.
        response,_=self.request(cookie=False); self.assertEqual(response.status,401)
        self.assertEqual(self.backend.limits_calls,[])
        for app in (False,True):
            with self.subTest(app=app):
                self.fixture.login(app=app); response,value=self.request()
                self.assertEqual(response.status,200); self.assertEqual(value,s.wrapper())
                self.assertIn('no-store',response.getheader('cache-control',''))

    def test_http_v2_private_or_invalid_source_is_never_serialized(self):
        # INV-WLIM-20 INV-WLIM-21: invalid v2 rejection needs a valid-v2 control.
        self.fixture.login(); response,value=self.request()
        self.assertEqual(response.status,200); self.assertEqual(value,s.wrapper())
        self.backend.limits_value['cached_sources'][0]['private']=s.PRIVATE
        response,body=self.request(); self.assertGreaterEqual(response.status,500)
        self.assertLess(response.status,600); self.assertNotIn(s.PRIVATE,json.dumps(body))


if __name__=='__main__': unittest.main()
