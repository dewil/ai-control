"""Regression RED for legitimate metadata sharing the durable task subject.

Contract amendment: metadata are classified as committed ignored diagnostics,
not task outcomes or poison. Fixtures describe actual agent-bus v1 envelopes;
no runner/core/runtime implementation was read. Synthetic private SQLite only.
"""
import importlib
import json
import sqlite3
import unittest

import test_control_node_tasks_ledger_red as ledger
import test_control_node_runtime_red as runtime


AGENT = 'codex-ai-dev-1'


def metadata(kind='heartbeat', **changes):
    document = dict(message_id=ledger.uid(), task_id='agent-' + AGENT,
        correlation_id='agent-' + AGENT, source=AGENT, target='observers',
        kind=kind, created_at=runtime.stamp(),
        payload={'agent_id': AGENT, 'version': '0.1.0'})
    if kind == 'registration':
        document['payload'] = dict(version='0.1.0', schema_version=1,
            agent_id=AGENT, capabilities=['research.submit'], executor='codex')
    document.update(changes)
    return ledger.encode(document)


def persisted_diagnostics(path):
    """Independent SQLite reader, public data classified without private names."""
    with sqlite3.connect(path, timeout=0) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        result = []
        for (name,) in tables:
            quoted = '"' + name.replace('"', '""') + '"'
            columns = {row[1] for row in connection.execute('PRAGMA table_info(' + quoted + ')')}
            if 'task_id' not in columns:
                result.append((name, tuple(connection.execute('SELECT * FROM ' + quoted))))
        return tuple(result)


class MetadataStoreRED(unittest.TestCase):
    setUp = ledger.LedgerRED.setUp
    reopen = ledger.LedgerRED.reopen
    submit = ledger.LedgerRED.submit

    def test_heartbeat_is_committed_ignored_diagnostic_without_fence(self):
        # INV-NRUN-05: routine heartbeat cannot permanently disable launch.
        before = persisted_diagnostics(self.path)
        self.assertEqual(self.store.ingest(metadata()), {'outcome': 'ignored', 'task_id': None})
        after = persisted_diagnostics(self.path)
        self.assertNotEqual(after, before, 'ignored diagnostic must commit, not silently skip')
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.store.runtime_state(), {'fence': None})
        self.reopen()
        self.assertEqual(persisted_diagnostics(self.path), after)

    def test_registration_and_untrusted_metadata_dict_are_ignored_without_authority(self):
        # INV-NRUN-05 amendment: classify kind, do not invent metadata validation.
        for raw in (metadata('registration'), metadata(payload={'version': [],
                'private_extra': 'synthetic-no-authority', 'agent_id': 'other'})):
            self.assertEqual(self.store.ingest(raw), {'outcome': 'ignored', 'task_id': None})
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.store.runtime_state(), {'fence': None})

    def test_metadata_crafted_existing_task_id_cannot_change_task_projection(self):
        # INV-NRUN-05: kind classification precedes task state dispatch.
        task = self.submit()
        before = self.store.get(task)
        raw = metadata(task_id=task, correlation_id=task)
        self.assertEqual(self.store.ingest(raw), {'outcome': 'ignored', 'task_id': None})
        self.assertEqual(self.store.get(task), before)
        self.assertEqual(self.store.runtime_state(), {'fence': None})

    def test_malformed_metadata_payload_remains_invalid(self):
        # INV-NRUN-05: do not blanket-ACK any document labeled heartbeat.
        for raw in (metadata(payload=[]), metadata(created_at='not-a-timestamp')):
            with self.subTest(wire_size=len(raw)):
                self.assertEqual(self.store.ingest(raw), {'outcome': 'invalid', 'task_id': None})
        self.assertEqual(self.store.list(), [])

    def test_malformed_metadata_envelope_remains_invalid(self):
        # INV-NRUN-05: exact envelope, strict JSON and v1 IDs still apply.
        doc = json.loads(metadata())
        del doc['correlation_id']
        other = json.loads(metadata()); other['extra'] = 'not-v1'
        duplicate = metadata().replace(b'"kind":"heartbeat"', b'"kind":"heartbeat","kind":"heartbeat"')
        for raw in (ledger.encode(doc), ledger.encode(other), duplicate):
            with self.subTest(wire_size=len(raw)):
                self.assertEqual(self.store.ingest(raw), {'outcome': 'invalid', 'task_id': None})
        self.assertEqual(self.store.list(), [])


class MetadataRuntimeRED(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = runtime.RuntimeRED.asyncSetUp
    asyncTearDown = runtime.RuntimeRED.asyncTearDown
    ready = runtime.RuntimeRED.ready
    create = runtime.RuntimeRED.create

    async def test_heartbeat_ack_follows_committed_ignore_and_keeps_admission_ready(self):
        # INV-NRUN-05: the same subject contains task events and routine metadata.
        await self.ready()
        before = persisted_diagnostics(self.path)
        msg = runtime.Message(metadata())
        def before_ack():
            self.assertNotEqual(persisted_diagnostics(self.path), before)
            self.assertEqual(self.store.runtime_state(), {'fence': None})
        msg.on_ack = before_ack
        self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(self.store.runtime_state(), {'fence': None})
        self.assertEqual(msg.acks, 1)
        self.assertEqual(self.runtime.overview()['node']['readiness'], 'ready')
        self.assertEqual(self.store.list(), [])
        self.create('admission survives legitimate heartbeat')

    async def test_registration_ack_has_no_task_outcome_or_global_fence(self):
        # INV-NRUN-05: actual startup registration shares the filtered subject.
        await self.ready()
        msg = runtime.Message(metadata('registration'))
        self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(self.store.runtime_state(), {'fence': None})
        self.assertEqual(msg.acks, 1)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.runtime.overview()['node']['readiness'], 'ready')

    async def test_metadata_storage_failure_must_not_ack(self):
        # INV-NRUN-05: classification does not bypass durable diagnostics.
        await self.ready()
        self.proxy.fail.add('ingest')
        msg = runtime.Message(metadata()); self.transport.messages.append(msg)
        await self.runtime.step()
        self.assertEqual(msg.acks, 0)
        self.assertEqual(self.store.runtime_state(), {'fence': None})

    async def test_fresh_heartbeat_without_retained_registration_allows_attested_launch(self):
        # INV-NRUN-06 amendment: after TTL/replay the old registration is absent.
        projection_api = importlib.import_module('_control_web_devbus')
        projection = projection_api.Projection(clock=lambda: self.now)
        projection.connection('live')
        self.assertTrue(projection.ingest(metadata(), 'devbus.events.' + AGENT, 1))
        self.observer = projection.snapshot()
        agent = next(item for item in self.observer['agents'] if item['agent'] == AGENT)
        self.assertFalse(agent['registered'], 'fixture represents heartbeat-only retained replay')
        self.assertEqual(agent['heartbeat_status'], 'fresh')
        await self.ready()
        task = self.create('owned profile attestation supplies identity/config proof')
        self.assertEqual(self.store.get(task)['execution'], 'waiting')
        self.assertEqual(self.runtime.overview()['node']['capacity'], 'unknown')


if __name__ == '__main__':
    unittest.main()
