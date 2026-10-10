"""Frozen65a271c6 synthetic native protocol fixtures; no runtime source oracle."""
from copy import deepcopy
import inspect
import threading
import native_queue_blind_support as q

NEXT='77777777-7777-4777-8777-777777777777'

class Crash(BaseException):pass

class StartRPC(q.QueueRPC):
    def __init__(self,root):
        super().__init__(root)
        self.queue_pages[None]['data']=[q.native_row()]
        self.start_ack={'turn':{'id':q.TURN,'status':'inProgress','items':[],'itemsView':'notLoaded'}}
        self.start_failure=None;self.before_wire=None;self.after_wire=None
        self.entered=threading.Event();self.gate=threading.Event();self.gate.set()
        self.title='Synthetic session'
    def __call__(self,method,params):
        if method=='thread/queue/start':
            self.calls.append((method,deepcopy(params)))
            if self.before_wire:self.before_wire()
            self.entered.set()
            if not self.gate.wait(3):raise TimeoutError('Synthetic blocked ACK')
            if self.after_wire:self.after_wire()
            if self.start_failure:raise self.start_failure
            return deepcopy(self.start_ack)
        result=super().__call__(method,params)
        if method=='thread/read':result['thread']['name']=self.title
        return result

class ModuleCase(q.QueueModuleCase):
    def setUp(self):
        super().setUp();self.rpc=StartRPC(self.project);self.addCleanup(self.rpc.gate.set)
        self.pin_path=self.base/'pins';self.chat=self.new_chat()
    def new_chat(self):
        kwargs=dict(model_context=self.rpc.model_context,model_clock=lambda:100.0)
        if hasattr(self,'pin_path') and 'pin_store' in inspect.signature(self.module.SessionChat).parameters:
            kwargs['pin_store']=str(self.pin_path)
        return self.module.SessionChat(self.rpc,self.resolve,lambda:['demo'],str(self.receipts),**kwargs)
    def start_action(self,action=q.ACTION,qid=q.QID,chat=None):
        return self.invoke('start_queued','demo',q.SID,qid,action,chat=chat)
    def support(self):return self.invoke('queue_start_support','demo',q.SID)
    def pins(self,principal='owner',chat=None):return self.invoke('pins',principal,chat=chat)
    def pin(self,principal='owner',sid=q.SID,chat=None):return self.invoke('pin',principal,'demo',sid,chat=chat)
    def unpin(self,pin_id,principal='owner',chat=None):return self.invoke('unpin',principal,pin_id,chat=chat)
    def wire_starts(self):return self.rpc.calls_for('thread/queue/start')
    def start_result(self,status='started',action=q.ACTION,qid=q.QID,reason=None):
        return dict(status=status,message_id=action,queued_submission_id=qid,turn_id=q.TURN if status=='started' else None,reason=reason)


def pin_item(pin_id=q.MID,project='demo',sid=q.SID,title='Pinned synthetic A',available=True):
    return dict(pin_id=pin_id,project=project if available else None,sid=sid if available else None,
                title=title if available else 'Недоступная сессия',vendor='codex' if available else None,
                available=available,metadata_state='saved' if available else 'unavailable')

class Backend(q.QueueBackend):
    def __init__(self):
        super().__init__();self.pin_value=dict(schema=1,items=[pin_item()]);self.support_value=dict(schema=1,supported=True,reason=None)
        self.start_value=None
    def session_pins(self,principal):self.calls.append(('pins',principal));return deepcopy(self.pin_value)
    def session_pin(self,principal,project,sid):
        self.calls.append(('pin',principal,project,sid));return dict(schema=1,pin_id=q.MID,pinned=True)
    def session_unpin(self,principal,pin_id):
        self.calls.append(('unpin',principal,pin_id));return dict(schema=1,pin_id=pin_id,pinned=False)
    def session_queue_start_support(self,project,sid):self.calls.append(('support',project,sid));return deepcopy(self.support_value)
    def session_queue_start(self,project,sid,qid,action):
        self.calls.append(('start',project,sid,qid,action))
        return deepcopy(self.start_value or dict(status='started',message_id=action,queued_submission_id=qid,turn_id=q.TURN,reason=None))
