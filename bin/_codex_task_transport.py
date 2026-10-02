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
