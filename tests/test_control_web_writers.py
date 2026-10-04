"""Actual trusted writers, synthetic private registry; runtime effects forbidden."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_control_web_contract import load_feature, QID, ROOT


class TrustedWriters(unittest.TestCase):
    def setUp(self):
        previous=os.umask(0o077)
        self.addCleanup(os.umask,previous)
        self.tmp=tempfile.TemporaryDirectory(dir='/var/tmp',prefix='web-writers-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.agent=self.root/'agents'/'task-one'
        (self.agent/'questions').mkdir(parents=True,mode=0o700)
        (self.root/'spool'/'task-one').mkdir(parents=True,mode=0o700)
        self.mock=self.root/'mockbin';self.mock.mkdir(mode=0o700)
        # Infrastructure entry points cannot accidentally use the operator runtime.
        for name in ('systemctl','systemd-run','codex','claude','curl','wget'):
            p=self.mock/name
            p.write_text('#!/bin/sh\nexit 99\n');p.chmod(0o700)
        self.env=dict(os.environ,HOME=str(self.root),XDG_RUNTIME_DIR=str(self.root/'runtime'),
            AI_AGENTS_DIR=str(self.agent.parent),AI_AGENT_SPOOL_BASE=str(self.root/'spool'),
            CLAUDE_CONFIG_DIR=str(self.root/'config'),AI_AGENT_ALERT_CMD='/usr/bin/true',
            PATH=str(self.mock)+':'+os.environ['PATH'])
        self.env.pop('AI_AGENTS_REQUIRE_MOUNT',None)
        self.agent.joinpath('spec.yaml').write_text('type: task\nengine: claude\nname: task-one\n')
        self.write('control.json',{'generation':1})
        self.write('state.1.json',{'phase':'waiting'})
        self.write('questions/'+QID+'.json',dict(qid=QID,kind='info',status='open',question='Reply?',envelope_key='fixture-request',asked_at='2026-10-04T00:00:00Z'))
        self.write('done.json',dict(state='requested',finalized=True,envelope_key='fixture-request',commit_sha='a'*40,summary='Synthetic result',pushed_gen8=None))
        mod=load_feature(self,'_control_web_broker.py')
        self.backend=mod.RegistryBackend(str(self.agent.parent),str(ROOT/'bin'),runner=lambda args,**kw:subprocess.run(args,env=self.env,**kw))
        self.gen=hashlib.sha256(('done-gen:fixture-request:'+'a'*40).encode()).hexdigest()[:8]
    def write(self,path,doc):
        (self.agent/path).write_text(json.dumps(doc));(self.agent/path).chmod(0o600)
    def test_actual_info_answer_is_durable_and_first_answer_immutable(self):
        self.assertEqual(self.backend.answer('task-one',QID,'text','First human answer'),{'status':'applied'})
        q=json.loads((self.agent/'questions'/(QID+'.json')).read_text())
        self.assertEqual(q['answer'],'First human answer')
        self.assertEqual(q['answered_by'],'web')
        self.assertTrue(q['event_published_at'])
        self.assertEqual(self.backend.answer('task-one',QID,'text','Second answer'),{'error':'invalid_or_stale'})
        self.assertEqual(json.loads((self.agent/'questions'/(QID+'.json')).read_text())['answer'],'First human answer')
        self.assertTrue(list((self.root/'spool'/'task-one').glob('*.json')))
    def test_actual_saved_pending_recovers_original_without_new_answer(self):
        shutil.rmtree(self.root/'spool'/'task-one')
        self.assertEqual(self.backend.answer('task-one',QID,'text','First durable answer'),{'error':'saved_pending'})
        question=self.backend.snapshot()['tasks'][0]['questions'][0]
        self.assertTrue(question['answered'])
        self.assertTrue(question['pending_delivery'])
        self.assertEqual(question['allowed_decisions'],[])
        (self.root/'spool'/'task-one').mkdir(mode=0o700)
        self.assertEqual(self.backend.answer('task-one',QID,'recover',''),{'status':'already'})
        record=json.loads((self.agent/'questions'/(QID+'.json')).read_text())
        self.assertEqual(record['answer'],'First durable answer')
        self.assertTrue(record['event_published_at'])

    @unittest.skipUnless(shutil.which('yq'),'existing Control writer requires yq')
    def test_actual_verdict_accept_repeat_and_stale(self):
        self.assertEqual(self.backend.verdict('task-one','deadbeef','accept',''),{'error':'stale'})
        self.assertEqual(self.backend.verdict('task-one',self.gen,'accept','First'),{'status':'applied'})
        self.assertEqual(self.backend.verdict('task-one',self.gen,'accept','Second'),{'status':'already'})
        done=json.loads((self.agent/'done.json').read_text())
        self.assertEqual(done['state'],'accepted')
        self.assertEqual(done['verdict_comment'],'First')
