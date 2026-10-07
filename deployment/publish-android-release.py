#!/usr/bin/python3
"""Bounded deployment operation; production paths/pins are reviewed constants."""
import ctypes
import errno
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
                allowed = (owner_uid,) if last else (0, owner_uid)
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
            if fresh != os.fstat(fd) or any(getattr(fresh, field) != getattr(info, field)
                    for field in ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
                                  'st_size', 'st_mtime_ns', 'st_ctime_ns')):
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



def ensure_dir_existing(path, uid, gid, mode):
    fd = directory(path, uid)
    try:
        info = os.fstat(fd)
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode):
            raise ValueError('Directory metadata drift')
    finally:
        os.close(fd)

PACKAGE_ID = 'ru.dewil.aicontrol'
DOWNLOAD_ORIGIN = 'https://llm-web.dewil.ru:18443'
EXPECTED_CERTIFICATE_SHA256 = 'baa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce'
AAPT = Path('/home/dwl/android-tools/sdk/build-tools/36.0.0/aapt2')
APKSIGNER = Path('/home/dwl/android-tools/sdk/build-tools/36.0.0/apksigner')
MAX_APK = 128 * 1024 * 1024
MAX_FEED = 16 * 1024


def feed_value(raw):
    if len(raw) > MAX_FEED:
        raise ValueError('Oversized feed')
    value = decode(raw)
    keys(value, ('versionCode', 'versionName', 'apkUrl', 'sha256'))
    code = value['versionCode']
    if type(code) is not int or not 1 <= code <= 2147483647:
        raise ValueError('Invalid APK versionCode')
    name = value['versionName']
    if type(name) is not str or not 1 <= len(name) <= 64 or any(ord(x) < 32 for x in name):
        raise ValueError('Invalid APK versionName')
    pin(value['sha256'])
    if value['apkUrl'] != DOWNLOAD_ORIGIN + '/download/android/ai-control-' + str(code) + '.apk':
        raise ValueError('Invalid APK URL')
    return value


def catalog():
    ensure_dir_existing(CATALOG_ROOT, ROOT_UID, ROOT_GID, 0o755)
    ensure_dir_existing(CATALOG, OWNER_UID, PANEL_GID, 0o750)
    ensure_dir_existing(PUBLICATION_PROOFS, OWNER_UID, OWNER_GID, 0o700)
    if FEED.parent != CATALOG or PUBLISH_LOCK.parent != CATALOG:
        raise ValueError('Catalog path mismatch')


def current_feed():
    try:
        return snapshot(FEED, OWNER_UID, 0o640, MAX_FEED, PANEL_GID)
    except FileNotFoundError:
        return None


