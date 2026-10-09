"""DEPLOY22 public fixtures: immutable actual helper, synthetic signed paths only."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import tempfile
import unittest
from unittest.mock import patch
import test_control_web_app_deploy16_blind_red as prior

ROOT=Path(__file__).resolve().parents[1]
OLD_COMMIT='0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde'
OLD_SHA='bf142e2b6fee390dfe50a44533e18801ba93b66bcba11c0d14c587b65b270dc1'
WHEEL_SHA='132a8e4b646ad058c7b242b7161621832ee8737ca6f6cbd47dcb6d3ad09490ed'
INVENTORY_SHA='40b35159d50cf2bf0f645f5ab1564f5a3fd0efcee266405fffeb6a496dc7bb43'
INDEX_SHA='572c199059d27df7df9c3feb38c6d7cb3cff264a8b6114e20bf28c54e9e22ec2'
FIXTURE=ROOT/'tests/fixtures/deploy22-nats'
WHEEL=FIXTURE/'nats_py-2.9.0-py3-none-any.whl'
FULL16=dict(prior.FULL16)
NEW=('bin/_control_web_devbus.py','bin/_control_web_devbus_nats.py','bin/_control_web_devbus.js',
     'bin/_control_web_devbus.css','requirements-devbus.lock','bin/_control_web_live.py')
FULL22=FULL16|{name:0o644 for name in NEW}
SERVICES=prior.fixture.SERVICES
CONFIG_LINE=b'Environment=CONTROL_DEVBUS_CONFIG=/home/dwl/.config/ai-control/devbus-observer.json\n'
SAFE_PROPERTIES=('User','Group','ProtectSystem','ProtectHome','ReadWritePaths','InaccessiblePaths','FragmentPath','DropInPaths')


def sha(data):return hashlib.sha256(data).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def rows():return json.loads((FIXTURE/'wheel-inventory.json').read_bytes())


def pinned_source():
    result=subprocess.run(['/usr/bin/git','-C',str(ROOT),'show',OLD_COMMIT+':deployment/ai-control-web-deploy.py'],
        capture_output=True,timeout=10,check=True)
    if len(result.stdout)>1024*1024 or sha(result.stdout)!=OLD_SHA:raise AssertionError('Immutable accepted helper byte/pin mismatch')
    return result.stdout


def module_bytes(data,label):
    module=types.ModuleType(label);module.__file__=str(ROOT/'deployment'/label)
    sys.modules[label]=module;exec(compile(data,module.__file__,'exec'),module.__dict__);return module


def source_module(case,leaf):
    path=ROOT/'deployment'/leaf
    case.assertTrue(path.is_file(),'PUBLIC-SEAM PREREQUISITE: missing '+leaf+'; absence is not semantic RED')
    spec=importlib.util.spec_from_file_location('deploy22_blind_'+leaf.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


class ControllerFixture(unittest.TestCase):
    for _name in ('crypto','write','hashes','stops','deploy','accepted'):
        locals()[_name]=getattr(prior.fixture.SignedDeploy,_name)

    def setUp(self):
        # Narrow accepted public fixture setup; no legacy inherited tests/source inspection.
        temp_constructor=tempfile.TemporaryDirectory
        with patch.object(tempfile,'TemporaryDirectory',side_effect=lambda **kwargs:temp_constructor(**(kwargs|{'dir':'/home/dwl'}))):
            prior.fixture.SignedDeploy.setUp(self)
        self.before16=self.current|{prior.AUTH:b'# invented auth16\n',prior.DOWNLOAD:b'# invented download16\n'}
        self.after22=self.before16|{p:('/* invented signed22 '+p+' */\n').encode() for p in NEW}
        self.install_state(self.before16,3,7)
        self.receipt=self.state.parent/'live-bootstrap-complete.json'
        self.unit=self.root/'actual-systemd/ai-control-web-broker.service'
        self.helper=self.root/'helper/ai-control-deploy'
        self.site=self.root/'venv/lib/python3.12/site-packages'
        self.write(self.helper,prior.fixture.SOURCE.read_bytes(),0o755)
        unit_before=(ROOT/'tests/fixtures/deploy22-blind/broker-unit.before').read_bytes()
        self.write(self.unit,unit_before.replace(b'[Service]\n',b'[Service]\n'+CONFIG_LINE,1),0o644)
        self.site.mkdir(parents=True,mode=0o755);self.site.chmod(0o755)
        # Only named source-final/public path constants are rebound; no private
        # validator/gate names or fake behavior implementations are introduced.
        for name,path in dict(LIVE_RECEIPT=self.receipt,BROKER_UNIT=self.unit,HELPER=self.helper,
            SITE_PACKAGES=self.site,DEP_PACKAGE=self.site/'nats',DEP_INFO=self.site/'nats_py-2.9.0.dist-info').items():
            if hasattr(self.api,name):setattr(self.api,name,path)

    def install_state(self,files,schema,number=7):
        for path,data in files.items():self.write(self.target/path,data,FULL22[path])
        value=dict(schema=schema,release_id=number,manifest_sha256='a'*64,files=self.hashes(files))
        self.write(self.state,json.dumps(value,indent=2).encode()+b'\n',0o600)
        self.initial_state=self.state.read_bytes();return value

    def tree(self):
        return {p:(self.target/p).read_bytes() for p in FULL22 if (self.target/p).is_file() and not (self.target/p).is_symlink()}

    def runner(self,args):
        self.assertEqual(args[0],'/usr/bin/systemctl');self.assertIn(args[1],('is-active','show','stop','start'))
        self.assertIn(args[2],SERVICES);self.calls.append(list(args))
        if args[1]=='is-active':return 'inactive' if self.unhealthy else 'active'
        if args[1]=='show':
            if len(args)==6 and args[3]=='-p' and args[4] in ('User','Group') and args[5]=='--value':
                return 'ai-panel' if args[4]=='Group' or args[2]==SERVICES[0] else 'dwl'
            selected=','.join(args[3:])
            self.assertNotIn('Environment',selected);self.assertNotIn('ExecStart',selected)
            for prop in SAFE_PROPERTIES:self.assertIn(prop,selected)
            properties=dict(User='ai-panel' if args[2]==SERVICES[0] else 'dwl',Group='ai-panel',
                ProtectSystem='strict' if args[2]==SERVICES[0] else 'full',
                ProtectHome='yes' if args[2]==SERVICES[0] else 'no',
                ReadWritePaths='/var/lib/ai-control-web' if args[2]==SERVICES[0] else '/run/ai-control-web /var/lib/ai-control-web',
                InaccessiblePaths='/data' if args[2]==SERVICES[0] else '',
                FragmentPath='/etc/systemd/system/'+args[2],DropInPaths='')
            return '\n'.join(key+'='+value for key,value in properties.items())+'\n'
        if args[1]=='start':
            self.observations.append(self.hashes(self.tree()))
            if self.before_start:self.before_start()
            if self.fail_starts:self.fail_starts-=1;raise RuntimeError('Synthetic start failure')
        return ''

    def signed(self,files=None,number=8,base=None,schema=4):
        files=self.after22 if files is None else files;base=self.before16 if base is None else base
        return prior.fixture.SignedDeploy.release(self,number,files,base,manifest_changes={'schema':schema})

    def dependency_after(self):
        import zipfile
        with zipfile.ZipFile(WHEEL) as wheel:
            for row in rows():self.write(self.site/row['path'],wheel.read(row['path']),row['install_mode'])
        for directory in self.site.rglob('*'):
            if directory.is_dir():directory.chmod(0o755)
        value=dict(schema=1,operation='live22-bootstrap',packet_sha256='b'*64,
            accepted_before_sha256=sha(self.initial_state),helper_sha256=sha(self.helper.read_bytes()),
            unit_sha256=sha(self.unit.read_bytes()),wheel_sha256=WHEEL_SHA,dependency_inventory_sha256=INVENTORY_SHA)
        self.write(self.receipt,canonical(value),0o600)

    def make_journal(self,before_schema=3,accepted_after=False,mask=0):
        before=self.before16 if before_schema==3 else self.after22
        after={path:data+b'\n/* independent22after */\n' for path,data in self.after22.items()}
        for path in NEW:
            if os.path.lexists(self.target/path):(self.target/path).unlink()
        self.install_state(before,before_schema)
        raw=self.state.read_bytes();before_state=json.loads(raw)
        after_state=dict(schema=4,release_id=8,manifest_sha256='b'*64,files=self.hashes(after))
        checkpoint=self.checkpoints/'release-live22-blind'
        checkpoint.mkdir(mode=0o700)
        for path,data in before.items():self.write(checkpoint/Path(path).name,data,0o600)
        self.write(checkpoint/'accepted.json',raw,0o600)
        self.write(self.checkpoints/'pending.json',canonical(dict(schema=4,before=before_state,after=after_state,checkpoint=checkpoint.name)),0o600)
        if accepted_after:
            for path,data in after.items():self.write(self.target/path,data,FULL22[path])
            self.write(self.state,canonical(after_state),0o600)
        else:
            for index,path in enumerate(NEW):
                if mask&(1<<index):self.write(self.target/path,after[path],FULL22[path])
        return raw,before,after,after_state,checkpoint

class RootStat:
    """Explicit synthetic identity boundary; real inode/mode/content stay intact."""
    def __init__(self,original,directory_mode=None):self.original=original;self.directory_mode=directory_mode
    def __getattr__(self,name):
        if name in ('st_uid','st_gid'):return 0
        if name=='st_mode' and self.directory_mode is not None:return (self.original.st_mode&~0o7777)|self.directory_mode
        return getattr(self.original,name)
    def __getitem__(self,index):
        if index in (4,5):return 0
        if index==0:return self.st_mode
        return self.original[index]
    def __iter__(self):return iter(tuple(self[index] for index in range(10)))


class BootstrapFixture(ControllerFixture):
    def prepare(self):
        self.op=source_module(self,'ai-control-live-bootstrap.py')
        ControllerFixture.setUp(self)
        self.paths=dict(TARGET=self.target,HELPER=self.helper,STATE=self.state,KEY=self.key,
            LOCK=self.checkpoints/'lock',PACKAGE_PENDING=self.checkpoints/'pending.json',
            CONFIG_PENDING=self.state.parent/'config-pending.json',BOOTSTRAP_PENDING=self.state.parent/'bootstrap-pending.json',
            LIVE_CHECKPOINTS=self.state.parent/'live-bootstrap-checkpoints',LIVE_RECEIPT=self.receipt,
            BROKER_UNIT=self.unit,SITE_PACKAGES=self.site,DEP_PACKAGE=self.site/'nats',
            DEP_INFO=self.site/'nats_py-2.9.0.dist-info',VENV_ROOT=self.root/'venv')
        for name,path in self.paths.items():setattr(self.op,name,path)
        self.write(self.paths['LOCK'],b'',0o600)
        self.paths['LIVE_CHECKPOINTS'].mkdir(mode=0o700)
        self.paths['VENV_ROOT'].chmod(0o755)
        self.before_unit=(ROOT/'tests/fixtures/deploy22-blind/broker-unit.before').read_bytes()
        self.after_unit=self.before_unit.replace(b'[Service]\n',b'[Service]\n'+CONFIG_LINE,1)
        self.write(self.unit,self.before_unit,0o644);self.write(self.helper,pinned_source(),0o755)
        self.new_helper=prior.fixture.SOURCE.read_bytes()
        self.virtual={}
        self.stat_pins={}
        for name in ('SYSTEM_PYTHON','VENV_PYTHON','OWNER_IMPORT_LAUNCHER','SYSTEMCTL'):
            fixed={'SYSTEM_PYTHON':'/usr/bin/python3','VENV_PYTHON':'/opt/ai-control-web/venv/bin/python',
                'OWNER_IMPORT_LAUNCHER':'/usr/bin/setpriv','SYSTEMCTL':'/usr/bin/systemctl'}[name]
            node=(self.paths['VENV_ROOT']/'bin/python') if name=='VENV_PYTHON' else self.root/'executor-vfs'/fixed.lstrip('/')
            self.write(node,('# synthetic never-executed '+name+'\n').encode(),0o755)
            for parent in node.parents:
                if parent==self.root:break
                parent.chmod(0o755)
            self.virtual[fixed]=node;stat=node.lstat()
            self.stat_pins[name]=dict(links=[],resolved=dict(path=fixed,dev=stat.st_dev,ino=stat.st_ino,
                uid=0,gid=0,mode=stat.st_mode&0o7777,size=stat.st_size,sha256=sha(node.read_bytes())))
        for fixed,node in list(self.virtual.items()):
            for parent in Path(fixed).parents:
                if str(parent)=='/':break
                if str(parent) not in self.virtual:
                    mapped=self.root/'executor-vfs'/str(parent).lstrip('/')
                    mapped.mkdir(parents=True,exist_ok=True,mode=0o755);mapped.chmod(0o755)
                    self.virtual[str(parent)]=mapped
        self.virtual['/opt/ai-control-web/venv']=self.paths['VENV_ROOT']
        self.virtual['/opt/ai-control-web/venv/bin']=self.paths['VENV_ROOT']/'bin'
        self.fd_logical={}
        for name in ('LOCK','SITE_PACKAGES','VENV_ROOT'):
            stat=self.paths[name].lstat();self.stat_pins[name]=dict(dev=stat.st_dev,ino=stat.st_ino,uid=0,gid=0,mode=stat.st_mode&0o7777)
        self.stat_pins['BROKER_UNIT_MODE']=0o644
        import base64
        self.bindings=dict(EXPECTED_ACCEPTED_SHA256=sha(self.state.read_bytes()),EXPECTED_BEFORE_FILES=self.hashes(self.before16),
            NEW_HELPER_SHA256=sha(self.new_helper),BEFORE_BROKER_UNIT_SHA256=sha(self.before_unit),
            AFTER_BROKER_UNIT_SHA256=sha(self.after_unit),EXPECTED_RUNTIME_STAT_PINS=deepcopy(self.stat_pins))
        blobs=dict(NEW_HELPER_BLOB_B64=self.new_helper,WHEEL_BLOB_B64=WHEEL.read_bytes(),
            BEFORE_BROKER_UNIT_BLOB_B64=self.before_unit,AFTER_BROKER_UNIT_BLOB_B64=self.after_unit)
        for name,value in self.bindings.items():setattr(self.op,name,deepcopy(value))
        for name,value in blobs.items():setattr(self.op,name,base64.b64encode(value).decode())
        self.op.OLD_HELPER_SHA256=OLD_SHA;self.op.KEY_SHA256=sha(self.key.read_bytes())
        bootstrap_snapshot=(ROOT/'deployment/ai-control-live-bootstrap.py').read_bytes()
        manifest=dict(schema=1,bootstrap=dict(sha256=sha(bootstrap_snapshot),size=len(bootstrap_snapshot)))
        for key,raw in dict(helper=self.new_helper,wheel=WHEEL.read_bytes(),unit_before=self.before_unit,unit_after=self.after_unit).items():
            manifest[key]=dict(sha256=sha(raw),size=len(raw))
        self.packet_manifest=canonical(manifest)
        self.op.PACKET_MANIFEST_SNAPSHOT=self.packet_manifest;self.op.PACKET_SHA256=sha(self.packet_manifest)
        self.trace=[];self.after_command=None;self.smoke_result=None;self.active={service:True for service in SERVICES}
        self.actual_run_command=self.op.run_command
        self.op.run_command=self.command
        self.original_stat=os.stat;self.original_lstat=os.lstat;self.original_fstat=os.fstat
        self.original_open=os.open;self.original_builtin_open=__import__('builtins').open

    def identity(self,path,dir_fd=None):
        if isinstance(path,int):return path
        text=os.fspath(path)
        if not os.path.isabs(text) and dir_fd is not None:
            parent=self.fd_logical.get(dir_fd,os.readlink('/proc/self/fd/'+str(dir_fd)))
            text=os.path.normpath(os.path.join(parent,text))
        return self.virtual.get(text,text)

    def root_stat(self,call,path,*args,**kwargs):
        actual=self.identity(path,kwargs.get('dir_fd'))
        return RootStat(call(actual,*args,**kwargs))

    def command(self,argv,*,timeout=40,env=None,cwd='/'):
        self.trace.append(dict(argv=list(argv),timeout=timeout,env=env,cwd=cwd))
        if self.after_command:self.after_command(argv)
        if argv[0]=='/usr/bin/setpriv':
            self.assertEqual(argv[:11],['/usr/bin/setpriv','--reuid=1000','--regid=1000','--clear-groups','--no-new-privs','--',
                '/opt/ai-control-web/venv/bin/python','-I','-B','-c',self.op.OWNER_IMPORT_CODE])
            self.assertEqual(len(argv),11);self.assertEqual((timeout,env,cwd),(10,{},'/'))
            self.assertEqual(self.installed_rows(),rows(),'Smoke cannot precede actual complete installed content/modes')
            value=dict(schema=1,uid=1000,gid=1000,python='3.12.3',version='2.9.0',connect_api=True,client_api=True,
                jetstream_api=True,consumer_config_api=True,
                source_file='/opt/ai-control-web/venv/lib/python3.12/site-packages/nats/__init__.py',network_calls=0)
            return self.smoke_result or subprocess.CompletedProcess(argv,0,canonical(value)+b'\n',b'')
        self.assertEqual(argv[0],'/usr/bin/systemctl');self.assertEqual(timeout,40)
        self.assertNotIn('Environment',','.join(argv));action=argv[1]
        self.assertIn(action,('is-active','show','stop','start','daemon-reload'))
        if action=='daemon-reload':self.assertEqual(len(argv),2);return subprocess.CompletedProcess(argv,0,b'',b'')
        self.assertIn(argv[2],SERVICES);service=argv[2]
        if action=='stop':self.active[service]=False
        if action=='start':self.active[service]=True
        if action=='is-active':return subprocess.CompletedProcess(argv,0 if self.active[service] else 3,
            b'active\n' if self.active[service] else b'inactive\n',b'')
        if action=='show':
            for key in SAFE_PROPERTIES:self.assertIn(key,','.join(argv[3:]))
            values=dict(User='ai-panel' if service==SERVICES[0] else 'dwl',Group='ai-panel',
                ProtectSystem='strict' if service==SERVICES[0] else 'full',ProtectHome='yes' if service==SERVICES[0] else 'no',
                ReadWritePaths='/var/lib/ai-control-web' if service==SERVICES[0] else '',
                InaccessiblePaths='/data' if service==SERVICES[0] else '',FragmentPath='/etc/systemd/system/'+service,DropInPaths='')
            return subprocess.CompletedProcess(argv,0,('\n'.join(key+'='+value for key,value in values.items())+'\n').encode(),b'')
        return subprocess.CompletedProcess(argv,0,b'',b'')

    def installed_rows(self):
        result=[]
        for row in rows():
            path=self.site/row['path'];data=path.read_bytes();stat=self.original_lstat(path)
            result.append(dict(path=row['path'],sha256=sha(data),size=len(data),archive_mode=row['archive_mode'],install_mode=stat.st_mode&0o777))
        return result

    def root_boundary(self):
        from contextlib import ExitStack
        import builtins
        import pwd
        import grp
        stack=ExitStack()
        stack.enter_context(patch.dict(os.environ,{},clear=True))
        for name in ('getuid','geteuid','getgid','getegid'):stack.enter_context(patch.object(os,name,return_value=0))
        stack.enter_context(patch.object(os,'stat',side_effect=lambda path,*a,**k:self.root_stat(self.original_stat,path,*a,**k)))
        stack.enter_context(patch.object(os,'lstat',side_effect=lambda path,*a,**k:self.root_stat(self.original_lstat,path,*a,**k)))
        stack.enter_context(patch.object(os,'fstat',side_effect=lambda fd:RootStat(self.original_fstat(fd))))
        def opened(path,*args,**kwargs):
            actual=self.identity(path,kwargs.get('dir_fd'))
            text=os.fspath(actual)
            if text.startswith('/home/dwl/.config/ai-control'):raise AssertionError('Root touched forbidden owner config/parent')
            if not isinstance(actual,int) and text.startswith(('/opt/ai-control','/var/lib/ai-control','/etc/ai-control','/etc/systemd')):
                raise AssertionError('Unmapped production filesystem access')
            fd=self.original_open(actual,*args,**kwargs)
            logical=os.fspath(path)
            if not os.path.isabs(logical) and kwargs.get('dir_fd') is not None:
                parent=self.fd_logical.get(kwargs['dir_fd'],os.readlink('/proc/self/fd/'+str(kwargs['dir_fd'])))
                logical=os.path.normpath(os.path.join(parent,logical))
            self.fd_logical[fd]=logical
            return fd
        stack.enter_context(patch.object(os,'open',side_effect=opened))
        def builtin_open(path,*args,**kwargs):
            actual=self.identity(path)
            if not isinstance(actual,int) and os.fspath(actual).startswith(('/home/dwl/.config/ai-control','/opt/ai-control','/var/lib/ai-control','/etc/ai-control','/etc/systemd')):
                raise AssertionError('Unmapped/forbidden production open')
            return self.original_builtin_open(actual,*args,**kwargs)
        stack.enter_context(patch.object(builtins,'open',side_effect=builtin_open))
        import socket
        stack.enter_context(patch.object(socket,'socket',side_effect=AssertionError('No real network in DEPLOY fixture')))
        stack.enter_context(patch.object(socket,'getaddrinfo',side_effect=AssertionError('No real DNS in DEPLOY fixture')))
        stack.enter_context(patch.object(subprocess,'run',side_effect=AssertionError('Bootstrap bypassed public run_command')))
        stack.enter_context(patch.object(subprocess,'Popen',side_effect=AssertionError('Bootstrap bypassed public run_command')))
        imported=builtins.__import__
        def import_only(name,*args,**kwargs):
            if name.split('.',1)[0] in ('nats','pip','setuptools'):raise AssertionError('Root bootstrap imported dependency/build code')
            return imported(name,*args,**kwargs)
        stack.enter_context(patch.object(builtins,'__import__',side_effect=import_only))
        def account(name):
            uid,gid={'root':(0,0),'dwl':(1000,1000),'ai-panel':(993,987)}[name]
            return pwd.struct_passwd((name,'x',uid,gid,'synthetic','/home/'+name,'/bin/false'))
        stack.enter_context(patch.object(pwd,'getpwnam',side_effect=account))
        stack.enter_context(patch.object(grp,'getgrnam',side_effect=lambda name:grp.struct_group((name,'x',{'root':0,'dwl':1000,'ai-panel':987}[name],[]))))
        stack.enter_context(patch.object(sys,'argv',['-']))
        return stack

    def invoke(self):
        with self.root_boundary():return self.op.bootstrap()
