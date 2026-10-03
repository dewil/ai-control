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
from unittest import mock
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
        home = self.root / 'home'
        home.mkdir(mode=0o700)
        isolation = mock.patch.dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'))
        isolation.start()
        self.addCleanup(isolation.stop)
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
        with self.assertRaises(worktree.GitGuardError):
            self.guarded('add', '--', 'tracked.txt')
        self.assertEqual(target.read_bytes(), original)
        self.index.unlink()
        os.link(target, self.index)
        with self.assertRaises(worktree.GitGuardError):
            self.guarded('add', '--', 'tracked.txt')
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)

    def test_worktree_index_path_and_unsafe_parent_are_not_private_index(self):
        candidate = self.cwd / 'model-selected.index'
        shutil.copyfile(self.index, candidate)
        candidate.chmod(0o600)
        before = candidate.read_bytes()
        with self.assertRaises(worktree.GitGuardError):
            self.guarded('add', '--', 'tracked.txt', index=candidate)
        self.assertEqual(candidate.read_bytes(), before)
        self.op.chmod(0o777)
        with self.assertRaises(worktree.GitGuardError):
            self.guarded('add', '--', 'tracked.txt')
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)

    def test_shared_guard_denial_prevents_private_index_mutation(self):
        unrelated = self.root / 'unrelated'
        unrelated.mkdir(mode=0o700)
        before = self.index.read_bytes()
        with self.assertRaises(worktree.GitGuardError):
            worktree.git_run(['add', '--', 'tracked.txt'], str(self.cwd), str(unrelated),
                index_file=str(self.index), deadline=time.monotonic() + 3)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)

    def test_explicit_none_is_identical_to_old_caller_index_behavior(self):
        # INV-CXRUN-07
        private_before = self.index.read_bytes()
        (self.cwd / 'tracked.txt').write_text('explicit None legacy change\n')
        worktree.git_run(['add', '--', 'tracked.txt'], str(self.cwd), str(self.project),
                         index_file=None, deadline=time.monotonic() + 3)
        self.assertEqual(self.index.read_bytes(), private_before)
        self.assertEqual(self.git('show', ':tracked.txt', cwd=self.cwd), 'explicit None legacy change\n')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.cwd).strip(), self.base)

    def test_default_caller_strips_malicious_environment_index(self):
        # INV-CXRUN-07
        redirected = self.root / 'model-environment.index'
        shutil.copyfile(self.index, redirected)
        redirected.chmod(0o600)
        sentinel_before = redirected.read_bytes()
        (self.cwd / 'tracked.txt').write_text('default trusted change\n')
        with mock.patch.dict(os.environ, GIT_INDEX_FILE=str(redirected)):
            worktree.git_run(['add', '--', 'tracked.txt'], str(self.cwd), str(self.project),
                             deadline=time.monotonic() + 3)
        self.assertEqual(redirected.read_bytes(), sentinel_before)
        self.assertEqual(self.git('show', ':tracked.txt', cwd=self.cwd), 'default trusted change\n')
        self.assertEqual(self.index.read_bytes(), self.original_main_index)

    def test_project_root_index_is_model_accessible_and_refused(self):
        # INV-CXRUN-07
        index = self.project / 'model-accessible.index'
        shutil.copyfile(self.index, index)
        index.chmod(0o600)
        before = index.read_bytes()
        with self.assertRaises(worktree.GitGuardError):
            self.guarded('add', '--', 'tracked.txt', index=index)
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)

    def test_symlinked_private_parent_and_noncanonical_path_are_refused(self):
        # INV-CXRUN-07
        alias = self.root / 'state-alias'
        alias.symlink_to(self.root / 'state', target_is_directory=True)
        unsafe = alias / self.index.relative_to(self.root / 'state')
        before = self.index.read_bytes()
        with self.assertRaises(worktree.GitGuardError):
            self.guarded('add', '--', 'tracked.txt', index=unsafe)
        noncanonical = str(self.op / '..' / self.op.name / self.index.name)
        with self.assertRaises(worktree.GitGuardError):
            self.guarded('add', '--', 'tracked.txt', index=noncanonical)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)

    def test_replaced_index_after_real_git_is_refused_before_success(self):
        # INV-CXRUN-07. Real Git does its ordinary atomic index rewrite first;
        # subprocess boundary then swaps only the own fixture index. Legitimate
        # replacement is covered by private_add success; unsafe replacement
        # must never be interpreted as a successful trusted checkpoint.
        real_git = shutil.which('git')
        self.assertIsNotNone(real_git)
        fakebin = self.root / 'test-boundary-bin'
        fakebin.mkdir(mode=0o700)
        sentinel = self.root / 'untouched-sentinel.index'
        shutil.copyfile(self.index, sentinel)
        sentinel.chmod(0o600)
        original = sentinel.read_bytes()
        replacement_marker = self.root / 'replacement-observed'
        wrapper = fakebin / 'git'
        for kind in ('symlink', 'hardlink'):
            with self.subTest(kind=kind):
                if self.index.exists() or self.index.is_symlink():
                    self.index.unlink()
                shutil.copyfile(self.main_index, self.index)
                self.index.chmod(0o600)
                replacement_marker.unlink(missing_ok=True)
                source = ('#!/usr/bin/env python3\nimport os,sys,subprocess,pathlib\n'
                    f'result=subprocess.run([{real_git!r},*sys.argv[1:]])\n'
                    'if result.returncode==0 and "add" in sys.argv[1:]:\n'
                    f' target=pathlib.Path({str(self.index)!r})\n'
                    ' target.unlink()\n'
                    + (f' target.symlink_to({str(sentinel)!r})\n' if kind == 'symlink' else
                       f' os.link({str(sentinel)!r},str(target))\n')
                    + f' pathlib.Path({str(replacement_marker)!r}).write_text("replaced")\n'
                    'sys.exit(result.returncode)\n')
                wrapper.write_text(source)
                wrapper.chmod(0o700)
                compile(source, str(wrapper), 'exec')
                (self.cwd / 'tracked.txt').write_text('real private Git change\n')
                with mock.patch.dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ['PATH']):
                    with self.assertRaises(worktree.GitGuardError):
                        self.guarded('add', '--', 'tracked.txt')
                self.assertTrue(replacement_marker.is_file(), 'real Git boundary must have completed')
                self.assertEqual(sentinel.read_bytes(), original)
                self.assertEqual(self.main_index.read_bytes(), self.original_main_index)
                self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.cwd).strip(), self.base)

    def test_private_index_does_not_bypass_actual_shared_clean_filter_guard(self):
        # INV-CXRUN-07. Existing project Git policy, genuine info attributes.
        marker = self.root / 'unsafe-filter-ran'
        filter_script = self.root / 'unsafe-clean-filter'
        filter_script.write_text('#!/bin/sh\nprintf executed > ' + str(marker) + '\ncat\n')
        filter_script.chmod(0o700)
        self.git('config', 'filter.fixture.clean', str(filter_script), cwd=self.project)
        attributes = self.project / '.git/info/attributes'
        attributes.write_text('*.txt filter=fixture\n')
        (self.cwd / 'tracked.txt').write_text('filter must never see this\n')
        before = self.index.read_bytes()
        with self.assertRaises(worktree.GitGuardError):
            self.guarded('add', '--', 'tracked.txt')
        self.assertFalse(marker.exists(), 'guard refusal must precede configured executable filter')
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(self.main_index.read_bytes(), self.original_main_index)
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.cwd).strip(), self.base)


if __name__ == '__main__':
    unittest.main()
