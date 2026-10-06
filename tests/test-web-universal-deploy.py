#!/usr/bin/env python3
"""Blind INV-DEPLOY acceptance. Real Ed25519; private synthetic paths, no root services."""
import copy
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'deployment/ai-control-web-deploy.py'
BOOTSTRAP_COMMIT='da0ed863509641c249a1ffa05d54369867c4da9f'
LEGACY_MODES={'bin/ai-control-web':0o755,'bin/_control_web.py':0o644,'bin/_control_web_broker.py':0o644,
 'bin/_control_web_sessions.py':0o644,'bin/_codex_rc.py':0o644,'bin/_rc_projects.sh':0o755,
 'bin/_control_web.html':0o644,'bin/_control_web.css':0o644,'bin/_control_web.js':0o644,
 'requirements-web.lock':0o644,'systemd/ai-control-web.service.tmpl':0o644,
 'systemd/ai-control-web-broker.service.tmpl':0o644,'bin/_control_web.svg':0o644}
NEW_LEAF='bin/_control_web_configured_create.py'
NEW_PAYLOAD=b'# owned synthetic configured-create fixture\n'
MODES={**LEGACY_MODES,NEW_LEAF:0o644}
SERVICES=('ai-control-web.service','ai-control-web-broker.service')
def sha(data): return hashlib.sha256(data).hexdigest()

