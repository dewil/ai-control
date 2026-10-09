"""Supplementary source-blind regressions from the frozen devbus contract.

INV-DEVBUS-03 INV-DEVBUS-06 INV-DEVBUS-08 FR-BUS-02
No implementation source, services, native runtime or network is inspected.
"""
import asyncio
import json
import time
import unittest

from test_control_web_devbus_red import feature, wire, NOW, Message, Transport


class ProjectionReviewRED(unittest.TestCase):
    def setUp(self):
        self.api = feature(self)

    def test_evicted_global_dedup_keeps_task_transitions_unique(self):
        # INV-DEVBUS-03: global event replay may reappear; task transitions do not duplicate.
        projection = self.api.Projection(limits=self.api.Limits(dedup=1), clock=lambda: NOW)
        accepted = wire('accepted', mid='old', task='task1')
        completed = wire('completed', mid='new', task='task1', payload={'text': 'done'})
        self.assertTrue(projection.ingest(accepted, 'devbus.events.worker1', 1))
        self.assertTrue(projection.ingest(completed, 'devbus.events.worker1', 2))
        projection.ingest(accepted, 'devbus.events.worker1', 1)
        task = projection.snapshot()['tasks'][0]
        self.assertEqual(task['state'], 'completed')
        self.assertEqual([event['message_id'] for event in task['transitions']], ['old', 'new'])
        self.assertEqual([event['sequence'] for event in task['transitions']], [1, 2])

    def test_transition_ttl_uses_each_events_observed_age(self):
        # INV-DEVBUS-04 INV-DEVBUS-06: task refresh must not renew old transitions.
        now = [NOW]
        projection = self.api.Projection(clock=lambda: now[0])
        projection.coverage(1, 2, 10, 1024, replay_complete=True)
        self.assertTrue(projection.ingest(wire('accepted', mid='A'), 'devbus.events.worker1', 1))
        now[0] += 9
        self.assertTrue(projection.ingest(wire('running', mid='B'), 'devbus.events.worker1', 2))
        now[0] += 2
        snapshot = projection.snapshot()
        self.assertEqual(len(snapshot['tasks']), 1)
        self.assertEqual(snapshot['tasks'][0]['state'], 'running')
        self.assertEqual([event['message_id'] for event in snapshot['events']], ['B'])
        self.assertEqual([event['message_id'] for event in snapshot['tasks'][0]['transitions']], ['B'])

    def test_registration_metadata_accepts_capability_and_semantic_version_grammar(self):
        # INV-DEVBUS-06: metadata grammar includes dots/colons; envelope IDs unchanged.
        projection = self.api.Projection(clock=lambda: NOW)
        payload = {'agent_id': 'worker1',
                   'capabilities': ['research.submit', 'questions:answer', 'bad whitespace', 'x'*81],
                   'executor': 'codex', 'version': '0.1.0', 'schema_version': 1}
        self.assertTrue(projection.ingest(wire('registration', payload=payload), 'devbus.events.worker1', 1))
        snapshot = projection.snapshot()
        self.assertEqual(len(snapshot['agents']), 1)
        agent = snapshot['agents'][0]
        self.assertEqual(agent['agent'], 'worker1')
        self.assertEqual(agent['capabilities'], ['research.submit', 'questions:answer'])
        self.assertEqual(agent['version'], '0.1.0')
        self.assertEqual(snapshot['tasks'], [])

    def test_json_credential_assignments_are_scrubbed_in_result(self):
        # INV-DEVBUS-06: assignments may have JSON quotes and whitespace.
        projection = self.api.Projection(clock=lambda: NOW)
        text = '{"token":"synthetic-json-token", "password": "synthetic-json-password", "api_key":"synthetic-json-api-key", "secret":"synthetic-json-secret", "authorization": "synthetic-json-auth"}'
        self.assertTrue(projection.ingest(wire('completed', payload={'text': text}), 'devbus.events.worker1', 1))
        snapshot = projection.snapshot()
        self.assertIsInstance(snapshot['tasks'][0]['result'], str)
        for value in ('synthetic-json-token', 'synthetic-json-password', 'synthetic-json-api-key', 'synthetic-json-secret', 'synthetic-json-auth'):
            self.assertNotIn(value, json.dumps(snapshot))


class ObserverReplayDeadlineReviewRED(unittest.IsolatedAsyncioTestCase):
    async def test_slow_ack_batch_cannot_extend_replay_past_total_budget(self):
        # INV-DEVBUS-06 INV-DEVBUS-08: total replay budget includes ACK processing.
        api = feature(self)
        projection = api.Projection(clock=lambda: NOW)

        class SlowAck(Message):
            async def ack(self):
                await asyncio.sleep(1)
                self.acks += 1

        class Replay(Transport):
            def __init__(self):
                super().__init__()
                self.pending_value = 1000
                self.sent = 0
                self.metadata['last_seq'] = 1000

            async def fetch(self):
                self.fetches += 1
                if self.skips:
                    await asyncio.sleep(.01)
                    return []
                result = [SlowAck(sequence=self.sent+i+1) for i in range(32)]
                self.sent += 32
                return result

        transport = Replay()

        async def connect():
            return transport

        observer = api.Observer(projection, connect, retry_seconds=.01, operation_timeout=5)
        started = time.monotonic()
        try:
            await observer.start()

            async def skipped():
                while not transport.skips:
                    await asyncio.sleep(.01)

            # One-second scheduling/operation margin around the frozen ten-second budget.
            await asyncio.wait_for(skipped(), 11)
            self.assertLessEqual(time.monotonic()-started, 11.2)
            self.assertEqual(transport.skips, [1001])
            snapshot = projection.snapshot()
            self.assertFalse(snapshot['coverage']['replay_complete'])
            self.assertEqual(snapshot['coverage']['mode'], 'partial')
            self.assertIn('replay_incomplete', snapshot['coverage']['issues'])
        finally:
            await asyncio.wait_for(observer.stop(), 1)


if __name__ == '__main__':
    unittest.main()
