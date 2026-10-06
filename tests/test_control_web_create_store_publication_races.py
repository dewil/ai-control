"""Deterministic same-owner path-swap regressions for CREATE publication."""
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


_BIN = str(Path(__file__).resolve().parents[1] / 'bin')
if _BIN not in sys.path:
    sys.path.insert(0, _BIN)

import _control_web_create_store as create_store  # noqa: E402
from _control_provider_accounts import AccountError  # noqa: E402
from _control_provider_context import ADAPTER, ExecutionContext  # noqa: E402


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


class CreatePublicationRaceTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='control-create-race-', dir='/var/tmp'))
        os.chmod(self.base, 0o700)
        self.project_root = self.base / 'project'
        self.project_root.mkdir(mode=0o700)
        os.chmod(self.project_root, 0o700)
        self.receipt_root = self.base / 'web-create-receipts'
        self.binding_root = self.base / 'web-session-bindings'
        self.lock_root = self.base / 'web-create-locks'
        self.operation_id = 'abcdefab-cdef-4abc-8def-abcdefabcdef'
        self.sid = 'fedcbafe-dcba-4fed-8cba-fedcbafedcba'
        native_home = self.base / 'native-home'
        child_home = self.base / 'child-home'
        self.context = ExecutionContext(
            reference={
                'schema': 1, 'provider_id': 'codex', 'account_id': 'acct-one',
                'profile_instance_id': '11111111-1111-4111-8111-111111111111',
                'adapter_revision': ADAPTER,
                'registration_snapshot': {
                    'dev': 1, 'ino': 2, 'ctime_ns': 3, 'sha256': 'a' * 64,
                },
            },
            native_home=native_home,
            child_home=child_home,
            child_env={'HOME': str(child_home), 'CODEX_HOME': str(native_home),
                       'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
            expected_native_principal={'kind': 'chatgpt_account_id', 'value': 'acct-one'},
        )

        def project_path(name):
            if name != 'alpha':
                raise ValueError('unexpected synthetic project')
            return str(self.project_root)

        self.project_path = project_path
        self.bindings = create_store.SessionBindings(
            self.binding_root, self.lock_root, self.receipt_root, self.project_path)
        self.store = create_store.CreateStore(
            self.receipt_root, self.bindings, self.project_path,
            clock=lambda: 1700000000000000001)
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def _receipt_leaf(self):
        locator = hashlib.sha256(_canonical({
            'kind': 'create_receipt', 'project': 'alpha',
            'operation_id': self.operation_id,
        })).hexdigest()
        return self.receipt_root / (locator + '.json')

    def test_cas_destination_swap_after_inode_check_preserves_foreign_file(self):
        reservation = self.store.reserve(self.context, 'alpha', self.operation_id)
        leaf = self._receipt_leaf()
        original_replace = os.replace
        injected = []
        foreign = b'foreign same-owner destination sentinel'

        def replace_with_destination_swap(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
            if dst == leaf.name and not injected:
                backup = dst + '.owned-fixture-backup'
                os.rename(dst, backup, src_dir_fd=dst_dir_fd, dst_dir_fd=dst_dir_fd)
                fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             0o600, dir_fd=dst_dir_fd)
                try:
                    os.write(fd, foreign)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                injected.append((leaf.stat().st_ino, leaf.read_bytes()))
            return original_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

        outcome, error = None, None
        with mock.patch.object(create_store.os, 'replace', replace_with_destination_swap):
            try:
                outcome = self.store.capture_candidate(reservation, self.sid)
            except AccountError as exc:
                error = exc

        failures = []
        if not injected:
            failures.append('destination race hook did not run')
        if outcome is not None or error is None:
            failures.append('CAS accepted a destination that changed after its inode check')
        elif error.code != 'store_unavailable':
            failures.append('path-swap refusal was not store_unavailable')
        if injected and (leaf.stat().st_ino, leaf.read_bytes()) != injected[0]:
            failures.append('foreign destination inode or bytes were replaced')
        self.assertEqual(failures, [], '; '.join(failures))

    def test_temp_swap_during_cleanup_preserves_foreign_file(self):
        original_unlink = os.unlink
        injected = []
        foreign = b'foreign same-owner temporary sentinel'

        class FailingRenameAt2:
            argtypes = None
            restype = None

            def __call__(self, *args):
                ctypes.set_errno(errno.EIO)
                return -1

        class UnsupportedRenameAt2:
            renameat2 = FailingRenameAt2()

        def unlink_with_temp_swap(path, *, dir_fd=None):
            if isinstance(path, str) and path.startswith('.tmp-') and not injected:
                backup = path + '.owned-fixture-backup'
                os.rename(path, backup, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             0o600, dir_fd=dir_fd)
                try:
                    os.write(fd, foreign)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                leaf = self.receipt_root / path
                injected.append((leaf, leaf.stat().st_ino, leaf.read_bytes()))
            return original_unlink(path, dir_fd=dir_fd)

        error = None
        with mock.patch.object(create_store.ctypes, 'CDLL',
                               side_effect=lambda *args, **kwargs: UnsupportedRenameAt2()), \
             mock.patch.object(create_store.os, 'unlink', unlink_with_temp_swap):
            try:
                self.store.reserve(self.context, 'alpha', self.operation_id)
            except AccountError as exc:
                error = exc

        failures = []
        if not injected:
            failures.append('temporary cleanup race hook did not run')
        if error is None or error.code != 'store_unavailable':
            failures.append('unsupported publication did not fail closed')
        if injected:
            leaf, inode, data = injected[0]
            if not leaf.exists() or leaf.stat().st_ino != inode or leaf.read_bytes() != data:
                failures.append('foreign temporary inode or bytes were unlinked')
        self.assertEqual(failures, [], '; '.join(failures))


if __name__ == '__main__':
    unittest.main()
