"""Source-blind contract tests for the CREATE receipt/binding storage seam.

These tests exercise metadata-only storage with synthetic ExecutionContext values.
They never construct a native host or invoke profile/auth/native APIs.
"""
import hashlib
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid


_BIN = str(Path(__file__).resolve().parents[1] / 'bin')
if _BIN not in sys.path:
    sys.path.insert(0, _BIN)

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


def _prepared_pair_crash_worker(base_text, operation_id, sid):
    """Leave a durable candidate and invisible binding, then exit before acceptance."""
    try:
        base = Path(base_text)
        project_root = base / 'project'
        receipt_root = base / 'web-create-receipts'
        binding_root = base / 'web-session-bindings'
        lock_root = base / 'web-create-locks'
        account_id = 'acct-crash'
        native_home = base / 'native-crash'
        child_home = base / 'child-crash'
        context = ExecutionContext(
            reference={
                'schema': 1, 'provider_id': 'codex', 'account_id': account_id,
                'profile_instance_id': '99999999-9999-4999-8999-999999999999',
                'adapter_revision': ADAPTER,
                'registration_snapshot': {
                    'dev': 1, 'ino': 2, 'ctime_ns': 3, 'sha256': 'a' * 64,
                },
            },
            native_home=native_home,
            child_home=child_home,
            child_env={'HOME': str(child_home), 'CODEX_HOME': str(native_home),
                       'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
            expected_native_principal={'kind': 'chatgpt_account_id', 'value': account_id},
        )

        def project_path(name):
            if name != 'alpha':
                raise ValueError('unexpected synthetic project')
            return str(project_root)

        api = importlib.import_module('_control_web_create_store')
        bindings = api.SessionBindings(binding_root, lock_root, receipt_root, project_path)
        store = api.CreateStore(receipt_root, bindings, project_path,
                                clock=lambda: 1700000000000000021)
        reservation = store.reserve(context, 'alpha', operation_id)
        reservation = store.capture_candidate(reservation, sid)
        binding = bindings.publish_candidate(reservation)
        if (reservation.record['status'] != 'unknown'
                or binding.record['sid'] != sid
                or bindings.resolve('alpha', binding.record['session_ref'], sid) is not None):
            os._exit(74)
        os._exit(73)
    except BaseException:
        os._exit(74)


class CreateStoreContract(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='control-web-create-', dir='/var/tmp'))
        os.chmod(self.base, 0o700)
        self.project_root = self.base / 'project'
        self.project_root.mkdir(mode=0o700)
        os.chmod(self.project_root, 0o700)
        self.receipt_root = self.base / 'web-create-receipts'
        self.binding_root = self.base / 'web-session-bindings'
        self.lock_root = self.base / 'web-create-locks'
        self.projects = {'alpha': self.project_root}
        self.resolver_calls = []
        self.project_path = self._resolve_project
        self.context = self._context('acct-one', '11111111-1111-4111-8111-111111111111')
        self.context_b = self._context('acct-two', '22222222-2222-4222-8222-222222222222')
        self.operation_id = 'abcdefab-cdef-4abc-8def-abcdefabcdef'
        self.sid = 'fedcbafe-dcba-4fed-8cba-fedcbafedcba'
        self.clock_values = iter((1700000000000000001, 1700000000000000002,
                                  1700000000000000003))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def _resolve_project(self, name):
        self.resolver_calls.append(name)
        return str(self.projects[name])

    def _context(self, account_id, profile_id):
        reference = {
            'schema': 1,
            'provider_id': 'codex',
            'account_id': account_id,
            'profile_instance_id': profile_id,
            'adapter_revision': ADAPTER,
            'registration_snapshot': {
                'dev': 1, 'ino': 2, 'ctime_ns': 3,
                'sha256': 'a' * 64,
            },
        }
        native_home = self.base / ('native-' + account_id)
        child_home = self.base / ('child-' + account_id)
        return ExecutionContext(
            reference=reference,
            native_home=native_home,
            child_home=child_home,
            child_env={'HOME': str(child_home), 'CODEX_HOME': str(native_home),
                       'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
            expected_native_principal={'kind': 'chatgpt_account_id', 'value': account_id},
        )

    def _api(self):
        try:
            return importlib.import_module('_control_web_create_store')
        except ModuleNotFoundError as exc:
            if exc.name != '_control_web_create_store':
                raise
        self.fail('INV-WSESS-32 storage contract is missing: '
                  '_control_web_create_store must expose the public CREATE store seam')

    def _stores(self, project_path=None, clock=None):
        api = self._api()
        resolver = self.project_path if project_path is None else project_path
        bindings = api.SessionBindings(self.binding_root, self.lock_root,
                                       self.receipt_root, resolver)
        kwargs = {} if clock is None else {'clock': clock}
        store = api.CreateStore(self.receipt_root, bindings, resolver, **kwargs)
        return api, store, bindings

    def _error(self, callable_, code):
        try:
            callable_()
        except AccountError as exc:
            self.assertEqual(exc.code, code)
            self.assertNotIn(str(self.base), str(exc))
        else:
            self.fail('expected AccountError code ' + code)

    def _receipt_leaf(self):
        return self._receipt_leaf_for(self.operation_id)

    def _receipt_leaf_for(self, operation_id):
        key = hashlib.sha256(_canonical({
            'kind': 'create_receipt', 'project': 'alpha',
            'operation_id': operation_id,
        })).hexdigest()
        return self.receipt_root / (key + '.json')

    def _reservation(self, store=None, context=None, operation_id=None):
        if store is None:
            _, store, _ = self._stores()
        return store.reserve(context or self.context, 'alpha',
                             operation_id or self.operation_id)

    def test_missing_lookup_is_read_only_and_resolve_does_not_create_roots(self):
        api, store, bindings = self._stores()
        self.assertIsNone(store.lookup(self.context, 'alpha', self.operation_id))
        self.assertIsNone(bindings.resolve('alpha', 'b' * 64, self.sid))
        self.assertFalse(self.receipt_root.exists())
        self.assertFalse(self.binding_root.exists())
        self.assertFalse(self.lock_root.exists())

    def test_reserve_publishes_exact_unknown_record_digest_and_private_leaf(self):
        legacy_receipt = self.base / 'web-send-receipts'
        legacy_receipt.mkdir(mode=0o700)
        legacy_leaf = legacy_receipt / 'legacy.json'
        legacy_leaf.write_bytes(b'legacy-send-receipt')
        os.chmod(legacy_leaf, 0o600)
        legacy_before = legacy_leaf.read_bytes()
        api, store, _ = self._stores(clock=lambda: 1700000000000000001)
        reservation = self._reservation(store)
        record = _plain(reservation.record)
        context_ref = _plain(self.context.reference)
        expected_payload = {'kind': 'session_create', 'operation_id': self.operation_id,
                            'project': 'alpha', 'root': str(self.project_root),
                            'context_ref': context_ref}
        self.assertEqual(set(record), {'schema', 'kind', 'operation_id', 'digest',
                                       'project', 'root', 'context_ref',
                                       'candidate_sid', 'status', 'created'})
        self.assertEqual(record['schema'], 1)
        self.assertEqual(record['kind'], 'session_create')
        self.assertEqual(record['candidate_sid'], None)
        self.assertEqual(record['status'], 'unknown')
        self.assertEqual(record['created'], 1700000000000000001)
        self.assertEqual(record['digest'], hashlib.sha256(_canonical(expected_payload)).hexdigest())
        self.assertEqual(record['context_ref'], context_ref)
        leaf = self._receipt_leaf()
        self.assertTrue(leaf.is_file())
        self.assertLessEqual(leaf.stat().st_size, 4096)
        self.assertEqual(leaf.stat().st_nlink, 1)
        self.assertEqual(leaf.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.receipt_root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(legacy_leaf.read_bytes(), legacy_before)
        self.assertFalse((self.base / 'web-session-rename-receipts').exists())
        self.assertFalse(hasattr(api, 'create_thread'))
        self.assertFalse(hasattr(api, 'activate'))
        self.assertFalse(hasattr(api, 'admission_callback'))

    def test_exact_reserve_replay_does_not_rewrite_or_advance_clock(self):
        api, store, _ = self._stores(clock=lambda: next(self.clock_values))
        first = self._reservation(store)
        leaf = self._receipt_leaf()
        before = (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns)
        second = self._reservation(store)
        self.assertEqual(_plain(first.record), _plain(second.record))
        self.assertEqual(before, (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns))

    def test_same_operation_uuid_with_other_context_conflicts_without_overwrite(self):
        _, store, _ = self._stores()
        self._reservation(store)
        before = self._receipt_leaf().read_bytes()
        self._error(lambda: store.reserve(self.context_b, 'alpha', self.operation_id),
                    'store_conflict')
        self.assertEqual(before, self._receipt_leaf().read_bytes())

    def test_same_native_sid_in_two_contexts_produces_distinct_session_refs(self):
        api, store, bindings = self._stores()
        first = self._reservation(store)
        second_op = '55555555-5555-4555-8555-555555555555'
        second = self._reservation(store, self.context_b, second_op)
        first = store.capture_candidate(first, self.sid)
        second = store.capture_candidate(second, self.sid)
        first_binding = bindings.publish_candidate(first)
        second_binding = bindings.publish_candidate(second)
        self.assertNotEqual(first_binding.record['session_ref'], second_binding.record['session_ref'])
        self.assertEqual(first_binding.record['sid'], second_binding.record['sid'])
        self.assertEqual(first_binding.record['context_ref']['account_id'], 'acct-one')
        self.assertEqual(second_binding.record['context_ref']['account_id'], 'acct-two')

    def test_context_and_root_are_committed_in_digest_and_not_rebound(self):
        _, store, _ = self._stores()
        reservation = self._reservation(store)
        before = self._receipt_leaf().read_bytes()
        self.projects['alpha'] = self.base / 'other-project'
        self.projects['alpha'].mkdir(mode=0o700)
        self._error(lambda: store.lookup(self.context, 'alpha', self.operation_id), 'stale')
        self._error(lambda: store.reserve(self.context, 'alpha', self.operation_id), 'stale')
        self.assertEqual(_plain(reservation.record)['root'], str(self.project_root))
        self.assertEqual(before, self._receipt_leaf().read_bytes())

    def test_invalid_project_names_fail_before_reservation(self):
        _, store, _ = self._stores()
        for project in ('../alpha', '', 'a' * 33, 'alpha/other', None, 4):
            with self.subTest(project=project):
                self._error(lambda project=project: store.reserve(
                    self.context, project, self.operation_id), 'invalid_request')
        self.assertFalse(self.receipt_root.exists())
        self.assertFalse(self.lock_root.exists())
        self.projects['A'] = self.project_root
        reservation = store.reserve(self.context, 'A', self.operation_id)
        self.assertEqual(_plain(reservation.record)['project'], 'A')
        self.assertEqual(_plain(reservation.record)['root'], str(self.project_root))
        self.assertEqual(_plain(store.lookup(self.context, 'A', self.operation_id).record),
                         _plain(reservation.record))
        self.assertIn('A', self.resolver_calls)

    def test_noncanonical_and_non_uuid_operation_ids_are_rejected(self):
        _, store, _ = self._stores()
        for operation_id in ('', self.operation_id.upper(), self.operation_id[:-1],
                             None, True, 123, '33333333-3333-4333-8333-333333333333\n'):
            with self.subTest(operation_id=operation_id):
                self._error(lambda operation_id=operation_id: store.reserve(
                    self.context, 'alpha', operation_id), 'invalid_request')
        self.assertFalse(self.receipt_root.exists())

    def test_non_execution_context_objects_are_rejected(self):
        _, store, _ = self._stores()
        for context in (None, {}, dict(self.context.reference), object()):
            with self.subTest(context_type=type(context).__name__):
                self._error(lambda context=context: store.reserve(
                    context, 'alpha', self.operation_id), 'context_invalid')

    def test_invalid_clock_values_are_rejected_without_receipt(self):
        for value in (True, 0, -1, 1.5, '1700000000000000000'):
            with self.subTest(clock_value=value):
                _, store, _ = self._stores(clock=lambda value=value: value)
                self._error(lambda: self._reservation(store), 'invalid_request')
        self.assertFalse(self.receipt_root.exists())

    def test_candidate_capture_is_compare_and_set_and_exact_replay_keeps_bytes(self):
        _, store, _ = self._stores()
        reservation = self._reservation(store)
        captured = store.capture_candidate(reservation, self.sid)
        leaf = self._receipt_leaf()
        before = (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns)
        replay = store.capture_candidate(captured, self.sid)
        self.assertEqual(_plain(replay.record)['candidate_sid'], self.sid)
        self.assertEqual(before, (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns))

    def test_different_candidate_sid_conflicts_and_preserves_original(self):
        _, store, _ = self._stores()
        captured = store.capture_candidate(self._reservation(store), self.sid)
        before = self._receipt_leaf().read_bytes()
        self._error(lambda: store.capture_candidate(
            captured, '66666666-6666-4666-8666-666666666666'), 'store_conflict')
        self.assertEqual(before, self._receipt_leaf().read_bytes())

    def test_noncanonical_candidate_sid_is_rejected(self):
        _, store, _ = self._stores()
        reservation = self._reservation(store)
        for sid in ('not-a-uuid', self.sid.upper(), None, True, 1):
            with self.subTest(sid=sid):
                self._error(lambda sid=sid: store.capture_candidate(reservation, sid),
                            'invalid_request')
        self.assertIsNone(_plain(store.lookup(self.context, 'alpha', self.operation_id).record)
                          ['candidate_sid'])

    def test_unaccepted_candidate_binding_is_invisible_to_resolve(self):
        api, store, bindings = self._stores()
        reservation = store.capture_candidate(self._reservation(store), self.sid)
        binding = bindings.publish_candidate(reservation)
        self.assertIsNone(bindings.resolve('alpha', binding.record['session_ref'], self.sid))
        self.assertEqual(_plain(binding.record)['sid'], self.sid)

    def test_prepared_binding_survives_new_instances_but_stays_invisible(self):
        api, store, bindings = self._stores()
        reservation = store.capture_candidate(self._reservation(store), self.sid)
        binding = bindings.publish_candidate(reservation)
        new_bindings = api.SessionBindings(self.binding_root, self.lock_root,
                                           self.receipt_root, self.project_path)
        new_store = api.CreateStore(self.receipt_root, new_bindings, self.project_path)
        reread = new_store.lookup(self.context, 'alpha', self.operation_id)
        self.assertEqual(_plain(reread.record)['candidate_sid'], self.sid)
        self.assertIsNone(new_bindings.resolve('alpha', binding.record['session_ref'], self.sid))

    def test_binding_publish_replay_does_not_overwrite_or_change_inode(self):
        _, store, bindings = self._stores()
        reservation = store.capture_candidate(self._reservation(store), self.sid)
        first = bindings.publish_candidate(reservation)
        session_ref = first.record['session_ref']
        leaf = self.binding_root / (session_ref + '.json')
        before = (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns)
        second = bindings.publish_candidate(reservation)
        self.assertEqual(_plain(first.record), _plain(second.record))
        self.assertEqual(before, (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns))

    def test_accepted_commit_is_the_visibility_marker(self):
        api, store, bindings = self._stores()
        reservation = store.capture_candidate(self._reservation(store), self.sid)
        binding = bindings.publish_candidate(reservation)
        self.assertIsNone(bindings.resolve('alpha', binding.record['session_ref'], self.sid))
        accepted = store.commit_accepted(reservation, binding)
        self.assertEqual(_plain(accepted.record)['status'], 'accepted')
        resolved = bindings.resolve('alpha', binding.record['session_ref'], self.sid)
        self.assertEqual(_plain(resolved.record), _plain(binding.record))

    def test_accepted_lookup_recovery_is_idempotent_across_instances(self):
        api, store, bindings = self._stores()
        reservation = store.capture_candidate(self._reservation(store), self.sid)
        binding = bindings.publish_candidate(reservation)
        accepted = store.commit_accepted(reservation, binding)
        leaf = self._receipt_leaf()
        before = (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns)
        again = store.commit_accepted(accepted, binding)
        self.assertEqual(_plain(again.record)['status'], 'accepted')
        self.assertEqual(before, (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns))
        self.assertEqual(_plain(store.reserve(self.context, 'alpha', self.operation_id).record)
                         ['status'], 'accepted')
        self.assertEqual(before, (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns))

    def test_accepted_receipt_with_missing_or_mismatched_binding_fails_closed(self):
        _, store, bindings = self._stores()
        reservation = store.capture_candidate(self._reservation(store), self.sid)
        binding = bindings.publish_candidate(reservation)
        store.commit_accepted(reservation, binding)
        leaf = self.binding_root / (binding.record['session_ref'] + '.json')
        leaf.unlink()
        self._error(lambda: store.lookup(self.context, 'alpha', self.operation_id),
                    'store_unavailable')
        mismatched = _plain(binding.record)
        mismatched['create_digest'] = 'b' * 64
        leaf.write_bytes(_canonical(mismatched))
        os.chmod(leaf, 0o600)
        self._error(lambda: store.lookup(self.context, 'alpha', self.operation_id),
                    'store_unavailable')

    def test_binding_with_missing_receipt_fails_closed_but_missing_binding_is_none(self):
        api, store, bindings = self._stores()
        absent_ref = 'a' * 64
        self.assertIsNone(bindings.resolve('alpha', absent_ref, self.sid))
        reservation = store.capture_candidate(self._reservation(store), self.sid)
        binding = bindings.publish_candidate(reservation)
        self._receipt_leaf().unlink()
        self._error(lambda: bindings.resolve('alpha', binding.record['session_ref'], self.sid),
                    'store_unavailable')

    def test_corrupt_receipt_is_not_treated_as_missing(self):
        _, store, _ = self._stores()
        self._reservation(store)
        leaf = self._receipt_leaf()
        leaf.write_bytes(b'{"schema":1,"schema":1}')
        os.chmod(leaf, 0o600)
        self._error(lambda: store.lookup(self.context, 'alpha', self.operation_id),
                    'store_unavailable')

    def test_existing_conflicting_binding_is_never_overwritten(self):
        _, store, bindings = self._stores()
        reservation = store.capture_candidate(self._reservation(store), self.sid)
        record = _plain(reservation.record)
        context_key = hashlib.sha256(_canonical(record['context_ref'])).hexdigest()
        session_ref = hashlib.sha256(_canonical({
            'kind': 'session_binding', 'context_key': context_key, 'sid': self.sid,
        })).hexdigest()
        self.binding_root.mkdir(mode=0o700)
        existing = {
            'schema': 1, 'kind': 'session_binding', 'session_ref': session_ref,
            'sid': self.sid, 'project': 'alpha', 'root': str(self.project_root),
            'context_ref': record['context_ref'],
            'create_operation_id': '88888888-8888-4888-8888-888888888888',
            'create_digest': record['digest'],
        }
        leaf = self.binding_root / (session_ref + '.json')
        leaf.write_bytes(_canonical(existing))
        os.chmod(leaf, 0o600)
        before = leaf.read_bytes()
        self._error(lambda: bindings.publish_candidate(reservation), 'store_conflict')
        self.assertEqual(before, leaf.read_bytes())

    def test_symlink_store_root_is_rejected_without_following_or_cleanup(self):
        outside = self.base / 'outside'
        outside.mkdir(mode=0o700)
        symlink = self.base / 'linked-receipts'
        symlink.symlink_to(outside, target_is_directory=True)
        api = self._api()
        def reserve_through_symlink():
            bindings = api.SessionBindings(self.binding_root, self.lock_root, symlink,
                                           self.project_path)
            store = api.CreateStore(symlink, bindings, self.project_path)
            return store.reserve(self.context, 'alpha', self.operation_id)
        self._error(reserve_through_symlink, 'store_unavailable')
        self.assertTrue(symlink.is_symlink())
        self.assertEqual(list(outside.iterdir()), [])

    def test_hardlinked_receipt_leaf_is_rejected_without_touching_peer(self):
        _, store, _ = self._stores()
        self._reservation(store)
        leaf = self._receipt_leaf()
        peer = self.base / 'receipt-peer'
        os.link(leaf, peer)
        before = (leaf.read_bytes(), peer.read_bytes(), leaf.stat().st_nlink)
        self._error(lambda: store.lookup(self.context, 'alpha', self.operation_id),
                    'store_unavailable')
        self.assertEqual(before, (leaf.read_bytes(), peer.read_bytes(), leaf.stat().st_nlink))

    def test_same_operation_concurrent_reserve_has_one_stable_unknown_record(self):
        api, store, _ = self._stores()
        # Separate store objects exercise the public locking boundary while sharing only
        # the synthetic private fixture. Threads always join before fixture cleanup.
        bindings2 = api.SessionBindings(self.binding_root, self.lock_root,
                                        self.receipt_root, self.project_path)
        store2 = api.CreateStore(self.receipt_root, bindings2, self.project_path,
                                 clock=lambda: 1700000000000000002)
        results, failures = [], []
        import threading
        barrier = threading.Barrier(3)

        def reserve(target):
            try:
                barrier.wait(timeout=3)
                results.append(target.reserve(self.context, 'alpha', self.operation_id))
            except BaseException as exc:
                failures.append(exc)

        threads = [threading.Thread(target=reserve, args=(target,), daemon=True)
                   for target in (store, store2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=3)
        for thread in threads:
            thread.join(timeout=5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(_plain(results[0].record), _plain(results[1].record))
        self.assertEqual(_plain(results[0].record)['candidate_sid'], None)
        self.assertEqual(_plain(results[0].record)['status'], 'unknown')

    def test_owned_child_crash_after_prepared_pair_recovers_without_new_dispatch(self):
        api = self._api()
        operation_id = '12345678-1234-4234-8234-123456789abc'
        sid = 'abcdef12-3456-4abc-8def-abcdef123456'
        process = multiprocessing.get_context('spawn').Process(
            target=_prepared_pair_crash_worker,
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
                self.fail('owned synthetic crash worker exceeded bounded wait')
            self.assertEqual(process.exitcode, 73,
                             'child must stop after prepared binding and before acceptance')
        finally:
            if started:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
                if process.is_alive():
                    self.fail('could not stop owned synthetic crash worker')
                process.close()

        bindings = api.SessionBindings(self.binding_root, self.lock_root,
                                       self.receipt_root, self.project_path)
        store = api.CreateStore(self.receipt_root, bindings, self.project_path)
        context = self._context('acct-crash', '99999999-9999-4999-8999-999999999999')
        reservation = store.lookup(context, 'alpha', operation_id)
        self.assertIsNotNone(reservation)
        self.assertEqual(_plain(reservation.record)['candidate_sid'], sid)
        self.assertEqual(_plain(reservation.record)['status'], 'unknown')
        session_ref = hashlib.sha256(_canonical({
            'kind': 'session_binding',
            'context_key': hashlib.sha256(_canonical(_plain(context.reference))).hexdigest(),
            'sid': sid,
        })).hexdigest()
        self.assertIsNone(bindings.resolve('alpha', session_ref, sid))

        receipt_leaf = self._receipt_leaf_for(operation_id)
        binding_leaf = self.binding_root / (session_ref + '.json')
        before_recovery = (receipt_leaf.read_bytes(), receipt_leaf.stat().st_ino,
                           receipt_leaf.stat().st_mtime_ns, binding_leaf.read_bytes(),
                           binding_leaf.stat().st_ino, binding_leaf.stat().st_mtime_ns)
        prepared = bindings.publish_candidate(reservation)
        self.assertEqual(before_recovery, (receipt_leaf.read_bytes(), receipt_leaf.stat().st_ino,
                                           receipt_leaf.stat().st_mtime_ns, binding_leaf.read_bytes(),
                                           binding_leaf.stat().st_ino, binding_leaf.stat().st_mtime_ns))
        accepted = store.commit_accepted(reservation, prepared)
        after_commit = (receipt_leaf.read_bytes(), receipt_leaf.stat().st_ino,
                        receipt_leaf.stat().st_mtime_ns, binding_leaf.read_bytes(),
                        binding_leaf.stat().st_ino, binding_leaf.stat().st_mtime_ns)
        replay = store.commit_accepted(accepted, prepared)
        self.assertEqual(_plain(replay.record)['status'], 'accepted')
        self.assertEqual(_plain(bindings.resolve('alpha', session_ref, sid).record),
                         _plain(prepared.record))
        self.assertEqual(after_commit, (receipt_leaf.read_bytes(), receipt_leaf.stat().st_ino,
                                        receipt_leaf.stat().st_mtime_ns, binding_leaf.read_bytes(),
                                        binding_leaf.stat().st_ino, binding_leaf.stat().st_mtime_ns))

    def test_reservation_and_binding_records_are_deeply_immutable_and_private(self):
        _, store, bindings = self._stores()
        reservation = store.capture_candidate(self._reservation(store), self.sid)
        binding = bindings.publish_candidate(reservation)
        receipt_leaf = self._receipt_leaf()
        binding_leaf = self.binding_root / (binding.record['session_ref'] + '.json')
        before = (receipt_leaf.read_bytes(), binding_leaf.read_bytes())
        self.assertNotIn(str(self.base), repr(reservation))
        self.assertNotIn(str(self.base), repr(binding))
        with self.assertRaises(TypeError):
            reservation.record['status'] = 'accepted'
        with self.assertRaises(TypeError):
            reservation.record['context_ref']['account_id'] = 'other-account'
        with self.assertRaises(TypeError):
            binding.record['context_ref']['account_id'] = 'other-account'
        with self.assertRaises((AttributeError, TypeError)):
            reservation.record = {}
        with self.assertRaises((AttributeError, TypeError)):
            binding.record = {}
        self.assertEqual(before, (receipt_leaf.read_bytes(), binding_leaf.read_bytes()))

    def test_insecure_receipt_mode_fails_closed_without_chmod_or_rewrite(self):
        _, store, _ = self._stores()
        self._reservation(store)
        leaf = self._receipt_leaf()
        os.chmod(leaf, 0o644)
        before = (leaf.read_bytes(), leaf.stat().st_ino, leaf.stat().st_mtime_ns,
                  leaf.stat().st_mode & 0o777)
        self._error(lambda: store.lookup(self.context, 'alpha', self.operation_id),
                    'store_unavailable')
        self._error(lambda: store.reserve(self.context, 'alpha', self.operation_id),
                    'store_unavailable')
        self.assertEqual(before, (leaf.read_bytes(), leaf.stat().st_ino,
                                  leaf.stat().st_mtime_ns, leaf.stat().st_mode & 0o777))

    def test_namespace_capacity_refuses_publication_without_touching_private_entries(self):
        _, store, _ = self._stores()
        self.receipt_root.mkdir(mode=0o700, exist_ok=True)
        for index in range(10002):
            leaf = self.receipt_root / ('fixture-entry-' + str(index).zfill(5))
            fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, ('fixture-' + str(index)).encode('ascii'))
            finally:
                os.close(fd)
        self.assertEqual(len(list(self.receipt_root.iterdir())), 10002)
        before = {entry.name: (entry.stat().st_ino, entry.stat().st_mode & 0o777,
                               entry.read_bytes())
                  for entry in self.receipt_root.iterdir()}
        self._error(lambda: store.reserve(self.context, 'alpha', self.operation_id),
                    'store_unavailable')
        after = {entry.name: (entry.stat().st_ino, entry.stat().st_mode & 0o777,
                              entry.read_bytes())
                 for entry in self.receipt_root.iterdir()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
