"""Independent corruption regression RED for closed private ledger files.

INV-NLAUNCH-01: metadata fail-closed; INV-NLAUNCH-03: storage-error rollback.
Public NodeTaskStore API plus direct SQLite fault injection; no author fix read,
network, credentials, native execution, services or production filesystem I/O.
"""
import sqlite3
import unittest

import test_control_node_tasks_ledger_red as fixtures


class CorruptionLedgerRED(unittest.TestCase):
    setUp=fixtures.LedgerRED.setUp
    submit=fixtures.LedgerRED.submit
    reopen=fixtures.LedgerRED.reopen

    def mutate_closed(self,sql,params=()):
        self.store.close()
        with sqlite3.connect(self.path) as database:
            database.execute(sql,params)

    def assert_constructor_refuses_without_rewrite(self):
        before=self.path.read_bytes();identity=self.path.stat()
        refused=False
        try:
            candidate=self.api.NodeTaskStore(str(self.path),clock=lambda:self.now)
        except ValueError as error:
            refused=True
            self.assertNotIn(str(self.path),str(error))
            self.assertNotIn('synthetic-corrupt',str(error))
        else:
            candidate.close()
        self.assertEqual(self.path.read_bytes(),before,'refusal must not rewrite/repair the existing database')
        self.assertEqual((self.path.stat().st_dev,self.path.stat().st_ino),(identity.st_dev,identity.st_ino))
        self.assertTrue(refused,'constructor must reject invalid singleton metadata with generic ValueError')

    def test_missing_metadata_singleton_rejected_without_recreating_it(self):
        self.mutate_closed('DELETE FROM metadata')
        self.assert_constructor_refuses_without_rewrite()

    def test_blob_metadata_fence_rejected_without_schema_or_data_repair(self):
        # SQLite TEXT affinity permits a BLOB; valid SQL schema is insufficient.
        self.mutate_closed('UPDATE metadata SET fence=? WHERE singleton=1',(sqlite3.Binary(b'synthetic-corrupt-fence'),))
        self.assert_constructor_refuses_without_rewrite()

    def test_unknown_text_metadata_fence_rejected_without_repair(self):
        self.mutate_closed('UPDATE metadata SET fence=? WHERE singleton=1',('synthetic-corrupt-unknown-fence',))
        self.assert_constructor_refuses_without_rewrite()

    def test_corrupt_result_returns_storage_and_rolls_back_before_immediate_count(self):
        task=self.submit('Synthetic corruption regression')
        self.mutate_closed('UPDATE tasks SET result=? WHERE task_id=?',('{',task))
        self.reopen()
        try:result=self.store.get(task)
        except Exception as error:result={'raised_exception_type':type(error).__name__}
        # Separate subtests verify transaction recovery even when get leaked an
        # exception; a later second count is not an acceptable recovery method.
        with self.subTest(operation='corrupt get'):
            self.assertEqual(result,{'error':'storage'})
        with self.subTest(operation='immediate independent healthy count'):
            self.assertEqual(self.store.count(),{'total':1})
        self.store.close()
        with sqlite3.connect(self.path) as database:
            self.assertEqual(database.execute('SELECT result FROM tasks WHERE task_id=?',(task,)).fetchone()[0],'{')


if __name__=='__main__':unittest.main()
