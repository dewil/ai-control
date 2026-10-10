"""Synthetic source-blind receipt identity tests for INV-WSESS-26."""
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
SID = '11111111-1111-4111-8111-111111111111'
MID = '22222222-2222-4222-8222-222222222222'
TURN = '33333333-3333-4333-8333-333333333333'
TEXT = 'Synthetic receipt identity draft'


def feature(case, name):
    case.assertTrue((ROOT / 'bin' / (name + '.py')).is_file(),
                    f'Missing public feature {name} from web-session specification')
    return importlib.import_module(name)


class PlainCallableRPC:
    """Callable fake with no identity metadata or generation-aware helper."""
    def __init__(self, root):
        self.root = str(Path(root).resolve())
        self.calls = []

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method in ('thread/read', 'thread/resume'):
            return {'thread': {'id': SID, 'cwd': self.root, 'status': {'type': 'idle'}}}
        if method == 'turn/start':
            return {'turn': {'id': TURN}}
        raise AssertionError('Unexpected synthetic RPC method: ' + method)

    def methods(self):
        return [method for method, _params in self.calls]


class ContextGetterRPC(PlainCallableRPC):
    """Synthetic callable exposing owner metadata through the default RPC getter seam."""
    def __init__(self, root, context):
        super().__init__(root)
        self.context = dict(context)

    def model_context(self):
        return dict(self.context)


