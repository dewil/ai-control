#!/usr/bin/python3
"""One fixed offline bootstrap transaction. Unbound production packets refuse."""
import ast
import base64
import contextlib
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import time
import zipfile

MAX_FILE = 2 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
MAX_EXECUTABLE = 32 * 1024 * 1024
TARGET = Path('/opt/ai-control-web')
HELPER = Path('/usr/local/sbin/ai-control-deploy')
STATE = Path('/var/lib/ai-control-deploy/accepted.json')
KEY = Path('/etc/ai-control-deploy/release-key.pem')
LOCK = Path('/var/lib/ai-control-deploy/checkpoints/lock')
PACKAGE_PENDING = Path('/var/lib/ai-control-deploy/checkpoints/pending.json')
CONFIG_PENDING = Path('/var/lib/ai-control-deploy/config-pending.json')
BOOTSTRAP_PENDING = Path('/var/lib/ai-control-deploy/bootstrap-pending.json')
LIVE_CHECKPOINTS = Path('/var/lib/ai-control-deploy/live-bootstrap-checkpoints')
LIVE_RECEIPT = Path('/var/lib/ai-control-deploy/live-bootstrap-complete.json')
BROKER_UNIT = Path('/etc/systemd/system/ai-control-web-broker.service')
CONTROL_DEVBUS_CONFIG = '/home/dwl/.config/ai-control/devbus-observer.json'
SITE_PACKAGES = Path('/opt/ai-control-web/venv/lib/python3.12/site-packages')
DEP_PACKAGE = SITE_PACKAGES / 'nats'
DEP_INFO = SITE_PACKAGES / 'nats_py-2.9.0.dist-info'
VENV_ROOT = Path('/opt/ai-control-web/venv')
SYSTEM_PYTHON = '/usr/bin/python3'
VENV_PYTHON = '/opt/ai-control-web/venv/bin/python'
OWNER_IMPORT_LAUNCHER = '/usr/bin/setpriv'
SYSTEMCTL = '/usr/bin/systemctl'
OLD_HELPER_SHA256 = 'bf142e2b6fee390dfe50a44533e18801ba93b66bcba11c0d14c587b65b270dc1'
KEY_SHA256 = '191cbdb3eee39ce8b8094e5d5bf1dd8281e8b9ad993dc4557402e1a10c11ae55'
PACKET_SHA256 = None
PACKET_MANIFEST_SNAPSHOT = None
EXPECTED_ACCEPTED_SHA256 = None
EXPECTED_BEFORE_FILES = None
NEW_HELPER_SHA256 = None
NEW_HELPER_BLOB_B64 = None
BEFORE_BROKER_UNIT_SHA256 = None
AFTER_BROKER_UNIT_SHA256 = None
BEFORE_BROKER_UNIT_BLOB_B64 = None
AFTER_BROKER_UNIT_BLOB_B64 = None
EXPECTED_RUNTIME_STAT_PINS = None
WHEEL_BLOB_B64 = None
CONFIG_LINE = b'Environment=CONTROL_DEVBUS_CONFIG=/home/dwl/.config/ai-control/devbus-observer.json\n'
SAFE_PROPERTIES = ('User', 'Group', 'ProtectSystem', 'ProtectHome', 'ReadWritePaths',
                   'InaccessiblePaths', 'FragmentPath', 'DropInPaths')
SERVICES = ('ai-control-web.service', 'ai-control-web-broker.service')
LEGACY_MODES = {'bin/ai-control-web': 493, 'bin/_control_web.py': 420, 'bin/_control_web_broker.py': 420, 'bin/_control_web_sessions.py': 420, 'bin/_codex_rc.py': 420, 'bin/_rc_projects.sh': 493, 'bin/_control_web.html': 420, 'bin/_control_web.css': 420, 'bin/_control_web.js': 420, 'requirements-web.lock': 420, 'systemd/ai-control-web.service.tmpl': 420, 'systemd/ai-control-web-broker.service.tmpl': 420, 'bin/_control_web.svg': 420}
NEW_LEAF = 'bin/_control_web_configured_create.py'
CURRENT_MODES = {**LEGACY_MODES, NEW_LEAF: 0o644}
APP_LEAVES = ('bin/_control_web_android_auth.py', 'bin/_control_web_android_download.py')
APP_MODES = {**CURRENT_MODES, **dict.fromkeys(APP_LEAVES, 0o644)}
LIVE_LEAVES = ('bin/_control_web_devbus.py', 'bin/_control_web_devbus_nats.py',
               'bin/_control_web_devbus.js', 'bin/_control_web_devbus.css',
               'requirements-devbus.lock', 'bin/_control_web_live.py')
LIVE_MODES = {**APP_MODES, **dict.fromkeys(LIVE_LEAVES, 0o644)}
WHEEL_SHA256 = '132a8e4b646ad058c7b242b7161621832ee8737ca6f6cbd47dcb6d3ad09490ed'
WHEEL_SIZE = 82408
WHEEL_INVENTORY_SHA256 = '40b35159d50cf2bf0f645f5ab1564f5a3fd0efcee266405fffeb6a496dc7bb43'
WHEEL_MEMBERS = ({'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/__init__.py',
  'sha256': '079ba46da1848a5fbd891fab25d948bf12fc233d314f0dda2c0572394d898246',
  'size': 1323},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/aio/__init__.py',
  'sha256': 'f42a170e66f67090746846d2468464049effc67f9a490a310768d2af5f485288',
  'size': 581},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/aio/client.py',
  'sha256': '05d7eeed5abf643c41a26439fec681b36af023f6475e06cbc670cf989ff48f13',
  'size': 78596},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/aio/errors.py',
  'sha256': '1df0969e1a39420a7ec1bef99eba5a736c4e23a29e185f07ce616192e789d9ca',
  'size': 4050},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/aio/msg.py',
  'sha256': '663e6fceac0b3e7e8c2a656b6b0d4bb4289252a0e30e2c1beb34604b88f8b154',
  'size': 8517},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/aio/subscription.py',
  'sha256': '764b000b065a8ed2fc7ea6953913b1a048b3d2ed9d428b053d6bec5dcdaa3a6d',
  'size': 12371},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/aio/transport.py',
  'sha256': '75e654e4402debb2605a2e43fde6abf858824cc2f2ba96bf27b0bd6c88b4bb4f',
  'size': 8286},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/errors.py',
  'sha256': 'd2f42f355b67227a650ee0ffc735682439a6f755048d959fc80a046a04561a8c',
  'size': 4269},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/js/__init__.py',
  'sha256': '803dc20bfb1b18daec3d04ca7da366e67c73e5af389835c2d375d6da6366a864',
  'size': 765},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/js/api.py',
  'sha256': '15ff0bf5d31d2744b3cb423fede3366663824560af97bf90956309716bd9b18b',
  'size': 22848},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/js/client.py',
  'sha256': '73e1baa5ae94de3fe66619999151118f41f5436d1780f3dbf6b71a53faca43f2',
  'size': 53625},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/js/errors.py',
  'sha256': 'bb5f8b0453fdd52617036ff6faca0490ad0de2d32146a47d724b483ef75cdb0e',
  'size': 7410},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/js/kv.py',
  'sha256': '383f6274e479caf2d760f16a4c94a5df3bcfa619e71c36e54593d7eadc70dcf3',
  'size': 15040},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/js/manager.py',
  'sha256': 'ef4ebfbfa18d776d4c1096328731cb22dbd0ca56112f90c130ccbfc7210e103f',
  'size': 13064},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/js/object_store.py',
  'sha256': '8a6af0bd8df31fc2deac78c57ff37c5a4abd7b23f09e6738171552093d398d8b',
  'size': 17511},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/micro/__init__.py',
  'sha256': '32322d40c0578933f3e5d215977f3148feb11cf21cd174a55dfbc6c38beff713',
  'size': 1107},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/micro/request.py',
  'sha256': 'eecdaa9b8ecf52142a7cf13e959d0f226e0f6b6c4f61f77eb2e16fdeb45e4876',
  'size': 3166},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/micro/service.py',
  'sha256': '5194e8b9f14a98a9dcabe3b5f1cbe1d6c9a31858bec6167cfc03a2bea6bd4903',
  'size': 23228},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/nuid.py',
  'sha256': '9790bb4089145a39f1c0e2913bc65d7d1f044a5ae0e43247821b174fdbda93e4',
  'size': 2210},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/protocol/__init__.py',
  'sha256': '0f5641f72caa65ba01dbae2027013eb42ea75ea01a47e47b43f37c1149d143b7',
  'size': 581},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/protocol/command.py',
  'sha256': 'ac80836ebea9379c4c089f23e3973a8924499b2282bc2bbd68bd6569668a6363',
  'size': 825},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/protocol/parser.py',
  'sha256': '61eeaeaffa2f66e7f85f60c7611176a16fd91a7ea7173db83f72fbddff79d1d7',
  'size': 7383},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats/py.typed',
  'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  'size': 0},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats_py-2.9.0.dist-info/LICENSE',
  'sha256': 'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4',
  'size': 11357},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats_py-2.9.0.dist-info/METADATA',
  'sha256': 'f03dc22e91ff617479e2bf86fe6a193830a6170a885f6677b1e78ff85338303e',
  'size': 8343},
 {'archive_mode': 436,
  'install_mode': 420,
  'path': 'nats_py-2.9.0.dist-info/RECORD',
  'sha256': 'cfea3c90174418d8795bb8ef745d0a139493f51518c1555e5154fc0b69744c84',
  'size': 2212},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats_py-2.9.0.dist-info/WHEEL',
  'sha256': '227f454cdc5e3fad0a9d3906c3bc24ea624f61dfdd4128c46665dd05d30223ef',
  'size': 91},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats_py-2.9.0.dist-info/top_level.txt',
  'sha256': 'f338971b88d559541fb4278582cff6671ee598ac3d3151c54951af571180aa18',
  'size': 5},
 {'archive_mode': 420,
  'install_mode': 420,
  'path': 'nats_py-2.9.0.dist-info/zip-safe',
  'sha256': '01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b',
  'size': 1})

