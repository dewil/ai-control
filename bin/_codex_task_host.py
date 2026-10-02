"""Owned task App Server supervision; no turn admission or cleanup authority."""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import errno
import json
import math
import os
import re
import select
import signal
import stat
import socket
import struct
import subprocess
import tempfile
import time
from uuid import UUID, uuid4

from _codex_task_policy import host_argv


class HostError(Exception):
    """Payload-free supervisor diagnostic."""


def _require(value):
    if not value:
        raise HostError('Task host evidence is not confirmed')


def _uuid(value, version=None):
    try:
        return isinstance(value, str) and str(UUID(value)) == value and (version is None or UUID(value).version == version)
    except ValueError:
        return False


def _text(value):
    return isinstance(value, str) and bool(value) and '\x00' not in value and '\n' not in value and '\r' not in value


def _path(value):
    _require(_text(value) and os.path.isabs(value) and os.path.normpath(value) == value)


def _deadline(deadline, clock):
    _require(type(deadline) in (int, float) and math.isfinite(deadline))
    remaining = deadline - clock()
    _require(remaining > 0 and math.isfinite(remaining))
    return remaining


def _group(value):
    _path(value)
    _require(value != '/' and not value.startswith('//'))


def _metadata(info):
    # Access time can change during readlink/connect; identity and ownership cannot.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _inode(value):
    return isinstance(value, list) and len(value) == 2 and all(type(v) is int and v >= 0 for v in value)


def _socket_identity(value):
    if value is None or _inode(value):
        return
    _require(isinstance(value, dict) and set(value) == {'link', 'target_path', 'target'})
    _require(_inode(value['link']) and _inode(value['target']))
    _path(value['target_path'])


def _unit(unit):
    _require(isinstance(unit, str) and unit.startswith('cctask-') and unit.endswith('.service') and _uuid(unit[7:-8], 4))


def _status(status):
    _require(isinstance(status, dict))
    _require(isinstance(status.get('invocation_id'), str) and re.fullmatch('[0-9a-f]{32}', status['invocation_id']) is not None)
    _require(type(status.get('main_pid')) is int and status['main_pid'] >= 0)
    for key in ('description', 'kill_mode', 'active_state', 'sub_state', 'control_group'):
        _require(isinstance(status.get(key), str))
    return status


def _cleanup(status):
    _require(status.get('type') == 'exec' and status.get('exit_type') == 'main'
             and status.get('restart') == 'no' and status.get('remain_after_exit') is False
             and status.get('send_sigkill') is True)


@dataclass(frozen=True)
class _ProcessHandle:
    pid: int
    uid: int
    cgroup: str
    pidfd: int
    eventsfd: int
    deadline: float
    clock: object

    def signal(self, sig):
        _deadline(self.deadline, self.clock)
        signal.pidfd_send_signal(self.pidfd, sig)

    def exited(self):
        _deadline(self.deadline, self.clock)
        poll = select.poll()
        poll.register(self.pidfd, select.POLLIN)
        events = poll.poll(0)
        if not events:
            return False
        _require(len(events) == 1 and events[0][0] == self.pidfd and events[0][1] in (select.POLLIN, select.POLLIN | select.POLLHUP))
        return True

    def drained(self):
        _deadline(self.deadline, self.clock)
        try:
            os.lseek(self.eventsfd, 0, os.SEEK_SET)
            _deadline(self.deadline, self.clock)
            content = os.read(self.eventsfd, 65537).decode('ascii')
        except OSError as error:
            if error.errno == errno.ENODEV:
                return True  # Captured original cgroup was removed only after emptying.
            raise HostError('Original task cgroup evidence unavailable') from None
        _require(len(content) <= 65536)
        fields = {}
        for line in content.splitlines():
            pair = line.split()
            _require(len(pair) == 2 and pair[0] not in fields and pair[1] in ('0', '1'))
            fields[pair[0]] = pair[1]
        _require('populated' in fields)
        return fields['populated'] == '0'

    def close(self):
        try:
            os.close(self.pidfd)
        finally:
            os.close(self.eventsfd)


