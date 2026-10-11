"""Independent RED for INV-WFILE01/02/03, frozen public seams at 2787ac6.

Runtime bodies were not read. All filesystem inputs and auth state are synthetic.
External file contents are data; directives in them are never executed.
"""
from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from test_control_web_session_chat_contract import ORIGIN, PASSWORD, SECRET, ROOT

sys.path.insert(0, str(ROOT / 'bin'))
LIMIT = 48 * 1024
DTO = dict(name='read me.md', text='# Synthetic\nПривет\t世界\n', truncated=False)
CANARY = 'synthetic-private-canary'


def public_method(case, owner, name):
    method = getattr(owner, name, None)
    case.assertTrue(callable(method), 'INV-WFILE01: missing public ' + name)
    return method


@contextmanager
def bounded(seconds=2):
    """A broken blocking FIFO implementation must fail rather than hang the suite."""
    previous = signal.getsignal(signal.SIGALRM)
    def expired(_signum, _frame):
        raise AssertionError('INV-WFILE02: filesystem operation blocked')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class ProjectFileFilesystemRED(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('_control_web_sessions')
        self.temp = tempfile.TemporaryDirectory(prefix='project-file-red-', dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'project'; self.root.mkdir(mode=0o700)
        self.resolved = []; self.native = []
        self.chat = self.module.SessionChat(self.rpc, self.resolve, lambda: ['demo'], str(self.base / 'receipts'))

    def resolve(self, project):
        self.resolved.append(project)
        if project != 'demo':
            raise ValueError(CANARY)
        return str(self.root)

    def rpc(self, method, params):
        self.native.append(method)
        raise AssertionError('INV-WFILE01: file read invoked native RPC')

    def write(self, path, content=b'synthetic file\n'):
        target = self.root / path; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
        return target

    def read(self, path, project='demo'):
        method = public_method(self, self.chat, 'project_file')
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('commands forbidden')), \
             patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')), bounded():
            value = method(project, path)
        self.assertEqual(self.native, [])
        self.assertIs(type(value), dict)
        self.assertNotIn(CANARY, json.dumps(value))
        self.assertNotIn(str(self.base), json.dumps(value))
        return value

    def denied(self, path, error='file_unavailable', project='demo'):
        self.assertEqual(self.read(path, project), {'error': error})

    def test_regular_utf8_nested_spaces_relative_absolute_literal_html(self):
        # INV-WFILE01 INV-WFILE02 INV-WFILE03
        text = '<script>synthetic()</script>\nПривет\t世界\r\n'
        target = self.write('docs/nested/read me.md', text)
        expected = dict(name='read me.md', text=text, truncated=False)
        for path in ('docs/nested/read me.md', './docs/nested/read me.md', str(target)):
            with self.subTest(form=path[:2]): self.assertEqual(self.read(path), expected)
        self.assertTrue(self.resolved)

    def test_inside_symlinks_and_percent_literal_are_allowed(self):
        # INV-WFILE02: aliases inside root and one-decode contract.
        self.write('docs/real.txt', 'inside\n')
        (self.root / 'shortcut.txt').symlink_to('docs/real.txt')
        (self.root / 'alias-dir').symlink_to('docs', target_is_directory=True)
        for path in ('shortcut.txt', 'alias-dir/real.txt'):
            value = self.read(path); self.assertEqual(value['text'], 'inside\n')
            self.assertEqual(set(value), {'name', 'text', 'truncated'})
        self.write('%2e%2e.txt', 'literal percent\n')
        self.assertEqual(self.read('%2e%2e.txt')['text'], 'literal percent\n')
        self.write('*.txt', 'literal glob\n')
        self.assertEqual(self.read('*.txt')['text'], 'literal glob\n')
        self.denied('docs/*.txt')

    def test_absolute_configured_root_alias_preserves_inside_and_denies_hidden_or_escape(self):
        # INV-WFILE01 INV-WFILE02: configured path alias is canonical-root authority.
        text = 'Synthetic configured root alias\n'
        self.write('docs/report.md', text)
        configured = self.base / 'visible-root-alias'
        configured.symlink_to(self.root, target_is_directory=True)
        (self.root / 'docs' / '.hidden-report.md').symlink_to('report.md')
        outside = self.base / 'outside-report.md'; outside.write_text(CANARY)
        (self.root / 'docs' / 'escape.md').symlink_to(outside)
        def project_path(project):
            self.resolved.append(project)
            if project != 'demo': raise ValueError(CANARY)
            return str(configured)
        self.chat = self.module.SessionChat(self.rpc, project_path, lambda: ['demo'],
                                            str(self.base / 'alias-receipts'))
        for relative, expected in (
            ('docs/report.md', dict(name='report.md', text=text, truncated=False)),
            ('docs/.hidden-report.md', {'error': 'file_unavailable'}),
            ('docs/escape.md', {'error': 'file_unavailable'}),
        ):
            with self.subTest(relative=relative):
                self.assertEqual(self.read(str(configured / relative)), expected)

    def test_unknown_project_missing_outside_and_traversal_are_generic(self):
        # INV-WFILE01 INV-WFILE02
        self.write('ok.txt'); outside = self.base / 'outside.txt'; outside.write_text(CANARY)
        self.assertIn(self.read('ok.txt', project='unknown'),
                      ({'error': 'file_unavailable'}, {'error': 'invalid_request'}))
        for path in ('missing.txt', str(outside), '.', str(self.root)):
            with self.subTest(path=Path(path).name): self.denied(path)
        self.denied('docs/../ok.txt', 'invalid_request')
        original_open = os.open
        def permission_error(component, flags, *args, **kwargs):
            if os.fspath(component) in ('ok.txt', str(self.root / 'ok.txt')):
                raise PermissionError(CANARY)
            return original_open(component, flags, *args, **kwargs)
        with patch.object(os, 'open', side_effect=permission_error): self.denied('ok.txt')

    def test_invalid_path_grammar_and_types(self):
        # INV-WFILE02
        for path in ('', None, 7, True, 'a'*4097, 'a\x00b', 'a\nb', 'a\x7fb',
                     'a\\b', 'file:///tmp/x', 'https://example.invalid/x', '//host/x',
                     'read.txt?q=x', 'read.txt#L2'):
            with self.subTest(kind=type(path).__name__): self.denied(path, 'invalid_request')

    def test_symlink_escape_and_root_prefix_collision(self):
        # INV-WFILE02: lexical prefix and canonical escape do not grant access.
        other = self.base / 'project-other'; other.mkdir()
        (other / 'outside.txt').write_text(CANARY)
        (self.root / 'escape.txt').symlink_to(other / 'outside.txt')
        (self.root / 'escape-dir').symlink_to(other, target_is_directory=True)
        for path in ('escape.txt', 'escape-dir/outside.txt', str(other / 'outside.txt')):
            self.denied(path)

    def test_hidden_and_reserved_credentials_original_and_canonical(self):
        # INV-WFILE02
        paths = ['.env', '.git/config', '.ssh/id_other', '.codex/note.md', '.claude/note.md',
                 'docs/.private/read.txt', 'AUTH.JSON', 'totp-state.json', 'Credentials.YAML',
                 'credentials.yml', 'id_rsa', 'ID_ED25519', 'cert.PEM', 'secret.key', 'a.p12', 'a.pfx']
        for index, path in enumerate(paths):
            target = self.write(path, CANARY)
            alias = 'public-alias-' + str(index) + '.txt'; (self.root / alias).symlink_to(target)
            with self.subTest(path=path):
                self.denied(path); self.denied(alias)
        self.write('public.txt')
        (self.root / '.hidden-alias.txt').symlink_to('public.txt')
        self.denied('.hidden-alias.txt')

    def test_fifo_socket_directory_and_hardlink_are_unavailable_without_blocking(self):
        # INV-WFILE02
        os.mkfifo(self.root / 'pipe.txt')
        unix = socket.socket(socket.AF_UNIX); unix.bind(str(self.root / 'socket.txt'))
        self.addCleanup(unix.close)
        target = self.write('original.txt'); os.link(target, self.root / 'second.txt')
        (self.root / 'folder').mkdir()
        for path in ('pipe.txt', 'socket.txt', 'folder', 'original.txt', 'second.txt'):
            with self.subTest(path=path): self.denied(path)

    def test_binary_and_malformed_utf8_fail_closed(self):
        # INV-WFILE03
        for index, raw in enumerate((b'hello\x00world', b'hello\x01world', b'\xff', b'text\xe2\x82')):
            path = 'binary-' + str(index) + '.txt'; self.write(path, raw)
            self.denied(path, 'unsupported_type')

    def test_48k_utf8_prefix_boundary_and_exact_length(self):
        # INV-WFILE03: truncation must preserve strict UTF-8 and exact byte budget.
        for index, (raw, text, truncated) in enumerate((
            (b'a'*LIMIT, 'a'*LIMIT, False),
            (b'a'*(LIMIT-1)+'€tail'.encode(), 'a'*(LIMIT-1), True),
            (('😀'*(LIMIT//4+20)).encode(), '😀'*(LIMIT//4), True))):
            path = 'large-' + str(index) + '.txt'; self.write(path, raw)
            result = self.read(path)
            self.assertEqual(result, dict(name=path, text=text, truncated=truncated))
            self.assertLessEqual(len(result['text'].encode('utf-8')), LIMIT)

    def test_read_budget_and_file_change_during_read_discard_result(self):
        # INV-WFILE03: full-file allocation and metadata change, no mixed response.
        path = self.write('bounded.txt', b'a'*LIMIT)
        with path.open('r+b') as writer: writer.truncate(16*1024*1024)
        # Warm imports/descriptor machinery before measuring the large sparse file.
        self.write('warm.txt'); self.read('warm.txt')
        tracemalloc.start()
        try:
            value = self.read('bounded.txt'); _, peak = tracemalloc.get_traced_memory()
        finally: tracemalloc.stop()
        self.assertEqual(value, dict(name='bounded.txt', text='a'*LIMIT, truncated=True))
        self.assertLess(peak, 2*1024*1024, 'must not allocate a complete 16MiB file')
        identity = path.stat(); original_stat = os.fstat; changed = []
        def mutate(fd):
            value = original_stat(fd)
            if (value.st_dev, value.st_ino) == (identity.st_dev, identity.st_ino) and not changed:
                changed.append(True)
                with path.open('ab') as writer: writer.write(b'changed')
            return value
        with patch.object(os, 'fstat', side_effect=mutate): self.denied('bounded.txt')
        self.assertTrue(changed, 'fixture must mutate after a real target metadata snapshot')

    def test_component_replacement_between_resolution_and_open_cannot_escape(self):
        # INV-WFILE02: deterministic component race at the public os.open boundary.
        self.write('docs/note.txt', 'inside')
        outside = self.base / 'outside'; outside.mkdir(); (outside / 'note.txt').write_text(CANARY)
        original_open = os.open; changed = []
        def replace(component, flags, *args, **kwargs):
            if not changed and os.fspath(component) in ('docs', str(self.root / 'docs')):
                changed.append(True)
                (self.root / 'docs').rename(self.root / 'old-docs')
                (self.root / 'docs').symlink_to(outside, target_is_directory=True)
            return original_open(component, flags, *args, **kwargs)
        with patch.object(os, 'open', side_effect=replace): self.denied('docs/note.txt')
        self.assertTrue(changed, 'fixture must replace a resolved directory before descriptor open')


class FileBackend:
    def __init__(self): self.calls = []; self.value = dict(DTO)
    def project_file(self, project, path):
        self.calls.append((project, path)); return self.value


class ProjectFileHTTPRED(unittest.TestCase):
    def setUp(self):
        self.web = importlib.import_module('_control_web'); self.backend = FileBackend()
        self.now = 1800000000; self.sessions = {}
        config = dict(origin=ORIGIN, password_hash=self.web.hash_password(PASSWORD),
                      totp_secret=SECRET, session_ttl=60, secure_cookie=True)
        self.client = TestClient(self.web.create_app(config, self.backend,
            clock=lambda: self.now, session_store=self.sessions), base_url=ORIGIN)
        self.addCleanup(self.client.close)
        self.path = '/api/project-file?' + urlencode(dict(project='demo', path='docs/read me.md'))

    def login(self):
        response = self.client.post('/api/login', json=dict(username='owner', password=PASSWORD,
            totp=self.web.totp_code(SECRET, self.now)), headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)

    def get(self, path=None, origin=ORIGIN):
        return self.client.get(path or self.path, headers={'Origin': origin} if origin else {})

    def test_owner_exact_arguments_closed_dto_no_store(self):
        # INV-WFILE01 INV-WFILE03
        self.login(); response = self.get()
        self.assertEqual(response.status_code, 200, response.text); self.assertEqual(response.json(), DTO)
        self.assertIn('no-store', response.headers.get('cache-control', ''))
        self.assertEqual(self.backend.calls, [('demo', 'docs/read me.md')])

    def test_anonymous_expired_nonowner_foreign_origin_before_backend(self):
        # INV-WFILE01
        self.assertEqual(self.get().status_code, 401)
        self.login(); self.assertEqual(self.get(origin='https://evil.invalid').status_code, 403)
        self.assertEqual(len(self.sessions), 1)
        record = next(iter(self.sessions.values())); original = record['principal']
        for principal in ('reviewer', None, True):
            record['principal'] = principal; self.assertEqual(self.get().status_code, 403)
        record['principal'] = original; self.now += 61
        self.assertEqual(self.get().status_code, 401); self.assertEqual(self.backend.calls, [])

    def test_query_exact_repeated_missing_wrong_types_and_path_grammar(self):
        # INV-WFILE01 INV-WFILE02
        self.login()
        for suffix in ('&line=1', '&root=/tmp', '&path=second.txt', '&project=other'):
            with self.subTest(suffix=suffix): self.assertEqual(self.get(self.path+suffix).status_code, 422)
        for query in ('project=demo', 'path=read.txt', 'project=demo&path=',
                      urlencode(dict(project='demo', path='../outside.txt')),
                      urlencode(dict(project='demo', path='file:///tmp/a'))):
            self.assertEqual(self.get('/api/project-file?'+query).status_code, 422)
        self.assertEqual(self.backend.calls, [])

    def test_absent_get_origin_allowed_and_typed_error_not_200(self):
        # INV-WFILE01 INV-WFILE03: fixed GET guard, no retries/fallback.
        self.login(); self.assertEqual(self.get(origin=None).status_code, 200)
        for error, status in (('invalid_request', 422), ('unsupported_type', 415), ('file_unavailable', 404)):
            self.backend.value = {'error': error}; response = self.get()
            self.assertEqual(response.status_code, status); self.assertEqual(response.json(), {'error': error})
        self.assertEqual(len(self.backend.calls), 4)

    def test_corrupt_backend_dto_never_serializes_private_fields_or_oversize(self):
        # INV-WFILE03: validate positive control before corrupted response.
        self.login(); self.assertEqual(self.get().json(), DTO)
        for value in ({**DTO, 'path': CANARY}, {**DTO, 'name': '/tmp/'+CANARY},
                      {**DTO, 'text': 'x'*(LIMIT+1)}, {**DTO, 'truncated': 1}):
            self.backend.value = value; response = self.get()
            self.assertGreaterEqual(response.status_code, 400)
            self.assertNotIn(CANARY, response.text); self.assertNotIn('text', response.json())


class ProjectFileBrokerRED(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('_control_web_broker')
        self.temp = tempfile.TemporaryDirectory(prefix='project-file-broker-red-', dir='/var/tmp')
        self.addCleanup(self.temp.cleanup); self.base = Path(self.temp.name); self.base.chmod(0o700)
        self.path = str(self.base / 'broker.sock'); self.backend = FileBackend()
        self.stop = threading.Event(); self.worker = None; self.errors = []

    def start(self):
        def run():
            try: self.module.serve_broker(self.path, self.backend, os.getuid(), stop_event=self.stop)
            except Exception as error: self.errors.append(type(error).__name__)
        self.worker = threading.Thread(target=run, daemon=True); self.worker.start()
        self.addCleanup(self.shutdown)
        deadline = time.monotonic()+2
        while not Path(self.path).exists() and not self.errors and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual(self.errors, []); self.assertTrue(Path(self.path).exists())

    def shutdown(self):
        self.stop.set()
        if self.worker: self.worker.join(2)

    def wire(self, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(2); sock.connect(self.path); sock.sendall(raw+b'\n'); data = b''
            while b'\n' not in data:
                chunk = sock.recv(128*1024+1)
                self.assertTrue(chunk, 'broker closed without a typed response')
                data += chunk; self.assertLessEqual(len(data), 128*1024)
        return json.loads(data.split(b'\n', 1)[0])

    def test_registry_and_socket_methods_use_same_positional_project_path(self):
        # INV-WFILE01
        registry = self.base / 'registry'; registry.mkdir()
        facade = FileBackend(); backend = self.module.RegistryBackend(str(registry), str(ROOT/'bin'), sessions=facade)
        invoke = public_method(self, backend, 'project_file')
        self.assertEqual(invoke('demo', 'docs/read me.md'), DTO)
        self.assertEqual(facade.calls, [('demo', 'docs/read me.md')])
        self.start(); client = self.module.SocketBackend(self.path)
        invoke = public_method(self, client, 'project_file')
        self.assertEqual(invoke('demo', 'docs/read me.md'), DTO)
        self.assertEqual(self.backend.calls, [('demo', 'docs/read me.md')])

    def test_exact_wire_operation_and_full_utf8_dto_fit_existing_cap(self):
        # INV-WFILE01 INV-WFILE03
        self.start(); request = dict(op='project_file', project='demo', path='read me.md')
        self.assertEqual(self.wire(request), DTO)
        self.backend.value = dict(name='unicode.txt', text='😀'*(LIMIT//4), truncated=True)
        self.assertEqual(self.wire(request), self.backend.value)
        self.assertEqual(self.backend.calls, [('demo', 'read me.md')]*2)

    def test_wire_extra_duplicate_missing_and_malformed_fields_never_dispatch(self):
        # INV-WFILE01 INV-WFILE02: positive control prevents vacuous unsupported-op success.
        self.start(); valid = dict(op='project_file', project='demo', path='ok.txt')
        self.assertEqual(self.wire(valid), DTO); self.backend.calls.clear()
        cases = [{**valid, 'line': 2}, {**valid, 'root': '/tmp'}, {**valid, 'rpc': 'thread/resume'},
                 {'op':'project_file', 'project':'demo'}, {**valid, 'path':None}, {**valid, 'path':True},
                 {**valid, 'path':'../outside.txt'}, {**valid, 'project':'../demo'},
                 b'{"op":"project_file","project":"demo","path":"a","path":"b"}']
        for value in cases:
            with self.subTest(kind=type(value).__name__):
                self.assertEqual(self.wire(value), {'error': 'invalid_request'})
        self.assertEqual(self.backend.calls, [])

    def test_socket_invalid_request_does_not_contact_owner(self):
        # INV-WFILE01 INV-WFILE02
        client = self.module.SocketBackend(self.path); invoke = public_method(self, client, 'project_file')
        for project, path in (('demo', ''), ('demo', '../out.txt'), ('demo', None), ('../demo', 'a.txt')):
            self.assertEqual(invoke(project, path), {'error':'invalid_request'})
        self.assertFalse(Path(self.path).exists())

    def test_broker_closes_corrupt_dto_and_preserves_typed_errors(self):
        # INV-WFILE03
        self.start(); request = dict(op='project_file', project='demo', path='ok.txt')
        self.assertEqual(self.wire(request), DTO)
        for value in ({**DTO, 'hostpath': CANARY}, {**DTO, 'text':'x'*(LIMIT+1)},
                      {**DTO, 'name':'../'+CANARY}, {**DTO, 'truncated':0}):
            self.backend.value = value; result = self.wire(request)
            self.assertEqual(set(result), {'error'}); self.assertNotIn(CANARY, json.dumps(result))
        for error in ('invalid_request', 'unsupported_type', 'file_unavailable'):
            self.backend.value = {'error': error}; self.assertEqual(self.wire(request), self.backend.value)

    def test_public_result_validator_exact_keys_types_utf8_limit_and_errors(self):
        # INV-WFILE03
        validate = public_method(self, self.module, 'project_file_result')
        self.assertEqual(validate(DTO), DTO)
        bad = [None, [], {k:v for k,v in DTO.items() if k!='text'}, {**DTO, 'private':CANARY},
               {**DTO, 'name':'../'+CANARY}, {**DTO, 'name':''}, {**DTO, 'text':None},
               {**DTO, 'text':'😀'*(LIMIT//4+1)}, {**DTO, 'text':'bad\x00text'},
               {**DTO, 'truncated':1}, {'error':'file_unavailable', 'reason':CANARY}, {'error':CANARY}]
        for value in bad:
            result = validate(value); self.assertEqual(set(result), {'error'})
            self.assertNotIn(CANARY, json.dumps(result))
        for error in ('invalid_request', 'unsupported_type', 'file_unavailable'):
            self.assertEqual(validate({'error':error}), {'error':error})


if __name__ == '__main__': unittest.main()
