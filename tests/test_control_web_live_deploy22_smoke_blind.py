"""INV-DEPLOY-23/25 unprivileged offline API/bytecode probes of tracked wheel.

No production interpreter/identity is executed; closed executable mapping is explicit.
"""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import zipfile
import deploy22_blind_support as s

CODE_SHA='70b31a6b98b049a0a3a6eba2af77f0732a2fcd856d232c5f86928b9b642a2189'
PRODUCTION_SOURCE='/opt/ai-control-web/venv/lib/python3.12/site-packages/nats/__init__.py'
UID_ASSERT='assert os.getuid()==1000 and os.geteuid()==1000 and os.getgid()==1000 and os.getegid()==1000'

class OwnerImportAdvisoryBlind(s.BootstrapFixture):
    def setUp(self):self.prepare()
    def inventory(self):
        return {str(p.relative_to(self.site)):(s.sha(p.read_bytes()),p.stat().st_mode&0o777) for p in self.site.rglob('*') if p.is_file()}
    def unpack_data(self):
        with zipfile.ZipFile(s.WHEEL) as archive:
            for row in s.rows():self.write(self.site/row['path'],archive.read(row['path']),0o644)
    def advisory(self):
        # Explicit precondition: the actual probe always runs as this unprivileged
        # test process, never as the synthetic root identity used for bootstrap IO.
        self.assertNotEqual(os.getuid(),0,'PUBLIC-SEAM PREREQUISITE: advisory requires unprivileged test runner')
        self.assertEqual(s.sha(self.op.OWNER_IMPORT_CODE.encode()),CODE_SHA)
        original=self.op.OWNER_IMPORT_CODE;source=str(self.site/'nats/__init__.py')
        guard=f'assert os.getuid()=={os.getuid()} and os.geteuid()=={os.geteuid()} and os.getgid()=={os.getgid()} and os.getegid()=={os.getegid()}'
        self.assertEqual(original.count(UID_ASSERT),1);self.assertEqual(original.count(PRODUCTION_SOURCE),1)
        adapted=original.replace(UID_ASSERT,guard).replace(PRODUCTION_SOURCE,source)
        # Only the explicitly allowed UID/source-path adaptations; the complete
        # normalized production predicates/import/socket guard remain identical.
        normalized=adapted.replace(guard,UID_ASSERT).replace(source,PRODUCTION_SOURCE)
        self.assertEqual(ast.dump(ast.parse(normalized)),ast.dump(ast.parse(original)))
        code='import sys\nsys.path.insert(0,'+repr(str(self.site))+')\n'+adapted
        result=subprocess.run([sys.executable,'-I','-B','-c',code],env={},cwd='/',capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,'Offline advisory failed; child output intentionally omitted')
        self.assertEqual(result.stderr,b'');self.assertLessEqual(len(result.stdout),4096)
        return json.loads(result.stdout)

    def test_exact_unpacked_wheel_four_API_predicates_no_network_no_bytecode(self):
        self.unpack_data();before=self.inventory();value=self.advisory()
        self.assertEqual(value['version'],'2.9.0');self.assertEqual(value['schema'],1)
        self.assertEqual(value['network_calls'],0);self.assertEqual(value['source_file'],str(self.site/'nats/__init__.py'))
        for name in ('connect_api','client_api','jetstream_api','consumer_config_api'):self.assertIs(value[name],True)
        self.assertEqual(self.inventory(),before);self.assertEqual(len(before),29)

    def test_missing_API_counterexample_fails_advisory_predicate_before_any_install(self):
        self.unpack_data();path=self.site/'nats/js/client.py'
        path.write_bytes(path.read_bytes()+b'\nJetStreamContext.stream_info = None\n')
        before=self.inventory();value=self.advisory()
        self.assertIs(value['jetstream_api'],False);self.assertEqual(value['network_calls'],0)
        self.assertEqual(self.inventory(),before);self.assertEqual(self.trace,[])

    def test_captured_owner_argv_B_flag_real_probe_and_29file_inventory_unchanged(self):
        self.invoke();captured=[row for row in self.trace if row['argv'][0]=='/usr/bin/setpriv']
        self.assertEqual(len(captured),1);call=captured[0];before=self.inventory()
        self.assertEqual(call['argv'][:10],['/usr/bin/setpriv','--reuid=1000','--regid=1000','--clear-groups','--no-new-privs','--',
            '/opt/ai-control-web/venv/bin/python','-I','-B','-c'])
        self.assertEqual(call['argv'][10],self.op.OWNER_IMPORT_CODE);self.assertEqual((call['env'],call['cwd'],call['timeout']),({},'/',10))
        probe='import json,os,sys; print(json.dumps({"dont_write_bytecode":sys.dont_write_bytecode,"uid":os.getuid()}))'
        synthetic_argv=call['argv'][:10]+[probe]
        def synthetic_uid_launcher(argv,*,env,cwd,timeout):
            # Public fixed launcher/interpreter paths are identity emulations in
            # this fixture. Map only their execution to the existing local Python;
            # preserve captured -I/-B/-c/empty-env/cwd. No setpriv/root/host venv.
            self.assertEqual(argv[:10],call['argv'][:10]);self.assertNotEqual(os.getuid(),0)
            return subprocess.run([sys.executable,*argv[7:]],env=env,cwd=cwd,timeout=timeout,capture_output=True)
        for failed in (False,True):
            with self.subTest(failed_child=failed):
                injected_argv=synthetic_argv[:-1]+[probe+';sys.exit('+str(int(failed))+')']
                result=synthetic_uid_launcher(injected_argv,env=call['env'],cwd=call['cwd'],timeout=call['timeout'])
                self.assertEqual(result.returncode,int(failed));self.assertEqual(result.stderr,b'')
                value=json.loads(result.stdout);self.assertIs(value['dont_write_bytecode'],True);self.assertEqual(value['uid'],os.getuid())
                self.assertEqual(self.inventory(),before);self.assertEqual(len(before),29)
