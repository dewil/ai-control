"""Strict metadata-only profile registration CLI; no native admission."""
import json
from pathlib import Path
import subprocess
import sys

from _control_provider_accounts import AccountError, production_reader, validate_binding
from _control_provider_context import ProviderProfiles


def _arguments(arguments):
    if not arguments or arguments[0] not in ('register', 'status'):
        raise AccountError('profile_invalid')
    command, arguments = arguments[0], arguments[1:]
    required = {'--provider', '--account', '--project', '--json'}
    if command == 'register':
        required.add('--metadata')
    values = {}
    while arguments:
        flag, arguments = arguments[0], arguments[1:]
        if flag not in required or flag in values:
            raise AccountError('profile_invalid')
        if flag == '--json':
            values[flag] = True
        else:
            if not arguments or not arguments[0] or arguments[0].startswith('--'):
                raise AccountError('profile_invalid')
            values[flag], arguments = arguments[0], arguments[1:]
    if set(values) != required:
        raise AccountError('profile_invalid')
    validate_binding({'schema': 1, 'provider_id': values['--provider'], 'account_id': values['--account']})
    return command, values


def main(arguments=None):
    try:
        command, values = _arguments(sys.argv[1:] if arguments is None else arguments)
        accounts, _ = production_reader()
        profiles = ProviderProfiles(Path.home(), accounts)
        selectors = (values['--provider'], values['--account'], values['--project'])
        result = (profiles.register(*selectors, values['--metadata']) if command == 'register'
                  else profiles.status(*selectors))
    except AccountError as error:
        result = {'schema': 1, 'error': {'code': error.code}}
    except (OSError, ValueError, subprocess.SubprocessError):
        result = {'schema': 1, 'error': {'code': 'profile_invalid'}}
    print(json.dumps(result, separators=(',', ':')))
    return 2 if 'error' in result else 0


if __name__ == '__main__':
    sys.exit(main())