class ReceiptContextContract(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-receipt-context-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.project = self.base / 'project'
        self.project.mkdir(mode=0o700)
        self.receipts = self.base / 'receipts'

    def resolve(self, alias):
        if alias != 'demo':
            raise ValueError('synthetic invalid project')
        return str(self.project.resolve())

    def chat(self, rpc, model_context=None):
        cls = self.module.SessionChat
        self.assertTrue(callable(getattr(cls, 'send', None)), 'SessionChat.send is required')
        if model_context is not None:
            params = inspect.signature(cls).parameters
            self.assertIn('model_context', params,
                          'Trusted model_context dependency injection is required by INV-WSESS-26')
        kwargs = {'model_context': model_context} if model_context is not None else {}
        return cls(rpc, self.resolve, lambda: ['demo'], str(self.receipts), **kwargs)

    def receipt_record(self, message_id=MID):
        records = []
        if self.receipts.exists():
            for path in self.receipts.rglob('*'):
                if path.is_file():
                    try:
                        record = json.loads(path.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        continue
                    if isinstance(record, dict) and record.get('message_id') == message_id:
                        records.append((path, record))
        self.assertEqual(len(records), 1, 'Expected exactly one private receipt for the synthetic UUID')
        return records[0]

    def assert_no_receipt(self, message_id=MID):
        found = []
        if self.receipts.exists():
            for path in self.receipts.rglob('*'):
                if not path.is_file():
                    continue
                try:
                    record = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if isinstance(record, dict) and record.get('message_id') == message_id:
                    found.append(path)
        self.assertEqual(found, [], 'Invalid context cannot reserve a legacy fallback receipt')

    def test_INV_WSESS_26_interactive_receipt_context_is_stable_offline_and_alias_scoped(self):
        rpc_class = getattr(self.module, 'InteractiveRPC', None)
        self.assertTrue(callable(rpc_class), 'InteractiveRPC is required by the public session transport contract')
        alias = self.base / 'fixed-owner-alias.sock'
        other_alias = self.base / 'different-owner-alias.sock'
        first_target = self.base / 'native-first.sock'
        second_target = self.base / 'native-second.sock'
        alias.symlink_to(first_target)
        other_alias.symlink_to(first_target)

        signature = inspect.signature(rpc_class)
        try:
            signature.bind(str(alias))
            signature.bind(str(other_alias))
        except TypeError as error:
            self.fail('InteractiveRPC must accept its fixed absolute socket alias: ' + str(error))

        frames = []
        server_errors = []
        connection_versions = ('codex/0.160.0 (synthetic fixture)', 'codex/0.161.0 (synthetic fixture)')
        from websockets.sync.server import unix_serve

        def handler(ws):
            connection_index = sum(1 for frame in frames if '_connection_start' in frame)
            frames.append({'_connection_start': connection_index})
            try:
                while True:
                    frame = json.loads(ws.recv(timeout=3))
                    frames.append(frame)
                    method = frame.get('method')
                    if method == 'initialize':
                        version = connection_versions[min(connection_index, len(connection_versions) - 1)]
                        ws.send(json.dumps({'id': frame['id'], 'result': {
                            'userAgent': version,
                            'codexHome': str(self.base / 'synthetic-codex-home'),
                            'platformFamily': 'unix', 'platformOs': 'linux'}}))
                    elif method == 'initialized':
                        continue
                    elif method == 'thread/read':
                        ws.send(json.dumps({'id': frame['id'], 'result': {
                            'thread': {'id': SID, 'cwd': str(self.project.resolve())}}}))
                    else:
                        server_errors.append('Unexpected synthetic RPC method')
                        return
            except TimeoutError:
                return
            except Exception as error:
                from websockets.exceptions import ConnectionClosed
                if not isinstance(error, ConnectionClosed):
                    server_errors.append(type(error).__name__)

        def start_server(target):
            server = unix_serve(handler, str(target))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            deadline = time.monotonic() + 3
            while not target.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(target.exists(), 'Synthetic Unix socket server did not create its fixture path')
            os.chmod(target, 0o600)
            self.addCleanup(worker.join, 2)
            self.addCleanup(server.shutdown)
            return server

        os.umask(0o077)
        server = start_server(first_target)
        first = rpc_class(str(alias), timeout=1)
        close = getattr(first, 'close', None)
        self.assertTrue(callable(close), 'InteractiveRPC.close is required for deterministic fixture cleanup')
        self.addCleanup(close)

        receipt_method = getattr(first, 'receipt_context', None)
        self.assertTrue(callable(receipt_method),
                        'InteractiveRPC.receipt_context() must expose the stable owner receipt snapshot')
        offline = receipt_method()
        self.assertEqual(set(offline), {'schema', 'vendor', 'context_kind', 'context_id'})
        self.assertEqual((offline['schema'], offline['vendor'], offline['context_kind']),
                         (1, 'codex', 'legacy_unbound'))
        self.assertRegex(offline['context_id'], r'^[0-9a-f]{64}$')
        before_snapshot = len(frames)
        self.assertEqual(first.receipt_context(), offline)
        self.assertEqual(len(frames), before_snapshot,
                         'Reading a receipt snapshot while offline must not dispatch native RPC')

        self.assertEqual(first('thread/read', {'threadId': SID, 'includeTurns': False})['thread']['id'], SID)
        model_context = getattr(first, 'model_context', None)
        self.assertTrue(callable(model_context), 'InteractiveRPC.model_context() is required by INV-WSESS-24')
        live = model_context()
        self.assertIsInstance(live, dict, 'Validated synthetic initialize must expose the live model context')
        self.assertEqual(live['context_id'], offline['context_id'],
                         'Model and receipt contexts share stable owner/vendor identity')
        first.close()
        frame_count = len(frames)
        self.assertEqual(first.receipt_context(), offline,
                         'Receipt snapshot stays available after disconnect')
        self.assertEqual(len(frames), frame_count, 'Disconnected snapshot read must not reconnect or dispatch')

        server2 = start_server(second_target)
        alias.unlink(); alias.symlink_to(second_target)
        second = rpc_class(str(alias), timeout=1)
        self.addCleanup(second.close)
        second_snapshot = second.receipt_context()
        self.assertEqual(second_snapshot['context_id'], offline['context_id'],
                         'A new RPC object and native compatibility version keep the same owner receipt token')
        self.assertEqual(second('thread/read', {'threadId': SID, 'includeTurns': False})['thread']['id'], SID)
        self.assertEqual(second.model_context()['native_version'], '0.161.0',
                         'Reviewed native 0.161 must expose its real compatibility version')
        captured = second.model_context()
        self.assertEqual(second.call_in_generation('thread/read', {'threadId': SID, 'includeTurns': False},
                         transport_generation=captured['transport_generation'],
                         context_generation=captured['context_generation'])['thread']['id'], SID)
        other = rpc_class(str(other_alias), timeout=1)
        self.addCleanup(other.close)
        other_snapshot = other.receipt_context()
        self.assertNotEqual(other_snapshot['context_id'], offline['context_id'],
                            'A different fixed socket alias has a separate receipt namespace')
        self.assertEqual([frame['method'] for frame in frames if frame.get('method')],
                         ['initialize', 'initialized', 'thread/read', 'initialize', 'initialized', 'thread/read', 'thread/read'])
        self.assertEqual(server_errors, [])


    def test_native_0161_capability_preserves_exact_version_fence(self):
        context = dict(schema=1, vendor='codex', context_kind='legacy_unbound',
                       context_id='a' * 64, transport_generation=1,
                       context_generation=0, native_version='0.161.0')
        self.assertIsNone(self.module.SessionChat._catalog_reason(context))
        for version in ('0.159.0', '0.160.1', '0.162.0', None, [], True):
            with self.subTest(version=version):
                self.assertEqual(self.module.SessionChat._catalog_reason(
                    dict(context, native_version=version)), 'unsupported_capability')

    def test_INV_WSESS_26_plain_callable_fallback_is_store_scoped_and_exact_restart_replay_has_no_effects(self):
        cls = self.module.SessionChat
        send = getattr(cls, 'send', None)
        self.assertTrue(callable(send), 'SessionChat.send is required')
        try:
            inspect.signature(send).bind(object(), 'demo', SID, MID, TEXT)
        except TypeError as error:
            self.fail('Existing four-argument inherit sends must remain supported: ' + str(error))
        params = inspect.signature(cls).parameters
        self.assertIn('model_context', params, 'Optional trusted context injection remains supported')
        self.assertIsNone(params['model_context'].default,
                          'Plain callable compatibility must not require new constructor arguments')

        rpc1 = PlainCallableRPC(self.project)
        self.assertFalse(callable(getattr(rpc1, 'model_context', None)))
        self.assertFalse(callable(getattr(rpc1, 'receipt_context', None)))
        first_chat = self.chat(rpc1)
        first = first_chat.send('demo', SID, MID, TEXT)
        self.assertEqual(first, {'status': 'accepted', 'message_id': MID, 'turn_id': TURN})

        expected_input = {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                          'owner_uid': os.getuid(), 'receipt_root': str(self.receipts.resolve())}
        canonical = json.dumps(expected_input, sort_keys=True, ensure_ascii=False,
                               separators=(',', ':'), allow_nan=False).encode('utf-8')
        expected_context_id = hashlib.sha256(canonical).hexdigest()
        path, record = self.receipt_record()
        self.assertEqual(record.get('schema'), 2, 'New inherit sends reserve schema2 receipts')
        self.assertEqual(record.get('context_id'), expected_context_id,
                         'Legacy compatibility identity is canonical store/UID hash, not callable repr')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        original_bytes = path.read_bytes()

        rpc2 = PlainCallableRPC(self.project)
        self.assertIsNot(rpc1, rpc2)
        restarted_chat = self.chat(rpc2)
        replay = restarted_chat.send('demo', SID, MID, TEXT)
        self.assertEqual(replay, first, 'Same store and inherit UUID replay the durable result after chat recreation')
        methods = rpc2.methods()
        self.assertNotIn('model/list', methods, 'Replay cannot discover a catalog')
        self.assertNotIn('thread/resume', methods, 'Replay cannot resume a native thread')
        self.assertNotIn('turn/start', methods, 'Replay cannot dispatch a second turn')
        self.assertEqual(path.read_bytes(), original_bytes, 'Exact replay leaves the receipt immutable')

    def test_INV_WSESS_26_unverified_or_malformed_explicit_context_never_uses_legacy_fallback(self):
        cls = self.module.SessionChat
        params = inspect.signature(cls).parameters
        self.assertIn('model_context', params,
                      'A trusted explicit context dependency is required to test fail-closed metadata')

        contexts = [
            {'schema': 1, 'vendor': 'codex', 'context_kind': 'unverified_bound',
             'context_id': 'b' * 64, 'transport_generation': 3, 'context_generation': 7,
             'native_version': '0.160.0'},
            {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
             'context_id': 'not-a-stable-token', 'transport_generation': 3,
             'context_generation': 7, 'native_version': '0.160.0'},
        ]
        for context in contexts:
            with self.subTest(context_kind=context['context_kind'], context_id=context['context_id'][:8]):
                rpc = PlainCallableRPC(self.project)
                chat = self.chat(rpc, model_context=lambda value=context: dict(value))
                result = chat.send('demo', SID, MID, TEXT)
                self.assertEqual(result, {'error': 'unavailable'},
                                 'Unverified or malformed explicit context must fail closed')
                self.assert_no_receipt()
                self.assertNotIn('thread/resume', rpc.methods())
                self.assertNotIn('turn/start', rpc.methods())

    def test_INV_WSESS_26_non_Codex_or_contradictory_legacy_context_fails_before_send_effects(self):
        params = inspect.signature(self.module.SessionChat).parameters
        self.assertIn('model_context', params,
                      'Trusted model_context injection is required for fail-closed context verification')
        claude_context = {'schema': 1, 'vendor': 'claude', 'context_kind': 'legacy_unbound',
                          'context_id': 'c' * 64, 'transport_generation': 3,
                          'context_generation': 7, 'native_version': 'codex/0.160.0'}

        # Exercise both the explicit trusted dependency and the production-default
        # rpc.model_context getter. The vendor/version contradiction must not turn
        # this into a legacy receipt namespace or fall back to a Codex send.
        cases = (
            ('explicit_dependency', lambda: PlainCallableRPC(self.project),
             lambda: (lambda: dict(claude_context))),
            ('rpc_getter', lambda: ContextGetterRPC(self.project, claude_context), None),
        )
        for label, make_rpc, make_getter in cases:
            with self.subTest(seam=label):
                rpc = make_rpc()
                getter = make_getter() if make_getter else None
                chat = self.chat(rpc, model_context=getter)
                result = chat.send('demo', SID, MID, TEXT)
                methods = rpc.methods()
                found_receipt = any(
                    path.is_file() and path.name.endswith('.json')
                    for path in self.receipts.rglob('*')
                ) if self.receipts.exists() else False
                violations = []
                if result != {'error': 'unavailable'}:
                    violations.append('expected unavailable, got ' + repr(result))
                if found_receipt:
                    violations.append('receipt storage was created/reserved')
                for method in ('model/list', 'thread/resume', 'turn/start'):
                    if method in methods:
                        violations.append('unexpected pre-rejection RPC ' + method)
                self.assertEqual(violations, [],
                                 'Non-Codex/contradictory context must fail before any send effects')

    def test_INV_WSESS_26_supported_Codex_inherit_does_not_depend_on_known_native_version(self):
        context = {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                   'context_id': 'd' * 64, 'transport_generation': 3,
                   'context_generation': 7, 'native_version': 'codex/future-synthetic'}
        rpc = ContextGetterRPC(self.project, context)
        chat = self.chat(rpc)
        result = chat.send('demo', SID, MID, TEXT)
        self.assertEqual(result, {'status': 'accepted', 'message_id': MID, 'turn_id': TURN},
                         'Ordinary Codex inherit remains available when compatibility version is unknown')
        self.assertNotIn('model/list', rpc.methods(), 'Inherit must not probe model catalog')
        self.assertEqual(rpc.methods().count('thread/resume'), 1)
        self.assertEqual(rpc.methods().count('turn/start'), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
