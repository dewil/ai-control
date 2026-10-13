"""Independent supplemental acceptance cases from core SOURCE findings.

Public API plus SQLite's own schema metadata; no implementation was read.
The original 28 RED cases remain unchanged.
"""
import sqlite3
import unittest

import test_control_node_tasks_ledger_red as fixtures


def quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


class SupplementalLedgerRED(unittest.TestCase):
    setUp = fixtures.LedgerRED.setUp
    reopen = fixtures.LedgerRED.reopen
    submit = fixtures.LedgerRED.submit
    complete = fixtures.LedgerRED.complete
    ingest = fixtures.LedgerRED.ingest

    def assert_unsafe(self, path):
        try:
            accepted = self.api.NodeTaskStore(str(path), clock=lambda: self.now)
        except ValueError as error:
            self.assertNotIn(str(path), str(error))
        else:
            accepted.close()
            self.fail('unsafe path/schema accepted')

    def test_private_parent_does_not_hide_writable_nonsticky_ancestor(self):
        # INV-NLAUNCH-01: another UID can rename the private subtree.
        ancestor = self.directory / 'unsafe-ancestor'
        ancestor.mkdir(mode=0o700)
        private = ancestor / 'private'
        private.mkdir(mode=0o700)
        for mode in (0o770, 0o777):
            with self.subTest(ancestor_mode=oct(mode)):
                ancestor.chmod(mode)
                candidate = private / ('tasks-' + str(mode) + '.sqlite')
                self.assert_unsafe(candidate)
                self.assertFalse(candidate.exists())
        # Existing fixture creation under the sticky /var/tmp is positive proof
        # that ordinary sticky system temporary ancestors remain usable.

    def test_same_version_and_columns_do_not_replace_key_and_index_validation(self):
        # INV-NLAUNCH-01: retain version, column types/defaults, and stored data.
        # Metadata comes from a valid disposable store, not implementation SQL.
        self.submit()
        self.store.close()
        with sqlite3.connect(self.path) as original:
            version = original.execute('PRAGMA user_version').fetchone()[0]
            tables = original.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            missing_keys = self.directory / 'missing-keys.sqlite'
            with sqlite3.connect(missing_keys) as broken:
                broken.execute('PRAGMA user_version=' + str(version))
                had_key = False
                for (name,) in tables:
                    columns = original.execute('PRAGMA table_info(' + quoted(name) + ')').fetchall()
                    had_key |= any(column[5] for column in columns)
                    definitions = []
                    for _, column, kind, required, default, _ in columns:
                        definition = quoted(column) + ' ' + kind
                        if required:
                            definition += ' NOT NULL'
                        if default is not None:
                            definition += ' DEFAULT ' + default
                        definitions.append(definition)
                    broken.execute('CREATE TABLE ' + quoted(name) + '(' + ','.join(definitions) + ')')
                    rows = original.execute('SELECT * FROM ' + quoted(name)).fetchall()
                    broken.executemany('INSERT INTO ' + quoted(name) + ' VALUES (' +
                                       ','.join('?' for _ in columns) + ')', rows)
                self.assertTrue(had_key, 'valid ledger must have durable identity keys')
            missing_keys.chmod(0o600)
            with self.subTest(missing='primary/unique keys'):
                self.assert_unsafe(missing_keys)

            missing_indexes = self.directory / 'missing-indexes.sqlite'
            with sqlite3.connect(missing_indexes) as broken:
                original.backup(broken)
                indexes = broken.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall()
                self.assertTrue(indexes, 'ledger must index bounded queue/event lookups')
                for (name,) in indexes:
                    broken.execute('DROP INDEX ' + quoted(name))
            missing_indexes.chmod(0o600)
            with self.subTest(missing='explicit indexes'):
                self.assert_unsafe(missing_indexes)

    def test_late_completion_retains_first_result_without_resolving_attention(self):
        # INV-NLAUNCH-03 INV-NLAUNCH-04: uncertainty and result retention differ.
        task = self.submit()
        self.ingest(task, 'needs_attention', {
            'reason': 'interrupted; outcome unknown; automatic retry disabled'})
        self.assertEqual(self.store.get(task)['execution'], 'needs_attention')
        self.assertIsNone(self.store.get(task)['result'])
        self.complete(task, 'Recovered first result')
        self.reopen()
        dto = self.store.get(task)
        self.assertEqual(dto['execution'], 'needs_attention')
        self.assertEqual(dto['coverage'], 'partial')
        self.assertIsNotNone(dto['result'])
        self.assertEqual(dto['result']['text'], 'Recovered first result')
        self.complete(task, 'Conflicting later result')
        self.assertEqual(self.store.get(task)['result'], dto['result'])
        self.assertEqual(self.store.pending(), [])

    def test_overcap_events_do_not_keep_touching_attention_projection(self):
        # INV-NLAUNCH-03: diagnostics may count rejected, unretained IDs.
        task = self.submit()
        for _ in range(256):
            self.ingest(task)
        self.now += 1
        overflow = fixtures.event(task)
        self.store.ingest(overflow)
        attention = self.store.get(task)
        self.assertEqual(attention['execution'], 'needs_attention')
        self.assertEqual(attention['coverage'], 'partial')
        for raw in (overflow, fixtures.event(task), overflow):
            self.now += 10
            self.store.ingest(raw)
            self.assertEqual(self.store.get(task), attention)
        self.reopen()
        self.assertEqual(self.store.get(task), attention)


if __name__ == '__main__':
    unittest.main()