def digest(data):
    return hashlib.sha256(data).hexdigest()

def directory(path, owner_uid, private=False, ancestors=True):
    """Open each component without following links and validate ownership."""
    file_budget()
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
                if info.st_gid != 0 or info.st_uid not in allowed or (info.st_mode & 0o022):
                    raise ValueError('Unsafe directory')
                if last and private and stat.S_IMODE(info.st_mode) != 0o700:
                    raise ValueError('Controller directory is not private')
        return fd
    except BaseException:
        os.close(fd)
        raise

def read_file(path, *, owners, limit=MAX_FILE, mode=None, private_parent=False, return_stat=False):
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
            raw = b''.join(chunks)
            return (raw, info) if return_stat else raw
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
            if (os.fstat(out.fileno()).st_uid, os.fstat(out.fileno()).st_gid) != (0, 0):
                os.fchown(out.fileno(), 0, 0)
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

def canonical_inventory(rows):
    if type(rows) not in (list, tuple):
        raise ValueError('Invalid inventory')
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != {'path', 'sha256', 'size', 'archive_mode', 'install_mode'}:
            raise ValueError('Invalid inventory row')
        path = row['path']
        if (type(path) is not str or not path or path.startswith('/') or
                any(part in ('', '.', '..') for part in path.split('/')) or
                any(c in path for c in '\\:\x00') or len(path.split('/')) > 8 or path in seen):
            raise ValueError('Invalid inventory path')
        seen.add(path)
        if type(row['sha256']) is not str or re.fullmatch('[0-9a-f]{64}', row['sha256']) is None:
            raise ValueError('Invalid inventory digest')
        if type(row['size']) is not int or not 0 <= row['size'] <= MAX_FILE:
            raise ValueError('Invalid inventory size')
        for field in ('archive_mode', 'install_mode'):
            if type(row[field]) is not int or not 0 <= row[field] <= 0o7777:
                raise ValueError('Invalid inventory mode')
    return json.dumps(sorted(rows, key=lambda row: row['path']), sort_keys=True,
                      separators=(',', ':'), ensure_ascii=True).encode('utf-8')

def dependency_inventory(site, *, owner_uid=0):
    """Observe every installed member independently; compiled rows only name provenance."""
    allowed_dirs = {str(parent) for row in WHEEL_MEMBERS for parent in Path(row['path']).parents
                    if str(parent) != '.'}
    required = {row['path'] for row in WHEEL_MEMBERS}
    fd = directory(site, owner_uid)
    try:
        info = os.fstat(fd)
        if (owner_uid == 0 and info.st_gid != 0) or stat.S_IMODE(info.st_mode) != 0o755:
            raise ValueError('Unsafe dependency site')
        matches = {name for name in os.listdir(fd) if name == 'nats' or name.startswith(('nats.', 'nats-', 'nats_py')) or
                   (name.startswith('nats') and name.endswith('.pth'))}
        if matches != {'nats', 'nats_py-2.9.0.dist-info'}:
            raise ValueError('Dependency shadow or missing package')
    finally:
        os.close(fd)
    seen_files, seen_dirs = set(), set()
    for top in ('nats', 'nats_py-2.9.0.dist-info'):
        def walk(relative):
            parent = directory(Path(site) / relative, owner_uid)
            try:
                info = os.fstat(parent)
                if (info.st_uid != owner_uid or (owner_uid == 0 and info.st_gid != 0) or stat.S_IMODE(info.st_mode) != 0o755):
                    raise ValueError('Unsafe dependency directory')
                seen_dirs.add(relative)
                for name in os.listdir(parent):
                    child = relative + '/' + name
                    value = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if stat.S_ISDIR(value.st_mode) and child in allowed_dirs:
                        walk(child)
                    elif stat.S_ISREG(value.st_mode) and child in required:
                        seen_files.add(child)
                    else:
                        raise ValueError('Unknown dependency node')
            finally:
                os.close(parent)
        walk(top)
    if seen_files != required or seen_dirs != allowed_dirs:
        raise ValueError('Incomplete dependency tree')
    observed = []
    for row in WHEEL_MEMBERS:
        data, info = read_file(Path(site) / row['path'], owners=(owner_uid,), mode=0o644, return_stat=True)
        observed.append(dict(path=row['path'], sha256=digest(data), size=info.st_size,
                             archive_mode=row['archive_mode'], install_mode=stat.S_IMODE(info.st_mode)))
    if digest(canonical_inventory(observed)) != WHEEL_INVENTORY_SHA256:
        raise ValueError('Dependency inventory drift')
    return observed

