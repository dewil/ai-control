"""Pure project-access policy validation; no filesystem or authentication IO."""
import posixpath
import re


class PolicyError(ValueError):
    """An invalid policy, without exposing rejected document values."""


def _require(condition):
    if not condition:
        raise PolicyError('invalid access policy')


def _fields(value, names):
    return (type(value) is dict and len(value) == len(names)
            and all(type(key) is str for key in value) and set(value) == names)


def _username(value):
    return type(value) is str and re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', value) is not None


def _no_controls(value):
    return all(ord(char) >= 32 and ord(char) != 127 for char in value)


def _alias(value):
    return (type(value) is str and 1 <= len(value) <= 128
            and value.strip() == value and _no_controls(value)
            and not any(char in value for char in '*?[]'))


def _root(value):
    return (type(value) is str and 1 < len(value) <= 4096
            and value.startswith('/') and _no_controls(value)
            and all(part not in ('', '.', '..') for part in value.split('/')[1:])
            and posixpath.normpath(value) == value)


def validate_policy(document):
    """Validate exact built-in types and return independent policy containers."""
    _require(_fields(document, {'version', 'owner', 'projects', 'users'}))
    _require(type(document['version']) is int and document['version'] == 1)
    owner, projects, users = document['owner'], document['projects'], document['users']
    _require(_username(owner))
    _require(type(projects) is dict and len(projects) <= 256)
    copied_projects = {}
    for alias, root in projects.items():
        _require(_alias(alias) and _root(root))
        copied_projects[alias] = root
    _require(type(users) is dict and 1 <= len(users) <= 256)
    copied_users = {}
    for username, record in users.items():
        _require(_username(username))
        _require(_fields(record, {'enabled', 'auth_epoch', 'projects'}))
        enabled, epoch, grants = record['enabled'], record['auth_epoch'], record['projects']
        _require(type(enabled) is bool)
        _require(type(epoch) is int and 1 <= epoch <= 2147483647)
        _require(type(grants) is list and len(grants) <= 256)
        seen = set()
        for alias in grants:
            _require(_alias(alias))
            _require(alias in copied_projects and alias not in seen)
            seen.add(alias)
        copied_users[username] = {'enabled': enabled, 'auth_epoch': epoch,
                                  'projects': list(grants)}
    _require(owner in copied_users)
    _require(copied_users[owner]['enabled'] and not copied_users[owner]['projects'])
    return {'version': 1, 'owner': owner, 'projects': copied_projects, 'users': copied_users}


def authorize(policy, principal, project_name, project_path, operation):
    """Authorize a trusted project tuple against current policy, failing closed."""
    try:
        validated = validate_policy(policy)
    except PolicyError:
        return False
    if (not _username(principal) or not _alias(project_name) or not _root(project_path)
            or type(operation) is not str
            or operation not in ('view', 'answer', 'verdict', 'recover')):
        return False
    record = validated['users'].get(principal)
    if record is None or not record['enabled']:
        return False
    if principal == validated['owner']:
        return True
    return (project_name in record['projects']
            and validated['projects'][project_name] == project_path)
