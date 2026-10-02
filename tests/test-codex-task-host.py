"""Independent public-contract tests: FR-CXHOST-01..05, INV-CXHOST-01..05."""
import dataclasses
import fcntl
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from _codex_task_host import CodexTaskHost, HostError, HostSnapshot, SystemdTaskManager


class Manager:
    def __init__(self):
        self.calls = []
        self.status = None
        self.launch_error = None
        self.stop_error = None
        self.inspect_error = None
        self.version_value = '0.160.0'
        self.on_start = None
        self.on_stop = None

    def version(self, executable, *, deadline):
        self.calls.append(('version', executable, deadline))
        return self.version_value

    def start(self, unit, argv, cwd, token, *, deadline):
        self.calls.append(('start', unit, argv, cwd, token, deadline))
        if self.on_start:
            self.on_start()
        self.status = dict(invocation_id='a' * 32,
            description='claude-control task ' + token, kill_mode='control-group',
            active_state='active', sub_state='running', main_pid=123,
            control_group='/user.slice/task')
        if self.launch_error:
            raise self.launch_error

    def inspect(self, unit, *, deadline):
        self.calls.append(('inspect', unit, deadline))
        if self.inspect_error:
            raise self.inspect_error
        return self.status

    def stop(self, unit, *, deadline):
        self.calls.append(('stop', unit, deadline))
        if self.on_stop:
            self.on_stop()
        if self.stop_error:
            raise self.stop_error
        self.status.update(active_state='inactive', sub_state='dead', main_pid=0, control_group='')


class HostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.cwd = self.root / 'task'
        self.cwd.mkdir()
        self.state = self.root / 'state'
        self.exe = self.root / 'codex'
        self.exe.write_text('#!/bin/sh\nexit 0\n')
        self.exe.chmod(0o700)
        self.task = str(uuid.uuid4())
        self.manager = Manager()
        self.host = self.make()
        self.deadline = 200.0

    def make(self, **changes):
        args = dict(state_dir=str(self.state), task_incarnation=self.task,
                    cwd=str(self.cwd), executable=str(self.exe), manager=self.manager,
                    clock=lambda: 100.0)
        args.update(changes)
        return CodexTaskHost(**args)

    def start(self):
        return self.host.start(deadline=self.deadline)

    def journal(self):
        return json.loads((self.state / 'journal.json').read_text())

    def count(self, name):
        return sum(call[0] == name for call in self.manager.calls)

    def test_FR01_INV01_constructor_rejects_paths_identity_and_permissions(self):
        for changes in ({'cwd': 'relative'}, {'cwd': str(self.cwd / '..' / 'task')},
                        {'state_dir': str(self.cwd / 'state')}, {'state_dir': str(self.root)},
                        {'task_incarnation': 'not-uuid'}, {'executable': 'codex'},
                        {'executable': str(self.cwd)}):
            with self.subTest(changes=changes), self.assertRaises(HostError):
                self.make(**changes)
        self.state.chmod(0o755)
        with self.assertRaises(HostError):
            self.make()
        self.assertEqual(self.manager.calls, [])

    def test_FR01_private_files_and_corrupt_journal(self):
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.start()
        for name in ('journal.json', 'host.lock'):
            self.assertEqual((self.state / name).stat().st_mode & 0o777, 0o600)
        for contents in ('', '{}', 'not json', 'x' * 65537):
            (self.state / 'journal.json').write_text(contents)
            self.manager.calls.clear()
            with self.subTest(contents=contents[:10]), self.assertRaises(HostError):
                self.make().start(deadline=self.deadline)
            self.assertEqual(self.manager.calls, [])

    def test_FR01_journal_identity_mismatch(self):
        self.start()
        self.manager.calls.clear()
        with self.assertRaises(HostError):
            self.make(task_incarnation=str(uuid.uuid4())).start(deadline=self.deadline)
        self.assertEqual(self.manager.calls, [])

    def test_FR01_deadlines_and_missing_journal(self):
        for method in ('start', 'inspect', 'stop'):
            for deadline in (True, False, float('nan'), float('inf'), -math.inf, 100, 99):
                with self.subTest(method=method, deadline=deadline), self.assertRaises(HostError):
                    getattr(self.host, method)(deadline=deadline)
        for method in ('inspect', 'stop'):
            with self.assertRaises(HostError):
                getattr(self.host, method)(deadline=200)
        self.assertEqual(self.manager.calls, [])

    def test_FR01_lock_contention_is_nonblocking(self):
        self.start()
        with (self.state / 'host.lock').open('r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.manager.calls.clear()
            with self.assertRaises(HostError):
                self.make().inspect(deadline=200)
            self.assertEqual(self.manager.calls, [])

    def test_FR02_INV02_prepared_before_launch_and_no_relaunch(self):
        self.manager.on_start = lambda: self.assertEqual(self.journal()['phase'], 'prepared')
        snap = self.start()
        self.assertIsInstance(snap, HostSnapshot)
        self.assertEqual(snap.phase, 'running')
        self.assertEqual(snap.invocation_id, 'a' * 32)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snap.phase = 'unknown'
        self.host.start(deadline=200)
        self.make().start(deadline=200)
        self.assertEqual(self.count('start'), 1)
        self.assertEqual(self.count('version'), 1)
        call = next(c for c in self.manager.calls if c[0] == 'start')
        self.assertEqual(call[2][0], str(self.exe))
        self.assertIn('app-server', call[2])
        self.assertFalse(any('model' in a or 'effort' in a for a in call[2]))
        self.assertEqual(call[3], str(self.cwd))
        self.assertTrue(call[1].startswith('cctask-') and call[1].endswith('.service'))
        self.assertEqual(uuid.UUID(call[1][7:-8]).version, 4)
        self.assertEqual(uuid.UUID(call[4]).version, 4)
        self.assertTrue(all(c[-1] == 200 for c in self.manager.calls))

    def test_FR02_version_allowlist_and_preexisting_socket(self):
        self.manager.version_value = '0.160.1'
        with self.assertRaises(HostError):
            self.start()
        self.assertEqual(self.count('start'), 0)
        self.manager.version_value = '0.160.0'
        (self.state / 'server.sock').write_text('keep')
        with self.assertRaises(HostError):
            self.start()
        self.assertEqual((self.state / 'server.sock').read_text(), 'keep')
        self.assertEqual(self.count('start'), 0)

    def test_FR02_launch_timeout_pending_recovery(self):
        self.manager.launch_error = TimeoutError('SECRET-PAYLOAD')
        self.assertEqual(self.start().phase, 'unknown')
        self.manager.launch_error = None
        self.assertEqual(self.make().start(deadline=200).phase, 'running')
        self.assertEqual(self.count('start'), 1)
        self.assertEqual(self.count('version'), 1)

    def test_FR03_INV03_replacement_unavailability_absence_and_transitional_states(self):
        self.start()
        original = dict(self.manager.status)
        for changes in ({'invocation_id': 'b' * 32}, {'description': 'foreign'},
                        {'kill_mode': 'process'}, {'active_state': 'activating'},
                        {'sub_state': 'start'}, {'main_pid': 0}, {'main_pid': True},
                        {'invocation_id': 'A' * 32}):
            self.manager.status = dict(original, **changes)
            snap = self.host.inspect(deadline=200)
            self.assertEqual(snap.phase, 'unknown')
            self.assertIsNone(snap.invocation_id)
            self.assertIsNone(snap.main_pid)
        self.manager.status = None
        self.assertEqual(self.host.inspect(deadline=200).phase, 'unknown')
        self.manager.inspect_error = RuntimeError('SECRET-PAYLOAD')
        self.assertEqual(self.host.inspect(deadline=200).phase, 'unknown')
        self.assertEqual(self.count('stop'), 0)
        self.assertEqual(self.count('start'), 1)

    def test_FR03_socket_readiness_and_inode_replacement(self):
        self.assertFalse(self.start().socket_ready)
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        path = self.state / 'server.sock'
        sock.bind(str(path))
        self.assertTrue(self.host.inspect(deadline=200).socket_ready)
        path.unlink()
        replacement = socket.socket(socket.AF_UNIX)
        self.addCleanup(replacement.close)
        replacement.bind(str(path))
        self.assertEqual(self.make().inspect(deadline=200).phase, 'unknown')

    def test_FR03_non_socket_and_symlink_are_unknown(self):
        self.start()
        path = self.state / 'server.sock'
        path.write_text('keep')
        self.assertEqual(self.host.inspect(deadline=200).phase, 'unknown')
        path.unlink()
        path.symlink_to(self.exe)
        self.assertEqual(self.host.inspect(deadline=200).phase, 'unknown')

    def test_FR04_INV04_quiescence_and_stop_receipt_idempotence(self):
        self.start()
        for value in (False, 1, 'yes', None):
            self.manager.calls.clear()
            with self.assertRaises(HostError):
                self.host.stop(deadline=200, quiescent=value)
            self.assertEqual(self.manager.calls, [])
        self.manager.on_stop = lambda: self.assertEqual(self.journal()['phase'], 'stopping')
        self.assertEqual(self.host.stop(deadline=200, quiescent=True).phase, 'stopped')
        self.assertEqual(self.journal()['phase'], 'stopped')
        self.assertEqual(self.make().stop(deadline=200, quiescent=True).phase, 'stopped')
        self.manager.status = None
        self.assertEqual(self.make().inspect(deadline=200).phase, 'stopped')
        self.assertEqual(self.count('stop'), 1)
        self.assertTrue(self.cwd.exists())
        self.assertTrue((self.state / 'journal.json').exists())

    def test_FR04_timeout_drained_recovery_and_missing_unknown(self):
        self.start()
        self.manager.stop_error = TimeoutError('SECRET-PAYLOAD')
        self.assertEqual(self.host.stop(deadline=200, quiescent=True).phase, 'unknown')
        self.assertEqual(self.journal()['phase'], 'stopping')
        status = dict(self.manager.status)
        self.manager.status = None
        self.assertEqual(self.make().inspect(deadline=200).phase, 'unknown')
        self.manager.status = dict(status, active_state='failed', sub_state='failed', main_pid=0, control_group='')
        self.assertEqual(self.make().inspect(deadline=200).phase, 'stopped')

    def test_FR04_new_active_invocation_after_stopped_is_unknown(self):
        self.start()
        self.host.stop(deadline=200, quiescent=True)
        self.manager.status.update(active_state='active', sub_state='running', main_pid=321,
                                   control_group='/new', invocation_id='b' * 32)
        self.assertEqual(self.make().inspect(deadline=200).phase, 'unknown')
        self.assertEqual(self.count('stop'), 1)

    def test_FR01_symlink_state_and_journal_are_refused(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(HostError):
            self.make(state_dir=str(alias))
        outside = self.root / 'outside.json'
        outside.write_text('{}')
        (self.state / 'journal.json').symlink_to(outside)
        with self.assertRaises(HostError):
            self.start()
        self.assertEqual(self.manager.calls, [])
        self.assertEqual(outside.read_text(), '{}')

    def test_FR02_pending_foreign_invocation_cannot_be_adopted_or_stopped(self):
        self.manager.launch_error = TimeoutError()
        self.start()
        self.manager.status['description'] = 'foreign'
        self.assertEqual(self.make().start(deadline=200).phase, 'unknown')
        try:
            snap = self.make().stop(deadline=200, quiescent=True)
            self.assertEqual(snap.phase, 'unknown')
        except HostError:
            pass
        self.assertEqual(self.count('start'), 1)
        self.assertEqual(self.count('stop'), 0)

    def test_FR04_stopping_same_active_invocation_can_retry_stop(self):
        self.start()
        self.manager.stop_error = TimeoutError()
        self.host.stop(deadline=200, quiescent=True)
        self.manager.stop_error = None
        self.assertEqual(self.make().stop(deadline=200, quiescent=True).phase, 'stopped')
        self.assertEqual(self.count('stop'), 2)
        self.assertEqual(self.count('start'), 1)

    def test_FR04_incomplete_drain_does_not_prove_stopped(self):
        self.start()
        self.manager.stop_error = TimeoutError()
        self.host.stop(deadline=200, quiescent=True)
        original = dict(self.manager.status)
        for changes in ({'main_pid': 0, 'control_group': '/still-populated'},
                        {'main_pid': 123, 'control_group': ''}):
            self.manager.status = dict(original, active_state='inactive', sub_state='dead', **changes)
            self.assertEqual(self.make().inspect(deadline=200).phase, 'unknown')
            self.assertEqual(self.journal()['phase'], 'stopping')


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.output = ''
        self.returncode = 0
        self.unit = 'cctask-' + str(uuid.uuid4()) + '.service'
        self.token = str(uuid.uuid4())
        self.manager = SystemdTaskManager(runner=self.run_fake, clock=lambda: 100.0)

    def run_fake(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, self.returncode, self.output, 'SECRET-PAYLOAD')

    def status(self, **changes):
        fields = dict(LoadState='loaded', Description='claude-control task ' + self.token,
                      InvocationID='a' * 32, ActiveState='active', SubState='running',
                      MainPID='123', ControlGroup='/task', KillMode='control-group')
        fields.update(changes)
        return ''.join(k + '=' + v + '\n' for k, v in fields.items())

    def test_FR05_INV05_scoped_commands_and_runner_deadline(self):
        self.output = 'codex-cli 0.160.0\n'
        self.assertEqual(self.manager.version('/bin/true', deadline=200), '0.160.0')
        with patch.dict(os.environ, {'HOME': '/tmp/$HOME', 'PATH': '/bin', 'CODEX_HOME': '/tmp/codex',
                                     'UNTRUSTED_VARIABLE': 'no'}, clear=True):
            self.manager.start(self.unit, ['/bin/true', 'app-server'], '/tmp/$HOME', self.token, deadline=200)
        argv = self.calls[-1][0]
        for value in ('--user', '--no-ask-password', '--quiet', '--unit=' + self.unit,
                      '--description=claude-control task ' + self.token, '--service-type=exec',
                      '--property=KillMode=control-group', '--property=Restart=no', '--property=UMask=0077',
                      '--property=TimeoutStopSec=5s', '--working-directory=/tmp/$HOME', '--expand-environment=no'):
            self.assertIn(value, argv)
        self.assertEqual(argv[0], 'systemd-run')
        self.assertEqual(argv[argv.index('--') + 1:], ['/bin/true', 'app-server'])
        self.assertFalse(any('UNTRUSTED_VARIABLE' in arg for arg in argv))
        self.assertFalse(any(arg in argv for arg in ('--collect', '--scope', '--shell')))
        self.manager.stop(self.unit, deadline=200)
        self.assertEqual(self.calls[-1][0], ['systemctl', '--user', '--no-ask-password', 'stop', self.unit])
        for _, kwargs in self.calls:
            self.assertTrue(kwargs['capture_output'])
            self.assertTrue(kwargs['text'])
            self.assertFalse(kwargs['check'])
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 100)
            self.assertFalse(kwargs.get('shell', False))

    def test_FR05_strict_version_and_redacted_errors(self):
        for output in ('codex-cli 0.160.1\n', 'banner\ncodex-cli 0.160.0\n', 'SECRET-PAYLOAD'):
            self.output = output
            with self.assertRaises(HostError) as ctx:
                self.manager.version('/bin/true', deadline=200)
            self.assertNotIn('SECRET-PAYLOAD', str(ctx.exception))
        self.returncode = 1
        with self.assertRaises(HostError) as ctx:
            self.manager.stop(self.unit, deadline=200)
        self.assertNotIn('SECRET-PAYLOAD', str(ctx.exception))

    def test_FR05_show_fields_and_strict_parsing(self):
        self.output = self.status()
        status = self.manager.inspect(self.unit, deadline=200)
        self.assertEqual(status['invocation_id'], 'a' * 32)
        self.assertEqual(status['main_pid'], 123)
        argv = self.calls[-1][0]
        self.assertEqual(argv[:4], ['systemctl', '--user', '--no-ask-password', 'show'])
        self.assertIn(self.unit, argv)
        for output in (self.status() + 'MainPID=123\n', self.status(MainPID='-1'),
                       self.status(InvocationID='A' * 32), 'LoadState=loaded\n',
                       self.status() + 'malformed\n'):
            self.output = output
            with self.subTest(output=output), self.assertRaises(HostError):
                self.manager.inspect(self.unit, deadline=200)

    def test_FR05_not_found_must_be_authoritative_and_drained(self):
        self.returncode = 1
        self.output = self.status(LoadState='not-found', Description='', InvocationID='',
                                  ActiveState='inactive', SubState='dead', MainPID='0',
                                  ControlGroup='', KillMode='')
        self.assertIsNone(self.manager.inspect(self.unit, deadline=200))
        self.output = self.status(LoadState='not-found')
        with self.assertRaises(HostError):
            self.manager.inspect(self.unit, deadline=200)

    def test_FR05_invalid_syntax_and_expired_deadline_no_runner(self):
        for unit in ('foreign.service', '../bad.service', self.unit + '\n'):
            with self.assertRaises(HostError):
                self.manager.stop(unit, deadline=200)
        for deadline in (True, float('nan'), float('inf'), 100):
            with self.assertRaises(HostError):
                self.manager.stop(self.unit, deadline=deadline)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
