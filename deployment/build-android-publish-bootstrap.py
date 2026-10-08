#!/usr/bin/python3
"""Owner-side generator: embed reviewed bytes in a fixed-scope bootstrap packet."""
import argparse
import base64
import hashlib
from pathlib import Path

TEMPLATE = r'''#!/usr/bin/python3 -I
"""One-time reviewed APK publisher installation. No owner paths are inputs."""
import base64
import hashlib
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tempfile

HELPER = Path('/usr/local/sbin/ai-control-publish-android')
PUBLISHER = Path('/usr/local/lib/ai-control/publish-android-release.py')
SUDOERS = Path('/etc/sudoers.d/ai-control-android-publish')
RULE = b'dwl ALL=(root) NOPASSWD: /usr/local/sbin/ai-control-publish-android ""\n'
HELPER_DATA = @HELPER_DATA@
HELPER_SHA256 = @HELPER_SHA256@
PUBLISHER_DATA = @PUBLISHER_DATA@
PUBLISHER_SHA256 = @PUBLISHER_SHA256@


def root_runtime():
    if (len(sys.argv) != 1 or not sys.flags.isolated or os.getuid() != 0 or
            os.geteuid() != 0 or any(k.startswith(('LD_', 'PYTHON')) for k in os.environ)):
        raise ValueError('Unsafe bootstrap runtime')
    for name, ids in [('root',(0,0)),('dwl',(1000,1000)),('ai-panel',(993,987))]:
        entry = pwd.getpwnam(name)
        if (entry.pw_uid, entry.pw_gid) != ids:
            raise ValueError('Account identity drift')


def parent_fd(path, create=False):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(path.parent.parts[1:]):
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                missing = Path(*path.parent.parts[:index+2])
                if missing != Path('/usr/local/lib/ai-control'):
                    raise
                if not create:
                    os.close(fd)
                    return None
                os.mkdir(part, 0o755, dir_fd=fd)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.fchmod(child, 0o755)
                os.fchown(child, 0, 0)
                os.fsync(child)
                os.fsync(fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
                raise ValueError('Unsafe install directory')
        return fd
    except BaseException:
        os.close(fd)
        raise


def stable_metadata(info):
    # Access time can advance on a valid read; identity/content metadata cannot.
    return tuple(getattr(info, field) for field in (
        'st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
        'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def validate_existing(path, raw, mode):
    parent = parent_fd(path)
    if parent is None:
        return
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            return
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_uid != 0 or info.st_gid != 0 or
                    stat.S_IMODE(info.st_mode) != mode or info.st_size != len(raw)):
                raise ValueError('Unknown installation collision')
            chunks, total = [], 0
            while True:
                chunk = os.read(fd, min(65536, len(raw)+1-total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > len(raw):
                    raise ValueError('Installation changed')
            if (b''.join(chunks) != raw or stable_metadata(os.fstat(fd)) != stable_metadata(info) or
                    stable_metadata(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != stable_metadata(info)):
                raise ValueError('Unknown installation collision')
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def validate_sudoers(candidate):
    tool = Path('/usr/sbin/visudo')
    parent = parent_fd(tool)
    try:
        fd = os.open(tool.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                    info.st_gid != 0 or info.st_mode & 0o022):
                raise ValueError('Unsafe visudo')
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    runtime_parent = parent_fd(Path('/run/placeholder'))
    os.close(runtime_parent)
    with tempfile.TemporaryDirectory(prefix='ai-control-apk-bootstrap-', dir='/run') as directory:
        path = Path(directory)/'sudoers'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        result = subprocess.run([str(tool), '-c', '-f', str(path)], cwd='/',
                                env={'PATH':'/usr/sbin:/usr/bin:/bin','LANG':'C'},
                                capture_output=True, timeout=20)
        if result.returncode != 0:
            raise ValueError('Invalid sudoers')


def atomic_install(path, raw, mode):
    validate_existing(path, raw, mode)
    parent = parent_fd(path, create=True)
    name = '.android-bootstrap-'+os.urandom(16).hex()
    fd = None
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write(raw)
            stream.flush()
            os.fchown(stream.fileno(), 0, 0)
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
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


def bootstrap():
    root_runtime()
    os.chdir('/')
    os.umask(0o077)
    helper = base64.b64decode(HELPER_DATA, validate=True)
    publisher = base64.b64decode(PUBLISHER_DATA, validate=True)
    if (hashlib.sha256(helper).hexdigest() != HELPER_SHA256 or
            hashlib.sha256(publisher).hexdigest() != PUBLISHER_SHA256):
        raise ValueError('Embedded checksum mismatch')
    for path, raw, mode in [(HELPER,helper,0o755),(PUBLISHER,publisher,0o644),(SUDOERS,RULE,0o440)]:
        validate_existing(path, raw, mode)
    validate_sudoers(RULE)
    atomic_install(HELPER, helper, 0o755)
    atomic_install(PUBLISHER, publisher, 0o644)
    atomic_install(SUDOERS, RULE, 0o440)


def main():
    try:
        bootstrap()
        print('APK publisher bootstrap installed')
        return 0
    except Exception:
        print('APK publisher bootstrap refused', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
'''


def build_packet(helper_source, publisher_source):
    for raw in (helper_source, publisher_source):
        if type(raw) is not bytes or not 0 < len(raw) <= 2*1024*1024:
            raise ValueError('Invalid reviewed input')
    source = TEMPLATE
    for prefix, raw in [('HELPER',helper_source),('PUBLISHER',publisher_source)]:
        source = source.replace('@'+prefix+'_DATA@', repr(base64.b64encode(raw)))
        source = source.replace('@'+prefix+'_SHA256@', repr(hashlib.sha256(raw).hexdigest()))
    return source.encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    packet = build_packet((root/'ai-control-android-publish.py').read_bytes(),
                          (root/'publish-android-release.py').read_bytes())
    with args.output.open('xb') as stream:
        stream.write(packet)
    print(hashlib.sha256(packet).hexdigest())


if __name__ == '__main__':
    main()
