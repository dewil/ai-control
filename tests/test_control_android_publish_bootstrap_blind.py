"""INV-APKDEP-02: one-time bootstrap fixed scope, no real installation or root calls."""
import hashlib,importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
BUILDER=ROOT/'deployment/build-android-publish-bootstrap.py'
HELPER=Path('/usr/local/sbin/ai-control-publish-android')
PUBLISHER=Path('/usr/local/lib/ai-control/publish-android-release.py')
SUDOERS=Path('/etc/sudoers.d/ai-control-android-publish')
RULE=b'dwl ALL=(root) NOPASSWD: /usr/local/sbin/ai-control-publish-android ""\n'
@unittest.skipUnless(BUILDER.exists(),'Future bootstrap builder absent; not meaningful RED')
class BootstrapContract(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('blind_bootstrap_builder',BUILDER);self.builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.builder)
        self.helper=b'PUBLIC_SYNTHETIC_HELPER=1\n';self.publisher=b'PUBLIC_SYNTHETIC_PUBLISHER=1\n'
        self.packet=self.builder.build_packet(self.helper,self.publisher)
        self.assertIsInstance(self.packet,bytes)
        self.api=types.ModuleType('blind_bootstrap_packet');self.api.__file__='<synthetic-packet>'
        exec(compile(self.packet,'<synthetic-packet>','exec'),self.api.__dict__)
    def fixture(self,refuse=None):
        events=[];installed={}
        def root():events.append('root')
        def existing(path,raw,mode):
            events.append(('validate',Path(path),raw,mode))
            if refuse=='existing':raise ValueError('Synthetic unknown collision')
        def sudoers(candidate):
            events.append('visudo')
            if refuse=='visudo':raise ValueError('Synthetic invalid sudoers')
        def install(path,raw,mode):
            events.append(('install',Path(path),raw,mode))
            if refuse=='publisher-install' and Path(path)==PUBLISHER:raise OSError('Synthetic install failure')
            installed[Path(path)]=(raw,mode)
        for name,value in [('root_runtime',root),('validate_existing',existing),('validate_sudoers',sudoers),('atomic_install',install)]:
            p=patch.object(self.api,name,value);p.start();self.addCleanup(p.stop)
        return events,installed
    def test_fixed_targets_and_embedded_checksums(self):
        self.assertEqual(Path(self.api.HELPER),HELPER);self.assertEqual(Path(self.api.PUBLISHER),PUBLISHER);self.assertEqual(Path(self.api.SUDOERS),SUDOERS)
        for raw in [self.helper,self.publisher]:self.assertIn(hashlib.sha256(raw).hexdigest().encode(),self.packet)
        self.assertNotEqual(self.packet,self.builder.build_packet(self.helper+b'#different\n',self.publisher))
    def test_all_validation_before_writes_exact_three_leaves_sudoers_last(self):
        events,installed=self.fixture();self.api.bootstrap()
        writes=[v for v in events if isinstance(v,tuple) and v[0]=='install']
        self.assertEqual(writes,[('install',HELPER,self.helper,0o755),('install',PUBLISHER,self.publisher,0o644),('install',SUDOERS,RULE,0o440)])
        first=events.index(writes[0]);self.assertLess(events.index('visudo'),first)
        checks=[v for v in events if isinstance(v,tuple) and v[0]=='validate']
        self.assertEqual({v[1] for v in checks},{HELPER,PUBLISHER,SUDOERS})
        self.assertTrue(all(events.index(v)<first for v in checks))
        self.assertEqual(set(installed),{HELPER,PUBLISHER,SUDOERS})
    def test_validation_failure_no_activation_or_other_writes(self):
        for refuse in ['existing','visudo']:
            with self.subTest(refuse=refuse):
                events,installed=self.fixture(refuse)
                with self.assertRaises((ValueError,OSError)):self.api.bootstrap()
                self.assertEqual(installed,{})
    def test_partial_exact_files_inert_until_sudoers_activation_retryable(self):
        events,installed=self.fixture('publisher-install')
        with self.assertRaises((ValueError,OSError)):self.api.bootstrap()
        self.assertNotIn(SUDOERS,installed)
        self.assertEqual(installed,{HELPER:(self.helper,0o755)})
        events,installed=self.fixture();self.api.bootstrap();self.assertEqual(installed[SUDOERS],(RULE,0o440))
    def test_existing_exact_root_file_old_access_time_is_valid(self):
        import os,stat,tempfile,time
        actual_fstat=os.fstat;actual_stat=os.stat;actual_lstat=os.lstat
        def trusted(info):
            fields=list(info);fields[4]=fields[5]=0
            if stat.S_ISDIR(info.st_mode):fields[0]=stat.S_IFDIR|0o755
            return os.stat_result(fields)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'exact.py';path.write_bytes(self.publisher);path.chmod(0o644);os.utime(path,(1,time.time()))
            with patch('os.fstat',lambda fd:trusted(actual_fstat(fd))),patch('os.stat',lambda *a,**k:trusted(actual_stat(*a,**k))),patch('os.lstat',lambda *a,**k:trusted(actual_lstat(*a,**k))):
                self.api.validate_existing(path,self.publisher,0o644)
    def test_generated_runtime_noargs_isolated_root_refusal(self):
        for isolated,uid,euid,argv in [(0,0,0,['packet']),(1,1000,1000,['packet']),(1,0,1000,['packet']),(1,0,0,['packet','argument'])]:
            with self.subTest(argv=argv,isolated=isolated,uid=uid,euid=euid),patch.object(sys,'flags',types.SimpleNamespace(isolated=isolated)),patch.object(sys,'argv',argv),patch('os.getuid',return_value=uid),patch('os.geteuid',return_value=euid):
                with self.assertRaises(ValueError):self.api.root_runtime()
if __name__=='__main__':unittest.main()
