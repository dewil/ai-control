#!/usr/bin/env python3
"""Independent public-contract tests for revoked-operation host abort."""
import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

_DEFAULT = object()

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from _codex_task_host import CodexTaskHost, HostError


class Manager:
    def __init__(self, case):
        self.case = case
        self.calls = []
        self.status = None
        self.stop_error = False
        self.inspect_error = False
        self.before_stop = None

    def check(self, name, deadline):
        self.calls.append((name, deadline))
        if self.case.require_guard:
            assert self.case.held, 'manager operation escaped guard'

    def version(self, executable, *, deadline):
        self.check('version', deadline)
        return '0.160.0'

    def start(self, unit, argv, cwd, token, *, deadline):
        self.check('start', deadline)
        self.status = dict(invocation_id='a' * 32,
            description='ai-control task ' + token, kill_mode='control-group',
            active_state='active', sub_state='running', main_pid=12345,
            control_group='/test/owned', type='exec', exit_type='main',
            restart='no', remain_after_exit=False, send_sigkill=True)

    def inspect(self, unit, *, deadline):
        self.check('inspect', deadline)
        if self.inspect_error:
            raise RuntimeError('PRIVATE-DETAIL')
        return None if self.status is None else dict(self.status)

    def stop(self, unit, *, invocation_id, main_pid, token, deadline):
        self.check('stop', deadline)
        assert self.case.journal()['phase'] == 'stopping', 'signal preceded intent'
        assert invocation_id == self.status['invocation_id']
        assert main_pid == self.status['main_pid']
        assert self.status['description'] == 'ai-control task ' + token
        if self.before_stop:
            self.before_stop()
        if self.stop_error:
            raise RuntimeError('PRIVATE-DETAIL')
        self.status.update(active_state='inactive', sub_state='dead', main_pid=0,
                           control_group='')


class AbortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cwd = self.base / 'work'
        self.cwd.mkdir(mode=0o700)
        self.state = self.base / 'state'
        self.now = 10.0
        self.deadline = 100.0
        self.held = False
        self.require_guard = False
        self.incarnation = str(uuid.uuid4())
        self.manager = Manager(self)
        self.host = self.make_host()
        self.host.start(deadline=self.deadline)
        self.manager.calls.clear()
        self.require_guard = True
        self.exits = 0

    def tearDown(self):
        self.tmp.cleanup()

    def make_host(self):
        return CodexTaskHost(str(self.state), self.incarnation, str(self.cwd),
            executable=os.path.realpath(sys.executable), manager=self.manager,
            clock=lambda: self.now)

    def journal(self):
        return json.loads((self.state / 'journal.json').read_text())

    @contextlib.contextmanager
    def guard(self, incarnation, *, deadline):
        self.assertEqual(incarnation, self.incarnation)
        self.assertEqual(deadline, self.deadline)
        # Lock must not already be held before entering TASK fence.
        self.assert_host_lock_free()
        self.held = True
        try:
            yield True
        finally:
            # Host lock must be released before exiting TASK fence.
            self.assert_host_lock_free()
            self.held = False
            self.exits += 1

    def assert_host_lock_free(self):
        fd = os.open(self.state / 'host.lock', os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def abort(self, guard=None, deadline=_DEFAULT):
        return self.host.abort(deadline=self.deadline if deadline is _DEFAULT else deadline,
                               guard=self.guard if guard is None else guard)

    def test_guard_held_through_stop_and_receipt_and_released_outside_lock(self):
        result = self.abort()
        self.assertEqual(result.phase, 'stopped')
        self.assertEqual(self.journal()['phase'], 'stopped')
        self.assertEqual(self.exits, 1)
        self.assertFalse(self.held)
        self.assertEqual([x[0] for x in self.manager.calls].count('stop'), 1)
        self.assertTrue(all(d == self.deadline for _, d in self.manager.calls))

    def test_stop_still_requires_quiescence(self):
        for value in (False, None, 1):
            with self.subTest(value=value), self.assertRaises(HostError):
                self.host.stop(deadline=self.deadline, quiescent=value)
        self.assertEqual(self.manager.calls, [])

    def test_invalid_deadlines_rejected_before_guard(self):
        def forbidden(*args, **kwargs):
            self.fail('invalid deadline entered guard')
        for value in (True, False, None, '100', math.nan, math.inf, -math.inf, 10.0, 9.0):
            with self.subTest(value=value), self.assertRaises(HostError):
                self.abort(guard=forbidden, deadline=value)
        self.assertEqual(self.manager.calls, [])
        self.assertEqual(self.journal()['phase'], 'running')

    def test_noncallable_guard_zero_effects(self):
        for value in (None, True, 1, 'guard', object()):
            with self.subTest(value=value), self.assertRaises(HostError):
                self.host.abort(deadline=self.deadline, guard=value)
        self.assertEqual(self.manager.calls, [])

    def test_nonliteral_true_guard_zero_effects(self):
        for value in (False, None, 1, 'yes'):
            @contextlib.contextmanager
            def fence(*args, **kwargs):
                yield value
            with self.subTest(value=value), self.assertRaises(HostError):
                self.abort(guard=fence)
        self.assertEqual(self.manager.calls, [])
        self.assertEqual(self.journal()['phase'], 'running')

    def test_guard_enter_exception_redacted(self):
        @contextlib.contextmanager
        def fence(*args, **kwargs):
            raise RuntimeError('PRIVATE-DETAIL')
            yield True
        with self.assertRaises(HostError) as caught:
            self.abort(guard=fence)
        self.assertNotIn('PRIVATE-DETAIL', str(caught.exception))
        self.assertEqual(self.manager.calls, [])

    def test_guard_exit_exception_no_success_even_after_drain(self):
        @contextlib.contextmanager
        def fence(*args, **kwargs):
            self.held = True
            try:
                yield True
            finally:
                self.held = False
                raise RuntimeError('PRIVATE-DETAIL')
        with self.assertRaises(HostError) as caught:
            self.abort(guard=fence)
        self.assertNotIn('PRIVATE-DETAIL', str(caught.exception))
        self.assertEqual(self.journal()['phase'], 'stopped')

    def test_guard_expiry_after_exit_does_not_return_success(self):
        @contextlib.contextmanager
        def fence(*args, **kwargs):
            with self.guard(*args, **kwargs):
                yield True
            self.now = self.deadline
        with self.assertRaises(HostError):
            self.abort(guard=fence)
        self.assertEqual(self.journal()['phase'], 'stopped')

    def test_guard_expiry_during_enter_zero_manager_effects(self):
        @contextlib.contextmanager
        def fence(*args, **kwargs):
            self.now = self.deadline
            yield True
        with self.assertRaises(HostError):
            self.abort(guard=fence)
        self.assertEqual(self.manager.calls, [])

    def test_suppressed_body_failure_cannot_be_success(self):
        (self.state / 'journal.json').write_text('{bad')
        @contextlib.contextmanager
        def fence(*args, **kwargs):
            try:
                yield True
            except Exception:
                pass
        with self.assertRaises(HostError):
            self.abort(guard=fence)
        self.assertEqual(self.manager.calls, [])

    def test_corrupt_journal_refusal_static(self):
        (self.state / 'journal.json').write_text('PRIVATE-DETAIL')
        with self.assertRaises(HostError) as caught:
            self.abort()
        self.assertNotIn('PRIVATE-DETAIL', str(caught.exception))
        self.assertEqual(self.manager.calls, [])

    def test_missing_journal_refuses_no_manager(self):
        (self.state / 'journal.json').unlink()
        with self.assertRaises(HostError):
            self.abort()
        self.assertEqual(self.manager.calls, [])

    def test_foreign_identity_never_signalled(self):
        for field, value in (('invocation_id', 'b' * 32),
                             ('description', 'foreign'),
                             ('kill_mode', 'process'),
                             ('control_group', '/')):
            original = self.manager.status[field]
            self.manager.status[field] = value
            self.manager.calls.clear()
            with self.subTest(field=field):
                self.assertEqual(self.abort().phase, 'unknown')
                self.assertNotIn('stop', [n for n, _ in self.manager.calls])
            self.manager.status[field] = original

    def test_manager_uncertainty_keeps_stopping_and_redacts(self):
        self.manager.stop_error = True
        result = self.abort()
        self.assertEqual(result.phase, 'unknown')
        self.assertEqual(self.journal()['phase'], 'stopping')
        self.assertNotIn('PRIVATE-DETAIL', repr(result))
        self.manager.status = None
        self.assertEqual(self.abort().phase, 'unknown')
        self.assertEqual([n for n, _ in self.manager.calls].count('stop'), 1)

    def test_inspect_uncertainty_never_stops(self):
        self.manager.inspect_error = True
        self.assertEqual(self.abort().phase, 'unknown')
        self.assertNotIn('stop', [n for n, _ in self.manager.calls])
        self.assertEqual(self.journal()['phase'], 'running')

    def test_stopped_replay_no_stop_or_launch(self):
        self.assertEqual(self.abort().phase, 'stopped')
        self.manager.calls.clear()
        self.host = self.make_host()
        self.assertEqual(self.abort().phase, 'stopped')
        self.manager.status = None
        self.assertEqual(self.abort().phase, 'stopped')
        self.assertTrue(all(n == 'inspect' for n, _ in self.manager.calls))

    def test_stopping_resume_same_owner_only_and_no_launch(self):
        self.manager.stop_error = True
        self.assertEqual(self.abort().phase, 'unknown')
        self.manager.stop_error = False
        self.manager.calls.clear()
        self.host = self.make_host()
        self.assertEqual(self.abort().phase, 'stopped')
        self.assertEqual([n for n, _ in self.manager.calls].count('stop'), 1)
        self.assertNotIn('start', [n for n, _ in self.manager.calls])

    def test_stopping_drained_recovery_without_second_stop(self):
        self.manager.stop_error = True
        self.abort()
        self.manager.status.update(active_state='inactive', sub_state='dead',
                                   main_pid=0, control_group='')
        self.manager.calls.clear()
        self.assertEqual(self.abort().phase, 'stopped')
        self.assertNotIn('stop', [n for n, _ in self.manager.calls])

    def test_stopping_intent_persistence_failure_never_signals(self):
        with patch('os.replace', side_effect=OSError('PRIVATE-DETAIL')):
            with self.assertRaises(HostError) as caught:
                self.abort()
        self.assertNotIn('PRIVATE-DETAIL', str(caught.exception))
        self.assertNotIn('stop', [n for n, _ in self.manager.calls])
        self.assertEqual(self.journal()['phase'], 'running')

    def test_contended_host_lock_inside_guard_zero_manager_effects(self):
        @contextlib.contextmanager
        def fence(*args, **kwargs):
            self.held = True
            fd = os.open(self.state / 'host.lock', os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield True
            finally:
                os.close(fd)
                self.held = False
        with self.assertRaises(HostError):
            self.abort(guard=fence)
        self.assertEqual(self.manager.calls, [])

    def test_persistence_failure_before_signal_cannot_be_suppressed(self):
        # Directory obstruction is actual filesystem failure, not internal patching.
        journal = self.state / 'journal.json'
        journal.unlink()
        journal.mkdir(mode=0o700)
        with self.assertRaises(HostError):
            self.abort()
        self.assertEqual(self.manager.calls, [])


if __name__ == '__main__':
    unittest.main()
