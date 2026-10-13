"""Independent DEPLOY25 RED: signed synthetic trees, protected synthetic receipts.

INV-DEPLOY-01 INV-DEPLOY-03 INV-DEPLOY-04 INV-DEPLOY-25
No production helper execution, real services, root provisioning or NATS.
"""
import json
import os
from pathlib import Path
import unittest
import deploy22_blind_support as s

NODE_LEAVES=('bin/_control_node_tasks.py','bin/_control_node_runtime.py')
FULL23={**s.FULL22,'bin/_control_web_attachments.py':0o644}
FULL25={**FULL23,**dict.fromkeys(NODE_LEAVES,0o644)}
NODE_LINE=b'Environment=CONTROL_NODE_TASKS_CONFIG=/home/dwl/.config/ai-control/node-tasks.json\n'


class NodeDeploy25RED(s.ControllerFixture):
    def setUp(self):
        super().setUp()
        self.after23={**self.after22,'bin/_control_web_attachments.py':b'# signed synthetic attachment\n'}
        self.after25={**self.after23,**{p:('# signed synthetic '+p+'\n').encode() for p in NODE_LEAVES}}
        self.install_state(self.after23,5,7);self.dependency_after()
        self.oldunit=self.unit.read_bytes();self.nodeunit=self.oldunit.replace(b'[Service]\n',b'[Service]\n'+NODE_LINE,1)
        self.attachment=self.state.parent/'attachments-bootstrap-complete.json'
        self.nodes=self.state.parent/'nodes-bootstrap-complete.json'
        self.api.ATTACHMENT_RECEIPT=self.attachment;self.api.NODE_RECEIPT=self.nodes
        live=json.loads(self.receipt.read_bytes());live['helper_sha256']=s.sha(s.accepted22_source())
        self.oldlive=s.canonical(live);self.write(self.receipt,self.oldlive,0o600)
        self.attachment_value=dict(schema=1,operation='attachments23-bootstrap',prior_helper_sha256=live['helper_sha256'],helper_sha256=s.sha(b'synthetic-prior-attachments-helper'),prior_receipt_sha256=s.sha(self.oldlive),accepted_before_sha256='a'*64,packet_sha256='b'*64)
        self.oldattachment=s.canonical(self.attachment_value);self.write(self.attachment,self.oldattachment,0o600)
        self.node_value=dict(schema=1,operation='nodes25-bootstrap',prior_receipt_sha256=s.sha(self.oldattachment),prior_helper_sha256=self.attachment_value['helper_sha256'],helper_sha256=s.sha(self.helper.read_bytes()),prior_unit_sha256=s.sha(self.oldunit),unit_sha256=s.sha(self.nodeunit),accepted_before_sha256=s.sha(self.state.read_bytes()),packet_sha256='c'*64)
        self.write(self.nodes,s.canonical(self.node_value),0o600);self.write(self.unit,self.nodeunit,0o644)

    def install_state(self,files,schema,number=7):
        for p,data in files.items():self.write(self.target/p,data,FULL25[p])
        value=dict(schema=schema,release_id=number,manifest_sha256='a'*64,files=self.hashes(files))
        self.write(self.state,json.dumps(value,indent=2).encode()+b'\n',0o600);self.initial_state=self.state.read_bytes();return value

    def tree(self):return {p:(self.target/p).read_bytes() for p in FULL25 if (self.target/p).is_file() and not (self.target/p).is_symlink()}
    def signed25(self,files=None,base=None,number=8,schema=6):
        return self.signed(files=self.after25 if files is None else files,base=self.after23 if base is None else base,number=number,schema=schema)
    def untouched_refusal(self):
        raw=self.state.read_bytes();before=self.tree();self.calls.clear()
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.tree(),before)
        self.assertFalse(self.stops());self.assertFalse((self.checkpoints/'pending.json').exists())

    def test_exact25_default_and_all_historical_maps(self):
        self.assertEqual(getattr(self.api,'NODE_MODES',None),FULL25);self.assertEqual(self.api.MODES,FULL25)
        self.assertEqual(set(self.api.SCHEMAS),{1,2,3,4,5,6})
        for schema,files in [(1,self.base),(2,self.current),(3,self.before16),(4,self.after22),(5,self.after23),(6,self.after25)]:
            self.assertEqual(set(self.api.SCHEMAS[schema]),set(files));self.install_state(files,schema)
            self.assertIsNotNone(self.deploy().read_state())

    def test_trusted5_to6_repeat_then6_to6_preserves_original_receipts(self):
        self.signed25();self.accepted(dict(result='installed',release_id=8))
        self.assertEqual(self.tree(),self.after25);self.assertEqual(json.loads(self.state.read_bytes())['schema'],6)
        self.assertEqual(self.receipt.read_bytes(),self.oldlive);self.assertEqual(self.attachment.read_bytes(),self.oldattachment)
        raw=self.state.read_bytes();self.calls.clear();self.accepted(dict(result='already_installed',release_id=8))
        self.assertEqual(self.state.read_bytes(),raw);self.assertFalse(self.stops());self.assertFalse(any(c[1]=='start' for c in self.calls))
        after={p:v+b'# next25\n' for p,v in self.after25.items()}
        self.signed25(files=after,base=self.after25,number=9);self.accepted(dict(result='installed',release_id=9));self.assertEqual(self.tree(),after)

    def test_invalid_scope_old_base_and_reused_id_refuse_before_mutation(self):
        for files,base in [(self.after23,self.after23),(self.after25|{'bin/arbitrary.py':b'wrong'},self.after23),(self.after25,self.before16),(self.after25,self.after22)]:
            with self.subTest(leaves=len(files),base=len(base)):
                self.signed25(files=files,base=base);self.untouched_refusal()
        self.signed25(number=7);self.untouched_refusal()

    def test_first6_requires_both_new_leaves_absent(self):
        self.signed25()
        for leaf in NODE_LEAVES:
            for kind in ('matching','symlink'):
                p=self.target/leaf
                if kind=='matching':self.write(p,self.after25[leaf],0o644)
                else:p.symlink_to(self.root/'absent')
                self.untouched_refusal();self.assertTrue(os.path.lexists(p));p.unlink()

    def test_node_chain_required_and_each_link_or_actual_unit_drift_refuses(self):
        self.signed25();self.nodes.unlink();self.untouched_refusal()
        for field,value in [('prior_receipt_sha256','e'*64),('prior_helper_sha256','e'*64),('helper_sha256','e'*64),('prior_unit_sha256','e'*64),('unit_sha256','e'*64),('schema',True),('operation','other'),('accepted_before_sha256','invalid'),('packet_sha256','invalid')]:
            with self.subTest(field=field):
                self.write(self.nodes,s.canonical({**self.node_value,field:value}),0o600);self.untouched_refusal()
        self.write(self.nodes,s.canonical(self.node_value),0o600)
        self.write(self.unit,self.nodeunit+b'# drift\n',0o644);self.untouched_refusal()

    def test_gate_accepts_complete_root_chain_and_rejects_broken_prior_chain(self):
        try:self.deploy().live_gate()
        except self.api.Rejected:self.fail('planned nodes25 root chain must authorize exact node unit/helper')
        self.write(self.attachment,s.canonical({**self.attachment_value,'prior_receipt_sha256':'e'*64}),0o600)
        with self.assertRaises(self.api.Rejected):self.deploy().live_gate()
        self.assertEqual(self.receipt.read_bytes(),self.oldlive)

    def test_nodes_keep_dependency_and_frontend_sandbox_guards(self):
        self.signed25();dependency=self.site/'nats/__init__.py';original_bytes=dependency.read_bytes()
        dependency.write_bytes(original_bytes+b'# drift\n');self.untouched_refusal();dependency.write_bytes(original_bytes)
        original=self.runner
        def widened(args):
            output=original(args)
            if args[1:3]==['show',s.SERVICES[0]]:
                output='\n'.join('ProtectHome=no' if row.startswith('ProtectHome=') else row for row in output.splitlines())
            return output
        self.runner=widened;self.untouched_refusal()

    def test_fresh6_to5_downgrade_and_unsafe_node_receipts_refuse(self):
        self.install_state(self.after25,6,8)
        self.signed25(files=self.after23,base=self.after25,number=9,schema=5);self.untouched_refusal()
        for leaf in NODE_LEAVES:(self.target/leaf).unlink()
        self.install_state(self.after23,5,7);self.signed25()
        self.nodes.chmod(0o644);self.untouched_refusal();self.nodes.unlink()
        elsewhere=self.root/'node-receipt-owner-copy';self.write(elsewhere,s.canonical(self.node_value),0o600)
        self.nodes.symlink_to(elsewhere);self.untouched_refusal()

    def test_failed5_to6_rolls_back_raw5_and_new_leaf_absence(self):
        self.signed25();raw=self.state.read_bytes();self.fail_starts=1
        with self.assertRaises(Exception):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.tree(),self.after23)
        self.assertTrue(self.stops(),'must reach installation, not early schema rejection')
        for leaf in NODE_LEAVES:self.assertFalse(os.path.lexists(self.target/leaf))
        self.assertFalse((self.checkpoints/'pending.json').exists())

    def test_failed6_to6_restores_previous25(self):
        self.install_state(self.after25,6,8);raw=self.state.read_bytes()
        nextfiles={p:v+b'# second25\n' for p,v in self.after25.items()};self.signed25(files=nextfiles,base=self.after25,number=9);self.fail_starts=1
        with self.assertRaises(Exception):self.deploy().run()
        self.assertTrue(self.stops(),'must exercise6 rollback');self.assertEqual(self.tree(),self.after25);self.assertEqual(self.state.read_bytes(),raw)

    def test_interrupted6_restores_raw5_before_bad_candidate(self):
        raw=self.state.read_bytes();before=json.loads(raw);after=dict(schema=6,release_id=8,manifest_sha256='d'*64,files=self.hashes(self.after25))
        cp=self.checkpoints/'release-node25';cp.mkdir(mode=0o700)
        for p,data in self.after23.items():self.write(cp/Path(p).name,data,0o600)
        self.write(cp/'accepted.json',raw,0o600)
        self.write(self.checkpoints/'pending.json',s.canonical(dict(schema=6,before=before,after=after,checkpoint=cp.name)),0o600)
        for p,data in self.after25.items():self.write(self.target/p,data,FULL25[p])
        self.signed25();(self.stage/'release.sig').write_bytes(bytes(64))
        with self.assertRaises(self.api.Rejected):self.deploy().run()
        self.assertEqual(self.state.read_bytes(),raw);self.assertEqual(self.tree(),self.after23)
        self.assertFalse((self.checkpoints/'pending.json').exists())


if __name__=='__main__':unittest.main()
