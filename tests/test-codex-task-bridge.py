"""Independent public-contract tests for CXTASK-BRIDGE; stdlib only."""
import contextlib
import copy
import importlib
import json
import os
import stat
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bin'))
from _codex_task_bridge import BridgeError, CodexTaskBridge, TaskBinding, dynamic_tools


class BridgeContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.agent = self.root / 'agent'
        self.agent.mkdir()
        self.state = self.root / 'private'
        self.binding = TaskBinding('incarnation', 'event', str(self.agent), 'thread', 'turn')
        self.now = 1.0
        self.active = False
        self.allowed = True
        self.enters = 0
        self.calls = []
        self.qid = str(uuid.uuid4())
        self.writer_result = None
        self.writer_error = None
        self.writer_hook = None
        self.bridge = self.make_bridge()

    @contextlib.contextmanager
    def guard(self, binding, *, deadline):
        self.assertEqual(binding, self.binding)
        self.enters += 1
        self.active = True
        try:
            yield self.allowed
        finally:
            self.active = False

    def writer(self, binding, tool, arguments, *, deadline):
        self.assertTrue(self.active)
        self.assertEqual(binding, self.binding)
        self.calls.append((tool, copy.deepcopy(arguments)))
        if self.writer_hook:
            self.writer_hook(arguments)
        if self.writer_error:
            raise self.writer_error
        if self.writer_result is not None:
            return self.writer_result
        return {'qid': self.qid} if tool == 'task_ask' else {'requested': True}

    def make_bridge(self, **kwargs):
        return CodexTaskBridge(self.state, self.binding, guard=self.guard,
                               writer=self.writer, clock=lambda: self.now, **kwargs)

    def request(self, tool='task_ask', arguments=None, call='call', rpc=1):
        if arguments is None:
            arguments = {'question': 'Where should we go?'} if tool == 'task_ask' else {'summary': 'Prepared'}
        return {'id': rpc, 'method': 'item/tool/call', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'callId': call,
            'tool': tool, 'arguments': arguments}}

    def handle(self, request=None, bridge=None):
        return (bridge or self.bridge).handle(request or self.request(), deadline=100.0)

    def reject(self, request):
        before = (len(self.calls), self.enters)
        with self.assertRaises(BridgeError):
            self.handle(request)
        self.assertEqual((len(self.calls), self.enters), before)

    def journal(self):
        candidates = []
        for path in self.state.iterdir():
            if path.is_file():
                try:
                    json.loads(path.read_text())
                    candidates.append(path)
                except (ValueError, UnicodeError):
                    pass
        self.assertEqual(len(candidates), 1, 'one observed JSON journal')
        return candidates[0]

    # FR-CXBRIDGE-01 / INV-CXBRIDGE-01
    def test_declarations_are_fresh_and_match_public_schemas(self):
        declarations = dynamic_tools()
        self.assertEqual(len(declarations), 2)
        self.assertEqual({d['name'] for d in declarations}, {'task_ask', 'task_done'})
        for d in declarations:
            self.assertEqual(d['type'], 'function')
            self.assertIs(d['deferLoading'], False)
            self.assertTrue(d['description'])
            schema = d['inputSchema']
            self.assertEqual(schema['type'], 'object')
            self.assertIs(schema['additionalProperties'], False)
            self.assertEqual(set(schema['properties']), {'question', 'context', 'options'} if d['name'] == 'task_ask' else {'summary'})
            self.assertEqual(schema.get('required', []), ['question'] if d['name'] == 'task_ask' else [])
        declarations[0]['inputSchema']['properties'].clear()
        self.assertTrue(dynamic_tools()[0]['inputSchema']['properties'])

    def test_response_exactly_addresses_current_request(self):
        for rpc in ['rpc', -(2 ** 63), 2 ** 63 - 1]:
            with self.subTest(rpc=rpc):
                response = self.handle(self.request(rpc=rpc))
                self.assertEqual(response, {'id': rpc, 'result': {'success': True, 'contentItems': [
                    {'type': 'inputText', 'text': json.dumps({'qid': self.qid})}]}})
        self.assertEqual(len(self.calls), 1)

    def test_nonowned_methods_have_no_effects(self):
        for method in ['item/commandExecution/requestApproval', 'item/fileChange/requestApproval', 'other']:
            self.assertIsNone(self.handle({'method': method, 'params': {'arbitrary': True}}))
        self.assertEqual(self.enters, 0)
        self.assertFalse(self.state.exists())

    def test_invalid_envelopes_reject_without_guard(self):
        variants = []
        for key in ['id', 'params']:
            r = self.request(); del r[key]; variants.append(r)
        for value in [True, None, '', 2 ** 63, -(2 ** 63)-1, [], 'x' * 257]:
            r = self.request(); r['id'] = value; variants.append(r)
        for key, value in [('threadId', 'other'), ('turnId', 'other'), ('callId', ''),
                           ('callId', '../call'), ('tool', 'shell'), ('namespace', 'task'), ('extra', 1)]:
            r = self.request(); r['params'][key] = value; variants.append(r)
        for key in ['threadId', 'turnId', 'callId', 'tool', 'arguments']:
            r = self.request(); del r['params'][key]; variants.append(r)
        for key, value in [('extra', True), ('jsonrpc', '1.0')]:
            r = self.request(); r[key] = value; variants.append(r)
        for r in variants:
            with self.subTest(request=r): self.reject(r)

    def test_optional_jsonrpc_and_null_namespace(self):
        r = self.request(); r['jsonrpc'] = '2.0'; r['params']['namespace'] = None
        self.handle(r)

    # FR-CXBRIDGE-02 / INV-CXBRIDGE-02
    def test_argument_negatives_and_utf8_limits(self):
        bad = [{}, {'question': None}, {'question': ' '}, {'question': 'é' * 2049},
               {'question': 'x\x00'}, {'question': 'x', 'context': None},
               {'question': 'x', 'context': 'é' * 4097}, {'question': 'x', 'options': None},
               {'question': 'x', 'options': ['one']}, {'question': 'x', 'options': ['x'] * 9},
               {'question': 'x', 'options': ['a', 'a']}, {'question': 'x', 'options': ['a', ' ']},
               {'question': 'x', 'options': ['a', 'é' * 129]}, {'question': 'x', 'options': ['a', 1]}]
        for key in ['agent_dir', 'event_key', 'engine', 'permissions', 'path']:
            bad.append({'question': 'x', key: 'authority'})
        for args in bad:
            with self.subTest(args=args): self.reject(self.request(arguments=args))
        for args in [None, [], 'text', {'summary': None}, {'summary': 'é' * 2049}, {'summary': '\x7f'}, {'question': 'x'}]:
            r = self.request(tool='task_done'); r['params']['arguments'] = args
            with self.subTest(done=args): self.reject(r)

    def test_valid_boundary_text_and_optional_arguments(self):
        args = {'question': 'é' * 2048, 'context': 'é' * 4096,
                'options': ['é' * 128, 'second\n\tchoice']}
        self.handle(self.request(arguments=args))
        self.handle(self.request('task_done', {}, call='done'))
        self.assertEqual(len(self.calls), 2)

    def test_writer_receives_defensive_copy(self):
        r = self.request(arguments={'question': 'x', 'options': ['a', 'b']})
        original = copy.deepcopy(r)
        self.writer_hook = lambda args: args['options'].append('mutated')
        self.handle(r)
        self.assertEqual(r, original)
        self.handle(r)
        self.assertEqual(len(self.calls), 1)

    def test_guard_requires_literal_true_and_rechecks_replay(self):
        for allowed in [False, None, 1, 'true']:
            self.allowed = allowed
            with self.subTest(allowed=allowed), self.assertRaises(BridgeError): self.handle()
        self.assertEqual(self.calls, [])
        self.allowed = True; self.handle()
        self.allowed = False
        with self.assertRaises(BridgeError): self.handle(bridge=self.make_bridge())
        self.assertEqual(len(self.calls), 1)

    # FR-CXBRIDGE-03 / INV-CXBRIDGE-03
    def test_intent_is_durable_before_writer_and_receipt_survives_reopen(self):
        observations = []
        def hook(args):
            observations.append(json.loads(self.journal().read_text()))
        self.writer_hook = hook
        self.handle()
        self.assertTrue(observations)
        result = self.handle(self.request(rpc='new-id'), bridge=self.make_bridge())
        self.assertEqual(result['id'], 'new-id')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.enters, 2)

    def test_abrupt_writer_interruption_never_retries_intent(self):
        self.writer_error = KeyboardInterrupt()
        with self.assertRaises((KeyboardInterrupt, BridgeError)):
            self.handle()
        self.writer_error = None
        with self.assertRaises(BridgeError): self.handle(bridge=self.make_bridge())
        self.assertEqual(len(self.calls), 1)

    def test_binding_directory_revalidated_before_next_effect(self):
        self.handle()
        self.agent.rmdir()
        with self.assertRaises(BridgeError): self.handle(self.request(call='second'))
        self.assertEqual(len(self.calls), 1)

    def test_same_call_changed_payload_or_tool_conflicts(self):
        self.handle()
        for r in [self.request(arguments={'question': 'changed'}), self.request('task_done')]:
            with self.assertRaises(BridgeError): self.handle(r)
        self.assertEqual(len(self.calls), 1)

    def test_canonical_argument_key_order_replays(self):
        self.handle(self.request(arguments={'question': 'x', 'context': 'y'}))
        self.handle(self.request(arguments={'context': 'y', 'question': 'x'}, rpc=2))
        self.assertEqual(len(self.calls), 1)

    def test_writer_exception_leaves_unresolved_and_hides_text(self):
        secret = 'PRIVATE QUESTION AND EXCEPTION'
        self.writer_error = RuntimeError(secret)
        with self.assertRaises(BridgeError) as caught: self.handle(self.request(arguments={'question': secret}))
        self.assertNotIn(secret, str(caught.exception))
        self.writer_error = None
        with self.assertRaises(BridgeError): self.handle(bridge=self.make_bridge())
        self.assertEqual(len(self.calls), 1)

    def test_invalid_writer_outputs_never_retried(self):
        for index, (tool, result) in enumerate([
            ('task_ask', {'qid': 'not-uuid'}), ('task_ask', {'qid': self.qid, 'extra': 1}),
            ('task_ask', {'qid': self.qid.upper()}), ('task_done', {'requested': 1}),
            ('task_done', {'requested': False}), ('task_done', {'requested': True, 'done': True}),
            ('task_done', []), ('task_ask', {'qid': None})]):
            self.writer_result = result
            r = self.request(tool, call='invalid' + str(index))
            with self.subTest(tool=tool, result=result):
                with self.assertRaises(BridgeError): self.handle(r)
                before = len(self.calls)
                with self.assertRaises(BridgeError): self.handle(r, bridge=self.make_bridge())
                self.assertEqual(len(self.calls), before)

    def test_expired_and_malformed_deadlines_have_no_effect(self):
        for deadline in [True, None, float('nan'), float('inf'), '100', 1.0, 0.0]:
            with self.subTest(deadline=deadline), self.assertRaises(BridgeError):
                self.bridge.handle(self.request(), deadline=deadline)
        self.assertEqual(self.enters, 0)
        self.assertFalse(self.state.exists())

    def test_expiry_after_writer_leaves_unresolved(self):
        self.writer_hook = lambda args: setattr(self, 'now', 101.0)
        with self.assertRaises(BridgeError): self.handle()
        self.now = 1.0; self.writer_hook = None
        with self.assertRaises(BridgeError): self.handle(bridge=self.make_bridge())
        self.assertEqual(len(self.calls), 1)

    def test_fsync_failure_before_intent_prevents_writer(self):
        with patch('os.fsync', side_effect=OSError('PRIVATE FSYNC TEXT')):
            with self.assertRaises(BridgeError) as caught: self.handle()
        self.assertNotIn('PRIVATE FSYNC TEXT', str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_receipt_fsync_failure_leaves_uncertain(self):
        real_fsync = os.fsync
        def fail_after_writer(fd):
            if self.calls: raise OSError('receipt failed')
            return real_fsync(fd)
        with patch('os.fsync', side_effect=fail_after_writer):
            with self.assertRaises(BridgeError): self.handle()
        with self.assertRaises(BridgeError): self.handle(bridge=self.make_bridge())
        self.assertEqual(len(self.calls), 1)

    def test_directory_fsync_failure_after_receipt_replace_never_repeats_writer(self):
        real_fsync = os.fsync
        injected = []
        def fail_receipt_directory_sync(fd):
            if self.calls and stat.S_ISDIR(os.fstat(fd).st_mode):
                # Discover our own persisted JSON; do not assume journal field names.
                observed = json.loads(self.journal().read_text())
                if self.qid in json.dumps(observed):
                    injected.append(True)
                    raise OSError('PRIVATE DIRECTORY FSYNC ERROR')
            return real_fsync(fd)
        with patch('os.fsync', side_effect=fail_receipt_directory_sync):
            with self.assertRaises(BridgeError) as caught: self.handle()
        self.assertTrue(injected, 'fault must occur with writer result already persisted')
        self.assertNotIn('PRIVATE DIRECTORY FSYNC ERROR', str(caught.exception))
        self.assertEqual(len(self.calls), 1)
        refreshed = []
        def observe_storage_sync(fd):
            self.assertTrue(self.active, 'storage recovery must remain fenced')
            refreshed.append(stat.S_ISDIR(os.fstat(fd).st_mode))
            return real_fsync(fd)
        with patch('os.fsync', side_effect=observe_storage_sync):
            try:
                response = self.handle(self.request(rpc='receipt-replay'), bridge=self.make_bridge())
            except BridgeError:
                # A fail-closed reopen is permitted; uncertain effects never repeat.
                pass
            else:
                self.assertIn(True, refreshed, 'replay requires a fresh storage fsync')
                self.assertEqual(response, {'id': 'receipt-replay', 'result': {
                    'success': True, 'contentItems': [{'type': 'inputText',
                    'text': json.dumps({'qid': self.qid})}]}})
        self.assertEqual(len(self.calls), 1)

    # FR-CXBRIDGE-04 / INV-CXBRIDGE-04
    def test_private_storage_and_no_raw_text(self):
        text = 'PRIVATE UNIQUE MODEL TEXT'
        self.handle(self.request(arguments={'question': text, 'context': text}))
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        for p in self.state.iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(p.stat().st_nlink, 1)
            self.assertNotIn(text.encode(), p.read_bytes())
        self.assertEqual(list(self.agent.iterdir()), [])

    def test_state_inside_agent_or_ancestor_rejected(self):
        for state in [self.agent, self.agent / 'state', self.root]:
            with self.subTest(state=state):
                with self.assertRaises(BridgeError):
                    bridge = CodexTaskBridge(state, self.binding, guard=self.guard, writer=self.writer, clock=lambda: 1)
                    self.handle(bridge=bridge)
        self.assertEqual(self.calls, [])

    def test_existing_insecure_directory_not_repaired(self):
        self.state.mkdir(mode=0o755); self.state.chmod(0o755)
        with self.assertRaises(BridgeError): self.handle()
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.calls, [])

    def test_symlink_state_rejected(self):
        target = self.root / 'target'; target.mkdir(mode=0o700)
        self.state.symlink_to(target, target_is_directory=True)
        with self.assertRaises(BridgeError): self.handle()
        self.assertEqual(self.calls, [])

    def test_corrupt_duplicate_and_wrong_schema_journal_rejected(self):
        self.handle(); journal = self.journal(); original = journal.read_bytes()
        for payload in [b'{', b'{"x":1,"x":2}', b'{}', b'[]', b'x' * (1024*1024 + 1)]:
            journal.write_bytes(payload)
            with self.subTest(payload=payload[:30]), self.assertRaises(BridgeError): self.handle(bridge=self.make_bridge())
            self.assertEqual(len(self.calls), 1)
            journal.write_bytes(original)

    def test_symlink_and_hardlinked_journal_rejected(self):
        self.handle(); journal = self.journal(); backup = self.root / 'backup'
        journal.rename(backup); journal.symlink_to(backup)
        with self.assertRaises(BridgeError): self.handle(bridge=self.make_bridge())
        journal.unlink(); os.link(backup, journal)
        with self.assertRaises(BridgeError): self.handle(bridge=self.make_bridge())
        self.assertEqual(len(self.calls), 1)

    def test_existing_lock_with_missing_journal_rejects_same_and_new_calls(self):
        self.handle()
        journal = self.journal()
        lock_candidates = [path for path in self.state.iterdir() if path != journal]
        self.assertEqual(len(lock_candidates), 1, 'one observed non-JSON lock')
        lock = lock_candidates[0]
        with self.assertRaises((ValueError, UnicodeError)):
            json.loads(lock.read_text())
        journal.unlink()
        for call in ['call', 'new-call']:
            with self.subTest(call=call), self.assertRaises(BridgeError):
                self.handle(self.request(call=call), bridge=self.make_bridge())
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(lock.exists())
            self.assertFalse(journal.exists())

    def test_existing_journal_with_missing_lock_rejects_same_and_new_calls(self):
        self.handle()
        journal = self.journal()
        lock_candidates = [path for path in self.state.iterdir() if path != journal]
        self.assertEqual(len(lock_candidates), 1, 'one observed non-JSON lock')
        lock = lock_candidates[0]
        with self.assertRaises((ValueError, UnicodeError)):
            json.loads(lock.read_text())
        lock.unlink()
        for call in ['call', 'new-call']:
            with self.subTest(call=call), self.assertRaises(BridgeError):
                self.handle(self.request(call=call), bridge=self.make_bridge())
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(journal.exists())
            self.assertFalse(lock.exists())

    def test_changed_binding_cannot_reuse_journal(self):
        self.handle()
        for field in ['task_incarnation', 'event_key', 'thread_id', 'turn_id']:
            values = dict(task_incarnation='incarnation', event_key='event', agent_dir=str(self.agent), thread_id='thread', turn_id='turn')
            values[field] = 'changed'
            binding = TaskBinding(**values)
            @contextlib.contextmanager
            def matching_guard(binding, *, deadline): yield True
            with self.subTest(field=field), self.assertRaises(BridgeError):
                bridge = CodexTaskBridge(self.state, binding, guard=matching_guard, writer=self.writer, clock=lambda: 1)
                r = self.request(); r['params']['threadId'] = binding.thread_id; r['params']['turnId'] = binding.turn_id
                self.handle(r, bridge=bridge)
        self.assertEqual(len(self.calls), 1)

    def test_lock_contention_is_nonblocking_and_prevents_writer(self):
        import fcntl
        self.handle()
        files = list(self.state.iterdir())
        with contextlib.ExitStack() as stack:
            for path in files:
                fd = stack.enter_context(path.open('rb'))
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BridgeError): self.handle(self.request(call='new'), bridge=self.make_bridge())
        self.assertEqual(len(self.calls), 1)

    def test_call_capacity_preserves_existing_receipts(self):
        for i in range(256): self.handle(self.request(call='call' + str(i)))
        with self.assertRaises(BridgeError): self.handle(self.request(call='overflow'))
        self.assertEqual(len(self.calls), 256)
        self.handle(self.request(call='call0', rpc='replay'), bridge=self.make_bridge())
        self.assertEqual(len(self.calls), 256)

    # FR-CXBRIDGE-05 / INV-CXBRIDGE-05
    def test_done_only_requests_and_does_not_cleanup(self):
        marker = self.agent / 'keep'; marker.write_text('task remains')
        result = self.handle(self.request('task_done'))
        self.assertEqual(json.loads(result['result']['contentItems'][0]['text']), {'requested': True})
        self.assertEqual(marker.read_text(), 'task remains')
        self.assertEqual(list(self.agent.iterdir()), [marker])

    def test_import_and_constructor_are_inert(self):
        before = dict(os.environ)
        with patch('subprocess.Popen', side_effect=AssertionError('process forbidden')):
            module = importlib.reload(sys.modules['_codex_task_bridge'])
            globals().update(BridgeError=module.BridgeError, TaskBinding=module.TaskBinding,
                             CodexTaskBridge=module.CodexTaskBridge, dynamic_tools=module.dynamic_tools)
            self.binding = TaskBinding('incarnation', 'event', str(self.agent), 'thread', 'turn')
            self.make_bridge()
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(self.enters, 0)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.state.exists())

    def test_guard_enter_exception_is_safe_and_has_no_effect(self):
        @contextlib.contextmanager
        def failing_guard(binding, *, deadline):
            raise RuntimeError('PRIVATE GUARD ERROR')
            yield True
        bridge = CodexTaskBridge(self.state, self.binding, guard=failing_guard,
                                 writer=self.writer, clock=lambda: self.now)
        with self.assertRaises(BridgeError) as caught: self.handle(bridge=bridge)
        self.assertNotIn('PRIVATE GUARD ERROR', str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_guard_exit_failure_is_safe(self):
        @contextlib.contextmanager
        def failing_exit(binding, *, deadline):
            self.active = True
            try:
                yield True
            finally:
                self.active = False
                raise RuntimeError('PRIVATE EXIT ERROR')
        bridge = CodexTaskBridge(self.state, self.binding, guard=failing_exit,
                                 writer=self.writer, clock=lambda: self.now)
        with self.assertRaises(BridgeError) as caught: self.handle(bridge=bridge)
        self.assertNotIn('PRIVATE EXIT ERROR', str(caught.exception))
        self.assertEqual(len(self.calls), 1)
        self.handle(bridge=self.make_bridge())
        self.assertEqual(len(self.calls), 1)

    def test_deadline_expiring_in_guard_prevents_writer(self):
        @contextlib.contextmanager
        def slow_guard(binding, *, deadline):
            self.now = 101.0
            yield True
        bridge = CodexTaskBridge(self.state, self.binding, guard=slow_guard,
                                 writer=self.writer, clock=lambda: self.now)
        with self.assertRaises(BridgeError): self.handle(bridge=bridge)
        self.assertEqual(self.calls, [])

    def test_invalid_binding_and_callbacks_rejected_at_construction(self):
        for field in ['task_incarnation', 'event_key', 'thread_id', 'turn_id']:
            for value in ['', ' padded ', 'a/b', 'a\\b', 'x\n', 'é' * 129]:
                values = dict(task_incarnation='incarnation', event_key='event', agent_dir=str(self.agent), thread_id='thread', turn_id='turn')
                values[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(BridgeError):
                    CodexTaskBridge(self.state, TaskBinding(**values), guard=self.guard, writer=self.writer)
        for path in ['relative', str(self.root / 'missing'), str(self.agent / '..' / 'agent')]:
            with self.subTest(agent=path), self.assertRaises(BridgeError):
                CodexTaskBridge(self.state, TaskBinding('i','e',path,'t','u'), guard=self.guard, writer=self.writer)
        for guard, writer in [(None, self.writer), (self.guard, None)]:
            with self.assertRaises(BridgeError): CodexTaskBridge(self.state, self.binding, guard=guard, writer=writer)


if __name__ == '__main__':
    unittest.main()
