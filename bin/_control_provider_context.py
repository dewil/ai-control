"""Private profile metadata and immutable references, never native admission.

Derived paths are metadata only. A native host still needs a proven kernel-bound
profile view and native identity; this library neither opens credentials nor
enables execution capabilities.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
import uuid

from _control_provider_accounts import AccountError, _id, validate_binding

LIMIT = 16 * 1024
ADAPTER = 'codex-managed-chatgpt-file-v1'
INPUT_KEYS = {'schema', 'adapter_revision', 'auth_source', 'credential_store',
              'expected_native_principal'}
REF_KEYS = {'schema', 'provider_id', 'account_id', 'profile_instance_id',
            'adapter_revision', 'registration_snapshot'}
REGISTRATION_KEYS = INPUT_KEYS | {'provider_id', 'account_id',
                                 'profile_instance_id', 'profile_objects'}


def _uuid(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
        return str(parsed) == value and parsed.version == 4 and parsed.variant == uuid.RFC_4122
    except ValueError:
        return False


def _integers(value, keys):
    return (isinstance(value, dict) and set(value) == set(keys)
            and all(type(value[k]) is int and value[k] >= 0 for k in keys))


def validate_context_ref(value):
    """Validate private authority and return a copy with no mutable aliases."""
    if (not isinstance(value, dict) or set(value) != REF_KEYS
            or type(value['schema']) is not int or value['schema'] != 1
            or value['provider_id'] != 'codex' or not _id(value['account_id'])
            or not _uuid(value['profile_instance_id']) or value['adapter_revision'] != ADAPTER):
        raise AccountError('context_invalid')
    snapshot = value['registration_snapshot']
    if (not isinstance(snapshot, dict) or set(snapshot) != {'dev', 'ino', 'ctime_ns', 'sha256'}
            or not _integers({k: snapshot[k] for k in ('dev', 'ino', 'ctime_ns')},
                             ('dev', 'ino', 'ctime_ns'))
            or not isinstance(snapshot['sha256'], str)
            or re.fullmatch('[0-9a-f]{64}', snapshot['sha256'], re.ASCII) is None):
        raise AccountError('context_invalid')
    return {**value, 'registration_snapshot': dict(snapshot)}


def check_context_unchanged(previous, candidate):
    """Whole-control CAS: an existing incarnation cannot add or reroute context."""
    if not isinstance(previous, dict) or not isinstance(candidate, dict):
        raise AccountError('context_invalid')
    old = validate_context_ref(previous['provider_context']) if 'provider_context' in previous else None
    new = validate_context_ref(candidate['provider_context']) if 'provider_context' in candidate else None
    if old != new:
        raise AccountError('context_immutable')
    if old is not None:
        for control in (previous, candidate):
            try:
                binding = validate_binding(control.get('provider_binding'))
            except AccountError:
                raise AccountError('context_invalid') from None
            if any(binding[k] != old[k] for k in ('provider_id', 'account_id')):
                raise AccountError('context_invalid')
        if any(previous.get(k) != candidate.get(k) for k in ('incarnation', 'project_name')):
            raise AccountError('context_immutable')


@dataclass(frozen=True, repr=False)
class ExecutionContext:
    reference: object = field(repr=False)
    native_home: Path = field(repr=False)
    child_home: Path = field(repr=False)
    child_env: object = field(repr=False)
    expected_native_principal: object = field(repr=False)

    def __post_init__(self):
        reference = validate_context_ref(self.reference)
        reference['registration_snapshot'] = MappingProxyType(reference['registration_snapshot'])
        object.__setattr__(self, 'reference', MappingProxyType(reference))
        if (not isinstance(self.native_home, Path) or not self.native_home.is_absolute()
                or not isinstance(self.child_home, Path) or not self.child_home.is_absolute()):
            raise AccountError('context_invalid')
        environment = dict(self.child_env)
        if environment != {'HOME': str(self.child_home), 'CODEX_HOME': str(self.native_home),
                           'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}:
            raise AccountError('context_invalid')
        try:
            principal = _principal(self.expected_native_principal)
        except AccountError:
            raise AccountError('context_invalid') from None
        object.__setattr__(self, 'child_env', MappingProxyType(environment))
        object.__setattr__(self, 'expected_native_principal', MappingProxyType(principal))


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AccountError('profile_invalid')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(AccountError('profile_invalid')))
    except (ValueError, UnicodeError, RecursionError):
        raise AccountError('profile_invalid') from None


def _input(value):
    if (not isinstance(value, dict) or set(value) != INPUT_KEYS
            or type(value['schema']) is not int or value['schema'] != 1
            or value['adapter_revision'] != ADAPTER or value['auth_source'] != 'managed_chatgpt'
            or value['credential_store'] != 'file'):
        raise AccountError('profile_invalid')
    return {**value, 'expected_native_principal': _principal(value['expected_native_principal'])}


def _principal(principal):
    if (not isinstance(principal, dict) or set(principal) != {'kind', 'value'}
            or principal['kind'] != 'chatgpt_account_id' or not isinstance(principal['value'], str)
            or re.fullmatch('[A-Za-z0-9_-]{1,128}', principal['value'], re.ASCII) is None):
        raise AccountError('profile_invalid')
    return dict(principal)


def _identity(info):
    return {'dev': info.st_dev, 'ino': info.st_ino}


def _pin(info):
    return tuple(getattr(info, k) for k in ('st_dev', 'st_ino', 'st_mode', 'st_uid',
                                          'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


class _Directories:
    """Keep the full no-follow ancestor chain open, then recheck its links."""
    def __init__(self, uid):
        self.uid, self.entries = uid, []
        self.base = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    def close(self):
        for _, _, fd, _ in reversed(self.entries):
            os.close(fd)
        os.close(self.base)

    def child(self, parent, name, private=False):
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=parent)
        try:
            info = os.fstat(fd)
            sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if (info.st_uid not in (0, self.uid) or (info.st_mode & 0o022 and not sticky_root)
                    or (private and (info.st_uid != self.uid or stat.S_IMODE(info.st_mode) != 0o700))):
                raise AccountError('profile_unsafe')
            self.entries.append((parent, name, fd, info))
            return fd
        except BaseException:
            os.close(fd)
            raise

    def walk(self, path):
        fd = self.base
        for part in path.parts[1:]:
            fd = self.child(fd, part)
        return fd

    def check(self, changed_directory=None):
        changed = _identity(os.fstat(changed_directory)) if changed_directory is not None else None
        for parent, name, fd, before in self.entries:
            live = os.stat(name, dir_fd=parent, follow_symlinks=False)
            current = os.fstat(fd)
            fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid')
            # Shared root-owned sticky directories can receive unrelated sibling
            # writes. Keep their object/mode/owner fences, not global timestamps.
            # Our account-root publication also legitimately changes timestamps.
            sticky_root = before.st_uid == 0 and before.st_mode & stat.S_ISVTX
            if _identity(before) != changed and not sticky_root:
                fields += ('st_mtime_ns', 'st_ctime_ns')
            if any(getattr(before, k) != getattr(info, k) for info in (live, current) for k in fields):
                raise AccountError('profile_unsafe')


def _read_leaf(directory, name, uid):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=directory)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
            raise AccountError('profile_unsafe')
        chunks, total = [], 0
        while total <= LIMIT:
            chunk = os.read(fd, min(4096, LIMIT + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > LIMIT:
            raise AccountError('profile_invalid')
        after = os.fstat(fd)
        live = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if _pin(before) != _pin(after) or _pin(before) != _pin(live):
            raise AccountError('profile_unsafe')
        return b''.join(chunks), before
    finally:
        os.close(fd)


def _snapshot(data, info):
    return {'dev': info.st_dev, 'ino': info.st_ino, 'ctime_ns': info.st_ctime_ns,
            'sha256': hashlib.sha256(data).hexdigest()}


def _unlink_owned(directory, name, info):
    """Under the account-root lock, remove only our held-FD inode's name."""
    try:
        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if _identity(current) != _identity(info):
        return False
    os.unlink(name, dir_fd=directory)
    return True


