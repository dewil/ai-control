"""Frozen LIVE public fixtures; actual app/runtime imported, never source-read."""
import asyncio
from copy import deepcopy
import http.client
import importlib
import inspect
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

ROOT = Path(os.environ.get('CONTROL_LIVE_SSE_QA_REPO', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / 'bin'))
SID = '11111111-1111-4111-8111-111111111111'
OTHER = '44444444-4444-4444-8444-444444444444'
THIRD = '55555555-5555-4555-8555-555555555555'
TURN = '33333333-3333-4333-8333-333333333333'
PASSWORD = 'synthetic-live-sse-password'
SECRET = 'JBSWY3DPEHPK3PXP'
EPOCH = 'a' * 32


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def settings(model='producer-A', age=0):
    return dict(schema=1, scope='configured_or_persisted', source='thread_read', model=model,
                effort='high', age_ms=age, expires_in_ms=15000-age)


def history(text='LIVE original synthetic text', item='item-A', model='producer-A'):
    return dict(turns=[dict(id=TURN, status='completed', items=[dict(id=item, role='assistant', text=text,
        truncated=False, timestamp=1770000000, time_precision='item')])], next_cursor=None,
        truncated=False, recent_sends=[], session_settings=settings(model))


def snapshot(revision=1, observation=None, epoch=EPOCH, value=None):
    return dict(schema=1, project='demo', sid=SID, epoch=epoch, revision=revision,
        observation=observation or revision, source='owner_history_poll', observed_at=1770000000000,
        history=deepcopy(value if value is not None else history()))


def frame(event, data, identifier=None):
    return (('id: '+identifier+'\n' if identifier else '')+'event: '+event+'\ndata: ').encode()+encoded(data)+b'\n\n'


class Backend:
    def __init__(self):
        self.value = history()
        self.outcome = None
        self.scope = '1' * 64
        self.gate = threading.Event(); self.gate.set()
        self.condition = threading.Condition()
        self.calls = []
        self.active = self.maximum = 0
        self.delay = 0

    def snapshot(self): return {'tasks': []}
    def answer(self, *args): return {'error': 'unavailable'}
    def verdict(self, *args): return {'error': 'unavailable'}
    def session_projects(self): return {'projects': [{'name': 'demo'}]}
    def session_project_summary(self): return {'projects': [dict(name='demo', session_count=3,
        last_activity=1770000000, summary_state='fresh', as_of=1770000000)]}
    def session_list(self, project, page): return {'rows': [dict(sid=sid, title=title, status='idle')
        for sid, title in ((SID, 'LIVE synthetic A'), (OTHER, 'LIVE synthetic B'), (THIRD, 'LIVE synthetic C'))], 'has_more': False}
    def session_history(self, project, sid, cursor): return deepcopy(self.value)
    def session_models(self, project, sid): return dict(schema=1, vendor='codex', context_kind='legacy_unbound',
        selection_support='available', catalog_id='a'*64, expires_in_ms=60000,
        rows=[dict(id='model-alpha', label='Model Alpha', efforts=['high'])])
    def session_send(self, project, sid, message_id, text, selection=None):
        return {'status': 'delivery_unknown', 'message_id': message_id, 'turn_id': None}
    def session_send_status(self, project, sid, message_id):
        return {'status': 'delivery_unknown', 'message_id': message_id, 'turn_id': None}

    def session_live_snapshot(self, project, sid):
        with self.condition:
            self.active += 1; self.maximum = max(self.maximum, self.active)
            row = dict(project=project, sid=sid, start=time.monotonic(), finish=None)
            self.calls.append(row); self.condition.notify_all()
        try:
            if not self.gate.wait(12): return {'error': 'unavailable'}
            if self.delay: time.sleep(self.delay)
            if isinstance(self.outcome, Exception): raise self.outcome
            if self.outcome is not None: return deepcopy(self.outcome)
            return {'schema': 1, 'scope_id': self.scope if sid == SID else ('2' if sid == OTHER else '3')*64,
                    'history': deepcopy(self.value)}
        finally:
            with self.condition:
                self.active -= 1; row['finish'] = time.monotonic(); self.condition.notify_all()

    def wait_calls(self, count, timeout=3):
        with self.condition: return self.condition.wait_for(lambda: len(self.calls) >= count, timeout)


