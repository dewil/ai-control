#!/usr/bin/env python3
"""Independent offline CXTASK-RPC contract tests; no native server required."""
import copy
import importlib.util
import json
import pathlib
import sys
import time
import unittest
from collections import deque

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
spec = importlib.util.spec_from_file_location('_runtime_transport_under_test', ROOT / 'bin/_codex_task_transport.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ProtocolError = module.ProtocolError


def dynamic(rpc='rpc', **changes):
    params = {'threadId': 'thread', 'turnId': 'turn', 'callId': 'call',
              'tool': 'task_read', 'arguments': {'path': 'file'}, 'namespace': None}
    params.update(changes)
    return {'id': rpc, 'method': 'item/tool/call', 'params': params}


def approval(method='item/commandExecution/requestApproval', rpc='rpc', **changes):
    params = {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'item'}
    if method == 'item/permissions/requestApproval':
        params['permissions'] = {'fileSystem': {'read': ['/safe']}}
    params.update(changes)
    return {'id': rpc, 'method': method, 'params': params}


def user_input(rpc='rpc', **changes):
    params = {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'item',
              'questions': [{'id': 'q1', 'question': 'Choose'}, {'id': 'q2'}],
              'autoResolutionMs': 1}
    params.update(changes)
    return {'id': rpc, 'method': 'item/tool/requestUserInput', 'params': params}


def resolved(rpc='rpc', thread='thread'):
    return {'method': 'serverRequest/resolved', 'params': {'threadId': thread, 'requestId': rpc}}


RESULT = {'success': True, 'contentItems': [{'type': 'inputText', 'text': ''}]}


class FakeSocket:
    def __init__(self):
        self.frames = deque()
        self.sent = []
        self.on_call = []
        self.closed = False
        self.fail_send = False
        self.fail_recv = False
        self.delay_send = 0
        self.close_calls = 0

    async def send(self, raw):
        self.sent.append(json.loads(raw))
        if self.fail_send:
            raise OSError('SECRET_WIRE_PAYLOAD')
        if self.delay_send:
            import asyncio
            await asyncio.sleep(self.delay_send)
        msg = self.sent[-1]
        if msg.get('method') == 'initialize':
            self.frames.append(json.dumps({'id': msg['id'], 'result': {}}))
        elif 'method' in msg and 'id' in msg:
            self.frames.extend(frame if isinstance(frame, str) else json.dumps(frame)
                               for frame in self.on_call)
            self.on_call = []
            self.frames.append(json.dumps({'id': msg['id'], 'result': {'ok': True}}))

    async def recv(self):
        if self.fail_recv:
            raise OSError('SECRET_WIRE_PAYLOAD')
        if self.frames:
            return self.frames.popleft()
        import asyncio
        await asyncio.sleep(10)

    async def close(self):
        self.closed = True
        self.close_calls += 1


class RuntimeContract(unittest.TestCase):
    """FR-CXRPC-01..04 / INV-CXRPC-01..04."""
    def setUp(self):
        self.transports = []
        self.connects = {}

    def tearDown(self):
        for transport in self.transports:
            transport.close()

    def deadline(self):
        return time.monotonic() + 2

    def make(self, *, bound=True, cls=None, **kwargs):
        socket = FakeSocket()
        connects = []
        async def connector(path, **options):
            connects.append((path, options))
            return socket
        transport_cls = cls or getattr(module, 'CodexTaskRuntimeTransport')
        transport = transport_cls('/offline/task.sock', deadline=self.deadline(), connector=connector, **kwargs)
        self.transports.append(transport)
        self.connects[id(transport)] = connects
        if bound and cls is None:
            transport.bind_operation('thread', 'turn')
        return transport, socket

    def ingest(self, transport, socket, frame):
        socket.frames.append(frame if isinstance(frame, str) else json.dumps(frame))
        return transport.receive(deadline=self.deadline())

    def reply(self, transport, rpc='rpc', result=None, **changes):
        identity = dict(thread_id='thread', turn_id='turn', call_id='call', deadline=self.deadline())
        identity.update(changes)
        return transport.reply_dynamic(rpc, copy.deepcopy(RESULT) if result is None else result, **identity)

    def human_reply(self, transport, frame, result):
        return transport.reply_approval(frame['id'], result, method=frame['method'],
            thread_id=frame['params']['threadId'], turn_id=frame['params']['turnId'],
            item_id=frame['params']['itemId'], deadline=self.deadline())

    def input_reply(self, transport, answers, rpc='rpc', **changes):
        identity = dict(thread_id='thread', turn_id='turn', item_id='item', deadline=self.deadline())
        identity.update(changes)
        return transport.reply_user_input(rpc, answers, **identity)

    def refused(self, transport, socket, action):
        before = copy.deepcopy(socket.sent)
        with self.assertRaises((ProtocolError, ValueError, TimeoutError)) as exc:
            action()
        self.assertNotIn('SECRET_WIRE_PAYLOAD', str(exc.exception))
        self.assertEqual(socket.sent, before)
        self.assertFalse(transport.closed)
        self.assertFalse(socket.closed)

    def protocol_failure(self, frame, **kwargs):
        transport, socket = self.make(**kwargs)
        before = len(socket.sent)
        with self.assertRaises(ProtocolError) as exc:
            self.ingest(transport, socket, frame)
        self.assertNotIn('SECRET_WIRE_PAYLOAD', str(exc.exception))
        self.assertTrue(transport.closed)
        self.assertTrue(socket.closed)
        self.assertEqual(len(socket.sent), before)
        return str(exc.exception)

    def test_opt_in_exact_allowlist_and_legacy_allowlist(self):
        # FR-CXRPC-01 / INV-CXRPC-01
        legacy = {'thread/read', 'turn/start', 'turn/interrupt'}
        runtime = legacy | {'thread/start', 'thread/resume', 'config/read', 'mcpServerStatus/list'}
        self.assertEqual(set(module.CodexTaskTransport.METHODS), legacy)
        self.assertEqual(set(getattr(module, 'CodexTaskRuntimeTransport').METHODS), runtime)
        for method in sorted(runtime):
            transport, socket = self.make()
            params = {'nested': {'values': [1, 2]}, 'opaque': 'SECRET_WIRE_PAYLOAD'}
            saved = copy.deepcopy(params)
            self.assertEqual(transport.call(method, params, deadline=self.deadline()), {'ok': True})
            self.assertEqual(params, saved)
            self.assertEqual(socket.sent[-1]['params'], saved)
        transport, socket = self.make()
        for method in ('config/write', 'send_response', 'unknown'):
            self.refused(transport, socket, lambda m=method: transport.call(m, {}, deadline=self.deadline()))

    def test_existing_transport_rejects_admission_and_keeps_callbacks(self):
        # INV-CXRPC-01: original class remains opt-in.
        transport, socket = self.make(bound=False, cls=module.CodexTaskTransport)
        self.refused(transport, socket, lambda: transport.call('thread/start', {}, deadline=self.deadline()))
        frame = dynamic()
        self.assertEqual(self.ingest(transport, socket, frame), frame)
        self.assertFalse(hasattr(transport, 'reply_dynamic'))

    def test_handshake_and_callbacks_during_call_before_bind_fifo(self):
        # INV-CXRPC-01 / INV-CXRPC-02
        transport, socket = self.make(bound=False)
        self.assertEqual(socket.sent[0]['method'], 'initialize')
        self.assertEqual(socket.sent[0]['params'], {'clientInfo': {'name': 'claude_control_task', 'version': '0.1'},
            'capabilities': {'experimentalApi': True}})
        self.assertEqual(socket.sent[1], {'method': 'initialized'})
        frames = [dynamic(), {'method': 'turn/completed', 'params': {'turnId': 'turn'}}]
        socket.on_call = copy.deepcopy(frames)
        transport.call('turn/start', {'threadId': 'thread'}, deadline=self.deadline())
        self.refused(transport, socket, lambda: self.reply(transport))
        transport.bind_operation('thread', 'turn')
        self.reply(transport)
        self.assertEqual(socket.sent[-1], {'id': 'rpc', 'result': RESULT})
        self.assertEqual([transport.receive(deadline=self.deadline()) for _ in frames], frames)

    def test_binding_is_immutable_and_validated(self):
        # INV-CXRPC-02 / INV-CXRPC-04
        transport, socket = self.make(bound=False)
        for thread, turn in [('', 'turn'), ('thread', ''), (0, 'turn'), ('thread', None),
                             ('a\n', 'turn'), ('thread', '\x7f'), ('é' * 129, 'turn')]:
            self.refused(transport, socket, lambda a=thread, b=turn: transport.bind_operation(a, b))
        transport.bind_operation('thread', 'turn')
        self.refused(transport, socket, lambda: transport.bind_operation('thread', 'turn'))
        self.refused(transport, socket, lambda: transport.bind_operation('other', 'turn'))
        transport.close()
        with self.assertRaises((ProtocolError, ValueError, TimeoutError)):
            transport.bind_operation('thread', 'turn')

    def test_binding_byte_boundary(self):
        transport, socket = self.make(bound=False)
        thread = 'é' * 128
        transport.bind_operation(thread, 'turn')
        self.ingest(transport, socket, dynamic(threadId=thread))
        self.reply(transport, thread_id=thread)
        self.assertEqual(socket.sent[-1]['id'], 'rpc')

    def test_typed_rpc_ids_zero_and_signed_boundaries(self):
        # INV-CXRPC-02 / INV-CXRPC-03
        transport, socket = self.make()
        for rpc in (0, '0', -(2**63), 2**63 - 1, 'é' * 128):
            self.ingest(transport, socket, dynamic(rpc))
        for rpc in (0, '0', -(2**63), 2**63 - 1, 'é' * 128):
            self.reply(transport, rpc)
            self.assertEqual(socket.sent[-1], {'id': rpc, 'result': RESULT})
            self.assertIs(type(socket.sent[-1]['id']), type(rpc))

    def test_invalid_rpc_ids_protocol_failure(self):
        for rpc in (True, False, None, '', 2**63, -(2**63) - 1, 1.0, [], {}, 'é' * 129):
            with self.subTest(rpc=repr(rpc)):
                self.protocol_failure(dynamic(rpc))

    def test_supported_callback_required_fields(self):
        # INV-CXRPC-02
        samples = [(dynamic(), ['threadId', 'turnId', 'callId', 'tool', 'arguments']),
                   (approval(), ['threadId', 'turnId', 'itemId']),
                   (user_input(), ['threadId', 'turnId', 'itemId', 'questions']),
                   (approval('item/permissions/requestApproval'), ['threadId', 'turnId', 'itemId', 'permissions'])]
        for frame, fields in samples:
            for field in fields:
                with self.subTest(method=frame['method'], field=field):
                    bad = copy.deepcopy(frame)
                    del bad['params'][field]
                    self.protocol_failure(bad)
        for changes in ({'arguments': []}, {'arguments': None}, {'namespace': ''}, {'namespace': 5},
                        {'threadId': ''}, {'turnId': 5}, {'callId': ''}, {'tool': ''}):
            self.protocol_failure(dynamic(**changes))
        self.protocol_failure(approval('item/permissions/requestApproval', permissions=[]))

    def test_namespace_absent_null_and_nonempty_are_eligible(self):
        for namespace in ('ABSENT', None, 'tasks'):
            transport, socket = self.make()
            frame = dynamic(namespace=namespace)
            if namespace == 'ABSENT':
                del frame['params']['namespace']
            self.assertEqual(self.ingest(transport, socket, frame), frame)
            self.reply(transport)

    def test_user_input_questions_validated(self):
        for questions in (None, {}, [1], [{}], [{'id': ''}], [{'id': 1}], [{'id': 'q'}, {'id': 'q'}]):
            with self.subTest(questions=questions):
                self.protocol_failure(user_input(questions=questions))

    def test_unknown_and_no_turn_callbacks_never_get_reply_capability(self):
        # INV-CXRPC-01 / INV-CXRPC-02 / INV-CXRPC-03
        for method in ('mcp/elicitation/request', 'account/chatgptAuthTokens/refresh', 'execCommand',
                       'applyPatch', 'unknown/request'):
            transport, socket = self.make()
            frame = {'id': 'rpc', 'method': method, 'params': {'threadId': 'thread'}}
            self.assertEqual(self.ingest(transport, socket, frame), frame)
            self.refused(transport, socket, lambda: self.reply(transport))
            self.refused(transport, socket, lambda: transport.reply_approval('rpc', {'decision': 'accept'},
                method=method, thread_id='thread', turn_id='turn', item_id='item', deadline=self.deadline()))
            self.refused(transport, socket, lambda: self.input_reply(transport, {'q1': {'answers': ['yes']}}))
            self.assertEqual(len(socket.sent), 2)

    def test_notifications_without_id_do_not_register(self):
        transport, socket = self.make()
        frame = dynamic()
        del frame['id']
        self.assertEqual(self.ingest(transport, socket, frame), frame)
        self.refused(transport, socket, lambda: self.reply(transport))

    def test_foreign_captured_owner_cannot_override_binding(self):
        # INV-CXRPC-02
        for changes, identity in [({'threadId': 'foreign'}, {'thread_id': 'foreign'}),
                                  ({'turnId': 'foreign'}, {'turn_id': 'foreign'})]:
            transport, socket = self.make()
            self.ingest(transport, socket, dynamic(**changes))
            self.refused(transport, socket, lambda: self.reply(transport, **identity))
            self.refused(transport, socket, lambda: self.reply(transport))

    def test_wrong_ids_identity_and_reply_class_zero_send_then_valid(self):
        # INV-CXRPC-03 / INV-CXRPC-04
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic(0))
        for rpc, changes in [('0', {}), ('unknown', {}), (True, {}), (0, {'thread_id': 'bad'}),
                             (0, {'turn_id': 'bad'}), (0, {'call_id': 'bad'})]:
            self.refused(transport, socket, lambda r=rpc, c=changes: self.reply(transport, r, **c))
        self.refused(transport, socket, lambda: transport.reply_approval(0, {'decision': 'accept'},
            method='item/commandExecution/requestApproval', thread_id='thread', turn_id='turn',
            item_id='item', deadline=self.deadline()))
        self.refused(transport, socket, lambda: self.input_reply(transport, {'q1': {'answers': []}}, rpc=0))
        self.reply(transport, 0)

    def test_receive_deepcopy_cannot_change_authority(self):
        # INV-CXRPC-02
        transport, socket = self.make()
        received = self.ingest(transport, socket, dynamic())
        received['params']['threadId'] = 'foreign'
        received['params']['callId'] = 'other'
        received['params']['arguments']['path'] = 'mutated'
        self.refused(transport, socket, lambda: self.reply(transport, thread_id='foreign', call_id='other'))
        self.reply(transport)

    def test_native_deepcopy_cannot_expand_permissions_or_question_ids(self):
        transport, socket = self.make()
        frame = approval('item/permissions/requestApproval')
        received = self.ingest(transport, socket, frame)
        received['params']['permissions']['fileSystem']['read'].append('/new')
        self.refused(transport, socket, lambda: self.human_reply(transport, frame,
            {'permissions': received['params']['permissions']}))
        self.human_reply(transport, frame, {'permissions': frame['params']['permissions']})
        transport, socket = self.make()
        received = self.ingest(transport, socket, user_input())
        received['params']['questions'][0]['id'] = 'invented'
        self.refused(transport, socket, lambda: self.input_reply(transport, {'invented': {'answers': ['yes']}}))
        self.input_reply(transport, {'q1': {'answers': ['yes']}})

    def test_replay_canonical_params_fifo_one_response(self):
        # INV-CXRPC-02
        transport, socket = self.make()
        first = dynamic()
        replay = copy.deepcopy(first)
        replay['params'] = dict(reversed(list(replay['params'].items())))
        for frame in (first, replay):
            self.assertEqual(self.ingest(transport, socket, frame), frame)
        self.reply(transport)
        self.refused(transport, socket, lambda: self.reply(transport))
        self.assertEqual(self.ingest(transport, socket, replay), replay)
        self.refused(transport, socket, lambda: self.reply(transport))
        self.assertEqual(sum('result' in msg for msg in socket.sent), 1)

    def test_conflicting_payload_method_and_extra_metadata_close(self):
        # INV-CXRPC-02 / INV-CXRPC-04
        for answered in (False, True):
            for change in ('arguments', 'method', 'extra'):
                transport, socket = self.make()
                self.ingest(transport, socket, dynamic())
                if answered:
                    self.reply(transport)
                other = dynamic()
                if change == 'method':
                    other = approval()
                elif change == 'arguments':
                    other['params']['arguments']['path'] = 'SECRET_WIRE_PAYLOAD'
                else:
                    other['params']['presentation'] = 'SECRET_WIRE_PAYLOAD'
                before = len(socket.sent)
                with self.assertRaises(ProtocolError) as exc:
                    self.ingest(transport, socket, other)
                self.assertNotIn('SECRET_WIRE_PAYLOAD', str(exc.exception))
                self.assertTrue(transport.closed)
                self.assertTrue(socket.closed)
                self.assertEqual(len(socket.sent), before)

    def test_resolution_inside_call_before_dequeue_blocks_reply(self):
        # INV-CXRPC-02
        transport, socket = self.make()
        socket.on_call = [dynamic(), resolved()]
        transport.call('thread/read', {}, deadline=self.deadline())
        self.refused(transport, socket, lambda: self.reply(transport))
        self.assertEqual(transport.receive(deadline=self.deadline()), dynamic())
        self.assertEqual(transport.receive(deadline=self.deadline()), resolved())
        self.assertEqual(self.ingest(transport, socket, dynamic()), dynamic())
        self.refused(transport, socket, lambda: self.reply(transport))

    def test_unknown_resolution_does_not_create_entry(self):
        transport, socket = self.make(max_requests=1)
        note = resolved('unknown')
        self.assertEqual(self.ingest(transport, socket, note), note)
        self.ingest(transport, socket, dynamic('unknown'))
        self.reply(transport, 'unknown')

    def test_resolution_preserves_typed_id(self):
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic(0))
        self.ingest(transport, socket, dynamic('0'))
        self.ingest(transport, socket, resolved(0))
        self.refused(transport, socket, lambda: self.reply(transport, 0))
        self.reply(transport, '0')

    def test_resolution_wrong_thread_known_id_conflicts(self):
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic())
        with self.assertRaises(ProtocolError):
            self.ingest(transport, socket, resolved(thread='foreign'))
        self.assertTrue(transport.closed)
        self.assertTrue(socket.closed)

    def test_resolution_payload_invalid_closes(self):
        for params in ({}, {'threadId': 'thread'}, {'threadId': '', 'requestId': 'rpc'},
                       {'threadId': 'thread', 'requestId': True}, {'threadId': 'thread', 'requestId': None}):
            self.protocol_failure({'method': 'serverRequest/resolved', 'params': params})

    def test_conflict_after_resolved_is_still_failure(self):
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic())
        self.ingest(transport, socket, resolved())
        with self.assertRaises(ProtocolError):
            self.ingest(transport, socket, dynamic(tool='other'))
        self.assertTrue(transport.closed)

    def test_registry_bound_includes_answered_resolved_and_drained(self):
        # INV-CXRPC-03 / INV-CXRPC-04
        for consume in ('pending', 'answered', 'resolved'):
            transport, socket = self.make(max_requests=1)
            self.ingest(transport, socket, dynamic())
            if consume == 'answered':
                self.reply(transport)
            if consume == 'resolved':
                self.ingest(transport, socket, resolved())
            self.assertEqual(self.ingest(transport, socket, dynamic()), dynamic())
            with self.assertRaises(ProtocolError):
                self.ingest(transport, socket, dynamic('second'))
            self.assertTrue(transport.closed)
            self.assertTrue(socket.closed)

    def test_registry_and_fifo_bounds_are_separate(self):
        transport, socket = self.make(max_requests=1, max_events=8)
        socket.on_call = [dynamic(), dynamic()]
        transport.call('thread/read', {}, deadline=self.deadline())
        self.assertEqual(transport.receive(deadline=self.deadline()), dynamic())
        self.assertEqual(transport.receive(deadline=self.deadline()), dynamic())
        self.reply(transport)
        transport, socket = self.make(max_requests=8, max_events=1)
        socket.on_call = [dynamic('one'), dynamic('two')]
        with self.assertRaises(ProtocolError):
            transport.call('thread/read', {}, deadline=self.deadline())
        self.assertTrue(transport.closed)

    def test_max_requests_positive_nonbool(self):
        for value in (0, -1, True, False, 1.5, None, '1'):
            with self.subTest(value=value):
                with self.assertRaises((ProtocolError, ValueError)):
                    self.make(max_requests=value)

    def test_nonfinite_and_duplicate_json_keys_are_protocol_errors(self):
        # INV-CXRPC-02 / INV-CXRPC-04
        for value in ('NaN', 'Infinity', '-Infinity'):
            raw = json.dumps(dynamic()).replace('"file"', value)
            self.protocol_failure(raw)
        for raw in ('{"id":"rpc","id":"other","method":"item/tool/call","params":{}}',
                    json.dumps(dynamic()).replace('"path": "file"', '"path":"a","path":"SECRET_WIRE_PAYLOAD"')):
            self.protocol_failure(raw)

    def test_dynamic_result_exact_shape_and_text_only(self):
        # INV-CXRPC-03 / INV-CXRPC-04
        bad_results = [None, {}, {'success': 1, 'contentItems': [{'type': 'inputText', 'text': 'x'}]},
            {'success': True, 'contentItems': []}, {'success': True, 'contentItems': [{'type': 'inputImage', 'text': 'x'}]},
            {'success': True, 'contentItems': [{'type': 'inputText', 'text': 1}]},
            {'success': True, 'contentItems': [{'type': 'inputText', 'text': 'x', 'extra': 1}]},
            {'success': True, 'contentItems': [{'type': 'inputText', 'text': 'x'}], 'error': 'invented'},
            {'success': True, 'contentItems': [{'type': 'inputText', 'text': 'x'}] * 65},
            {'success': False, 'contentItems': [{'type': 'inputText', 'text': 'x' * (1024 * 1024)}]}]
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic())
        for result in bad_results:
            self.refused(transport, socket, lambda r=result: transport.reply_dynamic('rpc', r,
                thread_id='thread', turn_id='turn', call_id='call', deadline=self.deadline()))
        result = {'success': False, 'contentItems': [{'type': 'inputText', 'text': ''}] * 64}
        saved = copy.deepcopy(result)
        self.reply(transport, result=result)
        self.assertEqual(result, saved)
        self.assertEqual(socket.sent[-1], {'id': 'rpc', 'result': saved})

    def test_dynamic_result_utf8_encoded_size_limit(self):
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic())
        result = {'success': True, 'contentItems': [{'type': 'inputText', 'text': 'é' * 600000}]}
        self.refused(transport, socket, lambda: self.reply(transport, result=result))
        self.reply(transport)

    def test_command_and_file_approval_exact_shapes(self):
        # INV-CXRPC-03
        for method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            for decision in ('accept', 'decline', 'cancel'):
                transport, socket = self.make()
                frame = approval(method, rpc=0)
                self.assertEqual(self.ingest(transport, socket, frame), frame)
                self.human_reply(transport, frame, {'decision': decision})
                self.assertEqual(socket.sent[-1], {'id': 0, 'result': {'decision': decision}})

    def test_approval_rejects_session_and_amendment_and_wrong_identity(self):
        transport, socket = self.make()
        frame = approval()
        self.ingest(transport, socket, frame)
        for result in ({}, {'decision': 'acceptForSession'}, {'decision': 'accept', 'execPolicyAmendment': ['x']},
                       {'decision': 'accept', 'networkPolicyAmendment': {}}, {'decision': 'accept', 'extra': True}):
            self.refused(transport, socket, lambda r=result: self.human_reply(transport, frame, r))
        for changes in ({'method': 'item/fileChange/requestApproval'}, {'thread_id': 'foreign'},
                        {'turn_id': 'foreign'}, {'item_id': 'foreign'}):
            opts = dict(method=frame['method'], thread_id='thread', turn_id='turn', item_id='item', deadline=self.deadline())
            opts.update(changes)
            self.refused(transport, socket, lambda o=opts: transport.reply_approval('rpc', {'decision': 'accept'}, **o))
        self.human_reply(transport, frame, {'decision': 'decline'})

    def test_permissions_only_requested_profile_or_deny(self):
        # INV-CXRPC-03
        for deny in (False, True):
            transport, socket = self.make()
            frame = approval('item/permissions/requestApproval')
            self.ingest(transport, socket, frame)
            result = {'permissions': {} if deny else copy.deepcopy(frame['params']['permissions']),
                      'scope': 'turn', 'strictAutoReview': None}
            saved = copy.deepcopy(result)
            self.human_reply(transport, frame, result)
            self.assertEqual(result, saved)
            self.assertEqual(socket.sent[-1], {'id': 'rpc', 'result': saved})
        for strict in (True, False):
            transport, socket = self.make()
            frame = approval('item/permissions/requestApproval', permissions={'a': 1, 'b': {'x': [1, 2]}})
            self.ingest(transport, socket, frame)
            result = {'permissions': {'b': {'x': [1, 2]}, 'a': 1}, 'strictAutoReview': strict}
            self.human_reply(transport, frame, result)
            self.assertEqual(socket.sent[-1]['result'], result)

    def test_permissions_partial_new_session_extra_refused(self):
        transport, socket = self.make()
        frame = approval('item/permissions/requestApproval')
        self.ingest(transport, socket, frame)
        for result in ({}, {'permissions': []}, {'permissions': {'fileSystem': {}}},
                       {'permissions': {'network': {'enabled': True}}}, {'permissions': {}, 'scope': 'session'},
                       {'permissions': {}, 'strictAutoReview': 1}, {'permissions': {}, 'extra': True}):
            self.refused(transport, socket, lambda r=result: self.human_reply(transport, frame, r))
        self.human_reply(transport, frame, {'permissions': {}})

    def test_permissions_scope_string_subclass_cannot_hide_session_grant(self):
        # FR-CXRPC-03 / INV-CXRPC-03 / INV-CXRPC-04
        class HiddenSession(str):
            def __ne__(self, other):
                return False
        transport, socket = self.make()
        frame = approval('item/permissions/requestApproval')
        self.ingest(transport, socket, frame)
        result = {'permissions': copy.deepcopy(frame['params']['permissions']),
                  'scope': HiddenSession('session')}
        self.assertEqual(json.loads(json.dumps(result))['scope'], 'session')
        self.refused(transport, socket, lambda: self.human_reply(transport, frame, result))
        self.human_reply(transport, frame, {'permissions': {}})
        self.assertEqual(socket.sent[-1], {'id': 'rpc', 'result': {'permissions': {}}})

    def test_approval_decision_string_subclass_cannot_hide_session_grant(self):
        # FR-CXRPC-03 / INV-CXRPC-03 / INV-CXRPC-04
        class HiddenSessionDecision(str):
            def __eq__(self, other):
                return True
            def __ne__(self, other):
                return False
            def __hash__(self):
                return hash('accept')
        for method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            with self.subTest(method=method):
                transport, socket = self.make()
                frame = approval(method)
                self.ingest(transport, socket, frame)
                result = {'decision': HiddenSessionDecision('acceptForSession')}
                self.assertEqual(json.loads(json.dumps(result))['decision'], 'acceptForSession')
                self.refused(transport, socket, lambda: self.human_reply(transport, frame, result))
                self.human_reply(transport, frame, {'decision': 'decline'})
                self.assertEqual(socket.sent[-1], {'id': 'rpc', 'result': {'decision': 'decline'}})

    def test_binding_rejects_string_subclasses_with_custom_equality(self):
        # FR-CXRPC-02 / INV-CXRPC-02 / INV-CXRPC-04
        class ForgedIdentity(str):
            def __eq__(self, other):
                return True
            def __ne__(self, other):
                return False
            __hash__ = str.__hash__
        transport, socket = self.make(bound=False)
        for thread, turn in ((ForgedIdentity('foreign'), 'turn'), ('thread', ForgedIdentity('foreign'))):
            self.refused(transport, socket, lambda t=thread, u=turn: transport.bind_operation(t, u))
        transport.bind_operation('thread', 'turn')
        self.ingest(transport, socket, dynamic())
        self.reply(transport)

    def test_reply_identities_reject_string_subclasses_with_custom_equality(self):
        # FR-CXRPC-02 / INV-CXRPC-02 / INV-CXRPC-03 / INV-CXRPC-04
        class ForgedIdentity(str):
            def __eq__(self, other):
                return True
            def __ne__(self, other):
                return False
            __hash__ = str.__hash__
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic())
        for field in ('thread_id', 'turn_id', 'call_id'):
            self.refused(transport, socket, lambda f=field: self.reply(transport, **{f: ForgedIdentity('foreign')}))
        self.reply(transport)
        transport, socket = self.make()
        frame = approval()
        self.ingest(transport, socket, frame)
        for field in ('method', 'thread_id', 'turn_id', 'item_id'):
            identity = dict(method=frame['method'], thread_id='thread', turn_id='turn',
                            item_id='item', deadline=self.deadline())
            identity[field] = ForgedIdentity('foreign')
            self.refused(transport, socket, lambda i=identity: transport.reply_approval('rpc', {'decision': 'accept'}, **i))
        self.human_reply(transport, frame, {'decision': 'decline'})
        transport, socket = self.make()
        self.ingest(transport, socket, user_input())
        for field in ('thread_id', 'turn_id', 'item_id'):
            self.refused(transport, socket, lambda f=field: self.input_reply(transport,
                {'q1': {'answers': ['yes']}}, **{f: ForgedIdentity('foreign')}))
        self.input_reply(transport, {'q1': {'answers': ['yes']}})

    def test_user_input_sparse_answers_exact_shape_original_id(self):
        # INV-CXRPC-03
        transport, socket = self.make()
        self.ingest(transport, socket, user_input(0))
        answers = {'q2': {'answers': []}}
        saved = copy.deepcopy(answers)
        self.input_reply(transport, answers, rpc=0)
        self.assertEqual(answers, saved)
        self.assertEqual(socket.sent[-1], {'id': 0, 'result': {'answers': saved}})
        self.refused(transport, socket, lambda: self.input_reply(transport, answers, rpc=0))

    def test_user_input_validation_zero_send_and_string_byte_bounds(self):
        transport, socket = self.make()
        self.ingest(transport, socket, user_input())
        for answers in ({}, [], {'unknown': {'answers': ['x']}}, {'q1': {}}, {'q1': {'answers': 'x'}},
                        {'q1': {'answers': [1]}}, {'q1': {'answers': ['x'] * 17}},
                        {'q1': {'answers': ['é' * 4097]}}, {'q1': {'answers': [], 'extra': 1}}):
            self.refused(transport, socket, lambda a=answers: self.input_reply(transport, a))
        for changes in ({'thread_id': 'foreign'}, {'turn_id': 'foreign'}, {'item_id': 'foreign'}):
            self.refused(transport, socket, lambda c=changes: self.input_reply(transport, {'q1': {'answers': ['x']}}, **c))
        answers = {'q1': {'answers': ['é' * 4096] * 16}, 'q2': {'answers': ['']}}
        self.input_reply(transport, answers)
        self.assertEqual(socket.sent[-1]['result'], {'answers': answers})

    def test_user_input_total_encoded_size(self):
        transport, socket = self.make()
        questions = [{'id': 'q' + str(i)} for i in range(10)]
        self.ingest(transport, socket, user_input(questions=questions))
        answers = {q['id']: {'answers': ['x' * 8192] * 16} for q in questions}
        self.refused(transport, socket, lambda: self.input_reply(transport, answers))
        self.input_reply(transport, {'q0': {'answers': ['x']}})

    def test_distinct_human_and_dynamic_response_apis(self):
        transport, socket = self.make()
        frame = user_input()
        self.ingest(transport, socket, frame)
        self.refused(transport, socket, lambda: self.reply(transport))
        self.refused(transport, socket, lambda: transport.reply_approval('rpc', {'decision': 'accept'},
            method=frame['method'], thread_id='thread', turn_id='turn', item_id='item', deadline=self.deadline()))
        self.input_reply(transport, {'q1': {'answers': ['human']}})
        transport, socket = self.make()
        frame = approval()
        self.ingest(transport, socket, frame)
        self.refused(transport, socket, lambda: self.reply(transport))
        self.refused(transport, socket, lambda: self.input_reply(transport, {'q1': {'answers': ['x']}}))
        self.human_reply(transport, frame, {'decision': 'decline'})

    def test_human_callbacks_foreign_owner_and_before_bind_no_send(self):
        # INV-CXRPC-02 / INV-CXRPC-03
        for family in ('approval', 'input'):
            for foreign in ('threadId', 'turnId'):
                transport, socket = self.make()
                changes = {foreign: 'foreign'}
                frame = approval(**changes) if family == 'approval' else user_input(**changes)
                self.assertEqual(self.ingest(transport, socket, frame), frame)
                if family == 'approval':
                    action = lambda: self.human_reply(transport, frame, {'decision': 'accept'})
                else:
                    identity = {'thread_id': frame['params']['threadId'], 'turn_id': frame['params']['turnId']}
                    action = lambda: self.input_reply(transport, {'q1': {'answers': ['x']}}, **identity)
                self.refused(transport, socket, action)
            transport, socket = self.make(bound=False)
            frame = approval() if family == 'approval' else user_input()
            self.ingest(transport, socket, frame)
            action = (lambda: self.human_reply(transport, frame, {'decision': 'decline'})) if family == 'approval' else (
                lambda: self.input_reply(transport, {'q1': {'answers': []}}))
            self.refused(transport, socket, action)
            transport.bind_operation('thread', 'turn')
            action()

    def test_native_optional_metadata_preserved_and_part_of_conflict(self):
        # INV-CXRPC-02
        for original in (approval(), user_input()):
            transport, socket = self.make()
            original['params']['presentation'] = {'reason': 'Display', 'optional': ['x']}
            self.assertEqual(self.ingest(transport, socket, original), original)
            replay = copy.deepcopy(original)
            self.assertEqual(self.ingest(transport, socket, replay), replay)
            changed = copy.deepcopy(original)
            changed['params']['presentation']['optional'].append('SECRET_WIRE_PAYLOAD')
            with self.assertRaises(ProtocolError) as exc:
                self.ingest(transport, socket, changed)
            self.assertNotIn('SECRET_WIRE_PAYLOAD', str(exc.exception))
            self.assertTrue(transport.closed)

    def test_resolved_human_callbacks_remain_unanswerable(self):
        for family in ('approval', 'input'):
            transport, socket = self.make()
            frame = approval() if family == 'approval' else user_input()
            self.ingest(transport, socket, frame)
            self.ingest(transport, socket, resolved())
            self.assertEqual(self.ingest(transport, socket, frame), frame)
            action = (lambda: self.human_reply(transport, frame, {'decision': 'accept'})) if family == 'approval' else (
                lambda: self.input_reply(transport, {'q1': {'answers': ['yes']}}))
            self.refused(transport, socket, action)

    def test_expired_or_invalid_reply_deadline_preserves_live_socket(self):
        # INV-CXRPC-03 / INV-CXRPC-04
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic())
        for deadline in (time.monotonic() - 1, True, None, float('nan'), float('inf')):
            self.refused(transport, socket, lambda d=deadline: self.reply(transport, deadline=d))
        self.reply(transport)

    def test_send_failure_delivery_uncertain_closes_without_retry(self):
        # INV-CXRPC-04
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic())
        socket.fail_send = True
        before = len(socket.sent)
        with self.assertRaises(ProtocolError) as exc:
            self.reply(transport)
        self.assertNotIn('SECRET_WIRE_PAYLOAD', str(exc.exception))
        self.assertTrue(transport.closed)
        self.assertTrue(socket.closed)
        self.assertEqual(len(socket.sent), before + 1)
        self.assertEqual(len(self.connects[id(transport)]), 1)
        with self.assertRaises(ProtocolError):
            self.reply(transport)
        self.assertEqual(len(socket.sent), before + 1)

    def test_deadline_during_send_closes_without_retry(self):
        transport, socket = self.make()
        self.ingest(transport, socket, dynamic())
        socket.delay_send = .1
        before = len(socket.sent)
        with self.assertRaises(ProtocolError):
            self.reply(transport, deadline=time.monotonic() + .02)
        self.assertTrue(transport.closed)
        self.assertTrue(socket.closed)
        self.assertEqual(len(socket.sent), before + 1)

    def test_receive_failure_and_timeout_clear_connection(self):
        for failure in ('recv', 'timeout'):
            transport, socket = self.make()
            self.ingest(transport, socket, dynamic())
            before = len(socket.sent)
            socket.fail_recv = failure == 'recv'
            with self.assertRaises(ProtocolError) as exc:
                transport.receive(deadline=time.monotonic() + .02)
            self.assertNotIn('SECRET_WIRE_PAYLOAD', str(exc.exception))
            self.assertTrue(transport.closed)
            self.assertTrue(socket.closed)
            with self.assertRaises(ProtocolError):
                self.reply(transport)
            self.assertEqual(len(socket.sent), before)
            self.assertEqual(len(self.connects[id(transport)]), 1)

    def test_protocol_errors_are_static_not_raw_payload(self):
        first = self.protocol_failure(dynamic(arguments={'x': float('nan'), 'secret': 'SECRET_WIRE_PAYLOAD'}))
        second = self.protocol_failure(dynamic(arguments={'x': float('nan'), 'secret': 'OTHER_PRIVATE_PAYLOAD'}))
        self.assertEqual(first, second)
        self.assertNotIn('OTHER_PRIVATE_PAYLOAD', second)

    def test_close_idempotent_discards_fifo_and_registry(self):
        # INV-CXRPC-04
        transport, socket = self.make()
        socket.on_call = [dynamic()]
        transport.call('thread/read', {}, deadline=self.deadline())
        before = len(socket.sent)
        transport.close()
        transport.close()
        self.assertTrue(transport.closed)
        self.assertTrue(socket.closed)
        self.assertEqual(socket.close_calls, 1)
        for action in (lambda: self.reply(transport), lambda: transport.receive(deadline=self.deadline()),
                       lambda: transport.call('thread/read', {}, deadline=self.deadline())):
            with self.assertRaises(ProtocolError):
                action()
        self.assertEqual(len(socket.sent), before)


if __name__ == '__main__':
    unittest.main()
