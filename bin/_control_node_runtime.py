"""Bounded owner-local ALP launch service; no executor or vendor auth access."""
import asyncio
import inspect
import json
import math
import os
from pathlib import Path
import stat
import threading
import time

from _control_node_tasks import _uuid
from _control_web_devbus import _timestamp

CONFIG_PATH = '/home/dwl/.config/ai-control/node-tasks.json'
CONFIG_ALIAS_DIR = '/home/dwl/.config/ai-control'
CONFIG_CANONICAL_DIR = '/data/.config/ai-control'
SERVICE_UID = 1000
BRIDGE_STATUS_PATH = '/home/dwl/.local/state/ai-control/devbus-bridge.json'
STORE_PATH = '/home/dwl/.local/state/ai-control/node-tasks/tasks.sqlite'
_LIMIT = 96 * 1024
_REASONS = {'disabled', 'invalid_config', 'profile_unverified', 'dependency_unavailable',
            'unavailable', 'observer_stale', 'retention_gap', 'invalid_event', 'id_conflict', 'storage', 'stopping'}
_ERRORS = {'invalid_request', 'conflict', 'capacity', 'storage', 'not_found', 'not_ready', 'unavailable', 'forbidden'}
_NODE = dict(node_id='alp', label='ALP', profile='codex-readonly-audit',
             workspace='/home/dwl/alp-ai-study/diagnostic-context', max_workers=1, timeout_seconds=900,
             capacity='unknown')
