"""Public immutable R/C/A/B storage contract tests with synthetic metadata only."""
import ctypes
import errno
import hashlib
import json
import multiprocessing
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


def _plain(value):
    if hasattr(value, 'items'):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _commitment(path):
    info = path.stat(follow_symlinks=False)
    data = path.read_bytes()
    return {'filename': path.name, 'dev': info.st_dev, 'ino': info.st_ino,
            'ctime_ns': info.st_ctime_ns, 'sha256': hashlib.sha256(data).hexdigest()}


def _stage_path(root, kind, project, operation_id):
    name_hash = hashlib.sha256(_canonical({
        'kind': kind, 'project': project, 'operation_id': operation_id,
    })).hexdigest()
    return Path(root) / (name_hash + '.json')


def _crash_after_prepared_stage(base_text, operation_id, sid):
    """Synthetic owner child leaves R+C+B durable and exits before A."""
    try:
        base = Path(base_text)
        receipt_root = base / 'web-create-receipts'
        binding_root = base / 'web-session-bindings'
        lock_root = base / 'web-create-locks'
        project_root = base / 'project'
        native_home, child_home = base / 'native-home', base / 'child-home'
        context = ExecutionContext(
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
            return str(project_root)

        bindings = create_store.SessionBindings(binding_root, lock_root,
                                                receipt_root, project_path)
        store = create_store.CreateStore(receipt_root, bindings, project_path,
                                         clock=lambda: 1700000000000000001)
        reservation = store.reserve(context, 'alpha', operation_id)
        reservation = store.capture_candidate(reservation, sid)
        binding = bindings.publish_candidate(reservation)
        if (not _stage_path(receipt_root, 'create_receipt', 'alpha', operation_id).is_file()
                or not _stage_path(receipt_root, 'create_candidate', 'alpha',
                                   operation_id).is_file()
                or _stage_path(receipt_root, 'create_accepted', 'alpha',
                               operation_id).exists()
                or binding.record['sid'] != sid
                or bindings.resolve('alpha', binding.record['session_ref'], sid) is not None):
            os._exit(74)
        os._exit(73)
    except BaseException:
        os._exit(74)


class ImmutableCreateStages(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='control-create-stage-', dir='/var/tmp'))
        os.chmod(self.base, 0o700)
        self.project_root = self.base / 'project'
        self.project_root.mkdir(mode=0o700)
        os.chmod(self.project_root, 0o700)
        self.receipt_root = self.base / 'web-create-receipts'
        self.binding_root = self.base / 'web-session-bindings'
        self.lock_root = self.base / 'web-create-locks'
        self.operation_id = 'abcdefab-cdef-4abc-8def-abcdefabcdef'
        self.sid = 'fedcbafe-dcba-4fed-8cba-fedcbafedcba'
        native_home, child_home = self.base / 'native-home', self.base / 'child-home'
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

    def _leaf(self, kind):
        return _stage_path(self.receipt_root, kind, 'alpha', self.operation_id)

    def _reservation_and_binding(self):
        reservation = self.store.reserve(self.context, 'alpha', self.operation_id)
        reservation = self.store.capture_candidate(reservation, self.sid)
        binding = self.bindings.publish_candidate(reservation)
        return reservation, binding, self.binding_root / (binding.record['session_ref'] + '.json')

    def _expect_store_unavailable(self, function):
        try:
            function()
        except AccountError as exc:
            self.assertEqual(exc.code, 'store_unavailable')
        else:
            self.fail('expected fail-closed store_unavailable')

    def test_reserve_and_candidate_use_immutable_r_and_parent_committed_c(self):
        reservation = self.store.reserve(self.context, 'alpha', self.operation_id)
        r_leaf = self._leaf('create_receipt')
        r_before = (r_leaf.read_bytes(), r_leaf.stat().st_ino, r_leaf.stat().st_ctime_ns)
        self.assertEqual(set(json.loads(r_before[0])), {
            'schema', 'kind', 'operation_id', 'digest', 'project', 'root',
            'context_ref', 'candidate_sid', 'status', 'created'})
        candidate = self.store.capture_candidate(reservation, self.sid)
        c_leaf = self._leaf('create_candidate')
        self.assertTrue(c_leaf.is_file(), 'capture must publish a separate immutable C stage')
        self.assertEqual(r_before, (r_leaf.read_bytes(), r_leaf.stat().st_ino,
                                    r_leaf.stat().st_ctime_ns))
        c_record = json.loads(c_leaf.read_bytes())
        self.assertEqual(set(c_record), {'schema', 'kind', 'record', 'parent'})
        self.assertEqual(c_record['schema'], 1)
        self.assertEqual(c_record['kind'], 'session_create_candidate')
        self.assertEqual(c_record['record'], _plain(candidate.record))
        self.assertEqual(c_record['record']['candidate_sid'], self.sid)
        self.assertEqual(c_record['record']['status'], 'unknown')
        self.assertEqual(c_record['parent'], _commitment(r_leaf))
        replay = self.store.capture_candidate(candidate, self.sid)
        self.assertEqual(_plain(replay.record), _plain(candidate.record))
        self.assertEqual(c_leaf.read_bytes(), _canonical(c_record))

    def test_accepted_stage_commits_exact_candidate_and_binding_parents(self):
        reservation, binding, b_leaf = self._reservation_and_binding()
        r_leaf, c_leaf, a_leaf = (self._leaf('create_receipt'),
                                  self._leaf('create_candidate'),
                                  self._leaf('create_accepted'))
        self.assertTrue(c_leaf.is_file(), 'candidate publication must create immutable C')
        self.assertTrue(b_leaf.is_file(), 'prepared binding B must exist before acceptance')
        before = {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_ctime_ns)
                  for path in (r_leaf, c_leaf, b_leaf)}
        accepted = self.store.commit_accepted(reservation, binding)
        self.assertTrue(a_leaf.is_file(), 'acceptance must publish a separate immutable A stage')
        a_record = json.loads(a_leaf.read_bytes())
        self.assertEqual(set(a_record), {'schema', 'kind', 'record', 'parent', 'binding'})
        self.assertEqual(a_record['schema'], 1)
        self.assertEqual(a_record['kind'], 'session_create_accepted')
        self.assertEqual(a_record['record'], _plain(accepted.record))
        self.assertEqual(a_record['record']['candidate_sid'], self.sid)
        self.assertEqual(a_record['record']['status'], 'accepted')
        self.assertEqual(a_record['parent'], _commitment(c_leaf))
        self.assertEqual(a_record['binding'], _commitment(b_leaf))
        self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_ino,
                                         path.stat().st_ctime_ns)
                                  for path in (r_leaf, c_leaf, b_leaf)})
        a_before = (a_leaf.read_bytes(), a_leaf.stat().st_ino, a_leaf.stat().st_ctime_ns)
        replay = self.store.commit_accepted(accepted, binding)
        self.assertEqual(_plain(replay.record), _plain(accepted.record))
        self.assertEqual(a_before, (a_leaf.read_bytes(), a_leaf.stat().st_ino,
                                    a_leaf.stat().st_ctime_ns))

    def test_known_accepted_handle_with_missing_a_fails_closed(self):
        reservation, binding, _ = self._reservation_and_binding()
        accepted = self.store.commit_accepted(reservation, binding)
        self._leaf('create_accepted').unlink(missing_ok=True)
        self._expect_store_unavailable(lambda: self.store.commit_accepted(accepted, binding))
        stateless = self.store.lookup(self.context, 'alpha', self.operation_id)
        self.assertEqual(_plain(stateless.record)['candidate_sid'], self.sid)
        self.assertEqual(_plain(stateless.record)['status'], 'unknown')

    def test_present_binding_with_missing_r_parent_is_unavailable(self):
        _, binding, _ = self._reservation_and_binding()
        self._leaf('create_receipt').unlink()
        self._expect_store_unavailable(lambda: self.bindings.resolve(
            'alpha', binding.record['session_ref'], self.sid))

    def test_initial_noreplace_collision_preserves_foreign_destination(self):
        real_cdll = ctypes.CDLL
        real_renameat2 = real_cdll(None, use_errno=True).renameat2
        real_renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                   ctypes.c_char_p, ctypes.c_uint)
        real_renameat2.restype = ctypes.c_int
        foreign = b'foreign same-owner immutable-stage sentinel'
        injected = []

        class RenameWithCollision:
            argtypes = None
            restype = None

            def __call__(self, old_dir_fd, old_name, new_dir_fd, new_name, flags):
                name = os.fsdecode(new_name)
                if not injected:
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                 0o600, dir_fd=new_dir_fd)
                    try:
                        os.write(fd, foreign)
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    path = self_test_root / name
                    injected.append((path, path.stat().st_ino, path.read_bytes()))
                return real_renameat2(old_dir_fd, old_name, new_dir_fd, new_name, flags)

        class Library:
            renameat2 = RenameWithCollision()

        self_test_root = self.receipt_root
        error = None
        with mock.patch.object(create_store.ctypes, 'CDLL',
                               side_effect=lambda *args, **kwargs: Library()):
            try:
                self.store.reserve(self.context, 'alpha', self.operation_id)
            except AccountError as exc:
                error = exc
        self.assertTrue(injected)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'store_unavailable')
        path, inode, data = injected[0]
        self.assertEqual((path.stat().st_ino, path.read_bytes()), (inode, data))

    def test_failed_noreplace_publication_never_unlinks_a_swapped_temp_path(self):
        real_unlink = os.unlink
        injected = []
        foreign = b'foreign temp sentinel'

        class FailingRenameAt2:
            argtypes = None
            restype = None

            def __call__(self, *args):
                ctypes.set_errno(errno.EIO)
                return -1

        class Library:
            renameat2 = FailingRenameAt2()

        def unlink_with_swap(path, *, dir_fd=None):
            if isinstance(path, str) and path.startswith('.tmp-') and not injected:
                backup = path + '.fixture-backup'
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
            return real_unlink(path, dir_fd=dir_fd)

        error = None
        with mock.patch.object(create_store.ctypes, 'CDLL',
                               side_effect=lambda *args, **kwargs: Library()), \
             mock.patch.object(create_store.os, 'unlink', unlink_with_swap):
            try:
                self.store.reserve(self.context, 'alpha', self.operation_id)
            except AccountError as exc:
                error = exc

        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'store_unavailable')
        if injected:
            leaf, inode, data = injected[0]
            self.assertTrue(leaf.exists(), 'foreign temporary path must not be unlinked')
            if leaf.exists():
                self.assertEqual((leaf.stat().st_ino, leaf.read_bytes()), (inode, data))
        else:
            orphans = list(self.receipt_root.glob('.tmp-*'))
            self.assertTrue(orphans, 'uncertain publication leaves its own bounded orphan')
            self.assertTrue(all(path.stat().st_nlink == 1 for path in orphans))

    def test_private_stage_and_orphan_entries_share_the_directory_cap(self):
        self.receipt_root.mkdir(mode=0o700, exist_ok=True)
        for index in range(10002):
            leaf = self.receipt_root / ('.tmp-' + format(index, '032x'))
            fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, ('orphan-' + str(index)).encode('ascii'))
            finally:
                os.close(fd)
        before = {entry.name: (entry.stat().st_ino, entry.stat().st_mode & 0o777,
                               entry.read_bytes())
                  for entry in self.receipt_root.iterdir()}
        self.assertEqual(len(before), 10002)
        try:
            self.store.reserve(self.context, 'alpha', self.operation_id)
        except AccountError as exc:
            self.assertEqual(exc.code, 'store_unavailable')
        else:
            self.fail('namespace cap must refuse publication before cleanup or overwrite')
        after = {entry.name: (entry.stat().st_ino, entry.stat().st_mode & 0o777,
                              entry.read_bytes())
                 for entry in self.receipt_root.iterdir()}
        self.assertEqual(before, after)

    def test_crash_after_candidate_and_binding_recovers_a_once(self):
        operation_id = '12345678-1234-4234-8234-123456789abc'
        sid = 'abcdef12-3456-4abc-8def-abcdef123456'
        process = multiprocessing.get_context('spawn').Process(
            target=_crash_after_prepared_stage,
            args=(str(self.base), operation_id, sid), daemon=True)
        started = False
        try:
            process.start()
            started = True
            process.join(timeout=15)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
                self.fail('owned synthetic stage-crash child exceeded bounded wait')
            self.assertEqual(process.exitcode, 73,
                             'child must stop with R+C+B and no accepted A')
        finally:
            if started:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
                if process.is_alive():
                    self.fail('could not stop owned synthetic stage-crash child')
                process.close()

        bindings = create_store.SessionBindings(self.binding_root, self.lock_root,
                                                self.receipt_root, self.project_path)
        store = create_store.CreateStore(self.receipt_root, bindings, self.project_path)
        reservation = store.lookup(self.context, 'alpha', operation_id)
        self.assertIsNotNone(reservation)
        self.assertEqual(_plain(reservation.record)['candidate_sid'], sid)
        self.assertEqual(_plain(reservation.record)['status'], 'unknown')
        session_ref = hashlib.sha256(_canonical({
            'kind': 'session_binding',
            'context_key': hashlib.sha256(_canonical(_plain(self.context.reference))).hexdigest(),
            'sid': sid,
        })).hexdigest()
        self.assertIsNone(bindings.resolve('alpha', session_ref, sid))

        r_leaf = _stage_path(self.receipt_root, 'create_receipt', 'alpha', operation_id)
        c_leaf = _stage_path(self.receipt_root, 'create_candidate', 'alpha', operation_id)
        a_leaf = _stage_path(self.receipt_root, 'create_accepted', 'alpha', operation_id)
        b_leaf = self.binding_root / (session_ref + '.json')
        self.assertTrue(r_leaf.is_file())
        self.assertTrue(c_leaf.is_file())
        self.assertTrue(b_leaf.is_file())
        self.assertFalse(a_leaf.exists())
        prepared_snapshot = {path: (path.read_bytes(), path.stat().st_ino,
                                    path.stat().st_ctime_ns)
                             for path in (r_leaf, c_leaf, b_leaf)}
        binding = bindings.publish_candidate(reservation)
        self.assertEqual(prepared_snapshot, {path: (path.read_bytes(), path.stat().st_ino,
                                                    path.stat().st_ctime_ns)
                                             for path in (r_leaf, c_leaf, b_leaf)})
        accepted = store.commit_accepted(reservation, binding)
        self.assertTrue(a_leaf.is_file())
        a_before = (a_leaf.read_bytes(), a_leaf.stat().st_ino, a_leaf.stat().st_ctime_ns)
        replay = store.commit_accepted(accepted, binding)
        self.assertEqual(_plain(replay.record)['status'], 'accepted')
        self.assertEqual(a_before, (a_leaf.read_bytes(), a_leaf.stat().st_ino,
                                    a_leaf.stat().st_ctime_ns))


if __name__ == '__main__':
    unittest.main()
