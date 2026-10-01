"""Shared App Server approvals belong to the native client, never this observer."""
import importlib.util
import json
from pathlib import Path
import time
import unittest

spec = importlib.util.spec_from_file_location('codex_transport_test', Path(__file__).resolve().parents[1]/'bin/_codex_rc.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class MockWebSocket:
    def __init__(self):
        self.sent = []
        self.events = []
        self.timeouts = []

    def send(self, frame):
        request = json.loads(frame)
        self.sent.append(request)
        self.events.extend([
            {'method':'thread/status/changed', 'params':{'threadId':'other'}},
            {'id':'approval-of-another-client', 'method':'item/commandExecution/requestApproval',
             'params':{'threadId':'other', 'command':'sensitive command'}},
            {'id':request['id'], 'result':{'status':'connected'}},
        ])

    def recv(self, timeout):
        self.timeouts.append(timeout)
        return json.dumps(self.events.pop(0))


class TransportTests(unittest.TestCase):
    def client(self, seconds=20):
        client = mod.WebSocketRPC.__new__(mod.WebSocketRPC)
        client.timeout = 25
        client.completed_turns = {}
        client.seed_turns = {}
        client.deadline = time.monotonic()+seconds
        client.ws = MockWebSocket()
        return client

    def test_shared_approval_is_not_answered_or_stolen(self):
        client = self.client()
        result = client.call('remoteControl/status/read', {})
        self.assertEqual(result, {'status':'connected'})
        self.assertEqual(len(client.ws.sent), 1)
        self.assertEqual(client.ws.sent[0]['method'], 'remoteControl/status/read')
        self.assertFalse(any('result' in x or 'error' in x for x in client.ws.sent))
        self.assertEqual(len(client.ws.timeouts), 3)

    def test_completion_before_turn_start_response_is_retained(self):
        client = self.client()
        sid = '12345678-1234-4000-8000-000000000001'
        completion = {'method':'turn/completed', 'params':{'threadId':sid,
                       'turn':{'id':'seed', 'status':'completed'}}}
        sent = []
        def send(frame):
            request = json.loads(frame)
            sent.append(request)
            if request['method'] == 'turn/start':
                client.ws.events.extend([completion,
                    {'id':request['id'], 'result':{'turn':{'id':'seed', 'status':'inProgress'}}}])
            elif request['method'] == 'thread/read':
                self.assertEqual(client.completed_turns[(sid, 'seed')], 'completed')
                client.ws.events.append({'id':request['id'], 'result':{'thread':{
                    'id':sid, 'cwd':'/tmp', 'status':{'type':'notLoaded'},
                    'turns':[{'id':'seed', 'status':'completed'}]}}})
            else:
                self.fail('Unexpected RPC ' + request['method'])
        client.ws.send = send
        client.call('turn/start', {'threadId':sid, 'input':[]})
        row = {'sid':sid, 'cwd':'/tmp', 'status':'active'}
        self.assertEqual(client.materialize(row)['status'], 'notLoaded')
        self.assertEqual([x['method'] for x in sent], ['turn/start','thread/read'])
        self.assertNotIn('_seed_turn_id', row)

    def test_materialize_waits_for_seed_notification_before_read(self):
        client = self.client()
        sid = '12345678-1234-4000-8000-000000000001'
        client.seed_turns[sid] = 'seed'
        client.ws.events.extend([
            {'method':'turn/completed', 'params':{'threadId':'other',
                'turn':{'id':'foreign', 'status':'completed'}}},
            {'method':'turn/completed', 'params':{'threadId':sid,
                'turn':{'id':'seed', 'status':'completed'}}},
        ])
        sent = []
        def send(frame):
            request = json.loads(frame)
            sent.append(request)
            self.assertIn((sid, 'seed'), client.completed_turns)
            self.assertEqual(request['method'], 'thread/read')
            client.ws.events.append({'id':request['id'], 'result':{'thread':{
                'id':sid, 'cwd':'/tmp', 'status':{'type':'notLoaded'},
                'turns':[{'id':'seed', 'status':'completed'}]}}})
        client.ws.send = send
        client.materialize({'sid':sid, 'cwd':'/tmp', 'status':'active'})
        self.assertEqual(len(sent), 1)

    def test_expired_global_deadline_prevents_outgoing_rpc(self):
        client = self.client(seconds=-1)
        with self.assertRaises(TimeoutError):
            client.call('thread/start', {})
        self.assertEqual(client.ws.sent, [])

    def test_receives_capped_by_global_remaining_budget(self):
        client = self.client(seconds=2)
        client.call('remoteControl/status/read', {})
        self.assertTrue(all(0 < t <= 2 for t in client.ws.timeouts))
        client.deadline = time.monotonic()-1
        with self.assertRaises(TimeoutError):
            client.call('thread/list', {})
        self.assertEqual(len(client.ws.sent), 1)

if __name__ == '__main__':
    unittest.main()
