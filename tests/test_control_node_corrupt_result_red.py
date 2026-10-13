"""Independent real SQLite result-corruption regression; no implementation read.

The stored malformed result remains below the wire/result byte caps. It must
produce a bounded storage error and leave the public transaction API usable.
"""
import json
import sqlite3
import sys
import unittest

import test_control_node_tasks_ledger_red as ledger


class CorruptResultRED(unittest.TestCase):
    setUp = ledger.LedgerRED.setUp
    submit = ledger.LedgerRED.submit
    complete = ledger.LedgerRED.complete
    ingest = ledger.LedgerRED.ingest

    def corrupt_result(self, depth=2000):
        task = self.submit()
        self.complete(task, 'synthetic bounded result')
        original = self.store.get(task)['result']
        nested = '[' * depth + ']' * depth
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

    def assert_storage_and_count_healthy(self, task):
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

    def test_nested_corrupt_result_returns_storage_and_immediate_count_remains_healthy(self):
        # INV-NLAUNCH-01/03: result must retain its declared exact dict shape.
        self.assert_storage_and_count_healthy(self.corrupt_result())

    def test_actual_decoder_recursion_error_rolls_back_and_count_remains_healthy(self):
        # INV-NLAUNCH-01/03: real parser failure, no mock/recursion-limit changes.
        # Python3.12 C JSON parser accepts depths beyond Python's reported limit;
        # select the first real failing depth while remaining under60000 bytes.
        depth = min(sys.getrecursionlimit() + 100, 29999)
        while True:
            try:
                json.loads('[' * depth + ']' * depth)
            except RecursionError:
                break
            if depth == 29999:
                self.fail('decoder recursion cannot be reached within bounded result fixture')
            depth = min(depth * 2, 29999)
        self.assert_storage_and_count_healthy(self.corrupt_result(depth))


if __name__ == '__main__':
    unittest.main()