def apk_metadata(path, value):
    try:
        badging = run_command([str(AAPT), 'dump', 'badging', str(path)], timeout=40)
        signer = run_command([str(APKSIGNER), 'verify', '--verbose', '--print-certs', str(path)], timeout=40)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('APK verification tool failed') from exc
    if badging.returncode != 0 or signer.returncode != 0:
        raise ValueError('APK verification failed')
    lines = re.findall(r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'", badging.stdout, re.M)
    if lines != [(PACKAGE_ID, str(value['versionCode']), value['versionName'])]:
        raise ValueError('APK package/version metadata mismatch')
    certificates = re.findall(r'^Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-fA-F]{64})\s*$', signer.stdout, re.M)
    if [c.lower() for c in certificates] != [pin(EXPECTED_CERTIFICATE_SHA256)]:
        raise ValueError('APK certificate mismatch')
    # aapt2 uses minSdkVersion; older aapt uses sdkVersion. Neither label
    # changes the package/code/certificate trust checked by this publisher.


def verified_apk(path, value):
    raw = snapshot(path, OWNER_UID, 0o640, MAX_APK, PANEL_GID)
    if digest(raw) != value['sha256']:
        raise ValueError('Retained APK digest mismatch')
    apk_metadata(path, value)
    if snapshot(path, OWNER_UID, 0o640, MAX_APK, PANEL_GID) != raw:
        raise ValueError('APK changed during tool verification')
    return raw


def final_path(value):
    return CATALOG / ('ai-control-' + str(value['versionCode']) + '.apk')


def retain_apk(raw, value):
    destination = final_path(value)
    if os.path.lexists(destination):
        if verified_apk(destination, value) != raw:
            raise ValueError('Immutable APK collision')
        return
    # Exclusive final-name creation never overwrites a concurrent immutable
    # object. A private temp snapshot is already verified before this copy.
    parent = directory(CATALOG, OWNER_UID)
    name = '.apk-' + os.urandom(16).hex()
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as out:
            out.write(raw)
            out.flush()
            os.fchmod(out.fileno(), 0o640)
            os.fchown(out.fileno(), OWNER_UID, PANEL_GID)
            os.fsync(out.fileno())
        # Linux renameat2 provides an atomic no-overwrite final-name commit;
        # no retained hardlink or partial final APK exists at a kill boundary.
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameat2
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        if rename(parent, os.fsencode(name), parent, os.fsencode(destination.name), 1) != 0:
            raise OSError(ctypes.get_errno(), 'Immutable APK rename refused')
        os.fsync(parent)
    finally:
        try:
            os.unlink(name, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)
    if verified_apk(destination, value) != raw:
        raise ValueError('Immutable APK verification failed')


def retain_proof(before, after, value, apk_size):
    path = Path(tempfile.mkdtemp(prefix='publication-', dir=PUBLICATION_PROOFS))
    os.chmod(path, 0o700)
    os.chown(path, OWNER_UID, OWNER_GID)
    metadata = dict(schema=1, before_sha256=digest(before) if before is not None else None,
                    after_sha256=digest(after), apk_sha256=value['sha256'],
                    package=PACKAGE_ID, certificate_sha256=EXPECTED_CERTIFICATE_SHA256,
                    version_code=value['versionCode'], apk_size=apk_size)
    if before is not None:
        write(path / 'feed.before', before, 0o600, OWNER_UID, OWNER_GID)
    write(path / 'feed.after', after, 0o600, OWNER_UID, OWNER_GID)
    write(path / 'metadata.json', encode(metadata), 0o600, OWNER_UID, OWNER_GID)
    sync_dir(path, OWNER_UID)
    sync_dir(PUBLICATION_PROOFS, OWNER_UID)
    return path.name


def publish(apk_path, *, version_code, version_name, sha256, certificate_sha256):
    try:
        identities(root=False)
        if certificate_sha256 != pin(EXPECTED_CERTIFICATE_SHA256):
            raise ValueError('Caller certificate is not authority')
        value = dict(versionCode=version_code, versionName=version_name,
                     apkUrl=DOWNLOAD_ORIGIN + '/download/android/ai-control-' + str(version_code) + '.apk', sha256=sha256)
        after = encode(value)
        feed_value(after)
        catalog()
        with locked(PUBLISH_LOCK, OWNER_UID, PANEL_GID):
            before = current_feed()
            if before is not None:
                old = feed_value(before)
                verified_apk(final_path(old), old)
                if version_code < old['versionCode'] or (version_code == old['versionCode'] and before != after):
                    raise ValueError('Nonmonotone publication')
            # Owner input is read once; tool verification uses private immutable
            # copy of those bytes, never reopens the supplied source path.
            input_path = Path(apk_path)
            parent = directory(input_path.parent, OWNER_UID)
            try:
                fd = os.open(input_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    info = os.fstat(fd)
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != OWNER_UID or
                        info.st_mode & 0o022 or info.st_size > MAX_APK):
                        raise ValueError('Unsafe input APK')
                    with os.fdopen(os.dup(fd), 'rb') as inp:
                        raw = inp.read(MAX_APK + 1)
                    if len(raw) > MAX_APK or digest(raw) != sha256:
                        raise ValueError('Input APK digest mismatch')
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
            with tempfile.TemporaryDirectory(prefix='verify-', dir=PUBLICATION_PROOFS) as tmp:
                temp = Path(tmp) / 'release.apk'
                write(temp, raw, 0o640, OWNER_UID, PANEL_GID)
                verified_apk(temp, value)
            retain_apk(raw, value)
            proof = retain_proof(before, after, value, len(raw))
            if current_feed() != before:
                raise ValueError('Feed predecessor changed')
            verified_apk(final_path(value), value)
            if before is not None and value == feed_value(before):
                return proof
            write(FEED, after, 0o640, OWNER_UID, PANEL_GID)
            if current_feed() != after:
                raise ValueError('Published feed drift')
            verified_apk(final_path(value), value)
            return proof
    except (OSError, TypeError, subprocess.SubprocessError) as exc:
        raise ValueError('Publication refused; retained evidence preserved') from exc


def rollback(expected_current_digest, predecessor_proof_id):
    try:
        identities(root=False)
        pin(expected_current_digest)
        if type(predecessor_proof_id) is not str or re.fullmatch('publication-[A-Za-z0-9_-]{1,128}', predecessor_proof_id) is None:
            raise ValueError('Invalid publication proof basename')
        catalog()
        with locked(PUBLISH_LOCK, OWNER_UID, PANEL_GID):
            proof = PUBLICATION_PROOFS / predecessor_proof_id
            ensure_dir_existing(proof, OWNER_UID, OWNER_GID, 0o700)
            metadata = decode(snapshot(proof / 'metadata.json', OWNER_UID, 0o600, MAX_FEED, OWNER_GID))
            keys(metadata, ('schema', 'before_sha256', 'after_sha256', 'apk_sha256', 'package', 'certificate_sha256', 'version_code', 'apk_size'))
            if type(metadata['schema']) is not int or metadata['schema'] != 1 or metadata['after_sha256'] != expected_current_digest:
                raise ValueError('Publication proof mismatch')
            after = snapshot(proof / 'feed.after', OWNER_UID, 0o600, MAX_FEED, OWNER_GID)
            after_value = feed_value(after)
            if (digest(after) != expected_current_digest or metadata['apk_sha256'] != after_value['sha256'] or
                metadata['package'] != PACKAGE_ID or metadata['certificate_sha256'] != pin(EXPECTED_CERTIFICATE_SHA256) or
                type(metadata['version_code']) is not int or metadata['version_code'] != after_value['versionCode']):
                raise ValueError('Unverified publication proof')
            retained = verified_apk(final_path(after_value), after_value)
            if type(metadata['apk_size']) is not int or metadata['apk_size'] != len(retained):
                raise ValueError('Publication size proof mismatch')
            if metadata['before_sha256'] is None:
                absent(proof / 'feed.before', OWNER_UID)
                before = None
            else:
                pin(metadata['before_sha256'])
                before = snapshot(proof / 'feed.before', OWNER_UID, 0o600, MAX_FEED, OWNER_GID)
                if digest(before) != metadata['before_sha256']:
                    raise ValueError('Predecessor proof mismatch')
                old = feed_value(before)
                verified_apk(final_path(old), old)
            current = current_feed()
            if current == before:
                return None
            if current != after or digest(current) != expected_current_digest:
                raise ValueError('Stale rollback proof')
            if before is None:
                parent = directory(CATALOG, OWNER_UID)
                try:
                    if current_feed() != after:
                        raise ValueError('Feed changed during rollback')
                    os.unlink(FEED.name, dir_fd=parent)
                    os.fsync(parent)
                finally:
                    os.close(parent)
            else:
                write(FEED, before, 0o640, OWNER_UID, PANEL_GID)
            if current_feed() != before:
                raise ValueError('Rollback feed drift')
            return None
    except (OSError, TypeError, subprocess.SubprocessError) as exc:
        raise ValueError('Rollback refused; retained evidence preserved') from exc


def main():
    # Destination, identities and pins have no CLI/env override. An explicit
    # rollback names a retained transaction and its whole-current-feed digest.
    import argparse
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest='operation', required=True)
    publication = modes.add_parser('publish')
    publication.add_argument('apk')
    publication.add_argument('--version-code', type=int, required=True)
    publication.add_argument('--version-name', required=True)
    publication.add_argument('--sha256', required=True)
    publication.add_argument('--certificate-sha256', required=True)
    restore = modes.add_parser('rollback')
    restore.add_argument('expected_current_digest')
    restore.add_argument('predecessor_proof_id')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.operation == 'publish':
            print(publish(args.apk, version_code=args.version_code, version_name=args.version_name,
                          sha256=args.sha256, certificate_sha256=args.certificate_sha256))
        else:
            rollback(args.expected_current_digest, args.predecessor_proof_id)
        return 0
    except Exception:
        print('Publication refused; retained evidence requires review', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
