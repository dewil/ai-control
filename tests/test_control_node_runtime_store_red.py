"""Independent first-release core amendments, INV-NRUN-03/07.

Only public API, existing RED fixture conventions and SQLite metadata consulted.
Frozen ledger tests are unchanged. Disposable files; no transport or inference.
"""
import sqlite3
import time
import unittest

import test_control_node_tasks_ledger_red as fixtures


class RuntimeStoreRED(unittest.TestCase):
    setUp = fixtures.LedgerRED.setUp
    reopen = fixtures.LedgerRED.reopen
    submit = fixtures.LedgerRED.submit
    complete = fixtures.LedgerRED.complete
    ingest = fixtures.LedgerRED.ingest

    def required(self, name):
        self.assertTrue(callable(getattr(self.store, name, None)),
                        'INV-NRUN-07 missing public NodeTaskStore.' + name)
        return getattr(self.store, name)

    def test_recent_selects_latest_50_of_57_and_preserves_list_ascending(self):
        # INV-NRUN-07: reversing list(50) loses seven latest tasks.
        expected = []
        for index in range(57):
            self.now += index % 3 == 0  # ties exercise task_id DESC.
            task = self.submit(str(index))
            self.complete(task)
            expected.append(self.store.get(task))
        ascending = sorted(expected, key=lambda row: (row['created_at'], row['task_id']))
        recent = self.required('recent')
        self.assertEqual(self.store.list(), ascending[:50])
        self.assertEqual(recent(), ascending[::-1][:50])
        self.assertEqual(recent(1), ascending[-1:])
        self.reopen()
        self.assertEqual(self.store.recent(50), ascending[::-1][:50])

    def test_recent_limits_and_count_include_completed_history(self):
        # INV-NRUN-07 and DESIGN closure count, no reverse-window count.
        recent, count = self.required('recent'), self.required('count')
        self.assertEqual(count(), {'total': 0})
        for limit in (0, 51, -1, True, 1.5, '2', None):
            with self.subTest(limit=limit):
                self.assertEqual(recent(limit), {'error': 'invalid_request'})
        first = self.submit()
        self.complete(first)
        self.submit()
        self.assertEqual(count(), {'total': 2})
        self.reopen()
        self.assertEqual(self.store.count(), {'total': 2})

    def test_expanded_wire_cap_refuses_atomically_before_outbox(self):
        # INV-NRUN-07: valid raw UTF8 bytes can expand sixfold in JSON.
        task = fixtures.uid()
        self.assertEqual(self.store.submit(task, 'alp', '\x01' * 32768),
                         {'error': 'invalid_request'})
        self.assertEqual(self.store.get(task), {'error': 'not_found'})
        self.assertEqual(self.store.pending(), [])
        self.reopen()
        self.assertEqual(self.store.get(task), {'error': 'not_found'})
        # A refusal reserves neither ID nor capacity; ordinary exact-max works.
        self.assertEqual(self.store.submit(task, 'alp', 'x' * 32768)['task_id'], task)
        self.assertLessEqual(len(self.store.pending()[0]['wire']), 126 * 1024)

    def test_gap_fence_survives_empty_ledger_and_reopen_first_reason_sticky(self):
        # INV-NRUN-05/07: no tasks cannot erase the durable global fence.
        state = self.required('runtime_state')
        self.assertEqual(state(), {'fence': None})
        self.assertEqual(self.store.mark_gap(reason='invalid_event'), {'affected': 0})
        self.reopen()
        self.assertEqual(self.store.runtime_state(), {'fence': 'invalid_event'})
        self.assertEqual(self.store.mark_gap(reason='id_conflict'), {'affected': 0})
        self.assertEqual(self.store.runtime_state(), {'fence': 'invalid_event'})
        self.reopen()
        self.assertEqual(self.store.runtime_state(), {'fence': 'invalid_event'})

    def test_gap_updates_tasks_and_fence_together_without_terminal_regression(self):
        # INV-NRUN-05/07, default reason remains compatible with frozen core.
        self.required('runtime_state')
        waiting = self.submit()
        completed = self.submit()
        self.complete(completed)
        before = self.store.get(completed)
        self.assertEqual(self.store.mark_gap(), {'affected': 1})
        self.reopen()
        self.assertEqual(self.store.runtime_state(), {'fence': 'retention_gap'})
        self.assertEqual(self.store.get(waiting)['coverage'], 'partial')
        self.assertEqual(self.store.get(completed), before)
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.mark_gap(reason='anything'), {'error': 'invalid_request'})
        self.assertEqual(self.store.runtime_state(), {'fence': 'retention_gap'})

    def test_persisted_fence_blocks_new_committed_rows_from_outbox(self):
        # INV-NRUN-05/07: stale caller readiness must not bypass the core fence.
        self.required('runtime_state')
        self.store.mark_gap()
        task = self.submit('pure core submit can still commit')
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.publication_started(task), {'publish': False})
        self.reopen()
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.publication_started(task), {'publish': False})

    def test_first_release_schema2_and_old_schema1_refused_without_rewrite(self):
        # INV-NRUN-07: absence of deployed data permits refusal, no migration.
        self.assertEqual(getattr(self.api, 'SCHEMA_VERSION', None), 2)
        task = self.submit()
        self.store.close()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            db.execute('PRAGMA user_version=1')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.api.NodeTaskStore(str(self.path))
        self.assertEqual(self.path.read_bytes(), before)

    def test_writer_lock_refusal_is_bounded_to_one_second(self):
        # INV-NRUN-03: actual SQLite lock, not an implementation timeout constant.
        with sqlite3.connect(self.path, timeout=0) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            started = time.monotonic()
            result = self.store.submit(fixtures.uid(), 'alp', 'locked')
            elapsed = time.monotonic() - started
            self.assertEqual(result, {'error': 'storage'})
            self.assertLess(elapsed, 1.20, 'SQLite busy timeout must be <=1s (small scheduling margin)')
            blocker.rollback()
        self.assertEqual(self.store.pending(), [])


if __name__ == '__main__':
    unittest.main()
