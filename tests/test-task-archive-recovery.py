#!/usr/bin/env python3
"""Blind CLI regressions: INV-TASK-44/06, accepted archive-recovery spec.

Only public CLI, persisted domain records and external systemd mocks are used.
No production functions are imported. Fixtures belong to a private /var/tmp root.
"""
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
STAMP = '2026-10-03T00:00:00Z'

class ArchiveRecovery(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        self.tmp = tempfile.TemporaryDirectory(prefix='cc-archive-tests-', dir='/var/tmp')
        self.base = Path(self.tmp.name)
        self.mock = self.base / 'mockbin'
        self.mock.mkdir()
        self.env = dict(os.environ, CLAUDE_AGENTS_DIR=str(self.base/'agents'),
                        CLAUDE_AGENT_SPOOL_BASE=str(self.base/'spool'),
                        CLAUDE_RECONCILER_DIR=str(self.base/'reconciler'),
                        CLAUDE_CONFIG_DIR=str(self.base/'config'),
                        CLAUDE_RC_PROJECTS_FILE=str(self.base/'projects.yaml'),
                        CLAUDE_AGENT_ALERT_CMD='/usr/bin/true',
                        CLAUDE_AGENT_PROBE_CMD='/usr/bin/true',
                        CLAUDE_AGENT_LESSONS_JOURNAL_DIR=str(self.base/'lessons'),
                        CLAUDE_AGENT_STOP_GRACE='0', TMPDIR=str(self.base),
                        CC_ARCHIVE_FIXTURE=str(self.base),
                        PATH=str(self.mock)+':'+str(ROOT/'bin')+':'+os.environ['PATH'])
        self.env.pop('CLAUDE_AGENTS_REQUIRE_MOUNT', None)
        (self.base/'projects.yaml').write_text('{}\n')
        self.system_state('inactive', 3)
        script = '''#!/usr/bin/env python3
import json, os, pathlib, sys, time
b=pathlib.Path(os.environ['CC_ARCHIVE_FIXTURE']); args=sys.argv[1:]
with (b/'systemctl.log').open('a') as f: f.write(json.dumps(args)+'\\n')
if 'is-active' in args:
    if (b/'block-query').exists() and not (b/'query-entered').exists():
        (b/'query-entered').touch()
        end=time.monotonic()+10
        while not (b/'query-release').exists() and time.monotonic()<end: time.sleep(.01)
    state,code=json.loads((b/'system-state').read_text())
    print(state); sys.exit(code)
if 'show' in args:
    props=[]
    for i,a in enumerate(args):
        if a in ('-p','--property') and i+1<len(args): props.extend(args[i+1].split(','))
    vals={'LoadState':'not-found','ActiveState':'inactive','ControlGroup':'','MainPID':'0','SubState':'dead'}
    override=b/'show-state'
    if override.exists():
        scenario=json.loads(override.read_text())
        if scenario.get('delay'): time.sleep(scenario['delay'])
        if scenario.get('code'): sys.exit(scenario['code'])
        vals=scenario['fields']
    if not props: props=list(vals)
    for p in props:
        if p in vals: print(vals[p] if '--value' in args else p+'='+vals[p])
sys.exit(0)
'''
        (self.mock/'systemctl').write_text(script)
        (self.mock/'systemctl').chmod(0o700)
        (self.mock/'systemd-run').write_text("""#!/usr/bin/env python3
import os,pathlib,time,json
b=pathlib.Path(os.environ['CC_ARCHIVE_FIXTURE'])
with (b/'launch.log').open('a') as f: f.write('launch\\n')
(b/'launch-entered').touch()
end=time.monotonic()+10
while (b/'block-launch').exists() and not (b/'launch-release').exists() and time.monotonic()<end: time.sleep(.01)
(b/'system-state').write_text(json.dumps(['active',0]))
""")
        (self.mock/'systemd-run').chmod(0o700)

    def tearDown(self):
        self.tmp.cleanup()

    def system_state(self, state, code):
        (self.base/'system-state').write_text(json.dumps([state, code]))

    def cli(self, binary, *args, check=False):
        p = subprocess.run([str(ROOT/'bin'/binary), *map(str,args)], env=self.env,
                           text=True, capture_output=True, timeout=15)
        if check:
            self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def fixture(self, phase='archived', desired='stopped', name='archiveone'):
        project=self.base/'project'; project.mkdir(exist_ok=True)
        spec=self.base/'fixture.yaml'
        spec.write_text(f'''schema: 1
name: {name}
type: event
role: none
project: {project}
goal: "archive recovery fixture"
autonomy: suggest
memory_max_mb: 100
limits: {{ runs_per_day: 100, run_timeout_s: 20 }}
source: {{ kind: spool, replay_window_h: 72 }}
workspace: none
''')
        self.cli('claude-rc', 'agent', 'create', name, '--spec', spec, check=True)
        agent=self.base/'agents'/name
        self.cli('claude-rc', 'agent', 'stop', name, check=True)
        control=json.loads((agent/'control.json').read_text())
        control['desired']=desired
        (agent/'control.json').write_text(json.dumps(control))
        done={'state':phase,'workspace':'none','summary':'archive recovery', 'finalized':True,
              'requested_at':STAMP,'envelope_key':'fixture-key','branch':None,'base':None,
              'commit_sha':None,'changes':None,'empty':None,'pushed_at':STAMP,
              'accepted_at':STAMP,'verdict_at':STAMP,'verdict_by':'test',
              'integrate_mode':'skipped','integrate_ref':None,'integrated_at':STAMP,
              'cleaned_at':STAMP,'archived_at':STAMP if phase=='archived' else None,
              'phase_attempts':0,'phase_error':None}
        (agent/'done.json').write_text(json.dumps(done))
        return agent

    def test_INV_TASK_44_retry_refuses_live_unknown_and_unstopped(self):
        for phase in ('cleaned','archived'):
            for state,code,desired in [('active',0,'stopped'),('activating',0,'stopped'),
                    ('deactivating',3,'stopped'),('unknown',4,'stopped'),
                    ('inactive',1,'stopped'),('inactive',0,'stopped'),
                    ('inactive',3,'running'),('inactive',3,'paused')]:
                with self.subTest(phase=phase,state=state,code=code,desired=desired):
                    name=f'a{phase}{state}{code}{desired}'
                    agent=self.fixture(phase,desired,name)
                    self.system_state(state,code)
                    self.cli('claude-agent-run','done-advance',agent)
                    self.assertTrue(agent.is_dir(), 'archive moved an unsafe agent directory')
                    if phase=='archived':
                        self.assertEqual(json.loads((agent/'done.json').read_text())['archived_at'],STAMP)

    def test_INV_TASK_44_proved_absent_unit_archives_both_phases(self):
        for phase in ('cleaned','archived'):
            with self.subTest(phase=phase):
                agent=self.fixture(phase,name='absent'+phase)
                self.system_state('inactive',4)
                self.cli('claude-agent-run','done-advance',agent,check=True)
                self.assertFalse(agent.exists(),'proved absent transient unit held archive forever')
                tomb=self.base/'tombstones'/(agent.name+'.json')
                self.assertTrue(tomb.exists(),'archive omitted tombstone')
                if phase=='archived':
                    self.assertEqual(json.loads(tomb.read_text())['archived_at'],STAMP)

    def test_INV_TASK_44_absent_unit_requires_complete_consistent_show(self):
        valid={'LoadState':'not-found','ActiveState':'inactive','MainPID':'0','ControlGroup':''}
        scenarios=[('error',{'code':1,'fields':valid}),
                   ('timeout',{'delay':6,'fields':valid})]
        for key in valid:
            scenarios.append(('missing'+key,{'fields':{k:v for k,v in valid.items() if k!=key}}))
        for key,value in [('LoadState','loaded'),('ActiveState','active'),
                          ('MainPID','17'),('ControlGroup','/user.slice/fixture')]:
            scenarios.append(('contradict'+key,{'fields':dict(valid,**{key:value})}))
        for phase in ('cleaned','archived'):
            for index,(label,scenario) in enumerate(scenarios):
                with self.subTest(phase=phase,scenario=label):
                    agent=self.fixture(phase,name='absent'+phase+str(index))
                    self.system_state('inactive',4)
                    (self.base/'show-state').write_text(json.dumps(scenario))
                    self.cli('claude-agent-run','done-advance',agent)
                    self.assertTrue(agent.is_dir(),'unproved missing unit allowed archive')
                    if phase=='archived':
                        self.assertEqual(json.loads((agent/'done.json').read_text())['archived_at'],STAMP)

    def test_INV_TASK_06_stopped_retry_keeps_stamp_destination_and_tombstone(self):
        agent=self.fixture()
        tomb=self.base/'tombstones'/'archiveone.json'; tomb.parent.mkdir(exist_ok=True)
        dest=self.base/'archive'/('archiveone-'+STAMP)
        tomb.write_text(json.dumps({'name':'archiveone','archived_at':STAMP,'archived_to':str(dest)}))
        self.cli('claude-agent-run','done-advance',agent,check=True)
        self.assertFalse(agent.exists())
        self.assertTrue(dest.is_dir())
        self.assertEqual(json.loads((dest/'done.json').read_text())['archived_at'],STAMP)
        self.assertEqual(len(list((self.base/'archive').iterdir())),1)
        self.cli('claude-agent-run','done-advance',agent)
        self.assertFalse(agent.exists(), 'late retry resurrected the old path')
        self.assertEqual(len(list((self.base/'archive').iterdir())),1)

    def wait_marker(self, path, proc):
        end=time.monotonic()+5
        while time.monotonic()<end:
            if path.exists(): return
            if proc.poll() is not None: break
            time.sleep(.01)
        self.fail('public archive did not reach the mocked liveness query')

    def launch_fixture(self):
        agent=self.fixture(desired='paused')
        done=(agent/'done.json').read_text()
        (agent/'done.json').unlink()
        self.cli('claude-rc','agent','start','archiveone',check=True)
        return agent,done

    def test_INV_TASK_44_reconciler_launch_wins_archive_waits(self):
        agent,done=self.launch_fixture()
        (self.base/'block-launch').touch()
        launch=subprocess.Popen([str(ROOT/'bin'/'claude-agent-reconciler'),'--once'],
                                env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        archive=None
        try:
            self.wait_marker(self.base/'launch-entered',launch)
            (agent/'done.json').write_text(done)
            control=json.loads((agent/'control.json').read_text())
            control['desired']='stopped'
            (agent/'control.json').write_text(json.dumps(control))
            archive=subprocess.Popen([str(ROOT/'bin'/'claude-agent-run'),'done-advance',str(agent)],
                                     env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try: archive.communicate(timeout=.3)
            except subprocess.TimeoutExpired: pass
            self.assertTrue(agent.is_dir(),'archive moved source while launch held admission')
            (self.base/'launch-release').touch()
            launch.communicate(timeout=10)
            archive.communicate(timeout=10)
            self.assertTrue(agent.is_dir(),'archive moved source after native unit became active')
        finally:
            (self.base/'launch-release').touch()
            for proc in (launch,archive):
                if proc is not None:
                    if proc.poll() is None: proc.kill()
                    proc.communicate()

    def test_INV_TASK_44_cached_reconciler_cannot_launch_after_archive(self):
        agent,done=self.launch_fixture()
        (self.base/'block-query').touch()
        launch=subprocess.Popen([str(ROOT/'bin'/'claude-agent-reconciler'),'--once'],
                                env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.wait_marker(self.base/'query-entered',launch)
            (agent/'done.json').write_text(done)
            control=json.loads((agent/'control.json').read_text())
            control['desired']='stopped'
            (agent/'control.json').write_text(json.dumps(control))
            self.cli('claude-agent-run','done-advance',agent,check=True)
            self.assertFalse(agent.exists(),'fixture archive did not win admission')
            (self.base/'query-release').touch()
            launch.communicate(timeout=10)
            self.assertFalse(agent.exists(),'cached reconciler recreated original path')
            self.assertFalse((self.base/'launch.log').exists(),'cached reconciler launched archived incarnation')
        finally:
            (self.base/'query-release').touch()
            if launch.poll() is None: launch.kill()
            launch.communicate()

    def test_INV_TASK_44_cached_reconciler_cannot_launch_replacement(self):
        agent,_=self.launch_fixture()
        (self.base/'block-query').touch()
        launch=subprocess.Popen([str(ROOT/'bin'/'claude-agent-reconciler'),'--once'],
                                env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.wait_marker(self.base/'query-entered',launch)
            original=self.base/'original-incarnation'
            agent.rename(original)
            shutil.copytree(original,agent)
            control=json.loads((agent/'control.json').read_text())
            control['incarnation']='replacement-incarnation'
            control['desired']='paused'
            (agent/'control.json').write_text(json.dumps(control))
            (agent/'replacement-proof').write_text('new object must remain')
            (self.base/'query-release').touch()
            launch.communicate(timeout=10)
            self.assertTrue((agent/'replacement-proof').exists())
            self.assertEqual(json.loads((agent/'control.json').read_text())['incarnation'],
                             'replacement-incarnation')
            self.assertFalse((self.base/'launch.log').exists(),
                             'cached reconciler launched into replacement incarnation')
        finally:
            (self.base/'query-release').touch()
            if launch.poll() is None: launch.kill()
            launch.communicate()

    def test_INV_TASK_44_replaced_incarnation_is_not_archived(self):
        agent=self.fixture('cleaned')
        (self.base/'block-query').touch()
        archive=subprocess.Popen([str(ROOT/'bin'/'claude-agent-run'),'done-advance',str(agent)],
                                 env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.wait_marker(self.base/'query-entered',archive)
            original=self.base/'original-incarnation'
            agent.rename(original)
            shutil.copytree(original,agent)
            control=json.loads((agent/'control.json').read_text())
            control['incarnation']='replacement-incarnation'
            (agent/'control.json').write_text(json.dumps(control))
            (agent/'replacement-proof').write_text('new object must remain')
            (self.base/'query-release').touch()
            archive.communicate(timeout=10)
            self.assertTrue((agent/'replacement-proof').exists(),
                            'stale archive moved the replacement incarnation')
            self.assertEqual(json.loads((agent/'control.json').read_text())['incarnation'],
                             'replacement-incarnation')
        finally:
            (self.base/'query-release').touch()
            if archive.poll() is None: archive.kill()
            archive.communicate()

    def test_INV_TASK_44_archive_wins_start_cannot_recreate_original(self):
        agent=self.fixture('cleaned')
        (self.base/'block-query').touch()
        archive=subprocess.Popen([str(ROOT/'bin'/'claude-agent-run'),'done-advance',str(agent)],
                                 env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        start=None
        try:
            self.wait_marker(self.base/'query-entered',archive)
            start=subprocess.Popen([str(ROOT/'bin'/'claude-rc'),'agent','start','archiveone'],
                                   env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            # The query gate holds archive's admission; start must wait or refuse.
            try:
                start.communicate(timeout=.3)
            except subprocess.TimeoutExpired:
                pass
            else:
                self.assertNotEqual(start.returncode,0,'start succeeded inside archive admission')
            (self.base/'query-release').touch()
            archive.communicate(timeout=10)
            self.assertEqual(archive.returncode,0)
            start.communicate(timeout=10)
            self.assertNotEqual(start.returncode,0,'start accepted an archived incarnation')
            self.assertFalse(agent.exists(),'start recreated archived original path')
            self.assertFalse((self.base/'launch.log').exists(),'start launched archived incarnation')
        finally:
            (self.base/'query-release').touch()
            for p in (archive,start):
                if p is not None:
                    if p.poll() is None: p.kill()
                    p.communicate()

if __name__=='__main__': unittest.main()
