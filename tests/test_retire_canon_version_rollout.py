#!/usr/bin/env python3
"""Blind public-contract regressions; no implementation imports or live services."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OLD = 'claude-agent-canon-maintainer'

class Retirement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='canon-retire-', dir=os.environ.get('TMPDIR'))
        self.p = Path(self.tmp.name)
        self.home = self.p / 'home'
        self.prefix = self.p / 'local'
        self.units = self.home / '.config/systemd/user'
        self.units.mkdir(parents=True)
        stub = self.p / 'stub'
        stub.mkdir()
        self.calls = self.p / 'systemctl.jsonl'
        ctl = stub / 'systemctl'
        ctl.write_text("""#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['RETIRE_CALLS'],'a') as f:
    f.write(json.dumps(args)+'\\n')
old='claude-agent-canon-maintainer'
is_old=any(old in a for a in args)
if 'stop' in args and is_old and os.environ.get('RETIRE_FAIL_STOP'):
    sys.exit(1)
if 'daemon-reload' in args and os.environ.get('RETIRE_FAIL_RELOAD'):
    sys.exit(1)
state=Path(os.environ['RETIRE_CALLS']+'.state')
loaded=is_old and (bool(os.environ.get('RETIRE_MANAGER_LOADED')) or any(os.path.lexists(Path(os.environ['HOME'])/'.config/systemd/user'/f'{old}.{suffix}') for suffix in ('service','timer')))
active=is_old and (bool(os.environ.get('RETIRE_FAIL_STOP')) or bool(os.environ.get('RETIRE_STICKY_ACTIVE')) or (bool(os.environ.get('RETIRE_MANAGER_ACTIVE')) and not state.exists()))
if 'stop' in args and is_old:
    state.write_text('stopped')
    active=bool(os.environ.get('RETIRE_FAIL_STOP')) or bool(os.environ.get('RETIRE_STICKY_ACTIVE'))
if 'is-active' in args:
    print('active' if active else 'inactive')
    sys.exit(0 if active else 3)
if 'show' in args:
    if os.environ.get('RETIRE_SHOW_FAILURE'):
        sys.exit(1)
    fields={'ActiveState':'active' if active else 'inactive', 'SubState':'running' if active else 'dead', 'LoadState':'loaded' if loaded else 'not-found'}
    requested=[]
    for i,arg in enumerate(args):
        if arg in ('-p','--property') and i+1<len(args):
            requested.extend(args[i+1].split(','))
        elif arg.startswith('--property=') or arg.startswith('-p='):
            requested.extend(arg.split('=',1)[1].split(','))
    for key in requested or fields:
        if key in fields:
            print(fields[key] if '--value' in args else key+'='+fields[key])
    sys.exit(0)
if 'is-enabled' in args:
    enabled=is_old and (Path(os.environ['HOME'])/'.config/systemd/user/timers.target.wants'/f'{old}.timer').exists()
    print('enabled' if enabled else 'disabled')
    sys.exit(0 if enabled else 1)
if 'disable' in args and is_old:
    (Path(os.environ['HOME'])/'.config/systemd/user/timers.target.wants'/f'{old}.timer').unlink(missing_ok=True)
