"""FR-BUS-03 INV-DEVBUS-01/03/08: disposable real JetStream, no installed config.

Run with CONTROL_DEVBUS_NATS_TEST_SERVER=/absolute/path/to/nats-server.
CI devbus job makes this mandatory; ordinary web job may omit local fixture.
"""
import asyncio
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))


@unittest.skipUnless(os.environ.get('CONTROL_DEVBUS_NATS_TEST_SERVER'), 'disposable NATS binary not configured')
class RealBus(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = tempfile.TemporaryDirectory(prefix='devbus-nats-', dir='/var/tmp')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.server = subprocess.Popen([os.environ['CONTROL_DEVBUS_NATS_TEST_SERVER'],
            '-js', '-a', '127.0.0.1', '-p', str(self.port), '-sd', self.storage.name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addAsyncCleanup(self.cleanup_bus)
        import nats
        for _ in range(100):
            try:
                self.nc = await nats.connect(servers=[f'nats://127.0.0.1:{self.port}'],
                    connect_timeout=.1, max_reconnect_attempts=0,
                    error_cb=self.quiet)
                break
            except Exception:
                await asyncio.sleep(.03)
        else:
            self.fail('disposable broker did not start')
        self.js = self.nc.jetstream()
        from nats.js.api import StreamConfig, StorageType, RetentionPolicy
        await self.js.add_stream(config=StreamConfig(name='DEVBUS_V1',
            subjects=['devbus.commands.*', 'devbus.events.*'], storage=StorageType.FILE,
            retention=RetentionPolicy.LIMITS, max_age=86400, max_bytes=104857600,
            max_msg_size=131072))
        self.transports = []

    async def quiet(self, _): pass

    async def cleanup_bus(self):
        for transport in getattr(self, 'transports', []):
            await transport.close()
        if getattr(self, 'nc', None):
            await self.nc.close()
        if getattr(self, 'server', None):
            self.server.terminate()
            await asyncio.to_thread(self.server.wait, 5)
        self.storage.cleanup()

    async def adapter(self):
        try:
            mod = importlib.import_module('_control_web_devbus_nats')
        except ModuleNotFoundError:
            self.fail('planned events-only NATS adapter is absent')
        config = mod.NatsConfig.from_env({'CONTROL_DEVBUS_ENABLED': '1',
            'DEVBUS_NATS_URL': f'nats://127.0.0.1:{self.port}'})
        transport = await mod.connect(config)
        self.transports.append(transport)
        return transport

    def event(self, kind, message_id):
        return json.dumps(dict(message_id=message_id, task_id='pong-task',
            correlation_id='pong-task', source='worker', target='control', kind=kind,
            created_at='2026-10-06T08:00:00Z', payload={'text': 'PONG'})).encode()

    async def test_events_ack_leave_command_consumer_and_stream_unchanged(self):
        from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
        commands = await self.js.pull_subscribe('devbus.commands.worker',
            durable='dispatcher-worker', stream='DEVBUS_V1',
            config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT, deliver_policy=DeliverPolicy.ALL))
        await self.js.publish('devbus.commands.worker', b'command-stays-pending')
        await self.js.publish('devbus.events.worker', self.event('completed', 'pong-msg'))
        before = await commands.consumer_info()
        config_before = (await self.js.stream_info('DEVBUS_V1')).config.as_dict()
        transport = await self.adapter()
        info = await transport.info()
        self.assertEqual(info['last_seq'], 2)
        messages = await transport.fetch()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].subject, 'devbus.events.worker')
        self.assertEqual(messages[0].sequence, 2)
        await messages[0].ack()
        after = await commands.consumer_info()
        self.assertEqual(after.num_pending, before.num_pending)
        self.assertEqual(after.ack_floor.stream_seq, before.ack_floor.stream_seq)
        self.assertEqual((await self.js.stream_info('DEVBUS_V1')).config.as_dict(), config_before)
        command = (await commands.fetch(batch=1, timeout=1))[0]
        self.assertEqual(command.data, b'command-stays-pending')
        await transport.close()
        # No observer consumer left; the durable executor alone survives.
        consumers = await self.js.consumers_info('DEVBUS_V1')
        self.assertEqual([c.name for c in consumers], ['dispatcher-worker'])
        await commands.unsubscribe()

    async def test_reopen_replay_and_skip_to_live_tail(self):
        await self.js.publish('devbus.events.worker', self.event('accepted', 'accepted-msg'))
        first = await self.adapter()
        first_messages = await first.fetch()
        self.assertEqual(len(first_messages), 1)
        await first_messages[0].ack()
        await first.close()
        second = await self.adapter()
        replay = await second.fetch()
        self.assertEqual(replay[0].data, first_messages[0].data)
        await replay[0].ack()
        await second.skip_to(2)
        await self.js.publish('devbus.events.worker', self.event('completed', 'completed-msg'))
        live = await second.fetch()
        self.assertEqual([m.sequence for m in live], [2])
        await live[0].ack()
        self.assertEqual(await second.pending(), 0)

    async def test_policy_mismatch_refuses_without_reconfiguring_stream(self):
        from nats.js.api import StreamConfig
        await self.js.update_stream(config=StreamConfig(name='DEVBUS_V1',
            subjects=['devbus.commands.*', 'devbus.events.*'], max_age=0))
        before = (await self.js.stream_info('DEVBUS_V1')).config.as_dict()
        try:
            mod = importlib.import_module('_control_web_devbus_nats')
        except ModuleNotFoundError:
            self.fail('planned adapter is absent')
        config = mod.NatsConfig.from_env({'CONTROL_DEVBUS_ENABLED': '1',
            'DEVBUS_NATS_URL': f'nats://127.0.0.1:{self.port}'})
        with self.assertRaises(Exception):
            await mod.connect(config)
        self.assertEqual((await self.js.stream_info('DEVBUS_V1')).config.as_dict(), before)

if __name__ == '__main__': unittest.main()
