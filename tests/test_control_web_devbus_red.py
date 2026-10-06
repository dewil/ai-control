"""Source-blind synthetic contract tests; no broker/native/service/network access.

FR-BUS-01 FR-BUS-02 FR-BUS-03 US-BUS-001
INV-DEVBUS-01 INV-DEVBUS-02 INV-DEVBUS-03 INV-DEVBUS-04 INV-DEVBUS-05
INV-DEVBUS-06 INV-DEVBUS-07 INV-DEVBUS-08 INV-DEVBUS-09
Browser contract (INV-DEVBUS-09) is covered in the companion browser suite.
"""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
ORIGIN = 'https://synthetic.invalid'
NOW = 1800000000.0


def feature(case, name='_control_web_devbus'):
    if importlib.util.find_spec(name) is None:
        case.fail('missing planned feature: ' + name)
    return importlib.import_module(name)


def timestamp(value=NOW):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def wire(kind='accepted', *, mid='m1', task='t1', source='worker1', at=None, payload=None):
    return json.dumps(dict(message_id=mid, task_id=task, correlation_id=task,
                           source=source, target='control', kind=kind,
                           created_at=timestamp() if at is None else at,
                           payload=payload or {}), allow_nan=False).encode()


class ProjectionRED(unittest.TestCase):
    def setUp(self):
        self.api = feature(self)
        self.now = NOW
        self.p = self.api.Projection(clock=lambda: self.now)

    def ingest(self, kind='accepted', seq=1, **kwargs):
        return self.p.ingest(wire(kind, **kwargs), 'devbus.events.' + kwargs.get('source', 'worker1'), seq)

    def test_schema_and_unknown_history_are_explicit(self):
        # INV-DEVBUS-02 INV-DEVBUS-04 FR-BUS-01
        snap = self.p.snapshot()
        self.assertEqual(set(snap), {'schema', 'connection', 'coverage', 'tasks', 'agents', 'events'})
        self.assertEqual(snap['schema'], 1)
        self.assertEqual(snap['coverage']['mode'], 'unknown')
        self.assertEqual(snap['tasks'], [])
        self.assertTrue(self.ingest())
        task = self.p.snapshot()['tasks'][0]
        self.assertEqual(task['delivery'], 'unknown')
        self.assertEqual(task['quality'], 'unreviewed')
        self.assertIsNone(task['submitted_at'])
        self.assertIsNone(task['duration_seconds'])

    def test_submit_and_wrong_subject_never_create_task(self):
        # INV-DEVBUS-01 INV-DEVBUS-02
        self.assertFalse(self.ingest('submit'))
        self.assertFalse(self.p.ingest(wire(mid='m2'), 'devbus.commands.worker1', 2))
        self.assertFalse(self.p.ingest(wire(mid='m3'), 'devbus.events.other', 3))
        snap = self.p.snapshot()
        self.assertEqual(snap['tasks'], [])
        self.assertEqual(snap['events'], [])
        self.assertIn('invalid_event', snap['coverage']['issues'])

    def test_sequence_not_timestamp_and_duplicate_id_controls_state(self):
        # INV-DEVBUS-03 FR-BUS-02
        self.assertTrue(self.ingest('completed', seq=30, mid='done', at=timestamp(NOW-100), payload={'text':'ok'}))
        self.assertTrue(self.ingest('running', seq=20, mid='run', at=timestamp(NOW+100)))
        self.assertTrue(self.ingest('accepted', seq=10, mid='accept'))
        self.assertFalse(self.ingest('running', seq=20, mid='run', at=timestamp(NOW+100)))
        task = self.p.snapshot()['tasks'][0]
        self.assertEqual(task['state'], 'completed')
        self.assertEqual(task['result'], 'ok')
        self.assertEqual([e['sequence'] for e in task['transitions']], [10,20,30])
        self.assertEqual(len(self.p.snapshot()['events']), 3)
        self.assertFalse(self.ingest('failed', seq=40, mid='done'))
        self.assertFalse(self.ingest('running', seq=41, mid='other', source='worker2'))
        self.assertIn('id_conflict', self.p.snapshot()['coverage']['issues'])
        self.assertEqual(self.p.snapshot()['tasks'][0]['state'], 'completed')

    def test_malformed_input_is_rejected_without_dto_data(self):
        # INV-DEVBUS-06
        valid = wire()
        values = [b'{', b'{"x":NaN}', b'{"message_id":"one","message_id":"two"}',
                  b'[' * 2000 + b']' * 2000, b' ' * 131073,
                  json.dumps({'message_id':'missing-fields'}).encode()]
        for raw in values:
            with self.subTest(raw_length=len(raw)):
                self.assertFalse(self.p.ingest(raw, 'devbus.events.worker1', 1))
        for sequence in (True, False, 0, -1, 1.5, '1'):
            with self.subTest(sequence=sequence):
                self.assertFalse(self.p.ingest(valid, 'devbus.events.worker1', sequence))
        self.assertEqual(self.p.snapshot()['tasks'], [])
        self.assertIn('invalid_event', self.p.snapshot()['coverage']['issues'])

    def test_missing_invalid_and_null_event_time_are_unknown(self):
        # INV-DEVBUS-05
        for index, value in enumerate((None, 'bad-time', 123)):
            obj = json.loads(wire(mid='m'+str(index), task='t'+str(index)))
            obj['created_at'] = value
            self.assertTrue(self.p.ingest(json.dumps(obj).encode(), 'devbus.events.worker1', index+1))
        obj = json.loads(wire(mid='missing', task='missing'))
        del obj['created_at']
        self.assertTrue(self.p.ingest(json.dumps(obj).encode(), 'devbus.events.worker1', 4))
        self.assertTrue(all(t['event_at'] is None for t in self.p.snapshot()['tasks']))

    def test_scrubbing_allowlist_errors_and_snapshot_copy(self):
        # INV-DEVBUS-06
        secret = 'synthetic-secret-value'
        self.p = self.api.Projection(clock=lambda:self.now, secrets=(secret,))
        content = secret + ' token=synthetic-token password=synthetic-password api_key=synthetic-key '
        content += 'Bearer synthetic-bearer https://user:synthetic-password@example.invalid/a '
        content += '\n-----BEGIN PRIVATE KEY-----\nsyntheticpem\n-----END PRIVATE KEY-----'
        self.assertTrue(self.ingest('completed', payload={'text':content, 'private_field':'private-content'}))
        self.assertTrue(self.ingest('failed',seq=2,mid='err',task='t2',payload={'reason':'/private/path synthetic-password'}))
        snap = self.p.snapshot()
        encoded = json.dumps(snap)
        for value in (secret,'synthetic-token','synthetic-password','synthetic-key','synthetic-bearer','syntheticpem','private-content','/private/path'):
            self.assertNotIn(value, encoded)
        self.assertEqual(next(t for t in snap['tasks'] if t['task_id']=='t2')['error'], 'unknown_error')
        snap['tasks'].clear()
        snap['coverage']['issues'].append('invented')
        self.assertEqual(len(self.p.snapshot()['tasks']), 2)
        self.assertNotIn('invented', self.p.snapshot()['coverage']['issues'])

    def test_caps_output_transitions_and_ttl_follow_observed_wall_age(self):
        # INV-DEVBUS-04 INV-DEVBUS-06
        self.p = self.api.Projection(limits=self.api.Limits(tasks=2,agents=2,events=2,dedup=2,text=16,transitions=2), clock=lambda:self.now)
        self.p.coverage(1,10,10,1024,replay_complete=True)
        for i in range(1,5):
            self.assertTrue(self.ingest('completed',seq=i,mid='m'+str(i),task='t'+str(i),payload={'text':'x'*100},at=timestamp(NOW-10000)))
        snap=self.p.snapshot()
        self.assertEqual([t['task_id'] for t in snap['tasks']], ['t3','t4'])
        self.assertLessEqual(len(snap['events']),2)
        self.assertTrue(snap['coverage']['truncated'])
        self.assertIn('local_eviction',snap['coverage']['issues'])
        self.assertTrue(all(t['output_truncated'] and len(t['result'])<=16 for t in snap['tasks']))
        self.now += 11
        snap=self.p.snapshot()
        self.assertEqual(snap['tasks'],[])
        self.assertEqual(snap['agents'],[])
        self.assertEqual(snap['events'],[])

    def test_evicted_dedup_does_not_regress_latest_task_state(self):
        # INV-DEVBUS-03
        self.p=self.api.Projection(limits=self.api.Limits(dedup=1),clock=lambda:self.now)
        self.ingest('running',seq=1,mid='old')
        self.ingest('completed',seq=10,mid='new',payload={'text':'done'})
        self.ingest('running',seq=1,mid='old')
        self.assertEqual(self.p.snapshot()['tasks'][0]['state'],'completed')

    def test_filters_exact_and_connection_loss_preserves_labeled_data(self):
        # INV-DEVBUS-04 INV-DEVBUS-08 FR-BUS-03
        self.ingest(task='t1')
        self.ingest(seq=2,mid='m2',task='t10',source='worker2')
        self.assertEqual([t['task_id'] for t in self.p.snapshot(task='t1')['tasks']],['t1'])
        self.assertEqual([t['task_id'] for t in self.p.snapshot(agent='worker2')['tasks']],['t10'])
        self.assertEqual(self.p.snapshot(task='t1',agent='worker2')['tasks'],[])
        self.p.connection('disconnected',reason='raw-private-diagnostic')
        snap=self.p.snapshot()
        self.assertEqual(snap['connection']['state'],'disconnected')
        self.assertNotIn('raw-private-diagnostic',json.dumps(snap))
        self.assertEqual(len(snap['tasks']),2)
        self.p.coverage(1,2,60,1024,replay_complete=True)
        self.assertEqual(self.p.snapshot()['coverage']['mode'],'window')


