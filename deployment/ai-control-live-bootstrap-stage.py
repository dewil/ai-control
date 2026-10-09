#!/usr/bin/python3
"""Immutable fixed-path packet transport; unbound production values fail closed."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import types

MAX_FILE = 2 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
WHEEL_SHA256 = '132a8e4b646ad058c7b242b7161621832ee8737ca6f6cbd47dcb6d3ad09490ed'
WHEEL_SIZE = 82408
WHEEL_INVENTORY_SHA256 = '40b35159d50cf2bf0f645f5ab1564f5a3fd0efcee266405fffeb6a496dc7bb43'

def digest(data):
    return hashlib.sha256(data).hexdigest()

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
        raise ValueError('Reviewed pin missing')
    return value

def strict_blob(value, maximum):
    if type(value) is not str or len(value) > 4 * ((maximum + 2) // 3):
        raise ValueError('Invalid embedded blob')
    try:
        data = base64.b64decode(value.encode('ascii'), validate=True)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid embedded blob') from exc
    if not data or len(data) > maximum or base64.b64encode(data).decode('ascii') != value:
        raise ValueError('Noncanonical embedded blob')
    return data

def manifest_value(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_MANIFEST:
        raise ValueError('Invalid manifest snapshot')
    value = decode(raw)
    keys(value, ('schema', 'bootstrap', 'helper', 'wheel', 'unit_before', 'unit_after'))
    if type(value['schema']) is not int or value['schema'] != 1 or encode(value) != raw:
        raise ValueError('Noncanonical manifest')
    for name, maximum in (('bootstrap', 4194304), ('helper', 1048576), ('wheel', 82408),
                          ('unit_before', 65536), ('unit_after', 65536)):
        keys(value[name], ('sha256', 'size'))
        pin(value[name]['sha256'])
        if type(value[name]['size']) is not int or not 0 < value[name]['size'] <= maximum:
            raise ValueError('Invalid manifest size')
    if value['wheel'] != {'sha256': WHEEL_SHA256, 'size': WHEEL_SIZE}:
        raise ValueError('Manifest wheel mismatch')
    return value

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
                if info.st_gid != 0 or info.st_uid not in allowed or (info.st_mode & 0o022):
                    raise ValueError('Unsafe directory')
                if last and private and stat.S_IMODE(info.st_mode) != 0o700:
                    raise ValueError('Controller directory is not private')
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
                    or (owners == (0,) and info.st_gid != 0)
                    or info.st_size > limit
                    or (mode is not None and stat.S_IMODE(info.st_mode) != mode)):
                raise ValueError('Unsafe or oversized file')
            chunks = []
            total = 0
            while True:
                chunk = os.read(child, min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limit:
                    raise ValueError('Oversized snapshot')
            fresh = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
                      'st_size', 'st_mtime_ns', 'st_ctime_ns')
            if any(getattr(info, field) != getattr(value, field)
                   for value in (os.fstat(child), fresh) for field in fields):
                raise ValueError('Snapshot changed')
            return b''.join(chunks)
        finally:
            os.close(child)
    finally:
        os.close(fd)

def isolated():
    if (len(sys.argv) != 1 or sys.argv[0] != '-' or
            any(call() != 0 for call in (os.getuid, os.geteuid, os.getgid, os.getegid)) or
            any(name.startswith(('PYTHON', 'LD_')) for name in os.environ)):
        raise ValueError('Isolated root stdin execution required')


def packet_files():
    parent = directory(STAGE, 0, private=True)
    try:
        if set(os.listdir(parent)) != {'wrapper.py', 'manifest.json', 'bootstrap.py'}:
            raise ValueError('Foreign or partial packet stage')
        return {name: read_file(STAGE / name, owners=(0,), mode=0o600, limit=maximum, private_parent=True)
                for name, maximum in (('wrapper.py', 2097152), ('manifest.json', 65536), ('bootstrap.py', 4194304))}
    finally:
        os.close(parent)


STAGE = Path('/var/lib/ai-control-deploy/live-bootstrap-packet')
WRAPPER_B64 = None
MANIFEST_B64 = None
BOOTSTRAP_B64 = None
WRAPPER_SHA256 = None
MANIFEST_SHA256 = None
BOOTSTRAP_SHA256 = None
WRAPPER_SIZE = None
MANIFEST_SIZE = None
BOOTSTRAP_SIZE = None


def stage():
    try:
        isolated()
        began = time.monotonic()
        payload = {}
        for prefix, name, maximum in (('WRAPPER', 'wrapper.py', 2097152), ('MANIFEST', 'manifest.json', 65536),
                                      ('BOOTSTRAP', 'bootstrap.py', 4194304)):
            expected_sha = pin(globals()[prefix + '_SHA256'])
            size = globals()[prefix + '_SIZE']
            if type(size) is not int or not 0 < size <= maximum:
                raise ValueError('Invalid packet stage size')
            raw = strict_blob(globals()[prefix + '_B64'], maximum)
            if len(raw) != size or digest(raw) != expected_sha:
                raise ValueError('Packet stage binding mismatch')
            payload[name] = raw
        if sum(map(len, payload.values())) > 6356992:
            raise ValueError('Packet stage oversized')
        parent = directory(STAGE.parent, 0)
        try:
            try:
                os.stat(STAGE.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                os.mkdir(STAGE.name, 0o700, dir_fd=parent)
                stage_fd = directory(STAGE, 0, private=True)
                try:
                    for name, raw in payload.items():
                        if time.monotonic() - began > 120:
                            raise ValueError('Stage budget exhausted')
                        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=stage_fd)
                        try:
                            if (os.fstat(fd).st_uid, os.fstat(fd).st_gid) != (0, 0):
                                os.fchown(fd, 0, 0)
                            remaining = memoryview(raw)
                            while remaining:
                                count = os.write(fd, remaining)
                                if count <= 0:
                                    raise ValueError('Incomplete stage write')
                                remaining = remaining[count:]
                            os.fchmod(fd, 0o600)
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                    os.fsync(stage_fd)
                    os.fsync(parent)
                finally:
                    os.close(stage_fd)
            if packet_files() != payload:
                raise ValueError('Existing packet differs')
            # Exact reuse is read-only, with durable file/directory/parent proof.
            stage_fd = directory(STAGE, 0, private=True)
            try:
                for name in payload:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=stage_fd)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                os.fsync(stage_fd)
                os.fsync(parent)
            finally:
                os.close(stage_fd)
            if time.monotonic() - began > 120:
                raise ValueError('Stage budget exhausted')
            return 0
        finally:
            os.close(parent)
    except Exception:
        return 1


if __name__ == '__main__':
    sys.exit(stage())