OWNER_IMPORT_CODE = '''import importlib.metadata,inspect,json,os,platform,socket
assert os.getuid()==1000 and os.geteuid()==1000 and os.getgid()==1000 and os.getegid()==1000
network_calls=0
class NoNetworkSocket(socket.socket):
    def __new__(cls,*args,**kwargs):
        global network_calls
        network_calls+=1
        raise RuntimeError("network forbidden in import-only smoke")
socket.socket=NoNetworkSocket
import nats
from nats.aio.client import Client
from nats.js.client import JetStreamContext
from nats.js.api import ConsumerConfig
source_file=os.path.realpath(nats.__file__)
assert source_file=="/opt/ai-control-web/venv/lib/python3.12/site-packages/nats/__init__.py"
assert nats.__file__==source_file
params=inspect.signature(Client.connect).parameters
value={"schema":1,"uid":os.getuid(),"gid":os.getgid(),"python":platform.python_version(),"version":importlib.metadata.version("nats-py"),"connect_api":callable(nats.connect),"client_api":all(x in params for x in ("servers","connect_timeout","max_reconnect_attempts","allow_reconnect","disconnected_cb","error_cb","token","user_credentials")),"jetstream_api":all(callable(getattr(JetStreamContext,x,None)) for x in ("stream_info","add_consumer","delete_consumer","pull_subscribe_bind")),"consumer_config_api":inspect.isclass(ConsumerConfig),"source_file":source_file,"network_calls":network_calls}
print(json.dumps(value,sort_keys=True,separators=(",",":")))
'''

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


def unit_pair(before, after):
    for raw in (before, after):
        validate_unit(raw)
    if (before.count(b'[Service]\n') != 1 or CONFIG_LINE in before or
            after != before.replace(b'[Service]\n', b'[Service]\n' + CONFIG_LINE, 1)):
        raise ValueError('Unit change outside fixed pointer')