class HttpRED(unittest.TestCase):
    def setUp(self):
        self.api=feature(self)
        self.p=self.api.Projection(clock=lambda:NOW)
        self.p.ingest(wire(), 'devbus.events.worker1',1)
        self.calls=[]
        original=self.p.snapshot
        def snapshot(*args,**kwargs):
            self.calls.append((args,kwargs))
            return original(*args,**kwargs)
        self.p.snapshot=snapshot

    def client(self,principal='owner',owner_only=True):
        app=FastAPI()
        def auth(request):
            if principal is None:
                return None,JSONResponse({'error':'unauthorized'},status_code=401)
            return {'principal':principal},None
        self.api.install_routes(app,self.p,auth,origin=ORIGIN,owner_only=owner_only)
        return TestClient(app,base_url=ORIGIN)

    def test_owner_get_filters_no_store_no_mutation_routes(self):
        # INV-DEVBUS-07 FR-BUS-01
        c=self.client()
        r=c.get('/api/devbus/overview?task=t1&agent=worker1')
        self.assertEqual(r.status_code,200,r.text)
        self.assertIn('no-store',r.headers.get('cache-control',''))
        self.assertEqual([t['task_id'] for t in r.json()['tasks']],['t1'])
        self.assertEqual(c.get('/api/devbus/overview',headers={'Origin':ORIGIN}).status_code,200)
        self.assertIn(c.post('/api/devbus/overview').status_code,(404,405))

    def test_auth_and_exact_owner_flag_precede_snapshot(self):
        # INV-DEVBUS-07 INV-DEVBUS-06
        for principal,flag,expected in ((None,True,401),('project',True,403),('owner',False,403),('owner',1,403),('owner','true',403)):
            with self.subTest(principal=principal,flag=flag):
                r=self.client(principal,flag).get('/api/devbus/overview')
                self.assertEqual(r.status_code,expected,r.text)
                self.assertIn('no-store',r.headers.get('cache-control',''))
        self.assertEqual(self.calls,[])

    def test_foreign_duplicate_origin_and_invalid_queries_rejected_before_read(self):
        # INV-DEVBUS-07 INV-DEVBUS-06
        c=self.client()
        for headers in ({'Origin':'https://evil.invalid'}, [('Origin',ORIGIN),('Origin',ORIGIN)]):
            r=c.get('/api/devbus/overview',headers=headers)
            self.assertEqual(r.status_code,403,r.text)
        for query in ('unknown=x','task=bad.id','agent='+('a'*81),'task=t1&task=t2','agent='):
            r=c.get('/api/devbus/overview?'+query)
            self.assertEqual(r.status_code,400,r.text)
            self.assertIn('no-store',r.headers.get('cache-control',''))
        self.assertEqual(self.calls,[])


