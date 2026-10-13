"""Independent runtime RED from launch-runtime spec; no implementation read.

All identities and passwords below are synthetic. Fake NATS has no socket,
credentials, admin methods, SSH, HTTP or inference. Real private SQLite proves
commit visibility through a second reader before network callbacks.
"""
import asyncio
import copy
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

import test_control_node_tasks_ledger_red as ledger

EPOCH = '2026-10-06T13:02:50.157073Z'
CONSUMER_EPOCH = '2026-10-13T00:00:00Z'
NOW = ledger.NOW


def stamp(value=NOW):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def config():
    return dict(schema=1, enabled=True, profile_attested=True,
                publisher=dict(url='nats://127.0.0.1:4222',
                               user='control_alp_publisher', password='synthetic-publisher-only'),
                sink=dict(url='nats://127.0.0.1:24222', user='control_task_sink',
                          password='synthetic-sink-only', stream_created=EPOCH,
                          consumer_created=CONSUMER_EPOCH, cutoff_sequence=0),
                origin_stream_created=EPOCH, bridge_consumer_created=CONSUMER_EPOCH)


def module(case):
    case.assertIsNotNone(importlib.util.find_spec('_control_node_runtime'),
                         'INV-NRUN-01 planned bin/_control_node_runtime.py absent')
    return importlib.import_module('_control_node_runtime')


class ConfigRED(unittest.TestCase):
    def setUp(self):
        self.api = module(self)
        self.tmp = tempfile.TemporaryDirectory(prefix='node-config-red-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.canonical = self.root / 'canonical'
        self.canonical.mkdir(mode=0o700)
        self.alias = self.root / 'alias'
        self.alias.symlink_to(self.canonical, target_is_directory=True)
        self.leaf = self.canonical / 'node-tasks.json'
        self.pointer = str(self.alias / 'node-tasks.json')
        # Python-only test constants; never an accepted config/HTTP parameter.
        self.constants = patch.multiple(self.api, CONFIG_PATH=self.pointer,
            CONFIG_ALIAS_DIR=str(self.alias), CONFIG_CANONICAL_DIR=str(self.canonical),
            SERVICE_UID=os.getuid())
        self.constants.start()
        self.addCleanup(self.constants.stop)
        self.env = patch.dict(os.environ, {'CONTROL_NODE_TASKS_CONFIG': self.pointer})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.write(config())

    def write(self, doc):
        self.leaf.write_bytes(json.dumps(doc).encode('utf-8'))
        self.leaf.chmod(0o600)

    def invalid(self):
        result, reason = self.api.load_node_tasks_config()
        self.assertIsNone(result)
        self.assertEqual(reason, 'invalid_config')
        self.assertNotIn('synthetic-publisher-only', repr((result, reason)))
        self.assertNotIn('synthetic-sink-only', repr((result, reason)))

    def test_fixed_alias_valid_missing_pointer_and_wrong_pointer(self):
        # INV-NRUN-02.
        loaded, reason = self.api.load_node_tasks_config()
        self.assertIsNone(reason)
        self.assertTrue(loaded['enabled'])
        self.assertNotIn('synthetic-publisher-only', repr(loaded))
        self.assertNotIn('synthetic-sink-only', repr(loaded))
        with patch.dict(os.environ, {'CONTROL_NODE_TASKS_CONFIG': self.pointer + '.other'}):
            self.invalid()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.api.load_node_tasks_config(), (None, 'disabled'))
        self.leaf.unlink()
        self.assertEqual(self.api.load_node_tasks_config(), (None, 'disabled'))

    def test_strict_json_exact_keys_types_roles_and_password_bounds(self):
        # INV-NRUN-02: role/port swaps and permissive JSON cannot be admitted.
        changes = [('schema', True), ('enabled', 1), ('profile_attested', 'true'),
                   ('origin_stream_created', '2026-10-06T00:00:00'),
                   ('bridge_consumer_created', 'garbage'), ('extra', True)]
        for key, value in changes:
            with self.subTest(field=key):
                doc = config(); doc[key] = value
                self.write(doc); self.invalid()
        for role in ('publisher', 'sink'):
            for key, value in [('url', 'nats://localhost:4222'),
                    ('url', 'nats://127.0.0.1:4222?x=1'),
                    ('user', 'control_task_sink' if role == 'publisher' else 'control_alp_publisher'),
                    ('password', ''), ('password', 'x' * 8193), ('password', '\n'),
                    ('password', '\ud800'), ('token', 'synthetic-only')]:
                with self.subTest(role=role, field=key, variant=len(str(value))):
                    doc = config(); doc[role][key] = value
                    self.write(doc); self.invalid()
        for value in (True, -1, 1.5):
            doc = config(); doc['sink']['cutoff_sequence'] = value
            self.write(doc); self.invalid()
        good = json.dumps(config()).encode()
        for raw in (good.replace(b'"schema": 1', b'"schema": 1,"schema": 1'),
                    good.replace(b'"cutoff_sequence": 0', b'"cutoff_sequence": NaN'),
                    b'\xff', b' ' * 16385):
            self.leaf.write_bytes(raw); self.invalid()

    def test_filesystem_uid_mode_links_and_alias_target_fail_closed(self):
        # INV-NRUN-02: no arbitrary paths or symlink leaf escape.
        for mode in (0o644, 0o660):
            self.leaf.chmod(mode); self.invalid()
        self.leaf.chmod(0o600)
        with patch.object(self.api, 'SERVICE_UID', os.getuid() + 1):
            self.invalid()
        hard = self.root / 'hard'; os.link(self.leaf, hard)
        self.invalid(); hard.unlink()
        saved = self.root / 'saved'; self.leaf.rename(saved)
        self.leaf.symlink_to(saved); self.invalid()
        self.leaf.unlink(); saved.rename(self.leaf)
        self.canonical.chmod(0o750); self.invalid(); self.canonical.chmod(0o700)
        self.alias.unlink(); self.alias.symlink_to(self.root, target_is_directory=True)
        self.invalid()


