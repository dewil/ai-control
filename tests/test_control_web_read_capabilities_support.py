"""Independent CAP fixtures: actual public adapters over private synthetic Unix RPC."""
import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
from test_control_web_session_chat_contract import RPC, SID, MID, TURN, OTHER, turn

READS = {'thread/list', 'thread/read', 'thread/turns/list', 'thread/items/list', 'thread/loaded/list'}
WRITES = {'thread/start', 'thread/resume', 'thread/name/set', 'turn/start', 'turn/steer',
          'thread/queue/list', 'thread/queue/add', 'thread/queue/start'}
OP = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
OPS = ('sessions_read', 'history_read', 'model_selection', 'send', 'create', 'rename', 'queue')


def expected_capabilities(version='0.999.0', history=False):
    return {'schema': 1, 'native_version': version, 'version_source': 'initialize_reported',
        'version_review': 'unknown' if version is None else 'unreviewed', 'read_status': 'compatible',
        'operations': {'sessions_read': {'supported': True, 'reason': None},
            'history_read': {'supported': True if history else None, 'reason': None if history else 'not_observed'},
            **{name: {'supported': False, 'reason': 'unsupported_native_version'} for name in OPS[2:]}}}


class NativeServer:
    def __init__(self, base, root):
        self.base = base; self.root = root; self.path = base / 'native.sock'; self.alias = base / 'owner-alias.sock'
        self.agent = 'codex/0.999.0 (synthetic platform /private-native-path)'
        self.native = RPC(root); self.frames = []; self.errors = []; self.connections = 0
        self.before_reply = None; self.on_connect = None; self.ws = None
        self.thread_changes = {}; self.list_pages = None; self.loaded = [SID]
        from websockets.sync.server import unix_serve
        def process_request(connection, request):
            self.connections += 1
            if self.on_connect: self.on_connect()
            return None
        def handle(ws):
            self.ws = ws
            try:
                for raw in ws:
                    request = json.loads(raw); self.frames.append(request)
                    method = request.get('method')
                    if method == 'initialized': continue
                    if method == 'initialize':
                        result = {'codexHome': str(base / 'synthetic-codex-home'), 'platformFamily': 'unix', 'platformOs': 'linux'}
                        if self.agent is not None: result['userAgent'] = self.agent
                    elif method == 'thread/loaded/list': result = {'data': list(self.loaded), 'nextCursor': None}
                    elif method == 'thread/read':
                        result = self.native(method, request['params'])
                        result['thread']['id'] = request['params'].get('threadId')
                        result['thread'].update(name='Native safe title', status={'type': 'idle'}, updatedAt=1700000000,
                            model='safe-configured-model', reasoningEffort='safe-custom-effort')
                        result['thread'].update(copy.deepcopy(self.thread_changes))
                    elif method == 'thread/list' and self.list_pages is not None:
                        result = copy.deepcopy(self.list_pages[request['params'].get('cursor')])
                    elif method in READS or method == 'turn/start': result = self.native(method, request.get('params', {}))
                    elif method in WRITES: result = {'thread': {'id': SID, 'cwd': str(root)}} if method in ('thread/start', 'thread/resume') else {}
                    elif method == 'model/list': result = {'data': [], 'nextCursor': None}
                    else: result = {}
                    if self.before_reply and self.before_reply(ws, request, result) is False: continue
                    ws.send(json.dumps({'id': request['id'], 'result': result}))
            except Exception as error:
                from websockets.exceptions import ConnectionClosed
                if not isinstance(error, ConnectionClosed): self.errors.append(type(error).__name__)
        self.server = unix_serve(handle, str(self.path), process_request=process_request)
        self.path.chmod(0o600); self.alias.symlink_to(self.path)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True); self.worker.start()

    def methods(self): return [frame['method'] for frame in self.frames if frame.get('method') not in ('initialize', 'initialized')]
    def stop(self): self.server.shutdown(); self.worker.join(2)


class NativeCase(unittest.TestCase):
    def setUp(self):
        self.sessions = importlib.import_module('_control_web_sessions')
        self.configured = importlib.import_module('_control_web_configured_create')
        temp = tempfile.TemporaryDirectory(prefix='read-cap-blind-', dir='/var/tmp'); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name); self.base.chmod(0o700)
        self.root = self.base / 'project'; self.root.mkdir(mode=0o700)
        self.rebound = self.base / 'other-project'; self.rebound.mkdir(mode=0o700)
        self.active_root = self.root; self.allowed = {'demo'}
        self.native = NativeServer(self.base, self.root); self.addCleanup(self.native.stop)
        self.rpc = self.sessions.InteractiveRPC(str(self.native.alias), timeout=1); self.addCleanup(self.rpc.close)
        self.send_path = self.base / 'send-receipts'; self.store_path = self.base / 'configured-store'
        self.store = self.configured.ConfiguredCreateStore(str(self.store_path))
        # Public store methods seed a synthetic accepted origin, never thread/start.
        context = self.rpc.receipt_context(); deadline = time.monotonic() + 5
        with self.store.locked(deadline, create=True) as base:
            record = self.store.reserve(base, 'demo', context['context_id'], str(self.root), OP, deadline)
            record = self.store.candidate(base, record, SID, deadline)
            record = self.store.origin(base, record, deadline); self.store.accept(base, record, deadline)
        self.creator = self.configured.ConfiguredSessionCreate(self.rpc, self.resolve, lambda: sorted(self.allowed),
            str(self.send_path), store=self.store)
        self.chat = self.sessions.SessionChat(self.rpc, self.resolve, lambda: sorted(self.allowed), str(self.send_path),
            configured_creator=self.creator, model_context=self.rpc.model_context)

    def resolve(self, project):
        if project not in self.allowed: raise PermissionError('Synthetic denied grant')
        return str(self.active_root)

    def invoke(self, callback):
        try: return callback()
        except Exception as error: self.fail('Public adapter unexpectedly raised ' + type(error).__name__)

    def require(self, owner, name):
        method = getattr(owner, name, None)
        self.assertTrue(callable(method), 'PUBLIC-SEAM PREREQUISITE absent: ' + name)
        return method

    def prepare(self): return self.rpc.prepare_context(timeout=1)
    def assert_closed(self, result):
        self.assertIn(result, ({'error': 'stale'}, {'error': 'unavailable'}, {'error': 'forbidden'}))
        self.assertNotIn(str(self.base), json.dumps(result))
    def assert_read_only(self): self.assertFalse(WRITES & set(self.native.methods()), self.native.methods())
    def files(self): return {str(path.relative_to(self.base)): path.read_bytes() for path in self.base.rglob('*') if path.is_file() and not path.is_symlink()}
    def rpc_rejected(self, callback):
        before = list(self.native.methods())
        with self.assertRaises(Exception): callback()
        self.assertEqual(self.native.methods(), before, 'Refused operation reached native application wire')
