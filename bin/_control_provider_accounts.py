"""Owner-local, non-executable account catalog and immutable TASK admission.

No descriptor in this first slice has a verified execution runtime.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

LIMIT = 256 * 1024
ID = re.compile(r'[a-z][a-z0-9_-]{0,63}', re.ASCII)
# Fixed production descriptors; catalog values cannot select code or endpoints.
PROVIDERS = {'claude': {'engine': 'claude'}, 'codex': {'engine': 'codex'}}
CAPABILITIES = ('create_task', 'session_messages', 'images', 'files', 'questions', 'events')
BIDI = set(range(0x202a, 0x202f)) | set(range(0x2066, 0x206a)) | {0x200e, 0x200f, 0x061c}


class AccountError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _id(value):
    return isinstance(value, str) and ID.fullmatch(value) is not None


def validate_binding(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'provider_id', 'account_id'}
            or type(value['schema']) is not int or value['schema'] != 1
            or not _id(value['provider_id']) or not _id(value['account_id'])):
        raise AccountError('invalid_binding')
    return dict(value)


def check_binding_unchanged(previous, candidate):
    old = validate_binding(previous['provider_binding']) if 'provider_binding' in previous else None
    new = validate_binding(candidate['provider_binding']) if 'provider_binding' in candidate else None
    if old != new:
        raise AccountError('binding_immutable')
    # The account grant is scoped to this TASK identity and project. Keeping
    # the IDs while changing that scope would reroute an existing binding.
    if old is not None and any(previous.get(key) != candidate.get(key)
                               for key in ('incarnation', 'project_name')):
        raise AccountError('binding_immutable')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AccountError('catalog_invalid')
        result[key] = value
    return result


def _json(data):
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(AccountError('catalog_invalid')))
    except (ValueError, UnicodeError):
        raise AccountError('catalog_invalid') from None


def _open_directory(path, uid):
    """Anchor a directory through non-following FDs and validate every ancestor."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            writable = info.st_mode & 0o022
            sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_uid not in (0, uid) or (writable and not sticky_root):
                raise AccountError('catalog_unsafe')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _fixed_catalog():
    """The one installed directory pointer exception; never a leaf exception."""
    uid = os.getuid()
    pointer = Path.home() / '.config/ai-control'
    fd = None
    try:
        fd = _open_directory(pointer.parent, uid)
        info = os.stat(pointer.name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISLNK(info.st_mode):
            return pointer / 'provider-accounts.json', None
        if info.st_uid != uid:
            raise AccountError('catalog_unsafe')
        target = os.readlink(pointer.name, dir_fd=fd)
        canonical = Path(os.path.abspath(pointer.parent / target))
        target_fd = _open_directory(canonical, uid)
        try:
            target_info = os.fstat(target_fd)
            if target_info.st_uid != uid or target_info.st_mode & 0o022:
                raise AccountError('catalog_unsafe')
        finally:
            os.close(target_fd)
        after = os.stat(pointer.name, dir_fd=fd, follow_symlinks=False)
        if ((info.st_dev, info.st_ino, info.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_ctime_ns)
                or os.readlink(pointer.name, dir_fd=fd) != target):
            raise AccountError('catalog_unsafe')
        return canonical / 'provider-accounts.json', (info.st_dev, info.st_ino, info.st_ctime_ns, target)
    except FileNotFoundError:
        # Absent ordinary config means unconfigured; a broken pointer is unsafe.
        if os.path.islink(pointer):
            raise AccountError('catalog_unsafe') from None
        return pointer / 'provider-accounts.json', None
    except OSError:
        raise AccountError('catalog_unsafe') from None
    finally:
        if fd is not None:
            os.close(fd)


class ProviderAccounts:
    def __init__(self, catalog_path, project_names, *, owner_uid=None):
        self.path = Path(os.path.abspath(catalog_path))
        self.projects = set(project_names)
        self.uid = os.getuid() if owner_uid is None else owner_uid
        self.snapshot_identity = None

    def _read(self):
        # Walk pinned directory FDs: no symlink/path replacement can redirect the
        # open after validation. Root-owned sticky temp ancestors protect fixtures.
        fd = None
        try:
            fd = _open_directory(self.path.parent, self.uid)
            stream = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                before = os.fstat(stream)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid != self.uid
                        or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
                    raise AccountError('catalog_unsafe')
                chunks, total = [], 0
                while total <= LIMIT:
                    chunk = os.read(stream, min(65536, LIMIT + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                if total > LIMIT:
                    raise AccountError('catalog_invalid')
                after = os.fstat(stream)
                if any(getattr(before, field) != getattr(after, field) for field in
                       ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")):
                    raise AccountError('catalog_unsafe')
                data = b''.join(chunks)
                self.snapshot_identity = (before.st_dev, before.st_ino, before.st_mtime_ns,
                                          before.st_ctime_ns, hashlib.sha256(data).hexdigest())
            finally:
                os.close(stream)
        except FileNotFoundError:
            raise AccountError('catalog_unconfigured') from None
        except OSError:
            raise AccountError('catalog_unsafe') from None
        finally:
            if fd is not None:
                os.close(fd)
        doc = _json(data)
        if (not isinstance(doc, dict) or set(doc) != {'schema', 'accounts'}
                or type(doc['schema']) is not int or doc['schema'] != 1
                or not isinstance(doc['accounts'], list) or len(doc['accounts']) > 256):
            raise AccountError('catalog_invalid')
        seen, providers = set(), set()
        for row in doc['accounts']:
            if not isinstance(row, dict) or set(row) != {'provider_id', 'account_id', 'label', 'enabled', 'projects'}:
                raise AccountError('catalog_invalid')
            provider, account, label, projects = (row[k] for k in ('provider_id', 'account_id', 'label', 'projects'))
            if not _id(provider) or not _id(account) or account in seen or type(row['enabled']) is not bool:
                raise AccountError('catalog_invalid')
            if provider not in PROVIDERS:
                raise AccountError('unsupported_provider')
            if (not isinstance(label, str) or not label.strip() or len(label) > 80
                    or any(ord(c) < 32 or 127 <= ord(c) <= 159 or ord(c) in BIDI for c in label)
                    or '/' in label or '\\' in label or '~' in label
                    or re.search(r'[^\s@]+@[^\s@]+', label)):
                raise AccountError('catalog_invalid')
            if (not isinstance(projects, list) or not projects or not all(isinstance(p, str) for p in projects)
                    or len(set(projects)) != len(projects)
                    or ('*' in projects and projects != ['*'])
                    or any(p != '*' and p not in self.projects for p in projects)):
                raise AccountError('catalog_invalid')
            seen.add(account)
            providers.add(provider)
        if len(providers) > 32:
            raise AccountError('catalog_invalid')
        return doc['accounts']

    def _project(self, project):
        if project not in self.projects:
            raise AccountError('project_unknown')

    @staticmethod
    def _allowed(row, project):
        return '*' in row['projects'] or project in row['projects']

    @staticmethod
    def _dto(row):
        return {**{k: row[k] for k in ('provider_id', 'account_id', 'label')},
                'status': 'runtime_unverified' if row['enabled'] else 'disabled',
                'capabilities': {k: bool(row['enabled']) if k == 'create_task' else False for k in CAPABILITIES}}

    def list_accounts(self, project):
        self._project(project)
        return [self._dto(r) for r in sorted(self._read(), key=lambda r: (r['provider_id'], r['account_id']))
                if self._allowed(r, project)]

    def resolve(self, provider_id, account_id, project):
        self._project(project)
        rows = self._read()
        if provider_id not in PROVIDERS:
            raise AccountError('unsupported_provider')
        for row in rows:
            if row['provider_id'] == provider_id and row['account_id'] == account_id:
                if not self._allowed(row, project):
                    raise AccountError('account_forbidden')
                if not row['enabled']:
                    raise AccountError('account_disabled')
                return self._dto(row)
        raise AccountError('account_unknown')


class _ProductionProviderAccounts(ProviderAccounts):
    def __init__(self, project_names):
        path, self.pointer_identity = _fixed_catalog()
        super().__init__(path, project_names)

    def _read(self):
        path, pin = _fixed_catalog()
        if path != self.path or pin != self.pointer_identity:
            raise AccountError('catalog_unsafe')
        rows = super()._read()
        after_path, after_pin = _fixed_catalog()
        if (after_path, after_pin) != (path, pin):
            raise AccountError('catalog_unsafe')
        self.snapshot_identity = (*self.snapshot_identity, pin)
        return rows


def production_reader():
    # Reuse the existing YAML resolver rather than creating another registry plane.
    helper = str(Path(__file__).with_name('_rc_projects.sh'))
    try:
        result = subprocess.run(['bash', '-c', '. "$1"; project_names', '_', helper],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise AccountError('project_unknown')
        names = result.stdout.splitlines()
        paths = {}
        for name in names:
            result = subprocess.run(['bash', '-c', '. "$1"; project_path "$2"', '_', helper, name],
                                    capture_output=True, text=True, timeout=10)
            path = result.stdout.rstrip('\n')
            if result.returncode or not path or not os.path.isdir(path):
                raise AccountError('project_unknown')
            paths[name] = os.path.realpath(path)
    except (OSError, subprocess.SubprocessError):
        raise AccountError('project_unknown') from None
    return _ProductionProviderAccounts(names), paths


def _control(agent_dir):
    # Shared authoritative validator, including incarnation, runs before admission.
    try:
        result = subprocess.run([str(Path(__file__).with_name('ai-agent-io')), 'control-read', str(agent_dir)],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        raise AccountError('invalid_binding') from None
    if result.returncode:
        raise AccountError('invalid_binding')
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise AccountError('invalid_binding') from None


def execution_gate(agent_dir):
    control = _control(agent_dir)
    if 'provider_binding' not in control:
        return
    binding = validate_binding(control['provider_binding'])
    reader, _ = production_reader()
    reader.resolve(binding['provider_id'], binding['account_id'], control.get('project_name'))
    raise AccountError('runtime_unverified')


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest='command', required=True)
    listing = subs.add_parser('list')
    listing.add_argument('--project', required=True)
    listing.add_argument('--json', action='store_true')
    admission = subs.add_parser('create-check')
    admission.add_argument('provider'); admission.add_argument('account'); admission.add_argument('project_path')
    for cmd in ('gate', 'status', 'legacy-check'):
        subs.add_parser(cmd).add_argument('agent_dir')
    args = parser.parse_args()
    try:
        if args.command == 'gate':
            execution_gate(args.agent_dir)
        elif args.command in ('status', 'legacy-check'):
            control = _control(args.agent_dir)
            if 'provider_binding' not in control:
                if args.command == 'status':
                    print('binding=legacy-unbound')
                return
            binding = validate_binding(control['provider_binding'])
            if args.command == 'legacy-check':
                raise AccountError('binding_immutable')
            prefix = 'binding=%s/%s' % (binding['provider_id'], binding['account_id'])
            try:
                reader, _ = production_reader()
                rows = reader.list_accounts(control.get('project_name'))
                dto = next((r for r in rows if r['provider_id'] == binding['provider_id']
                            and r['account_id'] == binding['account_id']), None)
                if dto is None:
                    reader.resolve(binding['provider_id'], binding['account_id'], control.get('project_name'))
                print('%s label=%s status=%s' % (prefix, dto['label'], dto['status']))
            except AccountError as exc:
                print('%s status=%s' % (prefix, exc.code))
        else:
            reader, paths = production_reader()
            if args.command == 'list':
                rows = reader.list_accounts(args.project)
                if args.json:
                    print(json.dumps({'schema': 1, 'accounts': rows}, ensure_ascii=False))
                else:
                    for row in rows:
                        print('%s/%s %s %s' % (row['provider_id'], row['account_id'], row['label'], row['status']))
            else:
                project = next((name for name, path in paths.items() if path == os.path.realpath(args.project_path)), None)
                reader.resolve(args.provider, args.account, project)
                print(json.dumps({'project_name': project, 'snapshot': reader.snapshot_identity,
                                  'engine': PROVIDERS[args.provider]['engine']}))
    except AccountError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    except (OSError, ValueError, subprocess.SubprocessError):
        print('invalid_binding', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
