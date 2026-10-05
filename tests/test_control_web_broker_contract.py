"""Blind registry and writer boundary tests. Fixtures private /var/tmp only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import socket
import threading
import time
import tempfile
import unittest
from test_control_web_contract import load_feature, QID


def canonical_callback(decisions=None):
    return dict(attempt_id='attempt-1',thread_id='thread-1',turn_id='turn-1',item_id='item-1',
        operation_id=QID,task_incarnation='a'*32,generation=1,request_id='request-1',
        method='item/fileChange/requestApproval',status='pending',payload_fingerprint='b'*64,
        changes_digest='c'*64,allowed_decisions=decisions or ['approve','reject'])


# INV-WEB-03 INV-WEB-04 INV-WEB-05 INV-WEB-06
class BrokerContract(unittest.TestCase):
    def setUp(self):
        self.mod = load_feature(self, '_control_web_broker.py')
        previous = os.umask(0o077)
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix='control-web-contract-', dir='/var/tmp')
        finally:
            os.umask(previous)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.registry = self.root/'agents'
        self.agent = self.registry/'task-one'
        self.bin = self.root/'bin'
        self.bin.mkdir(mode=0o700)
        (self.agent/'questions').mkdir(parents=True, mode=0o700)
        self.calls = []
        self.rc, self.stdout = 0, 'applied\n'
        self.timeout = False
        self.write('spec.yaml', {'type':'task','engine':'claude','name':'task-one','workspace':'/synthetic/private/path','secret':'synthetic-oauth-secret'})
        self.write('control.json', {'generation':'g1','secret':'synthetic-oauth-secret'})
        self.write('state.g1.json', {'phase':'waiting','status_line':'Ready'})
        self.write('questions/'+QID+'.json', {'qid':QID,'kind':'info','status':'open','question':'Question','envelope_key':'request-1','asked_at':1})
        self.write('done.json', {'state':'requested','finalized':True,'envelope_key':'request-1','commit_sha':'a'*40,'summary':'Result'})
        self.generation = hashlib.sha256(('done-gen:request-1:'+'a'*40).encode()).hexdigest()[:8]
        self.backend = self.mod.RegistryBackend(str(self.registry), str(self.bin), runner=self.runner)
    def write(self, name, value):
        path = self.agent/name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    def runner(self, args, **kwargs):
        self.calls.append((args,kwargs))
        if self.timeout:
            raise subprocess.TimeoutExpired(args, 1, stderr='synthetic-oauth-secret')
        if self.rc == 0 and Path(args[0]).name == 'ai-agent-answer':
            path = self.agent/'questions'/f'{args[args.index("--qid")+1]}.json'
            record = json.loads(path.read_text())
            if not record.get('answered_at'):
                if '--text' in args:
                    record['answer'] = args[args.index('--text')+1]
                else:
                    record['decision'] = 'approve' if '--approve' in args else 'reject'
                record['answered_at'] = '2026-10-04T00:00:00Z'
                record['answered_by'] = 'web'
            record['event_published_at'] = '2026-10-04T00:00:01Z'
            self.write('questions/'+QID+'.json',record)
        return subprocess.CompletedProcess(args,self.rc,self.stdout,'synthetic-oauth-secret')
    def snapshot(self):
        return self.backend.snapshot()['tasks']
    def unavailable(self):
        result = self.backend.snapshot()
        self.assertTrue(result.get('error') or any(t.get('unavailable') for t in result.get('tasks',[])), result)
        self.assertNotIn('synthetic-oauth-secret',json.dumps(result))
    def test_INV_WEB_05_allowlist_and_generation(self):
        tasks = self.snapshot()
        self.assertEqual(len(tasks),1)
        task = tasks[0]
        self.assertEqual((task['agent'],task['engine'],task['state']),('task-one','claude','waiting'))
        self.assertEqual(task['questions'][0]['qid'],QID)
        self.assertEqual(task['result']['generation'],self.generation)
        encoded = json.dumps(tasks)
        for forbidden in ('synthetic-oauth-secret','/synthetic/private/path','native_callback','envelope_key'):
            self.assertNotIn(forbidden,encoded)
    def test_INV_WEB_05_corrupt_and_oversized_records_visible(self):
        for filename, contents in [('control.json','{'),('done.json','['),('questions/'+QID+'.json','x'*131073)]:
            with self.subTest(filename=filename):
                p = self.agent/filename
                old = p.read_text()
                p.write_text(contents)
                self.unavailable()
                p.write_text(old)
    def test_INV_WEB_05_symlink_record_and_child_never_followed(self):
        outside = self.root/'private.json'
        outside.write_text('{"secret":"synthetic-oauth-secret"}')
        outside.chmod(0o600)
        p = self.agent/'done.json'
        p.unlink()
        p.symlink_to(outside)
        self.unavailable()
        p.unlink()
        (self.registry/'escaped').symlink_to(self.root, target_is_directory=True)
        result = self.backend.snapshot()
        self.assertNotIn('synthetic-oauth-secret',json.dumps(result))
        self.assertFalse(any(t.get('agent')=='escaped' and not t.get('unavailable') for t in result.get('tasks',[])))
    def test_INV_WEB_03_05_reject_bad_identifiers_before_runner(self):
        for agent,qid in [('../outside',QID),('/tmp/x',QID),('task-one','../secret'),('task-one',QID.upper()),('task-one','not-uuid')]:
            if qid == QID.upper():
                qid = 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'
            with self.subTest(agent=agent,qid=qid):
                result = self.backend.answer(agent,qid,'text','hello')
                self.assertIn('error',result)
        for generation in ('DEADBEEF','../../x','deadbee','deadbeeff'):
            self.assertIn('error',self.backend.verdict('task-one',generation,'accept',''))
        self.assertEqual(self.calls,[])
    def test_INV_WEB_04_trusted_writer_exact_argv_and_no_shell(self):
        self.assertEqual(self.backend.answer('task-one',QID,'text','$(touch forbidden)'),{'status':'applied'})
        args,kw = self.calls[-1]
        self.assertEqual(args,[str(self.bin/'ai-agent-answer'),str(self.agent),'--qid',QID,'--text','$(touch forbidden)','--by','web'])
        self.assertFalse(kw.get('shell',False))
        self.assertGreater(kw['timeout'],0)
        self.assertLessEqual(kw['timeout'],120)
        self.assertEqual(self.backend.verdict('task-one',self.generation,'accept','Human comment'),{'status':'applied'})
        self.assertEqual(self.calls[-1][0],[str(self.bin/'ai-agent-run'),'done-verdict',str(self.agent),'--accept','--expect-sha',self.generation,'--comment','Human comment'])
    def test_INV_WEB_04_returncodes_and_timeout_sanitized(self):
        for rc, expected in [(1,'invalid_or_stale'),(2,'invalid_or_stale'),(7,'saved_pending'),(88,'unavailable')]:
            self.rc=rc
            self.assertEqual(self.backend.answer('task-one',QID,'text','hello'),{'error':expected})
        for rc,out,expected in [(0,'already\n',{'status':'already'}),(3,'synthetic-oauth-secret',{'error':'stale'}),(1,'',{'error':'unavailable'}),(2,'',{'error':'invalid_or_stale'})]:
            self.rc,self.stdout=rc,out
            self.assertEqual(self.backend.verdict('task-one',self.generation,'accept',''),expected)
        self.timeout=True
        self.assertEqual(self.backend.verdict('task-one',self.generation,'accept',''),{'error':'unavailable'})
    def test_INV_WEB_06_native_permission_advertised_decisions(self):
        self.write('spec.yaml',{'type':'task','engine':'codex','name':'task-one'})
        self.write('questions/'+QID+'.json',{'qid':QID,'kind':'permission','status':'open','question':'May I?','envelope_key':'request-1','asked_at':1,'engine':'codex','native_callback':canonical_callback(['reject'])})
        self.assertEqual(self.snapshot()[0]['questions'][0]['allowed_decisions'],['reject'])
        self.assertIn('error',self.backend.answer('task-one',QID,'approve',''))
        self.assertEqual(self.calls,[])

    def socket_server(self, uid):
        path = self.root/'broker.sock'
        stop = threading.Event()
        errors = []
        def serve():
            try:
                self.mod.serve_broker(str(path), self.backend, uid, stop_event=stop)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        def cleanup():
            stop.set()
            thread.join(2)
            self.assertFalse(thread.is_alive(), 'broker did not honor stop_event')
        self.addCleanup(cleanup)
        deadline = time.monotonic()+2
        ready = False
        while not errors and time.monotonic()<deadline:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(min(0.1, max(0.001, deadline-time.monotonic())))
                    probe.connect(str(path))
                ready = True
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.01)
        self.assertFalse(errors, str(errors))
        self.assertTrue(ready, 'broker socket did not become connectable')
        self.assertTrue(path.exists(), 'broker socket not created')
        self.assertEqual(path.stat().st_mode & 0o777, 0o660)
        return path
    def request(self, path, payload):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(str(path))
            client.sendall(json.dumps(payload).encode()+b'\n')
            data=b''
            while b'\n' not in data:
                block=client.recv(131073)
                if not block:
                    break
                data+=block
            return json.loads(data)
    def test_INV_WEB_03_socket_peer_refusal_no_writer(self):
        path = self.socket_server(os.getuid()+1)
        result = self.request(path, {'op':'answer','agent':'task-one','qid':QID,'decision':'text','text':'hello'})
        self.assertIn('error',result)
        self.assertEqual(self.calls,[])
    def test_INV_WEB_03_socket_strict_fields_and_roundtrip(self):
        path = self.socket_server(os.getuid())
        for payload in ({'op':'cancel','agent':'task-one'}, {'op':'snapshot','env':{}}, {'op':'answer','agent':'task-one','qid':QID,'decision':'text','text':'hello','executable':'/bin/sh'}):
            self.assertIn('error',self.request(path,payload))
        self.assertEqual(self.calls,[])
        self.assertEqual(self.mod.SocketBackend(str(path)).snapshot()['tasks'][0]['agent'],'task-one')
    def test_INV_WEB_03_socket_never_replaces_regular_file(self):
        path=self.root/'broker.sock'
        path.write_text('synthetic-canary')
        path.chmod(0o600)
        with self.assertRaises((OSError,ValueError,RuntimeError)):
            self.mod.serve_broker(str(path),self.backend,os.getuid(),stop_event=threading.Event())
        self.assertEqual(path.read_text(),'synthetic-canary')

if __name__ == '__main__':
    unittest.main(verbosity=2)
