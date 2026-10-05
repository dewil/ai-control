#!/usr/bin/python3
"""Fixed-scope signed deploy controller; payload bytes are never executed here."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile

TARGET = Path('/opt/ai-control-web')
STAGE = Path('/home/dwl/ai-control-deploy-stage')
CHECKPOINTS = Path('/var/lib/ai-control-deploy/checkpoints')
STATE = Path('/var/lib/ai-control-deploy/accepted.json')
KEY = Path('/etc/ai-control-deploy/release-key.pem')
MAX_FILE = 2 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
SERVICES = ('ai-control-web.service', 'ai-control-web-broker.service')
MODES = {'bin/ai-control-web': 493, 'bin/_control_web.py': 420, 'bin/_control_web_broker.py': 420, 'bin/_control_web_sessions.py': 420, 'bin/_codex_rc.py': 420, 'bin/_rc_projects.sh': 493, 'bin/_control_web.html': 420, 'bin/_control_web.css': 420, 'bin/_control_web.js': 420, 'requirements-web.lock': 420, 'systemd/ai-control-web.service.tmpl': 420, 'systemd/ai-control-web-broker.service.tmpl': 420, 'bin/_control_web.svg': 420}
BOOTSTRAP_BASE = {'bin/ai-control-web': '2dbe492440a9e01f73468f2220a4e8b8b908fab2ea8c6a13a55d79409730f4e7', 'bin/_control_web.py': 'a0724ec2c3a505fdc123b96c90a178657e835562ce6b018ea34b8214e6617e8a', 'bin/_control_web_broker.py': 'c4f6f69e0c9d258c07f0138c192e35e99b30254485e078e4403acf5c9bc994e6', 'bin/_control_web_sessions.py': '978847a34320fb381f4bad2848a8832274c4dc34d7f816b9173d4e39e4bc510a', 'bin/_codex_rc.py': '8113bff19a607e9d0dd84af387a4aa700bb2dbfcd3223dc01a6d7c6cd8b6c3e6', 'bin/_rc_projects.sh': '8576c2c5aa4d0c5c24b9efee6ceeb3a9c46882724d6796acbce4a20246a6b2e6', 'bin/_control_web.html': '210ea89cdf6724f0f920cc39fc279a66477d8f08cfa10be1d4dda31862ce5b7f', 'bin/_control_web.css': '5a59c6251dbd376a73f0814ec094747b0a3413cfe80c15e94bbf1cb6dcb170de', 'bin/_control_web.js': 'be0f799ff9ba72b5d22a602b24919c3360d693a4b43ad24e15b1204eb7a55e15', 'requirements-web.lock': 'c56ca5ea2670d01dac8c1d3daa8ee204323bacb29e8a347a749c987a6615d222', 'systemd/ai-control-web.service.tmpl': 'ae73cbaf5dc9c6f35d973573a1a18b0ce451b9142c0c22ab8cc4f87b4b80c641', 'systemd/ai-control-web-broker.service.tmpl': '1bd0ad1c78d98b22245ace274c9b96a59159f0b14f6669b4e09076f87cd53434', 'bin/_control_web.svg': '2a6b140eb1e60610f61aeb3941241bab9121cc4f6f5b31e42d7da8743a2c79e9'}


class Rejected(Exception):
    """Input or controller state failed validation."""


class RollbackFailed(Exception):
    """Recovery could not be verified; retain the pending journal."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def runner(args):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=40, cwd='/',
                          env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}).stdout.strip()