class StoreProxy:
    """Public-contract interception, no access to store implementation fields."""
    def __init__(self, store):
        self.store = store
        self.fail = set()
        self.calls = []

    def __getattr__(self, name):
        target = getattr(self.store, name)
        if not callable(target):
            return target
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in self.fail:
                return {'error': 'storage'}
            return target(*args, **kwargs)
        return call


class Message:
    def __init__(self, data, sequence=1, subject='devbus.events.codex-ai-dev-1'):
        self.data, self.subject = data, subject
        self.metadata = NS(stream='OBS_EVENTS', consumer='CONTROL_TASK_LEDGER',
                           sequence=NS(stream=sequence, consumer=1))
        self.acks = 0
        self.on_ack = lambda: None
        self.ack_error = None

    async def ack_sync(self, timeout=2):
        self.on_ack()
        if self.ack_error:
            raise self.ack_error
        self.acks += 1


class FakeNATS:
    def __init__(self, owner, role):
        self.owner, self.role = owner, role
        self.closed = 0
        self.is_connected = True
        self.is_closed = False

    def jetstream(self, **kwargs):
        return self

    async def stream_info(self, stream, **kwargs):
        self.owner.assert_sink(self.role)
        if stream != 'OBS_EVENTS':
            raise AssertionError('publisher must not acquire stream-info ACL')
        return NS(created=self.owner.stream_epoch,
                  config=NS(name='OBS_EVENTS', storage='file'),
                  state=NS(first_seq=self.owner.first_seq, last_seq=100))

    async def consumer_info(self, stream, consumer, **kwargs):
        self.owner.assert_sink(self.role)
        assert (stream, consumer) == ('OBS_EVENTS', 'CONTROL_TASK_LEDGER')
        return NS(created=self.owner.consumer_epoch,
                  config=NS(durable_name=consumer, filter_subject=self.owner.filter,
                            ack_policy='explicit', ack_wait=30.0, max_ack_pending=1,
                            deliver_policy='by_start_sequence', opt_start_seq=1,
                            inactive_threshold=0),
                  ack_floor=NS(stream_seq=self.owner.ack_floor, consumer_seq=0))

    async def request(self, subject, payload=b'', timeout=2):
        self.owner.assert_sink(self.role)
        assert payload == b'' and timeout <= 2
        if subject == '$JS.API.STREAM.INFO.OBS_EVENTS':
            doc = dict(created=self.owner.stream_epoch,
                       config=dict(name='OBS_EVENTS', storage='file'),
                       state=dict(first_seq=self.owner.first_seq, last_seq=100))
        elif subject == '$JS.API.CONSUMER.INFO.OBS_EVENTS.CONTROL_TASK_LEDGER':
            doc = dict(created=self.owner.consumer_epoch,
                       config=dict(durable_name='CONTROL_TASK_LEDGER',
                           filter_subject=self.owner.filter, ack_policy='explicit',
                           ack_wait=30000000000, max_ack_pending=1,
                           deliver_policy='by_start_sequence', opt_start_seq=1,
                           inactive_threshold=0),
                       ack_floor=dict(stream_seq=self.owner.ack_floor, consumer_seq=0))
        else:
            raise AssertionError('unexpected raw API subject: ' + subject)
        return NS(data=json.dumps(doc).encode())

    async def pull_subscribe_bind(self, *args, **kwargs):
        self.owner.assert_sink(self.role)
        self.owner.binds.append((args, kwargs))
        self.owner.case.assertIn('CONTROL_TASK_LEDGER', str((args, kwargs)))
        self.owner.case.assertIn('OBS_EVENTS', str((args, kwargs)))
        return self

    async def fetch(self, batch=1, timeout=.25, **kwargs):
        self.owner.assert_sink(self.role)
        assert batch == 1 and timeout <= .25
        self.owner.fetches += 1
        if self.owner.fetch_gate is not None:
            self.owner.fetch_entered.set()
            while not self.owner.fetch_gate.is_set():
                try:
                    await self.owner.fetch_gate.wait()
                except asyncio.CancelledError:
                    if not self.owner.stubborn_fetch:
                        raise
        if self.owner.messages:
            return [self.owner.messages.pop(0)]
        return []

    async def publish(self, subject, data, headers=None, timeout=2, **kwargs):
        assert self.role == 'control_alp_publisher'
        self.owner.on_publish(subject, data, headers, timeout)
        self.owner.publishes.append((subject, data, headers))
        if self.owner.publish_error:
            raise self.owner.publish_error
        return self.owner.puback

    async def close(self):
        self.closed += 1
        self.is_connected = False
        self.is_closed = True


