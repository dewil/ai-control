"""INV-DEPLOY-22/23/24/25 frozen public bootstrap lifecycle, no privileged IO."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import deploy22_blind_support as s

class Live22BootstrapBlind(s.BootstrapFixture):
    def setUp(self):self.prepare()

    def snapshot(self):
        return {str(path.relative_to(self.root)):(s.sha(path.read_bytes()),path.lstat().st_mode&0o777) for path in self.root.rglob('*') if path.is_file() and not path.is_symlink()}

    def test_forward_dependency_modes_smoke_trace15_and_receipt(self):
        raw=self.state.read_bytes();inode=self.paths['LOCK'].lstat().st_ino
        self.assertIsNone(self.invoke());self.assertEqual(self.state.read_bytes(),raw)
        self.assertEqual(self.paths['LOCK'].lstat().st_ino,inode);self.assertEqual(self.installed_rows(),s.rows())
        self.assertEqual(self.helper.read_bytes(),self.new_helper);self.assertEqual(self.unit.read_bytes(),self.after_unit)
        self.assertFalse(self.paths['BOOTSTRAP_PENDING'].exists())
        receipt=json.loads(self.receipt.read_bytes());self.assertEqual(set(receipt),{'schema','operation','packet_sha256',
            'accepted_before_sha256','helper_sha256','unit_sha256','wheel_sha256','dependency_inventory_sha256'})
        self.assertEqual(receipt['dependency_inventory_sha256'],s.INVENTORY_SHA)
        calls=[row['argv'] for row in self.trace if row['argv'][0]=='/usr/bin/systemctl']
        self.assertEqual(len(calls),15)
        self.assertEqual([row[1:] for row in calls if row[1] in ('stop','start')],
            [['stop',s.SERVICES[0]],['stop',s.SERVICES[1]],['start',s.SERVICES[1]],['start',s.SERVICES[0]]])
        self.assertEqual(sum(row['argv'][0]=='/usr/bin/setpriv' for row in self.trace),1)
        self.assertTrue(all(row['timeout']==40 for row in self.trace if row['argv'][0]=='/usr/bin/systemctl'))
        checkpoints=list(self.paths['LIVE_CHECKPOINTS'].iterdir());self.assertEqual(len(checkpoints),1)
        self.assertEqual({path.name for path in checkpoints[0].iterdir()},
            {'helper.before','broker-unit.before','accepted.before','proof.json','manifest.json'})
        self.assertLessEqual(sum(path.stat().st_size for path in checkpoints[0].iterdir()),1310720)

    def test_completed_repeat_only4_readonly_commands_no_smoke_or_mutation(self):
        self.invoke();before=self.snapshot();inode=self.paths['LOCK'].stat().st_ino;self.trace.clear()
        self.invoke();self.assertEqual(self.snapshot(),before);self.assertEqual(self.paths['LOCK'].stat().st_ino,inode)
        self.assertEqual(len(self.trace),4);self.assertTrue(all(row['argv'][1] in ('is-active','show') for row in self.trace))

    def test_invalid_carrier_refuses_before_filesystem_lock_runner(self):
        for invalid in (None,True,b'a'*64,'A'*64,'a'*63):
            with self.subTest(kind=type(invalid).__name__):
                self.op.PACKET_SHA256=invalid
                with self.root_boundary(),patch.object(os,'open',side_effect=AssertionError('Carrier opened filesystem')):
                    with self.assertRaises(ValueError):self.op.bootstrap()
                self.assertEqual(self.trace,[])

    def test_none_operation_pin_refuses_without_marker_or_mutation(self):
        before=self.snapshot();self.op.NEW_HELPER_SHA256=None
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.trace,[])

    def test_existing_lock_missing_or_inode_drift_refuses_without_replacement(self):
        original=self.paths['LOCK'].read_bytes();self.paths['LOCK'].unlink()
        with self.assertRaises(ValueError):self.invoke()
        self.assertFalse(self.paths['LOCK'].exists());self.assertEqual(self.trace,[])
        self.write(self.paths['LOCK'],original,0o600)
        self.op.EXPECTED_RUNTIME_STAT_PINS['LOCK']['ino']=self.paths['LOCK'].lstat().st_ino+1
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.trace,[])

    def test_foreign_package_config_bootstrap_markers_preserve_all_bytes(self):
        for key in ('PACKAGE_PENDING','CONFIG_PENDING','BOOTSTRAP_PENDING'):
            with self.subTest(marker=key):
                self.write(self.paths[key],b'owned foreign marker',0o600);before=self.snapshot()
                with self.assertRaises(ValueError):self.invoke()
                self.assertEqual(self.snapshot(),before);self.assertEqual(self.trace,[]);self.paths[key].unlink()

    def test_stat_pin_eight_key_types_and_exact_inode_refuse(self):
        baseline=deepcopy(self.stat_pins)
        for changed in (dict(baseline,EXTRA={}),{key:value for key,value in baseline.items() if key!='LOCK'},
            baseline|{'BROKER_UNIT_MODE':True},baseline|{'LOCK':baseline['LOCK']|{'ino':baseline['LOCK']['ino']+1}}):
            with self.subTest(keys=sorted(changed)):
                self.op.EXPECTED_RUNTIME_STAT_PINS=changed;before=self.snapshot()
                with self.assertRaises(ValueError):self.invoke()
                self.assertEqual(self.snapshot(),before);self.assertEqual(self.trace,[])

    def test_marker_checkpoint_durable_before_stop_and_no_owner_config_access(self):
        observations=[]
        def observe(argv):
            if argv[:2]==['/usr/bin/systemctl','stop']:
                self.assertTrue(self.paths['BOOTSTRAP_PENDING'].is_file())
                marker=json.loads(self.paths['BOOTSTRAP_PENDING'].read_bytes());observations.append(marker)
                self.assertEqual(marker['schema'],2);self.assertEqual(marker['operation'],'live22-bootstrap')
                self.assertEqual(marker['packet_sha256'],self.op.PACKET_SHA256)
                checkpoint=self.paths['LIVE_CHECKPOINTS']/marker['checkpoint']
                self.assertEqual({path.name for path in checkpoint.iterdir()},
                    {'helper.before','broker-unit.before','accepted.before','proof.json','manifest.json'})
        self.after_command=observe;self.invoke();self.assertEqual(len(observations),2)
        # root_boundary trips on all production owner JSON/parent open attempts.
        self.assertEqual(self.unit.read_bytes(),self.after_unit)

    def test_preserved_exact_never_installs_or_unlinks_dependency(self):
        self.dependency_after();self.receipt.unlink()
        before={row['path']:(self.site/row['path']).lstat().st_ino for row in s.rows()}
        self.invoke();self.assertEqual(self.installed_rows(),s.rows())
        self.assertEqual({row['path']:(self.site/row['path']).lstat().st_ino for row in s.rows()},before)
        checkpoint=next(self.paths['LIVE_CHECKPOINTS'].iterdir())
        self.assertEqual(json.loads((checkpoint/'proof.json').read_bytes())['dependency_before'],
            {'mode':'preserved_exact','wheel_sha256':s.WHEEL_SHA})

    def test_shadow_py_pth_and_unknown_partial_final_refuse_no_cleanup(self):
        for relative in ('nats.py','nats-extra.pth','nats_py-1.0.dist-info/METADATA','nats/foreign.py'):
            with self.subTest(relative=relative):
                self.write(self.site/relative,b'# synthetic shadow',0o644);before=self.snapshot()
                with self.assertRaises(ValueError):self.invoke()
                self.assertEqual(self.snapshot(),before);self.assertEqual(self.trace,[])
                path=self.site/relative;path.unlink()
                while path.parent!=self.site and not list(path.parent.iterdir()):path.parent.rmdir();path=path.parent

    def test_smoke_failure_rolls_back_helper_unit_dependency_without_receipt(self):
        self.smoke_result=subprocess.CompletedProcess([],1,b'',b'')
        raw=self.state.read_bytes()
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.helper.read_bytes(),s.pinned_source())
        self.assertEqual(self.unit.read_bytes(),self.before_unit)
        self.assertFalse(self.paths['DEP_PACKAGE'].exists());self.assertFalse(self.paths['DEP_INFO'].exists())
        self.assertFalse(self.receipt.exists());self.assertEqual(len([row for row in self.trace if row['argv'][0]=='/usr/bin/systemctl']),26)
        self.assertLessEqual(sum(row['timeout'] for row in self.trace),1050)
        self.assertEqual(sum(row['argv'][0]=='/usr/bin/setpriv' for row in self.trace),1)

    def test_first_stop_failure_uses_only_bounded_bounce_and_never_dependency_mutation(self):
        command=self.command;failures=[];raw=self.state.read_bytes()
        def failed(argv,**kwargs):
            if argv[:2]==['/usr/bin/systemctl','stop'] and not failures:
                failures.append(True);self.trace.append(dict(argv=list(argv),**kwargs))
                return subprocess.CompletedProcess(argv,1,b'',b'')
            return command(argv,**kwargs)
        self.op.run_command=failed
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(failures,[True]);self.assertEqual(self.state.read_bytes(),raw)
        self.assertEqual(self.helper.read_bytes(),s.pinned_source());self.assertEqual(self.unit.read_bytes(),self.before_unit)
        self.assertFalse(self.paths['DEP_PACKAGE'].exists());self.assertFalse(self.paths['DEP_INFO'].exists());self.assertFalse(self.receipt.exists())
        self.assertLessEqual(sum(row['argv'][0]=='/usr/bin/systemctl' for row in self.trace),12)
        self.assertFalse(any(row['argv'][0]=='/usr/bin/setpriv' for row in self.trace))
        self.assertEqual([row['argv'][1:] for row in self.trace if row['argv'][1]=='start'],
            [['start',s.SERVICES[1]],['start',s.SERVICES[0]]])

    def test_smoke_strict_json_oversize_wrong_source_schema_bool_refuses(self):
        # Every malformed successful-child result gets a fresh complete before16 fixture.
        for output in (b'{}{}',b'{"schema":true}',b' '*(4096+1),b'{"source_file":"/synthetic/shadow/nats.py"}'):
            with self.subTest(shape=output[:20]):
                case=s.BootstrapFixture('runTest')
                try:
                    case.prepare();case.smoke_result=subprocess.CompletedProcess([],0,output,b'')
                    with self.assertRaises(ValueError):case.invoke()
                    self.assertFalse(case.receipt.exists());self.assertEqual(case.state.read_bytes(),case.initial_state)
                    self.assertEqual(sum(row['argv'][0]=='/usr/bin/setpriv' for row in case.trace),1)
                finally:case.doCleanups()

    def test_owner_import_code_pin_and_empty_env_pass_through_actual_runner(self):
        self.assertEqual(s.sha(self.op.OWNER_IMPORT_CODE.encode()),
            '70b31a6b98b049a0a3a6eba2af77f0732a2fcd856d232c5f86928b9b642a2189')
        result=subprocess.CompletedProcess([],0,b'',b'')
        with patch.dict(os.environ,{'CONTROL_SYNTHETIC_SENTINEL':'untrusted-ambient'}), \
             patch.object(subprocess,'run',return_value=result) as child:
            self.actual_run_command(['/usr/bin/systemctl','is-active',s.SERVICES[0]],env={},cwd='/',timeout=40)
        self.assertEqual(child.call_args.kwargs['env'],{})
        self.assertEqual(child.call_args.kwargs['cwd'],'/');self.assertEqual(child.call_args.kwargs['timeout'],40)

    def test_completed_accepted4_consistency_no_downgrade_then_leaf_drift_refuses(self):
        self.invoke()
        self.install_state(self.after22,4,8);before=self.snapshot();self.trace.clear()
        self.invoke();self.assertEqual(self.snapshot(),before);self.assertEqual(len(self.trace),4)
        self.write(self.target/'bin/_control_web_live.py',b'owned unknown22 leaf',0o644)
        before=self.snapshot();self.trace.clear()
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.snapshot(),before);self.assertFalse(any(row['argv'][1] in ('stop','start') for row in self.trace))
        self.assertEqual(self.helper.read_bytes(),self.new_helper)

    def test_accepted4_plus_bootstrap_marker_never_restores_old_helper(self):
        self.invoke();self.install_state(self.after22,4,8)
        self.write(self.paths['BOOTSTRAP_PENDING'],s.canonical(dict(schema=2,operation='live22-bootstrap',
            packet_sha256=self.op.PACKET_SHA256,checkpoint='live22-'+self.op.PACKET_SHA256,
            before_accepted_sha256=s.sha(self.initial_state),stage='rollback')),0o600)
        before=self.snapshot();self.trace.clear()
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.helper.read_bytes(),self.new_helper)

    def test_member_modes_and_fsync_before_final_promotions(self):
        real_rename=os.rename;real_replace=os.replace;real_fsync=os.fsync;promotions=[];synced=set()
        def fsync(fd):
            synced.add(os.readlink('/proc/self/fd/'+str(fd)));return real_fsync(fd)
        def ready(directory):
            self.assertEqual(directory.lstat().st_mode&0o777,0o755)
            for path in (directory,*directory.rglob('*')):
                self.assertIn(str(path),synced,'Every member/directory must be fsynced before promotion')
                if path.is_file():self.assertEqual(path.lstat().st_mode&0o777,0o644)
            self.assertIn(str(directory.parent),synced)
        def rename(source,destination,*args,**kwargs):
            if os.fspath(destination) in (str(self.paths['DEP_PACKAGE']),str(self.paths['DEP_INFO'])):
                directory=Path(source);ready(directory)
                promotions.append(os.fspath(destination))
            return real_rename(source,destination,*args,**kwargs)
        def replace(source,destination,*args,**kwargs):
            if os.fspath(destination) in (str(self.paths['DEP_PACKAGE']),str(self.paths['DEP_INFO'])):
                directory=Path(source);ready(directory)
                promotions.append(os.fspath(destination))
            return real_replace(source,destination,*args,**kwargs)
        with patch.object(os,'fsync',side_effect=fsync),patch.object(os,'rename',side_effect=rename),patch.object(os,'replace',side_effect=replace):self.invoke()
        self.assertEqual(promotions,[str(self.paths['DEP_PACKAGE']),str(self.paths['DEP_INFO'])])
