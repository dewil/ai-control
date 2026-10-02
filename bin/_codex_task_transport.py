"""Sequential NativeTransport for one task; never replies to native approvals.

Uses a private asyncio loop to bound connect, send and receive operations.
No automatic reconnection or retry: lifecycle journals own uncertain effects.
"""
import asyncio
from collections import deque
import json
import math
import time
import uuid

from _codex_task_lifecycle import ProtocolError


class CodexTaskTransport:
    METHODS = frozenset({'thread/read', 'turn/start', 'turn/interrupt'})

    def __init__(self, socket, *, deadline, connector=None,
                 clock=time.monotonic, max_events=256):
        self.clock = clock
        self.ws = None
        self.events = deque()
        self.closed = False
        self.loop = None
        if type(max_events) is not int or max_events < 1:
            raise ValueError('Invalid event queue limit')
        self.max_events = max_events
        self._remaining(deadline)
        if not isinstance(socket, str) or not socket:
            raise ValueError('Invalid socket path')
        if connector is None:
            from websockets.asyncio.client import unix_connect
            connector = unix_connect
        self.loop = asyncio.new_event_loop()
        try:
            async def connect():
                return await connector(socket, uri='ws://localhost',
                                       open_timeout=self._remaining(deadline),
                                       close_timeout=0.1, max_size=16*1024*1024,
                                       max_queue=16)
            self.ws = self._run(connect, deadline)
            self._call('initialize', {'clientInfo': {'name': 'claude_control_task', 'version': '0.1'},
                                     'capabilities': {'experimentalApi': True}}, deadline)
            self._send({'method': 'initialized'}, deadline)
        except Exception:
            self.close()
            raise ProtocolError('Native transport initialization failed') from None

    def _remaining(self, deadline):
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('Invalid operation deadline')
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError('Native operation deadline exceeded')
        return remaining

    def _run(self, factory, deadline):
        timeout = self._remaining(deadline)
        async def bounded():
            return await asyncio.wait_for(factory(), timeout=timeout)
        return self.loop.run_until_complete(bounded())

    def _ready(self, deadline):
        self._remaining(deadline)
        if self.closed:
            raise ProtocolError('Native transport is closed')

    def _send(self, message, deadline):
        raw = json.dumps(message, allow_nan=False)
        self._run(lambda: self.ws.send(raw), deadline)

    def _frame(self, deadline):
        raw = self._run(self.ws.recv, deadline)
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ProtocolError('Invalid native envelope')
        if 'method' in event:
            if (not isinstance(event['method'], str) or not event['method']
                    or not isinstance(event.get('params', {}), dict)
                    or 'result' in event or 'error' in event):
                raise ProtocolError('Invalid native event')
        elif ('id' not in event or ('result' in event) == ('error' in event)):
            raise ProtocolError('Invalid native response')
        return event

    def _call(self, method, params, deadline):
        request_id = str(uuid.uuid4())
        self._send({'id': request_id, 'method': method, 'params': params}, deadline)
        while True:
            event = self._frame(deadline)
            if 'method' in event:
                if len(self.events) >= self.max_events:
                    raise ProtocolError('Native event queue overflow')
                self.events.append(event)
                continue
            if event['id'] != request_id:
                continue
            if 'error' in event:
                raise ProtocolError('Native RPC failed')
            if not isinstance(event['result'], dict):
                raise ProtocolError('Invalid native result')
            return event['result']

    def call(self, method, params, *, deadline):
        self._ready(deadline)
        if method not in self.METHODS or not isinstance(params, dict):
            raise ValueError('Unsupported native request')
        try:
            return self._call(method, params, deadline)
        except Exception:
            self.close()
            raise ProtocolError('Native RPC unavailable') from None

    def receive(self, *, deadline):
        self._ready(deadline)
        if self.events:
            return self.events.popleft()
        try:
            while True:
                event = self._frame(deadline)
                if 'method' in event:
                    return event
        except Exception:
            self.close()
            raise ProtocolError('Native event stream unavailable') from None

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.events.clear()
        if self.loop is None:
            return
        try:
            if self.ws is not None:
                self.loop.run_until_complete(asyncio.wait_for(self.ws.close(), timeout=.1))
        except Exception:
            # A failed close must not leave a socket executing task traffic.
            transport = getattr(self.ws, 'transport', None)
            if transport is not None:
                transport.abort()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()


