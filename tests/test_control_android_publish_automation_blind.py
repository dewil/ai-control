"""INV-APKDEP-01..05: public frozen contract, no real root/publication operations."""
import importlib.util,json,os,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'deployment/ai-control-android-publish.py'
CERT='baa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce'
def metadata(code=8):return dict(schema=1,versionCode=code,versionName='0.1.'+str(code-1),sha256='a'*64)
def load(path):
    spec=importlib.util.spec_from_file_location('blind_publish',path);module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);return module
@unittest.skipUnless(SOURCE.exists(),'Future module absent; not architectural RED')
class PersistentPublisherContract(unittest.TestCase):
    def setUp(self):self.api=load(SOURCE)
    def test_exact_positive_metadata_successive_versions_same_source(self):
        before=SOURCE.read_bytes()
        for code in [8,9,2147483647]:self.assertEqual(self.api.parse_release(json.dumps(metadata(code)).encode()),metadata(code))
        self.assertEqual(before,SOURCE.read_bytes())
    def test_strict_parser_refuses_invalid_metadata(self):
        values=[]
        for key,bad in [('schema',True),('schema',2),('versionCode',True),('versionCode',0),('versionCode',2147483648),('versionCode',8.0),('versionName',''),('versionName','x'*65),('versionName','bad\nname'),('versionName','bad\x7fname'),('sha256','A'*64),('sha256','a'*63),('sha256',None)]:values.append({**metadata(),key:bad})
        values.extend([{**metadata(),'apk':'/arbitrary'},{**metadata(),'certificate':CERT},[],None,{k:v for k,v in metadata().items() if k!='schema'}])
        for value in values:
            with self.subTest(value=value),self.assertRaises(ValueError):self.api.parse_release(json.dumps(value).encode())
        for raw in [b'{',b'\xff',b'{"schema":1,"schema":1,"versionCode":8,"versionName":"test","sha256":"'+b'a'*64+b'"}',b' '*16385]:
            with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):self.api.parse_release(raw)
    def stage(self,directory):
        stage=Path(directory)/'stage';stage.mkdir(mode=0o700)
        release=stage/'release.json';release.write_text(json.dumps(metadata()));release.chmod(0o600)
        apk=stage/'release.apk';apk.write_bytes(b'synthetic APK');apk.chmod(0o600)
        return stage
    def test_secure_stage_positive_and_no_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            stage=self.stage(directory)
            with patch.dict(os.environ,{'STAGE':'/unapproved','APK_PATH':'/unapproved','VERSION_CODE':'1'}):self.assertEqual(self.api.load_release(stage,os.getuid()),metadata())
    def test_valid_private_release_with_old_access_time_remains_loadable(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            stage=self.stage(directory)
            for path in [stage/'release.json',stage/'release.apk']:os.utime(path,(1,time.time()))
            self.assertEqual(self.api.load_release(stage,os.getuid()),metadata())
    def test_stage_metadata_modes_links_owner_and_size_fail_closed(self):
        for case in ['directory-mode','file-mode','symlink','hardlink','fifo','oversize','wrong-owner','stage-link','apk-link','apk-hardlink','apk-mode','apk-oversize']:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                stage=self.stage(directory);release=stage/'release.json';apk=stage/'release.apk';owner=os.getuid()
                if case=='directory-mode':stage.chmod(0o755)
                elif case=='file-mode':release.chmod(0o644)
                elif case=='symlink':release.rename(stage/'saved');release.symlink_to(stage/'saved')
                elif case=='hardlink':os.link(release,stage/'alias')
                elif case=='fifo':release.unlink();os.mkfifo(release,0o600)
                elif case=='oversize':release.write_bytes(b' '*16385)
                elif case=='wrong-owner':owner+=1
                elif case=='stage-link':alias=Path(directory)/'alias';alias.symlink_to(stage);stage=alias
                elif case=='apk-link':apk.rename(stage/'saved');apk.symlink_to(stage/'saved')
                elif case=='apk-hardlink':os.link(apk,stage/'alias')
                elif case=='apk-mode':apk.chmod(0o666)
                elif case=='apk-oversize':
                    with apk.open('wb') as stream:stream.truncate(128*1024*1024+1)
                with self.assertRaises(ValueError):self.api.load_release(stage,owner)
    def test_privilege_drop_permanent_group_gid_uid_order(self):
        events=[];state=dict(uid=0,gid=0,groups=[0])
        def groups(v):events.append(('groups',v));state['groups']=v
        def gid(v):events.append(('gid',v));state['gid']=v
        def uid(v):events.append(('uid',v));state['uid']=v
        def resgid(real,effective,saved):
            self.assertEqual((real,effective,saved),(1000,1000,1000));gid(real)
        def resuid(real,effective,saved):
            self.assertEqual((real,effective,saved),(1000,1000,1000));uid(real)
        with patch('os.setgroups',groups),patch('os.setgid',gid),patch('os.setuid',uid),patch('os.setresgid',resgid),patch('os.setresuid',resuid),patch('os.getuid',lambda:state['uid']),patch('os.geteuid',lambda:state['uid']),patch('os.getgid',lambda:state['gid']),patch('os.getegid',lambda:state['gid']),patch('os.getgroups',lambda:state['groups']),patch('os.getresuid',lambda:(state['uid'],)*3),patch('os.getresgid',lambda:(state['gid'],)*3):self.api.drop_privileges(1000,1000,987)
        self.assertEqual(events,[('groups',[1000,987]),('gid',1000),('uid',1000)])
    def test_fixed_paths(self):
        self.assertEqual(Path(self.api.STAGE),Path('/home/dwl/ai-control-android-publish-stage'))
        self.assertEqual(Path(self.api.PUBLISHER),Path('/usr/local/lib/ai-control/publish-android-release.py'))
        self.assertEqual(Path(self.api.HELPER),Path('/usr/local/sbin/ai-control-publish-android'))

    def run_fixture(self):
        events=[];state={'dropped':False};snapshot=b'synthetic reviewed publisher'
        def root_runtime():events.append('root')
        def identity(name):
            events.append('identity-'+name)
            return {'root':(0,0),'dwl':(1000,1000),'ai-panel':(993,987)}[name]
        def validate():
            self.assertFalse(state['dropped']);events.append('validate-root-source');return snapshot
        def drop(*args):state['dropped']=True;events.append('drop')
        def loader(raw):
            self.assertTrue(state['dropped']);self.assertEqual(raw,snapshot);events.append('compile-source')
            def publish(path,**kwargs):
                self.assertTrue(state['dropped']);events.append(('publish',path,kwargs));return 'synthetic-proof'
            return types.SimpleNamespace(publish=publish)
        releases=iter([metadata(8),metadata(9)])
        def release(stage,uid):
            self.assertTrue(state['dropped']);self.assertEqual(Path(stage),Path('/home/dwl/ai-control-android-publish-stage'));self.assertEqual(uid,1000);events.append('read-stage');return next(releases)
        for name,value in [('root_runtime',root_runtime),('account_identity',identity),('validate_publisher_source',validate),('drop_privileges',drop),('load_publisher',loader),('load_release',release)]:
            patcher=patch.object(self.api,name,value);patcher.start();self.addCleanup(patcher.stop)
        return events,state
    def test_root_source_before_drop_stage_and_compilation_after_drop_reuse(self):
        events,state=self.run_fixture();before=SOURCE.read_bytes()
        with patch('os.chdir'),patch('os.umask'),patch.dict(os.environ,{'STAGE':'/hostile','PUBLISHER':'/hostile','VERSION_CODE':'1'}):
            for code in [8,9]:
                state['dropped']=False;events.clear();self.assertEqual(self.api.run(),'synthetic-proof')
                self.assertLess(events.index('validate-root-source'),events.index('drop'))
                self.assertLess(events.index('drop'),events.index('compile-source'));self.assertLess(events.index('drop'),events.index('read-stage'))
                published=[event for event in events if type(event) is tuple][0]
                self.assertEqual(published,('publish',Path('/home/dwl/ai-control-android-publish-stage/release.apk'),dict(version_code=code,version_name=metadata(code)['versionName'],sha256='a'*64,certificate_sha256=CERT)))
        self.assertEqual(SOURCE.read_bytes(),before)
    def test_failed_root_metadata_or_identity_never_reads_stage_or_compiles(self):
        for failure in ['root','identity','metadata','drop']:
            with self.subTest(failure=failure):
                events,state=self.run_fixture()
                def refuse(*args):raise ValueError('Synthetic refusal')
                seam={'root':'root_runtime','identity':'account_identity','metadata':'validate_publisher_source','drop':'drop_privileges'}[failure]
                with patch.object(self.api,seam,refuse),patch('os.chdir'),patch('os.umask'),patch.dict(os.environ,{}):
                    with self.assertRaises(ValueError):self.api.run()
                self.assertNotIn('read-stage',events);self.assertNotIn('compile-source',events)
    def test_noargs_main_refuses_cli_before_operation(self):
        from contextlib import redirect_stdout,redirect_stderr
        import io
        for arguments in [['helper','/arbitrary'],['helper','--version-code','8'],['helper','rollback']]:
            with self.subTest(arguments=arguments),patch.object(sys,'argv',arguments),patch.object(self.api,'run') as operation,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                self.assertNotEqual(self.api.main(),0);operation.assert_not_called()
    def test_root_runtime_rejects_nonisolated_or_nonroot(self):
        for isolated,uid,euid,argv in [(0,0,0,['helper']),(1,1000,1000,['helper']),(1,0,1000,['helper']),(1,0,0,['helper','argument'])]:
            with self.subTest(isolated=isolated,uid=uid,euid=euid,argv=argv),patch.object(sys,'flags',types.SimpleNamespace(isolated=isolated)),patch.object(sys,'argv',argv),patch('os.getuid',return_value=uid),patch('os.geteuid',return_value=euid):
                with self.assertRaises(ValueError):self.api.root_runtime()

    def test_root_publisher_snapshot_metadata_nofollow_bounds(self):
        import stat
        actual_fstat=os.fstat;actual_stat=os.stat;actual_lstat=os.lstat
        for case in ['safe','old-atime','file-mode','file-owner','hardlink','symlink','fifo','oversize','ancestor-mode','ancestor-link']:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                parent=Path(directory)/'trusted';parent.mkdir(mode=0o755);publisher=parent/'publisher.py';publisher.write_bytes(b'PUBLIC_SYNTHETIC_SOURCE=1\n');publisher.chmod(0o644)
                if case=='old-atime':
                    import time
                    os.utime(publisher,(1,time.time()))
                if case=='file-mode':publisher.chmod(0o666)
                if case=='hardlink':os.link(publisher,parent/'alias')
                if case=='symlink':publisher.rename(parent/'saved');publisher.symlink_to(parent/'saved')
                if case=='fifo':publisher.unlink();os.mkfifo(publisher,0o644)
                if case=='oversize':
                    with publisher.open('wb') as stream:stream.truncate(2*1024*1024+1)
                if case=='ancestor-link':alias=Path(directory)/'alias';alias.symlink_to(parent);publisher=alias/'publisher.py'
                def trusted(info):
                    fields=list(info);fields[4]=fields[5]=0
                    if stat.S_ISDIR(info.st_mode):fields[0]=stat.S_IFDIR|0o755
                    elif case=='file-owner':fields[4]=1000
                    return os.stat_result(fields)
                def fdstat(fd):
                    info=actual_fstat(fd);value=trusted(info)
                    if case=='ancestor-mode' and stat.S_ISDIR(info.st_mode):
                        fields=list(value);fields[0]=stat.S_IFDIR|0o777;return os.stat_result(fields)
                    return value
                with patch.object(self.api,'PUBLISHER',publisher),patch('os.fstat',fdstat),patch('os.stat',lambda *a,**k:trusted(actual_stat(*a,**k))),patch('os.lstat',lambda *a,**k:trusted(actual_lstat(*a,**k))):
                    if case in ['safe','old-atime']:self.assertEqual(self.api.validate_publisher_source(),b'PUBLIC_SYNTHETIC_SOURCE=1\n')
                    else:
                        with self.assertRaises(ValueError):self.api.validate_publisher_source()

@unittest.skipUnless(os.environ.get('RUN_FIXED_WRAPPER_BASELINE')=='1','Explicit diagnostic baseline only; expected RED')
class ExistingFixedWrapperArchitecture(unittest.TestCase):
    def test_stage_code8_cannot_be_published_by_unchanged_fixed_wrapper(self):
        api=load(Path('/home/dwl/ai-control-app-publisher-wrapper.py'));published=[];events=[]
        api.root_runtime=lambda:None;api.account_identity=lambda name:{'root':(0,0),'dwl':(1000,1000),'ai-panel':(993,987)}[name]
        api.drop_privileges=lambda:events.append('drop')
        def publish(path,**kwargs):
            self.assertEqual(events,['drop']);published.append(kwargs);return 'synthetic-proof'
        api.load_publisher=lambda:types.SimpleNamespace(publish=publish)
        with tempfile.TemporaryDirectory() as directory:
            stage=Path(directory);(stage/'release.json').write_text(json.dumps(metadata()))
            # A future stage does not provide any authority to mutate fixed literals.
            with patch.dict(os.environ,{'STAGE':str(stage),'VERSION_CODE':'8'}),patch('os.chdir'),patch('os.umask'):
                self.assertEqual(api.run(),'synthetic-proof')
        self.assertEqual(published[0]['version_code'],8,'Architectural RED: existing code7 wrapper ignores staged code8')
if __name__=='__main__':unittest.main()
