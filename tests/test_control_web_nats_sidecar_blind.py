"""Blind public-contract RED tests for the NATS observer sidecar design.

No live NATS server, credentials, network, or agent-bus package is used.
"""
import asyncio
import builtins
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

BRIDGE_CREATED = "2026-10-12T00:00:00.000000Z"
CONSUMER_CREATED = "2026-10-12T00:01:00.000000Z"
OBS_CREATED = "2026-10-12T00:02:00.000000Z"
SOURCE_URL = "tls://origin.invalid:4222"
OBS_URL = "nats://127.0.0.1:4422"
SOURCE_TOKEN = "synthetic-origin-token-never-a-real-secret"
OBS_PASSWORD = "synthetic-obs-password-never-a-real-secret"
BRIDGE_STATUS_FILE = "/home/dwl/.local/state/ai-control/devbus-bridge.json"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True, allow_nan=False).encode("utf-8")


def bridge_config():
    return {
        "schema": 1,
        "source": {
            "url": SOURCE_URL,
            "stream": "DEVBUS_V1",
            "consumer": "control_observer_bridge",
            "stream_created": BRIDGE_CREATED,
            "consumer_created": CONSUMER_CREATED,
            "auth": {"mode": "token", "token": SOURCE_TOKEN},
        },
        "destination": {
            "url": OBS_URL,
            "stream": "OBS_EVENTS",
            "stream_created": OBS_CREATED,
            "user": "obs_bridge_writer",
            "password": OBS_PASSWORD,
        },
        "agents": ["agent_a", "agent_b"],
    }


def observer_config():
    return {
        "schema": 2,
        "enabled": True,
        "url": OBS_URL,
        "stream": "OBS_EVENTS",
        "stream_created": OBS_CREATED,
        "user": "control_observer",
        "password": "synthetic-control-observer-password",
    }


def event_bytes(**changes):
    event = {
        "message_id": "payload-message-id-is-not-the-dedupe-key",
        "task_id": "task_1",
        "correlation_id": "task_1",
        "source": "agent_a",
        "target": "control",
        "kind": "completed",
        "created_at": "2026-10-12T00:03:00+00:00",
        "payload": {"result": "synthetic-only"},
    }
    event.update(changes)
    return canonical(event)


def fake_stat(real, *, owner=1000, mode=None, nlink=None, inode=None):
    fields = {name: getattr(real, name) for name in dir(real) if name.startswith("st_")}
    fields["st_uid"] = owner
    if mode is not None: fields["st_mode"] = mode
    if nlink is not None: fields["st_nlink"] = nlink
    if inode is not None:
        fields["st_ino"] = inode
    return SimpleNamespace(**fields)


def redirect_status_io(fixture):
    """Redirect the documented fixed status path to an owned private fixture."""
    stack = ExitStack()
    fixture = Path(fixture)
    status_dir = str(Path(BRIDGE_STATUS_FILE).parent)
    real_open, real_stat, real_lstat = os.open, os.stat, os.lstat
    real_mkdir, real_replace, real_unlink = os.mkdir, os.replace, os.unlink
    real_chmod, real_path_open, real_builtin_open = os.chmod, Path.open, builtins.open

    def remap(value):
        text = os.fsdecode(value)
        if text == BRIDGE_STATUS_FILE or text.startswith(status_dir + os.sep):
            return fixture.parent / Path(text).name
        return value

    stack.enter_context(patch.object(os, "open", side_effect=lambda path, *a, **k: real_open(remap(path), *a, **k)))
    stack.enter_context(patch.object(os, "stat", side_effect=lambda path, *a, **k: real_stat(remap(path), *a, **k)))
    stack.enter_context(patch.object(os, "lstat", side_effect=lambda path, *a, **k: real_lstat(remap(path), *a, **k)))
    stack.enter_context(patch.object(os, "mkdir", side_effect=lambda path, *a, **k: real_mkdir(remap(path), *a, **k)))
    stack.enter_context(patch.object(os, "replace", side_effect=lambda src, dst, *a, **k: real_replace(remap(src), remap(dst), *a, **k)))
    stack.enter_context(patch.object(os, "unlink", side_effect=lambda path, *a, **k: real_unlink(remap(path), *a, **k)))
    stack.enter_context(patch.object(os, "chmod", side_effect=lambda path, *a, **k: real_chmod(remap(path), *a, **k)))
    stack.enter_context(patch.object(Path, "open", lambda self, *a, **k: real_path_open(Path(remap(self)), *a, **k)))
    stack.enter_context(patch.object(builtins, "open", lambda path, *a, **k: real_builtin_open(remap(path), *a, **k)))
    return stack


