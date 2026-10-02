"""Public-contract regressions for FR-CXTASK-LIFE-02/05.

Only public API and OS directory descriptors are inspected; no journal layout
or lifecycle implementation is assumed. These tests supplement blind tests.
"""
import importlib.util
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'blind_lifecycle_contract', Path(__file__).with_name('test-codex-task-lifecycle.py'))
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
lifecycle = contract.lifecycle


class DurabilityRegression(unittest.TestCase):
    def setUp(self):
        # Reuse only the independently written public-contract fixture.
        self.fixture = contract.LifecycleAcceptance()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.journal = self.fixture.root / 'new-parent' / 'new-child' / 'journal'
        self.actual_fsync = os.fsync

    def directory(self, fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            return Path(os.readlink('/proc/self/fd/' + str(fd))).resolve()
        return None

    def attempt(self):
        f = self.fixture
        f.adapter = f.reopen()
        f.prepare()
        return f.adapter.submit(f.operation, deadline=10)

    def test_FR_CXTASK_LIFE_02_nested_journal_parent_fsync_failure_blocks_effect(self):
        f = self.fixture
        parent_seen = []
        def fail_parent(fd):
            directory = self.directory(fd)
            if directory == f.root:
                parent_seen.append(directory)
                raise OSError('parent directory sync failed')
            return self.actual_fsync(fd)
        with patch.object(os, 'fsync', side_effect=fail_parent):
            with self.assertRaises(lifecycle.JournalError):
                self.attempt()
        self.assertTrue(parent_seen, 'new directory entry requires syncing its existing parent')
        self.assertEqual(f.transport.count('turn/start'), 0)

    def test_FR_CXTASK_LIFE_02_retry_cached_directory_redoes_parent_durability(self):
        f = self.fixture
        failed = []
        def fail_parent(fd):
            if self.directory(fd) == f.root:
                failed.append(True)
                raise OSError('parent directory sync failed')
            return self.actual_fsync(fd)
        with patch.object(os, 'fsync', side_effect=fail_parent):
            with self.assertRaises(lifecycle.JournalError):
                self.attempt()
        self.assertTrue(failed)
        self.assertTrue((f.root / 'new-parent').is_dir(), 'failed sync leaves cached entry')
        self.assertEqual(f.transport.count('turn/start'), 0)
        synced = []
        def record_sync(fd):
            self.actual_fsync(fd)
            directory = self.directory(fd)
            if directory is not None:
                synced.append(directory)
        def check_before_start(created):
            self.assertIn(f.root, synced, 'cached existence is not durable parent-entry evidence')
        f.transport.start_hook = check_before_start
        with patch.object(os, 'fsync', side_effect=record_sync):
            result = self.attempt()
        self.assertEqual(result.phase, 'running')
        self.assertEqual(f.transport.count('turn/start'), 1)

    def test_FR_CXTASK_LIFE_02_post_replace_directory_fsync_failure_blocks_start(self):
        f = self.fixture
        f.adapter = f.reopen()
        f.prepare()
        replaces = []
        actual_replace = os.replace
        def record_replace(*args, **kwargs):
            result = actual_replace(*args, **kwargs)
            replaces.append(True)
            return result
        def fail_receipt_sync(fd):
            if replaces and self.directory(fd) == f.journal.resolve():
                raise OSError('directory sync after atomic replace failed')
            return self.actual_fsync(fd)
        with patch.object(os, 'replace', side_effect=record_replace), patch.object(os, 'fsync', side_effect=fail_receipt_sync):
            with self.assertRaises(lifecycle.JournalError):
                f.adapter.submit(f.operation, deadline=10)
        self.assertTrue(replaces)
        self.assertEqual(f.transport.count('turn/start'), 0)

    def test_FR_CXTASK_LIFE_05_omitted_history_mode_is_pinned_legacy(self):
        f = self.fixture
        del f.transport.thread['historyMode']
        self.assertEqual(self.attempt().phase, 'running')
        self.assertEqual(f.transport.count('turn/start'), 1)

    def test_FR_CXTASK_LIFE_05_relative_native_path_blocks_submission(self):
        f = self.fixture
        f.transport.thread['path'] = 'relative/rollout.jsonl'
        try:
            result = self.attempt()
            self.assertNotEqual(result.phase, 'running')
            self.assertFalse(result.terminal_proven)
        except lifecycle.LifecycleError:
            pass
        self.assertEqual(f.transport.count('turn/start'), 0)

    def test_FR_CXTASK_LIFE_05_no_terminal_materializing_turn_blocks_submission(self):
        f = self.fixture
        # No active turn: isolate the materialization condition, rather than
        # merely exercise the already covered active-turn exclusion.
        f.transport.thread['turns'] = [contract.turn(status='unrecognized')]
        try:
            result = self.attempt()
            self.assertNotEqual(result.phase, 'running')
            self.assertFalse(result.terminal_proven)
        except lifecycle.LifecycleError:
            pass
        self.assertEqual(f.transport.count('turn/start'), 0)


if __name__ == '__main__':
    unittest.main()
