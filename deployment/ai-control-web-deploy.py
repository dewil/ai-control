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
MODES = LIVE_MODES
SCHEMAS = {1: LEGACY_MODES, 2: CURRENT_MODES, 3: APP_MODES, 4: LIVE_MODES}
LIVE_RECEIPT = Path('/var/lib/ai-control-deploy/live-bootstrap-complete.json')
BROKER_UNIT = Path('/etc/systemd/system/ai-control-web-broker.service')
HELPER = Path('/usr/local/sbin/ai-control-deploy')
SITE_PACKAGES = Path('/opt/ai-control-web/venv/lib/python3.12/site-packages')
DEP_PACKAGE = SITE_PACKAGES / 'nats'
DEP_INFO = SITE_PACKAGES / 'nats_py-2.9.0.dist-info'
BOOTSTRAP_BASE = {'bin/ai-control-web': '2dbe492440a9e01f73468f2220a4e8b8b908fab2ea8c6a13a55d79409730f4e7', 'bin/_control_web.py': 'a0724ec2c3a505fdc123b96c90a178657e835562ce6b018ea34b8214e6617e8a', 'bin/_control_web_broker.py': 'c4f6f69e0c9d258c07f0138c192e35e99b30254485e078e4403acf5c9bc994e6', 'bin/_control_web_sessions.py': '978847a34320fb381f4bad2848a8832274c4dc34d7f816b9173d4e39e4bc510a', 'bin/_codex_rc.py': '8113bff19a607e9d0dd84af387a4aa700bb2dbfcd3223dc01a6d7c6cd8b6c3e6', 'bin/_rc_projects.sh': '8576c2c5aa4d0c5c24b9efee6ceeb3a9c46882724d6796acbce4a20246a6b2e6', 'bin/_control_web.html': '210ea89cdf6724f0f920cc39fc279a66477d8f08cfa10be1d4dda31862ce5b7f', 'bin/_control_web.css': '5a59c6251dbd376a73f0814ec094747b0a3413cfe80c15e94bbf1cb6dcb170de', 'bin/_control_web.js': 'be0f799ff9ba72b5d22a602b24919c3360d693a4b43ad24e15b1204eb7a55e15', 'requirements-web.lock': 'c56ca5ea2670d01dac8c1d3daa8ee204323bacb29e8a347a749c987a6615d222', 'systemd/ai-control-web.service.tmpl': 'ae73cbaf5dc9c6f35d973573a1a18b0ce451b9142c0c22ab8cc4f87b4b80c641', 'systemd/ai-control-web-broker.service.tmpl': '1bd0ad1c78d98b22245ace274c9b96a59159f0b14f6669b4e09076f87cd53434', 'bin/_control_web.svg': '2a6b140eb1e60610f61aeb3941241bab9121cc4f6f5b31e42d7da8743a2c79e9'}

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
            fresh = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
                      'st_size', 'st_mtime_ns', 'st_ctime_ns')
            if any(getattr(info, field) != getattr(value, field)
                   for value in (os.fstat(child), fresh) for field in fields):
                raise Rejected('Snapshot changed')
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


def scope(files):
    if type(files) is dict and set(files) == set(LEGACY_MODES):
        return LEGACY_MODES
    if type(files) is dict:
        for modes in (CURRENT_MODES, APP_MODES, LIVE_MODES):
            if set(files) == set(modes):
                return modes
    raise Rejected('Invalid fixed scope')


def hashes(value):
    scope(value)
    for item in value.values():
        if type(item) is not str or re.fullmatch('[0-9a-f]{64}', item) is None:
            raise Rejected('Invalid digest')


def state_value(value):
    keys(value, ('schema', 'release_id', 'manifest_sha256', 'files'))
    if type(value['schema']) is not int or value['schema'] not in SCHEMAS:
        raise Rejected('Invalid state schema')
    integer(value['release_id'], 0 if value['schema'] == 1 else 1)
    keys(value['files'], SCHEMAS[value['schema']])
    hashes(value['files'])
    sha = value['manifest_sha256']
    if value['release_id'] == 0:
        if sha is not None or value['files'] != BOOTSTRAP_BASE:
            raise Rejected('Invalid bootstrap state')
    elif type(sha) is not str or re.fullmatch('[0-9a-f]{64}', sha) is None:
        raise Rejected('Invalid state digest')
    return value