class SignedDeploy(unittest.TestCase):
 def setUp(self):
  self.assertTrue(SOURCE.is_file(),'INV-DEPLOY-01: accepted signed fixed-scope deployment helper absent')
  loader=importlib.machinery.SourceFileLoader('blind_signed_deploy',str(SOURCE))
  spec=importlib.util.spec_from_loader(loader.name,loader)
  self.api=importlib.util.module_from_spec(spec);sys.modules[loader.name]=self.api;loader.exec_module(self.api)
  for name in ('Deploy','Rejected','RollbackFailed','verify_ed25519','initialize_state'):
   self.assertTrue(callable(getattr(self.api,name,None)),'Accepted deploy public boundary absent: '+name)
  self.assertEqual(tuple(self.api.SERVICES),SERVICES)
  self.assertEqual(set(self.api.BOOTSTRAP_BASE),set(LEGACY_MODES))
  prior=os.umask(0o077);self.addCleanup(os.umask,prior)
  self.tmp=tempfile.TemporaryDirectory(prefix='signed-web-deploy-');self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.target=self.root/'target';self.stage=self.root/'stage'
  self.checkpoints=self.root/'checkpoints';self.state=self.root/'root-state/accepted.json'
  self.private=self.root/'keys/issuer-private.pem';self.key=self.root/'keys/release-key.pem'
  for path in (self.target,self.stage,self.checkpoints,self.state.parent,self.key.parent):path.mkdir(mode=0o700)
  self.base={}
  for relative,mode in LEGACY_MODES.items():
   baseline=subprocess.run(['/usr/bin/git','-C',str(ROOT),'show',BOOTSTRAP_COMMIT+':'+relative],
    stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
    env={'PATH':'/usr/bin:/bin','LANG':'C','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull},timeout=10)
   self.assertEqual(baseline.returncode,0,'Pinned public bootstrap Git fixture unavailable: '+relative)
   data=baseline.stdout;self.assertEqual(sha(data),self.api.BOOTSTRAP_BASE[relative],relative)
   self.base[relative]=data;self.write(self.target/relative,data,mode)
  self.current={**self.base,NEW_LEAF:NEW_PAYLOAD}
  self.crypto('genpkey','-algorithm','ED25519','-out',str(self.private));self.private.chmod(0o600)
  self.crypto('pkey','-in',str(self.private),'-pubout','-out',str(self.key));self.key.chmod(0o644)
  self.api.initialize_state(self.target,self.state,owner_uid=os.getuid())
  self.initial_state=self.state.read_bytes();self.calls=[];self.denied_calls=[];self.fail_starts=0;self.unhealthy=False
  self.addCleanup(lambda:self.assertEqual(self.denied_calls,[],'Helper attempted a command outside fixed service allowlist'))
  self.observations=[];self.helper_hash=sha(SOURCE.read_bytes());self.before_start=None

 def crypto(self,*args):
  result=subprocess.run(['/usr/bin/openssl',*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
   stderr=subprocess.PIPE,env={'PATH':'/usr/bin:/bin','LANG':'C'},timeout=10)
  self.assertEqual(result.returncode,0,'Synthetic OpenSSL operation failed (output intentionally omitted)')
  return result.stdout

 def write(self,path,data,mode=0o644):
  path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_bytes(data);path.chmod(mode)

 def hashes(self,files):return {p:sha(data) for p,data in files.items()}
 def tree(self):return {p:(self.target/p).read_bytes() for p in MODES if (self.target/p).is_file() and not (self.target/p).is_symlink()}
 def stops(self):return [c for c in self.calls if c[1]=='stop']
 def runner(self,args):
  allowed=isinstance(args,list) and len(args)>=3 and args[0]=='/usr/bin/systemctl' and args[1] in ('is-active','show','stop','start')
  if allowed:allowed=args[2] in SERVICES
  if not allowed:
   self.denied_calls.append('unallowlisted command');raise RuntimeError('DENIED_UNALLOWLISTED_RUNNER_REQUEST')
  self.assertIs(type(args),list);self.assertEqual(args[0],'/usr/bin/systemctl')
  self.assertIn(args[1],('is-active','show','stop','start'))
  if args[1] in ('stop','start'):
   self.assertTrue(args[2:]);self.assertTrue(all(s in SERVICES for s in args[2:]))
   if args[1]=='start':self.assertEqual(len(args),3)
  elif args[1]=='is-active':self.assertEqual(len(args),3);self.assertIn(args[2],SERVICES)
  else:
   self.assertEqual(len(args),6);self.assertIn(args[2],SERVICES)
   self.assertEqual(args[3],'-p');self.assertIn(args[4],('User','Group'));self.assertEqual(args[5],'--value')
  self.calls.append(list(args))
  if args[1]=='start':
   self.observations.append(self.hashes(self.tree()))
   if self.before_start is not None:self.before_start()
   if self.fail_starts:
    self.fail_starts-=1;raise RuntimeError('OWN_SYNTHETIC_START_FAILURE')
  if args[1]=='is-active':return 'inactive' if self.unhealthy else 'active'
  if args[1]=='show':return 'ai-panel' if args[4]=='Group' or args[2]==SERVICES[0] else 'dwl'
  return ''

 def deploy(self):return self.api.Deploy(self.target,self.stage,self.checkpoints,self.runner,
  state_path=self.state,key_path=self.key,owner_uid=os.getuid())

 def release(self,number=1,files=None,base=None,manifest_changes=None,raw=None):
  files=dict(self.current if files is None else files)
  for path in list(self.stage.iterdir()):
   if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
   else:path.unlink()
  for relative,data in files.items():self.write(self.stage/relative,data,MODES.get(relative,0o644))
  manifest=dict(schema=2,release_id=number,base=self.hashes(self.base if base is None else base),
   files={p:dict(sha256=sha(data),mode=MODES.get(p,0o644)) for p,data in files.items()})
  if manifest_changes:manifest.update(manifest_changes)
  encoded=json.dumps(manifest,separators=(',',':'),ensure_ascii=False).encode() if raw is None else raw
  self.write(self.stage/'release.json',encoded)
  self.crypto('pkeyutl','-sign','-inkey',str(self.private),'-rawin','-in',str(self.stage/'release.json'),
              '-out',str(self.stage/'release.sig'))
  (self.stage/'release.sig').chmod(0o644)
  self.assertEqual((self.stage/'release.sig').stat().st_size,64)
  return manifest

 def changed(self,marker=b'\n/* owned signed future release */\n'):
  files=dict(self.current);files['bin/_control_web.css']+=marker;return files

 def accepted(self,expected):
  try:result=self.deploy().run()
  except self.api.Rejected as exc:self.fail('A valid signed transition was refused: '+str(exc))
  self.assertEqual(result,expected)

 def refused(self):
  before=self.tree();state=self.state.read_bytes();stops=len(self.stops())
  with self.assertRaises(self.api.Rejected):self.deploy().run()
  self.assertEqual(self.tree(),before);self.assertEqual(self.state.read_bytes(),state)
  self.assertEqual(len(self.stops()),stops,'Rejected input stopped a service')

 def test_fixed_scope_has_legacy13_bootstrap_and_current14_signed_scope(self):
  self.assertEqual(getattr(self.api,'LEGACY_MODES',None),LEGACY_MODES)
  self.assertEqual(getattr(self.api,'MODES',None),MODES)
  self.assertEqual(set(self.api.BOOTSTRAP_BASE),set(LEGACY_MODES))
  self.assertEqual(set(self.tree()),set(LEGACY_MODES))
  initial=json.loads(self.initial_state)
  self.assertEqual(initial['schema'],1)
  self.assertEqual(initial['files'],self.hashes(self.base))

 def test_bootstrap_refuses_preexisting_new_leaf_without_state_creation(self):
  self.state.unlink()
  self.write(self.target/NEW_LEAF,NEW_PAYLOAD,0o644)
  with self.assertRaises(self.api.Rejected):
   self.api.initialize_state(self.target,self.state,owner_uid=os.getuid())
  self.assertFalse(self.state.exists())
  self.assertEqual((self.target/NEW_LEAF).read_bytes(),NEW_PAYLOAD)

 def test_literal_legacy_journal1_checkpoint13_recovers_before_signed14(self):
  # Captured legacy schema-1 layout: flat checkpoint basenames plus accepted.json.
  checkpoint_name='release-legacy13a'
  checkpoint=self.checkpoints/checkpoint_name
  checkpoint.mkdir(mode=0o700)
  for relative,data in self.base.items():
   self.write(checkpoint/Path(relative).name,data,0o600)
  self.write(checkpoint/'accepted.json',self.initial_state,0o600)
  after_files=dict(self.base);after_files['bin/_control_web.css']+=b'\n/* legacy journal fixture */\n'
  after={'schema':1,'release_id':1,'manifest_sha256':'c'*64,'files':self.hashes(after_files)}
  before=json.loads(self.initial_state)
  journal={'schema':1,'before':before,'after':after,'checkpoint':checkpoint_name}
  self.write(self.checkpoints/'pending.json',json.dumps(journal,separators=(',',':')).encode(),0o600)
  self.release(1,self.changed())
  self.accepted(dict(result='installed',release_id=1))
  self.assertEqual(self.tree(),self.current | {'bin/_control_web.css':self.current['bin/_control_web.css']+b'\n/* owned signed future release */\n'})
  self.assertFalse((self.checkpoints/'pending.json').exists())

 def test_checkpoint_directory_entry_is_fsynced_before_pending_publish(self):
  self.release(1,self.changed())
  event_path=self.root/'owned-fsync-events.jsonl'
  event_path.touch(mode=0o600)
  pid=os.fork()
  if pid==0:
   def log(event):
    fd=os.open(event_path,os.O_WRONLY|os.O_APPEND)
    try:os.write(fd,json.dumps(event,separators=(',',':')).encode()+b'\n')
    finally:os.close(fd)
   real_fsync=os.fsync;real_replace=os.replace
   def observed_fsync(fd):
    try:path=os.readlink('/proc/self/fd/'+str(fd))
    except OSError:path=''
    log({'kind':'fsync','path':path})
    return real_fsync(fd)
   def observed_replace(source,destination,*args,**kwargs):
    destination_path=Path(destination)
    if not destination_path.is_absolute() and kwargs.get('dst_dir_fd') is not None:
     destination_path=Path(os.readlink('/proc/self/fd/'+str(kwargs['dst_dir_fd'])))/destination_path
    if destination_path==self.checkpoints/'pending.json':log({'kind':'pending_publish'})
    return real_replace(source,destination,*args,**kwargs)
   original_runner=self.runner
   def stop_after_publish(args):
    if args[1]=='stop':os._exit(73)
    return original_runner(args)
   self.runner=stop_after_publish
   with patch('os.fsync',side_effect=observed_fsync),patch('os.replace',side_effect=observed_replace):
    try:self.deploy().run()
    except BaseException:os._exit(75)
   os._exit(74)
  waited,status=os.waitpid(pid,0);self.assertEqual(waited,pid)
  self.assertTrue(os.WIFEXITED(status));self.assertEqual(os.WEXITSTATUS(status),73,'Child did not reach pending-journal boundary')
  events=[json.loads(line) for line in event_path.read_text().splitlines()]
  publication=next((index for index,event in enumerate(events) if event['kind']=='pending_publish'),None)
  self.assertIsNotNone(publication,'No pending journal publication was observed')
  durable_dirs={Path(event['path']).resolve() for event in events[:publication] if event['kind']=='fsync' and event['path']}
  self.assertIn(self.checkpoints.resolve(),durable_dirs,'Checkpoint directory entry was not fsynced before pending publication')

 def test_real_ed25519_verifier_accepts_exact_bytes_and_refuses_forgery(self):
  self.release();manifest=(self.stage/'release.json').read_bytes();sig=(self.stage/'release.sig').read_bytes();key=self.key.read_bytes()
  self.assertIs(self.api.verify_ed25519(manifest,sig,key),True)
  for content,signature in ((manifest+b' ',sig),(manifest,sig[:-1]),(manifest,bytes(64)),(manifest,bytes([sig[0]^1])+sig[1:])):
   self.assertIs(self.api.verify_ed25519(content,signature,key),False)

 def test_two_future_signed_releases_use_unchanged_helper_and_default_crypto(self):
  first=self.changed();self.release(1,first)
  self.accepted(dict(result='installed',release_id=1));self.assertEqual(self.tree(),first)
  second=dict(first);second['bin/_control_web.js']+=b'\n// second accepted signed release\n'
  self.release(2,second,base=first)
  self.accepted(dict(result='installed',release_id=2));self.assertEqual(self.tree(),second)
  self.assertEqual(sha(SOURCE.read_bytes()),self.helper_hash)
  starts=[c[2] for c in self.calls if c[1]=='start']
  self.assertEqual(starts,[SERVICES[1],SERVICES[0],SERVICES[1],SERVICES[0]])
  state=json.loads(self.state.read_bytes());self.assertEqual(state['files'],self.hashes(second));self.assertEqual(state['release_id'],2)

 def test_same_committed_release_is_health_checked_noop(self):
  files=self.changed();self.release(1,files);self.accepted(dict(result='installed',release_id=1));self.calls.clear();before=self.state.read_bytes()
  self.accepted(dict(result='already_installed',release_id=1))
  self.assertFalse(self.stops());self.assertFalse(any(c[1]=='start' for c in self.calls));self.assertEqual(self.state.read_bytes(),before)
  self.assertEqual({c[2] for c in self.calls if c[1]=='is-active'},set(SERVICES))

 def test_signed_higher_identical_tree_advances_state_without_restart(self):
  self.release(1);self.accepted(dict(result='installed',release_id=1));self.calls.clear()
  self.release(2,base=self.current);self.accepted(dict(result='advanced',release_id=2))
  self.assertFalse(self.stops());self.assertFalse(any(c[1]=='start' for c in self.calls));self.assertEqual(self.tree(),self.current)
  self.assertEqual(json.loads(self.state.read_bytes())['manifest_sha256'],sha((self.stage/'release.json').read_bytes()))

 def test_unhealthy_signed_noop_is_not_success(self):
  self.release();self.unhealthy=True;self.refused()

 def test_signature_manifest_payload_tamper_reject_before_effects(self):
  self.release(1,self.changed());signature=self.stage/'release.sig'
  signature.write_bytes(bytes(64));self.refused()
  self.release(1,self.changed());manifest=self.stage/'release.json';manifest.write_bytes(manifest.read_bytes()+b' ');self.refused()
  self.release(1,self.changed());(self.stage/'bin/_control_web.css').write_bytes(b'tampered unsigned payload');self.refused()

 def test_all_fourteen_payload_hashes_are_authoritative(self):
  for relative in MODES:
   with self.subTest(relative=relative):
    self.release(1,self.changed());(self.stage/relative).write_bytes(b'owned tampered fixture');self.refused()

 def test_strict_signed_schema_ids_duplicate_unknown_keys_and_hashes(self):
  valid=self.release();raw=(self.stage/'release.json').read_bytes()
  variants=[raw.replace(b'"schema":2',b'"schema":2,"schema":2'),
   json.dumps(dict(valid,schema=1)).encode(),
   json.dumps(dict(valid,extra='no hooks')).encode(),json.dumps(dict(valid,release_id=True)).encode(),
   json.dumps(dict(valid,release_id=0)).encode(),json.dumps(dict(valid,release_id=2**63)).encode(),
   json.dumps(dict(valid,base={})).encode(),b'x'*65537]
  broken=copy.deepcopy(valid);broken['files']['bin/_control_web.css']['sha256']='A'*64;variants.append(json.dumps(broken).encode())
  for raw in variants:
   with self.subTest(raw=raw[:40]):self.release(raw=raw);self.refused()

 def test_signed_paths_extra_mode_and_missing_path_cannot_expand_scope(self):
  valid=self.release()
  for mutate in (lambda m:m['files'].update({'../outside':dict(sha256='0'*64,mode=0o644)}),
   lambda m:m['files'].pop('bin/_control_web.css'),lambda m:m['files']['bin/_control_web.css'].update(mode=0o755),
   lambda m:m['files']['bin/_control_web.css'].update(mode=True)):
   manifest=copy.deepcopy(valid);mutate(manifest);self.release(raw=json.dumps(manifest).encode());self.refused()

 def test_stage_extra_file_symlink_hardlink_and_special_file_refuse(self):
  for kind in ('extra','symlink','hardlink','fifo'):
   with self.subTest(kind=kind):
    self.release();leaf=self.stage/'bin/_control_web.css'
    if kind=='extra':self.write(self.stage/'unapproved.py',b'never execute')
    elif kind=='symlink':leaf.unlink();leaf.symlink_to(self.target/'bin/_control_web.css')
    elif kind=='hardlink':
     alias=self.root/'stage-private-alias';self.write(alias,self.base['bin/_control_web.css']);leaf.unlink();os.link(alias,leaf)
    else:leaf.unlink();os.mkfifo(leaf,0o600)
    self.refused()

 def test_stage_group_writable_file_and_directory_refuse(self):
  self.release();(self.stage/'bin/_control_web.css').chmod(0o666);self.refused()
  self.release();(self.stage/'bin').chmod(0o770);self.refused();(self.stage/'bin').chmod(0o700)

 def test_individual_and_total_payload_bounds(self):
  files=dict(self.current);files['bin/_control_web.css']=b'x'*(2*1024*1024+1);self.release(1,files);self.refused()
  files={p:b'x'*(2*1024*1024+1) for p in MODES};self.release(1,files);self.refused()

 def test_wrong_signed_base_old_id_and_same_id_conflicting_manifest_refuse(self):
  files=self.changed();self.release(1,files);self.accepted(dict(result='installed',release_id=1))
  self.release(2,files,base=self.base);self.refused()
  self.release(1,files,base=files);self.refused()
  self.release(2,files,base=files);self.accepted(dict(result='advanced',release_id=2))
  self.release(1,files,base=files);self.refused()

 def test_target_untracked_drift_or_mixed_accepted_tree_refuse(self):
  self.release(1,self.changed());leaf=self.target/'bin/_control_web.css';leaf.write_bytes(b'unknown target drift');self.refused()

 def test_preexisting_new_leaf_even_matching_release_payload_is_drift(self):
  self.release(1,self.changed())
  leaf=self.target/NEW_LEAF;self.write(leaf,NEW_PAYLOAD,0o644)
  self.refused()
  self.assertEqual(leaf.read_bytes(),NEW_PAYLOAD)

 def test_target_modes_symlink_or_hardlink_refuse(self):
  for kind in ('mode','symlink','hardlink'):
   with self.subTest(kind=kind):
    self.release();leaf=self.target/'bin/_control_web.css';original=self.base['bin/_control_web.css']
    if kind=='mode':leaf.chmod(0o666)
    elif kind=='symlink':leaf.unlink();leaf.symlink_to(self.stage/'bin/_control_web.css')
    else:
     alias=self.root/'target-leaf-alias';os.link(leaf,alias)
    with self.assertRaises(self.api.Rejected):self.deploy().run()
    self.assertFalse(self.stops())
    if kind=='hardlink':alias.unlink()
    if leaf.is_symlink():leaf.unlink()
    self.write(leaf,original)

 def test_wrong_expected_owner_refuses_even_a_genuinely_signed_release(self):
  self.release()
  deployment=self.api.Deploy(self.target,self.stage,self.checkpoints,self.runner,
   state_path=self.state,key_path=self.key,owner_uid=os.getuid()+1)
  with self.assertRaises(self.api.Rejected):deployment.run()
  self.assertFalse(self.stops());self.assertEqual(self.state.read_bytes(),self.initial_state)

 def test_absent_state_never_bootstraps_from_signed_manifest(self):
  self.release();self.state.unlink()
  with self.assertRaises(self.api.Rejected):self.deploy().run()
  self.assertFalse(self.state.exists());self.assertFalse(self.stops())

 def test_initialize_state_verifies_bootstrap_and_refuses_overwrite(self):
  with self.assertRaises(self.api.Rejected):self.api.initialize_state(self.target,self.state,owner_uid=os.getuid())
  self.state.unlink();(self.target/'bin/_control_web.css').write_bytes(b'unknown bootstrap')
  with self.assertRaises(self.api.Rejected):self.api.initialize_state(self.target,self.state,owner_uid=os.getuid())
  self.assertFalse(self.state.exists())

 def test_state_and_key_permissions_symlinks_hardlinks_refuse(self):
  self.release()
  for path in (self.state,self.key):
   original=path.read_bytes();mode=0o600 if path==self.state else 0o644
   path.chmod(0o666)
   with self.assertRaises(self.api.Rejected):self.deploy().run()
   path.chmod(mode);alias=path.with_name('own-alias');os.link(path,alias)
   with self.assertRaises(self.api.Rejected):self.deploy().run()
   alias.unlink();path.rename(alias);path.symlink_to(alias)
   with self.assertRaises(self.api.Rejected):self.deploy().run()
   path.unlink();alias.rename(path);self.assertEqual(path.read_bytes(),original)
  self.assertFalse(self.stops())

 def test_forged_root_state_and_malformed_private_state_refuse(self):
  self.release()
  for raw in (b'{invalid',b'{"schema":1,"schema":1}',json.dumps(dict(schema=1,release_id=True,manifest_sha256=None,files=self.hashes(self.base))).encode()):
   self.state.write_bytes(raw)
   with self.assertRaises(self.api.Rejected):self.deploy().run()
   self.assertFalse(self.stops())
  self.state.write_bytes(self.initial_state)

 def test_start_failure_rolls_back_exact_old_tree_state_and_order(self):
  self.release(1,self.changed());self.fail_starts=1
  with self.assertRaises((self.api.Rejected,RuntimeError)):self.deploy().run()
  self.assertEqual(self.tree(),self.base);self.assertEqual(self.state.read_bytes(),self.initial_state)
  starts=[c[2] for c in self.calls if c[1]=='start'];self.assertEqual(starts[-2:],[SERVICES[1],SERVICES[0]])
  retained=[directory for directory in self.checkpoints.iterdir() if directory.is_dir()]
  retained_hashes={sha(path.read_bytes()) for directory in retained for path in directory.rglob('*') if path.is_file()}
  self.assertTrue(set(self.hashes(self.base).values()) <= retained_hashes,'Failed deployment lost its durable previous13 snapshots')

 def test_rollback_restores_noncanonical_before_state_byte_exactly(self):
  state=json.loads(self.initial_state)
  raw=json.dumps(state,ensure_ascii=False,indent=2).encode()+b'\n'
  self.state.write_bytes(raw)
  self.release(1,self.changed());self.fail_starts=1
  try:self.deploy().run()
  except (self.api.Rejected,RuntimeError):pass
  else:self.fail('Synthetic start failure unexpectedly completed deployment')
  self.assertTrue(any(call[1]=='stop' for call in self.calls),'Deployment refused before reaching rollback')
  self.assertEqual(self.tree(),self.base)
  self.assertEqual(self.state.read_bytes(),raw,'Rollback normalized or rewrote the accepted before-state bytes')

 def test_rollback_refuses_unknown_new_leaf_bytes_without_overwrite(self):
  self.release(1,self.changed());self.fail_starts=1
  injected=b'unknown owned synthetic bytes'
  self.before_start=lambda:self.write(self.target/NEW_LEAF,injected,0o644)
  try:self.deploy().run()
  except (self.api.RollbackFailed,self.api.Rejected):pass
  else:self.fail('A failed deployment with an unknown new leaf unexpectedly succeeded')
  leaf=self.target/NEW_LEAF
  self.assertTrue(leaf.exists(),'The transition did not reach its owned new-leaf rollback boundary')
  self.assertEqual(leaf.read_bytes(),injected,'Rollback overwrote unknown new-leaf bytes')
  self.assertTrue((self.checkpoints/'pending.json').is_file(),'Unsafe rollback discarded recovery evidence')

 def test_rollback_refuses_new_leaf_hardlink_without_unlinking_either_name(self):
  self.release(1,self.changed());self.fail_starts=1
  alias=self.root/'owned-new-leaf-alias'
  def add_link():os.link(self.target/NEW_LEAF,alias)
  self.before_start=add_link
  try:self.deploy().run()
  except (self.api.RollbackFailed,self.api.Rejected):pass
  else:self.fail('A failed deployment with a hardlinked new leaf unexpectedly succeeded')
  leaf=self.target/NEW_LEAF
  self.assertTrue(leaf.is_file());self.assertFalse(leaf.is_symlink())
  self.assertTrue(alias.is_file());self.assertEqual(os.stat(leaf).st_ino,os.stat(alias).st_ino)
  self.assertEqual(os.stat(leaf).st_nlink,2,'Unsafe rollback removed the protected hardlink')

 def test_rollback_refuses_new_leaf_with_unexpected_mode_without_chmod(self):
  self.release(1,self.changed());self.fail_starts=1
  self.before_start=lambda:(self.target/NEW_LEAF).chmod(0o600)
  try:self.deploy().run()
  except (self.api.RollbackFailed,self.api.Rejected):pass
  else:self.fail('A failed deployment with a mode-drifted new leaf unexpectedly succeeded')
  leaf=self.target/NEW_LEAF
  self.assertTrue(leaf.is_file());self.assertEqual(leaf.stat().st_mode&0o777,0o600)
  self.assertTrue((self.checkpoints/'pending.json').is_file())

 def test_rollback_allows_already_absent_new_leaf(self):
  self.release(1,self.changed());self.fail_starts=1
  def remove_new_leaf_once():
   self.before_start=None
   (self.target/NEW_LEAF).unlink()
  self.before_start=remove_new_leaf_once
  with self.assertRaises((self.api.Rejected,RuntimeError)):
   self.deploy().run()
  self.assertEqual(self.tree(),self.base)
  self.assertEqual(self.state.read_bytes(),self.initial_state)
  self.assertFalse((self.checkpoints/'pending.json').exists())

 def test_rollback_failure_is_explicit_and_keeps_recovery_evidence(self):
  self.release(1,self.changed());self.fail_starts=100
  with self.assertRaises((self.api.RollbackFailed,self.api.Rejected)):self.deploy().run()
  self.assertTrue((self.checkpoints/'pending.json').is_file(),'Rollback failure discarded pending recovery authority')
  self.assertEqual(self.state.read_bytes(),self.initial_state)

 def child_crash(self,boundary):
  pid=os.fork()
  if pid==0:
   try:
    if boundary=='journal_before_stop':
     original=self.runner
     def stop_after_journal(args):
      if args[1]=='stop':os._exit(73)
      return original(args)
     self.runner=stop_after_journal
     self.deploy().run()
    else:
     genuine=os.replace
     def crash_after_atomic_replace(source,destination,*args,**kwargs):
      result=genuine(source,destination,*args,**kwargs)
      destination=Path(destination)
      if not destination.is_absolute() and kwargs.get('dst_dir_fd') is not None:
       destination=Path(os.readlink('/proc/self/fd/'+str(kwargs['dst_dir_fd'])))/destination
      if boundary=='new_leaf_installed' and destination==self.target/NEW_LEAF:os._exit(73)
      if boundary=='mixed_tree' and destination==self.target/'bin/_control_web.css':os._exit(73)
      if boundary=='state_published' and destination==self.state and self.state.read_bytes()!=self.initial_state:os._exit(73)
      return result
     with patch('os.replace',side_effect=crash_after_atomic_replace):self.deploy().run()
    os._exit(74)
   except BaseException:os._exit(75)
  waited,status=os.waitpid(pid,0);self.assertEqual(waited,pid)
  self.assertTrue(os.WIFEXITED(status));self.assertEqual(os.WEXITSTATUS(status),73,'Owned child never reached declared crash boundary')

 def test_default_crypto_clears_attacker_openssl_environment(self):
  self.release();invalid=self.root/'invalid-openssl.cnf';invalid.write_text('not a valid OpenSSL configuration')
  with patch.dict(os.environ,{'OPENSSL_CONF':str(invalid),'PATH':'/owned-invalid-path'}):
   self.assertIs(self.api.verify_ed25519((self.stage/'release.json').read_bytes(),
    (self.stage/'release.sig').read_bytes(),self.key.read_bytes()),True)

 def test_real_journal_precedes_first_stop_and_recovers_old_before_new_stage(self):
  files=self.changed();self.release(1,files);self.child_crash('journal_before_stop')
  pending=self.checkpoints/'pending.json';self.assertTrue(pending.is_file())
  journal=json.loads(pending.read_bytes());self.assertEqual(set(journal),{'schema','before','after','checkpoint'})
  self.assertEqual(journal['before'],json.loads(self.initial_state));self.assertEqual(journal['after']['files'],self.hashes(files))
  self.assertEqual(self.tree(),self.base);self.assertEqual(self.state.read_bytes(),self.initial_state)
  self.assertEqual(self.deploy().run(),dict(result='installed',release_id=1))
  self.assertEqual(self.observations[0],self.hashes(self.base),'Recovery did not restore accepted old tree before considering stage')
  self.assertEqual(self.tree(),files);self.assertFalse(pending.exists())

 def test_crash_mixed_known_tree_restores_old_before_rejecting_bad_stage(self):
  files=self.changed();files['bin/_control_web.js']+=b'\n// authorized second delta\n'
  self.release(1,files);self.child_crash('mixed_tree')
  mixed=self.tree();self.assertEqual(mixed['bin/_control_web.css'],files['bin/_control_web.css'])
  self.assertEqual(mixed['bin/_control_web.js'],self.base['bin/_control_web.js'])
  (self.stage/'release.sig').write_bytes(bytes(64))
  with self.assertRaises(self.api.Rejected):self.deploy().run()
  self.assertEqual(self.tree(),self.base);self.assertEqual(self.state.read_bytes(),self.initial_state)
  self.assertEqual(self.observations[0],self.hashes(self.base))

 def test_recovery_refuses_unknown_old_leaf_before_removing_known_new_leaf(self):
  files=self.changed();self.release(1,files);self.child_crash('new_leaf_installed')
  leaf=self.target/NEW_LEAF
  self.assertEqual(leaf.read_bytes(),files[NEW_LEAF])
  old_leaf=self.target/'bin/_control_web.css';old_leaf.write_bytes(b'unknown old-scope drift')
  before=self.tree();state=self.state.read_bytes();pending=(self.checkpoints/'pending.json').read_bytes()
  with self.assertRaises(self.api.Rejected):self.deploy().run()
  self.assertEqual(self.tree(),before)
  self.assertEqual(self.state.read_bytes(),state)
  self.assertEqual((self.checkpoints/'pending.json').read_bytes(),pending)
  self.assertEqual(leaf.read_bytes(),files[NEW_LEAF],'Recovery removed the known after-leaf before checking old-scope drift')

 def test_crash_after_state_publish_recognizes_committed_tree_without_restart(self):
  files=self.changed();self.release(1,files);self.child_crash('state_published')
  self.assertEqual(json.loads(self.state.read_bytes())['files'],self.hashes(files));self.assertEqual(self.tree(),files)
  self.assertTrue((self.checkpoints/'pending.json').exists())
  self.assertEqual(self.deploy().run(),dict(result='already_installed',release_id=1))
  self.assertFalse(self.stops());self.assertFalse(any(c[1]=='start' for c in self.calls))
  self.assertFalse((self.checkpoints/'pending.json').exists())

 def test_corrupt_emitted_journal_or_checkpoint_refuses_without_stop_or_write(self):
  self.release(1,self.changed());self.child_crash('journal_before_stop')
  pending=self.checkpoints/'pending.json';original=pending.read_bytes()
  for raw in (b'{invalid',json.dumps(dict(json.loads(original),checkpoint='../outside')).encode(),
              json.dumps(json.loads(original)).encode().replace(b'"schema": 1',b'"schema": 1, "schema": 1')):
   if raw==original:continue
   pending.write_bytes(raw);before=self.tree()
   with self.assertRaises(self.api.Rejected):self.deploy().run()
   self.assertEqual(self.tree(),before);self.assertFalse(self.stops());self.assertEqual(pending.read_bytes(),raw)
  pending.write_bytes(original);journal=json.loads(original)
  checkpoint=self.checkpoints/journal['checkpoint'];self.assertTrue(checkpoint.is_dir())
  snapshot=next(p for p in checkpoint.rglob('*') if p.is_file())
  snapshot.write_bytes(b'owned corrupt checkpoint snapshot')
  with self.assertRaises(self.api.Rejected):self.deploy().run()
  self.assertFalse(self.stops());self.assertEqual(self.state.read_bytes(),self.initial_state)

 def test_pending_journal_does_not_authorize_unknown_target_bytes(self):
  self.release(1,self.changed());self.child_crash('journal_before_stop')
  leaf=self.target/'bin/_control_web.css';leaf.write_bytes(b'unknown unsigned current target')
  before=self.tree();state=self.state.read_bytes()
  with self.assertRaises(self.api.Rejected):self.deploy().run()
  self.assertEqual(self.tree(),before);self.assertEqual(self.state.read_bytes(),state);self.assertFalse(self.stops())

 def test_cli_nonroot_and_any_argument_refuse_without_service_execution(self):
  for arguments in ([],['--stage',str(self.stage)],['--initialize']):
   result=subprocess.run([sys.executable,str(SOURCE),*arguments],stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={'PATH':'/usr/bin:/bin','HOME':str(self.root)},timeout=5)
   self.assertNotEqual(result.returncode,0)
  self.assertNotEqual(os.geteuid(),0,'This synthetic root-CLI refusal fixture must run unprivileged')

if __name__=='__main__':unittest.main()
