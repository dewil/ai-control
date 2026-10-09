"""INV-DEPLOY-22/25 real public packaging and root-stage boundaries, synthetic IO."""
import ast
import base64
from copy import deepcopy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import deploy22_blind_support as s

BOOT_BINDINGS={'EXPECTED_ACCEPTED_SHA256','EXPECTED_BEFORE_FILES','NEW_HELPER_SHA256','NEW_HELPER_BLOB_B64',
 'BEFORE_BROKER_UNIT_SHA256','AFTER_BROKER_UNIT_SHA256','BEFORE_BROKER_UNIT_BLOB_B64',
 'AFTER_BROKER_UNIT_BLOB_B64','EXPECTED_RUNTIME_STAT_PINS','WHEEL_BLOB_B64'}
STAGE_BINDINGS={prefix+suffix for prefix in ('WRAPPER','MANIFEST','BOOTSTRAP') for suffix in ('_B64','_SHA256','_SIZE')}


def literal_nodes(raw,names):
    tree=ast.parse(raw);result={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in names:
            name=node.targets[0].id
            if name in result:raise AssertionError('Duplicate public binding '+name)
            ast.literal_eval(node.value);result[name]=node.value
    if set(result)!=names:raise AssertionError('Missing public literal bindings')
    return tree,result


def masked(raw,names):
    # Independent proof of raw bytes outside allowed spans; not a replacement verifier.
    _,nodes=literal_nodes(raw,names);lines=raw.splitlines(keepends=True);offsets=[0]
    for line in lines:offsets.append(offsets[-1]+len(line))
    spans=sorted((offsets[node.lineno-1]+node.col_offset,offsets[node.end_lineno-1]+node.end_col_offset)
                 for node in nodes.values())
    for start,end in reversed(spans):raw=raw[:start]+b'<literal>'+raw[end:]
    return raw

class PacketBuilderBlind(s.BootstrapFixture):
    def setUp(self):
        self.builder=s.source_module(self,'ai-control-live-bootstrap-packet.py');self.prepare()
        self.inputs=dict(bootstrap_template=(s.ROOT/'deployment/ai-control-live-bootstrap.py').read_bytes(),
            wrapper_template=(s.ROOT/'deployment/ai-control-live-bootstrap-wrapper.py').read_bytes(),helper=self.new_helper,
            wheel=s.WHEEL.read_bytes(),unit_before=self.before_unit,unit_after=self.after_unit)

    def build(self,inputs=None,bindings=None):
        with patch.object(subprocess,'run',side_effect=AssertionError('Builder must not spawn')), \
             patch.object(socket,'socket',side_effect=AssertionError('Builder must not network')):
            return self.builder.build_packet(self.inputs if inputs is None else inputs,self.bindings if bindings is None else bindings)

    def test_deterministic_exact4_manifest_full_hash_size_crossbindings(self):
        packet=self.build();self.assertEqual(packet,self.build());self.assertEqual(set(packet),{'bootstrap.py','wrapper.py','manifest.json','bindings-proof.json'})
        self.assertTrue(all(type(value) is bytes for value in packet.values()))
        manifest=json.loads(packet['manifest.json']);self.assertEqual(packet['manifest.json'],s.canonical(manifest))
        self.assertEqual(set(manifest),{'schema','bootstrap','helper','wheel','unit_before','unit_after'});self.assertIs(type(manifest['schema']),int);self.assertEqual(manifest['schema'],1)
        artifacts={'bootstrap':packet['bootstrap.py'],'helper':self.new_helper,'wheel':s.WHEEL.read_bytes(),'unit_before':self.before_unit,'unit_after':self.after_unit}
        for name,raw in artifacts.items():self.assertEqual(manifest[name],dict(sha256=s.sha(raw),size=len(raw)))
        _,nodes=literal_nodes(packet['bootstrap.py'],BOOT_BINDINGS)
        for name,raw in [('NEW_HELPER_BLOB_B64',self.new_helper),('WHEEL_BLOB_B64',s.WHEEL.read_bytes()),('BEFORE_BROKER_UNIT_BLOB_B64',self.before_unit),('AFTER_BROKER_UNIT_BLOB_B64',self.after_unit)]:
            self.assertEqual(base64.b64decode(ast.literal_eval(nodes[name]),validate=True),raw)
        _,wrapper=literal_nodes(packet['wrapper.py'],{'MANIFEST_SHA256'})
        self.assertEqual(ast.literal_eval(wrapper['MANIFEST_SHA256']),s.sha(packet['manifest.json']))

    def test_closed_literal_spans_preserve_all_code_paths_and_carrier_None(self):
        packet=self.build()
        self.assertEqual(masked(packet['bootstrap.py'],BOOT_BINDINGS),masked(self.inputs['bootstrap_template'],BOOT_BINDINGS))
        self.assertEqual(masked(packet['wrapper.py'],{'MANIFEST_SHA256'}),masked(self.inputs['wrapper_template'],{'MANIFEST_SHA256'}))
        _,carrier=literal_nodes(packet['bootstrap.py'],{'PACKET_SHA256','PACKET_MANIFEST_SNAPSHOT'})
        for node in carrier.values():self.assertIsNone(ast.literal_eval(node))

    def test_input_keysets_unknown_binding_and_wrong_blob_hash_refuse(self):
        for inputs,bindings in [(self.inputs|{'foreign':b'candidate'},self.bindings),
            ({k:v for k,v in self.inputs.items() if k!='wheel'},self.bindings),
            (self.inputs,self.bindings|{'PACKET_SHA256':'a'*64}),
            (self.inputs,self.bindings|{'NEW_HELPER_SHA256':'a'*64}),
            (self.inputs|{'wheel':s.WHEEL.read_bytes()+b'unknown'},self.bindings)]:
            with self.subTest(keys=sorted(inputs),bindings=sorted(bindings)):
                with self.assertRaises(ValueError):self.build(inputs,bindings)

    def test_duplicate_and_nonliteral_bootstrap_binding_refuse(self):
        for extra in (b'\nNEW_HELPER_SHA256 = None\n',b'\nWHEEL_BLOB_B64 = str(None)\n'):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):self.build(self.inputs|{'bootstrap_template':self.inputs['bootstrap_template']+extra})

    def test_exact_one_CONFIG_insertion_rejects_other_allowed_byte_diffs(self):
        for after in (self.after_unit+b'# additional reviewed-looking comment\n',self.after_unit.replace(b'HOME=/home/dwl',b'HOME=/home/foreign'),
            self.after_unit.replace(s.CONFIG_LINE,s.CONFIG_LINE*2),self.after_unit.replace(b'\n',b'\r\n')):
            with self.subTest(hash=s.sha(after)):
                bindings=self.bindings|{'AFTER_BROKER_UNIT_SHA256':s.sha(after)}
                with self.assertRaises(ValueError):self.build(self.inputs|{'unit_after':after},bindings)

    def test_fill_stage_exact9_literal_spans_and_wrapper_pin_equality(self):
        packet=self.build();path=s.ROOT/'deployment/ai-control-live-bootstrap-stage.py'
        self.assertTrue(path.is_file(),'PUBLIC-SEAM PREREQUISITE: missing stage template')
        template=path.read_bytes();filled=self.builder.fill_stage(template,packet)
        self.assertEqual(filled,self.builder.fill_stage(template,packet));self.assertEqual(masked(template,STAGE_BINDINGS),masked(filled,STAGE_BINDINGS))
        _,nodes=literal_nodes(filled,STAGE_BINDINGS)
        for prefix,name in [('WRAPPER','wrapper.py'),('MANIFEST','manifest.json'),('BOOTSTRAP','bootstrap.py')]:
            self.assertEqual(ast.literal_eval(nodes[prefix+'_SIZE']),len(packet[name]))
            self.assertEqual(ast.literal_eval(nodes[prefix+'_SHA256']),s.sha(packet[name]))
            self.assertEqual(base64.b64decode(ast.literal_eval(nodes[prefix+'_B64']),validate=True),packet[name])
        for changed in (packet|{'foreign':b'unknown'},packet|{'bootstrap.py':packet['bootstrap.py']+b'\n# drift'}):
            with self.assertRaises(ValueError):self.builder.fill_stage(template,changed)

    def test_filled_wrapper_verifies_then_assigns_both_carriers_and_calls_public_bootstrap_once(self):
        import builtins
        import types
        packet=self.build();wrapper=s.module_bytes(packet['wrapper.py'],'deploy22_filled_wrapper_fixture')
        real_exec=builtins.exec;namespaces=[];calls=[]
        def execute(code,globals=None,locals=None,**kwargs):
            result=real_exec(code,globals,locals,**kwargs)
            if isinstance(code,types.CodeType) and 'bootstrap' in code.co_names and 'PACKET_SHA256' in code.co_names:
                self.assertEqual(len(namespaces),0);namespaces.append(globals)
                # Public operation callback isolates wrapper transport from bootstrap IO.
                # Bootstrap resource/lifecycle cases separately exercise actual bootstrap().
                def operation():
                    self.assertEqual(globals['PACKET_SHA256'],s.sha(packet['manifest.json']))
                    self.assertIs(globals['PACKET_MANIFEST_SNAPSHOT'],packet['manifest.json'])
                    calls.append(True)
                globals['bootstrap']=operation
            return result
        with self.root_boundary(),patch.object(builtins,'exec',side_effect=execute):
            self.assertEqual(wrapper.run_packet(packet['manifest.json'],packet['bootstrap.py']),0)
        self.assertEqual(len(namespaces),1);self.assertEqual(calls,[True]);self.assertEqual(self.trace,[])

    def test_filled_wrapper_manifest_blob_caps_hash_env_and_root_refuse_before_exec(self):
        import builtins
        packet=self.build();wrapper=s.module_bytes(packet['wrapper.py'],'deploy22_filled_wrapper_refusal')
        for manifest,bootstrap in [(packet['manifest.json']+b'\n',packet['bootstrap.py']),
            (packet['manifest.json'],packet['bootstrap.py']+b'\n# changed'),
            (b'{}',packet['bootstrap.py']), (b' '*(65536+1),packet['bootstrap.py'])]:
            with self.subTest(sizes=(len(manifest),len(bootstrap))):
                with self.root_boundary(),patch.object(builtins,'exec',side_effect=AssertionError('Invalid packet executed code')):
                    self.assertEqual(wrapper.run_packet(manifest,bootstrap),1)
        for env in ({'LD_PRELOAD':'synthetic-unsafe'},{'PYTHONPATH':'synthetic-unsafe'}):
            with self.root_boundary(),patch.dict(os.environ,env),patch.object(builtins,'exec',side_effect=AssertionError('Unsafe environment executed code')):
                self.assertEqual(wrapper.run_packet(packet['manifest.json'],packet['bootstrap.py']),1)
        with self.root_boundary(),patch.object(os,'geteuid',return_value=1000),patch.object(builtins,'exec',side_effect=AssertionError('Nonroot executed code')):
            self.assertEqual(wrapper.run_packet(packet['manifest.json'],packet['bootstrap.py']),1)


