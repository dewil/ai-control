#!/usr/bin/env python3
"""Independent black-box BOT4 recovery tests, written from the accepted spec.
INV-BOT-01/02/03/24/26/27/31; INV-TASK-21/24/25/26.
Production bodies are never inspected. Filesystem and trusted writer are real;
only Telegram and spool failure/crash boundaries are injected.
"""
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
import warnings
warnings.filterwarnings("ignore",category=ResourceWarning)
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class StopPoll(BaseException):
    pass

class Recovery(unittest.TestCase):
    def setUp(self):
        warnings.filterwarnings("ignore",category=ResourceWarning)
        old = os.umask(0o077)
        self.addCleanup(os.umask, old)
        self.temp = tempfile.TemporaryDirectory(prefix='bot-answer-', dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        shutil.copytree(ROOT / 'bin', self.bin)
        for directory in (self.bin,*[p for p in self.bin.rglob('*') if p.is_dir()]):
            directory.chmod(0o700)
        self.agent = self.root / 'agents/recovery-fixture'
        for p in (self.root/'home', self.agent/'questions', self.root/'spool'/self.agent.name,
                  self.root/'mockbin'):
            p.mkdir(parents=True, mode=0o700)
        self.effects = self.root/'forbidden-effects'
        for name in ('systemctl', 'systemd-run', 'claude', 'codex', 'curl'):
            p = self.root/'mockbin'/name
            p.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$TEST_EFFECTS"\nexit 99\n')
            p.chmod(0o700)
        self.env = {k:os.environ[k] for k in ('PATH','LANG','TZ') if k in os.environ}
        self.env.update(HOME=str(self.root/'home'), XDG_CONFIG_HOME=str(self.root/'home/config'),
            CODEX_HOME=str(self.root/'codex'), CLAUDE_CONFIG_DIR=str(self.root/'claude'),
            AI_AGENTS_DIR=str(self.agent.parent), AI_AGENT_SPOOL_BASE=str(self.root/'spool'),
            AI_AGENT_TG_SENT_MAP=str(self.root/'sent.json'),
            AI_AGENT_TG_TOKEN='OFFLINE_FIXTURE', AI_AGENT_TG_WHITELIST='1001',
            AI_AGENT_PROBE_CMD='/usr/bin/true', TEST_EFFECTS=str(self.effects),
            PATH=str(self.root/'mockbin')+os.pathsep+os.environ['PATH'])
        self.spool_calls = self.root/'spool-calls.jsonl'
        self.fault = self.root/'fault'
        self.fault.write_text('off')
        # Keep every non-spool operation real. Crash is after real spool commit,
        # before the trusted writer can receive its child result / mark the file.
        real_run = self.bin/'ai-agent-run.real'
        shutil.copy2(self.bin/'ai-agent-run', real_run)
        wrapper = self.bin/'ai-agent-run'
        wrapper.write_text('#!/usr/bin/env python3\nimport os,signal,subprocess,sys\n'
            f'mode=open({str(self.fault)!r}).read().strip()\n'
            'if len(sys.argv)>1 and sys.argv[1]=="spool-put":\n'
            f' with open({str(self.spool_calls)!r},"a") as log: log.write(__import__("json").dumps(sys.argv[1:])+"\\n")\n'
            ' if mode=="fail" or (mode.startswith("fail:") and mode[5:] in " ".join(sys.argv)): sys.exit(7)\n'
            f' rc=subprocess.call([{str(real_run)!r}]+sys.argv[1:])\n'
            ' if mode=="crash" and rc==0: os.kill(os.getppid(),signal.SIGKILL)\n'
            ' sys.exit(rc)\n'
            f'os.execv({str(real_run)!r},[{str(real_run)!r}]+sys.argv[1:])\n')
        wrapper.chmod(0o700)
        self.save(self.agent/'spec.yaml', dict(schema=1,name=self.agent.name,type='event',role='none',
            goal='offline fixture',autonomy='suggest',memory_max_mb=100,
            limits=dict(runs_per_day=100,run_timeout_s=20), source=dict(kind='spool',replay_window_h=72)))
        self.envpatch=patch.dict(os.environ,self.env,clear=True)
        self.envpatch.start(); self.addCleanup(self.envpatch.stop)
        loader=SourceFileLoader('bot_fixture_'+uuid.uuid4().hex,str(self.bin/'ai-agent-tgbot'))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        self.bot=importlib.util.module_from_spec(spec); loader.exec_module(self.bot)
        self.bot.OFFSET_FILE=str(self.root/'offset')
        self.bot.LOG_FILE=str(self.root/'bot.log')
        self.bot.BIN_DIR=str(self.bin)
        self.addCleanup(self.assert_no_external_effects)

    def assert_no_external_effects(self):
        self.assertFalse(self.effects.exists(), 'live/native process boundary invoked')

    def save(self,path,value):
        path.write_text(json.dumps(value)); path.chmod(0o600)

    def question(self,kind='info',saved=False,**changes):
        qid=str(uuid.uuid4())
        q=dict(qid=qid,envelope_key='fixture-event',asked_at='2026-10-01T00:00:00Z',kind=kind,
            question='Choose?',options=['first','second'] if kind=='info' else None,context=None,
            status='open',answer=None,answered_at=None,answered_by=None,decision=None,
            closed_by_envelope=None,reminder=dict(step=3,next_push_at='2099-01-01T00:00:00Z',
                snoozed_until='2099-01-01T00:00:00Z'))
        if saved:q.update(answer='first' if kind=='info' else None,
            decision='reject' if kind=='permission' else None,answered_at='2026-10-02T00:00:00Z',answered_by='original')
        q.update(changes); self.save(self.agent/'questions'/f'{qid}.json',q)
        return qid

    def read(self,qid):return json.loads((self.agent/'questions'/f'{qid}.json').read_text())
    def fields(self,qid):
        q=self.read(qid);return {k:q.get(k) for k in ('answer','decision','answered_at','answered_by')}
    def cli(self,name,*args):
        return subprocess.run([str(self.bin/name),*map(str,args)],env=self.env,text=True,capture_output=True,timeout=15)
    def answer(self,qid,*args):return self.cli('ai-agent-answer',self.agent,'--qid',qid,*args)
    def events(self):return [json.loads(p.read_text()) for p in (self.root/'spool'/self.agent.name).glob('*.json')]
    def one_address(self,qid):
        events=self.events();self.assertEqual(len(events),1,events)
        # spool envelope payload is the public task addressing contract.
        payload=events[0].get('payload',events[0])
        self.assertEqual(payload.get('kind'),'answer');self.assertEqual(payload.get('question_id'),qid)
        self.assertFalse(set(payload).intersection({'text','answer','approve','decision'}),payload)
        self.assertTrue(self.read(qid).get('event_published_at'))
        attempts=[json.loads(line) for line in self.spool_calls.read_text().splitlines()]
        matching=[args for args in attempts if qid in ' '.join(args)]
        self.assertTrue(matching)
        for args in matching:
            self.assertEqual(args[args.index('--id')+1],'ans:'+qid)

    def test_positive_writer_publishes_address_and_completed_is_stale(self):
        q=self.question();r=self.answer(q,'--text','first','--by','original')
        self.assertEqual(r.returncode,0,r.stderr);self.one_address(q)
        original=self.fields(q);self.assertEqual(self.answer(q,'--text','second').returncode,2)
        self.assertEqual(self.fields(q),original)

    def test_first_info_and_permission_survive_spool_failure_and_opposite_retry(self):
        for kind in ('info','permission'):
            with self.subTest(kind=kind):
                q=self.question(kind);self.fault.write_text('fail')
                args=('--text','first') if kind=='info' else ('--reject',)
                r=self.answer(q,*args,'--by','original');self.assertEqual(r.returncode,7,r.stderr)
                original=self.fields(q);self.assertTrue(original['answered_at'])
                self.fault.write_text('off')
                args=('--text','second') if kind=='info' else ('--approve',)
                r=self.answer(q,*args,'--by','replacement');self.assertEqual(r.returncode,0,r.stderr)
                self.assertEqual(self.fields(q),original)
                self.assertTrue(self.read(q).get('event_published_at'))

    def test_recover_is_idempotent_and_preserves_answer_and_reminder(self):
        q=self.question(saved=True);original=self.fields(q);reminder=self.read(q)['reminder']
        r=self.answer(q,'--recover');self.assertEqual(r.returncode,0,r.stderr)
        self.one_address(q);self.assertEqual(self.fields(q),original)
        self.assertEqual(self.read(q)['reminder'],reminder)
        self.assertEqual(self.answer(q,'--recover').returncode,0);self.one_address(q)
        for args in (('--text','replacement'),('--approve',),('--reject',)):
            self.assertEqual(self.answer(q,'--recover',*args).returncode,2)
        self.assertEqual(self.fields(q),original)
        self.register(q);offset,_,_=self.poll([self.update(q)])
        self.assertEqual(offset,42);self.one_address(q)

    def test_recover_rejects_unanswered_missing_corrupt_unsafe_and_closed_noop(self):
        unanswered=self.question();missing=str(uuid.uuid4());corrupt=self.question(saved=True)
        (self.agent/'questions'/f'{corrupt}.json').write_text('{bad')
        for q in (unanswered,missing,corrupt,'../../other'):
            with self.subTest(q=q):self.assertEqual(self.answer(q,'--recover').returncode,2)
        closed=self.question(saved=True,status='closed');before=self.read(closed)
        r=self.answer(closed,'--recover');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.read(closed),before);self.assertEqual(self.events(),[])

    def test_crash_after_spool_then_recovery_deduplicates_stable_id(self):
        q=self.question();self.fault.write_text('crash')
        r=self.answer(q,'--text','first','--by','original');self.assertLess(r.returncode,0,r.stderr)
        original=self.fields(q);self.assertFalse(self.read(q).get('event_published_at'))
        self.assertEqual(len(self.events()),1)
        self.fault.write_text('off');r=self.answer(q,'--recover')
        self.assertEqual(r.returncode,0,r.stderr);self.one_address(q);self.assertEqual(self.fields(q),original)

    def test_concurrent_recovery_and_new_tap_keep_one_original_answer_event(self):
        q=self.question(saved=True);original=self.fields(q)
        cmds=[['--recover'],['--text','replacement','--by','intruder']]*3
        ps=[subprocess.Popen([str(self.bin/'ai-agent-answer'),str(self.agent),'--qid',q,*a],
            env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for a in cmds]
        results=[(p.communicate(timeout=20),p.returncode) for p in ps]
        for args,(_,rc) in zip(cmds,results):
            self.assertIn(rc,(0,) if args==['--recover'] else (0,2),results)
        self.assertEqual(self.fields(q),original);self.one_address(q)

    def test_periodic_recovery_without_alert_due_or_user_retry(self):
        q=self.question(saved=True);original=self.fields(q);reminder=self.read(q)['reminder']
        self.env.pop('AI_AGENT_ALERT_CMD',None)
        r=self.cli('ai-agent-run','question-reminders',self.agent)
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn(f'{q} recovered',r.stdout.splitlines())
        self.one_address(q);self.assertEqual(self.fields(q),original);self.assertEqual(self.read(q)['reminder'],reminder)

    def test_periodic_failure_continues_other_questions_and_next_tick_recovers(self):
        q=self.question(saved=True);other=self.question(saved=True);self.fault.write_text('fail:'+q)
        r=self.cli('ai-agent-run','question-reminders',self.agent)
        self.assertIn(f'{q} fail',r.stdout.splitlines())
        self.assertIn(f'{other} recovered',r.stdout.splitlines())
        self.assertEqual(len(self.events()),1);self.fault.write_text('off')
        r=self.cli('ai-agent-run','question-reminders',self.agent)
        self.assertIn(f'{q} recovered',r.stdout.splitlines())
        self.assertEqual(len(self.events()),2)

    def native_callback(self):
        return dict(operation_id=str(uuid.uuid4()),task_incarnation='a'*32,generation=7,
            attempt_id='fixture',thread_id='thread',turn_id='turn',request_id=31,
            method='item/fileChange/requestApproval',item_id='item',payload_fingerprint='b'*64,
            changes_digest='c'*64,status='pending',allowed_decisions=['reject'])

    def test_native_recovery_validates_saved_decision_and_callback(self):
        allowed=self.question('permission',saved=True,engine='codex',native_callback=self.native_callback())
        forbidden=self.question('permission',saved=True,engine='codex',decision='approve',native_callback=self.native_callback())
        malformed=self.question('permission',saved=True,engine='codex',native_callback={'status':'pending'})
        for q in (forbidden,malformed):
            r=self.answer(q,'--recover');self.assertEqual(r.returncode,2,r.stderr)
        self.assertEqual(self.events(),[])
        r=self.answer(allowed,'--recover');self.assertEqual(r.returncode,0,r.stderr);self.one_address(allowed)
        cb=self.native_callback();cb['status']='answered'
        closed=self.question('permission',saved=True,status='closed',engine='codex',native_callback=cb)
        before=self.read(closed);r=self.answer(closed,'--recover')
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.read(closed),before)
        self.assertEqual(len(self.events()),1)

    def test_native_recovery_rejects_missing_partial_and_mistyped_binding(self):
        # Binding shape comes from test-codex-task-native-answer.py's public
        # native question fixture, independently of the writer implementation.
        invalid=[('missing',None),('partial',dict(status='pending',allowed_decisions=['reject']))]
        for field,value in (('operation_id',[]),('task_incarnation',42),('generation','7'),
                            ('attempt_id',[]),('thread_id',7),('turn_id',False),
                            ('request_id',{}),('method',7),('item_id',[]),
                            ('payload_fingerprint',{}),('changes_digest',42)):
            cb=self.native_callback();cb[field]=value;invalid.append((field,cb))
        for label,callback in invalid:
            with self.subTest(binding=label):
                extras=dict(engine='codex')
                if callback is not None:extras['native_callback']=callback
                q=self.question('permission',saved=True,**extras);before=self.read(q)
                r=self.answer(q,'--recover')
                self.assertEqual(r.returncode,2,r.stderr)
                self.assertEqual(self.read(q),before)
                self.assertEqual(self.events(),[])

    def test_closed_malformed_question_is_not_a_successful_recovery_noop(self):
        cases=[dict(status='closed'),dict(status='closed',kind='info'),
               dict(status='closed',qid=str(uuid.uuid4()),kind='unknown')]
        valid=self.question(saved=True,status='closed');valid_record=self.read(valid)
        for label,change in (('missing qid',None),('wrong qid',str(uuid.uuid4())),
                             ('wrong kind','bogus')):
            record=dict(valid_record)
            if label=='missing qid':record.pop('qid')
            elif label=='wrong qid':record['qid']=change
            else:record['kind']=change
            cases.append(record)
        for field in ('envelope_key','asked_at','question'):
            missing=dict(valid_record);missing.pop(field);cases.append(missing)
            mistyped=dict(valid_record);mistyped[field]=[];cases.append(mistyped)
        for index,record in enumerate(cases):
            with self.subTest(case=index):
                qid=str(uuid.uuid4())
                # Preserve matching identity for the wrong-kind complete case.
                if index>=5:record['qid']=qid
                self.save(self.agent/'questions'/f'{qid}.json',record)
                r=self.answer(qid,'--recover')
                self.assertEqual(r.returncode,2,r.stderr)
                self.assertEqual(self.read(qid),record);self.assertEqual(self.events(),[])
        for qid in (valid,self.question(status='closed')):
            before=self.read(qid);r=self.answer(qid,'--recover')
            self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.read(qid),before)
        self.assertEqual(self.events(),[])

    def test_poll_restart_reads_previously_committed_offset(self):
        q=self.question();self.register(q)
        offset,_,first_requests=self.poll([self.update(q)])
        self.assertEqual(first_requests[0]['offset'],40)
        self.assertEqual(offset,42)
        # A second real mode_poll entry must read disk, without fixture reset.
        offset,_,restart_requests=self.poll([])
        self.assertEqual(restart_requests[0]['offset'],42)
        self.assertEqual(offset,42)
        self.one_address(q)

    def test_closed_native_recovery_rejects_invalid_callback_before_noop(self):
        invalid=[('missing',None),('partial',dict(status='answered',allowed_decisions=['reject']))]
        cb=self.native_callback();cb.update(status='answered',generation='7')
        invalid.append(('mistyped generation',cb))
        for label,callback in invalid:
            with self.subTest(binding=label):
                extras=dict(engine='codex',status='closed')
                if callback is not None:extras['native_callback']=callback
                q=self.question('permission',saved=True,**extras);before=self.read(q)
                r=self.answer(q,'--recover')
                self.assertEqual(r.returncode,2,r.stderr)
                self.assertEqual(self.read(q),before);self.assertEqual(self.events(),[])
        complete=self.native_callback();complete['status']='answered'
        q=self.question('permission',saved=True,status='closed',engine='codex',native_callback=complete)
        before=self.read(q);r=self.answer(q,'--recover')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.read(q),before);self.assertEqual(self.events(),[])

    def register(self,qid,message=10):
        self.bot.sent_map_register(1001,[message],self.agent.name,None,kind='question',qid=qid)
    def update(self,qid,uid=41,message=10,reply=False,from_id=1001):
        if reply:return dict(update_id=uid,message=dict(message_id=100+uid,
            chat=dict(id=1001,type='private'),**{'from':dict(id=from_id)},text='first',
            reply_to_message=dict(message_id=message)))
        return dict(update_id=uid,callback_query=dict(id=str(uid),**{'from':dict(id=from_id)},
            message=dict(chat=dict(id=1001,type='private'),message_id=message),data=f'q:{qid}:0'))

    def poll(self,updates,writer_fault=None,spinner_fail=False):
        offset=Path(self.bot.OFFSET_FILE)
        if not offset.exists():offset.write_text('40')
        calls=[];requests=[]
        def api(token,proxy,method,http_timeout=30,**kw):
            calls.append((method,kw))
            if method=='answerCallbackQuery' and spinner_fail:raise OSError('offline spinner failure')
            if method=='getUpdates':
                requests.append(kw)
                if len(requests)>1:raise StopPoll()
                return dict(ok=True,result=updates)
            return dict(ok=True,result=dict(message_id=500))
        real_run=subprocess.run
        def run(args,**kw):
            if Path(str(args[0])).name=='ai-agent-answer' and writer_fault:
                if writer_fault=='timeout':raise subprocess.TimeoutExpired(args,1)
                if writer_fault=='oserror':raise OSError('offline injected I/O failure')
                if writer_fault=='validation':return subprocess.CompletedProcess(args,2,'','offline terminal validation')
                if writer_fault=='unknown':return subprocess.CompletedProcess(args,23,'','offline unknown failure')
            return real_run(args,**kw)
        with patch.object(self.bot,'api',api),patch.object(self.bot.time,'sleep',lambda _:None),patch.object(self.bot.subprocess,'run',run):
            with self.assertRaises(StopPoll):self.bot.mode_poll()
        return int(offset.read_text()),calls,requests

    def test_poll_positive_control_real_writer_commits_batch(self):
        q=self.question();other=self.question();self.register(q);self.register(other,11)
        offset,calls,_=self.poll([self.update(q),self.update(other,42,11)])
        self.assertEqual(offset,43);self.assertTrue(self.read(q)['answered_at']);self.assertTrue(self.read(other)['answered_at'])
        self.assertEqual(sum(m=='answerCallbackQuery' for m,_ in calls),2)

    def test_poll_callback_and_reply_transient_preserve_offset_and_stop_batch(self):
        for reply in (False,True):
            for fault in ('spool','timeout','oserror','unknown'):
                with self.subTest(reply=reply,fault=fault):
                    Path(self.bot.OFFSET_FILE).write_text('40')
                    q=self.question();other=self.question();self.register(q);self.register(other,11)
                    self.fault.write_text('fail' if fault=='spool' else 'off')
                    offset,calls,requests=self.poll([self.update(q,reply=reply),self.update(other,42,11)],
                        None if fault=='spool' else fault)
                    self.assertEqual(offset,40,'transient writer failure acknowledged Telegram update')
                    self.assertIsNone(self.read(other)['answered_at'],'later update processed before failed update')
                    self.assertEqual(requests[1]['offset'],40)
                    if not reply:self.assertTrue(any(m=='answerCallbackQuery' for m,_ in calls))
                    self.fault.write_text('off')
                    offset,_,redelivery_requests=self.poll([self.update(q,reply=reply),self.update(other,42,11)])
                    self.assertEqual(redelivery_requests[0]['offset'],40)
                    self.assertEqual(offset,43);self.assertTrue(self.read(q).get('event_published_at'))
                    self.assertEqual(sum(e.get('payload',e).get('question_id')==q for e in self.events()),1)

    def test_poll_stale_unauthorized_poison_are_terminal_and_spinner_is_cleared(self):
        stale=self.question();self.answer(stale,'--text','first');self.register(stale)
        unauthorized=self.question();self.register(unauthorized,11)
        good=self.question();self.register(good,12)
        batch=[self.update(stale),self.update(unauthorized,42,11,from_id=9999),
               dict(update_id=43,message=['poison']),self.update(good,44,12)]
        offset,calls,_=self.poll(batch)
        self.assertEqual(offset,45);self.assertIsNone(self.read(unauthorized)['answered_at'])
        self.assertTrue(self.read(good)['answered_at']);self.assertTrue(any(m=='answerCallbackQuery' for m,_ in calls))

    def test_poll_terminal_writer_validation_commits_without_direct_answer_write(self):
        q=self.question();self.register(q);before=self.read(q)
        offset,_,_=self.poll([self.update(q)],'validation')
        self.assertEqual(offset,42);self.assertEqual(self.read(q),before);self.assertEqual(self.events(),[])

    def test_saved_retry_preserves_original_independent_of_error_classification(self):
        for kind in ('info','permission'):
            with self.subTest(kind=kind):
                q=self.question(kind,saved=True);original=self.fields(q)
                args=('--text','replacement') if kind=='info' else ('--approve',)
                r=self.answer(q,*args,'--by','intruder')
                self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.fields(q),original)

    def test_recovery_spool_failure_returns_retryable_and_preserves_saved_answer(self):
        q=self.question(saved=True);before=self.read(q);self.fault.write_text('fail')
        r=self.answer(q,'--recover');self.assertEqual(r.returncode,7,r.stderr)
        self.assertEqual(self.read(q),before);self.assertEqual(self.events(),[])

    def test_spinner_api_error_still_commits_real_answer(self):
        q=self.question();self.register(q)
        offset,calls,_=self.poll([self.update(q)],spinner_fail=True)
        self.assertEqual(offset,42);self.one_address(q)
        self.assertTrue(any(method=='answerCallbackQuery' for method,_ in calls))

    def test_permission_reply_is_terminal_without_writing_decision(self):
        q=self.question('permission');self.register(q)
        offset,_,_=self.poll([self.update(q,reply=True)])
        self.assertEqual(offset,42);self.assertIsNone(self.read(q)['answered_at']);self.assertEqual(self.events(),[])

if __name__=='__main__':unittest.main(verbosity=2)