class CodexTaskRuntimeTransport(CodexTaskTransport):
    """Opt-in captured callbacks; only a trusted caller decides explicit replies.

    Registry tombstones live until close. This sequential client neither fences
    other subscribers nor establishes human consent or task authorization.
    """
    METHODS = CodexTaskTransport.METHODS | frozenset({
        'thread/start', 'thread/resume', 'config/read', 'mcpServerStatus/list'})
    _DYNAMIC = 'item/tool/call'
    _INPUT = 'item/tool/requestUserInput'
    _APPROVALS = frozenset({'item/commandExecution/requestApproval',
                           'item/fileChange/requestApproval',
                           'item/permissions/requestApproval'})
    _CALLBACKS = _APPROVALS | frozenset({_DYNAMIC, _INPUT})

    def __init__(self, socket, *, deadline, connector=None,
                 clock=time.monotonic, max_events=256, max_requests=256):
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError('Invalid callback registry limit')
        self._requests = {}
        self._owner = None
        self.max_requests = max_requests
        super().__init__(socket, deadline=deadline, connector=connector,
                         clock=clock, max_events=max_events)

    @staticmethod
    def _identity(value):
        try:
            return (type(value) is str and bool(value)
                    and len(value.encode('utf-8')) <= 256
                    and all(ord(char) >= 32 and not 127 <= ord(char) <= 159 for char in value))
        except UnicodeError:
            return False

    @classmethod
    def _request_key(cls, value):
        if type(value) is int and -(2**63) <= value < 2**63:
            return (int, value)
        if cls._identity(value):
            return (str, value)
        raise ValueError('Invalid callback identity')

    @staticmethod
    def _plain_json(value):
        # Built-in JSON values only: custom equality/iteration can otherwise
        # validate one permission or identity while serializing another.
        def visit(node):
            kind = type(node)
            if node is None or kind in (str, bool, int, float):
                return
            if kind is list:
                for item in node:
                    visit(item)
                return
            if kind is dict:
                for key, item in node.items():
                    if type(key) is not str:
                        raise ValueError('Invalid callback payload')
                    visit(item)
                return
            raise ValueError('Invalid callback payload')
        try:
            visit(value)
        except RecursionError:
            raise ValueError('Invalid callback payload') from None

    @classmethod
    def _canonical(cls, value):
        cls._plain_json(value)
        try:
            return json.dumps(value, allow_nan=False, ensure_ascii=False,
                              sort_keys=True, separators=(',', ':')).encode('utf-8')
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise ValueError('Invalid callback payload') from None

    def bind_operation(self, thread_id, turn_id):
        if self.closed:
            raise ProtocolError('Native transport is closed')
        if self._owner is not None or not all(map(self._identity, (thread_id, turn_id))):
            raise ValueError('Invalid operation binding')
        self._owner = (thread_id, turn_id)

    def _frame(self, deadline):
        # Strict decoding is opt-in: legacy JSON behavior stays unchanged.
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate native key')
                result[key] = value
            return result

        def invalid_constant(value):
            raise ValueError('Invalid native number')

        def finite_float(value):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError('Invalid native number')
            return number

        raw = self._run(self.ws.recv, deadline)
        event = json.loads(raw, object_pairs_hook=unique_object,
                           parse_constant=invalid_constant, parse_float=finite_float)
        if not isinstance(event, dict):
            raise ProtocolError('Invalid native envelope')
        if 'method' in event:
            if (not isinstance(event['method'], str) or not event['method']
                    or not isinstance(event.get('params', {}), dict)
                    or 'result' in event or 'error' in event):
                raise ProtocolError('Invalid native event')
            self._capture(event)
        elif ('id' not in event or ('result' in event) == ('error' in event)):
            raise ProtocolError('Invalid native response')
        return event

    def _capture(self, event):
        method = event['method']
        params = event.get('params', {})
        if method == 'serverRequest/resolved' and 'id' not in event:
            key = self._request_key(params.get('requestId'))
            if not self._identity(params.get('threadId')):
                raise ValueError('Invalid callback resolution')
            entry = self._requests.get(key)
            if entry is not None:
                if params['threadId'] != entry['params']['threadId']:
                    raise ValueError('Conflicting callback resolution')
                entry['state'] = 'resolved'
            return
        if 'id' not in event:
            return
        # A known ID cannot change method, even into an unsupported family.
        try:
            key = self._request_key(event['id'])
        except ValueError:
            if method in self._CALLBACKS:
                raise
            return
        entry = self._requests.get(key)
        if method not in self._CALLBACKS and entry is None:
            return
        canonical = self._canonical(params)
        if entry is not None:
            if entry['method'] != method or entry['canonical'] != canonical:
                raise ValueError('Conflicting callback replay')
            return
        required = ['threadId', 'turnId']
        required += ['callId', 'tool'] if method == self._DYNAMIC else ['itemId']
        if not all(self._identity(params.get(field)) for field in required):
            raise ValueError('Invalid callback identity')
        if method == self._DYNAMIC:
            if (not isinstance(params.get('arguments'), dict)
                    or (params.get('namespace') is not None
                        and not self._identity(params['namespace']))):
                raise ValueError('Invalid dynamic callback')
        if method == 'item/permissions/requestApproval' and not isinstance(params.get('permissions'), dict):
            raise ValueError('Invalid permissions callback')
        if method == self._INPUT:
            questions = params.get('questions')
            if not isinstance(questions, list):
                raise ValueError('Invalid input callback')
            ids = [q.get('id') if isinstance(q, dict) else None for q in questions]
            if not all(map(self._identity, ids)) or len(set(ids)) != len(ids):
                raise ValueError('Invalid input questions')
        if len(self._requests) >= self.max_requests:
            raise ValueError('Callback registry overflow')
        # Decode canonical bytes to own the entire payload independently of FIFO.
        self._requests[key] = {'id': event['id'], 'method': method,
                               'params': json.loads(canonical),
                               'canonical': canonical, 'state': 'pending'}

    def _pending(self, request_id, method, thread_id, turn_id, identity_name,
                 identity, deadline):
        self._ready(deadline)
        if type(method) is not str or not all(map(self._identity, (thread_id, turn_id, identity))):
            raise ValueError('Invalid callback reply identity')
        entry = self._requests.get(self._request_key(request_id))
        if (entry is None or entry['state'] != 'pending' or entry['method'] != method
                or self._owner != (thread_id, turn_id)
                or (entry['params']['threadId'], entry['params']['turnId']) != self._owner
                or entry['params'].get(identity_name) != identity):
            raise ValueError('Callback reply is not authorized')
        return entry

    def _reply(self, entry, result, deadline):
        encoded = self._canonical(result)
        if len(encoded) > 1024 * 1024:
            raise ValueError('Callback result exceeds limit')
        owned_result = json.loads(encoded)
        # Validation and deadline checks precede may-send; errors here keep alive.
        self._ready(deadline)
        try:
            self._send({'id': entry['id'], 'result': owned_result}, deadline)
            self._remaining(deadline)
        except Exception:
            self.close()
            raise ProtocolError('Native callback delivery uncertain') from None
        entry['state'] = 'answered'

    def reply_dynamic(self, request_id, result, *, thread_id, turn_id,
                      call_id, deadline):
        entry = self._pending(request_id, self._DYNAMIC, thread_id, turn_id,
                              'callId', call_id, deadline)
        self._plain_json(result)
        if (not isinstance(result, dict) or set(result) != {'success', 'contentItems'}
                or type(result['success']) is not bool
                or not isinstance(result['contentItems'], list)
                or not 1 <= len(result['contentItems']) <= 64):
            raise ValueError('Invalid dynamic result')
        for item in result['contentItems']:
            if (not isinstance(item, dict) or set(item) != {'type', 'text'}
                    or item['type'] != 'inputText' or not isinstance(item['text'], str)):
                raise ValueError('Invalid dynamic content')
        self._reply(entry, result, deadline)

    def reply_approval(self, request_id, result, *, method, thread_id,
                       turn_id, item_id, deadline):
        if type(method) is not str or method not in self._APPROVALS:
            raise ValueError('Invalid approval method')
        entry = self._pending(request_id, method, thread_id, turn_id,
                              'itemId', item_id, deadline)
        self._plain_json(result)
        if not isinstance(result, dict):
            raise ValueError('Invalid approval result')
        if method == 'item/permissions/requestApproval':
            if (not {'permissions'} <= set(result) <= {'permissions', 'scope', 'strictAutoReview'}
                    or not isinstance(result['permissions'], dict)
                    or ('scope' in result and result['scope'] != 'turn')
                    or ('strictAutoReview' in result and result['strictAutoReview'] is not None
                        and type(result['strictAutoReview']) is not bool)):
                raise ValueError('Invalid permissions result')
            if (result['permissions'] and self._canonical(result['permissions'])
                    != self._canonical(entry['params']['permissions'])):
                raise ValueError('Unrequested permissions result')
        elif (set(result) != {'decision'}
              or result['decision'] not in ('accept', 'decline', 'cancel')):
            raise ValueError('Invalid approval decision')
        self._reply(entry, result, deadline)

    def reply_user_input(self, request_id, answers, *, thread_id, turn_id,
                         item_id, deadline):
        entry = self._pending(request_id, self._INPUT, thread_id, turn_id,
                              'itemId', item_id, deadline)
        self._plain_json(answers)
        question_ids = {q['id'] for q in entry['params']['questions']}
        if not isinstance(answers, dict) or not answers or not set(answers) <= question_ids:
            raise ValueError('Invalid input answers')
        for answer in answers.values():
            if (not isinstance(answer, dict) or set(answer) != {'answers'}
                    or not isinstance(answer['answers'], list) or len(answer['answers']) > 16):
                raise ValueError('Invalid input answer')
            for value in answer['answers']:
                try:
                    valid = isinstance(value, str) and len(value.encode('utf-8')) <= 8192
                except UnicodeError:
                    valid = False
                if not valid:
                    raise ValueError('Invalid input answer text')
        self._reply(entry, {'answers': answers}, deadline)

    def close(self):
        self._requests.clear()
        self._owner = None
        super().close()
