#!/usr/bin/python3
"""Bounded deployment operation; production paths/pins are reviewed constants."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile

MAX_FILE = 2 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
ROOT_UID = ROOT_GID = 0

def account_identity(name):
    if name not in ('root', 'dwl', 'ai-panel'):
        raise ValueError('Unknown operation account')
    entry = pwd.getpwnam(name)
    return entry.pw_uid, entry.pw_gid

def optional_identity(name):
    try:
        return account_identity(name)
    except KeyError:
        return -1, -1

OWNER_UID, OWNER_GID = optional_identity('dwl')
PANEL_UID, PANEL_GID = optional_identity('ai-panel')

def run_command(argv, *, timeout=40):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
        cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C',
                     'JAVA_HOME': '/home/dwl/android-tools/jdk-17.0.20.1+1'})

TARGET = Path('/opt/ai-control-web')
STATE = Path('/var/lib/ai-control-deploy/accepted.json')
KEY = Path('/etc/ai-control-deploy/release-key.pem')
HELPER = Path('/usr/local/sbin/ai-control-deploy')
NEW_HELPER = Path('/home/dwl/ai-control-app-deploy16-helper.py')
# Same inode/path as the immutable accepted 4ead helper, not a new lock.
LOCK = Path('/var/lib/ai-control-deploy/checkpoints/lock')
PACKAGE_PENDING = Path('/var/lib/ai-control-deploy/checkpoints/pending.json')
BOOTSTRAP_MARKER = Path('/var/lib/ai-control-deploy/bootstrap-pending.json')
BOOTSTRAP_CHECKPOINTS = Path('/var/lib/ai-control-deploy/bootstrap-checkpoints')
CONFIG_MARKER = Path('/var/lib/ai-control-deploy/config-pending.json')
CONFIG_CHECKPOINTS = Path('/var/lib/ai-control-deploy/config-checkpoints')
AUTH_CONFIG = Path('/var/lib/ai-control-web/auth.json')
AUTH_DB = Path('/var/lib/ai-control-web/android-auth/device-grants.sqlite3')
CATALOG_ROOT = Path('/srv/ai-control-download')
CATALOG = Path('/srv/ai-control-download/android')
FEED = CATALOG / 'version.json'
PUBLISH_LOCK = CATALOG / '.publish.lock'
PUBLICATION_PROOFS = Path('/home/dwl/.local/state/ai-control-android/publication')
EXPECTED_OLD_HELPER_SHA256 = '4eadf6d37d597e9ba7034fe6b86b696d7f75735b5c47ce0aa3a2d249b277eaa9'
EXPECTED_KEY_SHA256 = '191cbdb3eee39ce8b8094e5d5bf1dd8281e8b9ad993dc4557402e1a10c11ae55'
# Fail closed until bound by the checksum-pinned, independently reviewed packet.
EXPECTED_NEW_HELPER_SHA256 = None
EXPECTED_ACCEPTED_SHA256 = None
EXPECTED_AUTH_SHA256 = None
SERVICES = ('ai-control-web.service', 'ai-control-web-broker.service')
LEGACY_MODES = {'bin/ai-control-web': 493, 'bin/_control_web.py': 420, 'bin/_control_web_broker.py': 420, 'bin/_control_web_sessions.py': 420, 'bin/_codex_rc.py': 420, 'bin/_rc_projects.sh': 493, 'bin/_control_web.html': 420, 'bin/_control_web.css': 420, 'bin/_control_web.js': 420, 'requirements-web.lock': 420, 'systemd/ai-control-web.service.tmpl': 420, 'systemd/ai-control-web-broker.service.tmpl': 420, 'bin/_control_web.svg': 420}
CURRENT_MODES = {**LEGACY_MODES, "bin/_control_web_configured_create.py": 0o644}
APP_LEAVES = ("bin/_control_web_android_auth.py", "bin/_control_web_android_download.py")
def digest(data):
    return hashlib.sha256(data).hexdigest()




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
                allowed = (0, owner_uid)
                sticky_temp = (not last and info.st_uid == 0
                               and stat.S_ISVTX & info.st_mode
                               and Path(*path.parts[:index + 2]) in
                               (Path('/tmp'), Path('/var/tmp')))
                if info.st_uid not in allowed or (info.st_mode & 0o022 and not sticky_temp):
                    raise ValueError('Unsafe directory')
                if last and private and stat.S_IMODE(info.st_mode) != 0o700:
                    raise ValueError('Controller directory is not private')
        return fd
    except BaseException:
        os.close(fd)
        raise






def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid JSON') from exc


def keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('Unexpected schema keys')


def integer(value, minimum):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ValueError('Invalid release identity')


def pin(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('Reviewed pin missing or invalid')
    return value

def identities(root=True):
    if os.geteuid() != (ROOT_UID if root else OWNER_UID):
        raise ValueError('Wrong operation identity')
    for name, expected in (('root', (ROOT_UID, ROOT_GID)),
                           ('dwl', (OWNER_UID, OWNER_GID)),
                           ('ai-panel', (PANEL_UID, PANEL_GID))):
        if account_identity(name) != expected or min(expected) < 0:
            raise ValueError('Account identity drift')

def snapshot(path, uid, mode, limit=MAX_FILE, gid=None):
    parent = directory(Path(path).parent, uid)
    try:
        fd = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid != uid or stat.S_IMODE(info.st_mode) != mode or
                (gid is not None and info.st_gid != gid) or info.st_size > limit):
                raise ValueError('File metadata drift')
            chunks, total = [], 0
            while True:
                chunk = os.read(fd, min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limit:
                    raise ValueError('Oversized snapshot')
            fresh = os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)
            if fresh != os.fstat(fd) or fresh != info:
                raise ValueError('Snapshot identity drift')
            return b''.join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def write(path, raw, mode, uid, gid):
    # Own atomic primitive also sets an explicit group (catalog ai-panel).
    parent = directory(Path(path).parent, uid)
    name = '.operation-' + os.urandom(16).hex()
    fd = None
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as out:
            fd = None
            out.write(raw)
            out.flush()
            os.fchmod(out.fileno(), mode)
            os.fchown(out.fileno(), uid, gid)
            os.fsync(out.fileno())
        os.replace(name, Path(path).name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(name, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)

def sync_dir(path, uid):
    fd = directory(path, uid)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def ensure_dir(path, uid, gid, mode):
    path = Path(path)
    parent = directory(path.parent, uid)
    try:
        try:
            os.mkdir(path.name, mode=mode, dir_fd=parent)
            child = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                os.fchown(child, uid, gid)
                os.fchmod(child, mode)
                os.fsync(child)
            finally:
                os.close(child)
            os.fsync(parent)
        except FileExistsError:
            pass
        child = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(child)
            if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode):
                raise ValueError('Directory metadata drift')
        finally:
            os.close(child)
    finally:
        os.close(parent)

def clear(path, uid, expected):
    parent = directory(Path(path).parent, uid)
    try:
        if snapshot(path, uid, 0o600) != expected:
            raise ValueError('Marker changed')
        os.unlink(Path(path).name, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)

@contextlib.contextmanager
def locked(path, uid, gid):
    parent = directory(Path(path).parent, uid)
    fd = None
    try:
        try:
            fd = os.open(Path(path).name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                         0o600, dir_fd=parent)
            os.fchown(fd, uid, gid)
            os.fsync(fd)
            os.fsync(parent)
        except FileExistsError:
            fd = os.open(Path(path).name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, 0o600)):
            raise ValueError('Unsafe operation lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)

def absent(path, uid):
    parent = directory(Path(path).parent, uid)
    try:
        try:
            os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise ValueError('Unexpected leaf')
    finally:
        os.close(parent)

def reject_pending(*paths):
    if any(os.path.lexists(p) for p in paths):
        raise ValueError('Other operation pending')

def accepted14():
    ensure_dir_existing(STATE.parent, ROOT_UID, ROOT_GID, 0o700)
    raw = snapshot(STATE, ROOT_UID, 0o600, MAX_MANIFEST, ROOT_GID)
    if digest(raw) != pin(EXPECTED_ACCEPTED_SHA256):
        raise ValueError('Accepted state drift')
    value = decode(raw)
    keys(value, ('schema', 'release_id', 'manifest_sha256', 'files'))
    if type(value['schema']) is not int or value['schema'] != 2:
        raise ValueError('Expected accepted14')
    integer(value['release_id'], 1)
    pin(value['manifest_sha256'])
    keys(value['files'], CURRENT_MODES)
    for leaf, mode in CURRENT_MODES.items():
        if digest(snapshot(TARGET / leaf, ROOT_UID, mode, gid=ROOT_GID)) != pin(value['files'][leaf]):
            raise ValueError('Accepted tree drift')
    for leaf in APP_LEAVES:
        absent(TARGET / leaf, ROOT_UID)
    return raw

def marker(path):
    raw = snapshot(path, ROOT_UID, 0o600, MAX_MANIFEST, ROOT_GID)
    value = decode(raw)
    keys(value, ('schema', 'checkpoint', 'before_sha256', 'after_sha256', 'accepted_sha256'))
    if type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Unknown marker schema')
    if type(value['checkpoint']) is not str or re.fullmatch('[A-Za-z0-9_-]{1,128}', value['checkpoint']) is None:
        raise ValueError('Invalid checkpoint basename')
    for name in ('before_sha256', 'after_sha256', 'accepted_sha256'):
        pin(value[name])
    if value['accepted_sha256'] != pin(EXPECTED_ACCEPTED_SHA256):
        raise ValueError('Marker accepted mismatch')
    return raw, value

def checkpoint(root, filename, before, metadata, uid, gid):
    ensure_dir(root, ROOT_UID, ROOT_GID, 0o700)
    path = Path(tempfile.mkdtemp(prefix='operation-', dir=root))
    os.chmod(path, 0o700)
    os.chown(path, ROOT_UID, ROOT_GID)
    write(path / filename, before, 0o600, uid, gid)
    write(path / 'metadata.json', encode(metadata), 0o600, ROOT_UID, ROOT_GID)
    sync_dir(path, ROOT_UID)
    sync_dir(root, ROOT_UID)
    return path

def checked_checkpoint(root, value, filename, uid, gid):
    path = root / value['checkpoint']
    ensure_dir_existing(path, ROOT_UID, ROOT_GID, 0o700)
    meta = decode(snapshot(path / 'metadata.json', ROOT_UID, 0o600, MAX_MANIFEST, ROOT_GID))
    keys(meta, ('schema', 'before_sha256', 'after_sha256', 'accepted_sha256'))
    if meta != {k:v for k,v in value.items() if k != 'checkpoint'}:
        raise ValueError('Checkpoint metadata mismatch')
    before = snapshot(path / filename, uid, 0o600, gid=gid)
    if digest(before) != value['before_sha256']:
        raise ValueError('Checkpoint digest mismatch')
    return before

def ensure_dir_existing(path, uid, gid, mode):
    fd = directory(path, uid)
    try:
        info = os.fstat(fd)
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode):
            raise ValueError('Directory metadata drift')
    finally:
        os.close(fd)






def entry(operation):
    if len(sys.argv) != 1:
        return 1
    os.umask(0o077)
    try:
        operation()
        return 0
    except Exception:
        print('Operation refused; retained private evidence requires review', file=sys.stderr)
        return 1

def bootstrap():
    try:
        identities()
        with locked(LOCK, ROOT_UID, ROOT_GID):
            reject_pending(PACKAGE_PENDING, CONFIG_MARKER)
            accepted14()
            if digest(snapshot(KEY, ROOT_UID, 0o644, MAX_MANIFEST, ROOT_GID)) != pin(EXPECTED_KEY_SHA256):
                raise ValueError('Trust key drift')
            new = snapshot(NEW_HELPER, OWNER_UID, 0o755, gid=OWNER_GID)
            if digest(new) != pin(EXPECTED_NEW_HELPER_SHA256):
                raise ValueError('New helper pin mismatch')
            current = snapshot(HELPER, ROOT_UID, 0o755, gid=ROOT_GID)
            if digest(current) not in (pin(EXPECTED_OLD_HELPER_SHA256), EXPECTED_NEW_HELPER_SHA256):
                raise ValueError('Unknown installed helper')
            if os.path.lexists(BOOTSTRAP_MARKER):
                raw, value = marker(BOOTSTRAP_MARKER)
                if (value['before_sha256'], value['after_sha256']) != (EXPECTED_OLD_HELPER_SHA256, EXPECTED_NEW_HELPER_SHA256):
                    raise ValueError('Bootstrap marker pins mismatch')
                checked_checkpoint(BOOTSTRAP_CHECKPOINTS, value, 'helper.before', ROOT_UID, ROOT_GID)
            elif digest(current) == EXPECTED_NEW_HELPER_SHA256:
                return None
            else:
                value = dict(schema=1, before_sha256=EXPECTED_OLD_HELPER_SHA256,
                    after_sha256=EXPECTED_NEW_HELPER_SHA256, accepted_sha256=EXPECTED_ACCEPTED_SHA256)
                proof = checkpoint(BOOTSTRAP_CHECKPOINTS, 'helper.before', current, value, ROOT_UID, ROOT_GID)
                value['checkpoint'] = proof.name
                raw = encode(value)
                write(BOOTSTRAP_MARKER, raw, 0o600, ROOT_UID, ROOT_GID)
            # Reread fixed state/key/helper before replacement, not owner candidate.
            accepted14()
            if snapshot(HELPER, ROOT_UID, 0o755, gid=ROOT_GID) != current:
                raise ValueError('Helper changed during bootstrap')
            write(HELPER, new, 0o755, ROOT_UID, ROOT_GID)
            if snapshot(HELPER, ROOT_UID, 0o755, gid=ROOT_GID) != new:
                raise ValueError('Replacement verification failed')
            clear(BOOTSTRAP_MARKER, ROOT_UID, raw)
            return None
    except (OSError, TypeError, subprocess.SubprocessError) as exc:
        raise ValueError('Bootstrap refused') from exc

if __name__ == '__main__':
    sys.exit(entry(bootstrap))
