#!/usr/bin/python3 -I
"""Fixed noargs APK publication entrypoint; publisher code runs only after drop."""
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import types

STAGE = Path('/home/dwl/ai-control-android-publish-stage')
PUBLISHER = Path('/usr/local/lib/ai-control/publish-android-release.py')
HELPER = Path('/usr/local/sbin/ai-control-publish-android')
OWNER_UID = OWNER_GID = 1000
PANEL_UID, PANEL_GID = 993, 987
CERTIFICATE = 'baa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce'


def root_runtime():
    if (len(sys.argv) != 1 or not sys.flags.isolated or
            os.getuid() != 0 or os.geteuid() != 0 or
            any(k.startswith(('LD_', 'PYTHON')) for k in os.environ)):
        raise ValueError('Unsafe publication runtime')


def account_identity(name):
    if name not in ('root', 'dwl', 'ai-panel'):
        raise ValueError('Unknown account')
    entry = pwd.getpwnam(name)
    return entry.pw_uid, entry.pw_gid


def directory(path, owner=0, private=False):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Unsafe directory')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(path.parts[1:]):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            last = index == len(path.parts) - 2
            sticky = (not last and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
                      and Path(*path.parts[:index + 2]) in (Path('/tmp'), Path('/var/tmp')))
            if (info.st_uid not in ((owner,) if last else (0, owner)) or
                    (info.st_mode & 0o022 and not sticky) or
                    (last and private and stat.S_IMODE(info.st_mode) != 0o700)):
                raise ValueError('Unsafe directory')
        return fd
    except BaseException:
        os.close(fd)
        raise


def file_info(fd, uid, mode, limit, gid=None):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != uid or
            stat.S_IMODE(info.st_mode) != mode or info.st_size > limit or
            (gid is not None and info.st_gid != gid)):
        raise ValueError('Unsafe file')
    return info


def read_snapshot(parent, name, uid, mode, limit, gid=None):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = file_info(fd, uid, mode, limit, gid)
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise ValueError('Oversized file')
        if (os.fstat(fd) != before or
                os.stat(name, dir_fd=parent, follow_symlinks=False) != before):
            raise ValueError('File changed')
        return b''.join(chunks)
    finally:
        os.close(fd)


def validate_publisher_source():
    try:
        parent = directory(PUBLISHER.parent)
        try:
            return read_snapshot(parent, PUBLISHER.name, 0, 0o644, 2*1024*1024, 0)
        finally:
            os.close(parent)
    except OSError as exc:
        raise ValueError('Unsafe publisher') from exc


def parse_release(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate key')
            result[key] = value
        return result
    try:
        if type(raw) is not bytes or len(raw) > 16384:
            raise ValueError('Invalid release')
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid number')))
        if (type(value) is not dict or set(value) != {'schema','versionCode','versionName','sha256'} or
                type(value['schema']) is not int or value['schema'] != 1 or
                type(value['versionCode']) is not int or not 1 <= value['versionCode'] <= 2147483647 or
                type(value['versionName']) is not str or not 1 <= len(value['versionName']) <= 64 or
                not value['versionName'].isprintable() or type(value['sha256']) is not str or
                re.fullmatch('[0-9a-f]{64}', value['sha256']) is None):
            raise ValueError('Invalid release')
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError('Invalid release') from exc


def load_release(stage, owner_uid):
    try:
        parent = directory(stage, owner_uid, private=True)
        try:
            raw = read_snapshot(parent, 'release.json', owner_uid, 0o600, 16384)
            fd = os.open('release.apk', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                file_info(fd, owner_uid, 0o600, 128*1024*1024)
            finally:
                os.close(fd)
            return parse_release(raw)
        finally:
            os.close(parent)
    except OSError as exc:
        raise ValueError('Unsafe stage') from exc


def drop_privileges(uid, gid, panel_gid):
    os.setgroups([gid, panel_gid])
    os.setresgid(gid, gid, gid)
    os.setresuid(uid, uid, uid)
    if (os.getresuid() != (uid,)*3 or os.getresgid() != (gid,)*3 or
            set(os.getgroups()) != {gid, panel_gid}):
        raise ValueError('Privilege drop failed')


def load_publisher(sourcebytes):
    if (os.getresuid() != (OWNER_UID,)*3 or os.getresgid() != (OWNER_GID,)*3 or
            set(os.getgroups()) != {OWNER_GID, PANEL_GID}):
        raise ValueError('Publisher requires dropped identity')
    module = types.ModuleType('ai_control_frozen_publisher')
    module.__file__ = str(PUBLISHER)
    exec(compile(sourcebytes, str(PUBLISHER), 'exec'), module.__dict__)
    return module


def run():
    root_runtime()
    for name, expected in [('root',(0,0)), ('dwl',(OWNER_UID,OWNER_GID)), ('ai-panel',(PANEL_UID,PANEL_GID))]:
        if account_identity(name) != expected:
            raise ValueError('Account identity drift')
    source = validate_publisher_source()
    drop_privileges(OWNER_UID, OWNER_GID, PANEL_GID)
    os.chdir('/')
    os.umask(0o077)
    publisher = load_publisher(source)
    release = load_release(STAGE, OWNER_UID)
    return publisher.publish(STAGE/'release.apk', version_code=release['versionCode'],
                             version_name=release['versionName'], sha256=release['sha256'],
                             certificate_sha256=CERTIFICATE)


def main():
    if len(sys.argv) != 1:
        print('Publication refused', file=sys.stderr)
        return 1
    try:
        print(run())
        return 0
    except Exception:
        print('Publication refused', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