@dataclass(frozen=True)
class HostSnapshot:
    unit: str
    phase: str
    invocation_id: str | None
    main_pid: int | None
    socket: str
    socket_ready: bool


class SystemdTaskManager:
    """Bounded synchronous systemd user operations with no output disclosure."""
    _fields = ('LoadState', 'Description', 'InvocationID', 'ActiveState', 'SubState', 'MainPID', 'ControlGroup', 'KillMode', 'Type', 'ExitType', 'Restart', 'RemainAfterExit', 'SendSIGKILL')
    _env = ('HOME', 'PATH', 'CODEX_HOME', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
            'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')

    def __init__(self, *, runner=subprocess.run, clock=time.monotonic, peer_probe=None, process_opener=None):
        self.runner, self.clock = runner, clock
        self.peer_probe = peer_probe if peer_probe is not None else self._peer_probe
        self.process_opener = process_opener if process_opener is not None else self._open_process

    def _open_process(self, main_pid, control_group, *, deadline):
        pidfd = eventsfd = None
        try:
            _deadline(deadline, self.clock)
            pidfd = os.pidfd_open(main_pid)
            group_path = '/sys/fs/cgroup' + control_group
            _require(os.path.realpath(group_path) == group_path)
            _deadline(deadline, self.clock)
            eventsfd = os.open(group_path + '/cgroup.events', os.O_RDONLY | os.O_NOFOLLOW)
            _deadline(deadline, self.clock)
            info = os.stat('/proc/' + str(main_pid))
            _require(info.st_uid == os.getuid())
            _deadline(deadline, self.clock)
            with open('/proc/' + str(main_pid) + '/cgroup') as stream:
                content = stream.read(65537)
            _require(len(content) <= 65536)
            groups = [line[3:] for line in content.splitlines() if line.startswith('0::')]
            _require(groups == [control_group])
            handle = _ProcessHandle(main_pid, info.st_uid, control_group, pidfd, eventsfd, deadline, self.clock)
            _require(not handle.exited())
            return handle
        except Exception:
            if pidfd is not None:
                os.close(pidfd)
            if eventsfd is not None:
                os.close(eventsfd)
            raise HostError('Original task process anchors unavailable') from None

    def _peer_probe(self, socket_path, *, deadline):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(_deadline(deadline, self.clock))
                connection.connect(socket_path)
                pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
                _require(pid > 0 and uid == os.getuid())
                _deadline(deadline, self.clock)
                with open('/proc/' + str(pid) + '/cgroup') as stream:
                    content = stream.read(65537)
                _require(len(content) <= 65536)
                groups = [line[3:] for line in content.splitlines() if line.startswith('0::')]
                _require(len(groups) == 1)
                _group(groups[0])
                return dict(pid=pid, uid=uid, cgroup=groups[0])
        except Exception:
            raise HostError('Task host socket peer is not confirmed') from None

    def validate_socket_link(self, socket_path, control_group, *, deadline):
        try:
            _deadline(deadline, self.clock)
            _group(control_group)
            _path(socket_path)
            parent = os.path.dirname(socket_path)
            _require(os.path.realpath(parent) == parent)
            link = os.lstat(socket_path)
            _require(stat.S_ISLNK(link.st_mode) and link.st_uid == os.getuid())
            target_path = os.readlink(socket_path)
            _path(target_path)
            _require(os.path.realpath(target_path) == target_path)
            target = os.lstat(target_path)
            _require(stat.S_ISSOCK(target.st_mode) and target.st_uid == os.getuid())
            target_parent = os.lstat(os.path.dirname(target_path))
            _require(stat.S_ISDIR(target_parent.st_mode) and target_parent.st_uid == os.getuid() and target_parent.st_mode & 0o077 == 0)
            peer = self.peer_probe(target_path, deadline=deadline)
            _require(isinstance(peer, dict) and type(peer.get('pid')) is int and peer['pid'] > 0)
            _require(type(peer.get('uid')) is int and peer['uid'] == os.getuid())
            _group(peer.get('cgroup'))
            _require(peer['cgroup'] == control_group or peer['cgroup'].startswith(control_group + '/'))
            _deadline(deadline, self.clock)
            _require(_metadata(os.lstat(socket_path)) == _metadata(link) and os.readlink(socket_path) == target_path and _metadata(os.lstat(target_path)) == _metadata(target))
            _require(os.path.realpath(target_path) == target_path and _metadata(os.lstat(os.path.dirname(target_path))) == _metadata(target_parent))
            return dict(link=[link.st_dev, link.st_ino], target_path=target_path, target=[target.st_dev, target.st_ino])
        except Exception:
            raise HostError('Task host socket alias is not confirmed') from None

    def _run(self, argv, deadline):
        timeout = _deadline(deadline, self.clock)
        try:
            return self.runner(argv, capture_output=True, text=True, check=False,
                               stdin=subprocess.DEVNULL, timeout=timeout)
        except Exception:
            raise HostError('Task host manager call failed') from None

    def version(self, executable, *, deadline):
        _path(executable)
        result = self._run([executable, '--version'], deadline)
        _require(result.returncode == 0 and result.stdout in ('codex-cli 0.160.0', 'codex-cli 0.160.0\n'))
        return '0.160.0'

    def start(self, unit, argv, cwd, token, *, deadline):
        _unit(unit)
        _path(cwd)
        _require(_uuid(token, 4) and isinstance(argv, list) and bool(argv))
        _require(all(_text(arg) for arg in argv))
        _path(argv[0])
        command = ['systemd-run', '--user', '--no-ask-password', '--quiet', '--unit=' + unit,
                   '--description=claude-control task ' + token, '--service-type=exec',
                   '--property=KillMode=control-group', '--property=Restart=no', '--property=UMask=0077',
                   '--property=TimeoutStopSec=5s', '--property=ExitType=main',
                   '--property=RemainAfterExit=no', '--property=SendSIGKILL=yes', '--working-directory=' + cwd, '--expand-environment=no']
        for name in self._env:
            if name in os.environ:
                _require('\x00' not in os.environ[name])
                command.append('--setenv=' + name)
        result = self._run(command + ['--'] + argv, deadline)
        _require(result.returncode == 0)

    def stop(self, unit, *, invocation_id, main_pid, token, deadline):
        handle = None
        try:
            _unit(unit)
            _require(isinstance(invocation_id, str) and re.fullmatch('[0-9a-f]{32}', invocation_id) is not None)
            _require(type(main_pid) is int and main_pid > 0 and _uuid(token, 4))
            _deadline(deadline, self.clock)
            def owned(status):
                _status(status)
                _cleanup(status)
                _require(status['invocation_id'] == invocation_id and status['description'] == 'claude-control task ' + token
                         and status['kill_mode'] == 'control-group')
            status = self.inspect(unit, deadline=deadline)
            owned(status)
            _require(status['active_state'] == 'active' and status['sub_state'] == 'running' and status['main_pid'] == main_pid)
            group = status['control_group']
            _group(group)
            _deadline(deadline, self.clock)
            handle = self.process_opener(main_pid, group, deadline=deadline)
            _require(type(handle.pid) is int and handle.pid == main_pid and type(handle.uid) is int
                     and handle.uid == os.getuid() and handle.cgroup == group)
            second = self.inspect(unit, deadline=deadline)
            owned(second)
            _require(second['active_state'] == 'active' and second['sub_state'] == 'running'
                     and second['main_pid'] == main_pid and second['control_group'] == group)
            def exited():
                _deadline(deadline, self.clock)
                value = handle.exited()
                _require(type(value) is bool)
                return value
            def send(sig):
                _deadline(deadline, self.clock)
                try:
                    handle.signal(sig)
                except ProcessLookupError:
                    _require(exited())
            term_time = self.clock()
            send(signal.SIGTERM)
            killed = False
            while True:
                gone = exited()
                if not gone:
                    # No manager subprocess can delay the one-second escalation grace.
                    if not killed and self.clock() - term_time >= 1:
                        send(signal.SIGKILL)
                        killed = True
                else:
                    _deadline(deadline, self.clock)
                    drained = handle.drained()
                    _require(type(drained) is bool)
                    current = self.inspect(unit, deadline=deadline)
                    if current is not None:
                        owned(current)
                    if drained and (current is None or (current['active_state'] in ('inactive', 'failed')
                                                         and current['main_pid'] == 0 and current['control_group'] == '')):
                        return
                remaining = _deadline(deadline, self.clock)
                time.sleep(min(0.02, remaining))
        except Exception:
            raise HostError('Original task invocation stop not confirmed') from None
        finally:
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    raise HostError('Original task process anchors close failed') from None

    def inspect(self, unit, *, deadline):
        _unit(unit)
        result = self._run(['systemctl', '--user', '--no-ask-password', 'show', unit,
                            '--property=' + ','.join(self._fields)], deadline)
        _require(isinstance(result.stdout, str) and len(result.stdout) <= 65536)
        fields = {}
        for line in result.stdout.splitlines():
            _require('=' in line)
            key, value = line.split('=', 1)
            _require(key in self._fields and key not in fields)
            fields[key] = value
        _require(set(fields) == set(self._fields))
        _require(re.fullmatch('[0-9]+', fields['MainPID']) is not None)
        pid = int(fields['MainPID'])
        if fields['LoadState'] == 'not-found':
            _require(fields['Description'] in ('', unit) and fields['KillMode'] in ('', 'control-group') and fields['InvocationID'] == fields['ControlGroup'] == ''
                     and pid == 0 and fields['ActiveState'] == 'inactive' and fields['SubState'] == 'dead')
            return None
        _require(result.returncode == 0 and fields['LoadState'] == 'loaded')
        _require(fields['RemainAfterExit'] in ('yes', 'no') and fields['SendSIGKILL'] in ('yes', 'no'))
        return _status(dict(invocation_id=fields['InvocationID'], description=fields['Description'],
                            kill_mode=fields['KillMode'], active_state=fields['ActiveState'],
                            sub_state=fields['SubState'], main_pid=pid, control_group=fields['ControlGroup'],
                            type=fields['Type'], exit_type=fields['ExitType'], restart=fields['Restart'],
                            remain_after_exit=fields['RemainAfterExit'] == 'yes', send_sigkill=fields['SendSIGKILL'] == 'yes'))