class Transport:
    def __init__(self, case):
        self.case = case
        self.connections, self.connect_kwargs, self.binds = [], [], []
        self.messages, self.publishes = [], []
        self.fetches = 0
        self.stream_epoch, self.consumer_epoch = EPOCH, CONSUMER_EPOCH
        self.first_seq, self.ack_floor = 1, 0
        self.filter = 'devbus.events.codex-ai-dev-1'
        self.puback = NS(stream='DEVBUS_V1', seq=11, duplicate=False)
        self.publish_error = None
        self.fetch_gate = None
        self.fetch_entered = asyncio.Event()
        self.stubborn_fetch = False
        self.on_publish = lambda *args: None

    def assert_sink(self, role):
        self.case.assertEqual(role, 'control_task_sink')

    async def connect(self, **kwargs):
        self.connect_kwargs.append(kwargs)
        connection = FakeNATS(self, kwargs.get('user'))
        self.connections.append(connection)
        return connection

class RuntimeRED(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        runtime_api = module(self)
        ledger.LedgerRED.setUp(self)
        self.proxy = StoreProxy(self.store)
        self.transport = Transport(self)
        self.settings = config()
        self.reason = None
        self.bridge = dict(schema=1, state='live', observed_at=stamp(),
            source_stream_created=EPOCH, consumer_created=CONSUMER_EPOCH,
            ack_floor=0, first_seq=1, pending=0, reason=None)
        self.observer = dict(schema=1, connection=dict(state='live', reason=None),
            coverage=dict(mode='window', first_seq=1, last_seq=100, ttl_seconds=86400,
                          max_bytes=104857600, replay_complete=True, truncated=False, issues=[]),
            tasks=[], events=[], agents=[dict(agent='codex-ai-dev-1', registered=True,
                capabilities=[], executor='codex', version='v1', heartbeat_at=stamp(),
                heartbeat_status='fresh')])
        self.runtime = runtime_api.NodeTaskRuntime(self.proxy,
            config_loader=lambda: (self.settings, self.reason),
            nats_factory=self.transport.connect,
            observer_snapshot=lambda: copy.deepcopy(self.observer),
            bridge_status=lambda: copy.deepcopy(self.bridge),
            clock=lambda: self.now, monotonic=lambda: self.now)

    async def asyncTearDown(self):
        if hasattr(self, 'runtime'):
            await asyncio.wait_for(self.runtime.stop(), 7)

    async def ready(self):
        # step is the deterministic one-tick production seam, not a test task.
        for _ in range(4):
            await asyncio.wait_for(self.runtime.step(), 5)
            if self.runtime.overview()['node']['readiness'] == 'ready':
                return
        self.fail('valid fixed synthetic deployment never reached ready: ' + repr(self.runtime.overview()['node']))

    def advance(self, seconds=100):
        self.now += seconds
        self.bridge['observed_at'] = stamp(self.now)
        self.observer['agents'][0]['heartbeat_at'] = stamp(self.now)

    def create(self, prompt='synthetic audit'):
        task = ledger.uid()
        reply = self.runtime.submit(task, 'alp', prompt)
        self.assertNotIn('error', reply)
        return task

    def durable_delivery(self, task):
        # Independent SQLite reader observes committed state, no private API.
        with sqlite3.connect(self.path, timeout=0) as reader:
            for (name,) in reader.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                columns = {row[1] for row in reader.execute('PRAGMA table_info("' + name.replace('"', '""') + '")')}
                if {'task_id', 'delivery'}.issubset(columns):
                    return reader.execute('SELECT delivery FROM "' + name.replace('"', '""') + '" WHERE task_id=?', (task,)).fetchone()[0]
        self.fail('no committed ledger task projection')

    async def test_two_fixed_connections_bind_only_and_rpc_never_uses_network(self):
        # INV-NRUN-01/03/04/05/06.
        await self.ready()
        self.assertEqual(len(self.transport.connections), 2)
        roles = {item['user']: item for item in self.transport.connect_kwargs}
        self.assertEqual(set(roles), {'control_alp_publisher', 'control_task_sink'})
        for role, port in [('control_alp_publisher', 4222), ('control_task_sink', 24222)]:
            kwargs = roles[role]
            self.assertIn('nats://127.0.0.1:' + str(port), str(kwargs.get('servers')))
            prefix = kwargs.get('inbox_prefix')
            if isinstance(prefix, bytes): prefix = prefix.decode()
            self.assertEqual(prefix, '_INBOX.' + role)
            self.assertEqual(kwargs['password'], self.settings['publisher' if port == 4222 else 'sink']['password'])
            self.assertLessEqual(kwargs.get('connect_timeout', 2), 2)
        self.assertTrue(self.transport.binds)
        counts = (len(self.transport.connect_kwargs), len(self.transport.publishes), self.transport.fetches)
        task = self.create('😀' * 200)
        overview, detail = self.runtime.overview(), self.runtime.task(task)
        self.assertEqual(counts, (len(self.transport.connect_kwargs), len(self.transport.publishes), self.transport.fetches))
        self.assertEqual(overview['node']['capacity'], 'unknown')
        self.assertIsNone(overview['usage'])
        self.assertNotIn('prompt', detail)
        self.assertLessEqual(len(detail['prompt_preview'].encode()), 256)
        self.assertTrue(detail['prompt_truncated'])
        self.assertNotIn('synthetic-publisher-only', repr(overview))
        self.assertNotIn('synthetic-sink-only', repr(detail))

    async def test_submit_commits_without_publication_then_exact_bytes_puback(self):
        # INV-NRUN-03/04: independent reader sees unknown before network.
        await self.ready()
        task = self.create('exact 😀')
        row = self.store.pending()[0]
        self.assertEqual(self.durable_delivery(task), 'pending')
        self.assertEqual(self.transport.publishes, [])
        def before(subject, data, headers, timeout):
            self.assertEqual(self.durable_delivery(task), 'unknown')
            self.assertEqual((subject, data, headers), ('devbus.commands.codex-ai-dev-1', row['wire'], {'Nats-Msg-Id': row['message_id']}))
            self.assertLessEqual(timeout, 2)
        self.transport.on_publish = before
        await self.runtime.step()
        dto = self.store.get(task)
        self.assertEqual(dto['delivery'], 'published')
        self.assertEqual(dto['execution'], 'waiting')
        self.assertIsNone(dto['usage'])
        self.assertEqual(dto['quality'], 'unreviewed')

    async def test_publication_commit_refusal_never_calls_network(self):
        # INV-NRUN-04.
        await self.ready(); task = self.create()
        self.proxy.fail.add('publication_started')
        await self.runtime.step()
        self.assertEqual(self.transport.publishes, [])
        self.assertEqual(self.store.get(task)['delivery'], 'pending')

    async def test_puback_invalid_stream_bool_zero_or_oversize_sequence_leaves_unknown(self):
        # INV-NRUN-04: a transport ACK is not a successful execution.
        await self.ready()
        for stream, seq in [('OTHER', 3), ('DEVBUS_V1', True), ('DEVBUS_V1', 0), ('DEVBUS_V1', 2**63)]:
            with self.subTest(stream=stream, sequence=seq):
                task = self.create()
                self.transport.puback = NS(stream=stream, seq=seq, duplicate=False)
                await self.runtime.step()
                dto = self.store.get(task)
                self.assertEqual((dto['delivery'], dto['execution']), ('unknown', 'waiting'))
                self.store.ingest(ledger.event(task, 'completed', {'text': 'done', 'executor': 'codex'}))
                self.advance()

    async def test_timeout_reconnect_preserves_message_id_and_wire(self):
        # INV-NRUN-04: no new task/attempt ID on uncertain delivery.
        await self.ready(); task = self.create()
        original = self.store.pending()[0]
        self.transport.publish_error = asyncio.TimeoutError()
        await self.runtime.step()
        self.assertEqual(self.store.get(task)['delivery'], 'unknown')
        self.transport.publish_error = None
        self.advance()
        await self.runtime.step()
        self.assertGreaterEqual(len(self.transport.publishes), 2)
        for _, wire, headers in self.transport.publishes:
            self.assertEqual(wire, original['wire'])
            self.assertEqual(headers, {'Nats-Msg-Id': original['message_id']})
        self.assertEqual(len(self.store.list()), 1)

    async def test_blocked_existing_exact_retry_and_conflict_new_submit_refused(self):
        # INV-NRUN-06: readiness applies to new work, not durable dedup lookup.
        await self.ready(); task = self.create('immutable')
        self.bridge['observed_at'] = stamp(self.now - 31)
        await self.runtime.step()
        self.assertEqual(self.runtime.overview()['node']['reason'], 'unavailable')
        self.assertNotIn('error', self.runtime.submit(task, 'alp', 'immutable'))
        self.assertEqual(self.runtime.submit(task, 'alp', 'changed'), {'error': 'conflict'})
        other = ledger.uid()
        self.assertIn('error', self.runtime.submit(other, 'alp', 'new'))
        self.assertEqual(self.store.get(other), {'error': 'not_found'})
        self.assertEqual(self.transport.publishes, [])
        self.assertEqual(self.store.get(task)['execution'], 'waiting')

    async def test_disabled_and_unattested_keep_history_no_connections(self):
        # INV-NRUN-02/06.
        task = ledger.uid(); self.store.submit(task, 'alp', 'retained')
        self.settings, self.reason = None, 'disabled'
        await self.runtime.step()
        self.assertEqual(self.runtime.overview()['node']['readiness'], 'disabled')
        self.assertEqual(self.runtime.task(task)['task_id'], task)
        self.assertEqual(self.transport.connections, [])

    async def test_heartbeat_is_freshness_and_unattested_is_blocked(self):
        # INV-NRUN-06: heartbeat cannot replace deployment proof.
        self.settings['profile_attested'] = False
        await self.runtime.step()
        self.assertEqual(self.runtime.overview()['node']['reason'], 'profile_unverified')
        self.assertEqual(self.transport.publishes, [])
        self.assertIn('error', self.runtime.submit(ledger.uid(), 'alp', 'no'))

    async def test_ingest_commit_visible_before_ack_duplicate_ack_safe(self):
        # INV-NRUN-05: real SQLite visibility and digest redelivery.
        await self.ready(); task = self.create()
        raw = ledger.event(task, 'completed', {'text': 'stored result', 'executor': 'codex'})
        msg = Message(raw)
        def ack_check():
            with sqlite3.connect(self.path, timeout=0) as reader:
                dumped = '\n'.join(reader.iterdump())
            self.assertIn('stored result', dumped)
            self.assertEqual(self.store.get(task)['execution'], 'completed')
        msg.on_ack = ack_check
        self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(msg.acks, 1)
        before = self.store.get(task)
        again = Message(raw, 2); self.transport.messages.append(again)
        await self.runtime.step()
        self.assertEqual(again.acks, 1)
        self.assertEqual(self.store.get(task), before)
        self.assertEqual(self.transport.publishes, [])

    async def test_ingest_storage_failure_no_ack_and_no_outcome(self):
        # INV-NRUN-05.
        await self.ready(); task = self.create()
        msg = Message(ledger.event(task)); self.transport.messages.append(msg)
        self.proxy.fail.add('ingest')
        await self.runtime.step()
        self.assertEqual(msg.acks, 0)
        self.assertEqual(self.store.get(task)['execution'], 'waiting')
        self.assertEqual(self.transport.publishes, [])

    async def test_invalid_ingest_fence_commit_before_ack_and_storage_no_ack(self):
        # INV-NRUN-05: poison must be persisted and fence committed before ACK.
        await self.ready()
        msg = Message(b'{broken')
        msg.on_ack = lambda: self.assertEqual(self.store.runtime_state(), {'fence': 'invalid_event'})
        self.transport.messages.append(msg)
        self.proxy.fail.add('mark_gap')
        await self.runtime.step()
        self.assertEqual(msg.acks, 0)
        self.proxy.fail.remove('mark_gap'); self.advance()
        self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(msg.acks, 1)
        self.assertEqual(self.runtime.overview()['node']['reason'], 'invalid_event')

    async def test_wrong_subject_never_ack_or_ingest(self):
        # INV-NRUN-05.
        await self.ready()
        msg = Message(ledger.event(ledger.uid()), subject='devbus.events.other')
        self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(msg.acks, 0)
        self.assertFalse(any(name == 'ingest' for name, _, _ in self.proxy.calls))
        self.assertIsNotNone(self.store.runtime_state()['fence'])

    async def test_foreign_task_is_committed_ignored_ack_without_new_task_or_fence(self):
        # INV-NRUN-05: normal shared-stream events are not poison.
        await self.ready()
        msg = Message(ledger.event(ledger.uid())); self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(msg.acks, 1)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.store.runtime_state(), {'fence': None})
        self.assertEqual(self.runtime.overview()['node']['readiness'], 'ready')

    async def test_gap_threshold_uses_numeric_ack_floor_and_commits_before_publish(self):
        # INV-NRUN-05: equal threshold safe; one above threshold fences first.
        self.transport.ack_floor = 10; self.transport.first_seq = 11
        await self.ready(); task = self.create()
        self.transport.first_seq = 12
        await self.runtime.step()
        self.assertEqual(self.store.runtime_state(), {'fence': 'retention_gap'})
        self.assertEqual(self.store.get(task)['coverage'], 'partial')
        self.assertEqual(self.transport.publishes, [])
        self.assertEqual(self.runtime.overview()['node']['reason'], 'retention_gap')

    async def test_epoch_change_between_ingest_and_ack_fences_no_ack(self):
        # INV-NRUN-05: pre-fetch checks alone cannot authorize later ACK.
        await self.ready(); task = self.create()
        original = self.proxy.ingest
        def ingest_and_change(raw):
            result = original(raw)
            self.transport.consumer_epoch = '2026-10-14T00:00:00Z'
            return result
        self.proxy.ingest = ingest_and_change
        msg = Message(ledger.event(task)); self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(msg.acks, 0)
        self.assertEqual(self.store.runtime_state(), {'fence': 'retention_gap'})
        self.assertEqual(self.transport.publishes, [])

    async def test_wrong_consumer_policy_blocks_without_recreate(self):
        # INV-NRUN-05: fake deliberately has no create/delete/skip methods.
        self.transport.filter = 'devbus.events.>'
        await self.runtime.step()
        self.assertNotEqual(self.runtime.overview()['node']['readiness'], 'ready')
        self.assertEqual(self.transport.publishes, [])
        self.assertIn('error', self.runtime.submit(ledger.uid(), 'alp', 'no'))

    async def test_overview_last50_count_flag_and_bounded_detail(self):
        # INV-NRUN-06/07: complete retained history exceeds one window.
        expected = []
        for index in range(53):
            task = ledger.uid(); self.store.submit(task, 'alp', '😀' * 500)
            self.store.ingest(ledger.event(task, 'completed', {'text': '😀' * 10000, 'executor': 'codex'}))
            expected.append(self.store.get(task))
            self.now += 1
        overview = self.runtime.overview()
        self.assertEqual([row['task_id'] for row in overview['tasks']],
                         [row['task_id'] for row in expected[::-1][:50]])
        self.assertTrue(overview['tasks_truncated'])
        self.assertFalse(overview['budget_trimmed'])
        self.assertLessEqual(len(json.dumps(overview, ensure_ascii=False).encode()), 96 * 1024)
        detail = self.runtime.task(expected[-1]['task_id'])
        self.assertNotIn('prompt', detail)
        self.assertEqual(detail['result'], expected[-1]['result'])
        self.assertLessEqual(len(json.dumps(detail, ensure_ascii=False).encode()), 96 * 1024)

    async def test_cancel_publication_keeps_unknown_and_stop_is_idempotent(self):
        # INV-NRUN-03/04: async cancellation propagates, durable bytes remain.
        await self.ready(); task = self.create()
        original = self.store.pending()[0]
        self.transport.publish_error = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.runtime.step()
        self.assertEqual(self.store.get(task)['delivery'], 'unknown')
        self.assertEqual(self.store.pending()[0], original)
        first = await asyncio.wait_for(self.runtime.stop(), 6.2)
        second = await self.runtime.stop()
        self.assertEqual(first, {'stopped': True})
        self.assertEqual(second, first)
        self.assertTrue(all(connection.closed == 1 for connection in self.transport.connections))
        self.assertIn('error', self.runtime.submit(ledger.uid(), 'alp', 'stopped'))

    async def test_start_twice_schedules_one_worker_and_stop_bounds_blocked_fetch(self):
        # INV-NRUN-03: one background worker, bounded cancellation and close.
        self.transport.fetch_gate = asyncio.Event()
        await self.runtime.start(); await self.runtime.start()
        async def wait_connections():
            while len(self.transport.connections) < 2:
                await asyncio.sleep(.01)
        await asyncio.wait_for(wait_connections(), 4)
        await asyncio.wait_for(self.transport.fetch_entered.wait(), 4)
        self.assertEqual(len(self.transport.connections), 2)
        result = await asyncio.wait_for(self.runtime.stop(), 6.2)
        self.assertEqual(result, {'stopped': True})
        self.assertTrue(all(connection.closed == 1 for connection in self.transport.connections))

    async def test_stubborn_worker_stop_false_does_not_close_live_store(self):
        # INV-NRUN-03: OS exit is not proof of drain; store remains usable.
        self.transport.fetch_gate = asyncio.Event()
        self.transport.stubborn_fetch = True
        try:
            await self.runtime.start()
            await asyncio.wait_for(self.transport.fetch_entered.wait(), 4)
            result = await asyncio.wait_for(self.runtime.stop(), 6.2)
            self.assertEqual(result, {'stopped': False})
            self.assertEqual(self.store.get(ledger.uid()), {'error': 'not_found'})
            self.assertFalse(any(name == 'close' for name, _, _ in self.proxy.calls))
        finally:
            self.transport.fetch_gate.set()
            await asyncio.sleep(.02)

    async def test_gap_commit_failure_prevents_publish_and_retry_persists_fence(self):
        # INV-NRUN-05: merely detecting loss is not a successful commit.
        await self.ready(); task = self.create()
        self.bridge['reason'] = 'retention_gap'
        self.proxy.fail.add('mark_gap')
        await self.runtime.step()
        self.assertEqual(self.transport.publishes, [])
        self.assertEqual(self.store.runtime_state(), {'fence': None})
        self.proxy.fail.remove('mark_gap'); self.advance()
        await self.runtime.step()
        self.assertEqual(self.store.runtime_state(), {'fence': 'retention_gap'})
        self.assertEqual(self.store.get(task)['coverage'], 'partial')
        self.assertEqual(self.transport.publishes, [])

    async def test_stale_heartbeat_blocks_new_work_without_fabricated_gap(self):
        # INV-NRUN-06: missing liveness is neither execution failure nor loss.
        await self.ready(); task = self.create()
        self.observer['agents'][0].update(heartbeat_at=stamp(self.now - 46),
                                          heartbeat_status='stale')
        await self.runtime.step()
        self.assertEqual(self.runtime.overview()['node']['reason'], 'observer_stale')
        self.assertEqual(self.store.get(task)['execution'], 'waiting')
        self.assertEqual(self.store.runtime_state(), {'fence': None})
        self.assertEqual(self.transport.publishes, [])

    async def test_reencoded_message_id_conflict_commits_fence_before_ack(self):
        # INV-NRUN-05: durable event digest covers exact received bytes.
        await self.ready(); task = self.create()
        first = ledger.event(task)
        self.transport.messages.append(Message(first))
        await self.runtime.step()
        changed = json.dumps(json.loads(first), indent=2).encode()
        self.assertNotEqual(changed, first)
        msg = Message(changed, 2)
        msg.on_ack = lambda: self.assertEqual(self.store.runtime_state(), {'fence': 'id_conflict'})
        self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(msg.acks, 1)
        self.assertEqual(self.store.get(task)['execution'], 'needs_attention')
        self.assertEqual(self.runtime.overview()['node']['reason'], 'id_conflict')

    async def assert_transport_poison(self, msg):
        await self.ready()
        self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(msg.acks, 0)
        self.assertFalse(any(name == 'ingest' for name, _, _ in self.proxy.calls))
        self.assertIsNotNone(self.store.runtime_state()['fence'])

    async def test_bool_stream_sequence_never_reaches_ingest_or_ack(self):
        # INV-NRUN-05: bool is not a positive stream sequence.
        await self.assert_transport_poison(Message(ledger.event(ledger.uid()), sequence=True))

    async def test_wrong_consumer_binding_never_reaches_ingest_or_ack(self):
        # INV-NRUN-05: another durable's message cannot update this ledger.
        msg = Message(ledger.event(ledger.uid()))
        msg.metadata.consumer = 'OTHER'
        await self.assert_transport_poison(msg)

    async def test_oversize_message_never_reaches_ingest_or_ack(self):
        # INV-NRUN-05: enforce transport wire cap before core interpretation.
        await self.assert_transport_poison(Message(b'x' * (126 * 1024 + 1)))



if __name__ == '__main__':
    unittest.main()
