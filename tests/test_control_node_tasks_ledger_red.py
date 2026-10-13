"""Independent closed-ledger RED: spec-alp-task-launch, Python seam.

No ledger implementation was consulted. Wire fixtures follow the public
agent-bus v1 schema. Everything runs against disposable private SQLite files;
no NATS, services, vendor accounts, or inference are used.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
NOW = 1800000000.0
FIELDS = {'message_id', 'task_id', 'correlation_id', 'source', 'target',
          'kind', 'created_at', 'payload'}
DTO_FIELDS = {'schema', 'task_id', 'node_id', 'prompt', 'created_at',
              'updated_at', 'delivery', 'execution', 'result', 'quality',
              'usage', 'coverage'}


def uid():
    return str(uuid.uuid4())


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')


def event(task, kind='accepted', payload=None, **changes):
    doc = dict(message_id=uid(), task_id=task, correlation_id=task,
               source='codex-ai-dev-1', target='control-web', kind=kind,
               created_at='2027-01-15T08:00:00Z',
               payload={} if payload is None else payload)
    doc.update(changes)
    return encode(doc)


class LedgerRED(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec('_control_node_tasks') is None:
            self.fail('missing planned closed ledger: bin/_control_node_tasks.py')
        self.api = importlib.import_module('_control_node_tasks')
        self.tmp = tempfile.TemporaryDirectory(prefix='node-ledger-red-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.directory.chmod(0o700)
        self.path = self.directory / 'tasks.sqlite'
        self.now = NOW
        self.store = self.api.NodeTaskStore(str(self.path), clock=lambda: self.now)
        self.addCleanup(lambda: self.store.close())

    def reopen(self):
        self.store.close()
        self.store = self.api.NodeTaskStore(str(self.path), clock=lambda: self.now)

    def submit(self, prompt='Audit this synthetic text', task=None):
        task = uid() if task is None else task
        result = self.store.submit(task, 'alp', prompt)
        self.assertNotIn('error', result)
        self.assertEqual(result['task_id'], task)
        return task

    def ingest(self, task, kind='accepted', payload=None, **changes):
        return self.store.ingest(event(task, kind, payload, **changes))

    def complete(self, task, text='Synthetic result', **changes):
        return self.ingest(task, 'completed', {'text': text, 'executor': 'codex'}, **changes)

    def test_submit_dto_and_exact_v1_command_survive_reopen(self):
        # INV-NLAUNCH-01: persisted bytes, rather than a regenerated command.
        task = self.submit('Аудит 😀')
        dto = self.store.get(task)
        self.assertEqual(set(dto), DTO_FIELDS)
        self.assertEqual({k: dto[k] for k in ('schema', 'node_id', 'delivery',
                         'execution', 'quality', 'coverage')},
                         dict(schema=1, node_id='alp', delivery='pending',
                              execution='waiting', quality='unreviewed', coverage='complete'))
        self.assertIsNone(dto['result'])
        self.assertIsNone(dto['usage'])
        original = self.store.pending()[0]
        self.assertEqual(set(original), {'task_id', 'message_id', 'wire', 'wire_sha256'})
        self.assertIsInstance(original['wire'], bytes)
        self.assertEqual(hashlib.sha256(original['wire']).hexdigest(), original['wire_sha256'])
        command = json.loads(original['wire'])
        self.assertEqual(set(command), FIELDS)
        self.assertEqual(command['message_id'], original['message_id'])
        self.assertEqual(command['task_id'], task)
        self.assertEqual(command['correlation_id'], task)
        self.assertEqual(command['source'], 'control-web')
        self.assertEqual(command['target'], 'codex-ai-dev-1')
        self.assertEqual(command['kind'], 'submit')
        self.assertEqual(command['payload'], {'prompt': 'Аудит 😀'})
        self.assertEqual(datetime.fromisoformat(command['created_at'].replace('Z', '+00:00')).utcoffset().total_seconds(), 0)
        self.now += 999
        self.reopen()
        self.assertEqual(self.store.submit(task, 'alp', 'Аудит 😀'), dto)
        self.assertEqual(self.store.pending(), [original])

    def test_same_id_competing_submits_have_one_durable_command(self):
        # INV-NLAUNCH-01
        task = uid()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.store.submit(task, 'alp', 'same'), range(16)))
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(len(self.store.pending()), 1)
        self.reopen()
        self.assertEqual(self.store.get(task), results[0])

    def test_request_conflict_and_new_id_same_prompt(self):
        # INV-NLAUNCH-01
        task = self.submit('same')
        before = self.store.get(task)
        self.assertEqual(self.store.submit(task, 'alp', 'different'), {'error': 'conflict'})
        self.assertEqual(self.store.get(task), before)
        self.submit('same')
        self.assertEqual(len(self.store.list()), 2)

    def test_request_validation_counts_utf8_bytes_and_preserves_exact_text(self):
        # INV-NLAUNCH-01
        for request, node, prompt in [('AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA', 'alp', 'ok'), ('bad', 'alp', 'ok'),
                (uid(), 'other', 'ok'), (uid(), 'alp', ''), (uid(), 'alp', 'a\x00b'),
                (uid(), 'alp', 'я' * 16385), (uid(), 'alp', '\ud800'),
                (uid(), 'alp', None), (uid(), 'alp', True)]:
            with self.subTest(node=node, prompt_type=type(prompt).__name__):
                self.assertEqual(self.store.submit(request, node, prompt), {'error': 'invalid_request'})
        task = self.submit('я' * 16384)
        self.assertEqual(self.store.get(task)['prompt'], 'я' * 16384)

    def test_backlog_limit_known_repeat_and_terminal_release(self):
        # INV-NLAUNCH-01
        tasks = [self.submit(str(i)) for i in range(32)]
        self.assertEqual(self.store.submit(uid(), 'alp', 'overflow'), {'error': 'capacity'})
        self.assertEqual(self.store.submit(tasks[0], 'alp', '0')['task_id'], tasks[0])
        self.complete(tasks[0])
        self.submit('new capacity')
        self.assertEqual(len(self.store.list()), 33)

    def test_retained_task_capacity_is_not_freed_by_completion(self):
        # INV-NLAUNCH-01: completed history also consumes the durable 1000 cap.
        first = None
        for _ in range(1000):
            task = self.submit('retained')
            first = task if first is None else first
            self.complete(task)
        self.assertEqual(self.store.submit(uid(), 'alp', 'overflow'), {'error': 'capacity'})
        self.assertEqual(self.store.submit(first, 'alp', 'retained')['task_id'], first)

    def test_unknown_publish_restart_backoff_preserves_original_identity(self):
        # INV-NLAUNCH-02
        task = self.submit()
        original = self.store.pending()[0]
        self.assertEqual(self.store.publication_started(task), {'publish': True})
        self.assertEqual(self.store.get(task)['delivery'], 'unknown')
        self.assertEqual(self.store.get(task)['execution'], 'waiting')
        self.reopen()
        self.assertEqual(self.store.pending(), [original])
        failed = self.store.publish_failed(task)
        self.assertEqual(failed['delivery'], 'unknown')
        self.assertEqual(failed['execution'], 'waiting')
        self.assertEqual(self.store.pending(), [])
        self.now += 61
        self.reopen()
        self.assertEqual(self.store.pending(), [original])

    def test_backoff_never_exceeds_sixty_seconds(self):
        # INV-NLAUNCH-02
        task = self.submit()
        original = self.store.pending()[0]
        for _ in range(12):
            self.store.publication_started(task)
            self.store.publish_failed(task)
            self.assertEqual(self.store.pending(), [])
            self.now += 61
            self.assertEqual(self.store.pending(), [original])

    def test_puback_binding_and_different_stream_sequences(self):
        # INV-NLAUNCH-02: broker acceptance does not imply execution acceptance.
        task = self.submit()
        row = self.store.pending()[0]
        self.store.publication_started(task)
        for mid, digest, seq in [(uid(), row['wire_sha256'], 1),
                (row['message_id'], '0' * 64, 1)]:
            self.assertEqual(self.store.publication(task, mid, digest, seq), {'error': 'conflict'})
        for seq in (0, -1, True, 1.5, '2'):
            self.assertEqual(self.store.publication(task, row['message_id'], row['wire_sha256'], seq), {'error': 'invalid_request'})
        for seq in (10, 10, 20):
            dto = self.store.publication(task, row['message_id'], row['wire_sha256'], seq)
            self.assertEqual(dto['delivery'], 'published')
            self.assertEqual(dto['execution'], 'waiting')
        self.reopen()
        self.assertEqual(self.store.get(task)['delivery'], 'published')
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(len(self.store.list()), 1)

    def test_events_can_confirm_execution_without_puback_and_stop_retry(self):
        # INV-NLAUNCH-02 INV-NLAUNCH-03
        task = self.submit()
        self.store.publication_started(task)
        self.assertEqual(self.ingest(task), {'outcome': 'applied', 'task_id': task})
        dto = self.store.get(task)
        self.assertEqual(dto['execution'], 'accepted')
        self.assertEqual(dto['delivery'], 'unknown')
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.publication_started(task), {'publish': False})

    def test_strict_binding_ignores_foreign_events_without_creating_tasks(self):
        # INV-NLAUNCH-03
        task = self.submit()
        before = self.store.get(task)
        for changes in ({'source': 'foreign'}, {'target': 'other'},
                        {'correlation_id': uid()}, {'task_id': uid()}):
            with self.subTest(changes=changes):
                result = self.ingest(task, **changes)
                self.assertEqual(result['outcome'], 'ignored')
                self.assertIn(result['task_id'], (None, task))
                self.assertEqual(self.store.get(task), before)
                self.assertEqual(len(self.store.list()), 1)

    def test_strict_wire_and_payload_validation(self):
        # INV-NLAUNCH-03
        task = self.submit()
        valid = event(task)
        doc = json.loads(valid)
        invalid = [b'{', b'\xff', b'[]', b' ' * (126 * 1024 + 1),
                   valid[:-1] + b',"payload":{}}',
                   event(task, created_at='no-timezone'), event(task, extra=True),
                   event(task, kind='submit', payload={'prompt': 'x'}),
                   event(task, payload={'extra': 'unexpected'}),
                   event(task, 'completed', {'text': 'ok', 'executor': 'other'}),
                   event(task, 'completed', {'text': 'ok', 'executor': 'codex', 'output_truncated': 1}),
                   event(task, 'completed', {'text': 'ok', 'executor': 'codex', 'extra': True}),
                   event(task, 'failed', {'reason': '/private/raw/exception', 'exit_code': 1}),
                   event(task, 'failed', {'reason': 'executor_exit', 'exit_code': True})]
        doc['payload'] = {'value': float('nan')}
        invalid.append(json.dumps(doc).encode())
        before = self.store.get(task)
        for raw in invalid:
            with self.subTest(length=len(raw)):
                self.assertEqual(self.store.ingest(raw), {'outcome': 'invalid', 'task_id': None})
                self.assertEqual(self.store.get(task), before)

    def test_exact_event_bytes_deduplicate_but_reencoding_conflicts(self):
        # INV-NLAUNCH-03
        task = self.submit()
        raw = event(task)
        self.assertEqual(self.store.ingest(raw)['outcome'], 'applied')
        self.reopen()
        before = self.store.get(task)
        self.assertEqual(self.store.ingest(raw), {'outcome': 'duplicate', 'task_id': task})
        self.assertEqual(self.store.get(task), before)
        different_bytes = json.dumps(json.loads(raw), indent=2).encode()
        self.assertEqual(self.store.ingest(different_bytes), {'outcome': 'conflict', 'task_id': task})
        self.assertEqual(self.store.get(task)['execution'], 'needs_attention')
        self.assertEqual(self.store.get(task)['coverage'], 'partial')

    def test_reordered_events_never_roll_back_terminal_and_result_is_durable(self):
        # INV-NLAUNCH-04
        task = self.submit()
        self.ingest(task, 'running')
        self.ingest(task, 'accepted')
        self.assertEqual(self.store.get(task)['execution'], 'running')
        text = '<script>alert(1)</script>\n**Plain result**'
        self.complete(task, text)
        self.ingest(task, 'accepted')
        self.ingest(task, 'running')
        self.reopen()
        dto = self.store.get(task)
        self.assertEqual(dto['execution'], 'completed')
        self.assertEqual(dto['result']['text'], text)
        self.assertEqual(dto['result']['executor'], 'codex')
        self.assertEqual(dto['quality'], 'unreviewed')
        self.assertIsNone(dto['usage'])
        self.now += 10 ** 7
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.publication_started(task), {'publish': False})

    def test_same_terminal_new_event_id_preserves_first_result(self):
        # INV-NLAUNCH-04
        task = self.submit()
        self.complete(task)
        result = self.store.get(task)['result']
        self.complete(task)
        self.assertEqual(self.store.get(task)['execution'], 'completed')
        self.assertEqual(self.store.get(task)['result'], result)

    def test_changed_terminal_payload_requires_attention_and_preserves_history(self):
        # INV-NLAUNCH-04
        task = self.submit()
        self.complete(task, 'first')
        first = self.store.get(task)['result']
        self.complete(task, 'different')
        dto = self.store.get(task)
        self.assertEqual(dto['execution'], 'needs_attention')
        self.assertEqual(dto['coverage'], 'partial')
        self.assertEqual(dto['result'], first)
        self.complete(task, 'first')
        self.assertEqual(self.store.get(task)['execution'], 'needs_attention')

    def test_conflicting_terminal_kind_requires_attention(self):
        # INV-NLAUNCH-04
        task = self.submit()
        self.complete(task)
        self.ingest(task, 'failed', {'reason': 'executor_exit', 'exit_code': 1})
        self.assertEqual(self.store.get(task)['execution'], 'needs_attention')
        self.assertEqual(self.store.get(task)['coverage'], 'partial')

    def test_failed_and_explicit_interruption_are_never_automatically_retried(self):
        # INV-NLAUNCH-04
        for kind, payload in [('failed', {'reason': 'timeout', 'exit_code': None}),
                ('needs_attention', {'reason': 'interrupted; outcome unknown; automatic retry disabled'})]:
            task = self.submit()
            self.ingest(task, kind, payload)
            self.assertEqual(self.store.get(task)['execution'], kind)
            self.now += 10000
            self.reopen()
            self.assertEqual(self.store.pending(), [])
            self.assertEqual(self.store.publication_started(task), {'publish': False})

    def test_result_limit_is_serialized_utf8_and_truncation_flag_survives(self):
        # INV-NLAUNCH-03 INV-NLAUNCH-04
        task = self.submit()
        payload = {'text': 'я' * 30000, 'executor': 'codex'}
        self.assertGreater(len(encode(payload)), 60000)
        self.assertEqual(self.ingest(task, 'completed', payload)['outcome'], 'invalid')
        self.assertIsNone(self.store.get(task)['result'])
        payload = {'text': 'x' * 59900, 'executor': 'codex', 'output_truncated': True}
        self.assertLessEqual(len(encode(payload)), 60000)
        self.assertEqual(self.ingest(task, 'completed', payload)['outcome'], 'applied')
        self.reopen()
        self.assertTrue(self.store.get(task)['result']['output_truncated'])

    def test_retention_gap_is_sticky_and_prevents_rerun_after_restart(self):
        # INV-NLAUNCH-02 INV-NLAUNCH-03
        task = self.submit()
        done = self.submit()
        self.complete(done)
        self.assertEqual(self.store.mark_gap(), {'affected': 1})
        self.assertEqual(self.store.get(task)['coverage'], 'partial')
        self.assertEqual(self.store.get(task)['execution'], 'waiting')
        self.assertEqual(self.store.get(done)['coverage'], 'complete')
        self.now += 10000
        self.reopen()
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.publication_started(task), {'publish': False})
        self.complete(task)
        self.assertEqual(self.store.get(task)['coverage'], 'partial')
        self.assertEqual(self.store.get(task)['execution'], 'completed')

    def test_event_retention_cap_preserves_task_as_attention(self):
        # INV-NLAUNCH-03: no unbounded event journal.
        task = self.submit()
        for _ in range(256):
            self.ingest(task)
        self.ingest(task)
        self.reopen()
        self.assertEqual(self.store.get(task)['execution'], 'needs_attention')
        self.assertEqual(self.store.get(task)['coverage'], 'partial')

    def test_read_limits_order_and_unknown_task(self):
        # INV-NLAUNCH-01 INV-NLAUNCH-03
        tasks = [self.submit(str(i)) for i in range(4)]
        self.assertEqual([r['task_id'] for r in self.store.list(2)], sorted(tasks)[:2])
        self.assertEqual(self.store.get(uid()), {'error': 'not_found'})
        for limit in (0, -1, 51, True, '2'):
            self.assertEqual(self.store.list(limit), {'error': 'invalid_request'})

    def test_private_file_permissions_and_wal_mode(self):
        # INV-NLAUNCH-01: real filesystem/SQLite, not mocked storage.
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')

    def assert_unsafe(self, path):
        with self.assertRaises(ValueError) as caught:
            self.api.NodeTaskStore(str(path), clock=lambda: self.now)
        self.assertNotIn(str(path), str(caught.exception))

    def test_existing_symlink_and_hardlink_are_rejected_without_touching_target(self):
        # INV-NLAUNCH-01
        self.store.close()
        original = self.path.read_bytes()
        link = self.directory / 'link.sqlite'
        link.symlink_to(self.path)
        self.assert_unsafe(link)
        link.unlink()
        os.link(self.path, link)
        self.assert_unsafe(link)
        self.assertEqual(self.path.read_bytes(), original)

    def test_unsafe_parent_and_existing_mode_are_rejected(self):
        # INV-NLAUNCH-01
        self.store.close()
        self.path.chmod(0o644)
        self.assert_unsafe(self.path)
        self.path.chmod(0o600)
        self.directory.chmod(0o755)
        self.assert_unsafe(self.path)
        self.directory.chmod(0o700)
        alias = self.directory / 'alias'
        alias.symlink_to(self.directory, target_is_directory=True)
        self.assert_unsafe(alias / 'tasks.sqlite')

    def test_existing_non_database_directory_and_unknown_schema_rejected(self):
        # INV-NLAUNCH-01
        foreign = self.directory / 'foreign.sqlite'
        foreign.write_bytes(b'foreign non database file')
        foreign.chmod(0o600)
        self.assert_unsafe(foreign)
        self.assertEqual(foreign.read_bytes(), b'foreign non database file')
        self.assert_unsafe(self.directory)
        unknown = self.directory / 'future.sqlite'
        with sqlite3.connect(unknown) as connection:
            connection.execute('PRAGMA user_version=999')
            connection.execute('CREATE TABLE unrelated(value TEXT)')
        unknown.chmod(0o600)
        self.assert_unsafe(unknown)

    def test_process_death_after_commit_preserves_task_and_unknown_publish(self):
        # INV-NLAUNCH-01 INV-NLAUNCH-02: exit without close/checkpoint.
        child_path = self.directory / 'crashed.sqlite'
        task = uid()
        program = '''import base64,json,os,sys
sys.path.insert(0,sys.argv[1])
from _control_node_tasks import NodeTaskStore
s=NodeTaskStore(sys.argv[2],clock=lambda:1800000000.0)
d=s.submit(sys.argv[3],"alp","crash fixture")
assert "error" not in d,d
r=s.pending()[0]
assert s.publication_started(sys.argv[3])=={"publish":True}
print(json.dumps({"wire":base64.b64encode(r["wire"]).decode(),"message_id":r["message_id"]}),flush=True)
os._exit(0)
'''
        result = subprocess.run([sys.executable, '-c', program, str(ROOT / 'bin'),
                                 str(child_path), task], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        store = self.api.NodeTaskStore(str(child_path), clock=lambda: NOW)
        try:
            self.assertEqual(store.get(task)['delivery'], 'unknown')
            row = store.pending()[0]
            self.assertEqual(row['wire'], base64.b64decode(record['wire']))
            self.assertEqual(row['message_id'], record['message_id'])
        finally:
            store.close()

    def test_commit_failure_never_returns_submit_or_event_ack_success(self):
        # INV-NLAUNCH-01 INV-NLAUNCH-03: inject SQLITE_FULL at stdlib commit seam.
        # This exercises SQL transactions without depending on ledger tables,
        # connection attribute names, private helpers, or filesystem capacity.
        self.store.close()
        armed = [False]
        real_connect = sqlite3.connect

        class FullOnCommit(sqlite3.Connection):
            def commit(connection):
                if armed[0]:
                    connection.rollback()
                    raise sqlite3.OperationalError('database or disk is full')
                return super().commit()

            def execute(connection, sql, *args, **kwargs):
                if armed[0] and sql.strip().upper().startswith(('COMMIT', 'END')):
                    connection.rollback()
                    raise sqlite3.OperationalError('database or disk is full')
                return super().execute(sql, *args, **kwargs)

            def __exit__(connection, kind, value, traceback):
                if armed[0] and kind is None:
                    connection.rollback()
                    raise sqlite3.OperationalError('database or disk is full')
                return super().__exit__(kind, value, traceback)

        def connect(*args, **kwargs):
            kwargs['factory'] = FullOnCommit
            return real_connect(*args, **kwargs)

        with patch.object(sqlite3, 'connect', connect):
            # Also support the ordinary ``from sqlite3 import connect`` style.
            importlib.reload(self.api)
            self.store = self.api.NodeTaskStore(str(self.path), clock=lambda: self.now)
            task = self.submit()
            original = self.store.get(task)
            other = uid()
            armed[0] = True
            self.assertEqual(self.store.submit(other, 'alp', 'disk full'), {'error': 'storage'})
            self.assertEqual(self.store.publication_started(task), {'error': 'storage'})
            raw = event(task, 'completed', {'text': 'durable only', 'executor': 'codex'})
            self.assertEqual(self.store.ingest(raw), {'error': 'storage'})
            armed[0] = False
            self.reopen()
            self.assertEqual(self.store.get(other), {'error': 'not_found'})
            self.assertEqual(self.store.get(task), original)
            self.assertEqual(self.store.ingest(raw), {'outcome': 'applied', 'task_id': task})
            self.assertEqual(self.store.submit(other, 'alp', 'disk full')['task_id'], other)
        importlib.reload(self.api)


if __name__ == '__main__':
    unittest.main()