class CodexTaskHost:
    def __init__(self, state_dir, task_incarnation, cwd, *, executable, manager=None, clock=time.monotonic):
        try:
            for path in (state_dir, cwd, executable):
                _path(path)
                _require(os.path.realpath(path) == path)
            _require(os.path.isdir(cwd) and os.path.isfile(executable) and os.access(executable, os.X_OK))
            _require(_uuid(task_incarnation))
            _require(os.path.commonpath((state_dir, cwd)) not in (state_dir, cwd))
            _require(os.path.isdir(os.path.dirname(state_dir)))
            if not os.path.lexists(state_dir):
                os.mkdir(state_dir, 0o700)
            self.state_dir, self.cwd, self.executable = state_dir, cwd, executable
            self.task_incarnation = task_incarnation
            self.clock = clock
            self.manager = manager if manager is not None else SystemdTaskManager(clock=clock)
            self.socket = os.path.join(state_dir, 'server.sock')
            self._check_directory()
        except (OSError, ValueError, TypeError):
            raise HostError('Invalid task host storage or identity') from None

    def _check_directory(self):
        _require(os.path.realpath(self.state_dir) == self.state_dir)
        info = os.lstat(self.state_dir)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0)

    def _open(self, name, flags):
        fd = os.open(os.path.join(self.state_dir, name), flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600)
            return fd
        except Exception:
            os.close(fd)
            raise

    @contextmanager
    def _locked(self, deadline):
        _deadline(deadline, self.clock)
        fd = None
        try:
            self._check_directory()
            # Also on reopen: a prior directory fsync may have failed after mkdir.
            for path in (os.path.dirname(self.state_dir), self.state_dir):
                directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            fd = self._open('host.lock', os.O_RDWR | os.O_CREAT)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        except (OSError, ValueError, TypeError):
            raise HostError('Task host storage unavailable') from None
        finally:
            if fd is not None:
                os.close(fd)

    def _read(self):
        try:
            fd = self._open('journal.json', os.O_RDONLY)
        except FileNotFoundError:
            return None
        try:
            with os.fdopen(fd) as stream:
                content = stream.read(65537)
            _require(len(content.encode('utf-8')) <= 65536)
            journal = json.loads(content, object_pairs_hook=self._pairs)
            keys = {'schema', 'task_incarnation', 'cwd', 'executable', 'unit', 'token', 'socket', 'phase', 'invocation_id', 'socket_identity'}
            _require(isinstance(journal, dict) and set(journal) == keys)
            _require(type(journal['schema']) is int and journal['schema'] == 1)
            for key, value in (('task_incarnation', self.task_incarnation), ('cwd', self.cwd), ('executable', self.executable), ('socket', self.socket)):
                _require(journal[key] == value)
            _unit(journal['unit'])
            _require(_uuid(journal['token'], 4))
            _require(journal['phase'] in ('prepared', 'running', 'stopping', 'stopped'))
            invocation = journal['invocation_id']
            _require((journal['phase'] == 'prepared' and invocation is None) or
                     (journal['phase'] != 'prepared' and isinstance(invocation, str) and re.fullmatch('[0-9a-f]{32}', invocation) is not None))
            identity = journal['socket_identity']
            _socket_identity(identity)
            _require(journal['phase'] != 'prepared' or identity is None)
            return journal
        except (UnicodeError, ValueError, TypeError, RecursionError):
            raise HostError('Invalid task host journal') from None

    @staticmethod
    def _pairs(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result

    def _write(self, journal):
        temporary = None
        try:
            self._check_directory()
            # Validate an existing destination without following links before replacement.
            try:
                fd = self._open('journal.json', os.O_RDONLY)
            except FileNotFoundError:
                pass
            else:
                os.close(fd)
            fd, temporary = tempfile.mkstemp(prefix='.journal-', dir=self.state_dir)
            with os.fdopen(fd, 'w') as stream:
                json.dump(journal, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, os.path.join(self.state_dir, 'journal.json'))
            temporary = None
            directory = os.open(self.state_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            raise HostError('Task host journal persistence failed') from None
        finally:
            if temporary is not None:
                os.unlink(temporary)

    def _snapshot(self, journal, phase='unknown', status=None, ready=False):
        return HostSnapshot(journal['unit'], phase, status['invocation_id'] if status else None,
                            status['main_pid'] if status else None, self.socket, ready)

    def _observe_socket(self, journal, status, deadline):
        identity = journal['socket_identity']
        try:
            info = os.lstat(self.socket)
        except FileNotFoundError:
            _require(identity is None)
            return False, None
        if stat.S_ISLNK(info.st_mode):
            _require(info.st_uid == os.getuid())
            observed = self.manager.validate_socket_link(self.socket, status['control_group'], deadline=deadline)
            _socket_identity(observed)
            _require(isinstance(observed, dict) and observed['link'] == [info.st_dev, info.st_ino])
            _require(_metadata(os.lstat(self.socket)) == _metadata(info))
        else:
            _require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid())
            observed = [info.st_dev, info.st_ino]
        _require(identity is None or identity == observed)
        return True, observed

    def _inspect(self, journal, deadline):
        try:
            _deadline(deadline, self.clock)
            status = self.manager.inspect(journal['unit'], deadline=deadline)
            if status is None:
                return self._snapshot(journal, 'stopped' if journal['phase'] == 'stopped' else 'unknown')
            _status(status)
            _cleanup(status)
            _require(status['description'] == 'claude-control task ' + journal['token'] and status['kill_mode'] == 'control-group')
            _require(journal['invocation_id'] is None or journal['invocation_id'] == status['invocation_id'])
            drained = status['active_state'] in ('inactive', 'failed') and status['main_pid'] == 0 and status['control_group'] == ''
            active = status['active_state'] == 'active' and status['sub_state'] == 'running' and status['main_pid'] > 0
            if active:
                _group(status['control_group'])
            if journal['phase'] in ('stopping', 'stopped'):
                if drained:
                    if journal['phase'] != 'stopped':
                        journal['phase'] = 'stopped'
                        persist = True
                    else:
                        persist = False
                    result = self._snapshot(journal, 'stopped', status)
                elif active and journal['phase'] == 'stopping':
                    _, observed = self._observe_socket(journal, status, deadline)
                    persist = journal['socket_identity'] != observed
                    journal['socket_identity'] = observed
                    result = self._snapshot(journal, 'stopping', status)
                else:
                    return self._snapshot(journal)
            elif active:
                ready, observed = self._observe_socket(journal, status, deadline)
                persist = journal['phase'] != 'running' or journal['invocation_id'] is None or journal['socket_identity'] != observed
                journal['socket_identity'] = observed
                journal.update(phase='running', invocation_id=status['invocation_id'])
                result = self._snapshot(journal, 'running', status, ready)
            else:
                return self._snapshot(journal)
        except Exception:
            return self._snapshot(journal)
        # Persistence errors must escape, never masquerade as manager uncertainty.
        if persist:
            self._write(journal)
        return result

    def start(self, *, deadline):
        with self._locked(deadline):
            journal = self._read()
            if journal is not None:
                return self._inspect(journal, deadline)
            try:
                _require(self.manager.version(self.executable, deadline=deadline) == '0.160.0')
                argv = host_argv(self.socket, executable=self.executable)
            except Exception:
                raise HostError('Task host launch prerequisites failed') from None
            journal = dict(schema=1, task_incarnation=self.task_incarnation, cwd=self.cwd,
                           executable=self.executable, unit='cctask-' + str(uuid4()) + '.service',
                           token=str(uuid4()), socket=self.socket, phase='prepared',
                           invocation_id=None, socket_identity=None)
            self._write(journal)
            try:
                _deadline(deadline, self.clock)
                self.manager.start(journal['unit'], argv, self.cwd, journal['token'], deadline=deadline)
            except Exception:
                return self._snapshot(journal)
            return self._inspect(journal, deadline)

    def inspect(self, *, deadline):
        with self._locked(deadline):
            journal = self._read()
            _require(journal is not None)
            return self._inspect(journal, deadline)

    def stop(self, *, deadline, quiescent=False):
        _require(quiescent is True)
        with self._locked(deadline):
            journal = self._read()
            _require(journal is not None)
            snapshot = self._inspect(journal, deadline)
            if snapshot.phase not in ('running', 'stopping'):
                return snapshot
            journal['phase'] = 'stopping'
            self._write(journal)
            try:
                _deadline(deadline, self.clock)
                self.manager.stop(journal['unit'], invocation_id=snapshot.invocation_id,
                                  main_pid=snapshot.main_pid, token=journal['token'], deadline=deadline)
            except Exception:
                return self._snapshot(journal)
            journal['phase'] = 'stopped'
            self._write(journal)
            return self._snapshot(journal, 'stopped')
