"""Bounded owner polling and SSE. No IO or process ownership before lifespan."""
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import time

from fastapi.responses import Response

SAFE_INTEGER = 2**53 - 1
HISTORY_LIMIT = 96 * 1024
WIRE_LIMIT = 100 * 1024


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def history_valid(value):
    from _control_web_broker import session_settings_result, valid_qid
    if type(value) is not dict:
        return False
    common = {'recent_sends', 'session_settings', 'needs_native_attention'}
    if 'history_state' in value:
        if set(value) - common != {'history_state', 'reason'} or value['history_state'] != 'unavailable' or value['reason'] != 'unavailable':
            return False
    else:
        if (set(value) - common != {'turns', 'next_cursor', 'truncated'}
                or type(value['turns']) is not list or len(value['turns']) > 8
                or type(value['truncated']) is not bool
                or value['next_cursor'] is not None and (type(value['next_cursor']) is not str or not 0 < len(value['next_cursor']) <= 4096)):
            return False
        count = 0
        for turn in value['turns']:
            if (type(turn) is not dict or set(turn) != {'id', 'status', 'items'}
                    or type(turn['id']) is not str or not 0 < len(turn['id']) <= 500
                    or type(turn['status']) is not str or not 0 < len(turn['status']) <= 500
                    or type(turn['items']) is not list):
                return False
            for item in turn['items']:
                count += 1
                fields = {'id', 'role', 'text', 'truncated', 'timestamp', 'time_precision'}
                if (type(item) is not dict or set(item) not in (fields, fields | {'client_id'})
                        or type(item['id']) is not str or not 0 < len(item['id']) <= 500
                        or item['role'] not in ('user', 'assistant') or type(item['text']) is not str
                        or len(item['text']) > 8000 or type(item['truncated']) is not bool
                        or item['timestamp'] is not None and (type(item['timestamp']) is not int or not 0 <= item['timestamp'] <= 253402300799)
                        or item['time_precision'] not in ('item', 'turn', 'unknown')
                        or 'client_id' in item and (item['role'] != 'user' or not valid_qid(item['client_id']))):
                    return False
        if count > 24:
            return False
    if 'needs_native_attention' in value and value['needs_native_attention'] is not True:
        return False
    if 'session_settings' in value and session_settings_result(value['session_settings']) is None:
        return False
    rows = value.get('recent_sends')
    if type(rows) is not list or len(rows) > 8:
        return False
    for row in rows:
        if (type(row) is not dict or set(row) != {'status', 'message_id', 'turn_id'}
                or not valid_qid(row['message_id']) or row['status'] not in ('accepted', 'delivery_unknown', 'rejected')
                or (row['status'] == 'accepted' and (type(row['turn_id']) is not str or not 0 < len(row['turn_id']) <= 500))
                or row['status'] != 'accepted' and row['turn_id'] is not None):
            return False
    try:
        return len(encoded(value)) <= HISTORY_LIMIT
    except (ValueError, UnicodeError, TypeError, RecursionError):
        return False


def owner_result(value, private_errors=False):
    failure = {'error': 'unavailable'}
    if private_errors and type(value) is dict and set(value) == {'error'} and value['error'] in ('busy', 'unsupported', 'unavailable'):
        return value.copy()
    if (type(value) is not dict or set(value) != {'schema', 'scope_id', 'history'}
            or type(value['schema']) is not int or value['schema'] != 1
            or type(value['scope_id']) is not str or not re.fullmatch('[0-9a-f]{64}', value['scope_id'])
            or not history_valid(value['history'])):
        return failure
    return deepcopy(value)


def canonical_hash(history):
    value = deepcopy(history)
    if 'session_settings' in value:
        value['session_settings'].pop('age_ms')
        value['session_settings'].pop('expires_in_ms')
    return hashlib.sha256(encoded(value)).digest()


def event_frame(event, value, identifier=None):
    prefix = ('id: ' + identifier + '\n') if identifier else ''
    wire = (prefix + 'event: ' + event + '\ndata: ').encode() + encoded(value) + b'\n\n'
    if len(wire) > WIRE_LIMIT:
        raise ValueError('invalid live envelope')
    return wire