class StageBoundaryBlind(unittest.TestCase):
    module_leaf='ai-control-live-bootstrap-stage.py'
    def setUp(self):
        self.op=s.source_module(self,self.module_leaf)
        temp=tempfile.TemporaryDirectory(prefix='control-deploy22-stage-',dir='/home/dwl');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.root.chmod(0o700);self.stage_path=self.root/'live-bootstrap-packet';self.op.STAGE=self.stage_path
        self.payload={'wrapper.py':b'def run_packet(manifest_snapshot, bootstrap_snapshot):\n    return 0\n',
            'manifest.json':b'{"schema":1}', 'bootstrap.py':b'PACKET_SHA256 = None\n'}
        self.original_stat=os.stat;self.original_lstat=os.lstat;self.original_fstat=os.fstat
        for prefix,name in [('WRAPPER','wrapper.py'),('MANIFEST','manifest.json'),('BOOTSTRAP','bootstrap.py')]:
            setattr(self.op,prefix+'_B64',base64.b64encode(self.payload[name]).decode());setattr(self.op,prefix+'_SHA256',s.sha(self.payload[name]));setattr(self.op,prefix+'_SIZE',len(self.payload[name]))

    def boundary(self):
        stack=ExitStack();stack.enter_context(patch.dict(os.environ,{},clear=True));stack.enter_context(patch.object(sys,'argv',['-']))
        for name in ('getuid','geteuid','getgid','getegid'):stack.enter_context(patch.object(os,name,return_value=0))
        def stat(call,path,*args,**kwargs):
            return s.RootStat(call(path,*args,**kwargs))
        stack.enter_context(patch.object(os,'stat',side_effect=lambda path,*a,**k:stat(self.original_stat,path,*a,**k)))
        stack.enter_context(patch.object(os,'lstat',side_effect=lambda path,*a,**k:stat(self.original_lstat,path,*a,**k)))
        stack.enter_context(patch.object(os,'fstat',side_effect=lambda fd:s.RootStat(self.original_fstat(fd))))
        stack.enter_context(patch.object(subprocess,'run',side_effect=AssertionError('Stage/launcher spawned child')))
        stack.enter_context(patch.object(subprocess,'Popen',side_effect=AssertionError('Stage/launcher spawned child')))
        stack.enter_context(patch.object(socket,'socket',side_effect=AssertionError('Stage/launcher opened network')))
        return stack

    def call(self):
        with self.boundary():return self.op.stage()
    def existing(self):
        self.stage_path.mkdir(mode=0o700)
        for name,raw in self.payload.items():path=self.stage_path/name;path.write_bytes(raw);path.chmod(0o600)
    def snapshot(self):
        return {p.name:(p.lstat().st_ino,s.sha(p.read_bytes()),p.lstat().st_mode&0o777) for p in self.stage_path.iterdir() if p.is_file()}

    def test_create_exact3_private_files_no_bindingsproof(self):
        self.assertEqual(self.call(),0);self.assertEqual(self.stage_path.stat().st_mode&0o777,0o700)
        self.assertEqual({p.name for p in self.stage_path.iterdir()},set(self.payload))
        for name,raw in self.payload.items():self.assertEqual((self.stage_path/name).read_bytes(),raw);self.assertEqual((self.stage_path/name).stat().st_mode&0o777,0o600)

    def test_exact_reuse_keeps_inodes_and_fsyncs_three_files_dir_parent(self):
        self.existing();before=self.snapshot();synced=set();real=os.fsync
        def fsync(fd):synced.add(os.readlink('/proc/self/fd/'+str(fd)));return real(fd)
        with patch.object(os,'fsync',side_effect=fsync):self.assertEqual(self.call(),0)
        self.assertEqual(self.snapshot(),before)
        self.assertTrue({str(self.stage_path),str(self.stage_path.parent),*(str(self.stage_path/name) for name in self.payload)}<=synced)

    def test_partial_foreign_stage_refuse_without_repair(self):
        self.existing();(self.stage_path/'bootstrap.py').unlink();before=self.snapshot()
        self.assertEqual(self.call(),1);self.assertEqual(self.snapshot(),before)
        (self.stage_path/'foreign').write_bytes(b'owned extra');before=self.snapshot()
        self.assertEqual(self.call(),1);self.assertEqual(self.snapshot(),before)

    def test_hash_size_bool_noncanonical_base64_None_reject_before_creation(self):
        for name,value in [('WRAPPER_SHA256',None),('WRAPPER_SHA256','a'*64),('WRAPPER_SIZE',True),
            ('WRAPPER_SIZE',len(self.payload['wrapper.py'])+1),('WRAPPER_B64',self.op.WRAPPER_B64+'\n')]:
            with self.subTest(binding=name):
                old=getattr(self.op,name);setattr(self.op,name,value)
                self.assertEqual(self.call(),1);self.assertFalse(self.stage_path.exists());setattr(self.op,name,old)

    def test_creation_uses_exclusive_nofollow_and_fsync_before_success(self):
        real_open=os.open;real_sync=os.fsync;created=[];synced=set()
        def opened(path,flags,*args,**kwargs):
            if flags&os.O_CREAT:
                self.assertTrue(flags&os.O_EXCL);self.assertTrue(flags&os.O_NOFOLLOW);created.append(os.fspath(path))
            return real_open(path,flags,*args,**kwargs)
        def sync(fd):synced.add(os.readlink('/proc/self/fd/'+str(fd)));return real_sync(fd)
        with patch.object(os,'open',side_effect=opened),patch.object(os,'fsync',side_effect=sync):self.assertEqual(self.call(),0)
        self.assertEqual(len(created),3)
        self.assertTrue({str(self.stage_path),str(self.stage_path.parent),*(str(self.stage_path/name) for name in self.payload)}<=synced)

    def test_complete_stage_wrong_bytes_or_mode_refuses_without_repair(self):
        self.existing();path=self.stage_path/'bootstrap.py';path.write_bytes(b'owned drift');before=self.snapshot()
        self.assertEqual(self.call(),1);self.assertEqual(self.snapshot(),before)
        path.write_bytes(self.payload['bootstrap.py']);path.chmod(0o644);before=self.snapshot()
        self.assertEqual(self.call(),1);self.assertEqual(self.snapshot(),before)

    def test_nonroot_extraargv_refuse_without_creation(self):
        with self.boundary(),patch.object(os,'geteuid',return_value=1000):self.assertEqual(self.op.stage(),1)
        with self.boundary(),patch.object(sys,'argv',['-','candidate']):self.assertEqual(self.op.stage(),1)
        self.assertFalse(self.stage_path.exists())

