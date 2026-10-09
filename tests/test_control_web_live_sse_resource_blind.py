"""Actual ASGI send backpressure/cleanup and factory lifecycle, no private seams."""
import asyncio
import importlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import live_sse_blind_support as s

class LiveASGIResourceBlind(unittest.TestCase):
    def setUp(self):
        self.fixture=s.Fixture();self.addCleanup(self.fixture.stop);self.fixture.login()
        connection,response=self.fixture.request('/api/session-live-snapshot?project=demo&sid='+s.SID)
        try:self.assertEqual(response.status,200,'Actual LIVE admission route required before ASGI resource proof');response.read()
        finally:connection.close()

    def begin(self,broken=False):
        self.started=threading.Event();self.stalled=threading.Event();self.release=threading.Event()
        self.disconnect=threading.Event();self.sent=[];self.body_count=0
        async def receive():
            if not getattr(receive,'initial',False):
                receive.initial=True;return {'type':'http.request','body':b'','more_body':False}
            while not self.disconnect.is_set():await asyncio.sleep(.02)
            return {'type':'http.disconnect'}
        async def send(message):
            if message['type']=='http.response.start':self.sent.append(dict(message));self.started.set();return
            if message.get('body'):
                self.body_count+=1
                if self.body_count==1:
                    self.stalled.set()
                    if broken:raise OSError('synthetic observed broken write')
                    while not self.release.is_set():await asyncio.sleep(.02)
                self.sent.append(dict(message))
        scope=dict(type='http',asgi={'version':'3.0','spec_version':'2.3'},http_version='1.1',method='GET',
            scheme='http',path='/api/session-events',raw_path=b'/api/session-events',
            query_string=('project=demo&sid='+s.SID).encode(),root_path='',server=('127.0.0.1',self.fixture.port),
            client=('127.0.0.1',34567),headers=[(b'host',('127.0.0.1:'+str(self.fixture.port)).encode()),
                (b'accept',b'text/event-stream'),(b'cookie',self.fixture.cookie.encode())])
        self.task=asyncio.run_coroutine_threadsafe(self.fixture.app(scope,receive,send),self.fixture.loop)
        self.addCleanup(self.finish)
        self.assertTrue(self.started.wait(3));self.assertEqual(self.sent[0]['status'],200)
        self.assertTrue(self.stalled.wait(3))

    def finish(self):
        self.release.set();self.disconnect.set()
        try:self.task.result(11)
        except (OSError,asyncio.CancelledError):pass
        except Exception:
            if not self.task.done():self.task.cancel()
            raise

    def decoded_events(self):
        raw=b''.join(message.get('body',b'') for message in self.sent)
        events=[]
        for chunk in raw.split(b'\n\n'):
            fields={}
            for line in chunk.splitlines():
                if line.startswith((b'event:',b'data:',b'id:')):
                    key,value=line.split(b':',1);fields[key.decode()]=value.strip().decode()
            if 'event' in fields:
                fields['data']=json.loads(fields['data']);events.append(fields)
        return events

    def test_stalling_send_overflow_reset_then_fresh_snapshot(self):
        self.begin();backend=self.fixture.backend
        for index in range(3):
            previous=len(backend.calls);backend.value=s.history('Synthetic queue update '+str(index))
            self.assertTrue(backend.wait_calls(previous+1,2.5));time.sleep(.12)
        self.release.set();deadline=time.monotonic()+4
        while not any(e['event']=='reset' for e in self.decoded_events()) and time.monotonic()<deadline:time.sleep(.02)
        events=self.decoded_events();reset=next((i for i,e in enumerate(events) if e['event']=='reset'),None)
        self.assertIsNotNone(reset,'Actual bounded queue must recover overflow explicitly')
        self.assertEqual(events[reset]['data']['reason'],'overflow');self.assertNotIn('id',events[reset])
        deadline=time.monotonic()+3
        while len(self.decoded_events())<=reset+1 and time.monotonic()<deadline:time.sleep(.02)
        events=self.decoded_events();self.assertEqual(events[reset+1]['event'],'snapshot')
        self.assertEqual(events[reset+1]['data']['history'],backend.value)
        self.assertEqual(backend.maximum,1)

    def test_observed_broken_write_slot_released_within25s(self):
        started=time.monotonic();self.begin(broken=True)
        try:self.task.result(25)
        except OSError:pass
        self.assertLess(time.monotonic()-started,25.5)
        connection,response=self.fixture.request('/api/session-live-snapshot?project=demo&sid='+s.SID)
        try:self.assertEqual(response.status,200);response.read()
        finally:connection.close()

    def test_write_deadline10s_finishes_even_while_send_stalled(self):
        self.begin();started=time.monotonic()
        try:self.task.result(11.5)
        except (asyncio.TimeoutError,OSError):
            # A deadline must cancel the stalled coroutine rather than require
            # fixture release. A still-live task is a meaningful resource failure.
            self.assertTrue(self.task.done(),'Actual ASGI writer remains live past10s write deadline')
        self.assertLess(time.monotonic()-started,11.5)

class LiveFactoryLifecycleBlind(unittest.TestCase):
    def test_manager_lock_exists_only_with_actual_lifespan_and_prevents_second_app(self):
        first=s.Fixture();self.addCleanup(first.stop)
        self.assertTrue((first.directory/'live-manager.lock').is_file(),'Accepted private state lock must be acquired during actual lifespan')
        with self.assertRaisesRegex(RuntimeError,'Actual app lifespan failed to start'):
            second=s.Fixture(state_parent=first.directory)
            self.addCleanup(second.stop)

    def test_create_app_does_not_acquire_process_lock_before_lifespan(self):
        web=importlib.import_module('_control_web')
        with tempfile.TemporaryDirectory(prefix='live-lifecycle-blind-',dir='/var/tmp') as temporary:
            directory=Path(temporary);directory.chmod(0o700);replay=directory/'totp.json'
            replay.write_text('{"last_step":-1}');replay.chmod(0o600)
            app=web.create_app(dict(origin='https://synthetic-live.example.test',username='dwl',
                password_hash=web.hash_password(s.PASSWORD),totp_secret=s.SECRET,session_ttl=3600,
                secure_cookie=True,totp_state_path=str(replay)),s.Backend(),clock=lambda:1800000000)
            self.assertIsNotNone(app);self.assertFalse((directory/'live-manager.lock').exists())
