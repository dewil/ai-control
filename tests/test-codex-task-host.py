"""Independent public-contract tests: FR-CXHOST-01..05, INV-CXHOST-01..05."""
import dataclasses
import fcntl
import json
import math
import os
from pathlib import Path
import socket
import signal
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
            description='ai-control task ' + token, kill_mode='control-group',
            active_state='active', sub_state='running', main_pid=123,
            control_group='/user.slice/task', type='exec', exit_type='main', restart='no',
            remain_after_exit=False, send_sigkill=True)
        if self.launch_error:
            raise self.launch_error

    def inspect(self, unit, *, deadline):
        self.calls.append(('inspect', unit, deadline))
        if self.inspect_error:
            raise self.inspect_error
        return self.status

    def stop(self, unit, *, invocation_id, main_pid, token, deadline):
        self.calls.append(('stop', unit, invocation_id, main_pid, token, deadline))
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

    # FR-CXHOST-01 / INV-CXHOST-01: fail closed before effects.
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

    # FR-CXHOST-02 / INV-CXHOST-02: durable launch intent and single start.
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

    # FR-CXHOST-03 / INV-CXHOST-03: ownership and readiness recovery.
    def test_FR03_INV03_replacement_unavailability_absence_and_transitional_states(self):
        self.start()
        original = dict(self.manager.status)
        for changes in ({'invocation_id': 'b' * 32}, {'description': 'foreign'},
                        {'kill_mode': 'process'}, {'active_state': 'activating'},
                        {'sub_state': 'start'}, {'main_pid': 0}, {'main_pid': True},
                        {'invocation_id': 'A' * 32}, {'type': 'simple'}, {'exit_type': 'cgroup'},
                        {'restart': 'always'}, {'remain_after_exit': True}, {'send_sigkill': False}):
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

    # FR-CXHOST-04 / INV-CXHOST-04: quiescent scoped stop and durable receipt.
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

    # FR-CXHOST-01 / INV-CXHOST-01: storage identity is checked per operation.
    def test_FR01_hardlinked_journal_and_mutex_rejected_before_manager(self):
        self.start()
        for filename in ('journal.json', 'host.lock'):
            with self.subTest(filename=filename):
                alias = self.root / ('alias-' + filename)
                os.link(self.state / filename, alias)
                self.manager.calls.clear()
                with self.assertRaises(HostError):
                    self.make().inspect(deadline=200)
                self.assertEqual(self.manager.calls, [])
                alias.unlink()

    def test_FR01_state_ancestor_symlink_after_constructor_rejected(self):
        self.start()
        moved = self.root / 'moved-state'
        self.state.rename(moved)
        self.state.symlink_to(moved, target_is_directory=True)
        self.manager.calls.clear()
        with self.assertRaises(HostError):
            self.host.inspect(deadline=200)
        self.assertEqual(self.manager.calls, [])

    # FR-CXHOST-03 / INV-CXHOST-03: active ownership needs cgroup identity.
    def test_FR03_active_cgroup_missing_or_noncanonical_is_unknown(self):
        self.start()
        for group in ('', '/', 'relative', '/owned/../task', '/owned//task'):
            self.manager.status['control_group'] = group
            with self.subTest(group=group):
                snap = self.host.inspect(deadline=200)
                self.assertEqual(snap.phase, 'unknown')
                self.assertFalse(snap.socket_ready)
        self.assertEqual(self.count('stop'), 0)

    # FR-CXHOST-03 / INV-CXHOST-03: verified alias and durable identities.
    def alias_fixture(self):
        parent = self.root / 'native-private'
        parent.mkdir(mode=0o700)
        target = parent / 'native.sock'
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        sock.bind(str(target))
        link = self.state / 'server.sock'
        link.symlink_to(target)
        return link, target

    def alias_identity(self, link, target):
        ls, ts = link.lstat(), target.lstat()
        return dict(link=[ls.st_dev, ls.st_ino], target_path=str(target),
                    target=[ts.st_dev, ts.st_ino])

    def test_FR03_verified_alias_is_ready_and_revalidated_on_recovery(self):
        self.start()
        link, target = self.alias_fixture()
        calls = []
        def validate(path, group, *, deadline):
            calls.append((path, group, deadline))
            return self.alias_identity(link, target)
        self.manager.validate_socket_link = validate
        snap = self.host.inspect(deadline=200)
        self.assertEqual(snap.phase, 'running')
        self.assertTrue(snap.socket_ready)
        self.assertEqual(self.journal()['socket_identity'], self.alias_identity(link, target))
        self.assertTrue(self.make().inspect(deadline=200).socket_ready)
        self.assertEqual(calls, [(str(link), '/user.slice/task', 200)] * 2)
        self.host.stop(deadline=200, quiescent=True)
        self.assertEqual(len(calls), 3)

    def test_FR03_alias_durable_link_and_target_replacement_are_unknown(self):
        self.start()
        link, target = self.alias_fixture()
        identity = self.alias_identity(link, target)
        self.manager.validate_socket_link = lambda path, group, deadline: self.alias_identity(link, target)
        self.assertTrue(self.host.inspect(deadline=200).socket_ready)
        # Rename preserves old inode, ensuring newly created link cannot reuse it.
        link.rename(self.state / 'old-link')
        link.symlink_to(target)
        self.assertNotEqual(link.lstat().st_ino, identity['link'][1])
        self.assertEqual(self.make().inspect(deadline=200).phase, 'unknown')
        link.unlink()
        (self.state / 'old-link').rename(link)
        target.rename(target.with_name('old.sock'))
        other = socket.socket(socket.AF_UNIX)
        self.addCleanup(other.close)
        other.bind(str(target))
        self.assertEqual(self.make().inspect(deadline=200).phase, 'unknown')
        self.assertEqual(self.count('stop'), 0)
        self.assertEqual(self.count('start'), 1)

    def test_FR03_alias_probe_error_and_malformed_identity_are_unknown(self):
        self.start()
        link, target = self.alias_fixture()
        valid = self.alias_identity(link, target)
        results = ({}, dict(valid, link=[1, 2]), dict(valid, target=[True, 2]),
                   dict(valid, target_path='relative'), dict(valid, extra='SECRET-PAYLOAD'))
        for result in results:
            self.manager.validate_socket_link = lambda path, group, deadline, result=result: result
            with self.subTest(result=result):
                self.assertEqual(self.host.inspect(deadline=200).phase, 'unknown')
        def broken(path, group, *, deadline):
            raise RuntimeError('SECRET-PAYLOAD')
        self.manager.validate_socket_link = broken
        snap = self.host.inspect(deadline=200)
        self.assertEqual(snap.phase, 'unknown')
        self.assertFalse(snap.socket_ready)


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
        fields = dict(LoadState='loaded', Description='ai-control task ' + self.token,
                      InvocationID='a' * 32, ActiveState='active', SubState='running',
                      MainPID='123', ControlGroup='/task', KillMode='control-group',
                      Type='exec', ExitType='main', Restart='no', RemainAfterExit='no', SendSIGKILL='yes')
        fields.update(changes)
        return ''.join(k + '=' + v + '\n' for k, v in fields.items())

    # FR-CXHOST-05 / INV-CXHOST-05: systemd adapter scope and bounded calls.
    def test_FR05_INV05_scoped_commands_and_runner_deadline(self):
        self.output = 'codex-cli 0.160.0\n'
        self.assertEqual(self.manager.version('/bin/true', deadline=200), '0.160.0')
        with patch.dict(os.environ, {'HOME': '/tmp/$HOME', 'PATH': '/bin', 'CODEX_HOME': '/tmp/codex',
                                     'UNTRUSTED_VARIABLE': 'no'}, clear=True):
            self.manager.start(self.unit, ['/bin/true', 'app-server'], '/tmp/$HOME', self.token, deadline=200)
        argv = self.calls[-1][0]
        for value in ('--user', '--no-ask-password', '--quiet', '--unit=' + self.unit,
                      '--description=ai-control task ' + self.token, '--service-type=exec',
                      '--property=KillMode=control-group', '--property=Restart=no', '--property=UMask=0077',
                      '--property=TimeoutStopSec=5s', '--working-directory=/tmp/$HOME', '--expand-environment=no'):
            self.assertIn(value, argv)
        self.assertEqual(argv[0], 'systemd-run')
        self.assertEqual(argv[argv.index('--') + 1:], ['/bin/true', 'app-server'])
        self.assertFalse(any('UNTRUSTED_VARIABLE' in arg for arg in argv))
        self.assertFalse(any(arg in argv for arg in ('--collect', '--scope', '--shell')))
        # Updated spec replaces unit-name stop with anchored handle signalling.
        for prop in ('--property=ExitType=main', '--property=RemainAfterExit=no',
                     '--property=SendSIGKILL=yes'):
            self.assertIn(prop, argv)
        for _, kwargs in self.calls:
            self.assertTrue(kwargs['capture_output'])
            self.assertTrue(kwargs['text'])
            self.assertFalse(kwargs['check'])
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 100)
            self.assertFalse(kwargs.get('shell', False))

    def test_FR05_environment_values_never_enter_launch_argv(self):
        secret_url = 'http://fixture-user:fixture-password@example.invalid:8080'
        with patch.dict(os.environ, {'HOME': '/tmp/home', 'PATH': '/bin', 'CODEX_HOME': '/tmp/config',
                                     'HTTPS_PROXY': secret_url, 'UNRELATED_ENV': secret_url}, clear=True):
            self.manager.start(self.unit, ['/bin/true', 'app-server'], '/tmp', self.token, deadline=200)
        argv = self.calls[-1][0]
        for name in ('HOME', 'PATH', 'CODEX_HOME', 'HTTPS_PROXY'):
            self.assertIn('--setenv=' + name, argv)
        self.assertNotIn('--setenv=UNRELATED_ENV', argv)
        self.assertFalse(any(secret_url in arg or 'fixture-password' in arg for arg in argv))
        self.assertFalse(any(arg.startswith('--setenv=') and '=' in arg[len('--setenv='):] for arg in argv))

    def test_FR05_strict_version_and_redacted_errors(self):
        for output in ('codex-cli 0.160.1\n', 'banner\ncodex-cli 0.160.0\n', 'SECRET-PAYLOAD'):
            self.output = output
            with self.assertRaises(HostError) as ctx:
                self.manager.version('/bin/true', deadline=200)
            self.assertNotIn('SECRET-PAYLOAD', str(ctx.exception))
        self.returncode = 1
        with self.assertRaises(HostError) as ctx:
            self.manager.stop(self.unit, invocation_id='a' * 32, main_pid=123, token=self.token, deadline=200)
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
                       self.status() + 'malformed\n', self.status(RemainAfterExit='true'),
                       self.status(SendSIGKILL='1'), self.status().replace('Type=exec\n', '')):
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

    def test_FR05_synthetic_not_found_requires_exact_description_and_kill_mode(self):
        for rc in (0, 1):
            self.returncode = rc
            self.output = self.status(LoadState='not-found', Description=self.unit,
                InvocationID='', ActiveState='inactive', SubState='dead', MainPID='0',
                ControlGroup='', KillMode='control-group')
            self.assertIsNone(self.manager.inspect(self.unit, deadline=200))
        for changes in ({'Description': 'foreign'}, {'KillMode': 'process'}):
            fields = dict(LoadState='not-found', Description=self.unit,
                InvocationID='', ActiveState='inactive', SubState='dead', MainPID='0',
                ControlGroup='', KillMode='control-group')
            fields.update(changes)
            self.output = self.status(**fields)
            with self.subTest(changes=changes), self.assertRaises(HostError):
                self.manager.inspect(self.unit, deadline=200)

    def test_FR05_invalid_syntax_and_expired_deadline_no_runner(self):
        for unit in ('foreign.service', '../bad.service', self.unit + '\n'):
            with self.assertRaises(HostError):
                self.manager.stop(unit, invocation_id='a' * 32, main_pid=123, token=self.token, deadline=200)
        for deadline in (True, float('nan'), float('inf'), 100):
            with self.assertRaises(HostError):
                self.manager.stop(self.unit, invocation_id='a' * 32, main_pid=123, token=self.token, deadline=deadline)
        self.assertEqual(self.calls, [])


