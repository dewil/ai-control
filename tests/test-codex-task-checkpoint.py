#!/usr/bin/env python3
"""Blind public guarded Git index contract; real disposable linked worktrees."""
import importlib
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
worktree = importlib.import_module('_agent_worktree')


class PrivateIndexContract(unittest.TestCase):
    def setUp(self):
        self.assertIn('index_file', inspect.signature(worktree.git_run).parameters,
            'INV-CXRUN-07: trusted explicit private Git index is required before TASK checkpoints')
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.cwd = self.root / 'agent/work'
        self.op = self.root / 'state' / str(uuid.uuid4()) / 'operations' / str(uuid.uuid4())
        self.project.mkdir(mode=0o700)
        self.cwd.parent.mkdir(mode=0o700)
        self.op.mkdir(parents=True, mode=0o700)
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                                GIT_TERMINAL_PROMPT='0')
        self.git('init', cwd=self.project)
        self.git('config', 'user.name', 'Fixture', cwd=self.project)
        self.git('config', 'user.email', 'fixture@example.invalid', cwd=self.project)
        (self.project / 'tracked.txt').write_text('baseline\n')
        self.git('add', 'tracked.txt', cwd=self.project)
        self.git('commit', '-m', 'baseline', cwd=self.project)
        self.git('worktree', 'add', '-b', 'task/fixture', str(self.cwd), cwd=self.project)
        self.main_index = Path(self.git('rev-parse', '--git-path', 'index', cwd=self.cwd).strip())
        if not self.main_index.is_absolute():
            self.main_index = self.cwd / self.main_index
        self.main_index = self.main_index.resolve()
        self.index = self.op / 'checkpoint.index'
        shutil.copyfile(self.main_index, self.index)
        self.index.chmod(0o600)
        self.original_main_index = self.main_index.read_bytes()
        self.base = self.git('rev-parse', 'HEAD', cwd=self.cwd).strip()

    def git(self, *args, cwd):
        return subprocess.run(['git', *args], cwd=cwd, env=self.environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True).stdout

    def guarded(self, *args, index=None):
        return worktree.git_run(list(args), str(self.cwd), str(self.project),
            index_file=str(self.index if index is None else index), deadline=time.monotonic() + 3)

    def test_private_add_changes_only_private_index_and_owned_tree(self):
        (self.cwd / 'tracked.txt').write_text('private change\n')
        self.guarded('add', '--', 'tracked.txt')
        self.assertNotEqual(self.index.read_bytes(), self.original_main_index)
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)
        environment = self.environment.copy()
        environment['GIT_INDEX_FILE'] = str(self.index)
        tree = subprocess.run(['git', 'write-tree'], cwd=self.cwd, env=environment,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
        self.assertEqual(self.git('show', tree + ':tracked.txt', cwd=self.cwd), 'private change\n')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.cwd).strip(), self.base)

    def test_caller_git_index_environment_cannot_redirect_trusted_index(self):
        outside = self.root / 'caller.index'
        shutil.copyfile(self.main_index, outside)
        outside.chmod(0o600)
        original = outside.read_bytes()
        (self.cwd / 'tracked.txt').write_text('trusted change\n')
        environment = self.environment.copy()
        environment['GIT_INDEX_FILE'] = str(outside)
        code = ('import sys,time; sys.path.insert(0,sys.argv[1]); '
                'from _agent_worktree import git_run; '
                "git_run(['add','--','tracked.txt'],sys.argv[2],sys.argv[3],"
                'index_file=sys.argv[4],deadline=time.monotonic()+3)')
        result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'bin'),
            str(self.cwd), str(self.project), str(self.index)], env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(result.returncode, 0, 'Trusted Git helper refused isolated valid fixture')
        self.assertEqual(outside.read_bytes(), original)
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)
        self.assertNotEqual(self.index.read_bytes(), original)

    def test_legacy_caller_without_index_keeps_existing_index_behavior(self):
        before = self.index.read_bytes()
        (self.cwd / 'tracked.txt').write_text('legacy change\n')
        worktree.git_run(['add', '--', 'tracked.txt'], str(self.cwd), str(self.project),
                         deadline=time.monotonic() + 3)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertNotEqual(self.main_index.read_bytes(), self.original_main_index)
        self.assertEqual(self.git('show', ':tracked.txt', cwd=self.cwd), 'legacy change\n')

    def test_symlink_and_hardlinked_private_index_cannot_mutate_target(self):
        target = self.root / 'sentinel.index'
        shutil.copyfile(self.index, target)
        target.chmod(0o600)
        original = target.read_bytes()
        self.index.unlink()
        self.index.symlink_to(target)
        with self.assertRaises(Exception):
            self.guarded('add', '--', 'tracked.txt')
        self.assertEqual(target.read_bytes(), original)
        self.index.unlink()
        os.link(target, self.index)
        with self.assertRaises(Exception):
            self.guarded('add', '--', 'tracked.txt')
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)

    def test_worktree_index_path_and_unsafe_parent_are_not_private_index(self):
        candidate = self.cwd / 'model-selected.index'
        shutil.copyfile(self.index, candidate)
        candidate.chmod(0o600)
        before = candidate.read_bytes()
        with self.assertRaises(Exception):
            self.guarded('add', '--', 'tracked.txt', index=candidate)
        self.assertEqual(candidate.read_bytes(), before)
        self.op.chmod(0o777)
        with self.assertRaises(Exception):
            self.guarded('add', '--', 'tracked.txt')
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)

    def test_shared_guard_denial_prevents_private_index_mutation(self):
        unrelated = self.root / 'unrelated'
        unrelated.mkdir(mode=0o700)
        before = self.index.read_bytes()
        with self.assertRaises(Exception):
            worktree.git_run(['add', '--', 'tracked.txt'], str(self.cwd), str(unrelated),
                index_file=str(self.index), deadline=time.monotonic() + 3)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)


if __name__ == '__main__':
    unittest.main()