class FakeMessage:
    def __init__(self, subject="devbus.events.agent_a", data=None, sequence=7):
        self.subject = subject
        self.data = event_bytes() if data is None else data
        self.sequence = sequence
        self.reply = "$JS.ACK.synthetic.reconstructed-subject-is-forbidden"
        self.metadata = SimpleNamespace(
            sequence=SimpleNamespace(stream=sequence), num_delivered=1)
        self.calls = []
        self.acked = asyncio.Event()
        self.before_ack = lambda: True

    async def ack_sync(self, timeout=None):
        if not self.before_ack():
            raise AssertionError("origin ACK must follow a successful destination PubAck")
        self.calls.append(("ack_sync", timeout))
        self.acked.set()

    async def ack(self):
        self.calls.append(("ack", None))
        self.acked.set()


class FakePullSubscription:
    def __init__(self, message):
        self.message = message
        self.fetch_calls = []
        self.first_returned = asyncio.Event()
        self.next_fetch = asyncio.Event()
        self.fetch_entered = asyncio.Event()
        self.block = asyncio.Event()

    async def fetch(self, batch=1, timeout=1):
        self.fetch_calls.append((batch, timeout))
        self.fetch_entered.set()
        if self.message is not None:
            message, self.message = self.message, None
            self.first_returned.set()
            return [message]
        self.next_fetch.set()
        await self.block.wait()
        return []

    async def unsubscribe(self):
        return None


