"""Bounded, events-only retained-window view of the development bus."""
import asyncio
from collections import OrderedDict
import copy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import inspect
import json
import math
import re
import time

_ID = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
_STATES = {'accepted', 'running', 'completed', 'failed', 'needs_attention'}
_ISSUES = {'local_eviction', 'invalid_event', 'id_conflict', 'retention_gap', 'stream_reset', 'replay_incomplete'}
_REASONS = {'disabled', 'unavailable', 'invalid_config', 'dependency_unavailable', 'stream_policy', 'connection_lost'}


def valid_id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


@dataclass(frozen=True)
class Limits:
    tasks: int = 256
    agents: int = 128
    events: int = 512
    dedup: int = 4096
    text: int = 4096
    transitions: int = 32
    stale_seconds: float = 45

    def __post_init__(self):
        for name in ('tasks', 'agents', 'events', 'dedup', 'text', 'transitions'):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError('invalid limits')
        if not math.isfinite(self.stale_seconds) or self.stale_seconds <= 0:
            raise ValueError('invalid limits')


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('invalid event')
        result[key] = value
    return result


def _timestamp(value):
    if type(value) is not str or len(value) > 100:
        return None, None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return None, None
        seconds = parsed.timestamp()
        return (value, seconds) if math.isfinite(seconds) else (None, None)
    except (ValueError, OverflowError, OSError):
        return None, None


