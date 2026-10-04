"""Execute the published operator PYPLAN against synthetic private Git fixtures."""
import collections
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def evidence(root):
    return {str(p.relative_to(root)): (p.lstat().st_mode,
            os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
            for p in [root, *sorted(root.rglob('*'))]}


class HistoricalPlanContract(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.temp = tempfile.TemporaryDirectory(prefix='historical-plan-', dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name)
        self.home = self.private / 'home'
        self.home.mkdir(mode=0o700)
        self.old = self.home / '.claude-control'
        self.old.mkdir(mode=0o700)
        self.new = self.home / '.ai-control'
        self.tools = self.private / 'tools'
        self.tools.mkdir(mode=0o700)
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.tools) + ':' + os.environ['PATH'],
                        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
        yq = self.tools / 'yq'
        yq.write_text('''#!/usr/bin/env python3
import json,sys
args=sys.argv[1:]
value=json.load(open(args[-1]))
queries=[a for a in args[:-1] if a.startswith('.')]
if queries:
    for key in queries[-1].lstrip('.').split('.'):
        value=value.get(key) if isinstance(value,dict) else None
print(json.dumps(value) if isinstance(value,(dict,list)) else str(value).lower() if value is None or isinstance(value,bool) else value)
''')
        yq.chmod(0o700)
        manager = self.tools / 'systemctl'
        manager.write_text('#!/bin/sh\nexit 0\n')
        manager.chmod(0o700)
        self.orphans = []
        external = self.private / 'external-valid'
        self.repository(external)
        self.worktree(external, self.old / 'agents/current/work', 'current')
        self.save(self.old / 'agents/current/spec.yaml', {'project': str(external)})
        for number in (1, 2):
            repo = self.old / ('canon/repos/cache' + str(number))
            self.repository(repo)
            self.worktree(repo, self.old / ('canon/worktrees/cache' + str(number) + '/dirty'), 'cache' + str(number))
        for number in (1, 2):
            agent = self.old / ('agents/history' + str(number))
            work = agent / 'work'
            work.mkdir(parents=True, mode=0o700)
            missing = self.private / ('deleted-repository-' + str(number))
            (work / '.git').write_bytes(('gitdir: ' + str(missing / ('.git/worktrees/history' + str(number))) + '\n').encode())
            (work / '.git').chmod(0o640)
            (work / 'opaque.bin').write_bytes(b'user bytes\x00\xff claude-control\n')
            (work / 'opaque.bin').chmod(0o600)
            (work / 'literal-link').symlink_to('opaque.bin')
            self.save(agent / 'spec.yaml', {'project': str(missing), 'type': 'task', 'engine': 'claude'})
            self.save(agent / 'control.json', {'schema': 1, 'acceptance': {'status': 'accepted'},
                                               'desired': 'stopped', 'lease': {'state': 'stale'}})
            self.orphans.append(agent)

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def git(self, repo, *args):
        return subprocess.run(['git', '-C', str(repo), *args], env=self.env,
                              check=True, capture_output=True, text=True).stdout

    def repository(self, path):
        path.mkdir(parents=True, mode=0o700)
        self.git(path, 'init')
        self.git(path, 'config', 'user.name', 'Fixture')
        self.git(path, 'config', 'user.email', 'fixture@example.invalid')
        (path / 'tracked').write_text('baseline\n')
        self.git(path, 'add', 'tracked')
        self.git(path, 'commit', '-m', 'synthetic')

    def worktree(self, repo, path, branch):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.git(repo, 'worktree', 'add', '-b', branch, str(path))
        (path / 'tracked').write_text('dirty tracked bytes\n')
        (path / 'untracked').write_bytes(b'dirty untracked\x00\xff')

    def generate(self):
        runbook = Path(os.environ.get('AI_NAMING_RUNBOOK', str(ROOT / 'docs/runbook-ai-control-names.md'))).read_text()
        code = runbook.split("python3 - <<'PYPLAN'\n", 1)[1].split('\nPYPLAN', 1)[0]
        code, replaced = re.subn(r"(?m)^home = Path\('/home/dwl'\)$", 'home = Path(' + repr(str(self.home)) + ')', code)
        self.assertEqual(replaced, 1, 'only documented operator home is substituted; plan logic runs unchanged')
        return subprocess.run(['python3', '-c', code], env=self.env, capture_output=True, timeout=30)

    def test_classifies_five_and_opaque_orphans_survive_forward_and_rollback(self):
        original = {agent.name: evidence(agent) for agent in self.orphans}
        identities = {agent.name: (agent.joinpath('work').stat().st_dev, agent.joinpath('work').stat().st_ino)
                      for agent in self.orphans}
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        plan = self.home / '.ai-control-naming-operator-plan/worktrees.json'
        self.assertEqual(stat.S_IMODE(plan.stat().st_mode), 0o600)
        entries = json.loads(plan.read_text())['worktrees']
        self.assertEqual(collections.Counter(e['role'] for e in entries), {'agent': 1, 'cache': 2, 'historical_orphan': 2})
        staging = self.home / '.ai-control-worktree-staging'
        staging.mkdir(mode=0o700)
        for entry in entries:
            if entry['role'] == 'historical_orphan':
                Path(entry['old']).rename(entry['staged'])
            else:
                self.git(entry['old_repository'], 'worktree', 'move', entry['old'], entry['staged'])
        self.old.rename(self.new)
        for entry in entries:
            canonical = Path(entry['canonical'])
            canonical.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if entry['role'] == 'historical_orphan':
                Path(entry['staged']).rename(canonical)
            else:
                repo = entry['canonical_repository']
                if entry['role'] == 'cache':
                    self.git(repo, 'worktree', 'repair', entry['staged'])
                self.git(repo, 'worktree', 'move', entry['staged'], entry['canonical'])
        for agent in self.orphans:
            canonical = self.new / agent.relative_to(self.old)
            self.assertEqual(evidence(canonical), original[agent.name])
            self.assertEqual((canonical.joinpath('work').stat().st_dev, canonical.joinpath('work').stat().st_ino), identities[agent.name])
            failed = subprocess.run(['git', '-C', str(canonical / 'work'), 'rev-parse', '--git-common-dir'], capture_output=True)
            self.assertNotEqual(failed.returncode, 0, 'historical orphan must remain invalid Git registration')
        for entry in entries:
            if entry['role'] == 'historical_orphan':
                Path(entry['canonical']).rename(entry['staged'])
            else:
                self.git(entry['canonical_repository'], 'worktree', 'move', entry['canonical'], entry['staged'])
        self.new.rename(self.old)
        for entry in entries:
            if entry['role'] == 'historical_orphan':
                Path(entry['staged']).rename(entry['old'])
            else:
                if entry['role'] == 'cache':
                    self.git(entry['old_repository'], 'worktree', 'repair', entry['staged'])
                self.git(entry['old_repository'], 'worktree', 'move', entry['staged'], entry['old'])
        for agent in self.orphans:
            self.assertEqual(evidence(agent), original[agent.name])
            self.assertEqual((agent.joinpath('work').stat().st_dev, agent.joinpath('work').stat().st_ino), identities[agent.name])

    def test_ineligible_history_refuses_before_plan_or_staging_mutation(self):
        agent = self.orphans[-1]
        control = json.loads((agent / 'control.json').read_text())
        control['desired'] = 'running'
        self.save(agent / 'control.json', control)
        before = evidence(self.home)
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(evidence(self.home), before)

    def test_nonaccepted_history_refuses_before_mutation(self):
        agent = self.orphans[-1]
        control = json.loads((agent / 'control.json').read_text())
        control['acceptance']['status'] = 'pending'
        self.save(agent / 'control.json', control)
        before = evidence(self.home)
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(evidence(self.home), before)

    def test_existing_candidate_repository_refuses_before_mutation(self):
        missing = Path(json.loads((self.orphans[-1] / 'spec.yaml').read_text())['project'])
        missing.mkdir(mode=0o700)
        before = evidence(self.home)
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(evidence(self.home), before)

    def test_missing_evidence_refuses_before_mutation(self):
        (self.orphans[-1] / 'control.json').unlink()
        before = evidence(self.home)
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(evidence(self.home), before)


    def test_ambiguous_marker_refuses_before_mutation(self):
        (self.orphans[-1] / 'work/.git').write_text('gitdir: ../ambiguous\n')
        before = evidence(self.home)
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(evidence(self.home), before)

    def test_symlink_marker_never_establishes_historical_eligibility(self):
        marker = self.orphans[-1] / 'work/.git'
        retained = self.private / 'retained-marker'
        marker.rename(retained)
        marker.symlink_to(retained)
        before = evidence(self.home)
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(evidence(self.home), before)


if __name__ == '__main__':
    unittest.main()