class Entry:
    def __init__(self, key, scope_id):
        self.key, self.scope_id = key, scope_id
        self.epoch = secrets.token_hex(16)
        self.revision = self.observation = 0
        self.digest = None
        self.value = None
        self.subscribers = set()
        self.last_success = self.last_used = time.monotonic()
        self.due = float('inf')

    def observe(self, history):
        digest = canonical_hash(history)
        changed = digest != self.digest
        epoch, revision, observation = self.epoch, self.revision, self.observation
        if self.observation == SAFE_INTEGER or changed and self.revision == SAFE_INTEGER:
            epoch = secrets.token_hex(16)
            revision = observation = 0
            changed = True
        observation += 1
        if changed:
            revision += 1
        value = dict(schema=1, project=self.key[0], sid=self.key[1], epoch=epoch,
                          revision=revision, observation=observation,
                          source='owner_history_poll', observed_at=int(time.time()*1000), history=history)
        wire = encoded(value)
        if len(wire) > WIRE_LIMIT or len(wire) - len(encoded(history)) > 4096:
            raise ValueError('invalid live envelope')
        event_frame('snapshot', value, epoch + ':' + str(revision))
        self.epoch, self.revision, self.observation = epoch, revision, observation
        self.digest, self.value = digest, value
        self.last_success = self.last_used = time.monotonic()
        return changed


class Subscriber:
    def __init__(self, entry, check=lambda:None):
        self.entry = entry
        self.check = check
        self.queue = deque()
        self.overflow = False
        self.recovering = False
        self.closed = False
        self.changed = asyncio.Event()

    def reset(self, reason):
        e = self.entry
        return event_frame('reset', dict(schema=1, project=e.key[0], sid=e.key[1], epoch=e.epoch, reason=reason))

    def snapshot(self):
        e = self.entry
        return event_frame('snapshot', e.value, e.epoch + ':' + str(e.revision))

    def publish(self):
        if self.closed:
            return
        if self.overflow:
            # Recovery uses the next fresh observation, never the overflowed cache.
            self.queue.clear()
            self.queue.extend((self.reset('overflow'), self.snapshot()))
            self.overflow = False
            self.recovering = True
        elif len(self.queue) >= 2:
            if self.recovering:
                self.fail()
                return
            self.queue.clear()
            self.overflow = True
        else:
            self.queue.append(self.snapshot())
        self.changed.set()

    def fail(self):
        if self.closed:
            return
        self.queue.clear()
        e = self.entry
        self.queue.append(event_frame('unavailable', dict(schema=1, project=e.key[0], sid=e.key[1], error='unavailable')))
        self.closed = True
        self.changed.set()


