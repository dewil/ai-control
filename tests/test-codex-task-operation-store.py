#!/usr/bin/env python3
"""Independent CXTASK-STORE behavioral contract tests; no native effects."""
import fcntl
import importlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
try:
    store_module = importlib.import_module('_codex_task_store')
except ModuleNotFoundError as exc:
    if exc.name != '_codex_task_store':
        raise
    store_module = None
from _codex_task_bridge import TaskBinding

INC = '0123456789abcdef0123456789abcdef'


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    path.chmod(0o600)


class OperationStoreContract(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(store_module,
            'INV-CXSTORE-01: durable operation registry public helper is not implemented')
        self.Store = store_module.CodexTaskOperationStore
        self.Error = store_module.StoreError
        self.old_umask = os.umask(0o077)
        self.addCleanup(os.umask, self.old_umask)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stage = self.root / 'agents/.staging'
        self.agent = self.root / 'agents/taskone'
        self.private = self.root / 'private'
        self.project = self.root / 'project'
        for p in (self.stage / 'work', self.stage / 'inbox/inflight', self.private, self.project):
            p.mkdir(parents=True, exist_ok=True, mode=0o700)
        for p in self.root.rglob('*'):
            if p.is_dir():
                p.chmod(0o700)
        for p in (self.stage / '.lock', self.stage / 'inbox/.inbox.lock'):
            p.touch(mode=0o600)
        self.control = dict(schema=1, incarnation=INC, generation=0,
            desired='paused', hold=None, mission_base='a' * 40,
            acceptance={'status': 'pending'}, lease={'state': 'none', 'start_attempt_id': None},
            seq=0, session_id=None, attention=None, handoff=None)
        save(self.stage / 'control.json', self.control)
        (self.stage / 'spec.yaml').write_text('engine: codex\ntype: event\nruntime: drain\nworkspace: worktree\nproject: ' + str(self.project) + '\n')
        self.sid = str(uuid.uuid4())
        self.now = 100.0
        self.deadline = 110.0
        self.clock = lambda: self.now
        self.index = self.private / self.sid / 'index.json'

    def initialize(self):
        return self.Store.initialize(str(self.stage), str(self.agent), self.sid,
            state_root=str(self.private), clock=self.clock, deadline=self.deadline)

    def publish(self):
        self.initialize()
        self.control.update(codex_state_id=self.sid, generation=7, desired='running',
            lease={'state': 'active', 'start_attempt_id': 'attempt-1'})
        save(self.stage / 'control.json', self.control)
        self.stage.rename(self.agent)
        save(self.agent / 'inbox/inflight/event-1.json', dict(key='event-1', meta={}))
        self.store = self.Store(str(self.agent), state_root=str(self.private), clock=self.clock)

    def prepare(self):
        return self.store.prepare('event-1', 7, 'attempt-1', deadline=self.deadline)

    def read_index(self):
        return json.loads(self.index.read_text())

    def op(self):
        return json.loads((self.agent / 'inbox/inflight/event-1.json').read_text())['meta']['codex_operation']

    def prepare_thread(self):
        record = self.prepare()
        self.store.record_thread(record['operation_id'], 'thread-1', deadline=self.deadline)
        return record['operation_id']

    def activate(self):
        operation = self.prepare_thread()
        with self.store.reserve_start(operation, deadline=self.deadline) as handle:
            handle.activate('thread-1', 'turn-1')
        return operation

    def drained(self, operation):
        record = self.read_index()['operations'][operation]
        host = Path(record['host_state_dir'])
        host.mkdir(mode=0o700, parents=True, exist_ok=True)
        token = str(uuid.uuid4())
        unit = 'cctask-' + token + '.service'
        save(host / 'journal.json', dict(schema=1,
            task_incarnation=str(uuid.UUID(hex=INC)), cwd=str(self.agent / 'work'),
            executable=os.path.realpath(sys.executable), unit=unit, token=token,
            socket=str(host / 'server.sock'), phase='stopped',
            invocation_id='b' * 32, socket_identity=None))
        return dict(operation_id=operation, task_incarnation=INC,
            host_state_dir=str(host), phase='stopped', unit=unit, token=token,
            invocation_id='b' * 32, drained=True)

    def historical(self, *, finished=True, outcome='ok'):
        self.publish()
        operation = self.activate()
        self.store.revoke(deadline=self.deadline)
        self.store.record_drained(operation, self.drained(operation), deadline=self.deadline)
        if finished:
            self.store.finish(operation, dict(operation_id=operation, task_incarnation=INC,
                thread_id='thread-1', turn_id='turn-1', terminal='completed',
                terminal_proven=True, quiescent=True), deadline=self.deadline)
        path = self.agent / 'inbox/inflight/event-1.json'
        envelope = json.loads(path.read_text())
        envelope['meta']['history'] = [{'outcome': outcome}]
        save(path, envelope)
        done = self.agent / 'inbox/done'
        done.mkdir(mode=0o700)
        destination = done / path.name
        path.rename(destination)
        return operation, destination

    def historical_refused(self):
        try:
            result = self.store.snapshot(deadline=self.deadline)
        except self.Error:
            pass
        else:
            self.assertIs(result['reconciliation_required'], True)
        with self.assertRaises(self.Error):
            self.store.require_drained(deadline=self.deadline)

    def test_historical_finished_matching_done_supports_snapshot_and_cleanup(self):
        # INV-CXSTORE-04: immutable completed envelope remains durable evidence.
        operation, destination = self.historical()
        before = destination.read_bytes()
        snapshot = self.store.snapshot(deadline=self.deadline)
        self.assertIs(snapshot['reconciliation_required'], False)
        self.assertEqual(snapshot['operations'][operation]['status'], 'finished')
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)
        self.assertEqual(destination.read_bytes(), before)

    def test_historical_finished_asked_is_valid_terminal_history(self):
        operation, path = self.historical(outcome='asked')
        self.assertIs(self.store.snapshot(deadline=self.deadline)['reconciliation_required'], False)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)

    def test_historical_revoked_not_launched_cancelled_supports_cleanup(self):
        self.publish()
        operation = self.prepare()['operation_id']
        self.store.revoke(deadline=self.deadline)
        source = self.agent / 'inbox/inflight/event-1.json'
        envelope = json.loads(source.read_text())
        envelope['meta']['history'] = [{'outcome': 'cancelled'}]
        save(source, envelope)
        done = self.agent / 'inbox/done'
        done.mkdir(mode=0o700)
        source.rename(done / source.name)
        self.assertIs(self.store.snapshot(deadline=self.deadline)['reconciliation_required'], False)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)

    def test_historical_pending_or_deadletter_path_is_not_terminal_evidence(self):
        operation, path = self.historical()
        for folder in ('pending', 'deadletter'):
            with self.subTest(folder=folder):
                directory = self.agent / 'inbox' / folder
                directory.mkdir(mode=0o700)
                other = directory / path.name
                path.rename(other)
                self.historical_refused()
                other.rename(path)

    def test_historical_revoked_drained_cancelled_supports_cleanup(self):
        operation, destination = self.historical(finished=False, outcome='cancelled')
        self.assertEqual(self.store.snapshot(deadline=self.deadline)['operations'][operation]['status'], 'revoked')
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)

    def test_historical_active_and_prepared_done_never_authorize_cleanup(self):
        self.publish()
        operation = self.prepare()['operation_id']
        path = self.agent / 'inbox/inflight/event-1.json'
        envelope = json.loads(path.read_text())
        envelope['meta']['history'] = [{'outcome': 'ok'}]
        save(path, envelope)
        done = self.agent / 'inbox/done'
        done.mkdir(mode=0o700)
        destination = done / path.name
        path.rename(destination)
        self.historical_refused()

    def test_historical_active_even_matching_native_drain_refuses(self):
        self.publish()
        operation = self.activate()
        self.store.record_drained(operation, self.drained(operation), deadline=self.deadline)
        path = self.agent / 'inbox/inflight/event-1.json'
        envelope = json.loads(path.read_text())
        envelope['meta']['history'] = [{'outcome': 'ok'}]
        save(path, envelope)
        done = self.agent / 'inbox/done'
        done.mkdir(mode=0o700)
        path.rename(done / path.name)
        self.historical_refused()

    def test_historical_projection_mismatches_refuse(self):
        operation, path = self.historical()
        original = json.loads(path.read_text())
        for field, value in (('status', 'active'), ('operation_id', str(uuid.uuid4())),
            ('task_incarnation', 'f' * 32), ('generation', 8), ('attempt_id', 'foreign'),
            ('thread_id', 'foreign-thread'), ('turn_id', 'foreign-turn'),
            ('start_reserved', False), ('launch_reserved', True)):
            with self.subTest(field=field):
                envelope = json.loads(json.dumps(original))
                envelope['meta']['codex_operation'][field] = value
                save(path, envelope)
                self.historical_refused()
        save(path, original)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)

    def test_historical_wrong_key_missing_history_and_unknown_outcome_refuse(self):
        operation, path = self.historical()
        original = json.loads(path.read_text())
        variants = []
        wrong_key = json.loads(json.dumps(original))
        wrong_key['key'] = 'foreign-event'
        variants.append(wrong_key)
        no_history = json.loads(json.dumps(original))
        del no_history['meta']['history']
        no_history['result'] = 'completed successfully'
        variants.append(no_history)
        for history in ([], [{'outcome': 'unknown'}], [{'outcome': 'ok'}, {'outcome': 'pending'}],
            [{'outcome': True}], [{'outcome': None}]):
            envelope = json.loads(json.dumps(original))
            envelope['meta']['history'] = history
            variants.append(envelope)
        for number, envelope in enumerate(variants):
            with self.subTest(number=number):
                save(path, envelope)
                self.historical_refused()

    def test_historical_missing_or_corrupt_done_refuses(self):
        operation, path = self.historical()
        path.unlink()
        self.historical_refused()
        path.write_text('{broken')
        path.chmod(0o600)
        self.historical_refused()

    def test_historical_finished_never_allows_same_event_projection_replacement(self):
        operation, path = self.historical()
        before = self.index.read_bytes()
        done_before = path.read_bytes()
        with self.assertRaises(self.Error):
            self.prepare()
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(path.read_bytes(), done_before)
        self.assertFalse((self.agent / 'inbox/inflight/event-1.json').exists())
        self.assertEqual(set(self.read_index()['operations']), {operation})

    def test_finished_inflight_never_allows_same_event_projection_replacement(self):
        operation, path = self.historical()
        inflight = self.agent / 'inbox/inflight/event-1.json'
        path.rename(inflight)
        before = inflight.read_bytes()
        index_before = self.index.read_bytes()
        with self.assertRaises(self.Error):
            self.prepare()
        self.assertEqual(inflight.read_bytes(), before)
        self.assertEqual(self.index.read_bytes(), index_before)

    def test_not_launched_cleanup_requires_intact_host_directory(self):
        # INV-CXSTORE-04 / INV-CXSTORE-05: absent journal is not absent host proof.
        self.publish()
        operation = self.prepare()['operation_id']
        self.store.revoke(deadline=self.deadline)
        host = Path(self.read_index()['operations'][operation]['host_state_dir'])
        self.assertTrue(host.is_dir())
        self.assertFalse((host / 'journal.json').exists())
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)
        saved = host.with_name('saved-host')
        host.rename(saved)
        with self.assertRaises(self.Error):
            self.store.require_drained(deadline=self.deadline)
        host.symlink_to(self.root / 'nonexistent-host', target_is_directory=True)
        with self.assertRaises(self.Error):
            self.store.require_drained(deadline=self.deadline)
        host.unlink()
        host.write_text('not a directory')
        host.chmod(0o600)
        with self.assertRaises(self.Error):
            self.store.require_drained(deadline=self.deadline)
        host.unlink()
        saved.rename(host)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)

    def test_not_launched_cleanup_refuses_missing_operation_parent(self):
        self.publish()
        operation = self.prepare()['operation_id']
        self.store.revoke(deadline=self.deadline)
        host = Path(self.read_index()['operations'][operation]['host_state_dir'])
        parent = host.parent
        saved = parent.with_name('saved-operation')
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)
        parent.rename(saved)
        with self.assertRaises(self.Error):
            self.store.require_drained(deadline=self.deadline)
        saved.rename(parent)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)

    def test_replaced_not_launched_host_directory_never_becomes_drain_proof(self):
        # INV-CXSTORE-04 / INV-CXSTORE-05: same safe pathname is not original identity.
        self.publish()
        operation = self.prepare()['operation_id']
        self.store.revoke(deadline=self.deadline)
        host = Path(self.read_index()['operations'][operation]['host_state_dir'])
        saved = host.with_name('original-host')
        original_index = self.index.read_bytes()
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)
        host.rename(saved)
        host.mkdir(mode=0o700)
        try:
            for store in (self.store, self.Store(str(self.agent), state_root=str(self.private), clock=self.clock)):
                with self.subTest(reopened=store is not self.store), self.assertRaises(self.Error):
                    store.require_drained(deadline=self.deadline)
            self.assertEqual(self.index.read_bytes(), original_index)
            self.assertEqual(list(host.iterdir()), [])
        finally:
            host.rmdir()
            saved.rename(host)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)
        reopened = self.Store(str(self.agent), state_root=str(self.private), clock=self.clock)
        self.assertIs(reopened.require_drained(deadline=self.deadline), True)

    def test_replaced_operation_parent_refuses_even_when_original_host_is_moved_back(self):
        # INV-CXSTORE-04 / INV-CXSTORE-05: all original private parent identities survive restart.
        self.publish()
        operation = self.prepare()['operation_id']
        self.store.revoke(deadline=self.deadline)
        host = Path(self.read_index()['operations'][operation]['host_state_dir'])
        parent = host.parent
        saved = parent.with_name('original-operation')
        original_index = self.index.read_bytes()
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)
        parent.rename(saved)
        parent.mkdir(mode=0o700)
        (saved / 'host').rename(host)
        try:
            for store in (self.store, self.Store(str(self.agent), state_root=str(self.private), clock=self.clock)):
                with self.subTest(reopened=store is not self.store), self.assertRaises(self.Error):
                    store.require_drained(deadline=self.deadline)
            self.assertEqual(self.index.read_bytes(), original_index)
        finally:
            host.rename(saved / 'host')
            parent.rmdir()
            saved.rename(parent)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)
        reopened = self.Store(str(self.agent), state_root=str(self.private), clock=self.clock)
        self.assertIs(reopened.require_drained(deadline=self.deadline), True)

    def partial_drain_publication(self):
        self.publish()
        operation = self.activate()
        self.store.revoke(deadline=self.deadline)
        evidence = self.drained(operation)
        self.assertIsNone(self.op()['drain_evidence'])
        real_replace = os.replace
        def crash(src, dst, *args, **kwargs):
            if Path(dst) == self.agent / 'inbox/inflight/event-1.json':
                raise OSError('injected drain projection crash')
            return real_replace(src, dst, *args, **kwargs)
        with patch('os.replace', side_effect=crash), self.assertRaises(self.Error):
            self.store.record_drained(operation, evidence, deadline=self.deadline)
        self.assertEqual(self.read_index()['operations'][operation]['drain_evidence'], evidence)
        self.assertIsNone(self.op()['drain_evidence'])
        return operation, evidence

    def test_drain_receipt_exact_repeat_repairs_projection_after_crash(self):
        # INV-CXSTORE-03 / INV-CXSTORE-04: durable receipt before projection.
        operation, evidence = self.partial_drain_publication()
        journal = Path(evidence['host_state_dir']) / 'journal.json'
        journal_before = journal.read_bytes()
        self.store.record_drained(operation, evidence, deadline=self.deadline)
        self.assertEqual(self.op()['drain_evidence'], evidence)
        self.assertEqual(self.read_index()['operations'][operation]['drain_evidence'], evidence)
        self.assertEqual(journal.read_bytes(), journal_before)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)

    def test_drain_receipt_conflicting_repeat_cannot_replace_durable_proof(self):
        operation, evidence = self.partial_drain_publication()
        index_before = self.index.read_bytes()
        for field, value in (('invocation_id', 'c' * 32),
            ('token', str(uuid.uuid4())), ('operation_id', str(uuid.uuid4()))):
            with self.subTest(field=field), self.assertRaises(self.Error):
                self.store.record_drained(operation, dict(evidence, **{field: value}), deadline=self.deadline)
            self.assertEqual(self.index.read_bytes(), index_before)
            self.assertEqual(self.read_index()['operations'][operation]['drain_evidence'], evidence)
        self.store.record_drained(operation, evidence, deadline=self.deadline)
        self.assertEqual(self.op()['drain_evidence'], evidence)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)

    def test_creator_registry_precedes_marker_and_final_publication(self):
        # INV-CXSTORE-01
        original = (self.stage / 'control.json').read_bytes()
        self.assertEqual(self.initialize(), self.sid)
        self.assertFalse(self.agent.exists())
        self.assertEqual((self.stage / 'control.json').read_bytes(), original)
        index = self.read_index()
        self.assertEqual(index['agent_dir'], str(self.agent))
        self.assertEqual(index['task_incarnation'], INC)
        self.assertEqual(index['operations'], {})
        with self.assertRaises(self.Error):
            self.initialize()

    def test_constructor_is_inert(self):
        self.Store(str(self.agent), state_root=str(self.private), clock=self.clock)
        self.assertFalse((self.private / self.sid).exists())
        self.assertFalse(self.agent.exists())

    def test_marker_without_index_never_reinitializes(self):
        self.publish()
        self.index.unlink()
        with self.assertRaises(self.Error):
            self.prepare()
        self.assertFalse(self.index.exists())
        with self.assertRaises(self.Error):
            self.store.require_drained(deadline=self.deadline)

    def test_runtime_missing_marker_refused(self):
        self.publish()
        del self.control['codex_state_id']
        save(self.agent / 'control.json', self.control)
        with self.assertRaises(self.Error):
            self.prepare()

    def test_prepare_immutable_binding_and_no_authority(self):
        # INV-CXSTORE-02
        self.publish()
        record = self.prepare()
        uuid.UUID(record['operation_id'])
        self.assertEqual(record['status'], 'prepared')
        self.assertIsNone(record['thread_id'])
        self.assertIsNone(record['turn_id'])
        self.assertFalse(record['start_reserved'])
        self.assertFalse(record['launch_reserved'])
        expected = self.private / self.sid / 'operations' / record['operation_id'] / 'host'
        self.assertEqual(record['host_state_dir'], str(expected))
        self.assertEqual(self.op()['operation_id'], record['operation_id'])
        self.assertEqual(self.op()['status'], 'prepared')
        record['status'] = 'active'
        self.assertEqual(self.read_index()['operations'][record['operation_id']]['status'], 'prepared')

    def test_second_unfinished_event_operation_refused(self):
        self.publish()
        self.prepare()
        with self.assertRaises(self.Error):
            self.prepare()

    def test_thread_assignment_immutable(self):
        self.publish()
        operation = self.prepare_thread()
        self.store.record_thread(operation, 'thread-1', deadline=self.deadline)
        with self.assertRaises(self.Error):
            self.store.record_thread(operation, 'foreign', deadline=self.deadline)

    def test_rpc_reservation_durable_before_yield_one_shot(self):
        self.publish()
        operation = self.prepare_thread()
        with self.store.reserve_start(operation, deadline=self.deadline):
            self.assertTrue(self.read_index()['operations'][operation]['start_reserved'])
            self.assertTrue(self.op()['start_reserved'])
            self.assertEqual(self.op()['status'], 'prepared')
        with self.assertRaises(self.Error):
            with self.store.reserve_start(operation, deadline=self.deadline):
                self.fail('reserved RPC retried')

    def test_publication_handle_activates_exact_ids_and_expires(self):
        # INV-CXSTORE-03
        self.publish()
        operation = self.prepare_thread()
        with self.store.reserve_start(operation, deadline=self.deadline) as handle:
            handle.activate('thread-1', 'turn-1')
            self.assertEqual(self.read_index()['operations'][operation]['status'], 'active')
            self.assertEqual(self.op()['status'], 'active')
        with self.assertRaises(self.Error):
            handle.activate('thread-1', 'turn-1')

    def test_publication_handle_is_bound_to_originating_thread(self):
        self.publish()
        operation = self.prepare_thread()
        errors = []
        with self.store.reserve_start(operation, deadline=self.deadline) as handle:
            def foreign():
                try:
                    handle.activate('thread-1', 'turn-1')
                except self.Error:
                    errors.append(True)
            thread = threading.Thread(target=foreign)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [True])
            self.assertEqual(self.op()['status'], 'prepared')
            handle.activate('thread-1', 'turn-1')

    def test_activation_foreign_thread_id_refused(self):
        self.publish()
        operation = self.prepare_thread()
        with self.store.reserve_start(operation, deadline=self.deadline) as handle:
            with self.assertRaises(self.Error):
                handle.activate('foreign', 'turn-1')
            self.assertEqual(self.op()['status'], 'prepared')

    def test_launch_reservation_one_shot_and_unknown_host_drain_refusal(self):
        # INV-CXSTORE-04
        self.publish()
        operation = self.prepare()['operation_id']
        with self.store.launch_guard(operation, deadline=self.deadline):
            self.assertTrue(self.read_index()['operations'][operation]['launch_reserved'])
        with self.assertRaises(self.Error):
            with self.store.launch_guard(operation, deadline=self.deadline):
                self.fail('launch retried')
        with self.assertRaises(self.Error):
            self.store.require_drained(deadline=self.deadline)

    def test_not_launched_registry_satisfies_drain_gate(self):
        self.publish()
        self.prepare()
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)

    def test_revoke_cancels_late_launch(self):
        self.publish()
        operation = self.prepare()['operation_id']
        self.store.revoke(deadline=self.deadline)
        self.assertEqual(self.op()['status'], 'revoked')
        with self.assertRaises(self.Error):
            with self.store.launch_guard(operation, deadline=self.deadline):
                self.fail('launch after revocation')

    def test_revoked_guard_holds_actual_fence_across_abort(self):
        self.publish()
        operation = self.activate()
        self.store.revoke(deadline=self.deadline)
        self.control.update(desired='stopped', generation=8)
        save(self.agent / 'control.json', self.control)
        with self.store.revoked_guard(operation, str(uuid.UUID(hex=INC)), deadline=self.deadline) as granted:
            self.assertIs(granted, True)
            for path in (self.agent / '.lock', self.agent / 'inbox/.inbox.lock', self.private / self.sid / 'store.lock'):
                fd = os.open(path, os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(fd)

    def test_revoked_guard_refuses_active_foreign_and_missing_registry(self):
        self.publish()
        operation = self.activate()
        with self.assertRaises(self.Error):
            with self.store.revoked_guard(operation, str(uuid.UUID(hex=INC)), deadline=self.deadline):
                self.fail('active operation admitted abort fence')
        self.store.revoke(deadline=self.deadline)
        for op, inc in ((operation, str(uuid.uuid4())), (str(uuid.uuid4()), str(uuid.UUID(hex=INC))), (operation, INC)):
            with self.subTest(operation=op, incarnation=inc), self.assertRaises(self.Error):
                with self.store.revoked_guard(op, inc, deadline=self.deadline):
                    self.fail('foreign host admitted abort fence')
        self.index.unlink()
        with self.assertRaises(self.Error):
            with self.store.revoked_guard(operation, str(uuid.UUID(hex=INC)), deadline=self.deadline):
                self.fail('lost registry granted stop authority')

    def test_revoke_safe_for_stopped_stale_generation(self):
        self.publish()
        operation = self.activate()
        self.control.update(desired='stopped', generation=8)
        save(self.agent / 'control.json', self.control)
        self.store.revoke(deadline=self.deadline)
        self.assertEqual(self.op()['status'], 'revoked')
        self.assertEqual(self.read_index()['operations'][operation]['status'], 'revoked')

    def test_generation_change_cannot_forget_reserved_host(self):
        self.publish()
        operation = self.prepare()['operation_id']
        with self.store.launch_guard(operation, deadline=self.deadline):
            pass
        self.control['generation'] = 8
        self.control['lease']['start_attempt_id'] = 'attempt-2'
        save(self.agent / 'control.json', self.control)
        with self.assertRaises(self.Error):
            self.store.prepare('event-1', 8, 'attempt-2', deadline=self.deadline)
        self.assertIn(operation, self.read_index()['operations'])

    def test_authority_mutations_require_exact_control(self):
        self.publish()
        for field, bad in (('desired', 'stopped'), ('hold', 'operator'), ('generation', 8)):
            old = self.control[field]
            self.control[field] = bad
            save(self.agent / 'control.json', self.control)
            with self.subTest(field=field), self.assertRaises(self.Error):
                self.prepare()
            self.control[field] = old
        save(self.agent / 'control.json', self.control)
        self.assertEqual(self.read_index()['operations'], {})

    def test_identity_and_bounds_inputs_refused_without_records(self):
        self.publish()
        for event, generation, attempt in (('../x', 7, 'a'), ('x/y', 7, 'a'),
            ('event-1', True, 'a'), ('event-1', 0, 'a'), ('event-1', 7, ''),
            ('event-1', 7, ' a '), ('event-1', 7, 'a/b'), ('event-1', 7, 'x' * 257)):
            with self.subTest(event=event, generation=generation, attempt=attempt), self.assertRaises(self.Error):
                self.store.prepare(event, generation, attempt, deadline=self.deadline)
        self.assertEqual(self.read_index()['operations'], {})

    def test_deadline_validation_precedes_effects(self):
        self.publish()
        for deadline in (True, None, '110', math.nan, math.inf, -math.inf, 100.0, 99.0):
            with self.subTest(deadline=deadline), self.assertRaises(self.Error):
                self.store.prepare('event-1', 7, 'attempt-1', deadline=deadline)
        self.assertEqual(self.read_index()['operations'], {})

    def test_busy_actual_control_inbox_and_store_locks_refuse(self):
        self.publish()
        for path in (self.agent / '.lock', self.agent / 'inbox/.inbox.lock', self.private / self.sid / 'store.lock'):
            fd = os.open(path, os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.subTest(path=path), self.assertRaises(self.Error):
                    self.prepare()
            finally:
                os.close(fd)
        self.assertEqual(self.read_index()['operations'], {})

    def test_guards_hold_all_actual_locks_across_caller_effect(self):
        self.publish()
        operation = self.prepare_thread()
        for guard in (self.store.launch_guard, self.store.reserve_start):
            with guard(operation, deadline=self.deadline):
                for path in (self.agent / '.lock', self.agent / 'inbox/.inbox.lock', self.private / self.sid / 'store.lock'):
                    fd = os.open(path, os.O_RDWR)
                    try:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    finally:
                        os.close(fd)

    def test_guard_locked_composes_without_recursive_control_flock(self):
        self.publish()
        operation = self.activate()
        binding = TaskBinding(INC, 'event-1', str(self.agent), 'thread-1', 'turn-1')
        fds = [os.open(p, os.O_RDWR) for p in (self.agent / '.lock', self.agent / 'inbox/.inbox.lock')]
        try:
            for fd in fds:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.store.guard_locked(binding, operation, deadline=self.deadline) as granted:
                self.assertIs(granted, True)
        finally:
            for fd in fds:
                os.close(fd)

    def test_invalid_json_duplicate_nonfinite_overflow_refused(self):
        # INV-CXSTORE-05
        self.publish()
        valid = self.index.read_text()
        for content in ('{bad', valid[:-1] + ',"schema":1}',
            valid[:-1] + ',"unknown":NaN}', valid[:-1] + ',"unknown":Infinity}',
            valid[:-1] + ',"unknown":{"nested":1e999}}'):
            self.index.write_text(content)
            with self.subTest(content=content[-45:]), self.assertRaises(self.Error):
                self.store.snapshot(deadline=self.deadline)
            with self.assertRaises(self.Error):
                self.store.require_drained(deadline=self.deadline)
        self.index.write_text(valid)

    def test_private_modes_and_single_link_files(self):
        self.publish()
        self.prepare()
        for p in (self.private / self.sid).rglob('*'):
            self.assertEqual(p.stat().st_mode & 0o777, 0o700 if p.is_dir() else 0o600)
            if p.is_file():
                self.assertEqual(p.stat().st_nlink, 1)
        self.index.chmod(0o644)
        with self.assertRaises(self.Error):
            self.store.snapshot(deadline=self.deadline)

    def test_hardlink_index_refused(self):
        self.publish()
        os.link(self.index, self.root / 'alias')
        with self.assertRaises(self.Error):
            self.prepare()

    def test_symlink_index_and_ancestor_refused(self):
        self.publish()
        actual = self.index.with_name('saved.json')
        self.index.rename(actual)
        self.index.symlink_to(actual)
        with self.assertRaises(self.Error):
            self.prepare()
        self.index.unlink()
        actual.rename(self.index)
        alias = self.root / 'private-alias'
        alias.symlink_to(self.private, target_is_directory=True)
        with self.assertRaises(self.Error):
            other = self.Store(str(self.agent), state_root=str(alias), clock=self.clock)
            other.snapshot(deadline=self.deadline)

    def test_drain_unknown_journal_or_foreign_evidence_refused(self):
        self.publish()
        operation = self.prepare()['operation_id']
        evidence = dict(operation_id=operation, task_incarnation=INC,
            host_state_dir=self.read_index()['operations'][operation]['host_state_dir'],
            phase='stopped', unit='cctask-' + str(uuid.uuid4()) + '.service',
            token=str(uuid.uuid4()), invocation_id='b' * 32, drained=True)
        with self.assertRaises(self.Error):
            self.store.record_drained(operation, evidence, deadline=self.deadline)
        evidence['operation_id'] = str(uuid.uuid4())
        with self.assertRaises(self.Error):
            self.store.record_drained(operation, evidence, deadline=self.deadline)

    def test_finish_requires_owned_terminal_and_prior_drain(self):
        self.publish()
        operation = self.activate()
        evidence = dict(operation_id=operation, task_incarnation=INC,
            thread_id='thread-1', turn_id='turn-1', terminal='completed',
            terminal_proven=True, quiescent=True)
        for changes in ({}, {'thread_id': 'foreign'}, {'turn_id': 'foreign'},
            {'terminal_proven': False}, {'quiescent': False}, {'extra': 'value'}):
            with self.subTest(changes=changes), self.assertRaises(self.Error):
                self.store.finish(operation, dict(evidence, **changes), deadline=self.deadline)
        self.assertEqual(self.op()['status'], 'active')

    def test_matching_drain_then_terminal_finish_preserves_tombstone(self):
        self.publish()
        operation = self.activate()
        evidence = self.drained(operation)
        self.store.record_drained(operation, evidence, deadline=self.deadline)
        self.assertIs(self.store.require_drained(deadline=self.deadline), True)
        terminal = dict(operation_id=operation, task_incarnation=INC,
            thread_id='thread-1', turn_id='turn-1', terminal='completed',
            terminal_proven=True, quiescent=True)
        self.store.finish(operation, terminal, deadline=self.deadline)
        self.store.finish(operation, terminal, deadline=self.deadline)
        self.assertEqual(self.op()['status'], 'finished')
        self.assertEqual(self.read_index()['operations'][operation]['status'], 'finished')
        self.assertEqual(self.read_index()['operations'][operation]['drain_evidence'], evidence)

    def test_matching_journal_required_for_each_drain_identity(self):
        self.publish()
        operation = self.activate()
        evidence = self.drained(operation)
        for field, value in (('unit', 'cctask-' + str(uuid.uuid4()) + '.service'),
            ('token', str(uuid.uuid4())), ('invocation_id', 'c' * 32),
            ('host_state_dir', str(self.root)), ('drained', 1), ('extra', True)):
            with self.subTest(field=field), self.assertRaises(self.Error):
                self.store.record_drained(operation, dict(evidence, **{field: value}), deadline=self.deadline)
        with self.assertRaises(self.Error):
            self.store.require_drained(deadline=self.deadline)

    def test_revoke_inflight_first_crash_can_only_reconcile_to_revoked(self):
        self.publish()
        operation = self.activate()
        real_replace = os.replace
        def crash(src, dst, *args, **kwargs):
            if Path(dst) == self.index:
                raise OSError('injected registry crash')
            return real_replace(src, dst, *args, **kwargs)
        with patch('os.replace', side_effect=crash), self.assertRaises(self.Error):
            self.store.revoke(deadline=self.deadline)
        self.assertEqual(self.op()['status'], 'revoked')
        self.assertEqual(self.read_index()['operations'][operation]['status'], 'active')
        self.assertIs(self.store.snapshot(deadline=self.deadline)['reconciliation_required'], True)
        self.store.revoke(deadline=self.deadline)
        self.assertEqual(self.read_index()['operations'][operation]['status'], 'revoked')

    def test_finish_inflight_first_crash_replays_only_matching_terminal(self):
        self.publish()
        operation = self.activate()
        self.store.record_drained(operation, self.drained(operation), deadline=self.deadline)
        evidence = dict(operation_id=operation, task_incarnation=INC,
            thread_id='thread-1', turn_id='turn-1', terminal='completed',
            terminal_proven=True, quiescent=True)
        real_replace = os.replace
        def crash(src, dst, *args, **kwargs):
            if Path(dst) == self.index:
                raise OSError('injected finish crash')
            return real_replace(src, dst, *args, **kwargs)
        with patch('os.replace', side_effect=crash), self.assertRaises(self.Error):
            self.store.finish(operation, evidence, deadline=self.deadline)
        self.assertEqual(self.op()['status'], 'finished')
        with self.assertRaises(self.Error):
            self.store.finish(operation, dict(evidence, terminal='failed'), deadline=self.deadline)
        self.store.finish(operation, evidence, deadline=self.deadline)
        self.assertEqual(self.read_index()['operations'][operation]['status'], 'finished')

    def test_cancel_competes_with_launch_fence_and_blocks_late_effect(self):
        self.publish()
        operation = self.prepare()['operation_id']
        outcomes = []
        with self.store.launch_guard(operation, deadline=self.deadline):
            def cancel():
                try:
                    self.store.revoke(deadline=self.deadline)
                except self.Error:
                    outcomes.append('busy')
            thread = threading.Thread(target=cancel)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes, ['busy'])
            self.assertEqual(self.op()['status'], 'prepared')
        self.store.revoke(deadline=self.deadline)
        with self.assertRaises(self.Error):
            with self.store.launch_guard(operation, deadline=self.deadline):
                self.fail('late launch survived cancellation')

    def test_crash_during_launch_or_start_intent_never_retries(self):
        for method in ('launch_guard', 'reserve_start'):
            with self.subTest(method=method):
                # Each intent tested on a separate event, keeping history intact.
                self.publish() if not self.agent.exists() else None
                event = 'event-' + method
                save(self.agent / ('inbox/inflight/' + event + '.json'), dict(key=event, meta={}))
                operation = self.store.prepare(event, 7, 'attempt-1', deadline=self.deadline)['operation_id']
                if method == 'reserve_start':
                    self.store.record_thread(operation, 'thread-1', deadline=self.deadline)
                real_replace = os.replace
                def crash(src, dst, *args, **kwargs):
                    if Path(dst) == self.agent / ('inbox/inflight/' + event + '.json'):
                        raise OSError('injected reservation crash')
                    return real_replace(src, dst, *args, **kwargs)
                with patch('os.replace', side_effect=crash), self.assertRaises(self.Error):
                    with getattr(self.store, method)(operation, deadline=self.deadline):
                        self.fail('effect before both durable publications')
                with self.assertRaises(self.Error):
                    with getattr(self.store, method)(operation, deadline=self.deadline):
                        self.fail('uncertain reservation retried')
                # Resolve metadata authority only, without granting effects.
                self.store.revoke(deadline=self.deadline)

    def test_record_thread_partial_publication_replays_exact_id_only(self):
        self.publish()
        operation = self.prepare()['operation_id']
        real_replace = os.replace
        def crash(src, dst, *args, **kwargs):
            if Path(dst) == self.agent / 'inbox/inflight/event-1.json':
                raise OSError('injected thread publication crash')
            return real_replace(src, dst, *args, **kwargs)
        with patch('os.replace', side_effect=crash), self.assertRaises(self.Error):
            self.store.record_thread(operation, 'thread-1', deadline=self.deadline)
        with self.assertRaises(self.Error):
            self.store.record_thread(operation, 'foreign', deadline=self.deadline)
        self.store.record_thread(operation, 'thread-1', deadline=self.deadline)
        self.assertEqual(self.op()['thread_id'], 'thread-1')

    def test_fsync_expiry_keeps_reservation_uncertain(self):
        self.publish()
        operation = self.prepare_thread()
        real_fsync = os.fsync
        def expires(fd):
            result = real_fsync(fd)
            self.now = self.deadline
            return result
        with patch('os.fsync', side_effect=expires), self.assertRaises(self.Error):
            with self.store.reserve_start(operation, deadline=self.deadline):
                self.fail('expired reservation entered RPC effect')
        self.now = 100.0
        if self.read_index()['operations'][operation]['start_reserved']:
            with self.assertRaises(self.Error):
                with self.store.reserve_start(operation, deadline=self.deadline):
                    self.fail('durably uncertain reservation retried')

    def test_index_capacity_no_eviction_or_partial_257th_operation(self):
        self.publish()
        for number in range(256):
            event = 'capacity-' + str(number)
            path = self.agent / ('inbox/inflight/' + event + '.json')
            save(path, dict(key=event, meta={}))
            self.store.prepare(event, 7, 'attempt-1', deadline=self.deadline)
            self.store.revoke(deadline=self.deadline)
        before = self.index.read_bytes()
        save(self.agent / 'inbox/inflight/overflow.json', dict(key='overflow', meta={}))
        with self.assertRaises(self.Error):
            self.store.prepare('overflow', 7, 'attempt-1', deadline=self.deadline)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(len(self.read_index()['operations']), 256)

    def test_registry_returns_previous_generation_undrained_hosts(self):
        self.publish()
        operation = self.prepare()['operation_id']
        with self.store.launch_guard(operation, deadline=self.deadline):
            pass
        self.control.update(generation=8, desired='stopped')
        self.control['lease']['start_attempt_id'] = 'attempt-2'
        save(self.agent / 'control.json', self.control)
        records = self.store.revoke(deadline=self.deadline)
        self.assertIn(operation, [record['operation_id'] for record in records])
        with self.assertRaises(self.Error):
            self.store.require_drained(deadline=self.deadline)

    def test_replaced_parent_during_fence_fails_pin_validation(self):
        self.publish()
        operation = self.prepare_thread()
        with self.assertRaises(self.Error):
            with self.store.reserve_start(operation, deadline=self.deadline) as handle:
                moved = self.agent.with_name('old-agent')
                self.agent.rename(moved)
                self.agent.mkdir(mode=0o700)
                handle.activate('thread-1', 'turn-1')
        self.assertNotEqual(self.read_index()['operations'][operation]['status'], 'active')

    def test_managed_state_root_inside_agent_work_refused(self):
        forbidden = self.stage / 'work/private'
        forbidden.mkdir(mode=0o700)
        with self.assertRaises(self.Error):
            self.Store.initialize(str(self.stage), str(self.agent), self.sid,
                state_root=str(forbidden), clock=self.clock, deadline=self.deadline)
        self.assertFalse((forbidden / self.sid).exists())

    def test_creator_rejects_live_lease_and_staging_marker(self):
        for changes in ({'generation': 1}, {'desired': 'running'},
            {'lease': {'state': 'active', 'start_attempt_id': 'attempt-1'}},
            {'codex_state_id': self.sid}):
            with self.subTest(changes=changes):
                save(self.stage / 'control.json', dict(self.control, **changes))
                with self.assertRaises(self.Error):
                    self.initialize()
                self.assertFalse(self.index.exists())

    def test_snapshot_fresh_exact_shape_and_no_effects(self):
        self.publish()
        operation = self.prepare()['operation_id']
        before = self.index.read_bytes()
        result = self.store.snapshot(deadline=self.deadline)
        self.assertEqual(set(result), {'schema', 'state_id', 'agent_dir',
            'task_incarnation', 'operations', 'reconciliation_required'})
        self.assertIs(result['reconciliation_required'], False)
        result['operations'][operation]['status'] = 'active'
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(self.store.snapshot(deadline=self.deadline)['operations'][operation]['status'], 'prepared')

    def test_crash_between_registry_and_inflight_never_grants_launch(self):
        self.publish()
        real_replace = os.replace
        def crash(src, dst, *args, **kwargs):
            if Path(dst) == self.agent / 'inbox/inflight/event-1.json':
                raise OSError('injected publication crash')
            return real_replace(src, dst, *args, **kwargs)
        with patch('os.replace', side_effect=crash), self.assertRaises(self.Error):
            self.prepare()
        records = self.read_index()['operations']
        self.assertEqual(len(records), 1)
        operation = next(iter(records))
        with self.assertRaises(self.Error):
            with self.store.launch_guard(operation, deadline=self.deadline):
                self.fail('partial prepared publication granted launch')

    def test_activation_index_before_inflight_failure_never_promotes_on_reopen(self):
        self.publish()
        operation = self.prepare_thread()
        with self.store.reserve_start(operation, deadline=self.deadline) as handle:
            real_replace = os.replace
            def crash(src, dst, *args, **kwargs):
                if Path(dst) == self.agent / 'inbox/inflight/event-1.json':
                    raise OSError('injected activation crash')
                return real_replace(src, dst, *args, **kwargs)
            with patch('os.replace', side_effect=crash), self.assertRaises(self.Error):
                handle.activate('thread-1', 'turn-1')
        reopened = self.Store(str(self.agent), state_root=str(self.private), clock=self.clock)
        binding = TaskBinding(INC, 'event-1', str(self.agent), 'thread-1', 'turn-1')
        with self.assertRaises(self.Error):
            with reopened.guard_locked(binding, operation, deadline=self.deadline):
                self.fail('partial activation restored callback authority')
        reopened.revoke(deadline=self.deadline)
        self.assertEqual(self.op()['status'], 'revoked')


if __name__ == '__main__':
    unittest.main()