def validate_unit(raw):
    """Closed renderer shape; independent secret-free attestation remains external."""
    if type(raw) is not bytes or not 0 < len(raw) <= 65536:
        raise ValueError('Invalid unit size')
    text = raw.decode('utf-8')
    if any(c in text for c in ('\x00', '\r', '\\', '$', '%', '{{', '}}')):
        raise ValueError('Unsafe unit syntax')
    if re.search(r'(?:token|password|secret|credential)\s*[:=]|://[^/\s]+@', text, re.IGNORECASE):
        raise ValueError('Unsafe inline unit data')
    sections = {'Unit': {'Description', 'After'},
                'Service': {'Type', 'User', 'Group', 'Environment', 'ExecStart', 'RuntimeDirectory',
                            'RuntimeDirectoryMode', 'Restart', 'RestartSec', 'UMask', 'NoNewPrivileges',
                            'PrivateTmp', 'BindReadOnlyPaths', 'ProtectSystem', 'ProtectHome',
                            'ProtectKernelTunables', 'ProtectKernelModules', 'RestrictSUIDSGID',
                            'RestrictAddressFamilies', 'CapabilityBoundingSet', 'LockPersonality'},
                'Install': {'WantedBy'}}
    current, seen_sections, seen, envs = None, set(), {}, {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        if line.startswith('['):
            current = line[1:-1]
            if line != '[' + current + ']' or current not in sections or current in seen_sections:
                raise ValueError('Invalid unit section')
            seen_sections.add(current)
            continue
        if '=' not in line or current is None:
            raise ValueError('Invalid unit directive')
        name, value = line.split('=', 1)
        if name not in sections[current] or (name in seen and name != 'Environment'):
            raise ValueError('Unknown or duplicate unit directive')
        if name == 'Environment':
            if '=' not in value:
                raise ValueError('Invalid unit environment')
            key, argument = value.split('=', 1)
            fixed = {'HOME': '/home/dwl', 'XDG_RUNTIME_DIR': '/run/user/1000',
                     'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus',
                     'CONTROL_DEVBUS_CONFIG': CONTROL_DEVBUS_CONFIG}
            if key in envs or key not in {*fixed, 'PATH'}:
                raise ValueError('Unsafe unit environment')
            if key == 'PATH':
                if re.fullmatch('/home/dwl/[A-Za-z0-9_./-]+:/usr/local/bin:/usr/bin:/bin', argument) is None:
                    raise ValueError('Unsafe unit path')
            elif argument != fixed[key]:
                raise ValueError('Unit environment mismatch')
            envs[key] = argument
        else:
            seen[name] = value
    if seen_sections != set(sections) or not {'HOME', 'PATH', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS'} <= envs.keys():
        raise ValueError('Incomplete unit shape')
    fixed = {'User': 'dwl', 'Group': 'ai-panel', 'Type': 'simple', 'ProtectSystem': 'full',
             'NoNewPrivileges': 'yes', 'PrivateTmp': 'yes', 'RuntimeDirectory': 'ai-control-web',
             'RuntimeDirectoryMode': '0750', 'Restart': 'on-failure', 'RestartSec': '3', 'UMask': '0077',
             'ProtectKernelTunables': 'yes', 'ProtectKernelModules': 'yes', 'RestrictSUIDSGID': 'yes',
             'RestrictAddressFamilies': 'AF_UNIX AF_INET AF_INET6', 'CapabilityBoundingSet': '',
             'LockPersonality': 'yes', 'After': 'network.target', 'WantedBy': 'multi-user.target'}
    if any(seen.get(key) != value for key, value in fixed.items()):
        raise ValueError('Unit role mismatch')
    if 'ProtectHome' in seen and seen['ProtectHome'] != 'no':
        raise ValueError('Broker sandbox mismatch')
    if 'BindReadOnlyPaths' in seen and seen['BindReadOnlyPaths'] != '-/tmp/codex-daemon-1000':
        raise ValueError('Unknown broker binding')
    args = seen.get('ExecStart', '').split(' ')
    if (len(args) != 11 or args[:3] != [VENV_PYTHON, '/opt/ai-control-web/bin/ai-control-web', 'broker'] or
            args[3] != '--registry' or args[5] != '--bin-dir' or args[7:] !=
            ['--socket', '/run/ai-control-web/broker.sock', '--allowed-uid', '993']):
        raise ValueError('Unsafe broker command')
    if (re.fullmatch('/home/dwl/[A-Za-z0-9_./-]+', args[4]) is None or
            re.fullmatch('/home/dwl/[A-Za-z0-9_./-]+', args[6]) is None or
            envs['PATH'] != args[6] + ':/usr/local/bin:/usr/bin:/bin' or
            any('/../' in value or '/./' in value for value in (args[4], args[6]))):
        raise ValueError('Unknown renderer parameters')


def identity_row(row, *, extra=()):
    keys(row, ('dev', 'ino', 'uid', 'gid', 'mode', *extra))
    for name in ('dev', 'ino', 'uid', 'gid', 'mode'):
        if type(row[name]) is not int:
            raise ValueError('Invalid stat pin')
    if row['dev'] < 0 or row['ino'] <= 0 or row['uid'] != 0 or row['gid'] != 0 or not 0 <= row['mode'] <= 0o7777:
        raise ValueError('Unsafe stat pin')


def runtime_shape(value):
    names = ('LOCK', 'SITE_PACKAGES', 'VENV_ROOT', 'BROKER_UNIT_MODE', 'SYSTEM_PYTHON',
             'VENV_PYTHON', 'OWNER_IMPORT_LAUNCHER', 'SYSTEMCTL')
    keys(value, names)
    for name in ('LOCK', 'SITE_PACKAGES', 'VENV_ROOT'):
        identity_row(value[name])
        required = {'LOCK': 0o600, 'SITE_PACKAGES': 0o755}.get(name)
        if ((required is not None and value[name]['mode'] != required) or
                (name == 'VENV_ROOT' and value[name]['mode'] & 0o022)):
            raise ValueError('Unsafe directory pin')
    if type(value['BROKER_UNIT_MODE']) is not int or value['BROKER_UNIT_MODE'] not in (0o644, 0o600):
        raise ValueError('Invalid unit mode pin')
    for name in ('SYSTEM_PYTHON', 'VENV_PYTHON', 'OWNER_IMPORT_LAUNCHER', 'SYSTEMCTL'):
        row = value[name]
        keys(row, ('links', 'resolved'))
        if type(row['links']) is not list or len(row['links']) > 8:
            raise ValueError('Invalid executable chain')
        current, seen = globals()[name], set()
        for link in row['links']:
            identity_row(link, extra=('path', 'target'))
            if (link['path'] != current or current in seen or type(link['target']) is not str or
                    not link['target'] or '\x00' in link['target']):
                raise ValueError('Invalid executable link')
            seen.add(current)
            current = os.path.normpath(os.path.join(os.path.dirname(current), link['target']))
            if not current.startswith('/'):
                raise ValueError('Invalid executable path')
        resolved = row['resolved']
        identity_row(resolved, extra=('path', 'size', 'sha256'))
        if (resolved['path'] != current or current in seen or resolved['mode'] & 0o022 or
                not resolved['mode'] & 0o111 or type(resolved['size']) is not int or
                not 0 < resolved['size'] <= MAX_EXECUTABLE):
            raise ValueError('Unsafe executable terminal')
        pin(resolved['sha256'])


def same_identity(info, row):
    observed = (info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
    if observed != tuple(row[key] for key in ('dev', 'ino', 'uid', 'gid', 'mode')):
        raise ValueError('Runtime inode drift')


def runtime_proof():
    for name in ('LOCK', 'SITE_PACKAGES', 'VENV_ROOT'):
        path = globals()[name]
        os.close(directory(Path(path).parent, 0))
        info = os.lstat(path)
        same_identity(info, EXPECTED_RUNTIME_STAT_PINS[name])
        if name == 'LOCK':
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Unsafe existing lock')
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('Unsafe runtime directory')
    for name in ('SYSTEM_PYTHON', 'VENV_PYTHON', 'OWNER_IMPORT_LAUNCHER', 'SYSTEMCTL'):
        row = EXPECTED_RUNTIME_STAT_PINS[name]
        for link in row['links']:
            os.close(directory(Path(link['path']).parent, 0))
            info = os.lstat(link['path'])
            same_identity(info, link)
            if not stat.S_ISLNK(info.st_mode) or info.st_nlink != 1 or os.readlink(link['path']) != link['target']:
                raise ValueError('Executable link drift')
        resolved = row['resolved']
        path = resolved['path']
        parent = directory(Path(path).parent, 0)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                same_identity(info, resolved)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != resolved['size']:
                    raise ValueError('Executable metadata drift')
                raw = bytearray()
                while len(raw) <= MAX_EXECUTABLE:
                    chunk = os.read(fd, min(65536, MAX_EXECUTABLE + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                fresh = os.stat(path, follow_symlinks=False)
                fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
                          'st_size', 'st_mtime_ns', 'st_ctime_ns')
                if (any(getattr(value, key) != getattr(info, key) for value in (fresh, os.fstat(fd)) for key in fields) or
                        digest(raw) != resolved['sha256']):
                    raise ValueError('Executable bytes changed')
            finally:
                os.close(fd)
        finally:
            os.close(parent)


def wheel_snapshot(raw):
    if len(raw) != WHEEL_SIZE or digest(raw) != WHEEL_SHA256:
        raise ValueError('Wheel pin mismatch')
    expected = {row['path']: row for row in WHEEL_MEMBERS}
    result = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 29 or sum(node.file_size for node in members) != 308765:
                raise ValueError('Wheel inventory mismatch')
            for node in members:
                name = node.filename
                if name not in expected or name in result:
                    raise ValueError('Unknown wheel member')
                row = expected[name]
                mode = node.external_attr >> 16
                if (node.is_dir() or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)) or
                        stat.S_IMODE(mode) != row['archive_mode'] or node.file_size != row['size'] or
                        node.file_size > MAX_FILE or node.flag_bits & 1):
                    raise ValueError('Unsafe wheel member')
                data = archive.read(node)
                if len(data) != row['size'] or digest(data) != row['sha256']:
                    raise ValueError('Wheel member mismatch')
                result[name] = data
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ValueError('Invalid wheel archive') from exc
    if set(result) != set(expected):
        raise ValueError('Incomplete wheel')
    record = list(csv.reader(io.StringIO(result['nats_py-2.9.0.dist-info/RECORD'].decode('utf-8'))))
    if len(record) != 29 or {row[0] for row in record if len(row) == 3} != set(expected):
        raise ValueError('Invalid wheel RECORD')
    for name, hashed, size in record:
        if name.endswith('/RECORD'):
            if hashed or size:
                raise ValueError('Invalid self RECORD')
        elif hashed != 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(result[name]).digest()).rstrip(b'=').decode() or size != str(len(result[name])):
            raise ValueError('Invalid RECORD member')
    return result


def operation_inputs():
    pin(PACKET_SHA256)
    manifest = manifest_value(PACKET_MANIFEST_SNAPSHOT)
    if digest(PACKET_MANIFEST_SNAPSHOT) != PACKET_SHA256:
        raise ValueError('Manifest carrier mismatch')
    for value in (EXPECTED_ACCEPTED_SHA256, NEW_HELPER_SHA256, BEFORE_BROKER_UNIT_SHA256,
                  AFTER_BROKER_UNIT_SHA256, OLD_HELPER_SHA256, KEY_SHA256):
        pin(value)
    keys(EXPECTED_BEFORE_FILES, APP_MODES)
    for value in EXPECTED_BEFORE_FILES.values():
        pin(value)
    runtime_shape(EXPECTED_RUNTIME_STAT_PINS)
    helper = strict_blob(NEW_HELPER_BLOB_B64, 1048576)
    wheel = strict_blob(WHEEL_BLOB_B64, 82408)
    before = strict_blob(BEFORE_BROKER_UNIT_BLOB_B64, 65536)
    after = strict_blob(AFTER_BROKER_UNIT_BLOB_B64, 65536)
    for name, raw, sha in (('helper', helper, NEW_HELPER_SHA256), ('wheel', wheel, WHEEL_SHA256),
                           ('unit_before', before, BEFORE_BROKER_UNIT_SHA256),
                           ('unit_after', after, AFTER_BROKER_UNIT_SHA256)):
        if digest(raw) != sha or manifest[name] != {'sha256': sha, 'size': len(raw)}:
            raise ValueError('Operation crossbinding mismatch')
    unit_pair(before, after)
    if (len(WHEEL_MEMBERS) != 29 or digest(canonical_inventory(WHEEL_MEMBERS)) != WHEEL_INVENTORY_SHA256 or
            digest(OWNER_IMPORT_CODE.encode()) != '70b31a6b98b049a0a3a6eba2af77f0732a2fcd856d232c5f86928b9b642a2189'):
        raise ValueError('Source-final inventory drift')
    return helper, before, after, wheel_snapshot(wheel)
def sync_dir(path):
    fd = directory(path, 0)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def existing_private(path):
    fd = directory(path, 0, private=True)
    try:
        if os.fstat(fd).st_gid != 0:
            raise ValueError('Unsafe private directory')
    finally:
        os.close(fd)


def node_exists(path):
    parent = directory(Path(path).parent, 0)
    try:
        try:
            os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
    finally:
        os.close(parent)


def mkdir_new(path, mode):
    parent = directory(Path(path).parent, 0)
    try:
        os.mkdir(Path(path).name, mode, dir_fd=parent)
        child = directory(path, 0)
        try:
            os.fchmod(child, mode)
            info = os.fstat(child)
            if (info.st_uid, info.st_gid) != (0, 0):
                os.fchown(child, 0, 0)
            os.fsync(child)
        finally:
            os.close(child)
        os.fsync(parent)
    finally:
        os.close(parent)


def remove_snapshot(path, raw, mode):
    """Anchored descriptor/content/identity proof immediately before unlink."""
    parent = directory(Path(path).parent, 0)
    try:
        fd = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            current = read_file(path, owners=(0,), mode=mode)
            fresh = os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)
            fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
                      'st_size', 'st_mtime_ns', 'st_ctime_ns')
            if current != raw or any(getattr(before, name) != getattr(value, name)
                                      for value in (fresh, os.fstat(fd)) for name in fields):
                raise ValueError('Unlink evidence changed')
            os.unlink(Path(path).name, dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def staged_dependency(kind, blobs, *, final=False):
    prefix = 'nats/' if kind == 'nats' else 'nats_py-2.9.0.dist-info/'
    path = (DEP_PACKAGE if kind == 'nats' else DEP_INFO) if final else SITE_PACKAGES / ('.ai-control-live22-' + kind + '.stage')
    members = {row['path'][len(prefix):]: row for row in WHEEL_MEMBERS if row['path'].startswith(prefix)}
    dirs = {str(parent) for name in members for parent in Path(name).parents if str(parent) != '.'}
    fd = directory(path, 0)
    try:
        root_mode = stat.S_IMODE(os.fstat(fd).st_mode)
        if root_mode not in ((0o755,) if final else (0o700, 0o755)):
            raise ValueError('Unsafe dependency stage mode')
    finally:
        os.close(fd)
    files, temps = set(), []
    def walk(relative):
        parent_path = path / relative
        fd = directory(parent_path, 0)
        try:
            if relative and stat.S_IMODE(os.fstat(fd).st_mode) != 0o755:
                raise ValueError('Unsafe dependency subdirectory')
            for name in os.listdir(fd):
                file_budget()
                leaf = (Path(relative) / name).as_posix()
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode) and leaf in dirs:
                    walk(leaf)
                elif stat.S_ISREG(info.st_mode) and leaf in members:
                    raw = read_file(path / leaf, owners=(0,), mode=0o644)
                    row = members[leaf]
                    if digest(raw) != row['sha256'] or len(raw) != row['size']:
                        raise ValueError('Unknown dependency member')
                    files.add(leaf)
                elif not final and stat.S_ISREG(info.st_mode) and name.startswith('.live22-') and name.endswith('.part'):
                    matching = [(member, row) for member, row in members.items()
                                if name == '.live22-' + row['sha256'] + '.part' and
                                Path(member).parent == Path(relative or '.')]
                    if len(matching) != 1:
                        raise ValueError('Unknown dependency temporary')
                    member, row = matching[0]
                    mode = stat.S_IMODE(info.st_mode)
                    if mode not in (0o600, 0o644) or member in files:
                        raise ValueError('Unsafe temporary mode')
                    raw = read_file(path / leaf, owners=(0,), mode=mode)
                    full = blobs[prefix + member]
                    if not full.startswith(raw) or (mode == 0o644 and raw != full):
                        raise ValueError('Unknown temporary bytes')
                    temps.append((path / leaf, raw, mode, member))
                else:
                    raise ValueError('Unknown dependency stage node')
        finally:
            os.close(fd)
    walk('')
    if any(member in files for _, _, _, member in temps) or len(temps) > 1:
        raise ValueError('Temporary member collision')
    if (final or root_mode == 0o755) and (files != set(members) or temps):
        raise ValueError('Incomplete promoted dependency')
    return path, members, files, temps