class LauncherBoundaryBlind(StageBoundaryBlind):
    module_leaf='ai-control-live-bootstrap-launcher.py'
    def call(self):
        with self.boundary():return self.op.launch()
    # Independent launcher cases only; stage behaviors belong to StageBoundaryBlind.
    test_creation_uses_exclusive_nofollow_and_fsync_before_success=None
    test_complete_stage_wrong_bytes_or_mode_refuses_without_repair=None
    test_create_exact3_private_files_no_bindingsproof=None
    test_exact_reuse_keeps_inodes_and_fsyncs_three_files_dir_parent=None
    test_partial_foreign_stage_refuse_without_repair=None
    test_hash_size_bool_noncanonical_base64_None_reject_before_creation=None
    test_nonroot_extraargv_refuse_without_creation=None

    def test_None_invalid_external_pin_before_stage_open(self):
        for pin in (None,True,b'a'*64,'A'*64,'a'*63):
            self.op.EXPECTED_WRAPPER_SHA256=pin
            with self.boundary(),patch.object(os,'open',side_effect=AssertionError('Invalid pin touched stage')):
                self.assertEqual(self.op.launch(),1)

    def test_actual_pinned_wrapper_snapshot_exec_success_no_mutation(self):
        self.existing();self.op.EXPECTED_WRAPPER_SHA256=s.sha(self.payload['wrapper.py']);before=self.snapshot()
        self.assertEqual(self.call(),0);self.assertEqual(self.snapshot(),before)

    def test_changed_wrapper_same_metadata_size_fails_full_SHA(self):
        self.existing();self.op.EXPECTED_WRAPPER_SHA256=s.sha(self.payload['wrapper.py'])
        path=self.stage_path/'wrapper.py';path.write_bytes(self.payload['wrapper.py'].replace(b'return 0',b'return 1'));before=self.snapshot()
        self.assertEqual(self.call(),1);self.assertEqual(self.snapshot(),before)

    def test_symlink_extra_and_hardlink_refuse_without_exec_or_cleanup(self):
        self.existing();self.op.EXPECTED_WRAPPER_SHA256=s.sha(self.payload['wrapper.py'])
        wrapper=self.stage_path/'wrapper.py';wrapper.unlink();wrapper.symlink_to(self.root/'absent')
        self.assertEqual(self.call(),1);self.assertTrue(wrapper.is_symlink());wrapper.unlink();wrapper.write_bytes(self.payload['wrapper.py']);wrapper.chmod(0o600)
        (self.stage_path/'foreign').write_bytes(b'owned foreign');self.assertEqual(self.call(),1);self.assertTrue((self.stage_path/'foreign').exists())
        (self.stage_path/'foreign').unlink();os.link(wrapper,self.root/'alias');self.assertEqual(self.call(),1)

    def test_wrapper_swap_during_descriptor_read_refuses_and_preserves_replacement(self):
        self.existing();self.op.EXPECTED_WRAPPER_SHA256=s.sha(self.payload['wrapper.py'])
        real_read=os.read;swapped=[]
        def read(fd,size):
            raw=real_read(fd,size)
            if not swapped and os.readlink('/proc/self/fd/'+str(fd))==str(self.stage_path/'wrapper.py'):
                replacement=self.root/'replacement';replacement.write_bytes(self.payload['wrapper.py']);replacement.chmod(0o600)
                replacement.replace(self.stage_path/'wrapper.py');swapped.append(True)
            return raw
        with patch.object(os,'read',side_effect=read):self.assertEqual(self.call(),1)
        self.assertEqual(swapped,[True]);self.assertEqual((self.stage_path/'wrapper.py').read_bytes(),self.payload['wrapper.py'])


