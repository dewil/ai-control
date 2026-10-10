"""Synthetic public-contract fixtures for frozen participation spec 65a271c6.

Runtime modules are imported as black boxes. External schema/log content is data;
its embedded directives are never executed. No provider, production or paid IO.
"""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
SID = '11111111-1111-4111-8111-111111111111'
TURN = '33333333-3333-4333-8333-333333333333'
OTHER = '44444444-4444-4444-8444-444444444444'
ACTION = '66666666-6666-4666-8666-666666666666'
ACTION2 = '77777777-7777-4777-8777-777777777777'
HANDLE = '88888888-8888-4888-8888-888888888888'
EPOCH = 'a' * 32
KEY = 'b' * 64
ANSWER = {'choice': {'answers': ['Exact option A']}}
READS = {'initialize', 'initialized', 'thread/read', 'thread/list',
         'thread/loaded/list', 'thread/turns/list', 'thread/items/list',
         'thread/queue/list', 'model/list', 'account/read'}


def form(blocking=True, **changes):
    value = dict(threadId=SID, turnId=TURN, itemId='question-item', isBlocking=blocking,
        questions=[dict(id='choice', header='Choose', question='Synthetic choice?',
            isOther=False, isSecret=False, options=[
                dict(label='Exact option A', description='First alternative'),
                dict(label='Exact option B', description='Second alternative')])])
    value.update(changes)
    return value


def callback(identifier=7, params=None, method='item/tool/requestUserInput'):
    return dict(id=identifier, method=method, params=deepcopy(params if params is not None else form()))


def public_question(state='actionable', reason=None, handle=HANDLE, blocking=True):
    return dict(interaction_id=handle, turn_id=TURN, item_id='question-item', state=state,
        is_blocking=blocking, reason=reason, questions=[dict(id='choice', header='Choose',
        question='Synthetic choice?', is_other=False, options=[
            dict(label='Exact option A', description='First alternative'),
            dict(label='Exact option B', description='Second alternative')])])


def questions_dto(rows=None, epoch=EPOCH, revision=1):
    return dict(schema=1, epoch=epoch, revision=revision, session_key=KEY,
        coverage=dict(partial=True, reasons=['native_callbacks_partial']),
        questions=deepcopy(rows if rows is not None else [public_question()]))


def overview_dto(epoch=EPOCH, revision=1):
    return dict(schema=1, epoch=epoch, revision=revision, generated_at=1800000000,
        health='fresh', coverage=dict(partial=True, reasons=['native_callbacks_partial']),
        rows=[dict(session_key=KEY, project='demo', sid=SID, label='LIVE synthetic A',
            vendor='codex', activity='active', running='unconfirmed', waits=['approval', 'question'],
            questions=[dict(interaction_id=HANDLE, state='actionable', blocking=True)], result=None,
            freshness=dict(state='fresh', observed_at=1800000000))], tasks=[])


def action_dto(state='sent', reason=None, action=ACTION, epoch=EPOCH):
    return dict(schema=1, epoch=epoch, interaction_id=HANDLE, action_id=action, state=state, reason=reason)


