"""INV-DEPLOY-23/24 closed dependency states and kill/retry via public syscalls."""
import base64
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
import deploy22_blind_support as s

class SyntheticProcessDeath(BaseException):pass

class DependencyRecoveryBlind(s.BootstrapFixture):
    def setUp(self):self.prepare()
    def snapshot(self):
        return {str(p.relative_to(self.root)):(s.sha(p.read_bytes()),p.lstat().st_mode&0o777) for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}
    def stage(self,kind,complete=False):
        prefix='nats/' if kind=='nats' else 'nats_py-2.9.0.dist-info/'
        directory=self.site/('.ai-control-live22-'+('nats' if kind=='nats' else 'info')+'.stage')
        directory.mkdir(mode=0o700)
        chosen=[row for row in s.rows() if row['path'].startswith(prefix)]
        if not complete:chosen=chosen[:1]
        with zipfile.ZipFile(s.WHEEL) as archive:
            for row in chosen:self.write(directory/row['path'][len(prefix):],archive.read(row['path']),0o644)
        for path in directory.rglob('*'):
            if path.is_dir():path.chmod(0o755)
        if complete:directory.chmod(0o755)
        return directory

    def test_unowned_stages_both_stages_INFO_before_NATS_and_partial_final_refuse(self):
        # No own marker: even seemingly valid staging is foreign, never adopted/removed.
        for kind in ('nats','info'):
            directory=self.stage(kind);before=self.snapshot()
            with self.assertRaises(ValueError):self.invoke()
            self.assertEqual(self.snapshot(),before);self.assertEqual(self.trace,[])
            for p in sorted(directory.rglob('*'),key=lambda p:len(p.parts),reverse=True):p.unlink() if p.is_file() else p.rmdir()
            directory.rmdir()
        directory=self.stage('nats');self.stage('info');before=self.snapshot()
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.snapshot(),before)

    def test_partial_final_without_own_marker_is_never_accepted_or_cleaned(self):
        self.write(self.site/'nats/__init__.py',b'# foreign incomplete final',0o644);before=self.snapshot()
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.trace,[])

    def test_wheel_blob_corruption_and_outer_hash_rebinding_refuse_before_stop(self):
        original=self.op.WHEEL_BLOB_B64
        for raw,rebound in [(s.WHEEL.read_bytes()+b'foreign',False),(b'not a ZIP wheel',True)]:
            self.op.WHEEL_BLOB_B64=base64.b64encode(raw).decode()
            if rebound:self.op.WHEEL_SHA256=s.sha(raw);self.op.WHEEL_SIZE=len(raw)
            before=self.snapshot()
            with self.assertRaises(ValueError):self.invoke()
            self.assertEqual(self.snapshot(),before);self.assertEqual(self.trace,[])
        self.op.WHEEL_BLOB_B64=original

    def test_kill_after_NATS_promotion_A2_then_resume_full29_before_smoke(self):
        original_rename=os.rename;original_replace=os.replace;killed=[]
        def intercept(call,source,destination,*args,**kwargs):
            result=call(source,destination,*args,**kwargs)
            if not killed and Path(os.fspath(destination)).name=='nats':killed.append(True);raise SyntheticProcessDeath()
            return result
        with patch.object(os,'rename',side_effect=lambda *a,**k:intercept(original_rename,*a,**k)), \
             patch.object(os,'replace',side_effect=lambda *a,**k:intercept(original_replace,*a,**k)):
            with self.assertRaises(SyntheticProcessDeath):self.invoke()
        self.assertEqual(killed,[True]);self.assertTrue(self.paths['DEP_PACKAGE'].is_dir());self.assertFalse(self.paths['DEP_INFO'].exists())
        self.assertTrue(self.paths['BOOTSTRAP_PENDING'].is_file());self.assertFalse(self.receipt.exists())
        self.trace.clear();self.invoke();self.assertEqual(self.installed_rows(),s.rows());self.assertTrue(self.receipt.exists())
        self.assertFalse(self.paths['BOOTSTRAP_PENDING'].exists());self.assertEqual(self.state.read_bytes(),self.initial_state)
        self.assertEqual(sum(row['argv'][0]=='/usr/bin/setpriv' for row in self.trace),1)

    def test_kill_after_INFO_promotion_A4_before_unit_then_resume(self):
        original_rename=os.rename;original_replace=os.replace;killed=[]
        def intercept(call,source,destination,*args,**kwargs):
            result=call(source,destination,*args,**kwargs)
            if not killed and Path(os.fspath(destination)).name=='nats_py-2.9.0.dist-info':killed.append(True);raise SyntheticProcessDeath()
            return result
        with patch.object(os,'rename',side_effect=lambda *a,**k:intercept(original_rename,*a,**k)), \
             patch.object(os,'replace',side_effect=lambda *a,**k:intercept(original_replace,*a,**k)):
            with self.assertRaises(SyntheticProcessDeath):self.invoke()
        self.assertEqual(killed,[True]);self.assertEqual(self.installed_rows(),s.rows())
        self.assertEqual(self.unit.read_bytes(),self.before_unit);self.assertEqual(self.helper.read_bytes(),s.pinned_source())
        self.trace.clear();self.invoke();self.assertTrue(self.receipt.exists());self.assertEqual(self.state.read_bytes(),self.initial_state)
        self.assertEqual(sum(row['argv'][0]=='/usr/bin/setpriv' for row in self.trace),1)

    def test_pre_and_post_smoke_death_each_resume_with_one_new_smoke_no_pass_bit(self):
        for after in (False,True):
            with self.subTest(after_successful_child=after):
                case=s.BootstrapFixture('runTest')
                try:
                    case.prepare();command=case.command
                    def killed(argv,**kwargs):
                        if argv[0]=='/usr/bin/setpriv':
                            if after:command(argv,**kwargs)
                            raise SyntheticProcessDeath()
                        return command(argv,**kwargs)
                    case.op.run_command=killed
                    with self.assertRaises(SyntheticProcessDeath):case.invoke()
                    self.assertTrue(case.paths['BOOTSTRAP_PENDING'].is_file());self.assertFalse(case.receipt.exists())
                    case.op.run_command=command;case.trace.clear();case.invoke()
                    self.assertEqual(sum(row['argv'][0]=='/usr/bin/setpriv' for row in case.trace),1)
                    self.assertLessEqual(sum(row['argv'][0]=='/usr/bin/systemctl' for row in case.trace),15)
                    self.assertTrue(case.receipt.exists());self.assertEqual(case.state.read_bytes(),case.initial_state)
                finally:case.doCleanups()

    def test_unknown_temp_after_crash_is_retained_and_never_blind_deleted(self):
        command=self.command
        def kill(argv,**kwargs):
            if argv[:2]==['/usr/bin/systemctl','stop']:raise SyntheticProcessDeath()
            return command(argv,**kwargs)
        self.op.run_command=kill
        with self.assertRaises(SyntheticProcessDeath):self.invoke()
        directory=self.stage('nats');foreign=directory/'.live22-unknown.part';self.write(foreign,b'owned foreign bytes',0o600)
        before=self.snapshot();self.op.run_command=command;self.trace.clear()
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.snapshot(),before);self.assertEqual(foreign.read_bytes(),b'owned foreign bytes')

    def test_failed_smoke_unknown_dependency_bytes_retain_evidence_no_rmtree(self):
        def inject(argv):
            if argv[0]=='/usr/bin/setpriv':
                self.write(self.site/'nats/foreign.py',b'unknown drift after install',0o644)
                raise ValueError('synthetic failure after unknown drift')
        self.after_command=inject
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual((self.site/'nats/foreign.py').read_bytes(),b'unknown drift after install')
        self.assertTrue(self.paths['BOOTSTRAP_PENDING'].exists());self.assertFalse(self.receipt.exists())
