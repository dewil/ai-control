"""Independent INV-WLIM-25 contract; runtime bodies deliberately unread.

All cache files and transport output are synthetic. Never invokes SSH, reads
provider state/config/auth, installs units, or changes source export files.
"""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import configparser
import io
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cached_limits_backend_blind_support as s
import limits_dashboard_blind_support as native
import live_sse_blind_support as live
from test_control_web_session_chat_contract import feature

ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/var/lib/alp-limits-export/limits-v1.json'
FAILURE = {'status': 'unavailable', 'reason': 'sync_failed'}


def encoded(value):
    return json.dumps(value, allow_nan=False, separators=(',', ':')).encode()


class AlpLimitsSyncRED(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_broker')
        self.temp = tempfile.TemporaryDirectory(prefix='alp-sync-blind-', dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.base.chmod(0o700)
        self.destination = self.base / 'limits' / 'alp.json'
        self.calls = []

    def seam(self):
        sync = getattr(self.module, 'sync_alp_limits', None)
        self.assertTrue(callable(sync), 'INV-WLIM-25: public sync_alp_limits seam missing')
        return sync

    def prior(self):
        self.destination.parent.mkdir(mode=0o700, exist_ok=True)
        self.destination.write_bytes(b'previous private synthetic snapshot\n')
        self.destination.chmod(0o600)
        return self.destination.read_bytes()

    def sync(self, payload=None, runner=None, destination=None):
        sync = self.seam()
        def transport(argv, *, timeout=8, max_bytes=131072):
            self.calls.append((list(argv), timeout, max_bytes))
            return encoded(s.alp()) if payload is None else payload
        with patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')):
            return sync(str(destination or self.destination), runner=runner or transport, clock=lambda: s.NOW)

    def remote(self, command, payload, *, mode=0o600):
        """Execute captured stdlib program with its sole input redirected locally.

        Never executes the shell command itself. Extracts its fixed Python
        program, then the launcher rejects opens except the synthetic export
        and records flags. Supports -c and a literal stdin heredoc.
        """
        source = self.base / 'synthetic-remote.json'
        source.write_bytes(payload)
        source.chmod(mode)
        events = self.base / 'remote-open-events.json'
        launchers = self.base / 'remote-bin'
        launchers.mkdir(exist_ok=True, mode=0o700)
        launcher = '''import atexit, builtins, io, json, os, stat, sys, datetime, uuid, math
original_os_open, original_open, original_io_open = os.open, builtins.open, io.open
events=[]
def checked_path(path):
    if os.fspath(path) != os.environ['EXPECTED_EXPORT']:
        raise PermissionError('unexpected source path')
    return os.environ['SYNTHETIC_EXPORT']
def safe_os_open(path, flags, *args, **kwargs):
    events.append(flags)
    return original_os_open(checked_path(path), flags, *args, **kwargs)
def safe_open(path, *args, **kwargs):
    return original_open(checked_path(path), *args, **kwargs)
def safe_io_open(path, *args, **kwargs):
    return original_io_open(checked_path(path), *args, **kwargs)
def save_events():
    with original_open(os.environ['OPEN_EVENTS'], 'w') as stream:
        json.dump(events, stream)
atexit.register(save_events)
os.open, builtins.open, io.open = safe_os_open, safe_open, safe_io_open
if '-c' in sys.argv:
    program=sys.argv[sys.argv.index('-c')+1]
elif len(sys.argv)==1 or '-' in sys.argv:
    program=sys.stdin.read()
else:
    raise SystemExit('unexpected Python invocation')
exec(compile(program, '<synthetic-remote-program>', 'exec'), {'__name__':'__main__'})
'''
        for name in ('python3', 'python'):
            path = launchers / name
            path.write_text('#!' + sys.executable + '\n' + launcher)
            path.chmod(0o700)
        heredoc = re.fullmatch(r"(?:exec\s+)?(?:/[^\s]+/)?python3(?:\.\d+)?\s+-\s+<<\s*['\"]?(\w+)['\"]?\s*\n(.*)\n\1\s*", command, re.S)
        if heredoc:
            arguments, stdin = ['-'], heredoc.group(2).encode()
        else:
            words = shlex.split(command)
            if words and words[0] == 'exec': words = words[1:]
            self.assertTrue(words and (Path(words[0]).name.startswith('python3') or Path(words[0]).name=='python'))
            self.assertIn('-c', words, 'fixed remote command must contain a literal stdlib Python program')
            self.assertEqual(words.index('-c'), len(words)-2, 'no trailing shell/payload commands')
            arguments, stdin = words[1:], None
        result = subprocess.run([sys.executable, str(launchers/'python3'), *arguments],
                                input=stdin, capture_output=True, timeout=4,
                                env={'PATH': str(launchers), 'EXPECTED_EXPORT': REMOTE,
                                     'SYNTHETIC_EXPORT': str(source), 'OPEN_EVENTS': str(events)})
        return result, json.loads(events.read_text()) if events.exists() else []

    def test_fixed_transport_and_remote_whitelist_rejects_private_payload_before_stdout(self):
        # INV-WLIM-25: inspect the actual emitted command, never runtime bodies.
        self.assertEqual(self.sync(), {'status': 'updated', 'accounts': 1})
        argv, timeout, bound = self.calls[0]
        self.assertEqual((timeout, bound), (8, 131072))
        self.assertEqual(Path(argv[0]).name, 'ssh')
        self.assertIn('-T', argv)
        for option in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'ForwardAgent=no',
                       'ClearAllForwardings=yes', 'RequestTTY=no'):
            self.assertTrue(option in argv or '-o'+option in argv, option)
        alias = argv.index('alp-ai-dev-1-dwl')
        self.assertEqual(argv.count('alp-ai-dev-1-dwl'), 1)
        self.assertFalse(any(option in ' '.join(argv) for option in (
            'StrictHostKeyChecking=no', 'ForwardAgent=yes', 'ProxyCommand=', 'LocalCommand=')))
        command = ' '.join(argv[alias+1:])
        self.assertIn(REMOTE, command)
        self.assertNotIn(s.PRIVATE, command)
        good, opens = self.remote(command, encoded(s.alp()))
        self.assertEqual(good.returncode, 0, 'fixed remote program must accept the safe synthetic DTO')
        self.assertEqual(json.loads(good.stdout), s.alp())
        self.assertTrue(opens, 'fixed export must be opened through nofollow/nonblocking descriptor')
        self.assertTrue(all(flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK for flags in opens))
        bad_account = s.alp_account(private=s.PRIVATE)
        bad_window = s.alp_account()
        bad_window['windows'][0]['command'] = 'touch ' + s.PRIVATE
        invalid = [encoded(value) for value in (
            {**s.alp(), 'credentials': s.PRIVATE}, s.alp(bad_account),
            s.alp(bad_window), s.alp(s.alp_account(ref='user@example.invalid')),
            s.alp(s.alp_account(provider='shell')),
            s.alp(s.alp_account(status='success')))]
        invalid += [encoded(s.alp())[:-1]+b',"schema_version":1}',
                    encoded(s.alp()).replace(b'"used_percent":25', b'"used_percent":NaN'),
                    b' '*131073]
        for index, payload in enumerate(invalid):
            with self.subTest(remote_case=index):
                result, _ = self.remote(command, payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'', 'rejected private DTO must produce no stdout')
                self.assertNotIn(s.PRIVATE.encode(), result.stderr)
        result, _ = self.remote(command, encoded(s.alp()), mode=0o666)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')

    def test_success_atomic_private_cache_preserves_source_times_and_stale_age(self):
        # INV-WLIM-25: fetch time must never replace collection/export times.
        value = s.alp(s.alp_account(observed_at=s.stamp(s.NOW-3600)))
        value['exported_at'] = s.stamp(s.NOW-3000)
        events = []
        original_fsync, original_replace = os.fsync, os.replace
        def synced(fd):
            events.append(('fsync', stat.S_ISDIR(os.fstat(fd).st_mode)))
            return original_fsync(fd)
        def replaced(source, destination, *args, **kwargs):
            self.assertEqual(stat.S_IMODE(os.stat(source, dir_fd=kwargs.get('src_dir_fd')).st_mode), 0o600)
            events.append(('replace', None))
            return original_replace(source, destination, *args, **kwargs)
        with patch.object(os, 'fsync', side_effect=synced) as fsync, \
             patch.object(os, 'replace', side_effect=replaced) as replace:
            self.assertEqual(self.sync(encoded(value)), {'status': 'updated', 'accounts': 1})
        self.assertEqual(json.loads(self.destination.read_bytes()), value)
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.destination.parent.stat().st_mode), 0o700)
        self.assertGreaterEqual(fsync.call_count, 2, 'file and directory must both be fsynced')
        self.assertEqual(replace.call_count, 1)
        replacement = events.index(('replace', None))
        self.assertIn(('fsync', False), events[:replacement])
        self.assertIn(('fsync', True), events[replacement+1:])
        reader = self.module.CachedLimitsReader(str(self.base/'missing-bot'), str(self.destination))
        source = next(row for row in reader.snapshot(s.NOW) if row['provider']=='codex')
        self.assertEqual((source['observed_at'], source['age_seconds'], source['status']),
                         (s.NOW-3600, 3600, 'stale'))
        before_inode = self.destination.stat().st_ino
        newer = s.alp()
        self.assertEqual(self.sync(encoded(newer)), {'status': 'updated', 'accounts': 1})
        self.assertNotEqual(self.destination.stat().st_ino, before_inode)
        self.assertEqual(set(self.destination.parent.iterdir()), {self.destination})

    def test_invalid_protocol_timestamps_numbers_extra_fields_duplicate_and_oversize_preserve_bytes(self):
        # INV-WLIM-25: exact producer protocol is stricter than window projection.
        self.seam()
        old = self.prior()
        edits = [lambda v:v.update(schema_version=True), lambda v:v.update(node_id='llm'),
                 lambda v:v.update(exported_at=s.stamp(s.NOW+1)),
                 lambda v:v.update(exported_at='2027-01-15T08:00:00'),
                 lambda v:v.update(exported_at='2027-01-15T09:00:00+01:00'),
                 lambda v:v['accounts'][0].update(observed_at=s.stamp(s.NOW+1)),
                 lambda v:v.update(exported_at=s.stamp(s.NOW-31)),
                 lambda v:v['accounts'][0].update(observed_at_semantics='capture_end'),
                 lambda v:v['accounts'][0].update(status='success'),
                 lambda v:v['accounts'][0]['windows'][0].update(slot='private-label'),
                 lambda v:v['accounts'][0]['windows'][0].update(used_percent=True),
                 lambda v:v['accounts'][0].update(private=s.PRIVATE),
                 lambda v:v.update(credentials=s.PRIVATE),
                 lambda v:v['accounts'].append(deepcopy(v['accounts'][0])),
                 lambda v:v.update(freshness={'max_age_seconds':True,'future_skew_seconds':0})]
        payloads = [b'  malformed  ', b'{}', b'[]', b'\xff',
                    encoded(s.alp())[:-1]+b',"schema_version":1}',
                    encoded(s.alp()).replace(b'"used_percent":25', b'"used_percent":NaN'),
                    encoded(s.alp()).replace(b'"used_percent":25', b'"used_percent":1e999'),
                    b' '*131073]
        for edit in edits:
            value = s.alp(); edit(value); payloads.append(encoded(value))
        for index, payload in enumerate(payloads):
            with self.subTest(case=index):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    self.assertEqual(self.sync(payload), FAILURE)
                self.assertNotIn(s.PRIVATE, out.getvalue()+err.getvalue())
                self.assertEqual(self.destination.read_bytes(), old)
                self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o600)

    def test_runner_nonzero_timeout_and_private_exception_are_sanitized_without_retry(self):
        # INV-WLIM-25
        self.seam(); old = self.prior()
        failures = [subprocess.CalledProcessError(7, ['ssh'], output=s.PRIVATE.encode(), stderr=s.PRIVATE.encode()),
                    subprocess.TimeoutExpired(['ssh'], 8, output=s.PRIVATE.encode(), stderr=s.PRIVATE.encode()),
                    OSError(s.PRIVATE)]
        for error in failures:
            with self.subTest(error=type(error).__name__):
                out, err = io.StringIO(), io.StringIO()
                with patch('builtins.print', wraps=print) as printed, redirect_stdout(out), redirect_stderr(err):
                    runner = unittest.mock.Mock(side_effect=error)
                    self.assertEqual(self.sync(runner=runner), FAILURE)
                self.assertEqual(runner.call_count, 1)
                self.assertNotIn(s.PRIVATE, out.getvalue()+err.getvalue()+repr(printed.call_args_list))
                self.assertEqual(self.destination.read_bytes(), old)
        # Exercise the default bounded-Popen adapter too, without an SSH child.
        for error in failures:
            with self.subTest(default_transport=type(error).__name__), \
                 patch.object(subprocess, 'Popen', side_effect=error) as popen, \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(self.seam()(str(self.destination), clock=lambda:s.NOW), FAILURE)
                self.assertEqual(popen.call_count, 1)
            self.assertEqual(self.destination.read_bytes(), old)
        # Real bounded child I/O, with SSH replaced by a synthetic Python child.
        # This catches a transport that ignores a child's nonzero status/size.
        original_popen = subprocess.Popen
        programs = ["import sys;sys.stderr.write("+repr(s.PRIVATE)+");sys.exit(7)",
                    "import sys;sys.stdout.buffer.write(b'x'*131073)"]
        for program in programs:
            def fake_ssh(argv, *args, **kwargs):
                self.assertEqual(Path(argv[0]).name, 'ssh')
                self.assertFalse(kwargs.get('shell', False))
                return original_popen([sys.executable, '-c', program], *args, **kwargs)
            out, err = io.StringIO(), io.StringIO()
            with self.subTest(child=program), patch.object(subprocess, 'Popen', side_effect=fake_ssh) as popen, \
                 redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(self.seam()(str(self.destination), clock=lambda:s.NOW), FAILURE)
                self.assertEqual(popen.call_count, 1)
            self.assertNotIn(s.PRIVATE, out.getvalue()+err.getvalue())
            self.assertEqual(self.destination.read_bytes(), old)

    def test_unsafe_local_leaf_parent_alias_and_foreign_ownership_refused(self):
        # INV-WLIM-25: filesystem policy tested on real files, not mocked opens.
        self.seam(); old = self.prior()
        target = self.base/'outside.json'; target.write_bytes(old); target.chmod(0o600)
        self.destination.unlink(); self.destination.symlink_to(target)
        self.assertEqual(self.sync(), FAILURE); self.assertEqual(target.read_bytes(), old)
        self.destination.unlink(); os.mkfifo(self.destination, 0o600)
        self.assertEqual(self.sync(), FAILURE); self.assertTrue(stat.S_ISFIFO(self.destination.lstat().st_mode))
        self.destination.unlink(); self.prior()
        alias = self.base/'hardlink.json'; os.link(self.destination, alias)
        self.assertEqual(self.sync(), FAILURE); self.assertEqual(alias.read_bytes(), old); alias.unlink()
        for mode in (0o644, 0o660, 0o666):
            with self.subTest(mode=mode):
                self.destination.chmod(mode)
                self.assertEqual(self.sync(), FAILURE)
                self.assertEqual(self.destination.read_bytes(), old)
                self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), mode)
        self.destination.chmod(0o600)
        self.destination.parent.chmod(0o755)
        self.assertEqual(self.sync(), FAILURE); self.assertEqual(self.destination.read_bytes(), old)
        self.destination.parent.chmod(0o700)
        linked_parent = self.base/'linked-limits'; linked_parent.symlink_to(self.destination.parent, target_is_directory=True)
        self.assertEqual(self.sync(destination=linked_parent/'alp.json'), FAILURE)
        self.assertEqual(self.destination.read_bytes(), old)
        # Simulate another effective owner without privileged chown or fixture skips.
        with patch.object(os, 'geteuid', return_value=os.geteuid()+1):
            self.assertEqual(self.sync(), FAILURE)
        self.assertEqual(self.destination.read_bytes(), old)

    def test_fsync_or_replace_failure_keeps_previous_bytes_and_cleans_temporary_files(self):
        # INV-WLIM-25: a new valid DTO cannot truncate the old file on failure.
        self.seam(); old = self.prior()
        for operation in ('fsync', 'replace'):
            with self.subTest(operation=operation), patch.object(os, operation, side_effect=OSError(s.PRIVATE)):
                self.assertEqual(self.sync(), FAILURE)
            self.assertEqual(self.destination.read_bytes(), old)
            self.assertEqual(set(self.destination.parent.iterdir()), {self.destination})

    def test_owner_cli_fixed_default_sanitized_status_exit_and_rejects_host_path_flags(self):
        # INV-WLIM-25: real parser/dispatch with only the public sync seam stubbed.
        cli = ROOT/'bin'/'ai-control-web'
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', [str(cli), 'sync-limits-alp', '--help']), \
             redirect_stdout(output), redirect_stderr(errors):
            try: runpy.run_path(str(cli), run_name='__main__')
            except SystemExit as exc: code = exc.code
            else: code = 0
        self.assertEqual(code, 0, 'INV-WLIM-25: sync-limits-alp CLI subcommand missing')
        for flag in ('--host', '--source', '--path', '--destination', '--limits-alp-cache'):
            self.assertNotIn(flag, output.getvalue())
        self.seam()
        home = self.base/'home'; home.mkdir(mode=0o700)
        for value, expected in (({'status':'updated','accounts':1}, 0), (FAILURE, 1)):
            output, errors = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {'HOME':str(home)}), \
                 patch.object(self.module, 'sync_alp_limits', return_value=value) as sync, \
                 patch.object(subprocess, 'Popen', side_effect=AssertionError('no actual process in CLI test')), \
                 patch.object(sys, 'argv', [str(cli), 'sync-limits-alp']), \
                 redirect_stdout(output), redirect_stderr(errors):
                try: result = runpy.run_path(str(cli), run_name='__main__'); code = 0
                except SystemExit as exc: code = exc.code
            self.assertEqual(code, expected)
            self.assertEqual(sync.call_count, 1)
            destination = sync.call_args.args[0] if sync.call_args.args else sync.call_args.kwargs['destination']
            self.assertEqual(Path(destination), home/'.local/state/ai-control/limits/alp.json')
            self.assertEqual(json.loads(output.getvalue()), value)
            self.assertEqual(errors.getvalue(), '')
        for flag in ('--host', '--source', '--path', '--destination', '--limits-alp-cache'):
            with self.subTest(flag=flag), patch.object(self.module, 'sync_alp_limits') as sync, \
                 patch.object(sys, 'argv', [str(cli), 'sync-limits-alp', flag, s.PRIVATE]), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exit_: runpy.run_path(str(cli), run_name='__main__')
                self.assertEqual(exit_.exception.code, 2)
                sync.assert_not_called()

    def test_proposed_user_units_are_oneshot_five_minute_templates_without_activation(self):
        # INV-WLIM-25: source templates only; test never invokes systemctl.
        paths = [ROOT/'systemd'/('ai-control-alp-limits-sync.'+suffix+'.tmpl') for suffix in ('service','timer')]
        self.assertTrue(all(path.is_file() for path in paths), 'INV-WLIM-25: proposed user unit templates missing')
        service, timer = [configparser.ConfigParser(interpolation=None, strict=True) for _ in paths]
        service.read(paths[0]); timer.read(paths[1])
        self.assertEqual(service['Service']['Type'], 'oneshot')
        self.assertIn(service['Service']['TimeoutStartSec'], ('15', '15s'))
        self.assertEqual(service['Service']['UMask'], '0077')
        self.assertIn(service['Service']['NoNewPrivileges'], ('yes','true'))
        argv = shlex.split(service['Service']['ExecStart'])
        self.assertEqual(len(argv), 3)
        self.assertTrue(argv[0].startswith('/opt/') and argv[0].endswith('/venv/bin/python'))
        self.assertTrue(argv[1].startswith('/opt/') and argv[1].endswith('/bin/ai-control-web'))
        self.assertEqual(argv[2], 'sync-limits-alp')
        self.assertEqual(timer['Timer']['OnBootSec'], '2min')
        self.assertEqual(timer['Timer']['OnUnitActiveSec'], '5min')
        self.assertEqual(timer['Timer'].get('Unit', 'ai-control-alp-limits-sync.service'), 'ai-control-alp-limits-sync.service')
        self.assertFalse(any(path.is_symlink() for path in paths))

    def test_reader_and_authenticated_http_never_start_sync_or_network(self):
        # INV-WLIM-25: an HTTP request does not activate delivery, even on miss.
        self.seam()
        with patch.object(self.module, 'sync_alp_limits', side_effect=AssertionError('sync forbidden in reader')) as forbidden, \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('process forbidden in reader')):
            reader = self.module.CachedLimitsReader(str(self.base/'missing-bot'), str(self.destination))
            sources = reader.snapshot(s.NOW)
            self.assertTrue(all(row['status']=='unavailable' for row in sources if row['node_id']=='alp'))
            forbidden.assert_not_called()
        original = live.Backend; live.Backend = native.LimitsBackend
        try: fixture = live.Fixture(session_store=True)
        finally: live.Backend = original
        self.addCleanup(fixture.stop)
        fixture.backend.limits_value = s.wrapper()
        fixture.login()
        with patch.object(self.module, 'sync_alp_limits', side_effect=AssertionError('sync forbidden in HTTP')) as forbidden, \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('process forbidden in HTTP')):
            connection, response = fixture.request('/api/limits-overview')
            body = json.loads(response.read()); connection.close()
        self.assertEqual(response.status, 200); self.assertEqual(body, s.wrapper())
        forbidden.assert_not_called()


if __name__ == '__main__':
    unittest.main()