class FakeJetStream:
    def __init__(self, role, config, *, message=None, puback_stream="OBS_EVENTS",
                 publish_error=None, after_publish=None):
        self.role, self.config = role, config
        self.message = message
        self.puback_stream, self.publish_error = puback_stream, publish_error
        self.after_publish = after_publish
        self.calls = []
        self.published = asyncio.Event()
        self.publish_completed = asyncio.Event()
        self.puback_completed = asyncio.Event()
        self.bound = asyncio.Event()
        self.stream_info_seen = asyncio.Event()
        self.source_consumer_created_override = None
        self.source_stream_created_override = None
        self.epoch_mismatch_seen = asyncio.Event()
        self.subscription = None
        self.consumer_info_calls = 0
        self.consumer_info_seen = asyncio.Event()

    async def stream_info(self, stream):
        self.calls.append(("stream_info", stream))
        self.stream_info_seen.set()
        cfg = self.config
        if self.role == "source":
            created = self.source_stream_created_override or cfg["source"]["stream_created"]
            name = "DEVBUS_V1"
            subjects = ["devbus.commands.*", "devbus.events.*"]
        else:
            created = cfg["destination"]["stream_created"]
            name = "OBS_EVENTS"
            subjects = ["devbus.events.*"]
        return SimpleNamespace(
            created=created, config=SimpleNamespace(
                name=name, subjects=subjects, storage="file", retention="limits",
                max_age=86400, max_bytes=104857600, max_msg_size=131072,
                duplicate_window=120),
            state=SimpleNamespace(first_seq=1, last_seq=50, messages=1))

    async def consumer_info(self, stream, consumer):
        self.consumer_info_calls += 1
        self.calls.append(("consumer_info", stream, consumer))
        self.consumer_info_seen.set()
        created = (self.source_consumer_created_override or
                   self.config["source"]["consumer_created"])
        if created != self.config["source"]["consumer_created"]:
            self.epoch_mismatch_seen.set()
        return SimpleNamespace(
            created=created, name=consumer, stream_name=stream,
            config=SimpleNamespace(
                durable_name=consumer, name=consumer, filter_subject="devbus.events.>",
                filter_subjects=None, ack_policy="explicit", deliver_policy="all",
                ack_wait=30, max_ack_pending=32, max_deliver=-1,
                max_waiting=1, max_batch=32, max_expires=5,
                flow_control=False, idle_heartbeat=0, headers_only=False,
                deliver_subject=None, deliver_group=None),
            ack_floor=SimpleNamespace(stream_seq=0, consumer_seq=0),
            delivered=SimpleNamespace(stream_seq=0, consumer_seq=0),
            num_pending=0, num_ack_pending=0)

    async def pull_subscribe_bind(self, consumer=None, stream=None, **kwargs):
        if consumer is None:
            consumer = kwargs.pop("name", None)
        self.calls.append(("bind", consumer, stream, kwargs))
        self.subscription = FakePullSubscription(self.message)
        self.bound.set()
        return self.subscription

    async def publish(self, subject, data, headers=None, timeout=None, **kwargs):
        self.calls.append(("publish", subject, data, headers, timeout))
        self.published.set()
        try:
            if self.after_publish is not None:
                self.after_publish()
            if self.publish_error is not None:
                raise self.publish_error
            result = SimpleNamespace(stream=self.puback_stream, seq=1, duplicate=False)
            self.puback_completed.set()
            return result
        finally:
            self.publish_completed.set()

    async def add_consumer(self, *args, **kwargs):
        self.calls.append(("FORBIDDEN_add_consumer", args, kwargs))
        raise AssertionError("bridge must bind the owner-precreated source durable")

    async def delete_consumer(self, *args, **kwargs):
        self.calls.append(("FORBIDDEN_delete_consumer", args, kwargs))
        raise AssertionError("bridge must not mutate the source durable")

    async def update_consumer(self, *args, **kwargs):
        self.calls.append(("FORBIDDEN_update_consumer", args, kwargs))
        raise AssertionError("bridge must not mutate the source durable")


class FakeConnection:
    def __init__(self, role, js, kwargs):
        self.role, self._js, self.kwargs = role, js, kwargs
        self.closed = False

    def jetstream(self):
        return self._js

    async def close(self):
        self.closed = True


class FakeNatsFactory:
    def __init__(self, config, *, message=None, puback_stream="OBS_EVENTS",
                 publish_error=None, after_publish=None,
                 source_stream_created=None, source_consumer_created=None):
        self.config = config
        self.calls = []
        self.connections = []
        self.message = message
        self.puback_stream = puback_stream
        self.publish_error = publish_error
        self.after_publish = after_publish
        self.source_stream_created = source_stream_created
        self.source_consumer_created = source_consumer_created
        self.source_js = self.destination_js = None
        self.source_connected = asyncio.Event()

    async def __call__(self, **kwargs):
        self.calls.append(kwargs.copy())
        servers = kwargs.get("servers", [])
        url = servers[0] if servers else kwargs.get("server")
        if url == self.config["source"]["url"]:
            role = "source"
            js = FakeJetStream(role, self.config, message=self.message)
            js.source_stream_created_override = self.source_stream_created
            js.source_consumer_created_override = self.source_consumer_created
            self.source_js = js
            self.source_connected.set()
            if self.message is not None:
                self.message.before_ack = lambda: (
                    self.destination_js is not None
                    and self.destination_js.puback_completed.is_set())
        elif url == self.config["destination"]["url"]:
            role = "destination"
            js = FakeJetStream(role, self.config, puback_stream=self.puback_stream,
                               publish_error=self.publish_error,
                               after_publish=self.after_publish)
            self.destination_js = js
        else:
            raise AssertionError("factory received an endpoint outside validated config")
        connection = FakeConnection(role, js, kwargs)
        self.connections.append(connection)
        return connection


