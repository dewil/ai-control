"""Independent exact23 deployment extension RED; signed synthetic local trees.

No helper implementation inspection, root operation or live service mutation.
Public API: fixed maps + Deploy.run/read_state from accepted deployment fixtures.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
import deploy22_blind_support as s

LEAF='bin/_control_web_attachments.py'
FULL23={**s.FULL22,LEAF:0o644}


class AttachmentDeploy23Red(s.ControllerFixture):
    def setUp(self):
        super().setUp()
        self.install_state(self.after22,4,7)
        self.after23={**self.after22,LEAF:b'# signed synthetic attachments module\n'}
        self.dependency_after()
    def install_state(self,files,schema,number=7):
        for path,data in files.items():self.write(self.target/path,data,FULL23[path])
        value=dict(schema=schema,release_id=number,manifest_sha256='a'*64,files=self.hashes(files))
        self.write(self.state,json.dumps(value,indent=2).encode()+b'\n',0o600)
        self.initial_state=self.state.read_bytes();return value
    def tree(self):
        return {p:(self.target/p).read_bytes() for p in FULL23
                if (self.target/p).is_file() and not (self.target/p).is_symlink()}
    def signed23(self,files=None,number=8,base=None,schema=5):
        return self.signed(files=self.after23 if files is None else files,number=number,
                           base=self.after22 if base is None else base,schema=schema)
    def assert_untouched_refusal(self):
        raw=self.state.read_bytes();tree=self.tree();self.calls.clear()
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.tree(),tree)
        self.assertFalse(self.stops());self.assertFalse((self.checkpoints/'pending.json').exists())

    def test_exact23_modes_and_historical_state_read_contract(self):
        # INV-DEPLOY-01 INV-DEPLOY-03: extension is exactly one regular0644 module.
        self.assertEqual(getattr(self.api,'ATTACHMENT_MODES',None),FULL23)
        self.assertEqual(self.api.MODES,FULL23);self.assertEqual(self.api.LIVE_MODES,s.FULL22)
        self.assertEqual(set(self.api.SCHEMAS),{1,2,3,4,5})
        for schema,files in ((1,self.base),(2,self.current),(3,self.before16),(4,self.after22),(5,self.after23)):
            with self.subTest(schema=schema):
                self.assertEqual(set(self.api.SCHEMAS[schema]),set(files))
                self.install_state(files,schema)
                self.assertIsNotNone(self.deploy().read_state())

    def test_trusted4_to5_then5_to5_and_sameid_without_restart(self):
        # INV-DEPLOY-03 INV-DEPLOY-05: historical4 is a valid base, not fresh authority.
        self.signed23();self.accepted(dict(result='installed',release_id=8))
        self.assertEqual(self.tree(),self.after23)
        state=json.loads(self.state.read_bytes());self.assertEqual(state['schema'],5)
        self.assertEqual(state['files'],self.hashes(self.after23))
        raw=self.state.read_bytes();self.calls.clear()
        self.accepted(dict(result='already_installed',release_id=8))
        self.assertEqual(self.state.read_bytes(),raw);self.assertFalse(self.stops())
        self.assertFalse(any(row[1]=='start' for row in self.calls))
        after={p:data+b'# next full23\n' for p,data in self.after23.items()}
        self.signed23(files=after,base=self.after23,number=9)
        self.accepted(dict(result='installed',release_id=9));self.assertEqual(self.tree(),after)

    def test_arbitrary_leaf_subset_fresh4_and_direct3_refuse_before_mutation(self):
        # INV-DEPLOY-01 INV-DEPLOY-03: valid signatures cannot expand fixed scope.
        cases=[(self.after23|{'bin/foreign.py':b'# signed arbitrary code\n'},5,self.after22),
               (self.after22,5,self.after22),(self.after22,4,self.after22),
               (self.after23,5,self.before16)]
        for files,schema,base in cases:
            with self.subTest(schema=schema,leaves=len(files),base=len(base)):
                self.signed23(files=files,schema=schema,base=base);self.assert_untouched_refusal()

    def test_preexisting_new_leaf_refuses_instead_of_adopting_owner_bytes(self):
        # INV-DEPLOY-03 INV-DEPLOY-04: even exact candidate bytes need absence proof.
        self.signed23()
        for kind in ('matching','symlink'):
            with self.subTest(kind=kind):
                path=self.target/LEAF
                if kind=='matching':self.write(path,self.after23[LEAF],0o644)
                else:path.symlink_to(self.root/'absent')
                self.assert_untouched_refusal();self.assertTrue(os.path.lexists(path));path.unlink()

    def test_live_dependency_and_frontend_sandbox_guards_still_gate_schema5(self):
        # INV-DEPLOY-25: allowlist extension conveys no service/dependency authority.
        self.signed23();dependency=self.site/'nats/__init__.py';before=dependency.read_bytes()
        dependency.write_bytes(before+b'# unexpected dependency drift\n')
        self.assert_untouched_refusal();dependency.write_bytes(before)
        original=self.runner
        def widened(argv):
            output=original(argv)
            if argv[1:3]==['show',s.SERVICES[0]]:
                output='\n'.join('ReadWritePaths=/run/ai-control-web /var/lib/ai-control-web'
                    if row.startswith('ReadWritePaths=') else row for row in output.splitlines())
            return output
        self.runner=widened;self.assert_untouched_refusal()

    def test_failed4_to5_restores_raw4_and_absence_of_attachment_module(self):
        # INV-DEPLOY-04: bounded ordinary rollback restores exact accepted22.
        self.signed23();raw=self.state.read_bytes();before=self.tree();self.fail_starts=1
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.tree(),before);self.assertEqual(self.state.read_bytes(),raw)
        self.assertFalse(os.path.lexists(self.target/LEAF))
        self.assertFalse((self.checkpoints/'pending.json').exists())
        self.assertTrue(self.stops(),'Must exercise install failure, not early schema refusal')

    def test_interrupted5_journal_restores_raw4_before_bad_next_candidate(self):
        # INV-DEPLOY-04: recovery precedes candidate rejection; provisional5 is rollbackable.
        raw=self.state.read_bytes();before=json.loads(raw)
        after=dict(schema=5,release_id=8,manifest_sha256='b'*64,files=self.hashes(self.after23))
        checkpoint=self.checkpoints/'release-attachments23-blind';checkpoint.mkdir(mode=0o700)
        for path,data in self.after22.items():self.write(checkpoint/Path(path).name,data,0o600)
        self.write(checkpoint/'accepted.json',raw,0o600)
        self.write(self.checkpoints/'pending.json',s.canonical(dict(schema=5,before=before,after=after,
            checkpoint=checkpoint.name)),0o600)
        for path,data in self.after23.items():self.write(self.target/path,data,FULL23[path])
        self.write(self.state,s.canonical(after),0o600)
        self.signed23();(self.stage/'release.sig').write_bytes(bytes(64))
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.tree(),self.after22)
        self.assertFalse(os.path.lexists(self.target/LEAF))
        self.assertFalse((self.checkpoints/'pending.json').exists())
        self.assertEqual((checkpoint/'accepted.json').read_bytes(),raw)

    def test_failed5_to5_restores_raw5_including_old_attachment_module(self):
        # INV-DEPLOY-04: schema5 rollback restores the previous module, not absence.
        self.install_state(self.after23,5,8);self.dependency_after()
        next_files={p:data+b'# second revision\n' for p,data in self.after23.items()}
        self.signed23(files=next_files,number=9,base=self.after23)
        raw=self.state.read_bytes();self.fail_starts=1
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.tree(),self.after23)
        self.assertEqual((self.target/LEAF).read_bytes(),self.after23[LEAF])
        self.assertFalse((self.checkpoints/'pending.json').exists())
        self.assertTrue(self.stops(),'Must exercise failed5 install and actual rollback')
