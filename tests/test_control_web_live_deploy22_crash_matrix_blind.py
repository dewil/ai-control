"""INV-DEPLOY-24 independent required A1/A3/temp/rollback crash matrix.

Crash actual filesystem syscalls; resume only actual bootstrap(). No private calls.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import unittest
import zipfile
from unittest.mock import patch
import deploy22_blind_support as s
from test_control_web_live_deploy22_dependency_blind import SyntheticProcessDeath


def fdpath(fd):return Path(os.readlink('/proc/self/fd/'+str(fd)))
def fullpath(value,kwargs,key):
    path=Path(os.fspath(value))
    return path if path.is_absolute() else fdpath(kwargs[key])/path if kwargs.get(key) is not None else Path.cwd()/path

def hashed_tree(case):
    return {str(p.relative_to(case.root)):(s.sha(p.read_bytes()),p.lstat().st_mode&0o777) for p in case.root.rglob('*') if p.is_file() and not p.is_symlink()}

class RequiredCrashMatrixBlind(s.BootstrapFixture):
    def setUp(self):self.prepare()
    def fresh(self):
        case=s.BootstrapFixture('runTest');case.prepare();return case
    def forward_complete(self,case):
        case.trace.clear();case.invoke();self.assertEqual(case.installed_rows(),s.rows())
        self.assertEqual(case.state.read_bytes(),case.initial_state);self.assertTrue(case.receipt.exists())
        self.assertFalse(case.paths['BOOTSTRAP_PENDING'].exists())
        self.assertEqual(sum(row['argv'][0]=='/usr/bin/setpriv' for row in case.trace),1)
        self.assertLessEqual(sum(row['argv'][0]=='/usr/bin/systemctl' for row in case.trace),15)
    def rollback_complete(self,case):
        case.trace.clear()
        try:self.assertIsNone(case.invoke())
        except ValueError:pass  # Successful rollback may report sanitized operation refusal.
        self.assertEqual(case.state.read_bytes(),case.initial_state)
        self.assertEqual(case.helper.read_bytes(),s.pinned_source());self.assertEqual(case.unit.read_bytes(),case.before_unit)
        self.assertFalse(case.paths['DEP_PACKAGE'].exists());self.assertFalse(case.paths['DEP_INFO'].exists())
        self.assertFalse(case.receipt.exists());self.assertFalse(case.paths['BOOTSTRAP_PENDING'].exists())
        self.assertFalse(any(row['argv'][0]=='/usr/bin/setpriv' for row in case.trace))
        self.assertLessEqual(sum(row['argv'][0]=='/usr/bin/systemctl' for row in case.trace),15)

    def test_A1_and_A3_temp_prefix0_1_half_full_resume(self):
        for stage in ('nats','info'):
            for length_kind in ('zero','one','half','full'):
                with self.subTest(stage=stage,prefix=length_kind):
                    case=self.fresh()
                    try:
                        events=[];stage_name='.ai-control-live22-'+stage+'.stage'
                        # O_EXCL descriptor creation is frozen; avoid requiring a particular
                        # Python write implementation. Inject a legitimate interrupted prefix
                        # into that actual descriptor, then emulate process death before return.
                        with case.root_boundary():
                            real_open=os.open
                            def opened(path,flags,*args,**kwargs):
                                fd=real_open(path,flags,*args,**kwargs);actual=fdpath(fd)
                                if stage_name in actual.parts and actual.name.startswith('.live22-') and actual.name.endswith('.part') and flags&os.O_CREAT and not events:
                                    digest=actual.name[len('.live22-'):-len('.part')]
                                    prefix='nats/' if stage=='nats' else 'nats_py-2.9.0.dist-info/'
                                    relative_parent=actual.parent.relative_to(case.site/stage_name)
                                    matching=[row for row in s.rows() if row['sha256']==digest and row['path'].startswith(prefix) and Path(row['path'][len(prefix):]).parent==relative_parent]
                                    self.assertEqual(len(matching),1)
                                    with zipfile.ZipFile(s.WHEEL) as archive:data=archive.read(matching[0]['path'])
                                    count={'zero':0,'one':min(1,len(data)),'half':len(data)//2,'full':len(data)}[length_kind]
                                    if count:os.write(fd,data[:count])
                                    events.append(actual);os.close(fd);raise SyntheticProcessDeath()
                                return fd
                            with patch.object(os,'open',side_effect=opened):
                                with self.assertRaises(SyntheticProcessDeath):case.op.bootstrap()
                        self.assertEqual(len(events),1);temp=events[0]
                        self.assertTrue(temp.is_file());self.assertEqual(temp.lstat().st_mode&0o777,0o600)
                        self.assertTrue(case.paths['BOOTSTRAP_PENDING'].exists());self.assertFalse(case.receipt.exists())
                        if stage=='info':self.assertTrue(case.paths['DEP_PACKAGE'].exists())
                        else:self.assertFalse(case.paths['DEP_PACKAGE'].exists())
                        self.forward_complete(case)
                        self.assertFalse(temp.exists())
                    finally:case.doCleanups()

    def test_A1_A3_complete0755_stage_fsync_before_promotion_resume(self):
        for stage in ('nats','info'):
            with self.subTest(stage=stage):
                case=self.fresh()
                try:
                    real=os.fsync;events=[];stage_name='.ai-control-live22-'+stage+'.stage'
                    def fsync(fd):
                        result=real(fd);path=fdpath(fd)
                        if path.name==stage_name and os.fstat(fd).st_mode&0o777==0o755 and not events:
                            events.append(path);raise SyntheticProcessDeath()
                        return result
                    with patch.object(os,'fsync',side_effect=fsync):
                        with self.assertRaises(SyntheticProcessDeath):case.invoke()
                    self.assertEqual(len(events),1);directory=events[0];self.assertTrue(directory.is_dir())
                    self.assertFalse(case.paths['DEP_INFO'].exists())
                    if stage=='nats':self.assertFalse(case.paths['DEP_PACKAGE'].exists())
                    self.forward_complete(case);self.assertFalse(directory.exists())
                finally:case.doCleanups()

    def test_A1_A3_first_member_rename_leaves_exact_subset_then_resume(self):
        for stage in ('nats','info'):
            with self.subTest(stage=stage):
                case=self.fresh()
                try:
                    rename=os.rename;replace=os.replace;events=[];stage_name='.ai-control-live22-'+stage+'.stage'
                    def intercept(call,source,destination,*args,**kwargs):
                        source_path=fullpath(source,kwargs,'src_dir_fd');destination_path=fullpath(destination,kwargs,'dst_dir_fd')
                        result=call(source,destination,*args,**kwargs)
                        if stage_name in source_path.parts and source_path.name.startswith('.live22-') and not events:
                            events.append(destination_path);raise SyntheticProcessDeath()
                        return result
                    with patch.object(os,'rename',side_effect=lambda *a,**k:intercept(rename,*a,**k)), \
                         patch.object(os,'replace',side_effect=lambda *a,**k:intercept(replace,*a,**k)):
                        with self.assertRaises(SyntheticProcessDeath):case.invoke()
                    self.assertEqual(len(events),1);self.assertTrue(events[0].is_file());self.assertEqual(events[0].stat().st_mode&0o777,0o644)
                    self.forward_complete(case)
                finally:case.doCleanups()

    def test_rollback_INFO_then_NATS_rename_intent_precedes_rename_and_resume_never_promotes(self):
        for stage in ('info','nats'):
            with self.subTest(stage=stage):
                case=self.fresh()
                try:
                    case.smoke_result=subprocess.CompletedProcess([],1,b'',b'')
                    rename=os.rename;replace=os.replace;events=[];stage_name='.ai-control-live22-'+stage+'.stage'
                    def intercept(call,source,destination,*args,**kwargs):
                        destination_path=fullpath(destination,kwargs,'dst_dir_fd')
                        if destination_path.name==stage_name:
                            marker=json.loads(case.paths['BOOTSTRAP_PENDING'].read_bytes());self.assertEqual(marker['stage'],'rollback')
                        result=call(source,destination,*args,**kwargs)
                        if destination_path.name==stage_name and not events:events.append(destination_path);raise SyntheticProcessDeath()
                        return result
                    with patch.object(os,'rename',side_effect=lambda *a,**k:intercept(rename,*a,**k)), \
                         patch.object(os,'replace',side_effect=lambda *a,**k:intercept(replace,*a,**k)):
                        with self.assertRaises(SyntheticProcessDeath):case.invoke()
                    self.assertEqual(len(events),1);self.assertTrue(events[0].is_dir())
                    self.rollback_complete(case)
                finally:case.doCleanups()

    def test_rollback_partial_INFO_and_NATS_stage_unlink_resume(self):
        for stage in ('info','nats'):
            with self.subTest(stage=stage):
                case=self.fresh()
                try:
                    case.smoke_result=subprocess.CompletedProcess([],1,b'',b'');real=os.unlink;events=[]
                    stage_name='.ai-control-live22-'+stage+'.stage'
                    def unlink(path,*args,**kwargs):
                        actual=fullpath(path,kwargs,'dir_fd');result=real(path,*args,**kwargs)
                        if stage_name in actual.parts and not events:
                            events.append(actual);raise SyntheticProcessDeath()
                        return result
                    with patch.object(os,'unlink',side_effect=unlink):
                        with self.assertRaises(SyntheticProcessDeath):case.invoke()
                    self.assertEqual(len(events),1);self.assertFalse(events[0].exists())
                    self.assertEqual(json.loads(case.paths['BOOTSTRAP_PENDING'].read_bytes())['stage'],'rollback')
                    self.rollback_complete(case)
                finally:case.doCleanups()

    def test_preserved_exact_smoke_failure_rollback_never_unlinks_or_renames_dependency(self):
        self.dependency_after();self.receipt.unlink()
        before={row['path']:((self.site/row['path']).stat().st_ino,s.sha((self.site/row['path']).read_bytes())) for row in s.rows()}
        self.smoke_result=subprocess.CompletedProcess([],1,b'',b'')
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual({row['path']:((self.site/row['path']).stat().st_ino,s.sha((self.site/row['path']).read_bytes())) for row in s.rows()},before)
        self.assertEqual(self.helper.read_bytes(),s.pinned_source());self.assertEqual(self.unit.read_bytes(),self.before_unit)
        self.assertFalse(self.receipt.exists())

    def test_checkpoint_foreign_collision_and_fifth_transaction_refuse_before_stop_no_GC(self):
        for kind in ('collision','quota'):
            with self.subTest(kind=kind):
                case=self.fresh()
                try:
                    names=['live22-'+case.op.PACKET_SHA256] if kind=='collision' else ['live22-'+str(number)*64 for number in range(1,5)]
                    for name in names:
                        directory=case.paths['LIVE_CHECKPOINTS']/name;directory.mkdir(mode=0o700)
                        case.write(directory/'owned-evidence',b'foreign preserved checkpoint',0o600)
                    before=hashed_tree(case)
                    with self.assertRaises(ValueError):case.invoke()
                    self.assertEqual(hashed_tree(case),before);self.assertFalse(any(row['argv'][1]=='stop' for row in case.trace))
                finally:case.doCleanups()

    def test_exact_manifest_snapshot_carrier_validation_before_filesystem_and_unchanged_checkpoint(self):
        manifest=self.packet_manifest;original=self.op.PACKET_SHA256
        for invalid in (None,bytearray(manifest),manifest+b'\n',b'{}',b' '*(65536+1)):
            with self.subTest(type=type(invalid).__name__,size=len(invalid) if invalid is not None else 0):
                self.op.PACKET_MANIFEST_SNAPSHOT=invalid
                with self.root_boundary(),patch.object(os,'open',side_effect=AssertionError('Invalid manifest touched filesystem')):
                    with self.assertRaises(ValueError):self.op.bootstrap()
                self.assertEqual(self.trace,[])
        self.op.PACKET_MANIFEST_SNAPSHOT=manifest;self.op.PACKET_SHA256='a'*64
        with self.root_boundary(),patch.object(os,'open',side_effect=AssertionError('Wrong manifest digest touched filesystem')):
            with self.assertRaises(ValueError):self.op.bootstrap()
        self.op.PACKET_SHA256=original;self.invoke()
        checkpoint=next(self.paths['LIVE_CHECKPOINTS'].iterdir())
        self.assertEqual((checkpoint/'manifest.json').read_bytes(),manifest)
