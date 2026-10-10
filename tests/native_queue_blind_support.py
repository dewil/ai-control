"""Frozen queue fixtures from a110af0 + reviewed native0.161 public schemas.

No implementation source inspection. Everything below is synthetic/local.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bin'))
from test_control_web_session_chat_contract import RPC, SID, MID, OTHER, TURN, feature, turn

ACTION='66666666-6666-4666-8666-666666666666'
TEXT='Synthetic immutable queue payload'
QID='native-submission-A'
CONTEXT=dict(schema=1,vendor='codex',context_kind='legacy_unbound',context_id='a'*64,
             transport_generation=3,context_generation=7,native_version='0.161.0')


def native_row(qid=QID,mid=MID,text=TEXT):
    return dict(id=qid,clientUserMessageId=mid,input=[dict(type='text',text=text)])


def public_row(qid=QID,mid=MID,text=TEXT):
    return dict(queued_submission_id=qid,message_id=mid,text=text,state='queued')


def queue_dto(rows=None,partial=False):
    return dict(schema=1,vendor='codex',supported=True,reason=None,
                rows=deepcopy(rows if rows is not None else [public_row()]),partial=partial,send_now_supported=False)


class QueueRPC(RPC):
    def __init__(self,root):
        super().__init__(root)
        self.context=dict(CONTEXT);self.fenced_calls=[]
        self.queue_pages={None:dict(data=[],nextCursor=None)}
        self.add_error=None;self.delete_error=None;self.deleted=True
        self.before_add=None;self.before_delete=None;self.after_queue=None
        self.add_entered=threading.Event();self.add_gate=threading.Event();self.add_gate.set()

    def model_context(self):return dict(self.context)
    def receipt_context(self):return {key:self.context[key] for key in ['schema','vendor','context_kind','context_id']}
    def call_in_generation(self,method,params,*,transport_generation,context_generation,timeout=None):
        self.fenced_calls.append((method,deepcopy(params),transport_generation,context_generation))
        if (transport_generation,context_generation)!=(self.context['transport_generation'],self.context['context_generation']):
            raise RuntimeError('Synthetic stale generation')
        return self(method,params)
    def __call__(self,method,params):
        if not method.startswith('thread/queue/'):
            return super().__call__(method,params)
        self.calls.append((method,deepcopy(params)))
        if method=='thread/queue/list':
            value=self.queue_pages[params.get('cursor')]
            if isinstance(value,BaseException):raise value
            result=deepcopy(value)
            if self.after_queue:self.after_queue()
            return result
        if method=='thread/queue/add':
            if self.before_add:self.before_add()
            self.add_entered.set()
            if not self.add_gate.wait(3):raise TimeoutError('Synthetic bounded add timeout')
            row=dict(id=QID,clientUserMessageId=params['clientUserMessageId'],input=deepcopy(params['input']))
            self.queue_pages[None]['data'].append(row)
            if self.add_error:raise self.add_error
            return dict(queuedSubmission=row)
        if method=='thread/queue/delete':
            if self.before_delete:self.before_delete()
            if self.deleted:
                for value in self.queue_pages.values():
                    if isinstance(value,dict):value['data']=[row for row in value['data'] if row['id']!=params['queuedSubmissionId']]
            if self.delete_error:raise self.delete_error
            return dict(deleted=self.deleted)
        raise AssertionError('Core must not dispatch native operation '+method)
    def methods(self):return [method for method,_ in self.calls]
    def calls_for(self,method):return [params for name,params in self.calls if name==method]
    def history_message(self,mid=MID,text=TEXT):
        value=turn(client_id=mid)
        value['items'][-1]['content'][0]['text']=text
        self.pages={None:dict(data=[value],nextCursor=None)}


class QueueModuleCase(unittest.TestCase):
    def setUp(self):
        self.module=feature(self,'_control_web_sessions')
        self.temp=tempfile.TemporaryDirectory(prefix='native-queue-blind-',dir='/var/tmp');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.base.chmod(0o700)
        self.project=self.base/'project';self.project.mkdir(mode=0o700)
        self.receipts=self.base/'receipts';self.rpc=QueueRPC(self.project)
        self.addCleanup(self.rpc.add_gate.set)
        self.bound_root=self.project
        self.chat=self.new_chat()
    def resolve(self,project):
        if project!='demo':raise ValueError('Synthetic invalid alias')
        return str(self.bound_root)
    def new_chat(self):
        return self.module.SessionChat(self.rpc,self.resolve,lambda:['demo'],str(self.receipts),
            model_context=self.rpc.model_context,model_clock=lambda:100.0)
    def invoke(self,name,*args,chat=None,**kwargs):
        target=getattr(chat or self.chat,name,None)
        self.assertTrue(callable(target),f'INV-SQUEUE public SessionChat.{name} seam missing (interim RED)')
        return target(*args,**kwargs)
    def queue(self):return self.invoke('queue','demo',SID)
    def enqueue(self,mid=MID,text=TEXT,**kwargs):return self.invoke('enqueue','demo',SID,mid,text,**kwargs)
    def cancel(self,qid=QID,action=ACTION):return self.invoke('cancel_queued','demo',SID,qid,action)
    def mutation_methods(self):return [m for m in self.rpc.methods() if m in ['thread/queue/add','thread/queue/delete','thread/queue/start','turn/start','turn/steer']]
    def records(self):
        return [p for p in self.receipts.rglob('*.json') if p.is_file()] if self.receipts.exists() else []
    def assert_reservation(self,identifier):
        files=self.records()
        self.assertTrue(files,'Immutable digest receipt must exist before native mutation')
        self.assertTrue(any(identifier in p.read_text() for p in files),'Mutation UUID absent from durable intent')
        for path in files:
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertNotIn(TEXT,path.read_text(),'Queue core may persist digest, never pending plaintext')


class QueueBackend:
    """Public broker/HTTP DTO backend; no private native implementation."""
    def __init__(self):self.calls=[];self.value=queue_dto();self.enqueue_status='queued';self.cancel_status='cancelled'
    def snapshot(self):return dict(tasks=[])
    def session_queue(self,project,sid):self.calls.append(('queue',project,sid));return deepcopy(self.value)
    def session_enqueue(self,project,sid,message_id,text,selection=None):
        self.calls.append(('enqueue',project,sid,message_id,text,deepcopy(selection)))
        return dict(status=self.enqueue_status,message_id=message_id,queued_submission_id=QID)
    def session_queue_cancel(self,project,sid,qid,action_id):
        self.calls.append(('cancel',project,sid,qid,action_id))
        return dict(status=self.cancel_status,message_id=action_id,queued_submission_id=qid)
    def session_send_status(self,project,sid,mid):return dict(status='queued',message_id=mid,queued_submission_id=QID)