def leaf_absent(target, owner_uid, leaf):
    if leaf not in (NEW_LEAF, *APP_LEAVES, *LIVE_LEAVES):
        raise Rejected('Unknown transition leaf path')
    parent = directory(Path(target) / Path(leaf).parent, owner_uid)
    try:
        try:
            os.stat(Path(leaf).name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise Rejected('Unexpected new leaf')
    finally:
        os.close(parent)


def new_leaf_absent(target, owner_uid):
    leaf_absent(target, owner_uid, NEW_LEAF)


def outside_absent(target, owner_uid, modes):
    for leaf in MODES.keys() - modes.keys():
        leaf_absent(target, owner_uid, leaf)


def tree(target, owner_uid, modes=MODES):
    if not any(modes is known for known in SCHEMAS.values()):
        raise Rejected('Invalid fixed scope')
    for relative in ('', 'bin', 'systemd'):
        os.close(directory(Path(target) / relative, owner_uid))
    return {path: read_file(Path(target) / path, owners=(owner_uid,), mode=mode)
            for path, mode in modes.items()}


def tree_hashes(payload):
    return {path: digest(data) for path, data in payload.items()}


def initialize_state(target, state_path, *, owner_uid=0):
    """Operator-only bootstrap: authenticate compiled baseline, never overwrite."""
    state_path = Path(state_path)
    os.close(directory(state_path.parent, owner_uid, private=True))
    if os.path.lexists(state_path):
        raise Rejected('State already exists')
    outside_absent(target, owner_uid, LEGACY_MODES)
    if tree_hashes(tree(target, owner_uid, LEGACY_MODES)) != BOOTSTRAP_BASE:
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
        self.rollback_used = False

    def ctl(self, *args):
        return self.runner(['/usr/bin/systemctl', *args]).strip()

    def services(self, *, live=True):
        # Historical journals retain their accepted identity-only query protocol.
        # Only schema4 forward paths require effective Fragment/DropIn proof.
        if not live:
            for service, user in zip(SERVICES, ('ai-panel', 'dwl')):
                if (self.ctl('is-active', service) != 'active' or
                        self.ctl('show', service, '-p', 'User', '--value') != user or
                        self.ctl('show', service, '-p', 'Group', '--value') != 'ai-panel'):
                    raise Rejected('Service health or account mismatch')
            return
        for service, user in zip(SERVICES, ('ai-panel', 'dwl')):
            if self.ctl('is-active', service) != 'active':
                raise Rejected('Service is not active')
            text = self.ctl('show', service, '--property=' + ','.join(SAFE_PROPERTIES))
            observed = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
            expected = {'User': user, 'Group': 'ai-panel',
                        'ProtectSystem': 'strict' if service == SERVICES[0] else 'full',
                        'ProtectHome': 'yes' if service == SERVICES[0] else 'no',
                        'FragmentPath': '/etc/systemd/system/' + service, 'DropInPaths': ''}
            if any(observed.get(key) != value for key, value in expected.items()):
                raise Rejected('Service identity or effective unit mismatch')
            if service == SERVICES[0] and (observed.get('ReadWritePaths') != '/run/ai-control-web /var/lib/ai-control-web'
                    or observed.get('InaccessiblePaths') != '/data'):
                raise Rejected('Frontend sandbox mismatch')

    def live_gate(self):
        try:
            receipt = decode(read_file(LIVE_RECEIPT, owners=(self.owner_uid,), limit=MAX_MANIFEST,
                                       mode=0o600, private_parent=True))
            keys(receipt, ('schema', 'operation', 'packet_sha256', 'accepted_before_sha256',
                           'helper_sha256', 'unit_sha256', 'wheel_sha256', 'dependency_inventory_sha256'))
            if type(receipt['schema']) is not int or receipt['schema'] != 1 or receipt['operation'] != 'live22-bootstrap':
                raise Rejected('Invalid bootstrap receipt')
            for key in set(receipt) - {'schema', 'operation'}:
                if type(receipt[key]) is not str or re.fullmatch('[0-9a-f]{64}', receipt[key]) is None:
                    raise Rejected('Invalid receipt digest')
            if (receipt['wheel_sha256'] != WHEEL_SHA256 or
                    receipt['dependency_inventory_sha256'] != WHEEL_INVENTORY_SHA256):
                raise Rejected('Receipt inventory mismatch')
            dependency_inventory(SITE_PACKAGES, owner_uid=self.owner_uid)
            unit_mode = stat.S_IMODE(BROKER_UNIT.lstat().st_mode)
            if unit_mode not in (0o600, 0o644):
                raise Rejected('Unsafe actual broker unit')
            if digest(read_file(BROKER_UNIT, owners=(self.owner_uid,), mode=unit_mode, limit=MAX_MANIFEST)) != receipt['unit_sha256']:
                raise Rejected('Actual broker unit mismatch')
            if digest(read_file(HELPER, owners=(self.owner_uid,), mode=0o755, limit=1024*1024)) != receipt['helper_sha256']:
                raise Rejected('Actual helper mismatch')
        except (OSError, ValueError, TypeError) as exc:
            raise Rejected('Live bootstrap proof failed') from exc

    def stop(self):
        for service in SERVICES:
            self.ctl('stop', service)

    def start(self, *, live=True):
        self.ctl('start', SERVICES[1])
        self.ctl('start', SERVICES[0])
        self.services(live=live)

    def read_state(self):
        raw = read_file(self.state_path, owners=(self.owner_uid,),
                        limit=MAX_MANIFEST, mode=0o600, private_parent=True)
        value = state_value(decode(raw))
        self.accepted_raw = raw
        return value

    def publish(self, state):
        atomic_write(self.state_path, encode(state), 0o600, self.owner_uid)

    def install(self, payload):
        for path in MODES:
            if path not in payload:
                continue
            data = payload[path]
            atomic_write(self.target / path, data, MODES[path], self.owner_uid)

    def match(self, expected):
        outside_absent(self.target, self.owner_uid, scope(expected))
        if tree_hashes(tree(self.target, self.owner_uid, scope(expected))) != expected:
            raise Rejected('Installed tree mismatch')

    def clear_pending(self):
        fd = directory(self.checkpoints, self.owner_uid, private=True)
        try:
            os.unlink('pending.json', dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)

    def transition_leaf(self, expected, remove=False, leaf=NEW_LEAF):
        """Only a closed transition leaf may be removed after anchored proof."""
        if leaf not in (NEW_LEAF, *APP_LEAVES, *LIVE_LEAVES):
            raise Rejected('Unknown transition leaf path')
        parent = directory(self.target / Path(leaf).parent, self.owner_uid)
        child = None
        try:
            try:
                child = os.open(Path(leaf).name,
                                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=parent)
            except FileNotFoundError:
                return None
            info = os.fstat(child)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != self.owner_uid
                    or (self.owner_uid == 0 and info.st_gid != 0)
                    or stat.S_IMODE(info.st_mode) != MODES[leaf]
                    or info.st_size > MAX_FILE):
                raise Rejected('Unsafe transition leaf')
            chunks, total = [], 0
            while True:
                chunk = os.read(child, min(65536, MAX_FILE + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_FILE:
                    raise Rejected('Oversized transition leaf')
            sha = digest(b''.join(chunks))
            if sha != expected:
                raise Rejected('Unknown transition leaf')
            if remove:
                fresh = os.stat(Path(leaf).name, dir_fd=parent,
                                follow_symlinks=False)
                if (fresh != os.fstat(child) or any(
                        getattr(fresh, field) != getattr(info, field)
                        for field in ('st_dev', 'st_ino', 'st_mode', 'st_nlink',
                                      'st_uid', 'st_gid', 'st_size',
                                      'st_mtime_ns', 'st_ctime_ns'))):
                    raise Rejected('Transition leaf changed')
                os.unlink(Path(leaf).name, dir_fd=parent)
                os.fsync(parent)
            return sha
        finally:
            if child is not None:
                os.close(child)
            os.close(parent)

    def interrupted_tree(self, before, after):
        modes = scope(before['files'])
        current = tree_hashes(tree(self.target, self.owner_uid, modes))
        if any(current[path] not in (before['files'][path], after['files'][path])
               for path in modes):
            raise Rejected('Unknown bytes in interrupted tree')
        for leaf in MODES.keys() - modes.keys():
            if leaf in after['files']:
                sha = self.transition_leaf(after['files'][leaf], leaf=leaf)
                if sha is not None:
                    current[leaf] = sha
            else:
                leaf_absent(self.target, self.owner_uid, leaf)
        return current

    def rollback(self, before, old, after, raw):
        if self.rollback_used:
            raise RollbackFailed('Rollback budget exhausted; pending journal retained')
        # Validation failures and timeouts also consume the single attempt.
        self.rollback_used = True
        if not os.path.lexists(self.pending):
            raise RollbackFailed('No pending journal authorizes rollback')
        try:
            self.interrupted_tree(before, after)
            self.stop()
            for leaf in after['files'].keys() - before['files'].keys():
                self.transition_leaf(after['files'][leaf], remove=True, leaf=leaf)
            self.install(old)
            self.start(live=before['schema'] == 4)
            self.match(before['files'])
            atomic_write(self.state_path, raw, 0o600, self.owner_uid)
            self.accepted_raw = raw
            self.clear_pending()
        except Exception as exc:
            raise RollbackFailed('Rollback failed; pending journal retained') from exc

    def recover(self, accepted):
        if not os.path.lexists(self.pending):
            return accepted
        journal = decode(read_file(self.pending, owners=(self.owner_uid,),
                                   limit=MAX_MANIFEST, mode=0o600, private_parent=True))
        keys(journal, ('schema', 'before', 'after', 'checkpoint'))
        if type(journal['schema']) is not int or journal['schema'] not in SCHEMAS:
            raise Rejected('Invalid journal schema')
        before, after = state_value(journal['before']), state_value(journal['after'])
        pairs = {1: {(1, 1)}, 2: {(1, 2), (2, 2)}, 3: {(2, 3), (3, 3)}, 4: {(3, 4), (4, 4)}}
        if ((before['schema'], after['schema']) not in pairs[journal['schema']]
                or after['release_id'] <= before['release_id']
                or accepted not in (before, after)):
            raise Rejected('Journal state mismatch')
        name = journal['checkpoint']
        if type(name) is not str or re.fullmatch('[a-zA-Z0-9_-]+', name) is None:
            raise Rejected('Invalid checkpoint name')
        checkpoint = self.checkpoints / name
        os.close(directory(checkpoint, self.owner_uid, private=True))
        raw = read_file(checkpoint / 'accepted.json', owners=(self.owner_uid,),
                        limit=MAX_MANIFEST, mode=0o600, private_parent=True)
        if state_value(decode(raw)) != before:
            raise Rejected('Checkpoint state mismatch')
        old = {path: read_file(checkpoint / Path(path).name, owners=(self.owner_uid,),
                              mode=0o600, private_parent=True) for path in scope(before['files'])}
        if tree_hashes(old) != before['files']:
            raise Rejected('Checkpoint bytes mismatch')
        current = self.interrupted_tree(before, after)
        if accepted == after and current == after['files']:
            try:
                if after['schema'] == 4:
                    self.live_gate()
                self.services(live=after['schema'] == 4)
            except Exception:
                pass
            else:
                # A prior process may have died after replace but before fsync.
                atomic_write(self.state_path, self.accepted_raw, 0o600, self.owner_uid)
                self.clear_pending()
                return after
        self.rollback(before, old, after, raw)
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
        if type(manifest['schema']) is not int or manifest['schema'] != 4:
            raise Rejected('Invalid release schema')
        integer(manifest['release_id'], 1)
        hashes(manifest['base'])
        if scope(manifest['base']) not in (APP_MODES, LIVE_MODES):
            raise Rejected('Invalid staged base scope')
        keys(manifest['files'], MODES)
        expected = {}
        for path, item in manifest['files'].items():
            keys(item, ('sha256', 'mode'))
            if type(item['mode']) is not int or item['mode'] != MODES[path]:
                raise Rejected('Invalid payload mode')
            expected[path] = item['sha256']
        hashes(expected)
        payload = {path: read_file(self.stage / path, owners=owners) for path in MODES}
        if sum(map(len, payload.values())) > 32 * 1024 * 1024 or tree_hashes(payload) != expected:
            raise Rejected('Payload digest mismatch')
        return manifest, raw, payload, expected

    def run(self):
        try:
            # No implicit accepted state initialization, including on recovery.
            os.close(directory(self.state_path.parent, self.owner_uid, private=True))
            os.close(directory(self.checkpoints.parent, self.owner_uid))
            self.checkpoints.mkdir(mode=0o700, exist_ok=True)
            parent = directory(self.checkpoints.parent, self.owner_uid)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
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
        # A reused library instance still represents a fresh operator invocation.
        self.rollback_used = False
        for name in ('bootstrap-pending.json', 'config-pending.json'):
            if os.path.lexists(self.state_path.parent / name):
                raise Rejected('Separate operation pending')
        before = self.recover(self.read_state())
        outside_absent(self.target, self.owner_uid, scope(before['files']))
        original = tree(self.target, self.owner_uid, scope(before['files']))
        if tree_hashes(original) != before['files']:
            raise Rejected('Accepted tree drift')
        manifest, raw, payload, expected = self.staged()
        release = manifest['release_id']
        sha = digest(raw)
        if release < before['release_id']:
            raise Rejected('Release replay')
        if release == before['release_id']:
            if before['schema'] != 4 or sha != before['manifest_sha256'] or expected != before['files']:
                raise Rejected('Release identity reused')
            self.live_gate()
            self.services()
            return {'result': 'already_installed', 'release_id': release}
        if before['schema'] not in (3, 4):
            raise Rejected('Only accepted16 or accepted22 may advance')
        if manifest['base'] != before['files']:
            raise Rejected('Signed base mismatch')
        self.live_gate()
        after = {'schema': 4, 'release_id': release, 'manifest_sha256': sha, 'files': expected}
        self.services()
        basenames = [Path(path).name for path in original] + ['accepted.json']
        if len(set(basenames)) != len(basenames):
            raise Rejected('Checkpoint basename collision')
        checkpoint = Path(tempfile.mkdtemp(prefix='release-', dir=self.checkpoints))
        os.chmod(checkpoint, 0o700)
        for path, data in original.items():
            atomic_write(checkpoint / Path(path).name, data, 0o600, self.owner_uid)
        atomic_write(checkpoint / 'accepted.json', self.accepted_raw, 0o600, self.owner_uid)
        for path in (checkpoint, self.checkpoints):
            fd = directory(path, self.owner_uid, private=True)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        journal = {'schema': 4, 'before': before, 'after': after, 'checkpoint': checkpoint.name}
        atomic_write(self.pending, encode(journal), 0o600, self.owner_uid)
        try:
            self.match(before['files'])
            self.stop()
            self.match(before['files'])
            self.install(payload)
            self.start()
            self.match(expected)
            self.live_gate()
            self.publish(after)
            self.live_gate()
        except Exception as exc:
            if self.rollback_used:
                # Pending recovery already spent this invocation's one attempt.
                # The new checkpoint/journal authorizes a later recovery only.
                raise RollbackFailed('Rollback budget exhausted; new pending journal retained') from exc
            self.rollback(before, original, after, self.accepted_raw)
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