class Projection:
    def __init__(self, limits=Limits(), clock=time.time, secrets=()):
        self.limits, self.clock = limits, clock
        self._secrets = tuple(s for s in secrets if type(s) is str and s)
        self._tasks, self._agents, self._events, self._ids = (OrderedDict() for _ in range(4))
        self._issues = set()
        self._purged_at = None
        self._connection = {'state': 'disabled', 'reason': None}
        self._coverage = dict(mode='unknown', first_seq=None, last_seq=None, ttl_seconds=None,
                              max_bytes=None, replay_complete=False, truncated=False, issues=[])

    def issue(self, code):
        if code in _ISSUES:
            self._issues.add(code)
        if code in {'local_eviction', 'retention_gap', 'replay_incomplete'}:
            self._coverage['truncated'] = True

    def reset(self):
        for collection in (self._tasks, self._agents, self._events, self._ids):
            collection.clear()
        self.issue('stream_reset')

    def connection(self, state, reason=None):
        if state not in {'disabled', 'connecting', 'replaying', 'live', 'disconnected'}:
            raise ValueError('invalid connection state')
        self._connection = dict(state=state, reason=reason if type(reason) is str and reason in _REASONS else ('unavailable' if reason else None))

    def coverage(self, first_seq, last_seq, ttl_seconds, max_bytes, *, replay_complete=False):
        self._coverage.update(first_seq=first_seq, last_seq=last_seq, ttl_seconds=ttl_seconds,
                              max_bytes=max_bytes, replay_complete=bool(replay_complete))

    def _purge(self, force=False):
        now = self.clock()
        if not force and self._purged_at is not None and now-self._purged_at < 1:
            return
        self._purged_at = now
        ttl = self._coverage['ttl_seconds'] or 86400
        now = self.clock()
        for collection in (self._tasks, self._agents, self._events, self._ids):
            for key in list(collection):
                if now - collection[key]['_observed'] >= ttl:
                    del collection[key]

    def _bound(self, collection, limit):
        while len(collection) > limit:
            collection.popitem(last=False)
            self.issue('local_eviction')

    def _scrub(self, text):
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, '***')
        text = re.sub(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', '***', text, flags=re.S)
        text = re.sub(r'(?i)\bBearer\s+[^\s,;]+', 'Bearer ***', text)
        text = re.sub(r'(?i)\b(?:token|password|api_key|secret|authorization)\s*[:=]\s*(?:"[^"]*"|\x27[^\x27]*\x27|[^\s,;]+)', '***', text)
        text = re.sub(r'(?i)\b[a-z][a-z0-9+.-]*://[^\s/@]+@[^\s]+', '***', text)
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    def ingest(self, data, subject, sequence):
        self._purge()
        try:
            if type(data) is not bytes or len(data) > 131072 or type(sequence) is not int or sequence <= 0:
                raise ValueError()
            obj = json.loads(data, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            # Bound nesting even when the JSON parser can accept it.
            stack = [(obj, 0)]
            while stack:
                value, depth = stack.pop()
                if depth > 32 or (type(value) is float and not math.isfinite(value)):
                    raise ValueError()
                if isinstance(value, (dict, list)):
                    stack.extend((v, depth+1) for v in (value.values() if isinstance(value, dict) else value))
            required = {'message_id', 'task_id', 'correlation_id', 'source', 'target', 'kind', 'payload'}
            if type(obj) is not dict or set(obj) not in (required, required | {'created_at'}) or any(not valid_id(obj.get(k)) for k in ('message_id', 'task_id', 'correlation_id', 'source', 'target')):
                raise ValueError()
            kind = obj.get('kind')
            if type(kind) is not str or kind not in _STATES | {'registration', 'heartbeat'} or type(obj.get('payload')) is not dict or subject != 'devbus.events.' + obj['source']:
                raise ValueError()
        except (ValueError, TypeError, RecursionError, UnicodeError):
            self.issue('invalid_event')
            return False
        mid, task_id, agent = obj['message_id'], obj['task_id'], obj['source']
        fingerprint = hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).digest()
        if mid in self._ids:
            if self._ids[mid]['digest'] != fingerprint:
                self.issue('id_conflict')
            return False
        if kind in _STATES and task_id in self._tasks and self._tasks[task_id]['agent'] != agent:
            self.issue('id_conflict')
            return False
        now = self.clock()
        self._ids[mid] = dict(digest=fingerprint, _observed=now)
        self._bound(self._ids, self.limits.dedup)
        at, seconds = _timestamp(obj.get('created_at'))
        event = dict(message_id=mid, task_id=task_id, agent=agent, kind=kind, event_at=at, sequence=sequence)
        self._events[mid] = dict(event, _observed=now)
        self._bound(self._events, self.limits.events)
        payload = obj['payload']
        if kind in _STATES:
            task = self._tasks.setdefault(task_id, dict(task_id=task_id, agent=agent, state=kind,
                delivery='unknown', quality='unreviewed', event_at=None, submitted_at=None,
                duration_seconds=None, result=None, error=None, output_truncated=False,
                transitions=[], _sequence=0, _observed=now))
            task['_observed'] = now
            task['transitions'].append(event)
            task['transitions'].sort(key=lambda e:e['sequence'])
            if len(task['transitions']) > self.limits.transitions:
                task['transitions'] = task['transitions'][-self.limits.transitions:]
                self.issue('local_eviction')
            if sequence > task['_sequence']:
                task.update(state=kind, event_at=at, _sequence=sequence, result=None, error=None, output_truncated=False)
                if kind == 'completed' and type(payload.get('text')) is str:
                    text = self._scrub(payload['text'])
                    task.update(result=text[:self.limits.text], output_truncated=payload.get('output_truncated') is True or len(text)>self.limits.text)
                if kind == 'failed':
                    reason = payload.get('reason')
                    task['error'] = reason if type(reason) is str and reason in {'timeout','output_limit','executor_exit','local_executor_error','interrupted'} else 'unknown_error'
            self._bound(self._tasks, self.limits.tasks)
        else:
            record = self._agents.setdefault(agent, dict(agent=agent, registered=False, capabilities=[], executor=None,
                version=None, heartbeat_at=None, heartbeat_status='unknown', _heartbeat=None, _hb_seq=0, _reg_seq=0, _observed=now))
            record['_observed'] = now
            if kind == 'registration' and sequence > record['_reg_seq']:
                caps = payload.get('capabilities')
                record.update(registered=True, capabilities=[c for c in caps if valid_id(c)][:32] if type(caps) is list else [],
                    executor=payload.get('executor') if type(payload.get('executor')) is str and payload.get('executor') in {'codex','echo-test-only'} else None,
                    version=payload.get('version') if valid_id(payload.get('version')) else None, _reg_seq=sequence)
            if kind == 'heartbeat' and sequence > record['_hb_seq']:
                record.update(heartbeat_at=at, _heartbeat=seconds, _hb_seq=sequence)
            self._bound(self._agents, self.limits.agents)
        return True

    def snapshot(self, task=None, agent=None):
        self._purge(force=True)
        def public(record):
            return {k:v for k,v in record.items() if not k.startswith('_')}
        coverage = dict(self._coverage, issues=sorted(self._issues))
        if coverage['first_seq'] is None:
            coverage['mode'] = 'unknown'
        elif coverage['truncated']:
            coverage['mode'] = 'partial'
        elif coverage['replay_complete']:
            coverage['mode'] = 'window'
        else:
            coverage['mode'] = 'replaying'
        tasks = [public(t) for t in self._tasks.values() if (task is None or t['task_id']==task) and (agent is None or t['agent']==agent)]
        events = [public(e) for e in self._events.values() if (task is None or e['task_id']==task) and (agent is None or e['agent']==agent)]
        events.sort(key=lambda e:e['sequence'])
        agents = []
        for record in self._agents.values():
            if agent is not None and record['agent'] != agent:
                continue
            if task is not None and not any(t['agent']==record['agent'] for t in tasks):
                continue
            value = public(record)
            age = None if record['_heartbeat'] is None else self.clock()-record['_heartbeat']
            value['heartbeat_status'] = 'unknown' if age is None or age < -5 else ('stale' if age >= self.limits.stale_seconds else 'fresh')
            agents.append(value)
        return copy.deepcopy(dict(schema=1, connection=self._connection, coverage=coverage, tasks=tasks, agents=agents, events=events))


class Observer:
    def __init__(self, projection, connect, *, retry_seconds=1, operation_timeout=5):
        self.projection, self.connect = projection, connect
        self.retry_seconds, self.timeout = retry_seconds, min(operation_timeout,5)
        self._worker = None
        self._stopping = False
        self._transport = None
        self._last_observed = None
        self._last_stream = None

    async def _io(self, awaitable):
        async with asyncio.timeout(self.timeout):
            return await awaitable

    async def start(self):
        if self._worker is None or self._worker.done():
            self._stopping = False
            self._worker = asyncio.create_task(self._run())

    async def stop(self):
        self._stopping = True
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.cancel()
            try:
                await asyncio.wait_for(worker, self.timeout*2 + .1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    async def _close(self):
        transport, self._transport = self._transport, None
        if transport is not None:
            try:
                await self._io(transport.close())
            except Exception:
                pass

    def _metadata(self, info, complete):
        first, last = info['first_seq'], info['last_seq']
        if self._last_stream is not None and last < self._last_stream:
            self.projection.reset()
            self._last_observed = None
        elif self._last_observed is not None and first > self._last_observed+1:
            self.projection.issue('retention_gap')
        self._last_stream = last
        self.projection.coverage(first,last,info['ttl_seconds'],info['max_bytes'],replay_complete=complete)

    async def _run(self):
        try:
            while not self._stopping:
                self.projection.connection('connecting')
                try:
                    self._transport = await self._io(self.connect())
                    info = await self._io(self._transport.info())
                    self._metadata(info,False)
                    initial_last = info['last_seq']
                    complete, limited = False, False
                    count = size = 0
                    started = refreshed = time.monotonic()
                    self.projection.connection('replaying')
                    while not self._stopping:
                        if time.monotonic()-refreshed >= 1:
                            info = await self._io(self._transport.info())
                            self._metadata(info,complete)
                            refreshed = time.monotonic()
                        messages = await self._io(self._transport.fetch())
                        for message in messages:
                            count += 1
                            size += len(message.data)
                            if message.subject.startswith('devbus.events.'):
                                self.projection.ingest(message.data,message.subject,message.sequence)
                                self._last_observed = max(self._last_observed or 0,message.sequence)
                                await self._io(message.ack())
                        if not complete and not limited:
                            if count >= 10000 or size >= 8*1024*1024 or time.monotonic()-started >= 10:
                                self.projection.issue('replay_incomplete')
                                await self._io(self._transport.skip_to(initial_last+1))
                                limited = True
                                self.projection.connection('live')
                            elif await self._io(self._transport.pending()) == 0:
                                complete = True
                                self._metadata(info,True)
                                self.projection.connection('live')
                        if not messages:
                            await asyncio.sleep(.01)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.projection.connection('disconnected','unavailable')
                finally:
                    await self._close()
                if not self._stopping:
                    await asyncio.sleep(self.retry_seconds)
        finally:
            await self._close()


def install_routes(app, projection, authorize, *, origin, owner_only=True):
    from fastapi import Request
    from fastapi.responses import JSONResponse

    async def overview(request: Request):
        def error(status):
            return JSONResponse({'error':'unauthorized' if status==401 else ('forbidden' if status==403 else 'invalid_request')}, status_code=status, headers={'Cache-Control':'no-store'})
        try:
            auth = authorize(request)
            principal, failure = await auth if inspect.isawaitable(auth) else auth
            if failure is not None:
                return error(401 if failure.status_code==401 else 403)
            if owner_only is not True or not principal or principal.get('principal') != 'owner':
                return error(403)
            origins = request.headers.getlist('origin')
            if origins and origins != [origin]:
                return error(403)
            params = {}
            for key,value in request.query_params.multi_items():
                if key not in {'task','agent'} or key in params or not valid_id(value):
                    return error(400)
                params[key] = value
            return JSONResponse(projection.snapshot(**params), headers={'Cache-Control':'no-store'})
        except Exception:
            return JSONResponse({'error':'unavailable'},status_code=503,headers={'Cache-Control':'no-store'})
    app.add_api_route('/api/devbus/overview',overview,methods=['GET'])