class ProviderProfiles:
    def __init__(self, owner_home, accounts, *, owner_uid=None):
        self.home = Path(os.path.abspath(owner_home))
        self.accounts = accounts
        self.uid = os.getuid() if owner_uid is None else owner_uid

    def _grant(self, provider, account, project):
        validate_binding({'schema': 1, 'provider_id': provider, 'account_id': account})
        self.accounts.resolve(provider, account, project)
        if provider != 'codex':
            raise AccountError('unsupported_provider')
        return self.accounts.snapshot_identity

    def _recheck_grant(self, provider, account, project, snapshot):
        if self._grant(provider, account, project) != snapshot:
            raise AccountError('catalog_unsafe')

    @contextmanager
    def _profile(self, account, *, writing=False):
        directories = _Directories(self.uid)
        try:
            parent = directories.walk(self.home / '.local/share/ai-control')
            profiles = directories.child(parent, 'provider-profiles', private=True)
            provider = directories.child(profiles, 'codex', private=True)
            root = directories.child(provider, account, private=True)
            fcntl.flock(root, fcntl.LOCK_EX if writing else fcntl.LOCK_SH)
            # Another cooperating registration may have completed while waiting.
            # Rebase timestamps only after validating the original pinned object.
            directories.check(changed_directory=root)
            parent_fd, name, _, _ = directories.entries[-1]
            directories.entries[-1] = (parent_fd, name, root, os.fstat(root))
            codex = directories.child(root, 'codex', private=True)
            child_home = directories.child(root, 'native-home', private=True)
            objects = {key: _identity(os.fstat(fd)) for key, fd in
                       (('root', root), ('codex', codex), ('native_home', child_home))}
            if len({tuple(value.values()) for value in objects.values()}) != 3:
                raise AccountError('profile_unsafe')
            # Inspect directory identities only, never native profile contents.
            for other in os.listdir(provider):
                if other == account or not _id(other):
                    continue
                info = os.stat(other, dir_fd=provider, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode):
                    continue
                other_fd = os.open(other, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                   dir_fd=provider)
                try:
                    for name in (None, 'codex', 'native-home'):
                        try:
                            info = os.fstat(other_fd) if name is None else os.stat(
                                name, dir_fd=other_fd, follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        if stat.S_ISDIR(info.st_mode) and _identity(info) in objects.values():
                            raise AccountError('profile_unsafe')
                finally:
                    os.close(other_fd)
            directories.check()
            yield directories, root, objects
        except FileNotFoundError:
            raise AccountError('profile_unconfigured') from None
        except OSError:
            raise AccountError('profile_unsafe') from None
        finally:
            directories.close()

    def _registration(self, root, provider, account):
        data, info = _read_leaf(root, 'registration.json', self.uid)
        doc = _json(data)
        if not isinstance(doc, dict) or set(doc) != REGISTRATION_KEYS:
            raise AccountError('profile_invalid')
        _input({key: doc[key] for key in INPUT_KEYS})
        objects = doc['profile_objects']
        if (doc['provider_id'] != provider or doc['account_id'] != account
                or not _uuid(doc['profile_instance_id']) or not isinstance(objects, dict)
                or set(objects) != {'root', 'codex', 'native_home'}
                or not all(_integers(obj, ('dev', 'ino')) for obj in objects.values())):
            raise AccountError('profile_invalid')
        return doc, _snapshot(data, info)

    @staticmethod
    def _dto(doc):
        return {'schema': 1, **{key: doc[key] for key in ('provider_id', 'account_id', 'profile_instance_id')},
                'status': 'runtime_unverified', 'reason': 'native_identity_unproven'}

    def _check_leaf(self, root, provider, account, snapshot):
        _, current = self._registration(root, provider, account)
        if current != snapshot:
            raise AccountError('profile_unsafe')

    def register(self, provider_id, account_id, project, metadata_path):
        catalog = self._grant(provider_id, account_id, project)
        source = _Directories(self.uid)
        try:
            path = Path(os.path.abspath(metadata_path))
            base = self.home / '.local/share/ai-control/provider-profiles'
            if path.is_relative_to(base):
                parts = path.relative_to(base).parts
                if len(parts) >= 3 and parts[2] in ('codex', 'native-home'):
                    raise AccountError('profile_invalid')
            parent = source.walk(path.parent)
            data, info = _read_leaf(parent, path.name, self.uid)
            metadata = _input(_json(data))
            with self._profile(account_id, writing=True) as (directories, root, objects):
                try:
                    previous, snapshot = self._registration(root, provider_id, account_id)
                except FileNotFoundError:
                    previous = None
                if previous is not None:
                    if ({key: previous[key] for key in INPUT_KEYS} != metadata
                            or previous['profile_objects'] != objects):
                        raise AccountError('profile_conflict')
                    self._recheck_grant(provider_id, account_id, project, catalog)
                    source.check()
                    directories.check()
                    self._check_leaf(root, provider_id, account_id, snapshot)
                    if _snapshot(*_read_leaf(parent, path.name, self.uid)) != _snapshot(data, info):
                        raise AccountError('profile_unsafe')
                    return self._dto(previous)
                doc = {**metadata, 'provider_id': provider_id, 'account_id': account_id,
                       'profile_instance_id': str(uuid.uuid4()), 'profile_objects': objects}
                temp = '.registration-' + str(uuid.uuid4())
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=root)
                try:
                    os.fchmod(fd, 0o600)
                    payload = (json.dumps(doc, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
                    view = memoryview(payload)
                    while view:
                        view = view[os.write(fd, view):]
                    os.fsync(fd)
                    self._recheck_grant(provider_id, account_id, project, catalog)
                    source.check(changed_directory=root)
                    directories.check(changed_directory=root)
                    if _snapshot(*_read_leaf(parent, path.name, self.uid)) != _snapshot(data, info):
                        raise AccountError('profile_unsafe')
                    temp_data, temp_info = _read_leaf(root, temp, self.uid)
                    if temp_data != payload or _pin(os.fstat(fd)) != _pin(temp_info):
                        raise AccountError('profile_unsafe')
                    # link is atomic no-replace; a concurrent leaf is never overwritten.
                    try:
                        os.link(temp, 'registration.json', src_dir_fd=root, dst_dir_fd=root,
                                follow_symlinks=False)
                    except FileExistsError:
                        raise AccountError('profile_conflict') from None
                    if not _unlink_owned(root, temp, os.fstat(fd)):
                        raise AccountError('profile_unsafe')
                    published_info = os.fstat(fd)
                    os.fsync(root)
                    # Publication itself may race a grant, source or directory
                    # change. Success requires a fresh fence after the link.
                    self._recheck_grant(provider_id, account_id, project, catalog)
                    source.check(changed_directory=root)
                    directories.check(changed_directory=root)
                    if _snapshot(*_read_leaf(parent, path.name, self.uid)) != _snapshot(data, info):
                        raise AccountError('profile_unsafe')
                    published, published_snapshot = self._registration(root, provider_id, account_id)
                    if published != doc or published_snapshot != _snapshot(payload, published_info):
                        raise AccountError('profile_unsafe')
                    return self._dto(doc)
                except BaseException:
                    # Keep the FD open through rollback: UUID/parsed JSON is not
                    # ownership proof. Preserve a foreign replacement leaf.
                    rollback_failed = False
                    owned = os.fstat(fd)
                    for name in ('registration.json', temp):
                        try:
                            _unlink_owned(root, name, owned)
                        except OSError:
                            rollback_failed = True
                    try:
                        os.fsync(root)
                    except OSError:
                        rollback_failed = True
                    if rollback_failed:
                        # Persistent IO failure leaves unknown commit state; no
                        # success, automatic retry or durable-absence assertion.
                        raise AccountError('profile_unsafe') from None
                    raise
                finally:
                    os.close(fd)
        except FileNotFoundError:
            raise AccountError('profile_unconfigured') from None
        except OSError:
            raise AccountError('profile_unsafe') from None
        finally:
            source.close()

    def status(self, provider_id, account_id, project):
        catalog = self._grant(provider_id, account_id, project)
        with self._profile(account_id) as (directories, root, objects):
            doc, snapshot = self._registration(root, provider_id, account_id)
            if doc['profile_objects'] != objects:
                raise AccountError('profile_conflict')
            self._recheck_grant(provider_id, account_id, project, catalog)
            directories.check()
            self._check_leaf(root, provider_id, account_id, snapshot)
            return self._dto(doc)

    def resolve(self, binding, context_ref, project):
        binding = validate_binding(binding)
        if context_ref is None:
            raise AccountError('context_missing')
        reference = validate_context_ref(context_ref)
        if any(reference[key] != binding[key] for key in ('provider_id', 'account_id')):
            raise AccountError('context_invalid')
        provider, account = binding['provider_id'], binding['account_id']
        catalog = self._grant(provider, account, project)
        with self._profile(account) as (directories, root, objects):
            doc, snapshot = self._registration(root, provider, account)
            if (snapshot != reference['registration_snapshot'] or doc['profile_objects'] != objects
                    or doc['profile_instance_id'] != reference['profile_instance_id']
                    or doc['adapter_revision'] != reference['adapter_revision']):
                raise AccountError('context_drift')
            self._recheck_grant(provider, account, project, catalog)
            directories.check()
            _, current = self._registration(root, provider, account)
            if current != snapshot:
                raise AccountError('context_drift')
            profile = self.home / '.local/share/ai-control/provider-profiles/codex' / account
            native_home, child_home = profile / 'codex', profile / 'native-home'
            return ExecutionContext(reference, native_home, child_home,
                                    {'HOME': str(child_home), 'CODEX_HOME': str(native_home),
                                     'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                                    doc['expected_native_principal'])

    def capture_reference(self, binding, project):
        """Capture metadata authority for a new paused TASK, without native IO."""
        binding = validate_binding(binding)
        provider, account = binding['provider_id'], binding['account_id']
        catalog = self._grant(provider, account, project)
        with self._profile(account) as (directories, root, objects):
            doc, snapshot = self._registration(root, provider, account)
            if doc['profile_objects'] != objects:
                raise AccountError('profile_conflict')
            self._recheck_grant(provider, account, project, catalog)
            directories.check()
            self._check_leaf(root, provider, account, snapshot)
            return validate_context_ref({'schema': 1, 'provider_id': provider,
                                         'account_id': account,
                                         'profile_instance_id': doc['profile_instance_id'],
                                         'adapter_revision': doc['adapter_revision'],
                                         'registration_snapshot': snapshot})
