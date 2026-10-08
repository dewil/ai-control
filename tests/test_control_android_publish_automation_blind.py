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
        with patch('os.setgroups',groups),patch('os.setgid',gid),patch('os.setuid',uid),patch('os.getuid',lambda:state['uid']),patch('os.geteuid',lambda:state['uid']),patch('os.getgid',lambda:state['gid']),patch('os.getegid',lambda:state['gid']),patch('os.getgroups',lambda:state['groups']),patch('os.getresuid',lambda:(state['uid'],)*3),patch('os.getresgid',lambda:(state['gid'],)*3):self.api.drop_privileges(1000,1000,987)
        self.assertEqual(events,[('groups',[1000,987]),('gid',1000),('uid',1000)])
    def test_fixed_paths(self):
        self.assertEqual(Path(self.api.STAGE),Path('/home/dwl/ai-control-android-publish-stage'))
        self.assertEqual(Path(self.api.PUBLISHER),Path('/usr/local/lib/ai-control/publish-android-release.py'))
        self.assertEqual(Path(self.api.HELPER),Path('/usr/local/sbin/ai-control-publish-android'))

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