class WrapperInputBoundaryBlind(unittest.TestCase):
    def setUp(self):self.op=s.source_module(self,'ai-control-live-bootstrap-wrapper.py')
    def test_unbound_manifest_pin_and_oversize_refuse_without_exec(self):
        for manifest,bootstrap in [(b'{}',b'pass\n'),(b' '*(65536+1),b'pass\n'),(b'{}',b' '*(4194304+1))]:
            with self.subTest(sizes=(len(manifest),len(bootstrap))):
                with patch.object(os,'geteuid',return_value=0),patch.object(sys,'argv',['-']),patch.dict(os.environ,{},clear=True):
                    self.assertEqual(self.op.run_packet(manifest,bootstrap),1)
    def test_pinned_manifest_with_wrong_bootstrap_snapshot_refuses(self):
        manifest=s.canonical(dict(schema=1,bootstrap=dict(sha256='a'*64,size=5),helper=dict(sha256='b'*64,size=1),
            wheel=dict(sha256=s.WHEEL_SHA,size=82408),unit_before=dict(sha256='c'*64,size=1),unit_after=dict(sha256='d'*64,size=1)))
        self.op.MANIFEST_SHA256=s.sha(manifest)
        with patch.object(os,'geteuid',return_value=0),patch.object(sys,'argv',['-']),patch.dict(os.environ,{},clear=True):
            self.assertEqual(self.op.run_packet(manifest,b'pass\n'),1)
