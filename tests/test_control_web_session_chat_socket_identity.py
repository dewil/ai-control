"""Blind INV-WSESS-07 owner socket alias/identity/peer contract, fe676a8 spec."""
import importlib
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
SID = '11111111-1111-4111-8111-111111111111'


class SocketIdentityContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'bin' / '_control_web_sessions.py').is_file(),
                        'Public InteractiveRPC required by socket topology specification')
        self.module = importlib.import_module('_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-session-socket-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.target = self.base / 'native.sock'
        self.alias = self.base / 'owner-alias.sock'
        self.frames = []
        self.server_errors = []
        self.connected = threading.Event()
        self.finished = threading.Event()
        self.connections = 0
    def server(self, path=None, mutate=None):
        from websockets.sync.server import unix_serve
        def process_request(connection, request):
            self.connections += 1
            self.connected.set()
            if mutate:
                mutate()
            return None
        def handler(ws):
            try:
                while True:
                    try:
                        frame = json.loads(ws.recv(timeout=1))
                    except TimeoutError:
                        return
                    self.frames.append(frame)
                    if frame.get('method') == 'initialize':
                        ws.send(json.dumps({'id': frame['id'], 'result': {}}))
                    elif frame.get('method') == 'thread/read':
                        ws.send(json.dumps({'id': frame['id'], 'result': {'thread': {'id': SID, 'cwd': '/var/tmp/synthetic'}}}))
            except Exception as error:
                from websockets.exceptions import ConnectionClosed
                if not isinstance(error, ConnectionClosed):
                    self.server_errors.append(error)
            finally:
                self.finished.set()
        path = path or self.target
        server = unix_serve(handler, str(path), process_request=process_request)
        os.chmod(path, 0o600)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(server.shutdown)
        return server
    def client(self, path=None):
        rpc = self.module.InteractiveRPC(str(path or self.alias), timeout=1)
        self.addCleanup(rpc.close)
        return rpc
    def read(self, rpc):
        return rpc('thread/read', {'threadId': SID, 'includeTurns': False})
    def reject(self, rpc):
        with self.assertRaises(Exception) as failure:
            self.read(rpc)
        self.assertNotIn(str(self.base), str(failure.exception), 'Errors cannot expose private alias/target paths')
        self.assertNotIsInstance(failure.exception, self.module.RPCRejected)
        rpc.close()
        if self.connected.is_set():
            self.assertTrue(self.finished.wait(2))
        self.assertEqual(self.frames, [], 'Mismatch must close before initialize or any application RPC')
        self.assertLessEqual(self.connections, 1, 'A mismatch must not reconnect/retry automatically')
        self.assertEqual(self.server_errors, [])

    def test_INV_WSESS_07_owner_alias_connects_to_verified_canonical_socket(self):
        self.server()
        self.alias.symlink_to(self.target)
        rpc = self.client()
        self.assertEqual(self.read(rpc), {'thread': {'id': SID, 'cwd': '/var/tmp/synthetic'}})
        self.assertEqual([frame.get('method') for frame in self.frames], ['initialize', 'initialized', 'thread/read'])
        self.assertEqual(self.connections, 1)

    def test_INV_WSESS_07_relative_owner_alias_resolution_is_supported(self):
        self.server()
        self.alias.symlink_to(self.target.name)
        self.assertEqual(self.read(self.client())['thread']['id'], SID)
        self.assertEqual(self.connections, 1)

    def test_INV_WSESS_07_direct_private_socket_still_supported(self):
        self.server()
        self.assertEqual(self.read(self.client(self.target))['thread']['id'], SID)
        self.assertEqual(self.connections, 1)

    def test_INV_WSESS_07_alias_target_must_be_socket(self):
        self.target.write_text('synthetic regular file, never websocket')
        os.chmod(self.target, 0o600)
        self.alias.symlink_to(self.target)
        self.reject(self.client())

    def test_INV_WSESS_07_alias_missing_target_fails_closed(self):
        self.alias.symlink_to(self.target)
        self.reject(self.client())

    def test_INV_WSESS_07_alias_loop_fails_closed(self):
        self.alias.symlink_to(self.alias.name)
        self.reject(self.client())

    def test_INV_WSESS_07_group_writable_target_rejected_before_initialize(self):
        self.server()
        self.alias.symlink_to(self.target)
        os.chmod(self.target, 0o620)
        self.reject(self.client())

    def test_INV_WSESS_07_world_writable_target_rejected_before_initialize(self):
        self.server()
        self.alias.symlink_to(self.target)
        os.chmod(self.target, 0o602)
        self.reject(self.client())

    def wrong_owner(self, wanted_type):
        original_stat = os.stat
        original_lstat = os.lstat
        checks = []
        def wrapped(original):
            def inspect(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                if wanted_type(info.st_mode):
                    checks.append(os.fspath(path))
                    fields = list(info)
                    fields[4] = os.getuid()+1
                    return os.stat_result(fields)
                return info
            return inspect
        rpc = self.client()
        with patch('os.stat', wrapped(original_stat)), patch('os.lstat', wrapped(original_lstat)):
            self.reject(rpc)
        self.assertTrue(checks, 'Transport must validate filesystem ownership metadata')

    def test_INV_WSESS_07_foreign_alias_owner_rejected_before_initialize(self):
        self.server()
        self.alias.symlink_to(self.target)
        self.wrong_owner(stat.S_ISLNK)

    def test_INV_WSESS_07_foreign_target_owner_rejected_before_initialize(self):
        self.server()
        self.alias.symlink_to(self.target)
        self.wrong_owner(stat.S_ISSOCK)

    def test_INV_WSESS_07_peer_credentials_mismatch_before_initialize(self):
        self.server()
        self.alias.symlink_to(self.target)
        original = socket.socket.getsockopt
        peer_checks = []
        def getsockopt(sock, level, option, *args):
            if level == socket.SOL_SOCKET and option == socket.SO_PEERCRED:
                peer_checks.append((level, option))
                return struct.pack('3i', os.getpid(), os.getuid()+1, os.getgid())
            return original(sock, level, option, *args)
        rpc = self.client()
        with patch.object(socket.socket, 'getsockopt', getsockopt):
            self.reject(rpc)
        self.assertTrue(peer_checks, 'Kernel SO_PEERCRED must be queried before initialize')

    def test_INV_WSESS_07_alias_retarget_during_websocket_connect_rejected(self):
        other = self.base / 'other.sock'
        self.server(other)
        def retarget():
            replacement = self.base / 'replacement-alias'
            replacement.symlink_to(other)
            os.replace(replacement, self.alias)
        self.server(mutate=retarget)
        self.alias.symlink_to(self.target)
        self.reject(self.client())

    def test_INV_WSESS_07_alias_same_target_new_identity_during_connect_rejected(self):
        def replace_alias():
            replacement = self.base / 'same-target-new-alias'
            replacement.symlink_to(self.target)
            os.replace(replacement, self.alias)
        self.server(mutate=replace_alias)
        self.alias.symlink_to(self.target)
        self.reject(self.client())

    def test_INV_WSESS_07_target_inode_replaced_during_connect_rejected(self):
        other = self.base / 'replacement.sock'
        self.server(other)
        def replace_target():
            os.replace(other, self.target)
        self.server(mutate=replace_target)
        self.alias.symlink_to(self.target)
        self.reject(self.client())

    def test_INV_WSESS_07_target_mode_changes_during_connect_rejected(self):
        self.server(mutate=lambda: os.chmod(self.target, 0o622))
        self.alias.symlink_to(self.target)
        self.reject(self.client())


if __name__ == '__main__':
    unittest.main()