class AliasAdapterTests(unittest.TestCase):
    """FR-CXHOST-03 / FR-CXHOST-05 / INV-CXHOST-03 / INV-CXHOST-05."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.private = self.root / 'private'
        self.private.mkdir(mode=0o700)
        self.target = self.private / 'native.sock'
        self.sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.sock.close)
        self.sock.bind(str(self.target))
        self.link = self.root / 'server.sock'
        self.link.symlink_to(self.target)
        self.probes = []
        self.peer = dict(pid=123, uid=os.getuid(), cgroup='/owned/task')
        self.mutate = None
        def probe(path, *, deadline):
            self.probes.append((path, deadline))
            if self.mutate:
                self.mutate()
            return self.peer
        def runner(*args, **kwargs):
            self.fail('socket validation must not launch systemd or native commands')
        self.manager = SystemdTaskManager(runner=runner, clock=lambda: 100.0,
                                         peer_probe=probe)

    def validate(self, group='/owned/task', deadline=200):
        return self.manager.validate_socket_link(str(self.link), group, deadline=deadline)

    def test_FR05_alias_exact_identity_and_subtree_peer(self):
        for group in ('/owned/task', '/owned/task/child'):
            self.peer['cgroup'] = group
            result = self.validate()
            ls, ts = self.link.lstat(), self.target.lstat()
            self.assertEqual(result, dict(link=[ls.st_dev, ls.st_ino],
                target_path=str(self.target), target=[ts.st_dev, ts.st_ino]))
        self.assertEqual(self.probes, [(str(self.target), 200)] * 2)

    def test_FR05_alias_foreign_sibling_malformed_peer_redacted(self):
        valid = dict(self.peer)
        for changes in ({'uid': os.getuid() + 1}, {'pid': True}, {'pid': 0},
                        {'cgroup': '/owned/task-sibling'}, {'cgroup': '/other'},
                        {'cgroup': '/owned/task/../foreign'}, {'uid': True}):
            self.peer = dict(valid, **changes)
            with self.subTest(changes=changes), self.assertRaises(HostError) as ctx:
                self.validate()
            self.assertNotIn('SECRET-PAYLOAD', str(ctx.exception))
        for peer in (None, {}, {'pid': 'SECRET-PAYLOAD'}):
            self.peer = peer
            with self.subTest(peer=peer), self.assertRaises(HostError) as ctx:
                self.validate()
            self.assertNotIn('SECRET-PAYLOAD', str(ctx.exception))
        def fail():
            raise RuntimeError('SECRET-PAYLOAD')
        self.mutate = fail
        with self.assertRaises(HostError) as ctx:
            self.validate()
        self.assertNotIn('SECRET-PAYLOAD', str(ctx.exception))

    def test_FR05_alias_unsafe_paths_direct_socket_and_deadline(self):
        for deadline in (True, 100, float('nan'), float('inf')):
            with self.subTest(deadline=deadline), self.assertRaises(HostError):
                self.validate(deadline=deadline)
        for group in ('/', 'relative', '/owned/../task', '/owned//task'):
            with self.subTest(group=group), self.assertRaises(HostError):
                self.validate(group=group)
        self.assertEqual(self.probes, [])
        self.private.chmod(0o755)
        with self.assertRaises(HostError):
            self.validate()
        self.private.chmod(0o700)
        with self.assertRaises(HostError):
            self.manager.validate_socket_link(str(self.target), '/owned/task', deadline=200)
        self.link.unlink()
        self.link.symlink_to('private/native.sock')
        with self.assertRaises(HostError):
            self.validate()
        self.link.unlink()
        self.link.symlink_to(str(self.private) + '/../private/native.sock')
        with self.assertRaises(HostError):
            self.validate()
        self.assertEqual(self.probes, [])

    def test_FR05_alias_link_and_target_mutation_during_probe(self):
        def change_link():
            self.link.rename(self.root / 'old-link')
            self.link.symlink_to(self.target)
        self.mutate = change_link
        with self.assertRaises(HostError):
            self.validate()
        self.link.unlink()
        (self.root / 'old-link').rename(self.link)
        def change_target():
            self.target.rename(self.private / 'old.sock')
            other = socket.socket(socket.AF_UNIX)
            self.addCleanup(other.close)
            other.bind(str(self.target))
        self.mutate = change_target
        with self.assertRaises(HostError):
            self.validate()


class FencedStopTests(unittest.TestCase):
    """FR-CXHOST-04 / FR-CXHOST-05 / INV-CXHOST-04 / INV-CXHOST-05."""
    def setUp(self):
        self.unit = 'cctask-' + str(uuid.uuid4()) + '.service'
        self.token = str(uuid.uuid4())
        self.invocation = 'a' * 32
        self.commands = []
        self.open_calls = []
        self.now = 100.0
        self.state = dict(LoadState='loaded', Description='ai-control task ' + self.token,
            InvocationID=self.invocation, ActiveState='active', SubState='running', MainPID='123',
            ControlGroup='/owned/task', KillMode='control-group', Type='exec', ExitType='main',
            Restart='no', RemainAfterExit='no', SendSIGKILL='yes')
        self.on_open = None
        self.on_signal = None
        self.opener_error = None
        self.handle_error = None
        self.signals = []
        self.closed = 0
        self.has_exited = False
        self.has_drained = False
        self.exit_on_term = True
        self.drain_on_exit = True
        outer = self
        class Handle:
            pid = 123
            uid = os.getuid()
            cgroup = '/owned/task'
            def signal(self, sig):
                outer.signals.append(sig)
                if outer.on_signal:
                    outer.on_signal(sig)
                if sig == signal.SIGKILL or outer.exit_on_term:
                    outer.has_exited = True
                    outer.has_drained = outer.drain_on_exit
                    if outer.state is not None and outer.state['InvocationID'] == outer.invocation:
                        outer.state.update(ActiveState='inactive', SubState='dead', MainPID='0', ControlGroup='')
            def exited(self):
                if outer.handle_error:
                    raise outer.handle_error
                return outer.has_exited
            def drained(self):
                return outer.has_drained
            def close(self):
                outer.closed += 1
        self.handle = Handle()
        def clock():
            self.now += 0.2
            return self.now
        def opener(pid, group, *, deadline):
            self.open_calls.append((pid, group, deadline))
            if self.opener_error:
                raise self.opener_error
            if self.on_open:
                self.on_open()
            return self.handle
        def runner(argv, **kwargs):
            self.commands.append((argv, kwargs))
            self.assertEqual(argv[:4], ['systemctl', '--user', '--no-ask-password', 'show'])
            if self.state is None:
                fields = dict(LoadState='not-found', Description=self.unit, InvocationID='',
                    ActiveState='inactive', SubState='dead', MainPID='0', ControlGroup='',
                    KillMode='control-group', Type='simple', ExitType='main', Restart='no',
                    RemainAfterExit='no', SendSIGKILL='yes')
            else:
                fields = self.state
            return subprocess.CompletedProcess(argv, 0, ''.join(k+'='+v+'\n' for k,v in fields.items()), '')
        self.manager = SystemdTaskManager(runner=runner, clock=clock, process_opener=opener)

    def stop(self, **changes):
        args = dict(invocation_id=self.invocation, main_pid=123, token=self.token, deadline=110)
        args.update(changes)
        return self.manager.stop(self.unit, **args)

    def foreign(self):
        self.state.update(InvocationID='b' * 32, MainPID='456', Description='foreign')

    def test_FR05_fenced_stop_only_original_handle_and_cleanup(self):
        self.assertIsNone(self.stop())
        self.assertEqual(self.signals, [signal.SIGTERM])
        self.assertEqual(self.open_calls, [(123, '/owned/task', 110)])
        self.assertEqual(self.closed, 1)
        self.assertGreaterEqual(len(self.commands), 3)
        for argv, kwargs in self.commands:
            self.assertNotIn('stop', argv)
            self.assertNotIn('kill', argv)
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 10)

    def test_FR05_wrong_identity_or_cleanup_never_opens_or_signals(self):
        original = dict(self.state)
        for changes in ({'InvocationID': 'b' * 32}, {'MainPID': '456'}, {'Description': 'foreign'},
                        {'Type': 'simple'}, {'ExitType': 'cgroup'}, {'Restart': 'always'},
                        {'RemainAfterExit': 'yes'}, {'SendSIGKILL': 'no'}):
            self.now = 100
            self.state = dict(original, **changes)
            with self.subTest(changes=changes), self.assertRaises(HostError):
                self.stop()
            self.assertEqual(self.open_calls, [])
            self.assertEqual(self.signals, [])

    def test_FR05_replacement_at_opener_prevents_signal_and_closes_handle(self):
        self.on_open = self.foreign
        with self.assertRaises(HostError):
            self.stop()
        self.assertEqual(self.signals, [])
        self.assertEqual(self.closed, 1)

    def test_FR05_replacement_during_signal_cannot_stop_foreign_invocation(self):
        self.on_signal = lambda sig: self.foreign()
        with self.assertRaises(HostError):
            self.stop()
        self.assertEqual(self.signals, [signal.SIGTERM])
        self.assertEqual(self.closed, 1)
        self.assertTrue(all('stop' not in argv and 'kill' not in argv for argv, _ in self.commands))

    def test_FR05_wrong_handle_identity_is_closed_without_signal(self):
        for attr, value in (('pid', 456), ('uid', os.getuid() + 1), ('cgroup', '/owned/task-sibling')):
            original = getattr(self.handle, attr)
            setattr(self.handle, attr, value)
            self.closed = 0
            self.now = 100
            with self.subTest(attr=attr), self.assertRaises(HostError):
                self.stop()
            self.assertEqual(self.signals, [])
            self.assertEqual(self.closed, 1)
            setattr(self.handle, attr, original)

    def test_FR05_main_exit_without_cgroup_drain_times_out(self):
        self.drain_on_exit = False
        with self.assertRaises(HostError):
            self.stop()
        self.assertTrue(self.has_exited)
        self.assertFalse(self.has_drained)
        self.assertEqual(self.signals, [signal.SIGTERM])
        self.assertEqual(self.closed, 1)

    def test_FR05_missing_unit_requires_both_pinned_anchor_proofs(self):
        for exited, drained in ((False, True), (True, False), (False, False)):
            self.now = 100
            self.closed = 0
            self.signals.clear()
            self.state.update(ActiveState='active', SubState='running', MainPID='123', ControlGroup='/owned/task')
            self.exit_on_term = False
            def vanish(sig, exited=exited, drained=drained):
                self.state = None
                self.has_exited, self.has_drained = exited, drained
                if not exited:
                    raise ProcessLookupError()
            self.on_signal = vanish
            with self.subTest(exited=exited, drained=drained), self.assertRaises(HostError):
                self.stop()
            self.assertEqual(self.closed, 1)
            self.state = dict(LoadState='loaded', Description='ai-control task ' + self.token,
                InvocationID=self.invocation, ActiveState='active', SubState='running', MainPID='123',
                ControlGroup='/owned/task', KillMode='control-group', Type='exec', ExitType='main',
                Restart='no', RemainAfterExit='no', SendSIGKILL='yes')

    def test_FR05_shutdown_anchors_and_authoritative_missing_succeed(self):
        self.on_signal = lambda sig: setattr(self, 'state', None)
        self.assertIsNone(self.stop())
        self.assertTrue(self.has_exited and self.has_drained)
        self.assertEqual(self.closed, 1)

    def test_FR05_escalates_only_same_handle_before_deadline(self):
        self.exit_on_term = False
        self.assertIsNone(self.stop())
        self.assertEqual(self.signals, [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(len(self.open_calls), 1)
        self.assertEqual(self.closed, 1)
        self.assertLess(self.now, 110)

    def test_FR05_opener_and_handle_errors_are_redacted_and_closed(self):
        self.opener_error = OSError('SECRET-PAYLOAD')
        with self.assertRaises(HostError) as ctx:
            self.stop()
        self.assertNotIn('SECRET-PAYLOAD', str(ctx.exception))
        self.assertEqual(self.signals, [])
        self.opener_error = None
        self.handle_error = OSError('SECRET-PAYLOAD')
        with self.assertRaises(HostError) as ctx:
            self.stop()
        self.assertNotIn('SECRET-PAYLOAD', str(ctx.exception))
        self.assertEqual(self.closed, 1)

    def test_FR05_expired_or_invalid_stop_parameters_no_commands(self):
        for changes in ({'deadline': 100}, {'invocation_id': 'A' * 32}, {'main_pid': True},
                        {'main_pid': 0}, {'token': 'invalid'}):
            self.now = 100
            with self.subTest(changes=changes), self.assertRaises(HostError):
                self.stop(**changes)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.open_calls, [])



if __name__ == '__main__':
    unittest.main()