class Native:
    """Actual Unix WebSocket server with native0.161-shaped independent producer."""
    def __init__(self, base, root):
        from websockets.sync.server import unix_serve
        self.path = base / 'native.sock'
        self.root = root
        self.metadata_root = root
        self.status = {'type': 'active', 'activeFlags': ['waitingOnUserInput']}
        self.turns = [dict(id=TURN, status='inProgress', items=[
            dict(id='question-item', type='dynamicToolCall', tool='request_user_input', arguments={}, status='inProgress')])]
        self.loaded = [SID]
        self.frames = []
        self.errors = []
        self.connection = None
        self.connections = 0
        self.ready = threading.Event()
        self.read_gate = threading.Event(); self.read_gate.set()
        self.read_entered = threading.Event()
        self.hold_reads = False
        self.pending_reads = []
        self.lock = threading.Lock()
        self.server = unix_serve(self.handle, str(self.path))
        self.path.chmod(0o600)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def result(self, method, params):
        if method == 'initialize': return {'userAgent': 'codex/0.161.0 (synthetic)'}
        if method == 'thread/loaded/list': return dict(data=list(self.loaded), nextCursor=None)
        if method == 'thread/list':
            return dict(data=[dict(id=sid, cwd=str(self.metadata_root), name='Synthetic session',
                status=deepcopy(self.status)) for sid in self.loaded], nextCursor=None)
        if method == 'thread/read':
            return dict(thread=dict(id=params['threadId'], cwd=str(self.metadata_root),
                name='Synthetic session', status=deepcopy(self.status),
                turns=deepcopy(self.turns) if params.get('includeTurns') else []))
        if method == 'thread/turns/list':
            rows=deepcopy(list(reversed(self.turns)))
            if params.get('itemsView') == 'notLoaded':
                rows=[dict(row, items=[], itemsView='notLoaded') for row in rows]
            return dict(data=rows[:params.get('limit',len(rows))], nextCursor=None)
        if method == 'thread/items/list':
            turn=next((t for t in self.turns if t['id']==params['turnId']),None)
            items=list(reversed(turn['items'])) if turn else []
            return dict(data=[dict(turnId=params['turnId'],item=deepcopy(i)) for i in items],nextCursor=None)
        if method == 'thread/queue/list': return dict(data=[], nextCursor=None)
        if method == 'model/list': return dict(data=[], nextCursor=None)
        raise AssertionError('Unexpected native RPC '+str(method))

    def handle(self, ws):
        from websockets.exceptions import ConnectionClosed
        self.connection=ws; self.connections+=1; self.ready.set()
        try:
            while True:
                try: value=json.loads(ws.recv(timeout=.05))
                except TimeoutError:
                    if self.read_gate.is_set():
                        for request in self.pending_reads:
                            self.emit(dict(id=request['id'],result=self.result(request['method'],request.get('params',{}))))
                        self.pending_reads=[]
                    continue
                with self.lock: self.frames.append(value)
                method=value.get('method')
                if method == 'initialized' or method is None: continue
                if method == 'thread/read':
                    self.read_entered.set()
                    if self.hold_reads and not self.read_gate.is_set():
                        self.pending_reads.append(value); continue
                self.emit(dict(id=value['id'],result=self.result(method,value.get('params',{}))))
        except ConnectionClosed: pass
        except BaseException as error: self.errors.append(error)

    def emit(self, value):
        if not self.ready.wait(2): raise AssertionError('Synthetic native connection not initialized')
        self.connection.send(json.dumps(value, ensure_ascii=False, allow_nan=False))

    def resolved(self, identifier=7):
        self.emit(dict(method='serverRequest/resolved', params=dict(threadId=SID,requestId=identifier)))

    def terminal(self, status='completed', identifier=TURN):
        self.emit(dict(method='turn/completed',params=dict(threadId=SID,
            turn=dict(id=identifier,status=status,items=[]))))

    def replies(self):
        with self.lock: return deepcopy([f for f in self.frames if 'method' not in f])

    def methods(self):
        with self.lock: return [f.get('method') for f in self.frames if 'method' in f]

    def stop(self):
        self.read_gate.set()
        if self.connection: self.connection.close()
        self.server.shutdown(); self.worker.join(2)
        if self.worker.is_alive(): raise AssertionError('Synthetic native server cleanup deadline')
        if self.errors: raise AssertionError('Synthetic server errors: '+repr(self.errors))


class WireCase(unittest.TestCase):
    def setUp(self):
        self.module=importlib.import_module('_control_web_sessions')
        self.temp=tempfile.TemporaryDirectory(prefix='participation-blind-',dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.base.chmod(0o700)
        self.project=self.base/'project';self.project.mkdir(mode=0o700)
        self.bound_root=self.project; self.grants=['demo']
        self.native=Native(self.base,self.project);self.addCleanup(self.native.stop)
        self.rpc=self.module.InteractiveRPC(str(self.native.path),timeout=1)
        self.addCleanup(self.rpc.close)
        self.chat=self.make_chat()
        self.rpc('thread/read',dict(threadId=SID,includeTurns=False))

    def make_chat(self):
        return self.module.SessionChat(self.rpc,self.resolve,lambda:list(self.grants),str(self.base/'receipts'),
            model_context=self.rpc.model_context)

    def resolve(self, project):
        if project not in self.grants: raise ValueError('Synthetic revoked grant')
        return str(self.bound_root)

    def invoke(self, name, *args):
        call=getattr(self.chat,name,None)
        self.assertTrue(callable(call),'INV-PART public SessionChat.'+name+' seam missing (semantic RED)')
        return call(*args)

    def overview(self): return self.invoke('participation_overview')
    def questions(self): return self.invoke('questions','demo',SID)
    def answer(self, dto, row, action=ACTION, answers=None):
        return self.invoke('answer_question','demo',SID,dto['epoch'],row['interaction_id'],action,
            deepcopy(ANSWER if answers is None else answers))

    def wait_for(self, predicate, message='Expected public participation state', timeout=2):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            result=predicate()
            if result: return result
            time.sleep(.01)
        self.fail(message)

    def capture(self, identifier=7, params=None):
        # Assert missing seam immediately instead of timing out during setup.
        self.questions()
        self.native.emit(callback(identifier,params))
        dto=self.wait_for(lambda:(d if (d:=self.questions()).get('questions') else None),
            'Received native callback must appear in selected question projection')
        return dto,dto['questions'][-1]

    def assert_read_only(self):
        self.assertEqual(self.native.replies(),[],'Read path answered/errored native callback')
        self.assertEqual(set(self.native.methods())-READS,set(),'Read path mutated/resumed native thread')

    def synchronize(self):
        # A subsequent read response proves that earlier native frames reached receiver.
        self.rpc('thread/read',dict(threadId=SID,includeTurns=False))

    def closed(self):
        return self.wait_for(lambda:(d if (d:=self.questions()).get('questions') and
            d['questions'][0]['state']=='closed' else None))