_SUMMARY = {'task_id', 'node_id', 'created_at', 'updated_at', 'delivery', 'execution',
            'coverage', 'quality', 'usage', 'result_available', 'prompt_preview', 'prompt_truncated'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def strict_json(raw, limit):
    if type(raw) is not bytes or len(raw) > limit:
        raise ValueError()
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


class _Config(dict):
    def __repr__(self):
        return '<private NodeTaskConfig>'


def _identity(info):
    return tuple(getattr(info, key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid',
                  'st_gid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def _read_private(directory, leaf, limit):
    fd = directory_fd = None
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        parent = os.fstat(directory_fd)
        if parent.st_uid != SERVICE_UID or stat.S_IMODE(parent.st_mode) != 0o700:
            raise ValueError()
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != SERVICE_UID
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1 or before.st_size > limit):
            raise ValueError()
        raw = bytearray()
        while len(raw) <= limit:
            block = os.read(fd, min(4096, limit + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        after = os.fstat(fd)
        current = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(current) or len(raw) != before.st_size:
            raise ValueError()
        return strict_json(bytes(raw), limit)
    finally:
        if fd is not None:
            os.close(fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _positive(value):
    return type(value) is int and 1 <= value <= 9223372036854775807


def valid_submit(request_id, node_id, prompt):
    try:
        return (_uuid(request_id) and node_id == 'alp' and type(prompt) is str
                and '\0' not in prompt and 1 <= len(prompt.encode('utf-8')) <= 32768)
    except UnicodeError:
        return False


def _config(value):
    if (type(value) is not dict or set(value) != {'schema', 'enabled', 'profile_attested', 'publisher', 'sink',
            'origin_stream_created', 'bridge_consumer_created'} or type(value['schema']) is not int
            or value['schema'] != 1 or type(value['enabled']) is not bool or type(value['profile_attested']) is not bool):
        raise ValueError()
    for key in ('origin_stream_created', 'bridge_consumer_created'):
        if _timestamp(value[key])[0] is None:
            raise ValueError()
    for role, user, port in (('publisher', 'control_alp_publisher', 4222), ('sink', 'control_task_sink', 24222)):
        part = value[role]
        fields = {'url', 'user', 'password'} | ({'stream_created', 'consumer_created', 'cutoff_sequence'} if role == 'sink' else set())
        if (type(part) is not dict or set(part) != fields or part['url'] != 'nats://127.0.0.1:' + str(port)
                or part['user'] != user or type(part['password']) is not str
                or not 1 <= len(part['password'].encode('utf-8')) <= 8192
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in part['password'])):
            raise ValueError()
        if role == 'sink' and (any(_timestamp(part[key])[0] is None for key in ('stream_created', 'consumer_created'))
                or type(part['cutoff_sequence']) is not int or not 0 <= part['cutoff_sequence'] < 9223372036854775807):
            raise ValueError()
    return _Config(value)


def load_node_tasks_config():
    pointer = os.environ.get('CONTROL_NODE_TASKS_CONFIG')
    if pointer is None:
        return None, 'disabled'
    if pointer != str(CONFIG_PATH) or os.geteuid() != SERVICE_UID:
        return None, 'invalid_config'
    try:
        info = os.lstat(CONFIG_ALIAS_DIR)
        if (not stat.S_ISLNK(info.st_mode) or info.st_uid != SERVICE_UID
                or os.readlink(CONFIG_ALIAS_DIR) != str(CONFIG_CANONICAL_DIR)):
            raise ValueError()
        value = _read_private(CONFIG_CANONICAL_DIR, Path(CONFIG_PATH).name, 16384)
        if _identity(info) != _identity(os.lstat(CONFIG_ALIAS_DIR)):
            raise ValueError()
        return _config(value), None
    except FileNotFoundError:
        return None, 'disabled'
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return None, 'invalid_config'


def load_bridge_status():
    try:
        path = Path(BRIDGE_STATUS_PATH)
        return _read_private(str(path.parent), path.name, 4096)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return None


def _preview(prompt):
    raw = prompt.encode('utf-8')
    return raw[:256].decode('utf-8', errors='ignore'), len(raw) > 256


def _detail(row):
    result = {k: v for k, v in row.items() if k != 'prompt'}
    result['prompt_preview'], result['prompt_truncated'] = _preview(row['prompt'])
    return result


def _summary(row):
    result = _detail(row)
    result.pop('schema')
    result['result_available'] = result.pop('result') is not None
    return result


def node_result(value, kind, task_id=None):
    """Validate every public DTO before either owner boundary, without raw errors."""
    try:
        if type(value) is not dict or len(encoded(value)) > _LIMIT:
            raise ValueError()
        if set(value) == {'error'} and type(value['error']) is str and value['error'] in _ERRORS:
            return value
        def task(row, detail=False):
            expected = (_SUMMARY - {'result_available'}) | {'schema', 'result'} if detail else _SUMMARY
            if (type(row) is not dict or set(row) != expected or not _uuid(row['task_id'])
                    or row['node_id'] != 'alp' or any(_timestamp(row[k])[0] is None for k in ('created_at', 'updated_at'))
                    or row['delivery'] not in ('pending', 'published', 'unknown')
                    or row['execution'] not in ('waiting', 'accepted', 'running', 'completed', 'failed', 'needs_attention')
                    or row['coverage'] not in ('complete', 'partial') or row['quality'] != 'unreviewed' or row['usage'] is not None
                    or type(row['prompt_preview']) is not str or len(row['prompt_preview'].encode('utf-8')) > 256
                    or type(row['prompt_truncated']) is not bool):
                raise ValueError()
            if detail:
                if type(row['schema']) is not int or row['schema'] != 1:
                    raise ValueError()
                result = row['result']
                if result is not None and (type(result) is not dict
                        or set(result) not in ({'text', 'executor'}, {'text', 'executor', 'output_truncated'})
                        or type(result['text']) is not str or result['executor'] != 'codex'
                        or 'output_truncated' in result and type(result['output_truncated']) is not bool
                        or len(encoded(result)) > 60000):
                    raise ValueError()
            elif type(row['result_available']) is not bool:
                raise ValueError()
        if kind == 'overview':
            if (set(value) != {'schema', 'node', 'tasks', 'tasks_truncated', 'budget_trimmed', 'usage'}
                    or type(value['schema']) is not int or value['schema'] != 1 or value['usage'] is not None
                    or type(value['tasks']) is not list or len(value['tasks']) > 50
                    or type(value['tasks_truncated']) is not bool or type(value['budget_trimmed']) is not bool):
                raise ValueError()
            node = value['node']
            if (type(node) is not dict or set(node) != set(_NODE) | {'readiness', 'reason', 'heartbeat'}
                    or any(type(node[k]) is not type(v) or node[k] != v for k, v in _NODE.items())
                    or node['readiness'] not in ('ready', 'blocked', 'disabled')
                    or node['heartbeat'] not in ('fresh', 'stale', 'unknown')
                    or node['reason'] is not None and node['reason'] not in _REASONS
                    or (node['reason'] is None) != (node['readiness'] == 'ready')):
                raise ValueError()
            for row in value['tasks']:
                task(row)
        elif kind == 'get':
            task(value, True)
            if value['task_id'] != task_id:
                raise ValueError()
        elif kind == 'submit':
            if set(value) != {'schema', 'task'} or type(value['schema']) is not int or value['schema'] != 1:
                raise ValueError()
            task(value['task'])
            if value['task']['task_id'] != task_id:
                raise ValueError()
        else:
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        return {'error': 'unavailable'}


_V2_EXTRA = {'execution_profile_id', 'attempt_id', 'binding',
             'session_verification', 'observed_session_uuid', 'native_model', 'effort_state'}


def node_result_v2(value, kind, task_id=None):
    """Validate the public v2 boundary without assembling or repairing data."""
    try:
        from _control_node_protocol import _identifier, validate_binding_v2, validate_result_v2
        if type(value) is not dict or len(encoded(value)) > _LIMIT:
            raise ValueError()
        if set(value) == {'error'}:
            if value['error'] not in _ERRORS or type(value['error']) is not str:
                raise ValueError()
            return value
        def task(row, detail=False):
            expected = ((_SUMMARY - {'result_available'}) | {'schema', 'result'}
                        if detail else _SUMMARY) | _V2_EXTRA
            if type(row) is not dict or set(row) != expected:
                raise ValueError()
            binding = validate_binding_v2(row['binding'])
            if (row['task_id'] != binding['task_id']
                    or row['node_id'] != binding['node_id']
                    or row['attempt_id'] != binding['attempt_id']
                    or row['execution_profile_id'] != binding['execution_profile_id']
                    or row['session_verification'] not in ('pending', 'verified', 'unknown')
                    or row['effort_state'] != 'requested_unverified'
                    or row['native_model'] is not None and not _identifier(row['native_model'])
                    or row['observed_session_uuid'] is not None and not _uuid(row['observed_session_uuid'])
                    or row['session_verification'] == 'verified'
                    and row['observed_session_uuid'] != binding['requested_session_uuid']):
                raise ValueError()
            old = {k: v for k, v in row.items() if k not in _V2_EXTRA}
            if old.get('execution') == 'waiting_slot':
                old['execution'] = 'waiting'
            if detail:
                if type(old['schema']) is not int or old['schema'] != 2:
                    raise ValueError()
                if old['result'] is not None:
                    validate_result_v2(old['result'])
                old.update(schema=1, result=None)
            if detail and 'error' in node_result(old, 'get', row['task_id']):
                raise ValueError()
            if not detail:
                if 'error' in node_result({'schema': 1, 'task': old}, 'submit', row['task_id']):
                    raise ValueError()
        if kind == 'get':
            task(value, True)
            if task_id is not None and value['task_id'] != task_id:
                raise ValueError()
        elif kind == 'submit':
            if set(value) != {'schema', 'task'} or type(value['schema']) is not int or value['schema'] != 2:
                raise ValueError()
            task(value['task'])
            if task_id is not None and value['task']['task_id'] != task_id:
                raise ValueError()
        elif kind == 'overview':
            if (set(value) != {'schema', 'node', 'tasks', 'tasks_truncated', 'budget_trimmed', 'usage'}
                    or type(value['schema']) is not int or value['schema'] != 2
                    or type(value['tasks']) is not list or len(value['tasks']) > 50):
                raise ValueError()
            for row in value['tasks']:
                task(row)
            old = dict(value, schema=1, tasks=[])
            if 'error' in node_result(old, 'overview'):
                raise ValueError()
        else:
            raise ValueError()
        return value
    except (ImportError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        return {'error': 'unavailable'}


class NodeTaskRuntime:
    def __init__(self, store, *, config_loader=load_node_tasks_config, nats_factory=None,
                 observer_snapshot=None, bridge_status=None, clock=time.time, monotonic=time.monotonic,
                 profile_resolver=None):
        self.store, self._loader, self._factory = store, config_loader, nats_factory
        self._profile_resolver = profile_resolver
        self._observer = observer_snapshot or (lambda: {})
        self._bridge = bridge_status or load_bridge_status
        self._clock, self._monotonic = clock, monotonic
        self._config, self._reason = self._loader()
        self._connections = []
        self._publisher = self._sink = self._sub = None
        self._metadata_ok = False
        self._step_lock = asyncio.Lock()
        self._rpc_lock = threading.RLock()
        self._wake = asyncio.Event()
        self._worker = self._loop = None
        self._stopping = False
        self._retry_at = 0
        self._delay = 1
        self._io_tasks = set()
        self._observer_cache, self._bridge_cache = {}, None
        self._owner_loop = None

    async def _io(self, awaitable, timeout=3):
        # asyncio.wait has a real deadline even when a broken SDK swallows cancel.
        task = asyncio.ensure_future(awaitable)
        self._io_tasks.add(task)
        def finished(done):
            self._io_tasks.discard(done)
            if not done.cancelled():
                done.exception()  # Consume abandoned SDK failures without exposing raw errors.
        task.add_done_callback(finished)
        try:
            done, _ = await asyncio.wait({task}, timeout=timeout)
            if not done:
                task.cancel()
                raise asyncio.TimeoutError()
            return task.result()
        except asyncio.CancelledError:
            task.cancel()
            raise

    def _health(self):
        # Projection access belongs to its owner loop. Broker threads read only
        # the last bounded snapshot; do not call a cross-thread future here.
        try:
            if asyncio.get_running_loop() is self._owner_loop:
                self._observer_cache = self._observer()
                self._bridge_cache = self._bridge()
        except RuntimeError:
            pass
        except Exception:
            self._observer_cache, self._bridge_cache = {}, None
        heartbeat = 'unknown'
        try:
            snapshot = self._observer_cache
            for agent in snapshot.get('agents', []):
                if agent.get('agent') == 'codex-ai-dev-1':
                    at = _timestamp(agent.get('heartbeat_at'))[1]
                    heartbeat = 'fresh' if (agent.get('heartbeat_status') == 'fresh'
                        and at is not None and -5 <= self._clock() - at <= 45
                        and snapshot.get('connection', {}).get('state') == 'live') else 'stale'
        except Exception:
            pass
        if self._stopping:
            return 'stopping', heartbeat
        if self._reason in ('invalid_config', 'dependency_unavailable', 'storage'):
            return self._reason, heartbeat
        if self._config is None or not self._config.get('enabled'):
            return 'disabled', heartbeat
        if not self._config.get('profile_attested'):
            return 'profile_unverified', heartbeat
        state = self.store.runtime_state() if self.store else {'error': 'storage'}
        if 'error' in state:
            return 'storage', heartbeat
        if state['fence']:
            return state['fence'], heartbeat
        try:
            bridge = self._bridge_cache
            fields = {'schema', 'state', 'observed_at', 'source_stream_created', 'consumer_created', 'ack_floor', 'first_seq', 'pending', 'reason'}
            if type(bridge) is not dict or set(bridge) != fields or type(bridge['schema']) is not int or bridge['schema'] != 1:
                raise ValueError()
            at = _timestamp(bridge['observed_at'])[1]
            if at is None or not -5 <= self._clock() - at <= 30:
                raise ValueError()
            if any(bridge[k] is not None and (type(bridge[k]) is not int or bridge[k] < 0) for k in ('ack_floor', 'first_seq', 'pending')):
                raise ValueError()
            if (bridge['source_stream_created'] != self._config['origin_stream_created']
                    or bridge['consumer_created'] != self._config['bridge_consumer_created']):
                return 'retention_gap', heartbeat
            if bridge['reason'] in ('retention_gap', 'invalid_event', 'id_conflict'):
                return bridge['reason'], heartbeat
            if bridge['state'] != 'live' or bridge['reason'] is not None:
                raise ValueError()
        except Exception:
            return 'unavailable', heartbeat
        if heartbeat != 'fresh':
            return 'observer_stale', heartbeat
        if self._reason == 'storage':
            return 'storage', heartbeat
        if not self._metadata_ok or len(self._connections) != 2 or any(not c.is_connected for c in self._connections):
            return 'unavailable', heartbeat
        return None, heartbeat

    def overview(self):
        with self._rpc_lock:
            reason, heartbeat = self._health()
            if reason == 'storage' and self.store is not None:
                return {'error': 'storage'}
            rows = self.store.recent(schema=1) if self.store else []
            if type(rows) is not list:
                return {'error': 'storage'}
            count = self.store.count(schema=1) if self.store else {'total': 0}
            if 'error' in count:
                return {'error': 'storage'}
            node = dict(_NODE, readiness='disabled' if reason == 'disabled' else 'blocked' if reason else 'ready',
                        reason=reason, heartbeat=heartbeat)
            result = dict(schema=1, node=node, tasks=[_summary(row) for row in rows],
                          tasks_truncated=count['total'] > len(rows), budget_trimmed=False, usage=None)
            while len(encoded(result)) > _LIMIT and result['tasks']:
                result['tasks'].pop()
                result.update(tasks_truncated=True, budget_trimmed=True)
            return node_result(result, 'overview')

    def task(self, task_id):
        if not _uuid(task_id):
            return {'error': 'invalid_request'}
        row = self.store.get(task_id) if self.store else {'error': 'not_found'}
        return row if 'error' in row else node_result(_detail(row), 'get', task_id)

    def submit(self, request_id, node_id, prompt):
        if not valid_submit(request_id, node_id, prompt):
            return {'error': 'invalid_request'}
        with self._rpc_lock:
            if self._stopping:
                return {'error': 'not_ready'}
            row = self.store.get(request_id) if self.store else {'error': 'not_found'}
            if row.get('error') == 'storage':
                return row
            if 'error' in row and self._health()[0] is not None:
                return {'error': 'not_ready'}
            row = self.store.submit(request_id, node_id, prompt)
            if 'error' in row:
                return row
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._wake.set)
            return node_result(dict(schema=1, task=_summary(row)), 'submit', request_id)


    def overview_v2(self):
        with self._rpc_lock:
            reason, heartbeat = self._health()
            rows = self.store.recent(schema=2) if self.store else []
            if type(rows) is not list:
                return {'error': 'storage'}
            count = self.store.count(schema=2) if self.store else {'total': 0}
            if 'error' in count:
                return {'error': 'storage'}
            if self._profile_resolver is None and reason is None:
                reason = 'profile_unverified'
            node = dict(_NODE, readiness='disabled' if reason == 'disabled' else 'blocked' if reason else 'ready',
                        reason=reason, heartbeat=heartbeat)
            result = dict(schema=2, node=node, tasks=[_summary(row) for row in rows],
                          tasks_truncated=count['total'] > len(rows), budget_trimmed=False, usage=None)
            while len(encoded(result)) > _LIMIT and result['tasks']:
                result['tasks'].pop()
                result.update(tasks_truncated=True, budget_trimmed=True)
            return node_result_v2(result, 'overview')

    def task_v2(self, task_id):
        if not _uuid(task_id):
            return {'error': 'invalid_request'}
        row = self.store.get(task_id) if self.store else {'error': 'not_found'}
        if 'error' in row:
            return row
        if row.get('schema') != 2:
            return {'error': 'not_found'}
        return node_result_v2(_detail(row), 'get', task_id)

    def submit_v2(self, request):
        from _control_node_protocol import validate_submit_v2, validate_profile_snapshot_v2
        try:
            validate_submit_v2(request)
        except (ValueError, TypeError, UnicodeError):
            return {'error': 'invalid_request'}
        with self._rpc_lock:
            if self._stopping or self.store is None:
                return {'error': 'not_ready'}
            if self._profile_resolver is None:
                return {'error': 'not_ready'}
            try:
                profile = self._profile_resolver(request['execution_profile_id'])
                validate_profile_snapshot_v2(profile)
            except (ValueError, TypeError, KeyError, OSError, UnicodeError):
                return {'error': 'not_ready'}
            # The resolver is trusted constructor DI. The installed default is
            # absent until a separately reviewed live profile is configured.
            if profile['account_attestation']['status'] != 'verified':
                return {'error': 'not_ready'}
            row = self.store.submit_v2(request, profile)
            if 'error' in row:
                return row
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._wake.set)
            return node_result_v2(dict(schema=2, task=_summary(row)), 'submit', request['request_id'])

    async def _connect(self):
        if self._connections:
            return
        factory = self._factory
        if factory is None:
            try:
                import nats
                factory = nats.connect
            except ImportError:
                self._reason = 'dependency_unavailable'
                return
        async def quiet(*args):
            self._metadata_ok = False
        for role in ('publisher', 'sink'):
            cfg = self._config[role]
            connection = await self._io(factory(servers=[cfg['url']], user=cfg['user'], password=cfg['password'],
                inbox_prefix=('_INBOX.' + cfg['user']).encode(), connect_timeout=2,
                allow_reconnect=False, error_cb=quiet, disconnected_cb=quiet))
            self._connections.append(connection)
            if role == 'publisher':
                self._publisher = connection.jetstream(timeout=2)
            else:
                self._sink = connection.jetstream(timeout=2)
        await self._metadata()
        self._sub = await self._io(self._sink.pull_subscribe_bind(stream='OBS_EVENTS', consumer='CONTROL_TASK_LEDGER',
            inbox_prefix=b'_INBOX.control_task_sink.', pending_msgs_limit=1, pending_bytes_limit=126 * 1024))

    async def _metadata(self):
        self._metadata_ok = False
        nc = self._connections[1]
        async def info(subject):
            response = await self._io(nc.request(subject, b'', timeout=2))
            doc = strict_json(response.data, 65536)
            if type(doc) is not dict or 'error' in doc:
                raise ValueError()
            return doc
        stream = await info('$JS.API.STREAM.INFO.OBS_EVENTS')
        consumer = await info('$JS.API.CONSUMER.INFO.OBS_EVENTS.CONTROL_TASK_LEDGER')
        cfg = self._config['sink']
        if stream.get('created') != cfg['stream_created'] or consumer.get('created') != cfg['consumer_created']:
            self._fence('retention_gap')
            raise ValueError()
        sc, cc = stream['config'], consumer['config']
        floor, first = consumer['ack_floor']['stream_seq'], stream['state']['first_seq']
        if (sc.get('name') != 'OBS_EVENTS' or sc.get('storage') != 'file'
                or cc.get('durable_name') != 'CONTROL_TASK_LEDGER' or cc.get('filter_subject') != 'devbus.events.codex-ai-dev-1'
                or cc.get('ack_policy') != 'explicit' or type(cc.get('ack_wait')) is not int or cc['ack_wait'] != 30000000000
                or type(cc.get('max_ack_pending')) is not int or cc['max_ack_pending'] != 1
                or cc.get('deliver_policy') != 'by_start_sequence' or type(cc.get('opt_start_seq')) is not int
                or cc['opt_start_seq'] != cfg['cutoff_sequence'] + 1
                or type(cc.get('inactive_threshold', 0)) is not int or cc.get('inactive_threshold', 0) != 0
                or cc.get('deliver_subject') not in (None, '') or cc.get('filter_subjects') not in (None, [])
                or type(floor) is not int or not 0 <= floor <= 9223372036854775807
                or type(first) is not int or not 0 <= first <= 9223372036854775807):
            raise ValueError()
        if first > max(cfg['cutoff_sequence'], floor) + 1:
            self._fence('retention_gap')
            raise ValueError()
        self._metadata_ok = True

    def _fence(self, reason):
        result = self.store.mark_gap(reason=reason)
        self._reason = 'storage' if 'error' in result else reason
        return 'error' not in result

    async def _disconnect(self):
        self._metadata_ok = False
        okay = True
        for connection in list(self._connections):
            try:
                await self._io(connection.close(), 1)
            except (Exception, asyncio.CancelledError):
                okay = False
            else:
                self._connections.remove(connection)
        if not self._connections:
            self._publisher = self._sink = self._sub = None
        return okay

    async def step(self):
        async with self._step_lock:
            self._owner_loop = asyncio.get_running_loop()
            if self._stopping or any(not task.done() for task in self._io_tasks):
                return
            try:
                self._observer_cache = self._observer()
                self._bridge_cache = self._bridge()
            except Exception:
                self._observer_cache, self._bridge_cache = {}, None
            self._config, loaded_reason = self._loader()
            self._reason = loaded_reason
            reason, _ = self._health()
            if reason in ('retention_gap', 'invalid_event', 'id_conflict'):
                self._fence(reason)
                return
            if reason in ('disabled', 'invalid_config', 'profile_unverified', 'storage', 'dependency_unavailable'):
                return
            if self._monotonic() < self._retry_at:
                return
            try:
                await self._connect()
                if self._reason == 'dependency_unavailable':
                    return
                await self._metadata()
                messages = []
                try:
                    messages = await self._io(self._sub.fetch(batch=1, timeout=.25), .5)
                except asyncio.TimeoutError:
                    if any(not task.done() for task in self._io_tasks):
                        raise  # A fetch ignoring cancellation must not overlap another tick.
                for message in messages:
                    metadata = message.metadata
                    if (message.subject != 'devbus.events.codex-ai-dev-1' or type(message.data) is not bytes
                            or len(message.data) > 126 * 1024 or metadata.stream != 'OBS_EVENTS'
                            or metadata.consumer != 'CONTROL_TASK_LEDGER' or not _positive(metadata.sequence.stream)
                            or not _positive(metadata.sequence.consumer)):
                        self._fence('invalid_event')
                        return
                    applied = self.store.ingest(message.data)
                    if 'error' in applied:
                        self._reason = 'storage'
                        return
                    if applied['outcome'] in ('invalid', 'conflict'):
                        if not self._fence('invalid_event' if applied['outcome'] == 'invalid' else 'id_conflict'):
                            return
                    await self._metadata()
                    await self._io(message.ack_sync(timeout=2))
                reason, _ = self._health()
                if reason in ('retention_gap', 'invalid_event', 'id_conflict'):
                    self._fence(reason)
                    return
                if reason is not None:
                    return
                rows = self.store.pending(1)
                if type(rows) is not list:
                    self._reason = 'storage'
                    return
                if rows:
                    row = rows[0]
                    started = self.store.publication_started(row['task_id'])
                    if 'error' in started:
                        self._reason = 'storage'
                        return
                    if started.get('publish'):
                        try:
                            ack = await self._io(self._publisher.publish('devbus.commands.codex-ai-dev-1', row['wire'],
                                headers={'Nats-Msg-Id': row['message_id']}, timeout=2))
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            if 'error' in self.store.publish_failed(row['task_id']):
                                self._reason = 'storage'
                            raise
                        if ack.stream != 'DEVBUS_V1' or not _positive(ack.seq):
                            if 'error' in self.store.publish_failed(row['task_id']):
                                self._reason = 'storage'
                            return
                        if 'error' in self.store.publication(row['task_id'], row['message_id'], row['wire_sha256'], ack.seq):
                            self._reason = 'storage'
                            return
                self._delay = 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self._metadata_ok = False
                self._retry_at = self._monotonic() + self._delay
                self._delay = min(self._delay * 2, 30)
                if not self._io_tasks:
                    await self._disconnect()

    async def start(self):
        if self._stopping or self._worker is not None:
            return
        self._loop = asyncio.get_running_loop()
        async def worker():
            while not self._stopping:
                await self.step()
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), 1)
                except asyncio.TimeoutError:
                    pass
        self._worker = asyncio.create_task(worker())

    async def stop(self):
        self._stopping = True
        self._wake.set()
        tasks = set(self._io_tasks)
        if self._worker and not self._worker.done():
            tasks.add(self._worker)
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=3)
            if pending:
                return {'stopped': False}
        if not await self._disconnect():
            return {'stopped': False}
        return {'stopped': True}