def dependency_state(blobs, *, own=False, rollback=False):
    parent = directory(SITE_PACKAGES, 0)
    try:
        names = set(os.listdir(parent))
        allowed = {'nats', 'nats_py-2.9.0.dist-info', '.ai-control-live22-nats.stage', '.ai-control-live22-info.stage'}
        matches = {name for name in names if name == 'nats' or name.startswith(('nats.', 'nats-', 'nats_py', '.ai-control-live22-')) or
                   (name.startswith('nats') and name.endswith('.pth'))}
        if matches - allowed:
            raise ValueError('Dependency shadow')
    finally:
        os.close(parent)
    nf, inf = 'nats' in names, 'nats_py-2.9.0.dist-info' in names
    ns, ins = '.ai-control-live22-nats.stage' in names, '.ai-control-live22-info.stage' in names
    if ns and ins or ns and nf or ins and inf:
        raise ValueError('Dependency state collision')
    # Rollback keeps INFO stage without its final while NATS still exists;
    # once INFO is deleted, NATS can be renamed into its stage.
    if (inf and not nf) or (ins and not nf):
        raise ValueError('Dependency order mismatch')
    temps = 0
    for kind, is_final, is_stage in (('nats', nf, ns), ('info', inf, ins)):
        if is_final:
            staged_dependency(kind, blobs, final=True)
        if is_stage:
            if not own:
                raise ValueError('Foreign dependency stage')
            temps += len(staged_dependency(kind, blobs)[3])
    if temps > 1:
        raise ValueError('Too many dependency temporaries')
    return ('A4' if nf and inf else 'A3' if nf and ins else 'A2' if nf else 'A1' if ns else 'A0')


