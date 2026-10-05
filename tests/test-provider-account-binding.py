#!/usr/bin/env python3
"""Blind INV-ACCOUNT public CLI/create/status/statewriter/admission integration."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]

class BindingCLI(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='provider-binding-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        shutil.copytree(ROOT / 'bin', self.bin)
        self.home = self.root / 'home'
        self.agents = self.root / 'agents'
        self.project = self.root / 'project'
        self.mockbin = self.root / 'mockbin'
        for directory in (self.home, self.agents, self.project, self.mockbin,
                          self.root / 'spool', self.root / 'reconciler', self.root / 'runtime'):
            directory.mkdir(mode=0o700)
        self.catalog = self.home / '.config/ai-control/provider-accounts.json'
        self.catalog.parent.mkdir(parents=True, mode=0o700)
        self.effects = self.root / 'effects.jsonl'
        self.env = {k:v for k,v in os.environ.items() if not k.startswith(('AI_', 'CLAUDE_', 'CODEX_', 'GIT_', 'XDG_'))}
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / '.config'),
            XDG_STATE_HOME=str(self.home / 'state'), XDG_RUNTIME_DIR=str(self.root / 'runtime'),
            CLAUDE_CONFIG_DIR=str(self.root / 'own-claude'), CODEX_HOME=str(self.root / 'own-codex'),
            AI_AGENTS_DIR=str(self.agents), AI_AGENT_SPOOL_BASE=str(self.root / 'spool'),
            AI_RECONCILER_DIR=str(self.root / 'reconciler'), AI_RC_PROJECTS_FILE=str(self.root / 'projects.yaml'),
            AI_RC_TASK_TEMPLATE=str(self.root / 'task-template.yaml'),
            AI_AGENT_PROBE_CMD='/usr/bin/true', AI_AGENT_GENERATION='1', AI_AGENT_ATTEMPT='fixture-attempt',
            PATH=str(self.mockbin) + ':' + str(self.bin) + ':' + os.environ['PATH'],
            GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
        for name in ('claude', 'codex', 'systemctl', 'systemd-run', 'gh'):
            path = self.mockbin / name
            path.write_text('#!/usr/bin/env python3\nimport json,sys\n'
                f'with open({str(self.effects)!r},"a") as f: f.write(json.dumps(sys.argv)+"\\n")\n'
                'if "is-active" in sys.argv: sys.exit(3)\n'
                'if "show" in sys.argv: print("LoadState=not-found\\nActiveState=inactive\\nMainPID=0\\nControlGroup="); sys.exit(0)\n'
                'sys.exit(2)\n')
            path.chmod(0o700)
        self.env['CLAUDE_BIN'] = str(self.mockbin / 'claude')
        self.git('init', '-q', '--initial-branch=main', str(self.project))
        (self.project / 'base.txt').write_text('fixture\n')
        self.git('-C', str(self.project), 'add', 'base.txt')
        self.git('-C', str(self.project), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'base')
        (self.root / 'projects.yaml').write_text(json.dumps({'fixture': {'path': str(self.project), 'integrate': 'none'}}))
        self.rows = [dict(provider_id='claude', account_id=account, label='Safe '+account,
                         enabled=True, projects=['fixture']) for account in ('alpha','beta')]
        self.catalog_write()
        (self.root / 'task-template.yaml').write_text('schema: 1\nname: {{name}}\ntype: event\nrole: none\nproject: {{project}}\ngoal: {{goal}}\nautonomy: suggest\nworkspace: worktree\nruntime: drain\nsource: {kind: spool}\n')

    def run_cmd(self, command, *args, timeout=15):
        try:
            return subprocess.run([str(self.bin / command), *map(str,args)], env=self.env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            self.fail('Bounded public command failed to terminate: '+command)

    def git(self, *args):
        return subprocess.run(['git', *args], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True, timeout=10).stdout.strip()

    def catalog_write(self):
        self.catalog.write_text(json.dumps({'schema':1,'accounts':self.rows}))
        self.catalog.chmod(0o600)

    def spec(self, name, **changes):
        value = dict(schema=1, name=name, type='event', role='none', project=str(self.project),
            engine='claude', runtime='drain', workspace='worktree', goal='Inspect own fixture', autonomy='suggest',
            memory_max_mb=100, limits={'runs_per_day':10,'run_timeout_s':20}, source={'kind':'spool'})
        value.update(changes)
        path = self.root / (name+'-spec.yaml')
        path.write_text(json.dumps(value))
        return path

    def create(self, name='bound-alpha', account='alpha', provider='claude', **changes):
        return self.run_cmd('ai-rc','agent','create',name,'--spec',self.spec(name,**changes),
                            '--provider',provider,'--account',account)

    def require_created(self, name='bound-alpha', account='alpha'):
        result = self.create(name,account)
        self.assertEqual(result.returncode,0,'Accepted paused bound create absent: '+result.stderr)
        path=self.agents/name
        control=json.loads((path/'control.json').read_text())
        self.assertEqual(control['provider_binding'],dict(schema=1,provider_id='claude',account_id=account))
        self.assertEqual(control['desired'],'paused')
        self.assertEqual((path/'control.json').stat().st_mode & 0o777,0o600)
        return path,control

    def snapshot(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for base in (self.agents,self.root/'spool')
                for p in base.rglob('*') if p.is_file() and not p.is_symlink()}

    def no_launch(self):
        calls=[json.loads(s) for s in self.effects.read_text().splitlines()] if self.effects.exists() else []
        self.assertFalse(any(Path(call[0]).name in ('claude','codex','systemd-run') for call in calls),calls)
        self.assertFalse((self.root/'own-claude').exists(),'Bound path touched provider config')
        self.assertFalse((self.root/'own-codex').exists(),'Bound path touched native home')

    def test_installed_default_catalog_cli_scoped_safe_json(self):
        self.rows.append(dict(provider_id='codex',account_id='hidden',label='FORBIDDEN_LABEL',enabled=True,projects=['other']))
        registry=json.loads((self.root/'projects.yaml').read_text()); registry['other']=str(self.project)
        (self.root/'projects.yaml').write_text(json.dumps(registry)); self.catalog_write()
        result=self.run_cmd('ai-rc','accounts','list','--project','fixture','--json')
        self.assertEqual(result.returncode,0,'Safe account listing is not integrated: '+result.stderr)
        value=json.loads(result.stdout)
        self.assertEqual(value['schema'],1)
        self.assertEqual([v['account_id'] for v in value['accounts']],['alpha','beta'])
        self.assertNotIn('FORBIDDEN_LABEL',result.stdout)
        self.assertNotIn(str(self.home),result.stdout)
        self.assertFalse(self.effects.exists())

    def test_two_paused_accounts_and_mutable_label_leave_identity_unchanged(self):
        first,a=self.require_created(); second,b=self.require_created('bound-beta','beta')
        self.assertNotEqual(a['incarnation'],b['incarnation'])
        before=(first/'control.json').read_bytes()
        self.rows[0]['label']='Renamed safe label'; self.catalog_write()
        status=self.run_cmd('ai-rc','agent','status','bound-alpha')
        self.assertEqual(status.returncode,0,status.stderr)
        self.assertIn('Renamed safe label',status.stdout)
        self.assertIn('runtime_unverified',status.stdout)
        self.assertNotIn('Safe beta',status.stdout)
        self.assertEqual((first/'control.json').read_bytes(),before)
        self.assertEqual(json.loads((second/'control.json').read_text())['provider_binding'],b['provider_binding'])
        self.no_launch()

    def test_invalid_selectors_and_reserved_spec_have_zero_publication(self):
        for selectors in (['--provider','claude'],['--account','alpha'],
                          ['--provider','claude','--provider','claude','--account','alpha'],
                          ['--provider','claude','--account','alpha','--account','beta']):
            with self.subTest(selectors=selectors):
                before=self.snapshot()
                result=self.run_cmd('ai-rc','agent','create','bad','--spec',self.spec('bad'),*selectors)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(self.snapshot(),before)
        result=self.create('reserved',provider_binding=dict(schema=1,provider_id='claude',account_id='beta'))
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.agents/'reserved').exists()); self.no_launch()

    def test_engine_type_runtime_workspace_mismatch_refuse_without_worktree(self):
        for change in ({'engine':'codex'},{'type':'mission'},{'runtime':'handoff'},{'workspace':'direct'}):
            with self.subTest(change=change):
                result=self.create('invalid',**change)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse((self.agents/'invalid').exists())
        self.no_launch()

    def test_disabled_forbidden_and_removed_account_create_errors_are_explicit(self):
        for rows,account,code in ([dict(self.rows[0],enabled=False)],'alpha','account_disabled'),([dict(self.rows[0],projects=['other'])],'alpha','account_forbidden'),([], 'alpha','account_unknown'):
            with self.subTest(code=code):
                registry=json.loads((self.root/'projects.yaml').read_text()); registry['other']=str(self.project)
                (self.root/'projects.yaml').write_text(json.dumps(registry))
                self.rows=rows; self.catalog_write()
                result=self.create(account=account)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(code,result.stdout+result.stderr)
                self.assertFalse((self.agents/'bound-alpha').exists())
        self.no_launch()

    def test_missing_unsafe_and_malformed_catalog_is_not_empty_success(self):
        for variant,code in (('missing','catalog_unconfigured'),('mode','catalog_unsafe'),('malformed','catalog_invalid')):
            with self.subTest(variant=variant):
                self.catalog_write()
                if variant=='missing': self.catalog.unlink()
                elif variant=='mode': self.catalog.chmod(0o644)
                else: self.catalog.write_text('{malformed')
                result=self.run_cmd('ai-rc','accounts','list','--project','fixture','--json')
                self.assertNotEqual(result.returncode,0)
                self.assertIn(code,result.stdout+result.stderr)
                self.assertFalse(self.effects.exists())

    def test_unknown_project_and_registry_read_failure_are_explicit_before_create(self):
        unknown=self.run_cmd('ai-rc','accounts','list','--project','missing','--json')
        self.assertNotEqual(unknown.returncode,0)
        self.assertIn('project_unknown',unknown.stdout+unknown.stderr)
        (self.root/'projects.yaml').write_text('{malformed')
        before=self.snapshot()
        result=self.create('registry-failure')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.snapshot(),before)
        self.assertFalse((self.agents/'registry-failure').exists()); self.no_launch()

    def test_catalog_identity_drift_during_trusted_worktree_creation_prevents_publication(self):
        genuine_git=shutil.which('git')
        self.assertIsNotNone(genuine_git)
        marker=self.root/'catalog-drift-observed'
        replacement=self.root/'replacement-catalog.json'
        replacement.write_text(json.dumps({'schema':1,'accounts':[dict(self.rows[0],enabled=False),self.rows[1]]}))
        replacement.chmod(0o600)
        wrapper=self.mockbin/'git'
        wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\n'
            f'if "worktree" in sys.argv and "add" in sys.argv and not os.path.exists({str(marker)!r}):\n'
            f' os.replace({str(replacement)!r},{str(self.catalog)!r}); open({str(marker)!r},"w").write("owned drift")\n'
            f'os.execv({genuine_git!r},[{genuine_git!r},*sys.argv[1:]])\n')
        wrapper.chmod(0o700)
        result=self.create('drifted')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.agents/'drifted').exists(),'Catalog drift published immutable binding')
        self.assertFalse((self.root/'spool/drifted').exists())
        # Reaching this public boundary ensures refusal tested a real snapshot race.
        self.assertTrue(marker.exists(),'Bound create never reached validated private worktree preparation')
        self.no_launch()

    def test_same_create_replay_preserves_control_and_different_account_refuses(self):
        path,control=self.require_created()
        before=(path/'control.json').read_bytes(); effects=self.snapshot()
        replay=self.create()
        self.assertIn(replay.returncode,(0,4))
        self.assertEqual((path/'control.json').read_bytes(),before)
        changed=self.create(account='beta')
        self.assertNotEqual(changed.returncode,0)
        self.assertEqual(self.snapshot(),effects)
        self.assertEqual((path/'control.json').read_bytes(),before); self.no_launch()

    def test_bound_new_task_refuses_before_template_create_spool_start(self):
        before=self.snapshot()
        result=self.run_cmd('ai-rc','agent','new-task','--name','autostart','--project','fixture','--text','own event',
                            '--provider','claude','--account','alpha')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('runtime_unverified',result.stdout+result.stderr)
        self.assertEqual(self.snapshot(),before)
        self.assertFalse((self.agents/'autostart').exists()); self.no_launch()

    def test_binding_control_cas_cannot_change_remove_or_add_identity(self):
        path,control=self.require_created(); before=(path/'control.json').read_bytes()
        for value in (json.dumps(dict(schema=1,provider_id='claude',account_id='beta')),'null'):
            result=self.run_cmd('ai-agent-io','control-cas',path,'--set','provider_binding='+value)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((path/'control.json').read_bytes(),before)
        legacy=self.run_cmd('ai-rc','agent','create','legacy','--spec',self.spec('legacy'))
        self.assertEqual(legacy.returncode,0,legacy.stderr)
        old=self.agents/'legacy'; oldbytes=(old/'control.json').read_bytes()
        result=self.run_cmd('ai-agent-io','control-cas',old,'--set','provider_binding='+json.dumps(control['provider_binding']))
        self.assertNotEqual(result.returncode,0); self.assertEqual((old/'control.json').read_bytes(),oldbytes)

    def test_same_binding_control_cas_cannot_change_project_or_incarnation(self):
        changes=(('project_name',json.dumps('other-fixture')),
                 ('incarnation',json.dumps('99999999-9999-4999-8999-999999999999')))
        for field,value in changes:
            with self.subTest(field=field):
                path,control=self.require_created('cas-'+field.replace('_','-'))
                control_bytes=(path/'control.json').read_bytes()
                same_binding=json.dumps(control['provider_binding'])
                warm=self.run_cmd('ai-agent-io','control-cas',path,'--set',
                                  'provider_binding='+json.dumps(dict(schema=1,provider_id='claude',account_id='beta')))
                self.assertNotEqual(warm.returncode,0)
                self.assertEqual((path/'control.json').read_bytes(),control_bytes)
                before=self.snapshot()
                result=self.run_cmd('ai-agent-io','control-cas',path,'--set','provider_binding='+same_binding,
                                    '--set',field+'='+value)
                self.assertNotEqual(result.returncode,0,'Same-binding CAS changed authoritative '+field)
                self.assertEqual(self.snapshot(),before,'Denied same-binding CAS had filesystem side effects')
        self.no_launch()

    def test_start_denied_before_desired_change_and_catalog_drift_leaves_other_account(self):
        path,a=self.require_created(); other,b=self.require_created('bound-beta','beta')
        before=(path/'control.json').read_bytes(); other_before=(other/'control.json').read_bytes()
        for rows,code in (self.rows,'runtime_unverified'),([self.rows[1]],'account_unknown'):
            self.rows=rows; self.catalog_write()
            result=self.run_cmd('ai-rc','agent','start','bound-alpha')
            self.assertNotEqual(result.returncode,0)
            self.assertIn(code,result.stdout+result.stderr)
            self.assertEqual((path/'control.json').read_bytes(),before)
            self.assertEqual((other/'control.json').read_bytes(),other_before)
        self.no_launch()

    def test_legacy_status_explicitly_unbound_without_catalog_default(self):
        result=self.run_cmd('ai-rc','agent','create','legacy','--spec',self.spec('legacy'))
        self.assertEqual(result.returncode,0,result.stderr)
        path=self.agents/'legacy'; before=(path/'control.json').read_bytes()
        self.catalog.write_text('{malformed')
        status=self.run_cmd('ai-rc','agent','status','legacy')
        self.assertEqual(status.returncode,0,status.stderr)
        self.assertIn('legacy-unbound',status.stdout)
        self.assertEqual((path/'control.json').read_bytes(),before)
        self.assertNotIn('provider_binding',json.loads(before)); self.no_launch()

    def pending(self, path):
        directory=path/'inbox/pending'; directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        event=directory/'owned-event.json'
        event.write_text(json.dumps(dict(schema=1,key='owned-event',source_ns='fixture',native_id='1',
            received_at='2026-10-05T00:00:00Z',payload={'text':'own synthetic pending'},
            meta=dict(attempts=0,recoveries=0,quarantined=False,next_attempt_at=None,history=[]))))
        event.chmod(0o600)
        return event

    def test_direct_runner_bound_gate_precedes_inbox_initialization(self):
        path,control=self.require_created()
        # A trusted fixture activates the existing valid control, never account spec/env routing.
        control['desired']='running'; control['generation']=1
        control['lease'].update(state='active',start_attempt_id='fixture-attempt')
        (path/'control.json').write_text(json.dumps(control))
        event=self.pending(path); before=self.snapshot()
        result=self.run_cmd('ai-agent-run','step',path)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('runtime_unverified',result.stdout+result.stderr)
        self.assertEqual(self.snapshot(),before); self.no_launch()

    def test_reconciler_bound_gate_precedes_acquisition_or_process_launch(self):
        path,control=self.require_created()
        control['desired']='running'; (path/'control.json').write_text(json.dumps(control))
        event=self.pending(path); before_event=event.read_bytes()
        before=json.loads((path/'control.json').read_text())
        result=self.run_cmd('ai-agent-reconciler','--once')
        after=json.loads((path/'control.json').read_text())
        for field in ('desired','incarnation','provider_binding','generation','lease'):
            self.assertEqual(after[field],before[field],field)
        self.assertTrue(event.is_file()); self.assertEqual(event.read_bytes(),before_event)
        self.assertFalse((path/'inbox/inflight/owned-event.json').exists())
        self.no_launch()

if __name__=='__main__': unittest.main()