class BridgeLoaderBlind(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("_control_web_devbus_nats")
        self.loader = getattr(self.module, "load_bridge_config", None)
        self.assertTrue(callable(self.loader),
                        "PUBLIC-SEAM PREREQUISITE: load_bridge_config absent")
        self.temp = tempfile.TemporaryDirectory(prefix="sidecar-bridge-loader-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "bridge.json"
        self.config = bridge_config()
        self.real_stat, self.real_fstat = os.stat, os.fstat

    def write(self, value, *, mode=0o600):
        raw = value if isinstance(value, bytes) else canonical(value)
        self.path.write_bytes(raw)
        self.path.chmod(mode)

    def invoke(self, *, value=None, mode=0o600, patches=(), ambient=None):
        if value is not None:
            self.write(value, mode=mode)
        else:
            self.path.write_bytes(b"{}"); self.path.chmod(mode)
        def synthetic_fstat(fd): return fake_stat(self.real_fstat(fd))
        def synthetic_stat(path, *args, **kwargs): return fake_stat(self.real_stat(path, *args, **kwargs))
        environment = {"DEVBUS_NATS_TOKEN": "synthetic-ambient-origin-token",
                       "DEVBUS_NATS_CREDS": "/synthetic/ambient-origin.creds"}
        if ambient: environment.update(ambient)
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.module, "BRIDGE_CONFIG_PATH", self.path, create=False))
            stack.enter_context(patch.dict(os.environ, environment, clear=True))
            stack.enter_context(patch.object(self.module.os, "geteuid", return_value=1000))
            stack.enter_context(patch.object(self.module.os, "fstat", side_effect=synthetic_fstat))
            stack.enter_context(patch.object(self.module.os, "stat", side_effect=synthetic_stat))
            for item in patches:
                stack.enter_context(item)
            return self.loader()

    def test_fixed_config_does_not_merge_ambient_origin_auth(self):
        loaded = self.invoke(value=self.config)
        self.assertEqual(loaded, self.config)
        self.assertEqual(loaded["source"]["auth"]["token"], SOURCE_TOKEN)

    def test_schema_auth_union_and_agent_list_are_exact(self):
        invalid = []
        invalid.append(self.config | {"extra": 1})
        invalid.append(self.config | {"schema": 2})
        mixed = bridge_config(); mixed["source"]["auth"] = {"mode": "token", "token": SOURCE_TOKEN,
                                                                "user": "x", "password": "y"}; invalid.append(mixed)
        invalid.append(bridge_config() | {"agents": []})
        invalid.append(bridge_config() | {"agents": ["agent_a", "agent_a"]})
        invalid.append(bridge_config() | {"agents": ["bad.agent"]})
        for value in invalid:
            with self.subTest(value=value):
                try: loaded = self.invoke(value=value)
                except (ValueError, OSError): continue
                self.assertIsNone(loaded, "invalid bridge config must not load")

    def test_loader_rejects_wrong_mode_overflow_and_symlink_without_repair(self):
        value = self.config
        try: loaded = self.invoke(value=value, mode=0o644)
        except (ValueError, OSError): loaded = None
        self.assertIsNone(loaded)
        try: loaded = self.invoke(value=b" " * 16385)
        except (ValueError, OSError): loaded = None
        self.assertIsNone(loaded)
        target = Path(self.temp.name) / "target.json"
        target.write_bytes(canonical(value)); target.chmod(0o600)
        self.path.unlink(); self.path.symlink_to(target)
        with patch.object(self.module, "BRIDGE_CONFIG_PATH", self.path, create=False):
            try: loaded = self.loader()
            except (ValueError, OSError): loaded = None
        self.assertIsNone(loaded)
        self.assertTrue(self.path.is_symlink(), "loader must not repair or replace unsafe input")
        self.path.unlink()
        self.write(self.config)
        def swapped(path, *args, **kwargs):
            return fake_stat(self.real_stat(path, *args, **kwargs), inode=self.real_stat(path).st_ino + 1)
        with patch.object(self.module, "BRIDGE_CONFIG_PATH", self.path, create=False), \
             patch.dict(os.environ, {}, clear=True), \
             patch.object(self.module.os, "geteuid", return_value=1000), \
             patch.object(self.module.os, "fstat", side_effect=lambda fd: fake_stat(self.real_fstat(fd))), \
             patch.object(self.module.os, "stat", side_effect=swapped):
            try: loaded = self.loader()
            except (ValueError, OSError): loaded = None
        self.assertIsNone(loaded)