def directory(path, owner_uid, private=False, ancestors=True):
    """Open each component without following links and validate ownership."""
    path = Path(os.path.abspath(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(path.parts[1:]):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            last = index == len(path.parts) - 2
            if last or ancestors:
                allowed = (owner_uid,) if last else (0, owner_uid)
                sticky_temp = (not last and info.st_uid == 0
                               and stat.S_ISVTX & info.st_mode
                               and Path(*path.parts[:index + 2]) in
                               (Path('/tmp'), Path('/var/tmp')))
                if info.st_uid not in allowed or (info.st_mode & 0o022 and not sticky_temp):
                    raise Rejected('Unsafe directory')
                if last and private and stat.S_IMODE(info.st_mode) != 0o700:
                    raise Rejected('Controller directory is not private')
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_file(path, *, owners, limit=MAX_FILE, mode=None, private_parent=False):
    """Bounded snapshot from an anchored descriptor; no symlinks or hardlinks."""
    path = Path(path)
    # Stage ancestry is not root authority; it is still walked without links.
    fd = directory(path.parent, owners[0], private=private_parent,
                   ancestors=len(owners) == 1)
    try:
        child = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=fd)
        try:
            info = os.fstat(child)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid not in owners or info.st_mode & 0o022
                    or info.st_size > limit
                    or (mode is not None and stat.S_IMODE(info.st_mode) != mode)):
                raise Rejected('Unsafe or oversized file')
            chunks = []
            total = 0
            while True:
                chunk = os.read(child, min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limit:
                    raise Rejected('Oversized snapshot')
            return b''.join(chunks)
        finally:
            os.close(child)
    finally:
        os.close(fd)


def atomic_write(path, data, mode, owner_uid):
    path = Path(path)
    parent = directory(path.parent, owner_uid)
    name = '.deploy-' + os.urandom(16).hex()
    fd = None
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as out:
            fd = None
            out.write(data)
            out.flush()
            os.fchmod(out.fileno(), mode)
            if os.geteuid() == 0:
                os.fchown(out.fileno(), owner_uid, owner_uid)
            os.fsync(out.fileno())
        os.replace(name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(name, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Rejected('Duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(Rejected('Invalid JSON number')))
    except (ValueError, UnicodeError) as exc:
        raise Rejected('Invalid JSON') from exc


def keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise Rejected('Unexpected schema keys')


def integer(value, minimum):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise Rejected('Invalid release identity')


def hashes(value):
    keys(value, MODES)
    for item in value.values():
        if type(item) is not str or re.fullmatch('[0-9a-f]{64}', item) is None:
            raise Rejected('Invalid digest')


def state_value(value):
    keys(value, ('schema', 'release_id', 'manifest_sha256', 'files'))
    if type(value['schema']) is not int or value['schema'] != 1:
        raise Rejected('Invalid state schema')
    integer(value['release_id'], 0)
    hashes(value['files'])
    sha = value['manifest_sha256']
    if value['release_id'] == 0:
        if sha is not None or value['files'] != BOOTSTRAP_BASE:
            raise Rejected('Invalid bootstrap state')
    elif type(sha) is not str or re.fullmatch('[0-9a-f]{64}', sha) is None:
        raise Rejected('Invalid state digest')
    return value


def tree(target, owner_uid):
    for relative in ('', 'bin', 'systemd'):
        os.close(directory(Path(target) / relative, owner_uid))
    return {path: read_file(Path(target) / path, owners=(owner_uid,), mode=mode)
            for path, mode in MODES.items()}


def tree_hashes(payload):
    return {path: digest(data) for path, data in payload.items()}


def initialize_state(target, state_path, *, owner_uid=0):
    """Operator-only bootstrap: authenticate compiled baseline, never overwrite."""
    state_path = Path(state_path)
    os.close(directory(state_path.parent, owner_uid, private=True))
    if os.path.lexists(state_path):
        raise Rejected('State already exists')
    if tree_hashes(tree(target, owner_uid)) != BOOTSTRAP_BASE:
        raise Rejected('Bootstrap tree mismatch')
    value = {'schema': 1, 'release_id': 0, 'manifest_sha256': None,
             'files': dict(BOOTSTRAP_BASE)}
    # Publish without replacement, even if another bootstrap raced this call.
    parent = directory(state_path.parent, owner_uid, private=True)
    try:
        fd = os.open(state_path.name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as out:
            out.write(encode(value))
            out.flush()
            if os.geteuid() == 0:
                os.fchown(out.fileno(), owner_uid, owner_uid)
            os.fsync(out.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)


def verify_ed25519(manifest, sig, key):
    if len(sig) != 64:
        return False
    # OpenSSL reads only these private immutable snapshots, never stage paths.
    with tempfile.TemporaryDirectory(prefix='ai-control-verify-', dir='/tmp') as name:
        root = Path(name)
        os.chmod(root, 0o700)
        for filename, data in (('manifest', manifest), ('signature', sig), ('key', key)):
            fd = os.open(root / filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as out:
                out.write(data)
        try:
            public = subprocess.run(
                ['/usr/bin/openssl', 'pkey', '-pubin', '-in', str(root / 'key'),
                 '-outform', 'DER'], cwd='/',
                env={'PATH': '/usr/bin:/bin', 'LANG': 'C'},
                capture_output=True, timeout=40)
            if (public.returncode != 0 or len(public.stdout) != 44
                    or not public.stdout.startswith(bytes.fromhex('302a300506032b6570032100'))):
                return False
            result = subprocess.run(
                ['/usr/bin/openssl', 'pkeyutl', '-verify', '-pubin', '-inkey',
                 str(root / 'key'), '-rawin', '-in', str(root / 'manifest'),
                 '-sigfile', str(root / 'signature')],
                cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C'},
                capture_output=True, timeout=40)
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


class Deploy:
    def __init__(self, target=TARGET, stage=STAGE, checkpoints=CHECKPOINTS,
                 runner=runner, *, state_path=None, key_path=None, owner_uid=0,
                 verifier=None):
        self.target = Path(target)
        self.stage = Path(stage)
        self.checkpoints = Path(checkpoints)
        self.state_path = Path(state_path) if state_path is not None else STATE
        self.key_path = Path(key_path) if key_path is not None else KEY
        self.owner_uid = owner_uid
        self.runner = runner
        self.verifier = verifier if verifier is not None else verify_ed25519
        self.pending = self.checkpoints / 'pending.json'

    def ctl(self, *args):
        return self.runner(['/usr/bin/systemctl', *args]).strip()

    def services(self):
        for service, user in zip(SERVICES, ('ai-panel', 'dwl')):
            if (self.ctl('is-active', service) != 'active'
                    or self.ctl('show', service, '-p', 'User', '--value') != user
                    or self.ctl('show', service, '-p', 'Group', '--value') != 'ai-panel'):
                raise Rejected('Service health or account mismatch')

    def stop(self):
        for service in SERVICES:
            self.ctl('stop', service)

    def start(self):
        self.ctl('start', SERVICES[1])
        self.ctl('start', SERVICES[0])
        self.services()

    def read_state(self):
        return state_value(decode(read_file(self.state_path, owners=(self.owner_uid,),
                                           limit=MAX_MANIFEST, mode=0o600,
                                           private_parent=True)))

    def publish(self, state):
        atomic_write(self.state_path, encode(state), 0o600, self.owner_uid)

    def install(self, payload):
        for path, data in payload.items():
            atomic_write(self.target / path, data, MODES[path], self.owner_uid)

    def match(self, expected):
        if tree_hashes(tree(self.target, self.owner_uid)) != expected:
            raise Rejected('Installed tree mismatch')

    def clear_pending(self):
        fd = directory(self.checkpoints, self.owner_uid, private=True)
        try:
            os.unlink('pending.json', dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)

    def rollback(self, before, old):
        try:
            self.stop()
            self.install(old)
            self.start()
            self.match(before['files'])
            self.publish(before)
            self.clear_pending()
        except Exception as exc:
            raise RollbackFailed('Rollback failed; pending journal retained') from exc

    def recover(self, accepted):
        if not os.path.lexists(self.pending):
            return accepted
        journal = decode(read_file(self.pending, owners=(self.owner_uid,),
                                   limit=MAX_MANIFEST, mode=0o600, private_parent=True))
        keys(journal, ('schema', 'before', 'after', 'checkpoint'))
        if type(journal['schema']) is not int or journal['schema'] != 1:
            raise Rejected('Invalid journal schema')
        before, after = state_value(journal['before']), state_value(journal['after'])
        if after['release_id'] <= before['release_id'] or accepted not in (before, after):
            raise Rejected('Journal state mismatch')
        name = journal['checkpoint']
        if type(name) is not str or re.fullmatch('[a-zA-Z0-9_-]+', name) is None:
            raise Rejected('Invalid checkpoint name')
        checkpoint = self.checkpoints / name
        os.close(directory(checkpoint, self.owner_uid, private=True))
        saved = state_value(decode(read_file(checkpoint / 'accepted.json',
            owners=(self.owner_uid,), limit=MAX_MANIFEST, mode=0o600, private_parent=True)))
        if saved != before:
            raise Rejected('Checkpoint state mismatch')
        old = {path: read_file(checkpoint / Path(path).name, owners=(self.owner_uid,),
                              mode=0o600, private_parent=True) for path in MODES}
        if tree_hashes(old) != before['files']:
            raise Rejected('Checkpoint bytes mismatch')
        current = tree_hashes(tree(self.target, self.owner_uid))
        if any(current[path] not in (before['files'][path], after['files'][path])
               for path in MODES):
            raise Rejected('Unknown bytes in interrupted tree')
        if accepted == after and current == after['files']:
            try:
                self.services()
            except Exception:
                pass
            else:
                self.clear_pending()
                return after
        self.rollback(before, old)
        return before

    def staged(self):
        info = self.stage.lstat()
        stage_uid = info.st_uid
        os.close(directory(self.stage, stage_uid, ancestors=False))
        allowed = set(MODES) | {'release.json', 'release.sig'}
        directories = {'bin', 'systemd'}
        for root, dirs, files in os.walk(self.stage, followlinks=False):
            for name in dirs:
                path = Path(root) / name
                relative = path.relative_to(self.stage).as_posix()
                if relative not in directories:
                    raise Rejected('Extra staging directory')
                os.close(directory(path, stage_uid, ancestors=False))
            for name in files:
                if (Path(root) / name).relative_to(self.stage).as_posix() not in allowed:
                    raise Rejected('Extra staging file')
        owners = (stage_uid, 0)
        raw = read_file(self.stage / 'release.json', owners=owners, limit=MAX_MANIFEST)
        sig = read_file(self.stage / 'release.sig', owners=owners, limit=64)
        key = read_file(self.key_path, owners=(self.owner_uid,), limit=MAX_MANIFEST, mode=0o644)
        if len(sig) != 64 or not self.verifier(raw, sig, key):
            raise Rejected('Signature verification failed')
        manifest = decode(raw)
        keys(manifest, ('schema', 'release_id', 'base', 'files'))
        if type(manifest['schema']) is not int or manifest['schema'] != 1:
            raise Rejected('Invalid release schema')
        integer(manifest['release_id'], 1)
        hashes(manifest['base'])
        keys(manifest['files'], MODES)
        expected = {}
        for path, item in manifest['files'].items():
            keys(item, ('sha256', 'mode'))
            if type(item['mode']) is not int or item['mode'] != MODES[path]:
                raise Rejected('Invalid payload mode')
            expected[path] = item['sha256']
        hashes(expected)
        payload = {path: read_file(self.stage / path, owners=owners) for path in MODES}
        if sum(map(len, payload.values())) > 26 * 1024 * 1024 or tree_hashes(payload) != expected:
            raise Rejected('Payload digest mismatch')
        return manifest, raw, payload, expected

    def run(self):
        try:
            # No implicit accepted state initialization, including on recovery.
            os.close(directory(self.state_path.parent, self.owner_uid, private=True))
            os.close(directory(self.checkpoints.parent, self.owner_uid))
            self.checkpoints.mkdir(mode=0o700, exist_ok=True)
            fd = directory(self.checkpoints, self.owner_uid, private=True)
            try:
                lock = os.open('lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                               0o600, dir_fd=fd)
                try:
                    info = os.fstat(lock)
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_uid != self.owner_uid
                            or stat.S_IMODE(info.st_mode) != 0o600):
                        raise Rejected('Unsafe controller lock')
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    return self._run_locked()
                finally:
                    os.close(lock)
            finally:
                os.close(fd)
        except (OSError, ValueError, TypeError) as exc:
            raise Rejected('Filesystem or schema validation failed') from exc

    def _run_locked(self):
        before = self.recover(self.read_state())
        original = tree(self.target, self.owner_uid)
        if tree_hashes(original) != before['files']:
            raise Rejected('Accepted tree drift')
        manifest, raw, payload, expected = self.staged()
        release = manifest['release_id']
        sha = digest(raw)
        if release < before['release_id']:
            raise Rejected('Release replay')
        if release == before['release_id']:
            if sha != before['manifest_sha256'] or expected != before['files']:
                raise Rejected('Release identity reused')
            self.services()
            return {'result': 'already_installed', 'release_id': release}
        if manifest['base'] != before['files']:
            raise Rejected('Signed base mismatch')
        after = {'schema': 1, 'release_id': release, 'manifest_sha256': sha, 'files': expected}
        if expected == before['files']:
            self.services()
            self.publish(after)
            return {'result': 'advanced', 'release_id': release}
        self.services()
        checkpoint = Path(tempfile.mkdtemp(prefix='release-', dir=self.checkpoints))
        os.chmod(checkpoint, 0o700)
        for path, data in original.items():
            atomic_write(checkpoint / Path(path).name, data, 0o600, self.owner_uid)
        atomic_write(checkpoint / 'accepted.json', encode(before), 0o600, self.owner_uid)
        journal = {'schema': 1, 'before': before, 'after': after, 'checkpoint': checkpoint.name}
        atomic_write(self.pending, encode(journal), 0o600, self.owner_uid)
        try:
            self.stop()
            self.install(payload)
            self.start()
            self.match(expected)
            self.publish(after)
        except Exception:
            self.rollback(before, original)
            raise
        self.clear_pending()
        return {'result': 'installed', 'release_id': release}


def interrupted(signum, frame):
    raise Rejected('Deployment interrupted')


def main():
    if len(sys.argv) != 1 or os.geteuid() != 0:
        print('Rejected: root execution without arguments required', file=sys.stderr)
        return 1
    os.umask(0o077)
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, interrupted)
    try:
        print(json.dumps(Deploy().run(), sort_keys=True))
        return 0
    except RollbackFailed:
        print('Rollback failed; journal retained for operator recovery', file=sys.stderr)
        return 2
    except Exception:
        print('Deployment rejected or failed; inspect controller state', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
