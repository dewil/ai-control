"""Internal paused-TASK metadata capture/check; stdout references are private."""
from contextlib import nullcontext
import json
import os
import re
from pathlib import Path
import sys

from _control_provider_accounts import AccountError, PROVIDERS, production_reader, validate_binding
from _control_provider_context import (ProviderProfiles, _Directories, _json, _read_leaf,
                                       validate_context_ref)


def _optional_reference(profiles, binding, project):
    if binding['provider_id'] != 'codex':
        return None
    try:
        return profiles.capture_reference(binding, project)
    except AccountError as error:
        leaf = (profiles.home / '.local/share/ai-control/provider-profiles/codex'
                / binding['account_id'] / 'registration.json')
        if error.code != 'profile_unconfigured' or os.path.lexists(leaf):
            raise
        return None


def main():
    try:
        command, provider, account, project, *extra = sys.argv[1:]
        if command not in ('capture', 'check', 'publish') or len(extra) != {
                'capture': 0, 'check': 1, 'publish': 3}.get(command):
            raise AccountError('context_invalid')
        binding = validate_binding({'schema': 1, 'provider_id': provider, 'account_id': account})
        accounts, _ = production_reader()
        accounts.resolve(provider, account, project)
        profiles = ProviderProfiles(Path.home(), accounts)
        if command == 'capture':
            reference = _optional_reference(profiles, binding, project)
            print(json.dumps(reference, separators=(',', ':')))
        else:
            reference = json.loads(sys.stdin.buffer.read(16 * 1024 + 1))
            guard = profiles.task_publication_guard(binding, reference, project) if command == 'publish' else nullcontext()
            with guard:
                directories = _Directories(os.getuid())
                try:
                    path = Path(os.path.abspath(extra[0]))
                    parent = directories.walk(path.parent)
                    data, info = _read_leaf(parent, path.name, os.getuid())
                    control = _json(data)
                    if (not isinstance(control, dict) or validate_binding(control.get('provider_binding')) != binding
                            or control.get('project_name') != project or control.get('desired') != 'paused'):
                        raise AccountError('context_invalid')
                    if reference is None:
                        if 'provider_context' in control:
                            raise AccountError('context_invalid')
                        if _optional_reference(profiles, binding, project) is not None:
                            raise AccountError('context_drift')
                    else:
                        reference = validate_context_ref(reference)
                        if validate_context_ref(control.get('provider_context')) != reference:
                            raise AccountError('context_drift')
                        profiles.resolve(binding, reference, project)
                    directories.check()
                    if command == 'publish':
                        final = Path(os.path.abspath(extra[1]))
                        expected = json.loads(extra[2])
                        if (path.name != 'control.json' or final.parent != path.parent.parent
                                or not path.parent.name.startswith('.new-' + final.name + '.')
                                or not isinstance(control.get('incarnation'), str)
                                or re.fullmatch('[0-9a-f]{32}', control['incarnation']) is None
                                or expected.get('project_name') != project
                                or expected.get('engine') != PROVIDERS[provider]['engine']):
                            raise AccountError('context_invalid')
                        accounts.resolve(provider, account, project)
                        if json.loads(json.dumps(accounts.snapshot_identity)) != expected.get('snapshot'):
                            raise AccountError('catalog_unsafe')
                        current, current_info = _read_leaf(parent, path.name, os.getuid())
                        if current != data or (current_info.st_dev, current_info.st_ino, current_info.st_ctime_ns) != (
                                info.st_dev, info.st_ino, info.st_ctime_ns):
                            raise AccountError('context_drift')
                        directories.check()
                        registry = directories.entries[-1][0]
                        if os.path.lexists(final):
                            raise AccountError('context_drift')
                        # The caller holds the stable TASK-name lock. Cooperating
                        # registration remains blocked across the atomic rename.
                        os.rename(path.parent.name, final.name, src_dir_fd=registry, dst_dir_fd=registry)
                finally:
                    directories.close()
    except AccountError as error:
        print(json.dumps({'schema': 1, 'error': {'code': error.code}}, separators=(',', ':')),
              file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print(json.dumps({'schema': 1, 'error': {'code': 'context_invalid'}}, separators=(',', ':')),
              file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
