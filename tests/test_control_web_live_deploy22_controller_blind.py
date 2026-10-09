"""INV-DEPLOY-20/21 actual controller and immutable16 guard counterexamples."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import deploy22_blind_support as s

class Deploy22ControllerBlind(s.ControllerFixture):
    def required22(self):
        self.assertEqual(self.api.MODES,s.FULL22,'Actual controller still admits16, not exact signed22')

    def test_exact22_modes_and_historical_schemas(self):
        self.required22();self.assertEqual(self.api.APP_MODES,s.FULL16);self.assertEqual(self.api.LIVE_MODES,s.FULL22)
        self.assertEqual(set(self.api.SCHEMAS),{1,2,3,4});self.assertEqual(self.api.SCHEMAS[3],s.FULL16)
        self.assertEqual(self.api.SCHEMAS[4],s.FULL22)

    def test_actual_signed4_full22_staged_from16(self):
        self.signed();self.dependency_after()
        try:result=self.deploy().staged()
        except self.api.Rejected as error:self.fail('Actual controller refused valid signed4 exact22: '+str(error))
        self.assertIsNotNone(result)

    def test_actual_schema4_state_accepts_exact22_rootrecord(self):
        self.install_state(self.after22,4)
        try:value=self.deploy().read_state()
        except self.api.Rejected as error:self.fail('Actual controller refuses exact schema4 rootrecord: '+str(error))
        self.assertIsNotNone(value)

    def test_signed22_install_preserves_full_scope_and_sameID_no_restart(self):
        self.required22();self.dependency_after();self.signed()
        self.accepted(dict(result='installed',release_id=8))
        self.assertEqual(self.tree(),self.after22);raw=self.state.read_bytes();state=json.loads(raw)
        self.assertEqual(state['schema'],4);self.assertEqual(state['files'],self.hashes(self.after22))
        self.calls.clear();self.accepted(dict(result='already_installed',release_id=8))
        self.assertEqual(self.state.read_bytes(),raw);self.assertFalse(self.stops())
        self.assertFalse(any(call[1]=='start' for call in self.calls))

    def test_subsets_extra_schema_boolean_and_direct14_rejected_before_mutation(self):
        self.required22();self.dependency_after()
        for label,files,schema,base in (('subset',dict(self.before16),4,self.before16),
            ('extra',self.after22|{'bin/foreign.py':b'owned invalid extra'},4,self.before16),
            ('boolean',self.after22,True,self.before16),('oldschema',self.after22,3,self.before16),
            ('direct14',self.after22,4,self.current)):
            with self.subTest(case=label):
                self.signed(files=files,schema=schema,base=base);before=self.tree();raw=self.state.read_bytes();self.calls.clear()
                with self.assertRaises(self.api.Rejected):self.deploy().run()
                self.assertEqual(self.tree(),before);self.assertEqual(self.state.read_bytes(),raw);self.assertFalse(self.stops())

    def test_all64_interrupted3to4_patterns_restore_raw16_and_six_absence(self):
        self.required22()
        for mask in range(64):
            with self.subTest(mask=mask):
                checkpoint=self.checkpoints/'release-live22-blind'
                if checkpoint.exists():shutil.rmtree(checkpoint)
                raw,before,after,_,checkpoint=self.make_journal(mask=mask)
                self.calls.clear();self.signed(files=after,base=before)
                (self.stage/'release.sig').write_bytes(bytes(64))
                with self.assertRaises(self.api.Rejected):self.deploy().run()
                self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.tree(),before)
                for path in s.NEW:self.assertFalse(os.path.lexists(self.target/path),path)
                self.assertFalse((self.checkpoints/'pending.json').exists())
                self.assertEqual(len(list(checkpoint.iterdir())),17,'Package16 checkpoint must not inherit bootstrap5/16 caps')

    def test_interrupted4to4_restores23file_checkpoint_and_before22(self):
        self.required22();raw,before,after,_,checkpoint=self.make_journal(before_schema=4)
        self.write(self.target/'bin/_control_web.css',after['bin/_control_web.css'],0o644)
        self.signed(files=after,base=before);(self.stage/'release.sig').write_bytes(bytes(64))
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.tree(),before);self.assertEqual(self.state.read_bytes(),raw)
        self.assertEqual(len(list(checkpoint.iterdir())),23)
        self.assertFalse((self.checkpoints/'pending.json').exists())

    def test_fresh_matching_or_dangling_new_leaf_is_present_and_refused_prejournal(self):
        self.required22();self.dependency_after();self.signed()
        for path in s.NEW:
            for kind in ('matching','dangling','directory'):
                with self.subTest(path=path,kind=kind):
                    target=self.target/path
                    if kind=='matching':self.write(target,self.after22[path],s.FULL22[path])
                    elif kind=='dangling':target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(self.root/'does-not-exist')
                    else:target.mkdir()
                    before=self.state.read_bytes();self.calls.clear()
                    with self.assertRaises(self.api.Rejected):self.deploy().run()
                    self.assertTrue(os.path.lexists(target));self.assertEqual(self.state.read_bytes(),before)
                    self.assertFalse(self.stops());self.assertFalse((self.checkpoints/'pending.json').exists())
                    if kind=='directory':target.rmdir()
                    else:target.unlink()

    def test_root_requirements_leaf_uses_target_parent_not_bin_collision(self):
        self.required22()
        decoy=self.target/'bin/requirements-devbus.lock';self.write(decoy,b'owned decoy must survive',0o644)
        self.signed();self.dependency_after();self.accepted(dict(result='installed',release_id=8))
        self.assertEqual((self.target/'requirements-devbus.lock').read_bytes(),self.after22['requirements-devbus.lock'])
        self.assertEqual(decoy.read_bytes(),b'owned decoy must survive')

    def test_unknown_interrupted_bytes_retained_without_blind_rollback(self):
        self.required22();raw,_,after,_,_=self.make_journal(mask=1)
        unknown=self.target/s.NEW[0];self.write(unknown,b'unknown interrupted bytes',0o644)
        journal=(self.checkpoints/'pending.json').read_bytes();self.signed(files=after)
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(unknown.read_bytes(),b'unknown interrupted bytes');self.assertEqual(self.state.read_bytes(),raw)
        self.assertEqual((self.checkpoints/'pending.json').read_bytes(),journal);self.assertFalse(self.stops())

    def test_forward_gate_dependency_mutations_refuse_even_matching_receipt(self):
        self.required22();self.dependency_after();self.signed();original=(self.site/'nats/__init__.py').read_bytes()
        for kind in ('byte','mode','missing','extra'):
            with self.subTest(kind=kind):
                path=self.site/'nats/__init__.py';self.write(path,original,0o644)
                if kind=='byte':path.write_bytes(original+b'# mutation')
                elif kind=='mode':path.chmod(0o600)
                elif kind=='missing':path.unlink()
                else:self.write(self.site/'nats/foreign.py',b'# extra',0o644)
                receipt=self.receipt.read_bytes();raw=self.state.read_bytes();self.calls.clear()
                with self.assertRaises(self.api.Rejected):self.deploy().run()
                self.assertEqual(self.receipt.read_bytes(),receipt);self.assertEqual(self.state.read_bytes(),raw);self.assertFalse(self.stops())
                (self.site/'nats/foreign.py').unlink(missing_ok=True)

    def test_missing_receipt_refuses_fresh_without_install_or_repair(self):
        self.required22();self.signed();before=self.tree();raw=self.state.read_bytes()
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.tree(),before);self.assertEqual(self.state.read_bytes(),raw);self.assertFalse(self.stops())

    def test_actual_unit_hash_fault_refuses_fresh(self):
        self.required22();self.dependency_after();self.signed();self.unit.write_bytes(self.unit.read_bytes()+b'# unknown unit drift\n')
        raw=self.state.read_bytes();before=self.tree();self.calls.clear()
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.tree(),before);self.assertFalse(self.stops())
        # No receipt repair and no active-health shortcut on later same-ID.
        self.assertTrue(self.receipt.exists())

    def test_actual_unit_fault_blocks_sameID_repeat_without_restart(self):
        self.required22();self.dependency_after();self.signed();self.accepted(dict(result='installed',release_id=8))
        self.unit.write_bytes(self.unit.read_bytes()+b'# changed after first22\n')
        raw=self.state.read_bytes();self.calls.clear()
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),raw);self.assertFalse(self.stops())

    def test_actual_unit_fault_blocks_journal4_forward_clear_retains_journal(self):
        self.required22();self.dependency_after()
        raw,before,after,_,_=self.make_journal(accepted_after=True)
        self.unit.write_bytes(self.unit.read_bytes()+b'# changed before clear\n')
        journal=(self.checkpoints/'pending.json').read_bytes();accepted=self.state.read_bytes()
        self.signed(files=after,base=before);self.calls.clear()
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),accepted);self.assertEqual(self.tree(),after)
        self.assertEqual((self.checkpoints/'pending.json').read_bytes(),journal);self.assertFalse(self.stops())

    def test_journal4_rollback_ignores_dependency_unit_gate_fault(self):
        self.required22();raw,before,after,_,_=self.make_journal(mask=63)
        self.unit.write_bytes(b'unknown unit fault outside package rollback');self.signed(files=after,base=before)
        (self.stage/'release.sig').write_bytes(bytes(64))
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.tree(),before);self.assertEqual(self.state.read_bytes(),raw)
        self.assertFalse((self.checkpoints/'pending.json').exists())
        self.assertEqual(self.unit.read_bytes(),b'unknown unit fault outside package rollback')

    def test_legacy_journal3_recovery_ignores_missing_dependency_receipt_and_unit_fault(self):
        # Legacy2->3 rollback happens before the invalid next signed22 candidate.
        self.install_state(self.current,2);raw=self.state.read_bytes();before=json.loads(raw)
        after=dict(schema=3,release_id=8,manifest_sha256='b'*64,files=self.hashes(self.before16))
        checkpoint=self.checkpoints/'release-legacy-before-live22';checkpoint.mkdir(mode=0o700)
        for path,data in self.current.items():self.write(checkpoint/Path(path).name,data,0o600)
        self.write(checkpoint/'accepted.json',raw,0o600)
        for path in (s.prior.AUTH,s.prior.DOWNLOAD):(self.target/path).unlink()
        self.write(self.target/s.prior.AUTH,self.before16[s.prior.AUTH],0o644)
        self.write(self.checkpoints/'pending.json',s.canonical(dict(schema=3,before=before,after=after,checkpoint=checkpoint.name)),0o600)
        self.unit.write_bytes(b'unknown unit outside legacy package rollback')
        self.signed();(self.stage/'release.sig').write_bytes(bytes(64))
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.tree(),self.current)
        self.assertFalse((self.checkpoints/'pending.json').exists());self.assertFalse(self.receipt.exists())
        self.assertEqual(self.unit.read_bytes(),b'unknown unit outside legacy package rollback')

class ImmutableHelperBoundaryBlind(s.ControllerFixture):
    def old(self):return s.module_bytes(s.pinned_source(),'deploy22_actual_old_immutable')

    def test_pinned_old16_refuses_real_signed22_not_a_shadow_validator(self):
        old=self.old();self.signed();controller=old.Deploy(self.target,self.stage,self.checkpoints,self.runner,
            state_path=self.state,key_path=self.key,owner_uid=os.getuid())
        with self.assertRaises(old.Rejected):controller.staged()
        self.assertFalse(self.stops());self.assertEqual(self.tree(),self.before16)

    def test_schema2_nonJSON_and_dangling_bootstrap_marker_block_before_all_later_seams(self):
        old=self.old();marker=self.state.parent/'bootstrap-pending.json'
        for content in (s.canonical({'schema':2,'operation':'live22-bootstrap'}),b'not JSON',b''):
            with self.subTest(content_kind='json' if content.startswith(b'{') else 'opaque'):
                self.write(marker,content,0o600)
                controller=old.Deploy(self.target,self.stage,self.checkpoints,self.runner,
                    state_path=self.state,key_path=self.key,owner_uid=os.getuid())
                with patch.object(controller,'read_state',side_effect=AssertionError('Later read_state must not run')), \
                     patch.object(controller,'recover',side_effect=AssertionError('Later recover must not run')), \
                     patch.object(controller,'staged',side_effect=AssertionError('Later staged must not run')):
                    with self.assertRaisesRegex(old.Rejected,'Separate operation pending'):controller._run_locked()
                self.assertEqual(self.calls,[])
                marker.unlink()
        marker.symlink_to(self.root/'absent-marker-target')
        controller=old.Deploy(self.target,self.stage,self.checkpoints,self.runner,state_path=self.state,key_path=self.key,owner_uid=os.getuid())
        with patch.object(controller,'read_state',side_effect=AssertionError('Later read_state must not run')):
            with self.assertRaisesRegex(old.Rejected,'Separate operation pending'):controller._run_locked()
        self.assertEqual(self.calls,[])

    def test_no_marker_control_reaches_first_later_tripwire(self):
        old=self.old();controller=old.Deploy(self.target,self.stage,self.checkpoints,self.runner,
            state_path=self.state,key_path=self.key,owner_uid=os.getuid())
        with patch.object(controller,'read_state',side_effect=AssertionError('FIRST_LATER_TRIPWIRE')):
            with self.assertRaisesRegex(AssertionError,'FIRST_LATER_TRIPWIRE'):controller._run_locked()
