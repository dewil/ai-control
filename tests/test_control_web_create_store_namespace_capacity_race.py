"""Cooperating-writer races at the bounded CREATE storage namespace caps."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import unittest
import uuid
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


class NamespaceCapacityRace(unittest.TestCase):
    writers = 4

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='control-create-cap-race-', dir='/var/tmp'))
        os.chmod(self.base, 0o700)
        self.project_root = self.base / 'project'
        self.project_root.mkdir(mode=0o700)
        os.chmod(self.project_root, 0o700)
        self.receipt_root = self.base / 'web-create-receipts'
        self.binding_root = self.base / 'web-session-bindings'
        self.lock_root = self.base / 'web-create-locks'
        native_home, child_home = self.base / 'native-home', self.base / 'child-home'
        self.context = ExecutionContext(
            reference={
                'schema': 1, 'provider_id': 'codex', 'account_id': 'acct-cap',
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
            expected_native_principal={'kind': 'chatgpt_account_id', 'value': 'acct-cap'},
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

    def _receipt_name(self, operation_id):
        return hashlib.sha256(_canonical({
            'kind': 'create_receipt', 'project': 'alpha',
            'operation_id': operation_id,
        })).hexdigest() + '.json'

    def _fixture_operation_id(self, index):
        return str(uuid.UUID(int=1000 + index, version=4))

    def _writer_operation_ids(self):
        return [str(uuid.UUID(int=500000 + index, version=4))
                for index in range(self.writers)]

    def _seed_receipts(self):
        self.receipt_root.mkdir(mode=0o700)
        context_ref = {
            'schema': 1, 'provider_id': 'codex', 'account_id': 'acct-cap',
            'profile_instance_id': '11111111-1111-4111-8111-111111111111',
            'adapter_revision': ADAPTER,
            'registration_snapshot': {'dev': 1, 'ino': 2, 'ctime_ns': 3, 'sha256': 'a' * 64},
        }
        for index in range(9999):
            operation_id = self._fixture_operation_id(index)
            record = {
                'schema': 1, 'kind': 'session_create', 'operation_id': operation_id,
                'project': 'alpha', 'root': str(self.project_root),
                'context_ref': context_ref, 'candidate_sid': None,
                'status': 'unknown', 'created': 1700000000000000001 + index,
            }
            record['digest'] = hashlib.sha256(_canonical({
                'kind': 'session_create', 'operation_id': operation_id,
                'project': 'alpha', 'root': str(self.project_root),
                'context_ref': context_ref,
            })).hexdigest()
            path = self.receipt_root / self._receipt_name(operation_id)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                data = _canonical(record)
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
        self.assertEqual(len(list(self.receipt_root.iterdir())), 9999)

    def _seed_locks(self):
        self.lock_root.mkdir(mode=0o700)
        for index in range(9999):
            name = format(index + 1, '064x') + '.lock'
            path = self.lock_root / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        self.assertEqual(len(list(self.lock_root.iterdir())), 9999)

    def _race_writers(self, target_root, leaf_predicate):
        gate = threading.Barrier(self.writers)
        arrivals = []
        arrivals_lock = threading.Lock()
        outcome_lock = threading.Lock()
        outcomes = []
        original_open = os.open

        def fd_parent_matches(dir_fd):
            if dir_fd is None:
                return False
            try:
                return Path(os.readlink('/proc/self/fd/' + str(dir_fd))) == target_root
            except OSError:
                return False

        def gated_open(path, flags, mode=0o777, *, dir_fd=None):
            fd = original_open(path, flags, mode, dir_fd=dir_fd) if dir_fd is not None else \
                original_open(path, flags, mode)
            name = os.fsdecode(path)
            if fd_parent_matches(dir_fd) and leaf_predicate(name):
                with arrivals_lock:
                    arrivals.append(name)
                try:
                    gate.wait(timeout=1.5)
                except threading.BrokenBarrierError:
                    pass
            return fd

        def writer(operation_id):
            try:
                result = self.store.reserve(self.context, 'alpha', operation_id)
                value = ('ok', result.record['operation_id'])
            except AccountError as exc:
                value = ('error', exc.code)
            except BaseException as exc:
                value = ('unexpected', type(exc).__name__)
            with outcome_lock:
                outcomes.append(value)

        threads = [threading.Thread(target=writer, args=(operation_id,), daemon=True)
                   for operation_id in self._writer_operation_ids()]
        with mock.patch.object(create_store.os, 'open', gated_open):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            if any(thread.is_alive() for thread in threads):
                gate.abort()
                for thread in threads:
                    thread.join(timeout=5)
        self.assertTrue(all(not thread.is_alive() for thread in threads),
                        'bounded race workers must stop before fixture cleanup')
        return outcomes, arrivals

    def _assert_bounded_outcomes(self, outcomes, max_successes):
        successes = [row for row in outcomes if row[0] == 'ok']
        errors = [row for row in outcomes if row[0] == 'error']
        unexpected = [row for row in outcomes if row[0] == 'unexpected']
        self.assertEqual(len(outcomes), self.writers)
        self.assertEqual(unexpected, [])
        self.assertLessEqual(len(successes), max_successes,
                             'distinct writers must not oversubscribe the shared namespace cap')
        self.assertGreaterEqual(len(errors), self.writers - max_successes,
                                'overflow writers must fail safely')
        self.assertTrue(all(code == 'store_unavailable' for _, code in errors))

    def test_distinct_operation_receipt_publications_do_not_oversubscribe_cap(self):
        self._seed_receipts()
        outcomes, arrivals = self._race_writers(
            self.receipt_root, lambda name: name.startswith('.tmp-'))
        self._assert_bounded_outcomes(outcomes, max_successes=1)
        entries = list(self.receipt_root.iterdir())
        receipt_records = list(self.receipt_root.glob('*.json'))
        self.assertLessEqual(len(entries), 10002)
        self.assertLessEqual(len(receipt_records), 10000)
        if len(arrivals) == self.writers:
            self.assertEqual(len(set(arrivals)), self.writers)

    def test_distinct_operation_lock_provisioning_respects_directory_cap(self):
        self._seed_locks()
        outcomes, arrivals = self._race_writers(
            self.lock_root,
            lambda name: len(name) == 69 and name.endswith('.lock')
            and re.fullmatch('[0-9a-f]{64}\\.lock', name) is not None)
        self._assert_bounded_outcomes(outcomes, max_successes=3)
        entries = list(self.lock_root.iterdir())
        self.assertLessEqual(len(entries), 10002)
        if len(arrivals) == self.writers:
            self.assertEqual(len(set(arrivals)), self.writers)


if __name__ == '__main__':
    unittest.main()
