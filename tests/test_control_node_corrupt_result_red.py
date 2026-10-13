"""Independent real SQLite result-corruption regression; no implementation read.

The stored malformed result remains below the wire/result byte caps. It must
produce a bounded storage error and leave the public transaction API usable.
"""
import json
import sqlite3
import unittest

import test_control_node_tasks_ledger_red as ledger


class CorruptResultRED(unittest.TestCase):
    setUp = ledger.LedgerRED.setUp
    submit = ledger.LedgerRED.submit
    complete = ledger.LedgerRED.complete
    ingest = ledger.LedgerRED.ingest

    def corrupt_result(self):
        task = self.submit()
        self.complete(task, 'synthetic bounded result')
        original = self.store.get(task)['result']
        nested = '[' * 2000 + ']' * 2000
        self.assertLess(len(nested.encode()), 60000)
        # Discover the persisted projection from actual SQLite metadata/content;
        # no table/column implementation names or private store handles assumed.
        with sqlite3.connect(self.path) as writer:
            matches = []
            for (table,) in writer.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                quoted = '"' + table.replace('"', '""') + '"'
                columns = [row[1] for row in writer.execute('PRAGMA table_info(' + quoted + ')')]
                if 'task_id' not in columns:
                    continue
                row = writer.execute('SELECT * FROM ' + quoted + ' WHERE task_id=?', (task,)).fetchone()
                if row is None:
                    continue
                for column, value in zip(columns, row):
                    if not isinstance(value, str):
                        continue
                    try:
                        decoded = json.loads(value)
                    except ValueError:
                        continue
                    if decoded == original:
                        matches.append((quoted, '"' + column.replace('"', '""') + '"'))
            self.assertEqual(len(matches), 1, 'one durable serialized result projection expected')
            table, column = matches[0]
            writer.execute('UPDATE ' + table + ' SET ' + column + '=? WHERE task_id=?', (nested, task))
        return task

    def test_nested_corrupt_result_returns_storage_and_immediate_count_remains_healthy(self):
        # INV-NLAUNCH-01/03: parse failure is storage failure, never leaked state.
        task = self.corrupt_result()
        error = None
        try:
            reply = self.store.get(task)
        except Exception as caught:
            error = caught
            reply = None
        count = self.store.count()
        self.assertEqual(count, {'total': 1}, 'failed result decode left the transaction unusable')
        self.assertIsNone(error, 'public getter leaked ' + (type(error).__name__ if error else ''))
        self.assertTrue(type(reply) is dict and set(reply) == {'error'} and
                        reply.get('error') == 'storage',
                        'corrupt deeply nested stored result was returned as a successful DTO')


if __name__ == '__main__':
    unittest.main()
