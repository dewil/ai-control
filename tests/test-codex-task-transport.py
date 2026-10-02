"""Offline acceptance for FR-CXTASK-TRANSPORT-01..05."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))


class Socket:
    def __init__(self):
        self.sent = []
        self.frames = []
        self.closed = False
        self.events = []
        self.error = None
        self.slow_send = False

    async def send(self, raw):
        if self.slow_send:
            await asyncio.sleep(1)
        request = json.loads(raw)
        self.sent.append(request)
        if 'id' in request:
            self.frames.extend(self.events)
            self.events = []
            self.frames.append(json.dumps({'id': request['id'], **(
                {'error': self.error} if self.error else {'result': {'ok': True}})}))

    async def recv(self):
        if not self.frames:
            await asyncio.sleep(1)
        return self.frames.pop(0)

    async def close(self):
        self.closed = True


class Tests(unittest.TestCase):
    def client(self, **kwargs):
        module = importlib.import_module('_codex_task_transport')
        ws = Socket()
        async def connect(path, **options):
            self.assertEqual(path, '/fake.sock')
            return ws
        client = module.CodexTaskTransport('/fake.sock', deadline=time.monotonic()+2,
                                           connector=connect, **kwargs)
        self.addCleanup(client.close)
        return client, ws

    def test_handshake_and_allowlist_FR_CXTASK_TRANSPORT_01(self):
        c, ws = self.client()
        self.assertEqual([x['method'] for x in ws.sent], ['initialize', 'initialized'])
        self.assertTrue(ws.sent[0]['params']['capabilities']['experimentalApi'])
        params = {'threadId': 'task', 'input': [{'type': 'text', 'text': 'private'}]}
        self.assertEqual(c.call('turn/start', params, deadline=time.monotonic()+2), {'ok': True})
        self.assertEqual(ws.sent[-1]['params'], params)
        with self.assertRaises(Exception):
            c.call('thread/start', {}, deadline=time.monotonic()+2)
        self.assertEqual(len(ws.sent), 3)

    def test_fifo_and_foreign_response_FR_CXTASK_TRANSPORT_02(self):
        c, ws = self.client()
        events = [{'id': 'approval', 'method': 'unknown/requestApproval', 'params': {'threadId': 'foreign'}},
                  {'method': 'turn/completed', 'params': {'threadId': 'task'}}]
        ws.events = [json.dumps({'id': 'foreign', 'result': {'wrong': True}})] + [json.dumps(e) for e in events]
        self.assertEqual(c.call('thread/read', {}, deadline=time.monotonic()+2), {'ok': True})
        self.assertEqual([c.receive(deadline=time.monotonic()+2) for _ in events], events)
        self.assertFalse(any('result' in x or 'error' in x for x in ws.sent))

    def test_invalid_deadlines_no_send_FR_CXTASK_TRANSPORT_03(self):
        c, ws = self.client()
        for deadline in (time.monotonic()-1, float('nan'), float('inf'), True, 'bad'):
            with self.assertRaises(Exception):
                c.call('turn/start', {}, deadline=deadline)
        self.assertEqual(len(ws.sent), 2)
        self.assertEqual(c.call('thread/read', {}, deadline=time.monotonic()+2), {'ok': True})

    def test_send_timeout_FR_CXTASK_TRANSPORT_03(self):
        c, ws = self.client()
        ws.slow_send = True
        before = time.monotonic()
        with self.assertRaises(Exception):
            c.call('turn/start', {}, deadline=before+.02)
        self.assertLess(time.monotonic()-before, .5)
        self.assertTrue(ws.closed)
        self.assertEqual(len(ws.sent), 2)

    def test_bad_frames_close_without_disclosure_FR_CXTASK_TRANSPORT_04(self):
        for frame in ('private secret', '[]', '{}', '{"id":"x","method":null}',
                      '{"method":"turn/completed","params":[]}'):
            with self.subTest(frame=frame):
                c, ws = self.client()
                ws.events = [frame]
                with self.assertRaises(Exception) as error:
                    c.call('thread/read', {}, deadline=time.monotonic()+2)
                self.assertNotIn(frame, str(error.exception))
                self.assertTrue(ws.closed)
                with self.assertRaises(Exception):
                    c.receive(deadline=time.monotonic()+2)
                self.assertEqual(len(ws.sent), 3)

    def test_rpc_error_and_overflow_FR_CXTASK_TRANSPORT_04(self):
        c, ws = self.client(max_events=1)
        ws.events = [json.dumps({'method': 'event', 'params': {}})] * 2
        with self.assertRaises(Exception):
            c.call('thread/read', {}, deadline=time.monotonic()+2)
        self.assertTrue(ws.closed)

    def test_lifecycle_approval_and_interrupt_FR_CXTASK_TRANSPORT_05(self):
        from _codex_task_lifecycle import CodexTaskLifecycle, TaskThread
        module = importlib.import_module('_codex_task_transport')
        with tempfile.TemporaryDirectory() as root:
            cwd = Path(root) / 'work'
            cwd.mkdir()
            sid = str(uuid4())
            thread = {'id': sid, 'cwd': str(cwd), 'ephemeral': False,
                      'path': '/native/rollout.jsonl', 'status': {'type': 'idle'},
                      'turns': [{'id': 'baseline', 'status': 'completed', 'items': [
                          {'type': 'agentMessage', 'text': 'ready', 'phase': 'final'}]}]}
            ws = Socket()
            async def send(raw):
                request = json.loads(raw)
                ws.sent.append(request)
                if 'id' not in request:
                    return
                method, params = request['method'], request['params']
                result = {}
                if method == 'thread/read':
                    result = {'thread': thread}
                elif method == 'turn/start':
                    turn = {'id': 'owned-turn', 'status': 'inProgress', 'items': [
                        {'type': 'userMessage', 'clientId': params['clientUserMessageId'],
                         'content': params['input']}]}
                    thread['turns'].append(turn)
                    thread['status'] = {'type': 'active', 'activeFlags': []}
                    result = {'turn': turn}
                    ws.frames.append(json.dumps({'id': 'native-approval',
                        'method': 'item/commandExecution/requestApproval',
                        'params': {'threadId': sid, 'turnId': 'owned-turn'}}))
                ws.frames.append(json.dumps({'id': request['id'], 'result': result}))
            ws.send = send
            async def connect(*args, **kwargs):
                return ws
            transport = module.CodexTaskTransport('/fake.sock', connector=connect,
                                                   deadline=time.monotonic()+2)
            self.addCleanup(transport.close)
            lifecycle = CodexTaskLifecycle(Path(root)/'journal', TaskThread('inc', sid, str(cwd)), transport)
            operation = str(uuid4())
            lifecycle.prepare(operation, 'task', deadline=time.monotonic()+2)
            self.assertEqual(lifecycle.submit(operation, deadline=time.monotonic()+2).phase, 'running')
            self.assertEqual(lifecycle.observe(operation, deadline=time.monotonic()+2).phase, 'waiting_approval')
            snapshot = lifecycle.interrupt(operation, deadline=time.monotonic()+2)
            self.assertEqual(snapshot.phase, 'stopping')
            self.assertFalse(snapshot.terminal_proven)
            thread['turns'][-1]['status'] = 'interrupted'
            thread['status'] = {'type': 'idle'}
            self.assertTrue(lifecycle.reconcile(operation, deadline=time.monotonic()+2).terminal_proven)
            self.assertFalse(any('result' in x or 'error' in x for x in ws.sent))

    def test_rpc_failure_FR_CXTASK_TRANSPORT_04(self):
        c, ws = self.client()
        ws.error = {'code': -1, 'message': 'private secret'}
        with self.assertRaises(Exception) as error:
            c.call('turn/start', {}, deadline=time.monotonic()+2)
        self.assertNotIn('private secret', str(error.exception))
        self.assertTrue(ws.closed)

    def test_receive_and_connect_timeouts_FR_CXTASK_TRANSPORT_03(self):
        c, ws = self.client()
        before = time.monotonic()
        with self.assertRaises(Exception):
            c.receive(deadline=before+.02)
        self.assertLess(time.monotonic()-before, .5)
        self.assertTrue(ws.closed)
        module = importlib.import_module('_codex_task_transport')
        async def slow_connect(*args, **kwargs):
            await asyncio.sleep(1)
        before = time.monotonic()
        with self.assertRaises(Exception):
            module.CodexTaskTransport('/fake.sock', deadline=before+.02, connector=slow_connect)
        self.assertLess(time.monotonic()-before, .5)

    def test_invalid_result_and_disconnect_FR_CXTASK_TRANSPORT_04(self):
        for payload in ([], None):
            c, ws = self.client()
            async def send(raw):
                request = json.loads(raw)
                ws.sent.append(request)
                ws.frames.append(json.dumps({'id': request['id'], 'result': payload}))
            ws.send = send
            with self.assertRaises(Exception):
                c.call('turn/start', {}, deadline=time.monotonic()+2)
            self.assertTrue(ws.closed)
            self.assertEqual(len(ws.sent), 3)
        c, ws = self.client()
        async def disconnect():
            raise ConnectionError('private secret')
        ws.recv = disconnect
        with self.assertRaises(Exception) as error:
            c.call('thread/read', {}, deadline=time.monotonic()+2)
        self.assertNotIn('private secret', str(error.exception))
        self.assertTrue(ws.closed)


if __name__ == '__main__':
    unittest.main()