def member_write(path, raw, row):
    parent = directory(Path(path).parent, 0)
    name = '.live22-' + row['sha256'] + '.part'
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            if (os.fstat(fd).st_uid, os.fstat(fd).st_gid) != (0, 0):
                os.fchown(fd, 0, 0)
            remaining = memoryview(raw)
            while remaining:
                file_budget()
                count = os.write(fd, remaining)
                if count <= 0:
                    raise ValueError('Incomplete member write')
                remaining = remaining[count:]
            os.fchmod(fd, 0o644)
            os.fsync(fd)
            if read_file(Path(path).parent / name, owners=(0,), mode=0o644) != raw:
                raise ValueError('Member snapshot changed')
            fresh = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if any(getattr(fresh, key) != getattr(os.fstat(fd), key)
                   for key in ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
                               'st_size', 'st_mtime_ns', 'st_ctime_ns')):
                raise ValueError('Temporary replaced')
            try:
                os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError('Member already exists')
            os.rename(name, Path(path).name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def sync_dependency(path):
    # Revalidate content separately before promotion; this phase only fsyncs.
    for root, dirs, files in os.walk(path, topdown=False, followlinks=False):
        for name in files:
            fd = os.open(Path(root) / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        sync_dir(root)
    sync_dir(SITE_PACKAGES)


def install_dependency(blobs):
    dependency_state(blobs, own=True)
    for kind, final in (('nats', DEP_PACKAGE), ('info', DEP_INFO)):
        if node_exists(final):
            staged_dependency(kind, blobs, final=True)
            continue
        stage = SITE_PACKAGES / ('.ai-control-live22-' + kind + '.stage')
        if not node_exists(stage):
            mkdir_new(stage, 0o700)
        path, members, files, temps = staged_dependency(kind, blobs)
        for temp, raw, mode, _ in temps:
            remove_snapshot(temp, raw, mode)
        for relative, row in members.items():
            file_budget()
            if relative in files:
                continue
            for parent in reversed(Path(relative).parents):
                if str(parent) != '.' and not node_exists(stage / parent):
                    mkdir_new(stage / parent, 0o755)
            member_write(stage / relative, blobs[row['path']], row)
        staged_dependency(kind, blobs)
        fd = directory(stage, 0)
        try:
            os.fchmod(fd, 0o755)
        finally:
            os.close(fd)
        sync_dependency(stage)
        staged_dependency(kind, blobs)
        if node_exists(final):
            raise ValueError('Dependency target collision')
        os.rename(stage, final)
        sync_dir(SITE_PACKAGES)
    dependency_inventory(SITE_PACKAGES)


def delete_stage(kind, blobs):
    path, members, files, temps = staged_dependency(kind, blobs)
    for temp, raw, mode, _ in temps:
        remove_snapshot(temp, raw, mode)
    for relative in sorted(files):
        file_budget()
        row = members[relative]
        remove_snapshot(path / relative, blobs[row['path']], 0o644)
    dirs = {str(parent) for member in members for parent in Path(member).parents if str(parent) != '.'}
    for relative in sorted(dirs, key=lambda value: len(Path(value).parts), reverse=True):
        if node_exists(path / relative):
            fd = directory(path / Path(relative).parent, 0)
            try:
                os.rmdir(Path(relative).name, dir_fd=fd)
                os.fsync(fd)
            finally:
                os.close(fd)
    if os.listdir(directory_fd := directory(path, 0)):
        os.close(directory_fd)
        raise ValueError('Unknown deletion residue')
    os.close(directory_fd)
    parent = directory(path.parent, 0)
    try:
        os.rmdir(path.name, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def remove_dependency(blobs):
    dependency_state(blobs, own=True, rollback=True)
    for kind, final in (('info', DEP_INFO), ('nats', DEP_PACKAGE)):
        stage = SITE_PACKAGES / ('.ai-control-live22-' + kind + '.stage')
        if node_exists(final):
            staged_dependency(kind, blobs, final=True)
            if node_exists(stage):
                raise ValueError('Rollback stage collision')
            os.rename(final, stage)
            sync_dir(SITE_PACKAGES)
        if node_exists(stage):
            staged_dependency(kind, blobs)
            fd = directory(stage, 0)
            try:
                os.fchmod(fd, 0o700)
                os.fsync(fd)
            finally:
                os.close(fd)
            delete_stage(kind, blobs)
    if dependency_state(blobs, own=True) != 'A0':
        raise ValueError('Dependency rollback failed')
_file_deadline = None


def file_budget():
    if _file_deadline is not None and time.monotonic() > _file_deadline:
        raise ValueError('File-work budget exhausted')


def run_command(argv, *, timeout=40, env=None, cwd='/'):
    return subprocess.run(argv, capture_output=True, timeout=timeout, cwd=cwd,
                          env={'PATH': '/usr/bin:/bin', 'LANG': 'C'} if env is None else env)


class Commands:
    def __init__(self):
        self.systemctl = 0
        self.smokes = 0

    def call(self, action, service=None):
        global _file_deadline
        allowed = {'is-active', 'show', 'stop', 'start', 'daemon-reload'}
        if action not in allowed or (action == 'daemon-reload') != (service is None) or (service is not None and service not in SERVICES):
            raise ValueError('Command outside fixed scope')
        if self.systemctl >= 26:
            raise ValueError('Service command budget exhausted')
        self.systemctl += 1
        argv = [SYSTEMCTL, action]
        if service:
            argv.append(service)
        if action == 'show':
            argv.append('--property=' + ','.join(SAFE_PROPERTIES))
        runtime_proof()
        began = time.monotonic()
        try:
            result = run_command(argv, timeout=40)
        finally:
            _file_deadline += time.monotonic() - began
        if type(result.stdout) is not bytes or type(result.stderr) is not bytes or len(result.stdout) > 16384 or len(result.stderr) > 16384:
            raise ValueError('Oversized service result')
        text = result.stdout.decode('utf-8').strip()
        if action == 'is-active':
            if result.returncode not in (0, 3) or text not in ('active', 'inactive', 'failed'):
                raise ValueError('Unknown service state')
        elif result.returncode != 0:
            raise ValueError('Service command failed')
        return text

    def health(self, *, stopped=False):
        for service, user in zip(SERVICES, ('ai-panel', 'dwl')):
            status = self.call('is-active', service)
            if not stopped and status != 'active':
                raise ValueError('Service is not active')
            rows = self.call('show', service).splitlines()
            observed = {}
            for row in rows:
                if '=' not in row:
                    raise ValueError('Unknown unit properties')
                key, value = row.split('=', 1)
                if key in observed:
                    raise ValueError('Duplicate unit property')
                observed[key] = value
            keys(observed, SAFE_PROPERTIES)
            expected = {'User': user, 'Group': 'ai-panel',
                        'ProtectSystem': 'strict' if service == SERVICES[0] else 'full',
                        'ProtectHome': 'yes' if service == SERVICES[0] else 'no',
                        'FragmentPath': '/etc/systemd/system/' + service, 'DropInPaths': ''}
            if any(observed[key] != value for key, value in expected.items()):
                raise ValueError('Effective unit mismatch')
            if service == SERVICES[0] and (observed['ReadWritePaths'] != '/run/ai-control-web /var/lib/ai-control-web' or observed['InaccessiblePaths'] != '/data'):
                raise ValueError('Frontend role mismatch')

    def stop(self):
        self.call('stop', SERVICES[0])
        self.call('stop', SERVICES[1])
        for service in SERVICES:
            if self.call('is-active', service) not in ('inactive', 'failed'):
                raise ValueError('Service did not stop')

    def start(self):
        self.call('start', SERVICES[1])
        self.call('start', SERVICES[0])
        self.health()

    def smoke(self):
        global _file_deadline
        if self.smokes:
            raise ValueError('Import budget exhausted')
        dependency_inventory(SITE_PACKAGES)
        runtime_proof()
        self.smokes += 1
        argv = [OWNER_IMPORT_LAUNCHER, '--reuid=1000', '--regid=1000', '--clear-groups',
                '--no-new-privs', '--', VENV_PYTHON, '-I', '-B', '-c', OWNER_IMPORT_CODE]
        began = time.monotonic()
        try:
            result = run_command(argv, timeout=10, env={}, cwd='/')
        finally:
            _file_deadline += time.monotonic() - began
        if result.returncode != 0 or result.stderr != b'' or type(result.stdout) is not bytes or not 0 < len(result.stdout) <= 4096:
            raise ValueError('Owner import refused')
        value = decode(result.stdout)
        expected = {'schema': 1, 'uid': 1000, 'gid': 1000, 'python': '3.12.3', 'version': '2.9.0',
                    'connect_api': True, 'client_api': True, 'jetstream_api': True, 'consumer_config_api': True,
                    'source_file': '/opt/ai-control-web/venv/lib/python3.12/site-packages/nats/__init__.py', 'network_calls': 0}
        keys(value, expected)
        if any(type(value[key]) is not type(want) or value[key] != want for key, want in expected.items()):
            raise ValueError('Owner import proof mismatch')
        dependency_inventory(SITE_PACKAGES)


def accepted_root(*, completed=False):
    existing_private(STATE.parent)
    raw = read_file(STATE, owners=(0,), mode=0o600, limit=MAX_MANIFEST, private_parent=True)
    value = decode(raw)
    keys(value, ('schema', 'release_id', 'manifest_sha256', 'files'))
    if type(value['schema']) is not int or value['schema'] not in ((3, 4) if completed else (3,)):
        raise ValueError('Accepted schema mismatch')
    integer(value['release_id'], 1)
    pin(value['manifest_sha256'])
    modes = APP_MODES if value['schema'] == 3 else LIVE_MODES
    keys(value['files'], modes)
    for leaf, mode in modes.items():
        file_budget()
        if digest(read_file(TARGET / leaf, owners=(0,), mode=mode)) != pin(value['files'][leaf]):
            raise ValueError('Accepted tree drift')
    if value['schema'] == 3:
        if digest(raw) != EXPECTED_ACCEPTED_SHA256 or value['files'] != EXPECTED_BEFORE_FILES:
            raise ValueError('Accepted raw state drift')
        for leaf in LIVE_LEAVES:
            if node_exists(TARGET / leaf):
                raise ValueError('Unexpected live leaf')
    return raw


def root_inputs(helper, before, after, *, completed=False):
    runtime_proof()
    accepted = accepted_root(completed=completed)
    if digest(read_file(KEY, owners=(0,), mode=0o644, limit=MAX_MANIFEST)) != KEY_SHA256:
        raise ValueError('Trust key drift')
    installed = read_file(HELPER, owners=(0,), mode=0o755, limit=1048576)
    if digest(installed) not in (OLD_HELPER_SHA256, NEW_HELPER_SHA256):
        raise ValueError('Unknown helper bytes')
    unit = read_file(BROKER_UNIT, owners=(0,), mode=EXPECTED_RUNTIME_STAT_PINS['BROKER_UNIT_MODE'], limit=MAX_MANIFEST)
    if unit not in (before, after):
        raise ValueError('Unknown broker unit bytes')
    return accepted, installed, unit


def expected_receipt():
    return {'schema': 1, 'operation': 'live22-bootstrap', 'packet_sha256': PACKET_SHA256,
            'accepted_before_sha256': EXPECTED_ACCEPTED_SHA256, 'helper_sha256': NEW_HELPER_SHA256,
            'unit_sha256': AFTER_BROKER_UNIT_SHA256, 'wheel_sha256': WHEEL_SHA256,
            'dependency_inventory_sha256': WHEEL_INVENTORY_SHA256}


def verify_receipt():
    raw = read_file(LIVE_RECEIPT, owners=(0,), mode=0o600, limit=MAX_MANIFEST, private_parent=True)
    value = decode(raw)
    wanted = expected_receipt()
    keys(value, wanted)
    if any(type(value[key]) is not type(item) or value[key] != item for key, item in wanted.items()):
        raise ValueError('Unknown completion receipt')
    return raw


def after_proof(helper, before, after, blobs, *, completed=False):
    _, current, unit = root_inputs(helper, before, after, completed=completed)
    if current != helper or unit != after or dependency_state(blobs, own=True) != 'A4':
        raise ValueError('Incomplete after operation')
    dependency_inventory(SITE_PACKAGES)


def marker_value(raw):
    value = decode(raw)
    keys(value, ('schema', 'operation', 'packet_sha256', 'checkpoint', 'before_accepted_sha256', 'stage'))
    if (type(value['schema']) is not int or value['schema'] != 2 or value['operation'] != 'live22-bootstrap' or
            value['packet_sha256'] != PACKET_SHA256 or value['before_accepted_sha256'] != EXPECTED_ACCEPTED_SHA256 or
            type(value['checkpoint']) is not str or re.fullmatch('[A-Za-z0-9_-]{1,80}', value['checkpoint']) is None or
            value['stage'] not in ('prepared', 'stopped', 'dependency', 'unit', 'helper', 'started', 'complete', 'rollback')):
        raise ValueError('Unknown bootstrap marker')
    return value


def proof_value(dependency_before):
    return {'schema': 1, 'operation': 'live22-bootstrap', 'packet_sha256': PACKET_SHA256,
            'before_accepted_sha256': EXPECTED_ACCEPTED_SHA256, 'helper_before_sha256': OLD_HELPER_SHA256,
            'unit_before_sha256': BEFORE_BROKER_UNIT_SHA256, 'dependency_before': dependency_before,
            'helper_after_sha256': NEW_HELPER_SHA256, 'unit_after_sha256': AFTER_BROKER_UNIT_SHA256,
            'wheel_sha256': WHEEL_SHA256}


def checkpoint_read(value, before):
    path = LIVE_CHECKPOINTS / value['checkpoint']
    existing_private(path)
    fd = directory(path, 0, private=True)
    try:
        if set(os.listdir(fd)) != {'helper.before', 'broker-unit.before', 'accepted.before', 'proof.json', 'manifest.json'}:
            raise ValueError('Checkpoint scope mismatch')
    finally:
        os.close(fd)
    old = read_file(path / 'helper.before', owners=(0,), mode=0o600, limit=1048576)
    unit = read_file(path / 'broker-unit.before', owners=(0,), mode=0o600, limit=MAX_MANIFEST)
    accepted = read_file(path / 'accepted.before', owners=(0,), mode=0o600, limit=MAX_MANIFEST)
    manifest = read_file(path / 'manifest.json', owners=(0,), mode=0o600, limit=MAX_MANIFEST)
    raw = read_file(path / 'proof.json', owners=(0,), mode=0o600, limit=MAX_MANIFEST)
    proof = decode(raw)
    if type(proof) is not dict:
        raise ValueError('Checkpoint proof mismatch')
    dependency_before = proof.get('dependency_before')
    if dependency_before != 'absent' and dependency_before != {'mode': 'preserved_exact', 'wheel_sha256': WHEEL_SHA256}:
        raise ValueError('Unknown dependency before')
    expected = proof_value(dependency_before)
    if (set(proof) != set(expected) or any(type(proof[key]) is not type(item) or proof[key] != item for key, item in expected.items()) or
            digest(old) != OLD_HELPER_SHA256 or unit != before or digest(accepted) != EXPECTED_ACCEPTED_SHA256 or
            manifest != PACKET_MANIFEST_SNAPSHOT or sum(map(len, (old, unit, accepted, manifest, raw))) > 1310720):
        raise ValueError('Checkpoint bytes mismatch')
    return old, dependency_before


def checkpoint_new(accepted, old, before, dependency_before):
    if not node_exists(LIVE_CHECKPOINTS):
        mkdir_new(LIVE_CHECKPOINTS, 0o700)
    existing_private(LIVE_CHECKPOINTS)
    fd = directory(LIVE_CHECKPOINTS, 0, private=True)
    try:
        names = os.listdir(fd)
        if len(names) >= 4:
            raise ValueError('Checkpoint quota reached')
        total = 0
        for name in names:
            if re.fullmatch('[A-Za-z0-9_-]{1,80}', name) is None:
                raise ValueError('Unknown checkpoint evidence')
            path = LIVE_CHECKPOINTS / name
            existing_private(path)
            checkpoint_files = {'helper.before': 1048576, 'broker-unit.before': 65536,
                                'accepted.before': 65536, 'proof.json': 65536, 'manifest.json': 65536}
            checkpoint_fd = directory(path, 0, private=True)
            try:
                if set(os.listdir(checkpoint_fd)) != set(checkpoint_files):
                    raise ValueError('Unknown retained checkpoint scope')
            finally:
                os.close(checkpoint_fd)
            retained = sum(len(read_file(path / child, owners=(0,), mode=0o600, limit=maximum))
                           for child, maximum in checkpoint_files.items())
            if retained > 1310720:
                raise ValueError('Retained checkpoint oversized')
            total += retained
            if total > 16777216:
                raise ValueError('Checkpoint byte quota reached')
    finally:
        os.close(fd)
    path = LIVE_CHECKPOINTS / ('live22-' + PACKET_SHA256)
    if node_exists(path):
        raise ValueError('Checkpoint collision')
    data = {'helper.before': old, 'broker-unit.before': before, 'accepted.before': accepted,
            'proof.json': encode(proof_value(dependency_before)), 'manifest.json': PACKET_MANIFEST_SNAPSHOT}
    if sum(map(len, data.values())) > 1310720:
        raise ValueError('Checkpoint oversized')
    mkdir_new(path, 0o700)
    for name, raw in data.items():
        atomic_write(path / name, raw, 0o600, 0)
    sync_dir(path)
    sync_dir(LIVE_CHECKPOINTS)
    return path.name


def marker_write(value, stage, previous=None):
    if previous is not None and read_file(BOOTSTRAP_PENDING, owners=(0,), mode=0o600, limit=MAX_MANIFEST) != previous:
        raise ValueError('Marker changed')
    value = dict(value, stage=stage)
    raw = encode(value)
    atomic_write(BOOTSTRAP_PENDING, raw, 0o600, 0)
    return value, raw


def rollback_operation(commands, value, marker_raw, helper, before, after, blobs, old, dependency_before):
    root_inputs(helper, before, after)
    dependency_state(blobs, own=True, rollback=True)
    receipt = verify_receipt() if node_exists(LIVE_RECEIPT) else None
    value, marker_raw = marker_write(value, 'rollback', marker_raw)
    commands.stop()
    root_inputs(helper, before, after)
    dependency_state(blobs, own=True, rollback=True)
    atomic_write(HELPER, old, 0o755, 0)
    atomic_write(BROKER_UNIT, before, EXPECTED_RUNTIME_STAT_PINS['BROKER_UNIT_MODE'], 0)
    commands.call('daemon-reload')
    if dependency_before == 'absent':
        remove_dependency(blobs)
    else:
        dependency_inventory(SITE_PACKAGES)
    commands.start()
    _, actual_helper, actual_unit = root_inputs(helper, before, after)
    if actual_helper != old or actual_unit != before:
        raise ValueError('Rollback afterproof failed')
    if dependency_before == 'absent':
        if dependency_state(blobs, own=True) != 'A0':
            raise ValueError('Dependency before not restored')
    else:
        dependency_inventory(SITE_PACKAGES)
    if receipt is not None:
        remove_snapshot(LIVE_RECEIPT, receipt, 0o600)
    remove_snapshot(BOOTSTRAP_PENDING, marker_raw, 0o600)


def bootstrap():
    global _file_deadline
    # Verified snapshot carrier and all producer bindings precede even lock reads.
    helper, before, after, blobs = operation_inputs()
    if (len(sys.argv) != 1 or any(call() != 0 for call in (os.getuid, os.geteuid, os.getgid, os.getegid)) or
            any(name.startswith(('PYTHON', 'LD_')) for name in os.environ)):
        raise ValueError('Isolated root execution required')
    for name, expected in (('root', (0, 0)), ('dwl', (1000, 1000)), ('ai-panel', (993, 987))):
        account = pwd.getpwnam(name)
        if (account.pw_uid, account.pw_gid) != expected:
            raise ValueError('Account identity drift')
    _file_deadline = time.monotonic() + 120
    try:
        runtime_proof()
        existing_private(LOCK.parent)
        parent = directory(LOCK.parent, 0, private=True)
        lock = None
        try:
            lock = os.open(LOCK.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            same_identity(os.fstat(lock), EXPECTED_RUNTIME_STAT_PINS['LOCK'])
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            same_identity(os.stat(LOCK.name, dir_fd=parent, follow_symlinks=False), EXPECTED_RUNTIME_STAT_PINS['LOCK'])
            if node_exists(PACKAGE_PENDING) or node_exists(CONFIG_PENDING):
                raise ValueError('Other operation pending')
            pending = node_exists(BOOTSTRAP_PENDING)
            receipt = node_exists(LIVE_RECEIPT)
            if receipt and not pending:
                verify_receipt()
                after_proof(helper, before, after, blobs, completed=True)
                Commands().health()
                return None
            # Accepted4 with any marker is a refusal, never a downgrade.
            accepted, current_helper, unit = root_inputs(helper, before, after)
            if pending:
                marker_raw = read_file(BOOTSTRAP_PENDING, owners=(0,), mode=0o600, limit=MAX_MANIFEST)
                value = marker_value(marker_raw)
                old, dependency_before = checkpoint_read(value, before)
                if receipt:
                    verify_receipt()
                dependency_state(blobs, own=True, rollback=value['stage'] == 'rollback')
                if dependency_before != 'absent':
                    dependency_inventory(SITE_PACKAGES)
            else:
                if digest(current_helper) != OLD_HELPER_SHA256 or unit != before:
                    raise ValueError('Initial before mismatch')
                state = dependency_state(blobs)
                if state not in ('A0', 'A4'):
                    raise ValueError('Initial dependency mismatch')
                dependency_before = 'absent' if state == 'A0' else {'mode': 'preserved_exact', 'wheel_sha256': WHEEL_SHA256}
                if state == 'A4':
                    dependency_inventory(SITE_PACKAGES)
                old = current_helper
            commands = Commands()
            commands.health(stopped=pending)
            if not pending:
                checkpoint = checkpoint_new(accepted, old, before, dependency_before)
                value = {'schema': 2, 'operation': 'live22-bootstrap', 'packet_sha256': PACKET_SHA256,
                         'checkpoint': checkpoint, 'before_accepted_sha256': EXPECTED_ACCEPTED_SHA256, 'stage': 'prepared'}
                value, marker_raw = marker_write(value, 'prepared')
            if value['stage'] == 'rollback':
                rollback_operation(commands, value, marker_raw, helper, before, after, blobs, old, dependency_before)
                return None
            writes = False
            try:
                commands.stop()
                root_inputs(helper, before, after)
                dependency_state(blobs, own=True)
                value, marker_raw = marker_write(value, 'stopped', marker_raw)
                writes = True
                if dependency_before == 'absent':
                    install_dependency(blobs)
                else:
                    dependency_inventory(SITE_PACKAGES)
                value, marker_raw = marker_write(value, 'dependency', marker_raw)
                atomic_write(BROKER_UNIT, after, EXPECTED_RUNTIME_STAT_PINS['BROKER_UNIT_MODE'], 0)
                value, marker_raw = marker_write(value, 'unit', marker_raw)
                commands.call('daemon-reload')
                atomic_write(HELPER, helper, 0o755, 0)
                value, marker_raw = marker_write(value, 'helper', marker_raw)
                after_proof(helper, before, after, blobs)
                commands.start()
                value, marker_raw = marker_write(value, 'started', marker_raw)
                commands.smoke()
                after_proof(helper, before, after, blobs)
                if node_exists(LIVE_RECEIPT):
                    verify_receipt()
                else:
                    atomic_write(LIVE_RECEIPT, encode(expected_receipt()), 0o600, 0)
                verify_receipt()
                value, marker_raw = marker_write(value, 'complete', marker_raw)
                after_proof(helper, before, after, blobs)
                remove_snapshot(BOOTSTRAP_PENDING, marker_raw, 0o600)
                return None
            except Exception as exc:
                # Unknown drift never authorizes bounce, cleanup or rollback writes.
                root_inputs(helper, before, after)
                dependency_state(blobs, own=True)
                if writes or pending:
                    rollback_operation(commands, value, marker_raw, helper, before, after, blobs, old, dependency_before)
                else:
                    commands.start()
                    remove_snapshot(BOOTSTRAP_PENDING, marker_raw, 0o600)
                raise ValueError('Bootstrap failed after bounded recovery') from exc
        finally:
            if lock is not None:
                os.close(lock)
            os.close(parent)
    except (OSError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise ValueError('Bootstrap refused; evidence retained') from exc
    finally:
        _file_deadline = None


def entry():
    try:
        os.umask(0o077)
        bootstrap()
        return 0
    except Exception:
        print('Bootstrap refused; retained evidence requires review', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(entry())