class Manager:
    def __init__(self, backend, replay_path):
        self.backend, self.replay_path = backend, replay_path
        self.entries = {}
        self.pending = []
        self.budgets = {}
        self.last_start = {}
        self.backoff = {}
        self.read_task = self.scheduler = None
        self.executor = None
        self.lock_fd = None
        self.running = False
        self.round_key = None

    async def start(self):
        path = self.replay_path.parent / 'live-manager.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise ValueError('invalid live manager ownership')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(fd)
            raise
        self.lock_fd = fd
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='control-live-owner')
        self.running = True
        self.scheduler = asyncio.create_task(self.schedule())

    async def stop(self):
        self.running = False
        if self.scheduler:
            await self.scheduler
        for entry in self.entries.values():
            self.fail(entry)
        for pending in self.pending:
            if not pending['future'].done():
                pending['future'].set_result({'error': 'unavailable'})
        if self.read_task:
            try:
                await asyncio.wait_for(asyncio.shield(self.read_task), 7)
            except asyncio.TimeoutError:
                raise RuntimeError('live owner did not stop') from None
        if self.executor:
            self.executor.shutdown(wait=True)
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    def reserve(self, identity, key=None):
        active = [e for e in self.entries.values() if e.subscribers or self.read_task and getattr(self.read_task, 'live_key', None) == e.key]
        if sum(self.budgets.values()) >= 8 or self.budgets.get(identity, 0) >= 2 or key is not None and key not in self.entries and len(active) >= 2:
            return False
        self.budgets[identity] = self.budgets.get(identity, 0) + 1
        return True

    def release(self, identity):
        count = self.budgets.get(identity, 0)
        if count <= 1:
            self.budgets.pop(identity, None)
        else:
            self.budgets[identity] = count - 1

    async def admit(self, key, check, stream=False):
        now = time.monotonic()
        future = asyncio.get_running_loop().create_future()
        row = dict(key=key, start=now, deadline=now+6, future=future, check=check, stream=stream)
        self.pending.append(row)
        try:
            result = await future
            if isinstance(result, Subscriber):
                result.entry.subscribers.add(result)
                result.entry.due = time.monotonic()+1.05
            return result
        finally:
            if row in self.pending:
                self.pending.remove(row)
            future.cancel()

    @staticmethod
    def checked(check):
        try:
            return check()
        except Exception:
            return {'error': 'unavailable'}

    def fail(self, entry):
        for subscriber in list(entry.subscribers):
            subscriber.fail()
        entry.due = float('inf')

    def detach(self, subscriber):
        entry = subscriber.entry
        entry.subscribers.discard(subscriber)
        entry.last_used = time.monotonic()
        if not entry.subscribers:
            entry.due = float('inf')

    async def schedule(self):
        while self.running:
            now = time.monotonic()
            for row in list(self.pending):
                failure = self.checked(row['check'])
                if row['future'].done() or now >= row['deadline'] or failure is not None:
                    if not row['future'].done():
                        row['future'].set_result(failure or {'error': 'unavailable'})
                    self.pending.remove(row)
            for key, entry in list(self.entries.items()):
                if entry.subscribers and now-entry.last_success >= 6:
                    self.fail(entry)
                if not entry.subscribers and not any(p['key'] == key for p in self.pending) and now-entry.last_used >= 10:
                    self.entries.pop(key)
                    self.last_start.pop(key, None)
                    self.backoff.pop(key, None)
            if self.read_task is None:
                keys = list(self.entries)
                keys += [p['key'] for p in self.pending if p['key'] not in keys]
                if self.round_key in keys:
                    index = keys.index(self.round_key)+1
                    keys = keys[index:] + keys[:index]
                for key in keys:
                    entry = self.entries.get(key)
                    waiting = any(p['key'] == key for p in self.pending)
                    active = bool(entry and any(not s.closed for s in entry.subscribers))
                    due = entry.due if active else self.last_start.get(key, -100)+1
                    if (waiting or active) and now >= max(due, self.last_start.get(key, -100)+1):
                        self.round_key = key
                        self.last_start[key] = now
                        cut = [p for p in self.pending if p['key'] == key]
                        self.read_task = asyncio.create_task(self.read(key, cut))
                        self.read_task.live_key = key
                        break
            await asyncio.sleep(.05)

    async def read(self, key, cut):
        try:
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(self.executor, self.backend.session_live_snapshot, *key)
                result = owner_result(result, private_errors=True)
            except Exception:
                result = {'error': 'unavailable'}
            entry = self.entries.get(key)
            candidate = None
            changed = False
            if 'error' not in result:
                candidate = Entry(key, result['scope_id'])
                if entry and entry.scope_id == result['scope_id']:
                    for name in ('epoch', 'revision', 'observation', 'digest'):
                        setattr(candidate, name, getattr(entry, name))
                changed = candidate.observe(result['history'])
            if entry:
                for subscriber in list(entry.subscribers):
                    if self.checked(subscriber.check) is not None:
                        subscriber.fail()
            # Candidate validation precedes the final authority/deadline cut;
            # no await separates this cut from state commit and delivery.
            eligible = []
            for row in cut:
                if row not in self.pending or row['future'].done():
                    continue
                failure = self.checked(row['check'])
                if failure is not None or time.monotonic() >= row['deadline']:
                    row['future'].set_result(failure if failure is not None else {'error': 'unavailable'})
                    self.pending.remove(row)
                else:
                    eligible.append(row)
            active = bool(entry and any(not s.closed for s in entry.subscribers))
            if not eligible and not active:
                return
            if 'error' in result:
                if entry:
                    self.fail(entry)
                n = min(self.backoff.get(key, 0)+1, 5)
                self.backoff[key] = n
                if entry:
                    entry.due = time.monotonic() + (1, 2, 5, 10, 30)[n-1]
            elif self.running:
                self.backoff.pop(key, None)
                if entry is None or entry.scope_id != result['scope_id']:
                    if entry is None and len(self.entries) == 2:
                        idle = [e for e in self.entries.values() if not e.subscribers]
                        if not idle:
                            result = {'error': 'capacity'}
                        else:
                            victim = min(idle, key=lambda e:e.last_used)
                            self.entries.pop(victim.key)
                            self.last_start.pop(victim.key, None)
                            self.backoff.pop(victim.key, None)
                    if 'error' not in result:
                        if entry:
                            self.fail(entry)
                        entry = candidate
                        self.entries[key] = entry
                        changed = True
                else:
                    for name in ('epoch', 'revision', 'observation', 'digest', 'value', 'last_success', 'last_used'):
                        setattr(entry, name, getattr(candidate, name))
                if 'error' not in result:
                    for subscriber in list(entry.subscribers):
                        if not subscriber.closed and (changed or subscriber.overflow):
                            subscriber.publish()
                    entry.due = time.monotonic()+1.05 if entry.subscribers else float('inf')
            for row in eligible:
                if row not in self.pending or row['future'].done():
                    continue
                if 'error' in result:
                    row['future'].set_result(result)
                elif row['stream']:
                    subscriber = Subscriber(entry, row['check'])
                    subscriber.queue.append(subscriber.snapshot())
                    row['future'].set_result(subscriber)
                else:
                    row['future'].set_result(entry.value)
                self.pending.remove(row)
        except Exception:
            if key in self.entries:
                self.fail(self.entries[key])
            for row in cut:
                if not row['future'].done():
                    row['future'].set_result({'error': 'unavailable'})
        finally:
            # Completed unknown probes retain no history or unbounded key state.
            if key not in self.entries and not any(p['key'] == key for p in self.pending):
                self.last_start.pop(key, None)
                self.backoff.pop(key, None)
            self.read_task = None