class Message:
    def __init__(self,kind='accepted',sequence=1):
        self.data=wire(kind,mid='m'+str(sequence))
        self.subject='devbus.events.worker1'
        self.sequence=sequence
        self.acks=0
    async def ack(self):
        self.acks+=1


class Transport:
    def __init__(self,batches=()):
        self.batches=list(batches)
        self.closed=0
        self.fetches=0
        self.skips=[]
        self.metadata=dict(first_seq=1,last_seq=10,ttl_seconds=60,max_bytes=1024)
        self.pending_value=0
    async def info(self):
        return dict(self.metadata)
    async def fetch(self):
        self.fetches+=1
        if self.batches:
            return self.batches.pop(0)
        await asyncio.sleep(.002)
        return []
    async def pending(self):
        return self.pending_value
    async def skip_to(self,sequence):
        self.skips.append(sequence)
    async def close(self):
        self.closed+=1


class ObserverRED(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api=feature(self)
        self.p=self.api.Projection(clock=lambda:NOW)
        self.observers=[]
    async def asyncTearDown(self):
        for observer in self.observers:
            await asyncio.wait_for(observer.stop(),1)
    def observer(self,connect):
        o=self.api.Observer(self.p,connect,retry_seconds=.01,operation_timeout=.03)
        self.observers.append(o)
        return o
    async def until(self,predicate):
        async def poll():
            while not predicate():
                await asyncio.sleep(.002)
        await asyncio.wait_for(poll(),1)

    async def test_events_ack_replay_pending_and_idempotent_start_stop(self):
        # INV-DEVBUS-01 INV-DEVBUS-04 INV-DEVBUS-08
        event=Message()
        transport=Transport([[event]])
        calls=[]
        async def connect():
            calls.append('connect')
            return transport
        o=self.observer(connect)
        await o.start()
        await o.start()
        await self.until(lambda:event.acks==1 and self.p.snapshot()['connection']['state']=='live')
        self.assertEqual(calls,['connect'])
        self.assertTrue(self.p.snapshot()['coverage']['replay_complete'])
        await o.stop()
        await o.stop()
        self.assertEqual(transport.closed,1)
        fetches=transport.fetches
        await asyncio.sleep(.04)
        self.assertEqual(fetches,transport.fetches)

    async def test_empty_fetch_does_not_claim_replay_finished(self):
        # INV-DEVBUS-04
        t=Transport()
        t.pending_value=3
        async def connect():return t
        o=self.observer(connect)
        await o.start()
        await self.until(lambda:t.fetches>=3)
        self.assertFalse(self.p.snapshot()['coverage']['replay_complete'])
        self.assertEqual(self.p.snapshot()['connection']['state'],'replaying')
        t.pending_value=0
        await self.until(lambda:self.p.snapshot()['connection']['state']=='live')

    async def test_hung_io_reconnects_after_close_and_stop_is_bounded(self):
        # INV-DEVBUS-06 INV-DEVBUS-08
        class Hung(Transport):
            async def fetch(self):
                self.fetches+=1
                await asyncio.Event().wait()
        first=Hung()
        second=Transport([[Message('completed',2)]])
        calls=[]
        async def connect():
            if calls:
                self.assertEqual(first.closed,1,'old consumer must close before replacement')
            calls.append('connect')
            return first if len(calls)==1 else second
        o=self.observer(connect)
        await o.start()
        await self.until(lambda:len(calls)>=2 and len(self.p.snapshot()['tasks'])==1)
        self.assertEqual(self.p.snapshot()['tasks'][0]['state'],'completed')
        await asyncio.wait_for(o.stop(),.3)
        count=len(calls)
        await asyncio.sleep(.05)
        self.assertEqual(len(calls),count)

    async def test_stop_interrupts_hung_connect_without_retry(self):
        # INV-DEVBUS-06 INV-DEVBUS-08
        entered=asyncio.Event()
        calls=[]
        async def connect():
            calls.append(1)
            entered.set()
            await asyncio.Event().wait()
        o=self.observer(connect)
        await o.start()
        await asyncio.wait_for(entered.wait(),.5)
        await asyncio.wait_for(o.stop(),.3)
        count=len(calls)
        await asyncio.sleep(.05)
        self.assertEqual(len(calls),count)

    async def test_numeric_holes_not_loss_and_retention_gap_and_stream_reset_visible(self):
        # INV-DEVBUS-03 INV-DEVBUS-04 FR-BUS-02
        t=Transport([[Message('accepted',1),Message('completed',10)]])
        async def connect():return t
        o=self.observer(connect)
        await o.start()
        await self.until(lambda:self.p.snapshot()['connection']['state']=='live')
        self.assertNotIn('retention_gap',self.p.snapshot()['coverage']['issues'])
        t.metadata.update(first_seq=12,last_seq=20)
        await asyncio.wait_for(self.wait_issue('retention_gap'),6)
        t.metadata.update(first_seq=1,last_seq=2)
        await asyncio.wait_for(self.wait_issue('stream_reset'),6)
        self.assertEqual(self.p.snapshot()['tasks'],[])

    async def wait_issue(self,code):
        while code not in self.p.snapshot()['coverage']['issues']:
            await asyncio.sleep(.01)

class HeartbeatRED(unittest.TestCase):
    def test_agent_metadata_allowlist_and_freshness_boundaries(self):
        # INV-DEVBUS-05 INV-DEVBUS-06
        api=feature(self)
        now=[NOW]
        p=api.Projection(clock=lambda:now[0])
        payload={'agent_id':'spoofed','capabilities':['one','two'],'executor':'codex','version':'v1','schema_version':1,'private':'synthetic-private'}
        self.assertTrue(p.ingest(wire('registration',payload=payload),'devbus.events.worker1',1))
        self.assertEqual(p.snapshot()['tasks'],[])
        agent=p.snapshot()['agents'][0]
        self.assertEqual(agent['agent'],'worker1')
        self.assertTrue(agent['registered'])
        self.assertEqual(agent['capabilities'],['one','two'])
        self.assertNotIn('synthetic-private',json.dumps(p.snapshot()))
        for seq,at,status in ((2,timestamp(),'fresh'),(3,timestamp(NOW-45),'stale'),(4,timestamp(NOW+6),'unknown'),(5,'bad','unknown')):
            self.assertTrue(p.ingest(wire('heartbeat',mid='h'+str(seq),at=at,payload={'agent_id':'worker1'}),'devbus.events.worker1',seq))
            self.assertEqual(p.snapshot()['agents'][0]['heartbeat_status'],status)
        p.connection('disconnected')
        self.assertEqual(len(p.snapshot()['agents']),1)


class NatsConfigurationRED(unittest.TestCase):
    def setUp(self):
        self.api=feature(self,'_control_web_devbus_nats')

    def test_disabled_default_and_local_or_tls_only(self):
        # INV-DEVBUS-01 INV-DEVBUS-06
        config=self.api.NatsConfig.from_env({})
        self.assertFalse(config.enabled)
        for url in ('nats://localhost:4222','nats://127.0.0.1:4222','nats://[::1]:4222','tls://broker.invalid:4222'):
            with self.subTest(url=url):
                self.api.NatsConfig.from_env({'CONTROL_DEVBUS_ENABLED':'1','DEVBUS_NATS_URL':url})

    def test_bad_config_and_credential_values_never_exposed(self):
        # INV-DEVBUS-06 INV-DEVBUS-08
        base={'CONTROL_DEVBUS_ENABLED':'1','DEVBUS_NATS_URL':'nats://localhost:4222'}
        for extra in ({'CONTROL_DEVBUS_ENABLED':'true'}, {'CONTROL_DEVBUS_ENABLED':'2'},
                      {'DEVBUS_NATS_URL':'nats://remote.invalid:4222'},
                      {'DEVBUS_NATS_URL':'nats://user:synthetic-password@localhost:4222'},
                      {'DEVBUS_NATS_TOKEN':'synthetic-token','DEVBUS_NATS_CREDS':'/synthetic/private.creds'},
                      {'CONTROL_DEVBUS_STREAM':'BAD.*'}):
            with self.subTest(keys=list(extra)):
                try:self.api.NatsConfig.from_env(dict(base,**extra))
                except ValueError as exc:
                    for secret in ('synthetic-password','synthetic-token','/synthetic/private.creds'):
                        self.assertNotIn(secret,str(exc))
                else:self.fail('invalid configuration accepted')
        config=self.api.NatsConfig.from_env(dict(base,DEVBUS_NATS_TOKEN='synthetic-token'))
        self.assertNotIn('synthetic-token',repr(config))


if __name__=='__main__':
    unittest.main()
