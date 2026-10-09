"""Narrow owner-side task interface. Never returns raw registry documents."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import threading
import time
import uuid

from _control_web_devbus import Observer, Projection, _timestamp, valid_id, valid_metadata
from _control_web_devbus_nats import NatsConfig, connect

DEVBUS_CONFIG_PATH = Path('/home/dwl/.config/ai-control/devbus-observer.json')
DEVBUS_LIMIT = 96 * 1024
_BUS_STATES = {'accepted', 'running', 'completed', 'failed', 'needs_attention'}
_BUS_ISSUES = {'local_eviction', 'invalid_event', 'id_conflict', 'retention_gap', 'stream_reset', 'replay_incomplete'}


def load_devbus_config():
    """Owner startup ingress; never consult ambient transport credentials."""
    disabled = NatsConfig()
    pointer = os.environ.get('CONTROL_DEVBUS_CONFIG')
    if pointer is None:
        return disabled, None
    if pointer != str(DEVBUS_CONFIG_PATH) or os.geteuid() != 1000:
        return disabled, 'invalid_config'
    try:
        fd = os.open(DEVBUS_CONFIG_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return disabled, None
    except Exception:
        return disabled, 'invalid_config'
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 1000
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 0 <= before.st_size <= 16384):
            raise ValueError('invalid_config')
        data = bytearray()
        while len(data) < 16385:
            block = os.read(fd, 16385 - len(data))
            if not block:
                break
            data.extend(block)
        after = os.fstat(fd)
        leaf = os.stat(DEVBUS_CONFIG_PATH, follow_symlinks=False)
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
                  'st_size', 'st_mtime_ns', 'st_ctime_ns')
        identity = lambda info: tuple(getattr(info, name) for name in fields)
        if (identity(before) != identity(after) or identity(after) != identity(leaf)
                or len(data) > 16384 or len(data) != before.st_size):
            raise ValueError('invalid_config')
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('invalid_config')
                result[key] = value
            return result
        def nonfinite(_):
            raise ValueError('invalid_config')
        value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=nonfinite)
        if (type(value) is not dict or set(value) != {'CONTROL_DEVBUS_ENABLED',
                'CONTROL_DEVBUS_STREAM', 'DEVBUS_NATS_URL', 'DEVBUS_NATS_TOKEN'}
                or any(type(item) is not str or any(ord(c) < 32 or 127 <= ord(c) <= 159
                    or 0xd800 <= ord(c) <= 0xdfff for c in item) for item in value.values())
                or value['CONTROL_DEVBUS_ENABLED'] not in ('0', '1')
                or not valid_id(value['CONTROL_DEVBUS_STREAM'])
                or (value['CONTROL_DEVBUS_ENABLED'] == '1' and not value['DEVBUS_NATS_TOKEN'])):
            raise ValueError('invalid_config')
        return NatsConfig.from_env(value), None
    except Exception:
        return disabled, 'invalid_config'
    finally:
        os.close(fd)


def _devbus_empty(state='disabled', reason=None):
    return dict(schema=1, connection=dict(state=state, reason=reason),
                coverage=dict(mode='unknown', first_seq=None, last_seq=None,
                    ttl_seconds=None, max_bytes=None, replay_complete=False, truncated=False, issues=[]),
                tasks=[], agents=[], events=[])


def _devbus_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True,
                      allow_nan=False).encode('utf-8')


def _valid_devbus_dto(value):
    """Validate exact accepted public shapes, including types below containers."""
    def shape(item, keys):
        return type(item) is dict and set(item) == set(keys.split())
    def member(item, choices):
        return type(item) is str and item in choices
    def nullable(item, predicate):
        return item is None or predicate(item)
    def timestamp(item):
        return nullable(item, lambda v: _timestamp(v)[0] is not None)
    def integer(item, low=0):
        return type(item) is int and item >= low
    def bound(item, maximum):
        return nullable(item, lambda v: type(v) in (int, float) and math.isfinite(v) and 0 < v <= maximum)
    def event(item):
        return (shape(item, 'message_id task_id agent kind event_at sequence')
                and valid_id(item['message_id']) and nullable(item['task_id'], valid_id)
                and valid_id(item['agent']) and member(item['kind'], _BUS_STATES | {'registration', 'heartbeat'})
                and timestamp(item['event_at']) and integer(item['sequence'], 1))
    if (not shape(value, 'schema connection coverage tasks agents events')
            or type(value['schema']) is not int or value['schema'] != 1):
        return False
    connection, coverage = value['connection'], value['coverage']
    if (not shape(connection, 'state reason')
            or not member(connection['state'], {'disabled', 'connecting', 'replaying', 'live', 'disconnected'})
            or not nullable(connection['reason'], lambda v: member(v, {'disabled', 'unavailable',
                'invalid_config', 'dependency_unavailable', 'stream_policy', 'connection_lost'}))
            or not shape(coverage, 'mode first_seq last_seq ttl_seconds max_bytes replay_complete truncated issues')
            or not member(coverage['mode'], {'unknown', 'partial', 'window', 'replaying'})
            or not nullable(coverage['first_seq'], integer) or not nullable(coverage['last_seq'], integer)
            or not bound(coverage['ttl_seconds'], 86400) or not bound(coverage['max_bytes'], 104857600)
            or type(coverage['replay_complete']) is not bool or type(coverage['truncated']) is not bool
            or type(coverage['issues']) is not list
            or any(not member(issue, _BUS_ISSUES) for issue in coverage['issues'])
            or coverage['issues'] != sorted(set(coverage['issues']))):
        return False
    if coverage['first_seq'] is None and coverage['mode'] != 'unknown':
        return False
    for key, maximum in (('tasks', 256), ('agents', 128), ('events', 512)):
        if type(value[key]) is not list or len(value[key]) > maximum:
            return False
    if not all(event(item) for item in value['events']):
        return False
    for item in value['tasks']:
        if (not shape(item, 'task_id agent state delivery quality event_at submitted_at duration_seconds result error output_truncated transitions')
                or not valid_id(item['task_id']) or not valid_id(item['agent'])
                or not member(item['state'], _BUS_STATES) or not member(item['delivery'], {'unknown'})
                or not member(item['quality'], {'unreviewed'}) or not timestamp(item['event_at'])
                or item['submitted_at'] is not None or item['duration_seconds'] is not None
                or not nullable(item['result'], lambda v: type(v) is str and len(v) <= 4096)
                or not nullable(item['error'], lambda v: member(v, {'timeout', 'output_limit', 'executor_exit',
                    'local_executor_error', 'interrupted', 'unknown_error'}))
                or type(item['output_truncated']) is not bool or type(item['transitions']) is not list
                or len(item['transitions']) > 32 or not all(event(row) for row in item['transitions'])):
            return False
    for item in value['agents']:
        if (not shape(item, 'agent registered capabilities executor version heartbeat_at heartbeat_status')
                or not valid_id(item['agent']) or type(item['registered']) is not bool
                or type(item['capabilities']) is not list or len(item['capabilities']) > 32
                or not all(valid_metadata(row) for row in item['capabilities'])
                or not nullable(item['executor'], lambda v: member(v, {'codex', 'echo-test-only'}))
                or not nullable(item['version'], valid_metadata) or not timestamp(item['heartbeat_at'])
                or not member(item['heartbeat_status'], {'unknown', 'stale', 'fresh'})):
            return False
    # UTF-8 serialization rejects lone surrogates everywhere (wire validation
    # never repairs data). Measurement is separate so clipping can validate first.
    _devbus_bytes(value)
    return True


def devbus_result(value):
    try:
        if _valid_devbus_dto(value) and len(_devbus_bytes(value)) <= DEVBUS_LIMIT:
            return copy.deepcopy(value)
    except Exception:
        pass
    return {'error': 'unavailable'}


def _devbus_private_result(value):
    if (type(value) is dict and set(value) == {'error'} and type(value['error']) is str
            and value['error'] in {'busy', 'unsupported', 'unavailable'}):
        return dict(value)
    return devbus_result(value)


def _devbus_limited(value):
    coverage = value['coverage']
    coverage['truncated'] = True
    coverage['issues'] = sorted(set(coverage['issues']) | {'local_eviction'})
    coverage['mode'] = 'partial' if coverage['first_seq'] is not None else 'unknown'


def bounded_devbus_snapshot(projection, task=None, agent=None):
    """Export a filtered copy only; accepted retention is never mutated."""
    try:
        if not all(item is None or valid_id(item) for item in (task, agent)):
            return {'error': 'unavailable'}
        value = copy.deepcopy(projection.snapshot(task, agent))
        # Only known producer result text has this transport-local exception.
        if type(value) is dict and type(value.get('tasks')) is list:
            sanitized = False
            for row in value['tasks']:
                if type(row) is dict and type(row.get('result')) is str:
                    result = row['result']
                    if any(0xd800 <= ord(c) <= 0xdfff for c in result):
                        row['result'] = ''.join('\ufffd' if 0xd800 <= ord(c) <= 0xdfff else c for c in result)
                        row['output_truncated'] = True
                        sanitized = True
            # Validate before applying coverage helpers to untrusted structures.
            if not _valid_devbus_dto(value):
                return {'error': 'unavailable'}
            if sanitized:
                _devbus_limited(value)
        if not _valid_devbus_dto(value):
            return {'error': 'unavailable'}
        if len(_devbus_bytes(value)) <= DEVBUS_LIMIT:
            return value
        ranks = sorted((max((row['sequence'] for row in item['transitions']), default=0), item['task_id'])
                       for item in value['tasks'])
        for item in value['tasks']:
            if item['result'] is not None and len(item['result']) > 256:
                item['result'] = item['result'][:256]
                item['output_truncated'] = True
        _devbus_limited(value)
        if len(_devbus_bytes(value)) <= DEVBUS_LIMIT:
            return value

        def minimum_prefix(count, apply):
            # Monotonic serialized size permits bounded binary search; at most
            # 8192 transitions, never one full serialization per removed row.
            original = copy.deepcopy(value)
            def candidate(n):
                data = copy.deepcopy(original)
                apply(data, n)
                return data
            full = candidate(count)
            if len(_devbus_bytes(full)) > DEVBUS_LIMIT:
                value.clear(); value.update(full)
                return False
            low, high = 1, count
            while low < high:
                middle = (low + high) // 2
                if len(_devbus_bytes(candidate(middle))) <= DEVBUS_LIMIT:
                    high = middle
                else:
                    low = middle + 1
            value.clear(); value.update(candidate(low))
            return True

        ordered = sorted(value['events'], key=lambda row: (row['sequence'], row['message_id']))
        if ordered and minimum_prefix(len(ordered), lambda data, n: data.update(events=ordered[n:])):
            return value
        transitions = sorted((row['sequence'], row['message_id'], item['task_id'])
                             for item in value['tasks'] for row in item['transitions'])
        def remove_transitions(data, n):
            removed = set(transitions[:n])
            for item in data['tasks']:
                item['transitions'] = [row for row in item['transitions']
                    if (row['sequence'], row['message_id'], item['task_id']) not in removed]
        if transitions and minimum_prefix(len(transitions), remove_transitions):
            return value
        def remove_tasks(data, n):
            removed = {item[1] for item in ranks[:n]}
            data['tasks'] = [item for item in data['tasks'] if item['task_id'] not in removed]
        if ranks and minimum_prefix(len(ranks), remove_tasks):
            return value
        if value['agents'] and minimum_prefix(len(value['agents']),
                lambda data, n: data.update(agents=data['agents'][n:])):
            return value
        return devbus_result(value)
    except Exception:
        return {'error': 'unavailable'}


class DevbusRuntime:
    """One owner loop and one export token retained through actual completion."""
    def __init__(self, *, config_loader=load_devbus_config, projection_factory=Projection,
                 observer_factory=Observer, connect_factory=connect, dependency_probe=None):
        self._loader, self._projection_factory = config_loader, projection_factory
        self._observer_factory, self._connect_factory = observer_factory, connect_factory
        self._probe = dependency_probe if dependency_probe is not None else lambda: importlib.util.find_spec('nats') is not None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._started = False
        self._failed = False
        self._loop = self._thread = self._observer = self._projection = None
        self._cleanup_task = None
        self._cleanup_failed = False
        self._export_token = None
        self._fallback = _devbus_empty()

    def start(self):
        with self._lock:
            if self._started or self._stopping.is_set():
                return
            self._started = True
        try:
            config, reason = self._loader()
            if reason is not None:
                self._fallback = _devbus_empty('disconnected', 'invalid_config')
                return
            if not config.enabled:
                return
            self._fallback = _devbus_empty('disconnected', 'unavailable')
            present = self._probe()
            if present is not True:
                if present is False:
                    self._fallback = _devbus_empty('disconnected', 'dependency_unavailable')
                return
            self._thread = threading.Thread(target=self._run, args=(config,), daemon=True, name='control-devbus')
            self._thread.start()
            if not self._ready.wait(1):
                with self._lock:
                    self._failed = True
                self.request_stop()
        except Exception:
            self._fallback = _devbus_empty('disconnected', 'unavailable')
            with self._lock:
                self._failed = True
            self.request_stop()

    def _run(self, config):
        try:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
        except Exception:
            with self._lock:
                self._failed = True
            self._ready.set()
            if self._loop is not None:
                self._loop.close()
            return
        async def setup():
            if self._stopping.is_set():
                return
            self._projection = self._projection_factory(secrets=(config.token,) if config.token else ())
            if self._stopping.is_set():
                return
            self._observer = self._observer_factory(self._projection, lambda: self._connect_factory(config))
            if self._stopping.is_set():
                return
            await self._observer.start()
        try:
            loop.run_until_complete(setup())
            self._ready.set()
            if self._stopping.is_set():
                loop.run_until_complete(self._cleanup())
            else:
                loop.run_forever()
        except Exception:
            with self._lock:
                self._failed = True
            self._ready.set()
        finally:
            # Pending cleanup stays on this same thread/loop, even when startup
            # timed out during a synchronous injected factory.
            try:
                try:
                    loop.run_until_complete(self._cleanup())
                except Exception:
                    self._cleanup_failed = True
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    _, alive = loop.run_until_complete(asyncio.wait(pending, timeout=.5))
                    if alive:
                        self._cleanup_failed = True
                        # A noncompliant coroutine keeps this same loop/thread
                        # alive. stop() reports failure at its 12s bound; closing
                        # beneath live callbacks would falsely claim cleanup.
                        loop.run_until_complete(asyncio.gather(*alive, return_exceptions=True))
            finally:
                loop.close()

    async def _cleanup(self):
        if self._cleanup_task is None:
            async def close():
                if self._observer is not None:
                    await asyncio.wait_for(self._observer.stop(), 10.1)
            self._cleanup_task = asyncio.create_task(close())
        await asyncio.shield(self._cleanup_task)

    def request_stop(self):
        """Nonblocking signal hook; cleanup runs alongside legacy worker drain."""
        self._stopping.set()
        loop = self._loop
        if loop is not None and not loop.is_closed():
            def submit():
                async def finish():
                    try:
                        await self._cleanup()
                    except Exception:
                        self._cleanup_failed = True
                    finally:
                        loop.stop()
                if not getattr(self, '_shutdown_submitted', False):
                    self._shutdown_submitted = True
                    asyncio.create_task(finish())
            try:
                loop.call_soon_threadsafe(submit)
            except RuntimeError:
                pass

    def snapshot(self, task=None, agent=None):
        if not all(value is None or valid_id(value) for value in (task, agent)):
            return {'error': 'unavailable'}
        with self._lock:
            if self._failed or self._stopping.is_set():
                return _devbus_empty('disconnected', 'unavailable')
            if self._thread is None:
                return copy.deepcopy(self._fallback)
            if not self._ready.is_set() or not self._thread.is_alive() or self._loop.is_closed():
                return _devbus_empty('disconnected', 'unavailable')
            if self._export_token is not None:
                return {'error': 'busy'}
            token = self._export_token = object()
        deadline = time.monotonic() + 1
        cancellation = threading.Event()
        export_task = None
        async def export():
            nonlocal export_task
            try:
                export_task = asyncio.current_task()
                if cancellation.is_set() or self._stopping.is_set() or time.monotonic() >= deadline:
                    return {'error': 'unavailable'}
                value = bounded_devbus_snapshot(self._projection, task, agent)
                return value if time.monotonic() < deadline else {'error': 'unavailable'}
            finally:
                with self._lock:
                    if self._export_token is token:
                        self._export_token = None
        coroutine = export()
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except Exception:
            coroutine.close()
            with self._lock:
                if self._export_token is token:
                    self._export_token = None
            return {'error': 'unavailable'}
        try:
            return _devbus_private_result(future.result(max(0, deadline - time.monotonic())))
        except FutureTimeout:
            # Cancel on the owner loop, not the concurrent Future. Cancelling
            # that Future before coroutine entry can skip its finally entirely.
            # A queued export observes this flag and releases its own token.
            cancellation.set()
            def cancel_export():
                if export_task is not None:
                    export_task.cancel()
            try:
                self._loop.call_soon_threadsafe(cancel_export)
            except RuntimeError:
                pass
            return {'error': 'unavailable'}
        except Exception:
            return {'error': 'unavailable'}

    def stop(self):
        self.request_stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(12)
            if thread.is_alive():
                raise RuntimeError('devbus cleanup unavailable')
            if self._cleanup_failed:
                raise RuntimeError('devbus cleanup unavailable')

LIMIT = 128 * 1024
FIELD_LIMIT = 16000
NAME = re.compile(r'[a-z][a-z0-9-]{0,30}[a-z0-9]\Z')
GEN = re.compile(r'[0-9a-f]{8}\Z')
PROJECT = re.compile(r'[a-zA-Z0-9_-]{1,32}\Z')
SESSION_FIELDS = {
    'session_projects': {'op'},
    'session_project_summary': {'op'},
    'session_list': {'op', 'project', 'page'},
    'session_history': {'op', 'project', 'sid', 'cursor'},
    'session_live_snapshot': {'op', 'project', 'sid'},
    'session_models': {'op', 'project', 'sid'},
    'session_send': {'op', 'project', 'sid', 'message_id', 'text'},
    'session_send_status': {'op', 'project', 'sid', 'message_id'},
    'session_rename': {'op', 'project', 'sid', 'operation_id', 'title'},
    'session_rename_status': {'op', 'project', 'sid', 'operation_id'},
    'session_create_options': {'op', 'project'},
    'session_create': {'op', 'project', 'operation_id', 'context_mode', 'provider_id'},
    'session_create_status': {'op', 'project', 'operation_id', 'context_mode', 'provider_id'},
}


def _valid_session(request):
    if (type(request) is not dict or type(request.get('op')) is not str
            or request['op'] not in SESSION_FIELDS):
        return False
    fields = SESSION_FIELDS[request['op']]
    if set(request) != fields and not (
            request['op'] == 'session_send' and set(request) == fields | {'selection'}):
        return False
    if 'selection' in request:
        from _control_web_sessions import _valid_selection
        if not _valid_selection(request['selection']):
            return False
    if 'project' in request and (type(request['project']) is not str or not PROJECT.fullmatch(request['project'])):
        return False
    if any(not valid_qid(request[key]) for key in ('sid', 'message_id', 'operation_id') if key in request):
        return False
    if 'page' in request and (type(request['page']) is not int or request['page'] < 0):
        return False
    if 'cursor' in request and request['cursor'] is not None and (
            type(request['cursor']) is not str or not 0 < len(request['cursor']) <= 4096):
        return False
    if 'context_mode' in request and (request['context_mode'] != 'configured'
                                      or request['provider_id'] != 'codex'):
        return False
    if 'title' in request and not valid_rename_title(request['title']):
        return False
    return 'text' not in request or valid_text(request['text'], True)


def valid_rename_title(title):
    try:
        from _control_web_sessions import SessionChat
        SessionChat._rename_title(title)
        return True
    except Exception:
        return False


def rename_result(result, operation_id):
    if type(result) is not dict:
        return {'error': 'unavailable'}
    if 'error' in result:
        code = result['error']
        return {'error': code if code in ('invalid_request', 'forbidden', 'stale') else 'unavailable'}
    if result.get('operation_id') != operation_id or result.get('status') not in ('accepted', 'delivery_unknown'):
        return {'error': 'unavailable'}
    safe = {'operation_id': operation_id, 'status': result['status']}
    if result['status'] == 'accepted':
        title = result.get('title')
        if type(title) is not str or not title.strip():
            return {'error': 'unavailable'}
        try:
            title.encode('utf-8')
        except UnicodeError:
            return {'error': 'unavailable'}
        safe['title'] = redact(title)[:500]
    return safe


def configured_create_result(result, project, operation_id=None):
    """Exact public DTO gate; no private object is projected by dropping fields."""
    failure = {'error': 'unavailable'}
    if type(result) is not dict:
        return failure
    if 'error' in result:
        code = result['error']
        return {'error': code if set(result) == {'error'} and code in
                ('invalid_request', 'forbidden', 'stale') else 'unavailable'}
    if operation_id is None:
        if (set(result) != {'schema', 'project', 'options'} or type(result['schema']) is not int
                or result['schema'] != 1 or result['project'] != project
                or type(result['options']) is not list or len(result['options']) != 1):
            return failure
        row = result['options'][0]
        if (type(row) is not dict or set(row) != {'context_mode', 'provider_id', 'available', 'reason'}
                or row['context_mode'] != 'configured' or row['provider_id'] != 'codex'
                or type(row['available']) is not bool
                or row['reason'] != (None if row['available'] else 'unavailable')):
            return failure
        return dict(schema=1, project=project, options=[dict(row)])
    if result.get('operation_id') != operation_id:
        return failure
    if result.get('status') == 'delivery_unknown':
        return dict(result) if set(result) == {'operation_id', 'status'} else failure
    if set(result) != {'operation_id', 'status', 'session'} or result['status'] != 'accepted':
        return failure
    session = result['session']
    if (type(session) is not dict or set(session) != {'sid', 'project', 'vendor', 'context_mode', 'title'}
            or not valid_qid(session['sid']) or session['project'] != project
            or session['vendor'] != 'codex' or session['context_mode'] != 'configured'
            or session['title'] is not None and (type(session['title']) is not str or len(session['title']) > 500)):
        return failure
    title = session['title']
    if title is not None:
        try:
            title.encode('utf-8')
        except UnicodeError:
            return failure
        title = redact(title)[:500]
    return dict(operation_id=operation_id, status='accepted', session=dict(session, title=title))


def valid_session_setting(value):
    return (type(value) is str and 0 < len(value) <= 256
            and not any(ord(char) < 32 or 127 <= ord(char) <= 159
                        or 0xd800 <= ord(char) <= 0xdfff for char in value)
            and SECRET_RE.search(value) is None)


def session_settings_result(value):
    fields = {'schema', 'source', 'scope', 'model', 'effort', 'age_ms', 'expires_in_ms'}
    if (type(value) is not dict or set(value) != fields
            or type(value['schema']) is not int or value['schema'] != 1
            or value['source'] != 'thread_read' or value['scope'] != 'configured_or_persisted'
            or any(value[key] is not None and not valid_session_setting(value[key])
                   for key in ('model', 'effort'))
            or type(value['age_ms']) is not int or not 0 <= value['age_ms'] < 15000
            or type(value['expires_in_ms']) is not int
            or value['expires_in_ms'] != 15000 - value['age_ms']):
        return None
    return dict(value)


def history_result(result):
    """Validate the honest unavailable variant, leaving ordinary history unchanged."""
    if type(result) is not dict:
        return {'error': 'unavailable'}
    if 'history_state' not in result:
        return result
    if (set(result) - {'session_settings'} not in ({'history_state', 'reason', 'recent_sends'},
                           {'history_state', 'reason', 'recent_sends', 'needs_native_attention'})
            or result['history_state'] != 'unavailable' or result['reason'] != 'unavailable'
            or 'needs_native_attention' in result and result['needs_native_attention'] is not True
            or type(result['recent_sends']) is not list or len(result['recent_sends']) > 8):
        return {'error': 'unavailable'}
    recent = []
    for row in result['recent_sends']:
        if (type(row) is not dict or set(row) != {'status', 'message_id', 'turn_id'}
                or not valid_qid(row['message_id'])
                or row['status'] not in ('accepted', 'delivery_unknown', 'rejected')
                or row['status'] in ('delivery_unknown', 'rejected') and row['turn_id'] is not None
                or row['status'] == 'accepted' and
                   (type(row['turn_id']) is not str or not 0 < len(row['turn_id']) <= 500)):
            return {'error': 'unavailable'}
        recent.append(dict(row))
    safe = dict(history_state='unavailable', reason='unavailable', recent_sends=recent)
    settings = session_settings_result(result.get('session_settings'))
    if settings is not None:
        safe['session_settings'] = settings
    if result.get('needs_native_attention') is True:
        safe['needs_native_attention'] = True
    try:
        if len(json.dumps(safe, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 96 * 1024:
            return {'error': 'unavailable'}
    except (ValueError, UnicodeError):
        return {'error': 'unavailable'}
    return safe


def _send_request(project, sid, message_id, text, selection):
    request = dict(op='session_send', project=project, sid=sid, message_id=message_id, text=text)
    if selection is not None:
        request['selection'] = selection
    return request


def _forward_send(target, request):
    args = (request['project'], request['sid'], request['message_id'], request['text'])
    if 'selection' in request:
        return target(*args, selection=request['selection'])
    return target(*args)


# Intentional per-binary copy of ai-agent-run's complete export policy.
# Keep the established credential aliases without importing writer runtime.
SECRET_RE = re.compile(
    # покрытие расширено (аудит V2.7a, major 7): pwd/passwd/access_key -
    # смежные формы того же класса секрета, которые прежний список слов не
    # ловил (changes теперь тоже проходят через redact(), см. ниже).
    r'(?i)((?:api[_-]?key|access[_-]?key|token|secret|password|passwd|pwd|'
    r'authorization)"?\s*[=:]\s*"?'
    r'(?:bearer\s+)?)[^\s&"]+'
    r'|(\bbearer\s+)\S+'
    r'|\b(?:sk|xox[a-z]|ghp|gho|github_pat)-[A-Za-z0-9_-]{8,}'
    r'|\b[A-Za-z0-9+/_-]{40,}\b')


def redact(s):
    return SECRET_RE.sub(lambda m: (m.group(1) or m.group(2) or "") + "***", s)



def canonical_callback(callback, saved):
    if type(callback) is not dict:
        return False
    return (
        all(type(callback.get(key)) is str and callback[key]
            for key in ('attempt_id', 'thread_id', 'turn_id', 'item_id'))
        and valid_qid(callback.get('operation_id'))
        and type(callback.get('task_incarnation')) is str
        and bool(re.fullmatch(r'[0-9a-f]{32}', callback['task_incarnation']))
        and type(callback.get('generation')) is int and callback['generation'] > 0
        and (type(callback.get('request_id')) is int or
             (type(callback.get('request_id')) is str and bool(callback['request_id'])))
        and callback.get('method') == 'item/fileChange/requestApproval'
        and callback.get('status') in (('pending', 'answered') if saved else ('pending',))
        and all(type(callback.get(key)) is str and re.fullmatch(r'[0-9a-f]{64}', callback[key])
                for key in ('payload_fingerprint', 'changes_digest'))
        and callback.get('allowed_decisions') in (['reject'], ['approve', 'reject']))


def valid_agent(value):
    return type(value) is str and bool(NAME.fullmatch(value))


def valid_qid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def valid_text(value, nonempty=False):
    return type(value) is str and len(value) <= FIELD_LIMIT and (not nonempty or bool(value.strip()))


def _read(parent, name, optional=False, yaml=False):
    """Read relative to an anchored directory; no traversal or symlink races."""
    if '/' in name or name in ('.', '..'):
        raise ValueError('invalid record')
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except FileNotFoundError:
        if optional:
            return None
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('invalid record')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('large record')
        text = data.decode('utf-8')
        try:
            doc = json.loads(text)
        except ValueError:
            if not yaml:
                raise
            # Reuse Control's existing YAML parser, over bounded stdin bytes.
            # No registry path reaches yq and its stderr never reaches the UI.
            result = subprocess.run(['yq', '-p=yaml', '-o=json', '.', '-'],
                                    input=text, capture_output=True, text=True,
                                    shell=False, timeout=5)
            if result.returncode != 0 or len(result.stdout.encode()) > LIMIT:
                raise ValueError('invalid specification')
            doc = json.loads(result.stdout)
        if type(doc) is not dict:
            raise ValueError('invalid record')
        return doc
    finally:
        os.close(fd)


def _dir(parent, name):
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _field(doc, key, default=''):
    value = doc.get(key, default)
    if not valid_text(value):
        raise ValueError('invalid field')
    return value


class RegistryBackend:
    def __init__(self, registry, bin_dir, runner=None, sessions=None, configured_creator=None, *, devbus=None):
        self.registry = os.path.abspath(registry)
        self.bin_dir = os.path.abspath(bin_dir)
        self.runner = runner or subprocess.run
        self.sessions = sessions
        self.configured_creator = configured_creator
        self.devbus = devbus

    def devbus_overview(self, task=None, agent=None):
        if not all(value is None or valid_id(value) for value in (task, agent)):
            return {'error': 'unavailable'}
        if self.devbus is None:
            return _devbus_empty()
        try:
            return _devbus_private_result(self.devbus.snapshot(task, agent))
        except Exception:
            return {'error': 'unavailable'}

    def _session(self, request):
        if not _valid_session(request):
            return {'error': 'invalid_request'}
        if request['op'] in ('session_create_options', 'session_create', 'session_create_status'):
            if self.configured_creator is None:
                return {'error': 'unavailable'}
            try:
                method = {'session_create_options': 'options', 'session_create': 'create',
                          'session_create_status': 'status'}[request['op']]
                args = (request['project'],) if method == 'options' else (
                    request['project'], request['operation_id'], request['context_mode'], request['provider_id'])
                result = getattr(self.configured_creator, method)(*args)
            except Exception as exc:
                result = {'error': getattr(exc, 'code', 'unavailable')}
            return configured_create_result(result, request['project'], request.get('operation_id'))
        if self.sessions is None:
            return {'error': 'unavailable'}
        try:
            op = request['op']
            if op == 'session_projects':
                result = self.sessions.projects()
            elif op == 'session_project_summary':
                result = self.sessions.project_summary()
            elif op == 'session_list':
                result = self.sessions.list_sessions(request['project'], request['page'])
            elif op == 'session_history':
                result = self.sessions.history(request['project'], request['sid'], request['cursor'])
            elif op == 'session_live_snapshot':
                result = self.sessions.live_snapshot(request['project'], request['sid'])
            elif op == 'session_models':
                result = self.sessions.models(request['project'], request['sid'])
            elif op == 'session_send':
                result = _forward_send(self.sessions.send, request)
            elif op == 'session_rename':
                result = self.sessions.rename(request['project'], request['sid'], request['operation_id'], request['title'])
            elif op == 'session_rename_status':
                result = self.sessions.rename_status(request['project'], request['sid'], request['operation_id'])
            else:
                result = self.sessions.send_status(request['project'], request['sid'], request['message_id'])
            if op == 'session_history':
                return history_result(result)
            if op in ('session_rename', 'session_rename_status'):
                return rename_result(result, request['operation_id'])
            return result if type(result) is dict else {'error': 'unavailable'}
        except Exception:
            return {'error': 'unavailable'}

    def session_projects(self):
        return self._session({'op': 'session_projects'})

    def session_project_summary(self):
        return self._session({'op': 'session_project_summary'})

    def session_list(self, project, page):
        return self._session(dict(op='session_list', project=project, page=page))

    def session_history(self, project, sid, cursor):
        return self._session(dict(op='session_history', project=project, sid=sid, cursor=cursor))

    def session_live_snapshot(self, project, sid):
        from _control_web_live import owner_result
        return owner_result(self._session(dict(op='session_live_snapshot', project=project, sid=sid)))

    def session_models(self, project, sid):
        return self._session(dict(op='session_models', project=project, sid=sid))

    def session_send(self, project, sid, message_id, text, selection=None):
        return self._session(_send_request(project, sid, message_id, text, selection))

    def session_send_status(self, project, sid, message_id):
        return self._session(dict(op='session_send_status', project=project, sid=sid, message_id=message_id))

    def session_create_options(self, project):
        return self._session(dict(op='session_create_options', project=project))

    def session_create(self, project, operation_id, context_mode, provider_id):
        return self._session(dict(op='session_create', project=project, operation_id=operation_id,
                                  context_mode=context_mode, provider_id=provider_id))

    def session_create_status(self, project, operation_id, context_mode, provider_id):
        return self._session(dict(op='session_create_status', project=project, operation_id=operation_id,
                                  context_mode=context_mode, provider_id=provider_id))

    def session_rename(self, project, sid, operation_id, title):
        return self._session(dict(op='session_rename', project=project, sid=sid, operation_id=operation_id, title=title))

    def session_rename_status(self, project, sid, operation_id):
        return self._session(dict(op='session_rename_status', project=project, sid=sid, operation_id=operation_id))

    def _root(self):
        return os.open(self.registry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def _raw_question(self, agent, qid):
        root = self._root()
        try:
            fd = _dir(root, agent)
            try:
                qfd = _dir(fd, 'questions')
                try:
                    return _read(qfd, qid + '.json')
                finally:
                    os.close(qfd)
            finally:
                os.close(fd)
        finally:
            os.close(root)

    def _question(self, fd, qid, engine):
        doc = _read(fd, qid + '.json')
        if doc.get('qid') != qid or doc.get('kind') not in ('info', 'permission') or doc.get('status') not in ('open', 'closed'):
            raise ValueError('invalid question')
        saved = doc.get('answered_at') is not None
        published = doc.get('event_published_at') is not None
        if saved and (not valid_text(doc['answered_at'], True) or not valid_text(doc.get('answered_by'), True)):
            raise ValueError('invalid saved answer')
        if published and not valid_text(doc['event_published_at'], True):
            raise ValueError('invalid publication')
        allowed, saved_answer, saved_decision = [], '', None
        if doc['kind'] == 'permission':
            allowed = ['approve', 'reject']
            if saved:
                saved_decision = doc.get('decision')
                if saved_decision not in allowed:
                    raise ValueError('invalid saved decision')
            if engine == 'codex' or doc.get('native_callback') is not None:
                callback = doc.get('native_callback')
                if engine != 'codex' or doc.get('engine') != 'codex' or not canonical_callback(callback, saved):
                    raise ValueError('invalid callback')
                allowed = callback['allowed_decisions']
                if saved and saved_decision not in allowed:
                    raise ValueError('invalid saved native decision')
        elif doc.get('native_callback') is not None:
            raise ValueError('invalid callback kind')
        elif saved:
            saved_answer = redact(_field(doc, 'answer'))
        return {'qid': qid, 'kind': doc['kind'], 'status': doc['status'],
                'question': redact(_field(doc, 'question')),
                'allowed_decisions': [] if saved or doc['status'] != 'open' else allowed,
                'answered': saved, 'pending_delivery': saved and not published,
                'saved_answer': saved_answer, 'saved_decision': saved_decision}

    def _task(self, root, name):
        fd = _dir(root, name)
        try:
            spec = _read(fd, 'spec.yaml', yaml=True)
            if spec.get('type') not in ('task', 'mission', 'event'):
                raise ValueError('invalid spec type')
            for key in ('type', 'engine', 'name'):
                if key in spec and not valid_text(spec[key], True):
                    raise ValueError('invalid spec scalar')
            if spec.get('type') != 'task':
                return None
            engine = spec.get('engine', 'claude')
            if engine not in ('claude', 'codex'):
                raise ValueError('invalid engine')
            control = _read(fd, 'control.json')
            generation = control.get('generation')
            if not isinstance(generation, (str, int)) or type(generation) is bool or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(generation)):
                raise ValueError('invalid generation')
            state = _read(fd, 'state.' + str(generation) + '.json', optional=True) or {}
            questions = []
            try:
                qfd = _dir(fd, 'questions')
            except FileNotFoundError:
                qfd = None
            if qfd is not None:
                try:
                    filenames = [n for n in os.listdir(qfd) if n.endswith('.json')]
                    if len(filenames) > 1000:
                        raise ValueError('many questions')
                    for filename in sorted(filenames):
                        qid = filename[:-5]
                        if not valid_qid(qid):
                            raise ValueError('invalid qid')
                        questions.append(self._question(qfd, qid, engine))
                finally:
                    os.close(qfd)
            done = _read(fd, 'done.json', optional=True)
            result = None
            if done is not None:
                key = _field(done, 'envelope_key')
                commit = _field(done, 'commit_sha') if done.get('commit_sha') is not None else ''
                if commit and not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', commit):
                    raise ValueError('invalid commit')
                result = {'generation': hashlib.sha256(('done-gen:' + key + ':' + commit).encode()).hexdigest()[:8],
                          'state': redact(_field(done, 'state')), 'summary': redact(_field(done, 'summary')),
                          'commit_sha': commit, 'finalized': done.get('finalized') is True}
            return {'agent': name, 'name': redact(_field(spec, 'name', name)), 'engine': engine,
                    'state': redact(_field(state, 'phase', 'unknown')), 'summary': redact(_field(state, 'status_line')),
                    'status_line': redact(_field(state, 'status_line')),
                    'questions': questions, 'result': result}
        finally:
            os.close(fd)

    def snapshot(self):
        try:
            root = self._root()
            try:
                names = os.listdir(root)
                tasks = []
                agents = 0
                for name in sorted(names):
                    if not valid_agent(name):
                        continue
                    info = os.stat(name, dir_fd=root, follow_symlinks=False)
                    if not stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                        continue
                    agents += 1
                    if agents > 1000:
                        return {'error': 'unavailable'}
                    try:
                        task = self._task(root, name)
                        if task is not None:
                            tasks.append(task)
                    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
                        tasks.append({'agent': name, 'unavailable': True, 'questions': [], 'result': None})
                return {'tasks': tasks}
            finally:
                os.close(root)
        except (OSError, ValueError):
            return {'error': 'unavailable'}

    def _checked_task(self, agent):
        if not valid_agent(agent):
            raise ValueError('invalid agent')
        root = self._root()
        try:
            task = self._task(root, agent)
            if task is None:
                raise ValueError('not task')
            return task
        finally:
            os.close(root)

    def _run(self, argv):
        # Only owner-configured helpers; no client env, executable or argv.
        return self.runner(argv, shell=False, capture_output=True, text=True, timeout=60)

    def answer(self, agent, qid, decision, text):
        if not valid_agent(agent) or not valid_qid(qid) or decision not in ('text', 'approve', 'reject', 'recover') or not valid_text(text, decision == 'text') or (decision == 'recover' and text != ''):
            return {'error': 'invalid_or_stale'}
        try:
            task = self._checked_task(agent)
            q = next((q for q in task['questions'] if q['qid'] == qid), None)
            if q is None or q['status'] != 'open':
                return {'error': 'invalid_or_stale'}
            if decision == 'recover':
                if not q['answered']:
                    return {'error': 'invalid_or_stale'}
            elif (decision == 'text' and q['kind'] != 'info') or (decision != 'text' and q['kind'] != 'permission'):
                return {'error': 'invalid_or_stale'}
            elif not q['answered'] and decision != 'text' and decision not in q['allowed_decisions']:
                return {'error': 'invalid_or_stale'}
            args = [os.path.join(self.bin_dir, 'ai-agent-answer'), os.path.join(self.registry, agent), '--qid', qid]
            args += ['--text', text] if decision == 'text' else ['--' + decision]
            args += ['--by', 'web']
            result = self._run(args)
            if result.returncode != 0:
                return {1: {'error': 'invalid_or_stale'}, 2: {'error': 'invalid_or_stale'}, 7: {'error': 'saved_pending'}}.get(result.returncode, {'error': 'unavailable'})
            # The writer owns the durable first answer, including a racing caller.
            # A successful publication must not falsely confirm later client text.
            original = self._raw_question(agent, qid)
            if original.get('qid') != qid or original.get('kind') != q['kind'] or original.get('answered_at') is None:
                return {'error': 'unavailable'}
            if original.get('event_published_at') is None:
                return {'error': 'saved_pending'}
            matching = original.get('answer') == text if decision == 'text' else original.get('decision') == decision
            return {'status': 'already' if q['answered'] or decision == 'recover' or not matching else 'applied'}
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            return {'error': 'unavailable'}

    def verdict(self, agent, generation, decision, comment):
        if not valid_agent(agent) or type(generation) is not str or not GEN.fullmatch(generation) or decision not in ('accept', 'reject') or not valid_text(comment):
            return {'error': 'invalid_or_stale'}
        try:
            task = self._checked_task(agent)
            done = task['result']
            if done is None or done['generation'] != generation:
                return {'error': 'stale'}
            if done['state'] == 'requested' and not done['finalized']:
                return {'error': 'invalid_or_stale'}
            args = [os.path.join(self.bin_dir, 'ai-agent-run'), 'done-verdict', os.path.join(self.registry, agent), '--' + decision, '--expect-sha', generation]
            if comment:
                args += ['--comment', comment]
            result = self._run(args)
            if result.returncode == 0 and result.stdout.strip() in ('applied', 'already'):
                return {'status': result.stdout.strip()}
            return {'error': {3: 'stale', 2: 'invalid_or_stale'}.get(result.returncode, 'unavailable')}
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            return {'error': 'unavailable'}


def _receive(conn, deadline=None):
    data = bytearray()
    while b'\n' not in data:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('broker deadline')
            conn.settimeout(remaining)
        block = conn.recv(min(4096, LIMIT + 1 - len(data)))
        if not block:
            raise ValueError('incomplete request')
        data.extend(block)
        if len(data) > LIMIT:
            raise ValueError('large request')
    line, rest = bytes(data).split(b'\n', 1)
    if rest:
        raise ValueError('multiple requests')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate field')
            result[key] = value
        return result
    return json.loads(line, object_pairs_hook=pairs)


def serve_broker(socket_path, backend, allowed_uid, stop_event=None):
    parent = os.path.dirname(os.path.abspath(socket_path))
    info = os.stat(parent, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o007:
        raise ValueError('private owner directory required')
    if os.path.lexists(socket_path):
        info = os.lstat(socket_path)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('refusing socket replacement')
        # A live owner socket must not be displaced either.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(socket_path)
            except ConnectionRefusedError:
                os.unlink(socket_path)
            else:
                raise ValueError('broker already running')
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    slots = threading.BoundedSemaphore(4)
    live_slot = threading.BoundedSemaphore(1)
    bus_slot = threading.BoundedSemaphore(1)
    workers = set()
    workers_lock = threading.Lock()
    fields = {'snapshot': {'op'}, 'answer': {'op', 'agent', 'qid', 'decision', 'text'},
              'verdict': {'op', 'agent', 'generation', 'decision', 'comment'},
              'devbus_overview': {'op', 'task', 'agent'}, **SESSION_FIELDS}

    def reply(conn, result):
        wire = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'
        if len(wire) > LIMIT:
            wire = b'{"error":"unavailable"}\n'
        conn.sendall(wire)

    def execute(conn, request):
        try:
            with conn:
                try:
                    op = request['op']
                    if op == 'snapshot':
                        result = backend.snapshot()
                    elif op == 'devbus_overview':
                        deadline = time.monotonic() + 5
                        result = _devbus_private_result(backend.devbus_overview(request['task'], request['agent']))
                        if time.monotonic() >= deadline:
                            result = {'error': 'unavailable'}
                    elif op == 'answer':
                        result = backend.answer(request['agent'], request['qid'], request['decision'], request['text'])
                    elif op == 'verdict':
                        result = backend.verdict(request['agent'], request['generation'], request['decision'], request['comment'])
                    elif op == 'session_projects':
                        result = backend.session_projects()
                    elif op == 'session_project_summary':
                        result = backend.session_project_summary()
                    elif op == 'session_list':
                        result = backend.session_list(request['project'], request['page'])
                    elif op == 'session_history':
                        result = backend.session_history(request['project'], request['sid'], request['cursor'])
                    elif op == 'session_live_snapshot':
                        from _control_web_live import owner_result
                        result = owner_result(backend.session_live_snapshot(request['project'], request['sid']))
                    elif op == 'session_models':
                        result = backend.session_models(request['project'], request['sid'])
                    elif op == 'session_send':
                        result = _forward_send(backend.session_send, request)
                    elif op == 'session_create_options':
                        result = backend.session_create_options(request['project'])
                    elif op == 'session_create':
                        result = backend.session_create(request['project'], request['operation_id'], request['context_mode'], request['provider_id'])
                    elif op == 'session_create_status':
                        result = backend.session_create_status(request['project'], request['operation_id'], request['context_mode'], request['provider_id'])
                    elif op == 'session_rename':
                        result = backend.session_rename(request['project'], request['sid'], request['operation_id'], request['title'])
                    elif op == 'session_rename_status':
                        result = backend.session_rename_status(request['project'], request['sid'], request['operation_id'])
                    else:
                        result = backend.session_send_status(request['project'], request['sid'], request['message_id'])
                    if op in ('session_create_options', 'session_create', 'session_create_status'):
                        result = configured_create_result(result, request['project'], request.get('operation_id'))
                    elif op == 'session_history':
                        result = history_result(result)
                    if op in ('session_rename', 'session_rename_status'):
                        result = rename_result(result, request['operation_id'])
                    reply(conn, result)
                except Exception:
                    try:
                        reply(conn, {'error': 'unavailable'})
                    except OSError:
                        pass
        finally:
            if request['op'] == 'session_live_snapshot':
                live_slot.release()
            elif request['op'] == 'devbus_overview':
                bus_slot.release()
            slots.release()
            with workers_lock:
                workers.discard(threading.current_thread())
    try:
        server.bind(socket_path)
        os.chmod(socket_path, 0o660)
        inode = os.lstat(socket_path).st_ino
        server.listen(8)
        server.settimeout(0.25)
        while stop_event is None or not stop_event.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            conn.settimeout(0.5)
            try:
                _, uid, _ = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != allowed_uid:
                    result = {'error': 'forbidden'}
                else:
                    request = _receive(conn)
                    live = type(request) is dict and request.get('op') == 'session_live_snapshot'
                    bus = type(request) is dict and request.get('op') == 'devbus_overview'
                    reservation = live_slot if live else bus_slot if bus else None
                    if (type(request) is not dict or type(request.get('op')) is not str
                            or request['op'] not in fields):
                        result = {'error': 'unsupported'}
                    elif (set(request) != fields[request['op']] and not (
                            request['op'] == 'session_send' and set(request) == fields[request['op']] | {'selection'})):
                        result = {'error': 'unavailable' if live or bus else 'invalid_request' if request['op'] == 'session_project_summary' else 'invalid_or_stale'}
                    elif request['op'] in SESSION_FIELDS and not _valid_session(request):
                        result = {'error': 'unavailable' if live else 'invalid_request'}
                    elif bus and not all(request[key] is None or valid_id(request[key]) for key in ('task', 'agent')):
                        result = {'error': 'unavailable'}
                    elif reservation is not None and not reservation.acquire(blocking=False):
                        result = {'error': 'busy'}
                    elif slots.acquire(blocking=False):
                        worker = None
                        try:
                            worker = threading.Thread(target=execute, args=(conn, request), daemon=True)
                            with workers_lock:
                                workers.add(worker)
                            worker.start()
                        except Exception:
                            with workers_lock:
                                workers.discard(worker)
                            slots.release()
                            if reservation is not None:
                                reservation.release()
                            raise
                        continue
                    else:
                        if reservation is not None:
                            reservation.release()
                        result = {'error': 'busy'}
                reply(conn, result)
            except Exception:
                try:
                    conn.sendall(b'{"error":"unavailable"}\n')
                except OSError:
                    pass
            conn.close()
    finally:
        server.close()
        # Active calls are bounded: task writers retain their existing 60s
        # deadline; session operations have one overall 55s deadline.
        deadline = time.monotonic() + 61
        with workers_lock:
            active = list(workers)
        for worker in active:
            worker.join(max(0, deadline - time.monotonic()))
        if 'inode' in locals() and os.path.lexists(socket_path) and os.lstat(socket_path).st_ino == inode:
            os.unlink(socket_path)


class SocketBackend:
    def __init__(self, socket_path):
        self.socket_path = socket_path

    def devbus_overview(self, task=None, agent=None):
        if not all(value is None or valid_id(value) for value in (task, agent)):
            return {'error': 'unavailable'}
        value = self._call(dict(op='devbus_overview', task=task, agent=agent), timeout=6)
        if value == {'error': 'invalid_or_stale'}:
            return {'error': 'unsupported'}
        return _devbus_private_result(value)

    def _call(self, request, timeout=65):
        try:
            wire = json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'
            if len(wire) > LIMIT:
                return {'error': 'invalid_or_stale'}
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                deadline = time.monotonic() + timeout if request.get('op') in ('session_live_snapshot', 'devbus_overview') else None
                conn.settimeout(timeout)
                conn.connect(self.socket_path)
                if deadline is not None:
                    conn.settimeout(max(.001, deadline-time.monotonic()))
                conn.sendall(wire)
                result = _receive(conn, deadline=deadline)
                return result if type(result) is dict else {'error': 'unavailable'}
        except (OSError, ValueError, TypeError):
            return {'error': 'unavailable'}

    def snapshot(self):
        return self._call({'op': 'snapshot'})

    def answer(self, agent, qid, decision, text):
        return self._call(dict(op='answer', agent=agent, qid=qid, decision=decision, text=text))

    def verdict(self, agent, generation, decision, comment):
        return self._call(dict(op='verdict', agent=agent, generation=generation, decision=decision, comment=comment))

    def _session(self, request):
        if not _valid_session(request):
            return {'error': 'invalid_request'}
        result = self._call(request)
        if request['op'] in ('session_create_options', 'session_create', 'session_create_status'):
            return configured_create_result(result, request['project'], request.get('operation_id'))
        if request['op'] == 'session_history':
            return history_result(result)
        return result

    def session_projects(self):
        return self._session({'op': 'session_projects'})

    def session_project_summary(self):
        return self._session({'op': 'session_project_summary'})

    def session_list(self, project, page):
        return self._session(dict(op='session_list', project=project, page=page))

    def session_history(self, project, sid, cursor):
        return self._session(dict(op='session_history', project=project, sid=sid, cursor=cursor))

    def session_live_snapshot(self, project, sid):
        from _control_web_live import owner_result
        request = dict(op='session_live_snapshot', project=project, sid=sid)
        if not _valid_session(request):
            return {'error': 'unavailable'}
        result = self._call(request, timeout=6)
        if result == {'error': 'invalid_or_stale'}:
            return {'error': 'unsupported'}
        return owner_result(result, private_errors=True)

    def session_models(self, project, sid):
        return self._session(dict(op='session_models', project=project, sid=sid))

    def session_send(self, project, sid, message_id, text, selection=None):
        return self._session(_send_request(project, sid, message_id, text, selection))

    def session_send_status(self, project, sid, message_id):
        return self._session(dict(op='session_send_status', project=project, sid=sid, message_id=message_id))

    def session_create_options(self, project):
        return self._session(dict(op='session_create_options', project=project))

    def session_create(self, project, operation_id, context_mode, provider_id):
        return self._session(dict(op='session_create', project=project, operation_id=operation_id,
                                  context_mode=context_mode, provider_id=provider_id))

    def session_create_status(self, project, operation_id, context_mode, provider_id):
        return self._session(dict(op='session_create_status', project=project, operation_id=operation_id,
                                  context_mode=context_mode, provider_id=provider_id))

    def session_rename(self, project, sid, operation_id, title):
        return self._session(dict(op='session_rename', project=project, sid=sid, operation_id=operation_id, title=title))

    def session_rename_status(self, project, sid, operation_id):
        return self._session(dict(op='session_rename_status', project=project, sid=sid, operation_id=operation_id))