class SSEWriteDeadline:
    """Deadline the actual socket send, outside Starlette's middleware buffering."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] != '/api/session-events':
            return await self.app(scope, receive, send)
        async def bounded(message):
            await asyncio.wait_for(send(message), 10)
        try:
            await self.app(scope, receive, bounded)
        except (OSError, asyncio.TimeoutError):
            return


class SSEResponse(Response):
    media_type = 'text/event-stream'

    def __init__(self, manager, subscriber, identity, check, last_id=None):
        self.manager, self.subscriber, self.identity, self.check = manager, subscriber, identity, check
        super().__init__(content=None, headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        self.raw_headers = [(k,v) for k,v in self.raw_headers if k != b'content-length']
        if last_id:
            epoch, revision = last_id.split(':')
            entry = subscriber.entry
            reason = 'epoch_changed' if epoch != entry.epoch else 'reconnect' if int(revision)>entry.revision else None
            if reason:
                subscriber.queue.appendleft(subscriber.reset(reason))

    async def __call__(self, scope, receive, send):
        subscriber = self.subscriber
        async def disconnected():
            while True:
                if (await receive())['type'] == 'http.disconnect':
                    return
        watcher = asyncio.create_task(disconnected())
        try:
            await send({'type':'http.response.start', 'status':200, 'headers':self.raw_headers})
            heartbeat = time.monotonic()+15
            while not watcher.done():
                if self.check() is not None:
                    subscriber.queue.clear()
                    break
                if subscriber.queue:
                    wire = subscriber.queue.popleft()
                    await asyncio.wait_for(send({'type':'http.response.body', 'body':wire, 'more_body':True}), 10)
                    if not subscriber.queue:
                        subscriber.recovering = False
                    if subscriber.closed and not subscriber.queue:
                        break
                elif time.monotonic() >= heartbeat:
                    await asyncio.wait_for(send({'type':'http.response.body', 'body':b': heartbeat\n\n', 'more_body':True}), 10)
                    heartbeat = time.monotonic()+15
                else:
                    subscriber.changed.clear()
                    try:
                        await asyncio.wait_for(subscriber.changed.wait(), .25)
                    except asyncio.TimeoutError:
                        pass
            await send({'type':'http.response.body', 'body':b'', 'more_body':False})
        finally:
            watcher.cancel()
            self.manager.detach(subscriber)
            self.manager.release(self.identity)
