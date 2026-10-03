#!/usr/bin/env python3
"""Blind public CLI contract tests: INV-TASK-39/41/42/51.
Real private Git fixtures; transparent query barriers, no production imports.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
os.umask(0o077)
TMP = Path(tempfile.mkdtemp(prefix='control-integration-fence-', dir='/var/tmp'))
REAL_GIT = shutil.which('git')
ENV = os.environ.copy()
ENV.update(HOME=str(TMP/'home'), CLAUDE_CONFIG_DIR=str(TMP/'cfg'),
           CLAUDE_AGENTS_DIR=str(TMP/'agents'), CLAUDE_AGENT_SPOOL_BASE=str(TMP/'spool'),
           CLAUDE_RECONCILER_DIR=str(TMP/'reconciler'), CLAUDE_AGENT_PROBE_CMD='/usr/bin/true',
           CLAUDE_AGENT_GENERATION='1', CLAUDE_AGENT_ATTEMPT='fixture',
           CLAUDE_RC_PROJECTS_FILE=str(TMP/'projects.yaml'), GIT_CONFIG_NOSYSTEM='1',
           GIT_AUTHOR_NAME='fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
           GIT_COMMITTER_NAME='fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
for name in ('home', 'cfg', 'agents', 'spool', 'reconciler', 'mockbin'):
    (TMP/name).mkdir()
(TMP/'projects.yaml').write_text('{}\n')
(TMP/'mockbin/systemctl').write_text('''#!/usr/bin/env python3
import sys
if 'is-active' in sys.argv:
 print('inactive'); sys.exit(3)
if 'show' in sys.argv:
 vals={'LoadState':'not-found','ActiveState':'inactive','SubState':'dead','MainPID':'0','ControlGroup':'','Result':'success'}
 for i,a in enumerate(sys.argv):
  if a in ('-p','--property'):
   for p in sys.argv[i+1].split(','): print(vals.get(p,'') if '--value' in sys.argv else p+'='+vals.get(p,''))
''')
(TMP/'mockbin/systemctl').chmod(0o700)
ENV['PATH'] = str(TMP/'mockbin')+':'+ENV['PATH']

def cmd(*args, check=True, env=None):
    p = subprocess.run(list(map(str,args)), env=env or ENV, text=True, capture_output=True)
    if check and p.returncode:
        raise AssertionError(f'fixture command {args}: {p.returncode}: {p.stderr}')
    return p

def git(repo,*args):
    return cmd(REAL_GIT,'-C',repo,*args).stdout.strip()

def data(path):
    return json.loads(path.read_text())

def fixture(name, kind='checked-ff', policy='merge'):
    name=name[:32].rstrip('-')
    base=TMP/name; base.mkdir(); repo=base/'repo'
    cmd(REAL_GIT,'init','-q','--initial-branch=main',repo)
    (repo/'base.txt').write_text('base\n'); git(repo,'add','.'); git(repo,'commit','-qm','base')
    registry={name:{'path':str(repo),'integrate':policy}}
    import yaml
    (TMP/'projects.yaml').write_text(yaml.safe_dump(registry))
    spec=base/'spec.yaml'
    spec.write_text(f'''schema: 1
name: {name}
type: event
role: none
project: {repo}
goal: integration fixture
autonomy: suggest
memory_max_mb: 100
limits: {{ runs_per_day: 100, run_timeout_s: 20 }}
source: {{ kind: spool, replay_window_h: 72 }}
workspace: worktree
''')
    cmd(ROOT/'bin/claude-rc','agent','create',name,'--spec',spec)
    agent=TMP/'agents'/name; work=agent/'work'
    (work/'task.txt').write_text('accepted\n'); git(work,'add','.'); git(work,'commit','-qm','task')
    if 'divergent' in kind:
        (repo/'target.txt').write_text('target\n'); git(repo,'add','.'); git(repo,'commit','-qm','target')
    if kind.startswith('unchecked'):
        git(repo,'checkout','-qb','parking')
    inflight=agent/'inbox/inflight'; inflight.mkdir(parents=True,exist_ok=True)
    (inflight/'done.json').write_text(json.dumps({'schema':1,'key':'done','source_ns':'test','native_id':'0','received_at':'2026-01-01T00:00:00Z','meta':{'attempts':0,'recoveries':0,'quarantined':False,'next_attempt_at':None,'history':[]},'payload':{'text':'done'}}))
    denv=ENV.copy(); denv.update(CLAUDE_AGENT_DIR=str(agent),CLAUDE_AGENT_EVENT_KEY='done')
    cmd(ROOT/'bin/claude-agent-done','--summary','fixture',env=denv)
    done=data(agent/'done.json'); done.update(state='accepted',verdict_at='2026-01-01T00:00:00Z',verdict_by='tg:1001',verdict_comment=None,integrate_mode=None,integrate_ref=None,phase_attempts=0,phase_error=None)
    (agent/'done.json').write_text(json.dumps(done))
    remote=base/'remote.git'; cmd(REAL_GIT,'init','--bare','-q',remote); git(repo,'remote','add','origin',str(remote))
    return dict(base=base,repo=repo,agent=agent,remote=remote,name=name,kind=kind,sha=done['commit_sha'],branch=done['branch'],target=git(repo,'rev-parse','main'))

WRAPPER='''#!/usr/bin/env python3
import json,os,subprocess,sys
from pathlib import Path
c=json.load(open(os.environ['FENCE_CONFIG'])); a=sys.argv[1:]
with open(c['log'],'a') as f: f.write(json.dumps(a)+'\\n')
if Path(c['marker']).exists() and ((c['action'].startswith('unknown-worktree') and 'worktree' in a and 'list' in a) or (c['action'].startswith('unknown-status') and 'status' in a and c['repo'] in a)):
 if c['action'].endswith('malformed'): print('unparseable git output'); sys.exit(0)
 sys.exit(1)
p=subprocess.run([c['git']]+a,capture_output=True)
trigger=(c['trigger']=='ancestry' and 'merge-base' in a and '--is-ancestor' in a and c['target'] in a and c['sha'] in a and a.index(c['target'])<a.index(c['sha'])) or (c['trigger']=='temporary' and 'merge' in a and '--no-edit' in a and '-C' in a and a[a.index('-C')+1]!=c['repo']) or (c['trigger']=='push' and 'push' in a)
mark=Path(c['marker'])
if trigger and not mark.exists():
 mark.write_text('triggered')
 action=c['action']
 if action=='sha': subprocess.run([c['git'],'-C',c['repo'],'update-ref','refs/heads/'+c['branch'],c['target']],check=True)
 elif action=='registry': Path(c['registry']).write_text('{}\\n')
 elif action=='dirty': (Path(c['repo'])/'late-dirty.txt').write_text('human data')
 elif action=='head':
  subprocess.run([c['git'],'-C',c['repo'],'commit','--allow-empty','-qm','late human commit'],check=True)
 elif action=='branch': subprocess.run([c['git'],'-C',c['repo'],'checkout','-qb','late-other'],check=True)
 elif action=='checkout': subprocess.run([c['git'],'-C',c['repo'],'worktree','add',c['duplicate'],'main'],check=True,stdout=subprocess.DEVNULL)
 elif action=='duplicate': subprocess.run([c['git'],'-C',c['repo'],'worktree','add','--force',c['duplicate'],'main'],check=True,stdout=subprocess.DEVNULL)
sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); sys.exit(p.returncode)
'''

def advance(f, action=None, trigger='ancestry'):
    e=ENV.copy()
    if action:
        cfg=dict(f,git=REAL_GIT,action=action,trigger=trigger,registry=ENV['CLAUDE_RC_PROJECTS_FILE'],marker=str(f['base']/'triggered'),log=str(f['base']/'git.log'),duplicate=str(f['base']/'duplicate'))
        cfg={k:str(v) for k,v in cfg.items()}; config=f['base']/'barrier.json'; config.write_text(json.dumps(cfg))
        wrapper=f['base']/'mock'; wrapper.mkdir(exist_ok=True); (wrapper/'git').write_text(WRAPPER); (wrapper/'git').chmod(0o700)
        e['FENCE_CONFIG']=str(config); e['PATH']=str(wrapper)+':'+e['PATH']
    p=cmd(ROOT/'bin/claude-agent-run','done-advance',f['agent'],check=False,env=e)
    (f['base']/'result.log').write_text(f'exit={p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}\ndone={json.dumps(data(f["agent"]/"done.json"))}\n')
    return p

def refused(f,p):
    d=data(f['agent']/'done.json')
    assert p.returncode==3, f'exit {p.returncode}: {p.stderr}'
    assert d['state']=='accepted' and d.get('phase_error'), f'not accepted/error: {d}'
    control=data(f['agent']/'control.json')
    assert control.get('attention'), f'no attention: {control}'

def unchanged(f):
    assert git(f['repo'],'rev-parse','main')==f['target'], 'target changed'

FAIL=[]; PASS=[]
def case(name,fn):
    selected=os.environ.get('FENCE_CASE_FILTER')
    if selected and selected not in name: return
    try: fn(); PASS.append(name); print('PASS',name,flush=True)
    except Exception as exc: FAIL.append(name); print('FAIL',name,str(exc),flush=True)

# INV-TASK-41: five distinct publication paths, two independent drift sources.
for kind in ('checked-ff','checked-divergent','unchecked-ff','unchecked-divergent','pr'):
    for action in ('sha','registry'):
        def test(kind=kind,action=action):
            f=fixture(f'{kind}-{action}',kind,'pr' if kind=='pr' else 'merge')
            if kind=='pr': gh(f,[])
            p=advance(f,action,'temporary' if kind=='unchecked-divergent' else 'ancestry')
            assert (f['base']/'triggered').exists(), 'public preparation barrier was not reached'
            refused(f,p); unchanged(f)
            assert git(f['repo'],'worktree','list','--porcelain').count('worktree ')==2,'temporary checkout leaked'
            if action=='sha': assert git(f['repo'],'rev-parse',f['branch'])==f['target'],'task drift rolled back'
            if kind=='pr': assert not git(f['remote'],'for-each-ref','--format=%(refname)'),'remote changed'
        if kind!='pr': case(f'{kind}-{action}',test)

# INV-TASK-42: target must retain identity, clean status and expected HEAD.
for action in ('dirty','head','branch','duplicate','unknown-worktree-error','unknown-worktree-malformed','unknown-status-error','unknown-status-malformed'):
    def test(action=action):
        f=fixture('target-'+action); p=advance(f,action)
        assert (f['base']/'triggered').exists(),'public preparation barrier was not reached'
        refused(f,p)
        if action!='head': unchanged(f)
        if action=='dirty': assert (f['repo']/'late-dirty.txt').read_text()=='human data'
    case('target-'+action,test)

# INV-TASK-42: a newly appeared checkout prohibits update-ref publication.
for kind in ('unchecked-ff','unchecked-divergent'):
    def test(kind=kind):
        f=fixture('appeared-'+kind,kind)
        p=advance(f,'checkout','temporary' if kind=='unchecked-divergent' else 'ancestry')
        assert (f['base']/'triggered').exists(),'preparation barrier not reached'
        refused(f,p); unchanged(f)
        assert git(f['base']/'duplicate','rev-parse','HEAD')==f['target'],'human checkout moved'
        assert git(f['repo'],'worktree','list','--porcelain').count('worktree ')==3,'temporary worktree leaked'
    case('appeared-'+kind,test)

# Valid paths establish fixtures and guard against blanket refusal.
for kind in ('checked-ff','checked-divergent','unchecked-ff','unchecked-divergent'):
    def test(kind=kind):
        f=fixture('positive-'+kind,kind); p=advance(f)
        assert p.returncode==0,p.stderr
        assert data(f['agent']/'done.json')['state']=='integrated'
        assert cmd(REAL_GIT,'-C',f['repo'],'merge-base','--is-ancestor',f['sha'],'main',check=False).returncode==0
        lines=git(f['repo'],'worktree','list','--porcelain'); assert lines.count('worktree ')==2,'temporary checkout leaked'
    case('positive-'+kind,test)

# INV-TASK-39/42: existing PR must prove exact accepted head.
def gh(f, rows, create_rows=None, action=None, create_crash=False):
    mock=f['base']/'ghbin'; mock.mkdir(exist_ok=True)
    response=f['base']/'prs.json'; response.write_text(json.dumps(rows) if not isinstance(rows,str) else rows)
    script=mock/'gh'; script.write_text(f'''#!/usr/bin/env python3
import json,sys
from pathlib import Path
with open({str(f['base']/'gh.log')!r},'a') as out: out.write(' '.join(sys.argv[1:])+'\\n')
if sys.argv[1:3]==['pr','list']:
 print(Path({str(response)!r}).read_text())
 if {action!r} and not Path({str(f['base']/'triggered')!r}).exists():
  Path({str(f['base']/'triggered')!r}).write_text('triggered')
  if {action!r}=='registry': Path({ENV['CLAUDE_RC_PROJECTS_FILE']!r}).write_text('{{}}\\n')
  else:
   import subprocess
   subprocess.run([{REAL_GIT!r},'-C',{str(f['repo'])!r},'update-ref',{'refs/heads/'+f['branch']!r},{f['target']!r}],check=True)
elif sys.argv[1:3]==['pr','view']:
 rows=json.loads(Path({str(response)!r}).read_text()); print(json.dumps(rows[0] if isinstance(rows,list) and len(rows)==1 else rows))
elif sys.argv[1:3]==['pr','create']:
 print('https://example.invalid/pull/1')
 Path({str(response)!r}).write_text({json.dumps(create_rows if create_rows is not None else rows)!r})
 if {create_crash!r}: sys.exit(1)
else: sys.exit(1)
'''); script.chmod(0o700)
    ENV['PATH']=str(mock)+':'+str(TMP/'mockbin')+':'+os.environ['PATH']

for mode in ('correct','wrong','missing','wrong-branch','missing-url','malformed','ambiguous'):
    def test(mode=mode):
        f=fixture('pr-existing-'+mode,policy='pr')
        row={'url':'https://example.invalid/pull/1','headRefName':f['branch'],'headRefOid':f['sha'],'state':'CLOSED'}
        rows=[row]
        if mode=='wrong': row['headRefOid']=f['target']
        if mode=='missing': row.pop('headRefOid')
        if mode=='wrong-branch': row['headRefName']='other-branch'
        if mode=='missing-url': row.pop('url')
        if mode=='malformed': rows='{"unparsed":true}'
        if mode=='ambiguous': rows=[row,row.copy()]
        gh(f,rows); p=advance(f)
        log=(f['base']/'gh.log').read_text()
        assert '--state all' in log,'list must include closed/merged'
        assert 'pr create' not in log,'created duplicate PR'
        assert not git(f['remote'],'for-each-ref','--format=%(refname)'),'pushed despite existing result'
        if mode=='correct': assert p.returncode==0 and data(f['agent']/'done.json')['state']=='integrated',p.stderr
        else: refused(f,p)
    case('pr-existing-'+mode,test)

# PR listing is preparation: mutate only after its genuine empty response.
for action in ('sha','registry'):
    def test(action=action):
        f=fixture('pr-prepush-'+action,policy='pr'); gh(f,[],action=action)
        p=advance(f)
        assert (f['base']/'triggered').exists(),'list preparation barrier not reached'
        refused(f,p)
        assert not git(f['remote'],'for-each-ref','--format=%(refname)'),'remote changed before fresh fence'
        assert 'pr create' not in (f['base']/'gh.log').read_text(),'PR created after drift'
    case('pr-prepush-'+action,test)

# INV-TASK-41: successful local push may precede drift, but create must not.
for action in ('sha','registry'):
    def test(action=action):
        f=fixture('pr-postpush-'+action,policy='pr'); gh(f,[])
        p=advance(f,action,'push')
        assert (f['base']/'triggered').exists(),'push barrier not reached'
        refused(f,p)
        assert git(f['remote'],'rev-parse',f['branch'])==f['sha'],'push must use accepted fixed SHA'
        assert 'pr create' not in (f['base']/'gh.log').read_text(),'create after drift'
    case('pr-postpush-'+action,test)

# New PR proof and uncertain-create recovery use either public list or view.
for mode in ('correct','wrong','missing'):
    def test(mode=mode):
        f=fixture('pr-created-'+mode,policy='pr')
        row={'url':'https://example.invalid/pull/1','headRefName':f['branch'],'headRefOid':f['sha']}
        if mode=='wrong': row['headRefOid']=f['target']
        if mode=='missing': row.pop('headRefOid')
        gh(f,[],[row]); p=advance(f)
        assert git(f['remote'],'rev-parse',f['branch'])==f['sha']
        log=(f['base']/'gh.log').read_text(); assert log.count('pr create')==1
        if mode=='correct':
            assert p.returncode==0 and data(f['agent']/'done.json')['state']=='integrated',p.stderr
            assert log.count('pr list')+log.count('pr view')>=2,'no postcreate proof'
        else:
            refused(f,p)
            # Correct proof on retry represents eventual externally resolved head.
            (f['base']/'prs.json').write_text(json.dumps([dict(row,headRefOid=f['sha'])]))
            retry=advance(f)
            assert retry.returncode==0 and data(f['agent']/'done.json')['state']=='integrated',retry.stderr
            assert (f['base']/'gh.log').read_text().count('pr create')==1,'duplicate PR during recovery'
    case('pr-created-'+mode,test)

# Unknown outcome after real local push and mocked create is recovered list-first.
def crash_recovery():
    f=fixture('pr-create-crash',policy='pr')
    row={'url':'https://example.invalid/pull/1','headRefName':f['branch'],'headRefOid':f['sha']}
    gh(f,[],[row],create_crash=True)
    p=advance(f); refused(f,p)
    assert git(f['remote'],'rev-parse',f['branch'])==f['sha']
    git(f['repo'],'remote','set-url','origin',str(f['base']/'unavailable.git'))
    retry=advance(f)
    assert retry.returncode==0 and data(f['agent']/'done.json')['state']=='integrated',retry.stderr
    assert (f['base']/'gh.log').read_text().count('pr create')==1,'created duplicate after unknown outcome'
case('pr-create-crash-recovery',crash_recovery)

# INV-TASK-51: excluded lessons dirty path, adjacent dirt remains protected.
for neighbor in (False,True):
    def test(neighbor=neighbor):
        f=fixture('lessons-'+str(neighbor).lower())
        lessons=f['repo']/'.claude/rules/lessons.md'; lessons.parent.mkdir(parents=True); lessons.write_text('lesson')
        if neighbor: (lessons.parent/'neighbor.md').write_text('human data')
        p=advance(f)
        if neighbor: refused(f,p); unchanged(f)
        else: assert p.returncode==0 and data(f['agent']/'done.json')['state']=='integrated',p.stderr
        assert lessons.read_text()=='lesson'
    case('lessons-'+str(neighbor),test)

# Conflict abort preserves target and removes temporary merge checkout.
for kind in ('checked-divergent','unchecked-divergent'):
    def test(kind=kind):
        f=fixture('conflict-'+kind,kind)
        # Public fixture card references accepted SHA from a real conflicting commit.
        work=f['agent']/'work'; (work/'base.txt').write_text('task conflict'); git(work,'add','.'); git(work,'commit','-qm','conflict')
        d=data(f['agent']/'done.json'); d['commit_sha']=git(work,'rev-parse','HEAD'); (f['agent']/'done.json').write_text(json.dumps(d))
        if kind.startswith('unchecked'): git(f['repo'],'checkout','main')
        (f['repo']/'base.txt').write_text('target conflict'); git(f['repo'],'add','.'); git(f['repo'],'commit','-qm','conflict target')
        f['target']=git(f['repo'],'rev-parse','main')
        if kind.startswith('unchecked'): git(f['repo'],'checkout','parking')
        p=advance(f); refused(f,p); unchanged(f)
        assert git(f['repo'],'worktree','list','--porcelain').count('worktree ')==2,'temporary worktree leaked'
        assert cmd(REAL_GIT,'-C',f['repo'],'rev-parse','--verify','MERGE_HEAD',check=False).returncode!=0,'merge not aborted'
    case('conflict-'+kind,test)

print(f'PASS={len(PASS)} FAIL={len(FAIL)} fixtures={TMP}',flush=True)
# Keep failed private fixtures and traces for independent review.
if not FAIL: shutil.rmtree(TMP)
raise SystemExit(bool(FAIL))