""")
        ctl.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(stub)+':'+os.environ['PATH'], CLAUDE_CONTROL_OS='Linux', RETIRE_CALLS=str(self.calls), TMPDIR=str(self.p))
        self.canaries = {}
        for rel in ['.config/systemd/user/sibling.service', '.config/other/env', '.claude-control/projects.yaml', 'clients/repo/.git/HEAD', 'clients/worktree/keep', 'clients/archive/keep']:
            f = self.home / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(('canary '+rel+'\n').encode())
            self.canaries[f] = f.read_bytes()
    def tearDown(self):
        self.tmp.cleanup()
    def runcli(self, script, *args, env=None):
        result = subprocess.run([str(ROOT/script), *args], env=env or self.env, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, f'{script}: exit {result.returncode}\n{result.stderr[-1200:]}')
        return result.stdout
    def install(self):
        self.runcli('install.sh', '--prefix', str(self.prefix))
    def uninstall(self):
        self.runcli('uninstall.sh', '--prefix', str(self.prefix))
    def legacy(self):
        binary = self.prefix/'bin'/OLD
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text('#!/bin/sh\nexit 99\n')
        binary.chmod(0o755)
        for suffix in ['service','timer']:
            (self.units/f'{OLD}.{suffix}').write_text('[Unit]\nDescription=retired fixture\n')
        wants = self.units/'timers.target.wants'
        wants.mkdir()
        (wants/f'{OLD}.timer').symlink_to(self.units/f'{OLD}.timer')
    def absent(self):
        for f in [self.prefix/'bin'/OLD, self.units/f'{OLD}.service', self.units/f'{OLD}.timer', self.units/'timers.target.wants'/f'{OLD}.timer']:
            self.assertFalse(os.path.lexists(f), f'retired artifact remains: {f.name}')
    def preserved(self):
        for f,b in self.canaries.items():
            self.assertEqual(f.read_bytes(), b, f'changed unrelated canary: {f.name}')
        calls = [json.loads(l) for l in self.calls.read_text().splitlines()] if self.calls.exists() else []
        self.assertFalse(any(any('sibling' in a for a in c) for c in calls), 'unrelated unit touched')
        self.assertFalse(any('start' in c and any(OLD in a for a in c) for c in calls), 'retired operator started')
        return calls
    def test_INV_CANONRET_01_clean_inventory(self):
        self.install()
        self.absent()
        for name in (ROOT/'scripts.manifest').read_text().splitlines():
            name = name.split('#')[0].strip()
            if name:
                self.assertTrue((self.prefix/'bin'/name).exists(), f'missing supported CLI: {name}')
    def test_INV_CANONRET_02_legacy_install_repeat(self):
        self.legacy()
        self.install()
        self.absent()
        calls = self.preserved()
        self.assertTrue(any('disable' in c and any(OLD in a for a in c) for c in calls), 'legacy timer never disabled')
        self.assertTrue(any('daemon-reload' in c for c in calls), 'units not reloaded')
        self.install()
        self.absent()
        self.preserved()
    def test_INV_CANONRET_02_stop_failure_keeps_active_operator(self):
        self.legacy()
        result = subprocess.run([str(ROOT/'install.sh'), '--prefix', str(self.prefix)], env=dict(self.env, RETIRE_FAIL_STOP='1'), capture_output=True, text=True, timeout=180)
        self.assertNotEqual(result.returncode, 0, 'failed legacy stop reported success')
        self.assertTrue((self.prefix/'bin'/OLD).exists(), 'active operator binary deleted after failed stop')
        self.assertTrue((self.units/f'{OLD}.service').exists(), 'active service deleted after failed stop')
        self.preserved()
    def test_INV_CANONRET_02_reload_failure_is_visible(self):
        self.legacy()
        result = subprocess.run([str(ROOT/'install.sh'), '--prefix', str(self.prefix)], env=dict(self.env, RETIRE_FAIL_RELOAD='1'), capture_output=True, text=True, timeout=180)
        self.assertNotEqual(result.returncode, 0, 'failed daemon-reload reported success')
        self.preserved()
    def test_INV_CANONRET_03_uninstall_repeat(self):
        self.legacy()
        self.uninstall()
        self.absent()
        self.preserved()
        self.uninstall()
        self.absent()
        self.preserved()
    def test_INV_CANONRET_04_harvest_delivery_pending_without_wake(self):
        project = self.p/'project'
        (project/'.claude').mkdir(parents=True)
        (project/'.claude/canon.yaml').write_text('project_type: [coding]\nupstream_pending: []\n')
        agents = self.p/'agents'
        harvest = self.p/'harvest'
        for i in range(2):
            d = agents/f'coder-{i}'
            d.mkdir(parents=True)
            (d/'spec.yaml').write_text(f'schema: 1\nname: coder-{i}\ntype: mission\nrole: coder\nproject: {project}\ngoal: g\nautonomy: act\n')
            (d/'control.json').write_text(json.dumps({'schema':1,'incarnation':f'{i+1:032x}'}))
            (d/'events.jsonl').write_text(json.dumps({'event':'agent_created','at':'2026-07-13T00:00:00Z','actor':'operator'})+'\n'+json.dumps({'event':'acceptance_revise','at':'2026-07-13T00:00:05Z','seq':5,'actor':'operator','detail':{'note':'write regression tests'}})+'\n')
        wake = self.p/'wake'
        canon = self.p/'canon'
        env = dict(self.env, CLAUDE_AGENTS_DIR=str(agents), CLAUDE_HARVEST_DIR=str(harvest), CLAUDE_BIN=str(ROOT/'tests/mock-harvest-claude'), MOCK_MODE='one', CLAUDE_CANON_DIR=str(canon), CLAUDE_CANON_KICK_CMD=f'touch {wake}')
        key = hashlib.sha256(str(project.resolve()).encode()).hexdigest()[:16]
        def h(*args): return self.runcli('bin/claude-agent-harvest', *args, env=env)
        h('collect'); h('propose', key, 'coder')
        emitted = harvest/key/'coder/emitted.jsonl'
        cid = next(json.loads(l)['candidate_id'] for l in emitted.read_text().splitlines() if json.loads(l).get('kind')=='candidate')
        h('approve', key, 'coder', cid)
        brief = project/f'toolkit-log/upstream-pending/harvest-coder-{cid}.md'
        self.assertTrue(brief.exists(), 'delivery lost')
        original = brief.read_bytes()
        rows = [json.loads(l) for l in h('pending').splitlines() if l.strip()]
        self.assertTrue(any(r.get('cid')==cid for r in rows), 'manual pending feed lost')
        h('approve',key,'coder',cid)
        self.assertEqual(brief.read_bytes(), original, 'repeat approval changed delivered brief')
        self.assertFalse(wake.exists(), 'harvest invoked retired wake command')
        self.assertFalse((canon/'harvest-trigger.json').exists(), 'harvest wrote retired trigger')
        h('mark-applied', key, 'coder', cid)
        self.assertFalse(any(json.loads(l).get('cid')==cid for l in h('pending').splitlines() if l.strip()), 'receipt did not close pending')
    def test_INV_CANONRET_05_unrelated_canaries_survive_clean_cycle(self):
        self.install(); self.preserved()
        self.uninstall(); self.preserved()
        self.uninstall(); self.preserved()
    def test_INV_CANONRET_06_no_active_operator_inventory(self):
        names = (ROOT/'scripts.manifest').read_text().splitlines()
        self.assertNotIn(OLD, names, 'retired CLI still installed')
        for rel in [f'bin/{OLD}',f'systemd/{OLD}.service',f'systemd/{OLD}.timer','tests/test-agent-canon-maintainer.sh']:
            self.assertFalse((ROOT/rel).exists(), f'live retired operator artifact: {rel}')
        self.assertNotIn('bin/'+OLD, (ROOT/'README.md').read_text(), 'README still links runnable operator')
        for rel in ['docs/runbook-canon-maintainer.md', 'docs/specs/canon.md']:
            f = ROOT/rel
            if f.exists():
                text = f.read_text()
                if OLD in text or 'canon-maintainer' in text:
                    self.assertRegex(text[:1500].lower(), r'archiv|historical|архив|историческ', f'{rel} still presents active operator instructions')
        for workflow in (ROOT/'.github/workflows').glob('*.y*ml'):
            self.assertNotIn('tests/test-agent-canon-maintainer', workflow.read_text(), 'CI still invokes removed operator test')

if __name__ == '__main__':
    unittest.main(verbosity=2)
