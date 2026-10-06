"""Public-contract RED for explicit configured-context session creation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
import uuid

_BIN = str(Path(__file__).resolve().parents[1] / 'bin')
_TESTS = str(Path(__file__).resolve().parent)
for _path in (_BIN, _TESTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from _control_web_sessions import InteractiveRPC  # noqa: E402

try:
    import _control_web_configured_create as configured_create  # noqa: E402
except Exception as exc:  # Missing feature must be a semantic RED, not loader ERROR.
    configured_create = None
    _IMPORT_ERROR = type(exc).__name__
else:
    _IMPORT_ERROR = None


PROJECT = 'alpha'
OPERATION = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
SID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
CONTEXT_ID = 'c' * 64
NATIVE_VERSION = '0.160.0'


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def expected_digest(project, operation_id, context_id, root):
    return hashlib.sha256(canonical_json({
        'kind': 'configured_session_create', 'project': project,
        'operation_id': operation_id, 'context_mode': 'configured',
        'provider_id': 'codex', 'context_id': context_id, 'root': root,
    })).hexdigest()


def stage_name(stage, project, operation_id):
    kinds = {'R': 'configured_create_receipt',
             'C': 'configured_create_candidate',
             'A': 'configured_create_accepted'}
    token = hashlib.sha256(canonical_json({
        'kind': kinds[stage], 'project': project, 'operation_id': operation_id,
    })).hexdigest()
    return token + '.json'


def origin_name(context_id, root, sid):
    return hashlib.sha256(canonical_json({
        'kind': 'configured_session_origin', 'context_id': context_id,
        'root': root, 'sid': sid,
    })).hexdigest() + '.json'


class FakeRPC:
    def __init__(self):
        self.context = {
            'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
            'context_id': CONTEXT_ID, 'transport_generation': 7,
            'context_generation': 3, 'native_version': NATIVE_VERSION,
        }
        self.prepares = 0
        self.calls = []
        self.start_error = None
        self.start_result = None
        self.read_results = []
        self.on_prepare = None
        self.on_start = None

    def prepare_context(self, timeout=None):
        self.prepares += 1
        if self.on_prepare:
            self.on_prepare()
        return dict(self.context)

    def model_context(self):
        return dict(self.context)

    def receipt_context(self):
        return {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                'context_id': CONTEXT_ID}

    def call_in_generation(self, method, params, *, transport_generation,
                           context_generation, timeout=None):
        self.calls.append((method, dict(params), transport_generation, context_generation))
        if (transport_generation != self.context['transport_generation']
                or context_generation != self.context['context_generation']):
            raise RuntimeError('synthetic captured generation mismatch')
        if method == 'thread/start':
            if self.on_start:
                self.on_start()
            if self.start_error:
                raise self.start_error
            root = params.get('cwd')
            return self.start_result or {'thread': {'id': SID, 'cwd': root}}
        if method == 'thread/loaded/list':
            return {'data': [SID], 'nextCursor': None}
        if method == 'thread/read':
            if self.read_results:
                result = self.read_results.pop(0)
                if isinstance(result, BaseException):
                    raise result
                return result
            return {'thread': {'id': params.get('threadId'), 'cwd': self.last_root,
                               'name': None}}
        raise AssertionError('unexpected native method: ' + method)

    @property
    def last_root(self):
        return next((params['cwd'] for method, params, _, _ in reversed(self.calls)
                     if method == 'thread/start'), None)


class ConfiguredCreateModuleContract(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='control-configured-create-', dir='/var/tmp'))
        self.base.chmod(0o700)
        self.root = self.base / 'project'
        self.root.mkdir(mode=0o700)
        self.root = self.root.resolve(strict=True)
        self.alternate_root = self.base / 'alternate-project'
        self.alternate_root.mkdir(mode=0o700)
        self.alternate_root = self.alternate_root.resolve(strict=True)
        self.receipt_dir = self.base / 'web-send-receipts'
        os.chmod(self.base, 0o700)
        self.allowed = {PROJECT}
        self.rpc = FakeRPC()
        self.path_calls = []

        def project_path(name):
            self.path_calls.append(name)
            if name not in self.allowed:
                raise PermissionError('synthetic grant denied')
            return str(self.root)

        self.project_path = project_path
        self.names = lambda: sorted(self.allowed)
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def api(self):
        self.assertIsNotNone(
            configured_create,
            'ConfiguredSessionCreate/ConfiguredCreateStore public module is absent'
            + (': ' + _IMPORT_ERROR if _IMPORT_ERROR else ''),
        )
        self.assertTrue(hasattr(configured_create, 'ConfiguredSessionCreate'),
                        'ConfiguredSessionCreate public owner type is absent')
        self.assertTrue(hasattr(configured_create, 'ConfiguredCreateStore'),
                        'ConfiguredCreateStore public store type is absent')
        self.assertTrue(hasattr(configured_create, 'ConfiguredCreateReservation'),
                        'ConfiguredCreateReservation frozen handle type is absent')
        return configured_create

    def owner(self, *, store=None):
        api = self.api()
        return api.ConfiguredSessionCreate(
            self.rpc, self.project_path, self.names, str(self.receipt_dir), store=store)

    def error_code(self, callback, expected):
        try:
            result = callback()
        except Exception as exc:
            self.assertEqual(getattr(exc, 'code', None), expected,
                             'method must expose only its documented safe error code')
        else:
            self.assertEqual(result, {'error': expected})

    def _records(self):
        directory = self.base / 'web-configured-create-receipts'
        return directory, {path.name: json.loads(path.read_text(encoding='utf-8'))
                           for path in directory.glob('*.json')}

    def test_options_are_exact_fresh_capability_dto_without_reservation(self):
        result = self.owner().options(PROJECT)
        self.assertEqual(result, {'schema': 1, 'project': PROJECT, 'options': [{
            'context_mode': 'configured', 'provider_id': 'codex',
            'available': True, 'reason': None,
        }]})
        self.assertEqual(self.rpc.prepares, 1)
        self.assertEqual(self.rpc.calls, [])
        self.assertFalse((self.base / 'web-configured-create-receipts').exists())

    def test_unsupported_context_is_unavailable_and_never_falls_back(self):
        self.rpc.context['context_kind'] = 'bound'
        result = self.owner().options(PROJECT)
        self.assertEqual(result, {'schema': 1, 'project': PROJECT, 'options': [{
            'context_mode': 'configured', 'provider_id': 'codex',
            'available': False, 'reason': 'unavailable',
        }]})
        self.assertEqual(self.rpc.calls, [])
        self.assertFalse((self.base / 'web-configured-create-receipts').exists())

    def test_create_publishes_exact_r_c_a_chain_and_safe_accepted_dto(self):
        result = self.owner().create(PROJECT, OPERATION, 'configured', 'codex')
        self.assertEqual(set(result), {'operation_id', 'status', 'session'})
        self.assertEqual(result['operation_id'], OPERATION)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['session'], {
            'sid': SID, 'project': PROJECT, 'vendor': 'codex',
            'context_mode': 'configured', 'title': None,
        })
        methods = [method for method, *_ in self.rpc.calls]
        self.assertEqual(methods.count('thread/start'), 1)
        self.assertEqual(methods.count('thread/loaded/list'), 1)
        self.assertEqual(methods.count('thread/read'), 1)
        self.assertTrue(all((transport, context) == (7, 3)
                            for _, _, transport, context in self.rpc.calls))
        self.assertIn(('thread/start', {'cwd': str(self.root)}, 7, 3), self.rpc.calls)
        self.assertIn(('thread/read', {'threadId': SID, 'includeTurns': False}, 7, 3),
                      self.rpc.calls)
        directory, records = self._records()
        self.assertEqual(set(records), {stage_name(k, PROJECT, OPERATION) for k in 'RCA'}
                         | {origin_name(CONTEXT_ID, str(self.root), SID)})
        r = records[stage_name('R', PROJECT, OPERATION)]
        self.assertEqual(set(r), {'schema', 'kind', 'project', 'operation_id', 'context_id',
                                  'root', 'digest', 'status', 'sid', 'created'})
        self.assertEqual(r, {
            'schema': 1, 'kind': 'configured_session_create', 'project': PROJECT,
            'operation_id': OPERATION, 'context_id': CONTEXT_ID, 'root': str(self.root),
            'digest': expected_digest(PROJECT, OPERATION, CONTEXT_ID, str(self.root)),
            'status': 'unknown', 'sid': None, 'created': r['created'],
        })
        self.assertIs(type(r['created']), int)
        self.assertGreater(r['created'], 0)
        c = records[stage_name('C', PROJECT, OPERATION)]
        a = records[stage_name('A', PROJECT, OPERATION)]
        self.assertEqual(set(c), {'schema', 'kind', 'record', 'parent'})
        self.assertEqual(set(a), {'schema', 'kind', 'record', 'parent', 'origin'})
        self.assertEqual((c['schema'], c['kind']), (1, 'configured_create_candidate'))
        self.assertEqual((a['schema'], a['kind']), (1, 'configured_create_accepted'))
        self.assertEqual(c['record']['status'], 'unknown')
        self.assertEqual(c['record']['sid'], SID)
        self.assertEqual(a['record']['status'], 'accepted')
        for field in ('schema', 'kind', 'project', 'operation_id', 'context_id',
                      'root', 'digest', 'created'):
            self.assertEqual(c['record'][field], r[field])
            self.assertEqual(a['record'][field], r[field])
        self.assertEqual(a['record']['sid'], SID)
        origin = records[origin_name(CONTEXT_ID, str(self.root), SID)]
        self.assertEqual(set(origin), {'schema', 'kind', 'project', 'operation_id',
                                       'context_id', 'root', 'sid', 'created', 'parent'})
        self.assertEqual((origin['schema'], origin['kind']), (1, 'configured_session_origin'))
        self.assertEqual(origin['created'], r['created'])
        self.assertEqual(origin['parent']['filename'], stage_name('C', PROJECT, OPERATION))
        self.assertEqual(set(a['origin']), {'filename', 'dev', 'ino', 'ctime_ns', 'sha256'})
        self.assertEqual(a['origin']['filename'], origin_name(CONTEXT_ID, str(self.root), SID))
        for stage, wrapper, parent_stage in (('C', c, 'R'), ('A', a, 'C')):
            parent = wrapper['parent']
            self.assertEqual(set(parent), {'filename', 'dev', 'ino', 'ctime_ns', 'sha256'})
            self.assertEqual(parent['filename'], stage_name(parent_stage, PROJECT, OPERATION))
            self.assertTrue(all(type(parent[key]) is int and parent[key] >= 0
                                for key in ('dev', 'ino', 'ctime_ns')))
            self.assertRegex(parent['sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(stat.S_IMODE((directory / stage_name('R', PROJECT, OPERATION)).stat().st_mode),
                         0o600)
        self.assertFalse(set(result) & {'account_id', 'session_ref', 'root', 'context_id',
                                       'peer', 'generation', 'history', 'preview'})

    def test_exact_create_replay_never_dispatches_second_start(self):
        rpc = self.rpc
        rpc.start_error = TimeoutError('synthetic transport uncertainty')
        first = self.owner().create(PROJECT, OPERATION, 'configured', 'codex')
        self.assertEqual(first, {'operation_id': OPERATION, 'status': 'delivery_unknown'})
        before = list(rpc.calls)
        second = self.owner().create(PROJECT, OPERATION, 'configured', 'codex')
        self.assertEqual(second, {'operation_id': OPERATION, 'status': 'delivery_unknown'})
        self.assertEqual(rpc.calls, before)
        self.assertEqual([method for method, *_ in rpc.calls], ['thread/start'])
        directory, records = self._records()
        self.assertEqual(set(records), {stage_name('R', PROJECT, OPERATION)})
        self.assertEqual(records[stage_name('R', PROJECT, OPERATION)]['sid'], None)

    def test_manual_status_proves_only_stored_candidate_without_start_retry(self):
        self.rpc.read_results = [RuntimeError('synthetic metadata read unavailable')]
        created = self.owner().create(PROJECT, OPERATION, 'configured', 'codex')
        self.assertEqual(created, {'operation_id': OPERATION, 'status': 'delivery_unknown'})
        methods_before = [method for method, *_ in self.rpc.calls]
        self.assertEqual(methods_before.count('thread/start'), 1)
        self.assertEqual(methods_before.count('thread/read'), 1)
        self.assertTrue(set(methods_before) <= {
            'thread/start', 'thread/read', 'thread/loaded/list'})
        directory, records = self._records()
        self.assertEqual(set(records), {
            stage_name('R', PROJECT, OPERATION), stage_name('C', PROJECT, OPERATION)})
        checked = self.owner().status(PROJECT, OPERATION, 'configured', 'codex')
        self.assertEqual(checked, {
            'operation_id': OPERATION, 'status': 'accepted',
            'session': {'sid': SID, 'project': PROJECT, 'vendor': 'codex',
                        'context_mode': 'configured', 'title': None},
        })
        self.assertEqual([method for method, *_ in self.rpc.calls].count('thread/start'), 1)
        self.assertEqual([method for method, *_ in self.rpc.calls].count('thread/read'), 2)
        self.assertGreaterEqual([method for method, *_ in self.rpc.calls].count('thread/loaded/list'), 1)
        directory, records = self._records()
        self.assertEqual(set(records), {stage_name(k, PROJECT, OPERATION) for k in 'RCA'}
                         | {origin_name(CONTEXT_ID, str(self.root), SID)})

    def test_invalid_selector_or_operation_id_fails_before_rpc_or_storage(self):
        owner = self.owner()
        self.error_code(lambda: owner.create(PROJECT, OPERATION.upper(), 'configured', 'codex'),
                        'invalid_request')
        self.error_code(lambda: owner.create(PROJECT, OPERATION, 'configured', 'claude'),
                        'invalid_request')
        self.assertEqual(self.rpc.prepares, 0)
        self.assertEqual(self.rpc.calls, [])
        self.assertFalse((self.base / 'web-configured-create-receipts').exists())

    def test_revoked_fresh_grant_prevents_reservation_and_native_effect(self):
        owner = self.owner()
        self.rpc.on_prepare = lambda: self.allowed.clear()
        self.error_code(lambda: owner.create(PROJECT, OPERATION, 'configured', 'codex'),
                        'forbidden')
        self.assertEqual(self.rpc.calls, [])
        self.assertFalse((self.base / 'web-configured-create-receipts').exists())

    def test_generation_drift_after_reservation_never_dispatches_metadata_read(self):
        self.rpc.on_start = lambda: self.rpc.context.__setitem__('context_generation', 4)
        result = self.owner().create(PROJECT, OPERATION, 'configured', 'codex')
        self.assertEqual(result, {'operation_id': OPERATION, 'status': 'delivery_unknown'})
        self.assertEqual([method for method, *_ in self.rpc.calls], ['thread/start'])
        directory, records = self._records()
        self.assertEqual(set(records), {stage_name('R', PROJECT, OPERATION)})
        self.assertNotIn(SID, json.dumps(result))

    def test_fresh_root_drift_after_dispatch_preserves_unknown_without_sid_export(self):
        original_root = self.root
        self.rpc.on_start = lambda: setattr(self, 'root', self.alternate_root)
        result = self.owner().create(PROJECT, OPERATION, 'configured', 'codex')
        self.assertEqual(result, {'operation_id': OPERATION, 'status': 'delivery_unknown'})
        self.assertEqual([method for method, *_ in self.rpc.calls], ['thread/start'])
        directory, records = self._records()
        self.assertEqual(set(records), {stage_name('R', PROJECT, OPERATION)})
        self.assertEqual(records[stage_name('R', PROJECT, OPERATION)]['root'], str(original_root))
        self.assertNotIn(SID, json.dumps(result))

    def test_configured_store_records_are_exact_parent_committed_and_replayable(self):
        api = self.api()
        store_path = self.base / 'private-store'
        store = api.ConfiguredCreateStore(str(store_path), clock=lambda: 1700000000000000123)
        deadline = time.monotonic() + 4
        root = str(self.root)
        with store.locked(deadline, create=True) as base:
            reservation = store.reserve(base, PROJECT, CONTEXT_ID, root, OPERATION, deadline)
            self.assertIsInstance(reservation, api.ConfiguredCreateReservation)
            replay = store.lookup(base, PROJECT, OPERATION, deadline)
            self.assertIsNotNone(replay)
            self.assertEqual(replay.record, reservation.record)
            candidate = store.candidate(base, reservation, SID, deadline)
            store.origin(base, reservation, deadline)
            accepted = store.accept(base, reservation, deadline)
            self.assertEqual(accepted.record['status'], 'accepted')
            self.assertEqual(accepted.record['sid'], SID)
            with self.assertRaises((AttributeError, TypeError)):
                accepted.record['status'] = 'unknown'
            with self.assertRaises((AttributeError, TypeError)):
                accepted.record = {}
            self.assertNotIn(str(store_path), repr(accepted))
        files = {path.name: json.loads(path.read_text(encoding='utf-8'))
                 for path in store_path.glob('*.json')}
        self.assertEqual(set(files), {stage_name(k, PROJECT, OPERATION) for k in 'RCA'}
                         | {origin_name(CONTEXT_ID, root, SID)})
        self.assertEqual(files[stage_name('R', PROJECT, OPERATION)]['digest'],
                         expected_digest(PROJECT, OPERATION, CONTEXT_ID, root))
        c = files[stage_name('C', PROJECT, OPERATION)]
        a = files[stage_name('A', PROJECT, OPERATION)]
        origin = files[origin_name(CONTEXT_ID, root, SID)]
        self.assertEqual(c['record']['status'], 'unknown')
        self.assertEqual(c['record']['sid'], SID)
        self.assertEqual(a['record']['status'], 'accepted')
        self.assertEqual(a['parent']['filename'], stage_name('C', PROJECT, OPERATION))
        self.assertEqual(c['parent']['filename'], stage_name('R', PROJECT, OPERATION))
        self.assertEqual(origin['created'], files[stage_name('R', PROJECT, OPERATION)]['created'])
        self.assertEqual(origin['parent']['filename'], stage_name('C', PROJECT, OPERATION))
        self.assertEqual(a['origin']['filename'], origin_name(CONTEXT_ID, root, SID))
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600
                            for path in store_path.glob('*.json')))

        capped_path = self.base / 'capped-store'
        capped = api.ConfiguredCreateStore(str(capped_path), clock=lambda: 1700000000000000123)
        with capped.locked(time.monotonic() + 4, create=True):
            for _ in range(10002):
                (capped_path / ('.tmp-' + uuid.uuid4().hex)).touch(mode=0o600)
        before = {path.name for path in capped_path.iterdir()}
        with capped.locked(time.monotonic() + 4) as base:
            self.error_code(lambda: capped.reserve(
                base, PROJECT, CONTEXT_ID, root, OPERATION, time.monotonic() + 4), 'unavailable')
        self.assertEqual({path.name for path in capped_path.iterdir()}, before)

    def test_store_rejects_context_rebinding_and_known_accepted_missing_parent(self):
        api = self.api()
        store_path = self.base / 'private-store'
        store = api.ConfiguredCreateStore(str(store_path), clock=lambda: 1700000000000000123)
        deadline = time.monotonic() + 4
        with store.locked(deadline, create=True) as base:
            reservation = store.reserve(base, PROJECT, CONTEXT_ID, str(self.root), OPERATION, deadline)
            self.error_code(lambda: store.reserve(
                base, PROJECT, 'd' * 64, str(self.root), OPERATION, deadline), 'invalid_request')
            candidate = store.candidate(base, reservation, SID, deadline)
            store.origin(base, reservation, deadline)
            accepted = store.accept(base, reservation, deadline)
        (store_path / stage_name('C', PROJECT, OPERATION)).unlink()
        with store.locked(time.monotonic() + 4) as base:
            self.error_code(lambda: store.accept(base, accepted, time.monotonic() + 4),
                            'unavailable')


class ConfiguredTransportContract(unittest.TestCase):
    def test_interactive_rpc_prepare_and_fixed_start_allowlist_over_owned_unix_socket(self):
        self.assertTrue(callable(getattr(InteractiveRPC, 'prepare_context', None)),
                        'InteractiveRPC.prepare_context public owner seam is absent')
        self.assertIn('thread/start', InteractiveRPC.METHODS,
                      'InteractiveRPC fixed allowlist omits configured thread/start')
        from websockets.sync.server import unix_serve

        base = Path(tempfile.mkdtemp(prefix='control-configured-rpc-', dir='/var/tmp'))
        base.chmod(0o700)
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        socket_path = str(base / 'rpc.sock')
        root = str((base / 'project').resolve())
        Path(root).mkdir(mode=0o700)
        received = []

        def handler(ws):
            try:
                for message in ws:
                    request = json.loads(message)
                    if 'method' not in request or 'id' not in request:
                        continue
                    received.append((request['method'], request.get('params')))
                    if request['method'] == 'initialize':
                        ws.send(json.dumps({'id': request['id'], 'result': {
                            'userAgent': 'codex/0.160.0 (synthetic)'}}))
                    elif request['method'] == 'thread/start':
                        ws.send(json.dumps({'id': request['id'], 'result': {
                            'thread': {'id': SID, 'cwd': root}}}))
                    else:
                        ws.send(json.dumps({'id': request['id'], 'result': {}}))
            except (OSError, ConnectionError):
                pass

        server = unix_serve(handler, socket_path)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join, 2)
        self.addCleanup(server.shutdown)
        deadline = time.monotonic() + 1
        while not os.path.exists(socket_path) and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(os.path.exists(socket_path), 'synthetic Unix WebSocket listener did not start')
        rpc = InteractiveRPC(socket_path, timeout=2)
        self.addCleanup(rpc.close)
        context = rpc.prepare_context(timeout=2)
        self.assertEqual(set(context), {'schema', 'vendor', 'context_kind', 'context_id',
                                        'transport_generation', 'context_generation',
                                        'native_version'})
        self.assertEqual(context['native_version'], NATIVE_VERSION)
        self.assertEqual([method for method, _ in received], ['initialize'])
        response = rpc.call_in_generation(
            'thread/start', {'cwd': root},
            transport_generation=context['transport_generation'],
            context_generation=context['context_generation'], timeout=2)
        self.assertEqual(response, {'thread': {'id': SID, 'cwd': root}})
        self.assertEqual(received, [('initialize', {
            'clientInfo': {'name': 'ai_control_web', 'version': '0.1'},
            'capabilities': {'experimentalApi': True},
        }), ('thread/start', {'cwd': root})])
        existing_methods = {'initialize', 'thread/read', 'thread/list', 'thread/turns/list',
                            'thread/resume', 'turn/start', 'model/list', 'thread/name/set'}
        self.assertEqual(set(InteractiveRPC.METHODS), existing_methods | {
            'thread/start', 'thread/loaded/list'})
        for unsupported in ('account/read', 'config/read'):
            with self.assertRaises(ValueError):
                rpc.call(unsupported, {}, timeout=1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