class ObserverConfigBlind(unittest.TestCase):
    def setUp(self):
        self.broker = importlib.import_module("_control_web_broker")
        self.loader = getattr(self.broker, "load_devbus_config", None)
        self.assertTrue(callable(self.loader), "PUBLIC-SEAM PREREQUISITE: load_devbus_config absent")
        self.temp = tempfile.TemporaryDirectory(prefix="sidecar-observer-config-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "observer.json"
        self.real_stat, self.real_fstat = os.stat, os.fstat

    def load(self, config):
        self.path.write_bytes(canonical(config)); self.path.chmod(0o600)
        def fstat(fd): return fake_stat(self.real_fstat(fd))
        def stat_fn(path, *args, **kwargs): return fake_stat(self.real_stat(path, *args, **kwargs))
        with patch.object(self.broker, "DEVBUS_CONFIG_PATH", self.path), \
             patch.dict(os.environ, {"CONTROL_DEVBUS_CONFIG": str(self.path),
                                     "DEVBUS_NATS_TOKEN": "synthetic-ambient-origin-token",
                                     "DEVBUS_NATS_CREDS": "/synthetic/origin.creds"}, clear=True), \
             patch.object(self.broker.os, "geteuid", return_value=1000), \
             patch.object(self.broker.os, "fstat", side_effect=fstat), \
             patch.object(self.broker.os, "stat", side_effect=stat_fn):
            return self.loader()

    def test_schema2_observer_accepts_obs_only_and_rejects_origin_auth_fields(self):
        config, reason = self.load(observer_config())
        self.assertIsNone(reason)
        self.assertTrue(config.enabled)
        self.assertEqual(config.url, OBS_URL)
        self.assertEqual(config.stream, "OBS_EVENTS")
        self.assertEqual(config.user, "control_observer")
        self.assertEqual(config.password, observer_config()["password"])
        self.assertNotIn(SOURCE_TOKEN, repr(config))
        self.assertNotIn("synthetic-ambient-origin-token", repr(config))
        for field, value in (("token", SOURCE_TOKEN), ("creds", "/synthetic/origin.creds"),
                             ("source", {"url": SOURCE_URL}), ("auth", {"mode": "token"}),
                             ("extra", "not-allowed")):
            with self.subTest(field=field):
                config, reason = self.load(observer_config() | {field: value})
                self.assertFalse(config.enabled)
                self.assertEqual(reason, "invalid_config")


class BridgeRunBlind(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = importlib.import_module("_control_web_devbus_nats")
        self.run_bridge = getattr(self.module, "run_bridge", None)
        self.assertTrue(callable(self.run_bridge), "PUBLIC-SEAM PREREQUISITE: run_bridge absent")
        self.temp = tempfile.TemporaryDirectory(prefix="sidecar-bridge-run-")
        self.addCleanup(self.temp.cleanup)
        self.status_path = Path(self.temp.name) / "devbus-bridge.json"

    async def asyncTearDown(self):
        self.temp.cleanup()

    def harness(self, **kwargs):
        cfg = bridge_config()
        kwargs.setdefault("message", FakeMessage())
        factory = FakeNatsFactory(cfg, **kwargs)
        return cfg, factory

    async def start(self, cfg, factory):
        self.addCleanup(redirect_status_io(self.status_path).close)
        return asyncio.create_task(self.run_bridge(cfg, nats_factory=factory))

    async def wait_source_fetch(self, factory):
        await asyncio.wait_for(factory.source_connected.wait(), 1)
        await asyncio.wait_for(factory.source_js.bound.wait(), 1)
        await asyncio.wait_for(factory.source_js.subscription.fetch_entered.wait(), 1)

    async def stop_task(self, task):
        if task.done():
            await asyncio.gather(task, return_exceptions=True)
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_run_bridge_revalidates_before_any_factory_or_network_call(self):
        for invalid in (bridge_config() | {"extra": 1},
                        bridge_config() | {"agents": []},
                        bridge_config() | {"destination": bridge_config()["source"]}):
            with self.subTest(invalid=invalid):
                factory = FakeNatsFactory(bridge_config())
                status_io = redirect_status_io(self.status_path)
                try:
                    try:
                        await asyncio.wait_for(self.run_bridge(invalid, nats_factory=factory), .2)
                    except (ValueError, OSError, asyncio.TimeoutError):
                        pass
                finally:
                    status_io.close()
                self.assertEqual(factory.calls, [], "config validation must precede NATS connect")

    async def test_binds_only_precreated_source_durable_never_source_mutation(self):
        cfg, factory = self.harness()
        task = await self.start(cfg, factory)
        try:
            await self.wait_source_fetch(factory)
            await factory.message.acked.wait()
            calls = factory.source_js.calls
            self.assertIn(("bind", cfg["source"]["consumer"], "DEVBUS_V1", ANY), calls)
            self.assertFalse(any(call[0] in {"publish", "FORBIDDEN_add_consumer",
                                             "FORBIDDEN_delete_consumer", "FORBIDDEN_update_consumer"}
                                 for call in calls))
        finally:
            await self.stop_task(task)

    async def test_destination_puback_precedes_ack_and_uses_exact_subject_bytes(self):
        cfg, factory = self.harness()
        task = await self.start(cfg, factory)
        try:
            await asyncio.wait_for(factory.message.acked.wait(), 1)
            calls = factory.destination_js.calls
            publish = next(call for call in calls if call[0] == "publish")
            self.assertEqual(publish[1], "devbus.events.agent_a")
            self.assertEqual(publish[2], factory.message.data)
            self.assertTrue(factory.destination_js.puback_completed.is_set())
            self.assertEqual(factory.message.calls[-1][0], "ack_sync")
            self.assertEqual(publish[3].get("Nats-Msg-Id"),
                             hashlib.sha256(BRIDGE_CREATED.encode() + b"7" + factory.message.data).hexdigest())
        finally:
            await self.stop_task(task)

    async def test_dedupe_id_changes_with_epoch_sequence_and_bytes_not_payload_id(self):
        async def one(cfg, sequence, data):
            msg = FakeMessage(data=data, sequence=sequence)
            factory = FakeNatsFactory(cfg, message=msg)
            task = await self.start(cfg, factory)
            await asyncio.wait_for(msg.acked.wait(), 1)
            publish = next(call for call in factory.destination_js.calls if call[0] == "publish")
            value = publish[3]["Nats-Msg-Id"]
            await self.stop_task(task)
            return value
        cfg = bridge_config()
        base = await one(cfg, 7, event_bytes())
        self.assertEqual(base, await one(bridge_config(), 7, event_bytes()))
        self.assertNotEqual(base, await one(cfg, 8, event_bytes()))
        changed_epoch = bridge_config(); changed_epoch["source"]["stream_created"] = "2026-10-12T00:00:01.000000Z"
        self.assertNotEqual(base, await one(changed_epoch, 7, event_bytes()))
        self.assertNotEqual(base, await one(cfg, 7, event_bytes(message_id="different-payload-id")))
        self.assertRegex(base, r"^[0-9a-f]{64}$")

    async def test_invalid_events_never_publish_or_ack(self):
        valid = event_bytes()
        duplicate = b'{"message_id":"a","message_id":"b"}'
        cases = [
            (valid.replace(b',"created_at":"2026-10-12T00:03:00+00:00"', b""), "devbus.events.agent_a"),
            (event_bytes(created_at="2026-10-12T00:03:00"), "devbus.events.agent_a"),
            (event_bytes(source="agent_unknown"), "devbus.events.agent_unknown"),
            (event_bytes(), "devbus.events.agent_b"),
            (event_bytes(kind="submit"), "devbus.events.agent_a"),
            (duplicate, "devbus.events.agent_a"),
            (b"x" * 131073, "devbus.events.agent_a"),
        ]
        for payload, subject in cases:
            with self.subTest(subject=subject, size=len(payload)):
                cfg, factory = self.harness(message=FakeMessage(subject=subject, data=payload))
                task = await self.start(cfg, factory)
                try:
                    await self.wait_until_processed(task, factory)
                    self.assertFalse(factory.message.acked.is_set())
                    self.assertFalse(any(call[0] == "publish" for call in factory.destination_js.calls))
                finally:
                    await self.stop_task(task)

    async def wait_until_processed(self, task, factory):
        await self.wait_source_fetch(factory)
        later_fetch = asyncio.create_task(factory.source_js.subscription.next_fetch.wait())
        done, pending = await asyncio.wait({task, later_fetch}, timeout=1,
                                           return_when=asyncio.FIRST_COMPLETED)
        for item in pending:
            item.cancel()
        self.assertTrue(done, "event handler must reach a bounded terminal or next-fetch point")

    async def test_publish_failure_or_wrong_stream_puback_leaves_source_unacked(self):
        outcomes = (dict(publish_error=RuntimeError("synthetic unavailable")),
                    dict(puback_stream="WRONG_STREAM"))
        for options in outcomes:
            with self.subTest(options=options):
                cfg, factory = self.harness(**options)
                task = await self.start(cfg, factory)
                try:
                    await self.wait_source_fetch(factory)
                    await asyncio.wait_for(factory.destination_js.publish_completed.wait(), 1)
                    self.assertFalse(factory.message.acked.is_set())
                finally:
                    await self.stop_task(task)

    async def test_epoch_change_after_destination_puback_blocks_source_ack(self):
        cfg = bridge_config()
        factory = None
        def change_source_epoch():
            factory.source_js.source_consumer_created_override = "2026-10-12T00:09:00.000000Z"
        factory = FakeNatsFactory(cfg, message=FakeMessage(), after_publish=change_source_epoch)
        task = await self.start(cfg, factory)
        try:
            await self.wait_source_fetch(factory)
            await asyncio.wait_for(factory.destination_js.published.wait(), 1)
            await asyncio.wait_for(factory.source_js.epoch_mismatch_seen.wait(), 1)
            self.assertFalse(factory.message.acked.is_set(), "generation mismatch must fence ACK")
        finally:
            await self.stop_task(task)

    async def test_source_auth_modes_are_oneof_and_destination_gets_only_obs_password(self):
        for auth, expected in (
            ({"mode": "token", "token": SOURCE_TOKEN}, {"token": SOURCE_TOKEN}),
            ({"mode": "creds", "creds": "/synthetic/delegated.creds"},
             {"user_credentials": "/synthetic/delegated.creds"}),
            ({"mode": "user_password", "user": "origin_bridge", "password": "synthetic-source-password"},
             {"user": "origin_bridge", "password": "synthetic-source-password"}),
        ):
            with self.subTest(mode=auth["mode"]):
                cfg = bridge_config(); cfg["source"]["auth"] = auth
                factory = FakeNatsFactory(cfg)
                task = await self.start(cfg, factory)
                try:
                    await self.wait_source_fetch(factory)
                    source_call = next(call for call in factory.calls if call.get("servers") == [SOURCE_URL])
                    destination_call = next(call for call in factory.calls if call.get("servers") == [OBS_URL])
                    for key, value in expected.items(): self.assertEqual(source_call.get(key), value)
                    self.assertEqual(destination_call.get("user"), "obs_bridge_writer")
                    self.assertEqual(destination_call.get("password"), OBS_PASSWORD)
                    self.assertNotIn("token", destination_call)
                    self.assertNotIn("user_credentials", destination_call)
                finally:
                    await self.stop_task(task)

    async def test_cancellation_closes_both_clients_without_invented_ack(self):
        cfg, factory = self.harness()
        factory.message = None
        task = await self.start(cfg, factory)
        await self.wait_source_fetch(factory)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(len(factory.connections), 2)
        self.assertTrue(all(connection.closed for connection in factory.connections))
        self.assertEqual(factory.source_js.calls[-1][0], "bind")


class ExistingObserverContractBlind(unittest.TestCase):
    def test_projection_keeps_created_at_optional_for_existing_event_contract(self):
        module = importlib.import_module("_control_web_devbus")
        projection = module.Projection(clock=lambda: 100.0)
        event = {
            "message_id": "legacy_without_created_at", "task_id": "task_legacy",
            "correlation_id": "task_legacy", "source": "agent_a", "target": "control",
            "kind": "completed", "payload": {"result": "synthetic"},
        }
        accepted = projection.ingest(canonical(event), "devbus.events.agent_a", 1)
        self.assertTrue(accepted)
        snapshot = projection.snapshot()
        self.assertIsNone(snapshot["events"][0]["event_at"])
        self.assertEqual(snapshot["tasks"][0]["quality"], "unreviewed")


class ExistingObserverEphemeralBlind(unittest.IsolatedAsyncioTestCase):
    async def test_local_observer_keeps_bounded_event_replay_and_ack_contract(self):
        module = importlib.import_module("_control_web_devbus")
        projection = module.Projection(clock=lambda: 100.0)
        message = FakeMessage(sequence=3)

        class Transport:
            def __init__(self): self.fetches = 0; self.closed = False
            async def info(self):
                return {"first_seq": 1, "last_seq": 3,
                        "ttl_seconds": 86400, "max_bytes": 104857600}
            async def fetch(self):
                self.fetches += 1
                return [message] if self.fetches == 1 else []
            async def pending(self): return 0
            async def skip_to(self, sequence): raise AssertionError("small replay must not seek")
            async def close(self): self.closed = True

        transport = Transport()
        async def connect(): return transport
        observer = module.Observer(projection, connect)
        await observer.start()
        try:
            await asyncio.wait_for(message.acked.wait(), 1)
        finally:
            await observer.stop()
        snapshot = projection.snapshot()
        self.assertEqual(snapshot["events"][0]["message_id"], json.loads(message.data)["message_id"])
        self.assertEqual(snapshot["events"][0]["sequence"], 3)
        self.assertTrue(transport.closed)

    def test_owner_projection_reads_status_fixture_marks_partial_and_rejects_stale(self):
        broker = importlib.import_module("_control_web_broker")
        web = importlib.import_module("_control_web_devbus")
        with tempfile.TemporaryDirectory(prefix="sidecar-owner-status-") as directory:
            fixture = Path(directory) / "devbus-bridge.json"
            observed = datetime.now(timezone.utc)
            class Observer:
                def __init__(self, projection, connect): self.projection = projection
                async def start(self): self.projection.connection("live")
                async def stop(self): return None
            config = SimpleNamespace(enabled=True, token="")
            for age, reason in ((0, "retention_gap"), (31, None)):
                timestamp = observed - timedelta(seconds=age)
                status = {
                    "schema": 1,
                    "state": "degraded" if reason else "live",
                    "observed_at": timestamp.isoformat().replace("+00:00", "Z"),
                    "source_stream_created": BRIDGE_CREATED,
                    "consumer_created": CONSUMER_CREATED,
                    "ack_floor": 12, "first_seq": 10, "pending": 2 if reason else 0,
                    "reason": reason,
                }
                fixture.write_bytes(canonical(status)); fixture.chmod(0o600)
                with redirect_status_io(fixture):
                    runtime = broker.DevbusRuntime(
                        config_loader=lambda: (config, None), projection_factory=web.Projection,
                        observer_factory=Observer, connect_factory=lambda _: None,
                        dependency_probe=lambda: True)
                    runtime.start()
                    try: value = runtime.snapshot()
                    finally: runtime.stop()
                self.assertTrue(value["coverage"]["truncated"])
                if reason:
                    self.assertEqual(value["coverage"]["mode"], "partial")
                    self.assertIn(reason, value["coverage"]["issues"])
                else:
                    self.assertNotEqual(value["connection"]["state"], "live")


if __name__ == "__main__":
    unittest.main()