class Transport:
    """Real native EventSource fixture at documented routes; actual app elsewhere."""
    def __init__(self, app):
        self.app = app; self.frames = []; self.requests = []
        self.close = False; self.status = 200; self.json_status = 200
        self.json_value = snapshot(); self.json_error = 'unavailable'; self.streams = self.closed = 0
        self.lock = threading.Lock()

    def emit(self, value, event='snapshot'):
        identifier = value['epoch']+':'+str(value['revision']) if event == 'snapshot' else None
        with self.lock: self.frames.append(frame(event, value, identifier))

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        path = scope['path']
        with self.lock: self.requests.append((path, time.monotonic(), scope.get('query_string', b'')))
        if path == '/api/session-live-snapshot':
            await send({'type':'http.response.start', 'status':self.json_status,
                        'headers':[(b'content-type',b'application/json'),(b'cache-control',b'no-store')]})
            await send({'type':'http.response.body','body':encoded(self.json_value if self.json_status == 200 else {'error':self.json_error})})
            return
        if path != '/api/session-events': return await self.app(scope, receive, send)
        with self.lock: self.streams += 1
        await send({'type':'http.response.start','status':self.status,
                    'headers':[(b'content-type',b'text/event-stream'),(b'cache-control',b'no-store')]})
        if self.status != 200:
            await send({'type':'http.response.body','body':b'{"error":"unavailable"}'}); return
        index = 0
        try:
            while True:
                with self.lock: pending = self.frames[index:]; index = len(self.frames)
                for body in pending: await send({'type':'http.response.body','body':body,'more_body':True})
                if self.close: break
                try:
                    message = await asyncio.wait_for(receive(), .02)
                    if message['type'] == 'http.disconnect': return
                except asyncio.TimeoutError: pass
            await send({'type':'http.response.body','body':b''})
        finally:
            with self.lock: self.closed += 1


class Fixture:
    def __init__(self, owner_only=True, session_store=False, transport=False, configured=True, state_parent=None):
        self.temp = tempfile.TemporaryDirectory(prefix='live-sse-blind-', dir='/var/tmp')
        self.directory = Path(state_parent or self.temp.name); self.directory.chmod(0o700)
        replay = self.directory / 'totp.json'
        if not replay.exists(): replay.write_text('{"last_step":-1}'); replay.chmod(0o600)
        self.now = 1800000000
        self.web = importlib.import_module('_control_web')
        self.backend = Backend(); self.sessions = {} if session_store else None
        self.listener = socket.socket(); self.listener.bind(('127.0.0.1',0)); self.listener.listen(128)
        self.port = self.listener.getsockname()[1]; self.origin = 'http://127.0.0.1:'+str(self.port)
        config = dict(origin=self.origin, username='dwl', password_hash=self.web.hash_password(PASSWORD),
            totp_secret=SECRET, session_ttl=3600, secure_cookie=False,
            android_auth_db=str(self.directory / 'devices.sqlite'))
        if configured: config['totp_state_path'] = str(replay)
        kwargs = dict(owner_only=owner_only)
        self.session_store_supported = 'session_store' in inspect.signature(self.web.create_app).parameters
        if session_store and self.session_store_supported: kwargs['session_store'] = self.sessions
        self.app = self.web.create_app(config, self.backend, clock=lambda:self.now, **kwargs)
        self.transport = Transport(self.app) if transport else None
        import uvicorn
        self.server = uvicorn.Server(uvicorn.Config(self.transport or self.app, log_level='error', access_log=False))
        self.loop = None
        def run():
            self.loop = asyncio.new_event_loop(); asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.server.serve(sockets=[self.listener])); self.loop.close()
        self.worker = threading.Thread(target=run, daemon=True); self.worker.start()
        deadline = time.monotonic()+8
        while not self.server.started:
            if not self.worker.is_alive() or time.monotonic()>deadline:
                self.server.should_exit = True; self.worker.join(1); self.listener.close(); self.temp.cleanup()
                raise RuntimeError('Actual app lifespan failed to start')
            time.sleep(.01)
        self.cookie = None

    def request(self, path, cookie=True, headers=None, method='GET', body=None, timeout=9):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        connection.putrequest(method, path)
        for key, value in headers or []: connection.putheader(key,value)
        if cookie and self.cookie: connection.putheader('Cookie', self.cookie)
        if body is not None:
            payload = encoded(body); connection.putheader('Content-Type','application/json')
            connection.putheader('Content-Length',str(len(payload)))
        connection.endheaders(payload if body is not None else None)
        response = connection.getresponse()
        return connection, response

    def login(self, app=False):
        self.now += 30
        connection, response = self.request('/api/app/login' if app else '/api/login', cookie=False,
            method='POST', headers=[('Origin',self.origin)], body=dict(username='dwl', password=PASSWORD,
            totp=self.web.totp_code(SECRET,self.now)))
        status = response.status; value = json.loads(response.read())
        if status != 200: raise RuntimeError('Synthetic actual owner login failed: status '+str(status))
        self.cookie = response.getheader('set-cookie').split(';',1)[0]
        connection.close(); return value

    def stop(self):
        self.backend.gate.set()
        if self.transport: self.transport.close = True
        self.server.should_exit = True
        self.worker.join(8)
        alive = self.worker.is_alive()
        self.temp.cleanup()
        if alive: raise RuntimeError('Actual app/server did not finish bounded cleanup')


def event(response):
    fields = {}
    while True:
        line = response.readline()
        if not line: return None
        if line == b'\n':
            if 'event' in fields:
                fields['data'] = json.loads(fields['data']); return fields
            fields = {}; continue
        if line.startswith(b':'): continue
        key, value = line.decode('utf-8').rstrip('\r\n').split(':',1)
        fields[key] = value.lstrip(' ')
