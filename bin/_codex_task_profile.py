"""Pure fixed native TASK policy construction and controller evidence validation."""
import copy
import json
import math
import os
import re
import stat

from _codex_task_policy import validate_task_policy, TaskPolicyError


class ProfileError(Exception):
    pass


def _require(value):
    if not value:
        raise ProfileError('Sealed native task policy is not confirmed')


def _string(value):
    _require(type(value) is str and bool(value) and len(value.encode('utf-8')) <= 4096
             and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value))
    return value


def _plain(value, depth=0, budget=None):
    if budget is None:
        budget = [100000]
    budget[0] -= 1
    _require(depth <= 64 and budget[0] >= 0)
    kind = type(value)
    if kind in (str, int, bool, type(None)):
        if kind is str:
            _require(len(value.encode('utf-8')) <= 1048576)
        elif kind is int:
            _require(value.bit_length() <= 4096)
        return
    if kind is float:
        _require(math.isfinite(value))
        return
    _require(kind in (list, dict))
    if kind is dict:
        for key, child in value.items():
            _require(type(key) is str)
            _plain(key, depth + 1, budget)
            _plain(child, depth + 1, budget)
    else:
        for child in value:
            _plain(child, depth + 1, budget)


def _equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return set(actual) == set(expected) and all(_equal(actual[key], value) for key, value in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _path(path, *, directory=False):
    _string(path)
    _require(os.path.isabs(path) and os.path.normpath(path) == path
             and os.path.realpath(path) == path)
    if directory:
        current = path
        while True:
            info = os.lstat(current)
            _require(stat.S_ISDIR(info.st_mode))
            if current == path:
                _require(info.st_uid == os.getuid())
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        info = os.lstat(os.path.join(path, '.git'))
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and info.st_nlink == 1)
    return path


_FALSE = 'shell_tool js_repl js_repl_tools_only code_mode_only multi_agent multi_agent_v2 hooks plugins remote_plugin apps tool_suggest request_permissions_tool image_generation view_image deferred_executor token_budget current_time_reminder sleep_tool send_message_to_user_async browser_use browser_use_full_cdp_access browser_use_external computer_use memories goals agent_message_board skill_search'.split()
_TOOLS = {'task_read', 'task_search', 'task_list', 'task_ask', 'task_done'}
_HASHES = {
    'codex': '12eb3e81114588aca3b7998f4f19e8997b056aca08e57a7ca7c8a3ec8c652aad',
    'code_mode_host': '37cab1584302611e9936902219640ab5e7a79fcfccd2504c6e85ea8cb97d0e10',
    'bwrap': '01fb705f067bd5365b63d8ad2323a61c8d007733ca5e649437e086f3fb9935d8',
    'rg': 'e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849',
}


def _overrides(cwd, names):
    _path(cwd, directory=True)
    _require(type(names) is list and len(names) <= 1000)
    seen = set()
    for name in names:
        _string(name)
        _require(re.fullmatch(r'[A-Za-z0-9_-]+', name) is not None and name not in seen)
        seen.add(name)
    escaped = ''.join('\\' + c if c in '\\[]*?' else c for c in cwd)
    prefix = escaped + '/**/'
    def fold(name):
        return ''.join('[' + c.lower() + c.upper() + ']' if c.isascii() and c.isalpha() else c for c in name)
    fs = {'/': 'deny', cwd: 'write', cwd + '/.git': 'deny'}
    for name in ['.env', '.env.*', '.netrc', '.npmrc', '.pypirc', 'auth.json', 'credentials.json', 'cookies.json', 'id_rsa', 'id_ed25519', 'id_dsa', 'id_ecdsa', '*.pem', '*.key', '*.p12', '*.pfx']:
        fs[prefix + fold(name)] = 'deny'
    for name in ['.git', '.ssh', '.aws', '.azure', '.kube', 'browser-sessions']:
        fs[prefix + fold(name)] = 'deny'
        fs[prefix + fold(name) + '/**'] = 'deny'
    result = {'features.' + key: False for key in _FALSE}
    result.update({
        'features.code_mode': {'enabled': False, 'direct_only_tool_namespaces': [], 'excluded_tool_namespaces': []},
        'features.code_mode_host': {'enabled': True, 'disable_in_process_fallback': False},
        'features.code_mode_interrupt': True,
        'agents.enabled': False, 'tools.experimental_request_user_input.enabled': False,
        'tools.update_plan.enabled': False, 'memories.use_memories': False,
        'cloud.skills.enabled': False, 'web_search': 'disabled', 'notify': [],
        'default_permissions': 'control_task',
        'permissions.control_task': {'filesystem': fs, 'network': {'enabled': False}},
    })
    result.update({'mcp_servers.' + name + '.enabled': False for name in names})
    return result


def _safe(function):
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError, TaskPolicyError):
            raise ProfileError('Sealed native task policy is not confirmed') from None
    return wrapped


@_safe
def sealed_overrides(cwd, mcp_names):
    return _overrides(cwd, mcp_names)


def _toml(value):
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False)
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is list:
        return '[' + ', '.join(_toml(v) for v in value) + ']'
    if type(value) is dict:
        return '{' + ', '.join(_toml(k) + ' = ' + _toml(v) for k, v in value.items()) + '}'
    raise ProfileError('Sealed native task policy is not confirmed')


@_safe
def sealed_host_argv(socket, cwd, mcp_names, *, executable='codex'):
    _path(socket)
    _require(not os.path.lexists(socket))
    _string(executable)
    result = [executable, 'app-server', '--listen', 'unix://' + socket]
    for key, value in _overrides(cwd, mcp_names).items():
        result.extend(['-c', key + '=' + _toml(value)])
    return result


@_safe
def sealed_thread_params(cwd, mcp_names, dynamic_tools):
    config = _overrides(cwd, mcp_names)
    _plain(dynamic_tools)
    _require(type(dynamic_tools) is list and len(dynamic_tools) == 5)
    _require(len(json.dumps(dynamic_tools).encode('utf-8')) <= 65536)
    names = set()
    for tool in dynamic_tools:
        _require(type(tool) is dict and set(tool) == {'type', 'name', 'description', 'inputSchema', 'deferLoading'})
        _require(tool['type'] == 'function' and tool['deferLoading'] is False)
        name = tool['name']
        _require(type(name) is str and name in _TOOLS and name not in names)
        names.add(name)
        description = tool['description']
        _require(type(description) is str and bool(description.strip()) and len(description.encode('utf-8')) <= 4096)
        schema = tool['inputSchema']
        _require(type(schema) is dict and schema.get('type') == 'object'
                 and type(schema.get('properties')) is dict and schema.get('additionalProperties') is False)
        required = schema.get('required', [])
        _require(type(required) is list and all(type(key) is str and key in schema['properties'] for key in required)
                 and len(set(required)) == len(required))
    return {'cwd': cwd, 'runtimeWorkspaceRoots': [cwd], 'ephemeral': False,
            'permissions': 'control_task', 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user',
            'selectedCapabilityRoots': [], 'environments': [{'environmentId': 'local', 'cwd': cwd, 'runtimeWorkspaceRoots': [cwd]}],
            'config': config, 'dynamicTools': copy.deepcopy(dynamic_tools)}


@_safe
def validate_sealed_policy(response, cwd, config, catalog_pages, registry_names, release_evidence):
    for value in (response, config, catalog_pages, registry_names, release_evidence):
        _plain(value)
    _require(type(response) is dict and type(config) is dict)
    expected = _overrides(cwd, [])
    result = validate_task_policy(response, cwd, catalog_pages)
    _require(_equal(response.get('activePermissionProfile'), {'id': 'control_task', 'extends': None}))
    _require(response.get('runtimeWorkspaceRoots') == [cwd])
    _require(response['thread'].get('environments') == [{'environmentId': 'local', 'cwd': cwd, 'runtimeWorkspaceRoots': [cwd]}])
    optional = {'tools.experimental_request_user_input.enabled', 'tools.update_plan.enabled'}
    for key, value in expected.items():
        node = config
        absent = False
        for part in key.split('.'):
            if type(node) is not dict or part not in node:
                absent = True
                break
            node = node[part]
        if absent:
            _require(key in optional)
        else:
            if key == 'permissions.control_task' and type(node) is dict:
                node = copy.deepcopy(node)
                for container, fields in (
                    (node, ('description', 'extends', 'workspace_roots')),
                    (node.get('filesystem'), ('glob_scan_max_depth',)),
                    (node.get('network'), ('proxy_url', 'enable_socks5', 'socks_url',
                     'enable_socks5_udp', 'allow_upstream_proxy',
                     'dangerously_allow_non_loopback_proxy',
                     'dangerously_allow_all_unix_sockets', 'mode', 'domains',
                     'unix_sockets', 'allow_local_binding', 'mitm')),
                ):
                    if type(container) is dict:
                        for field in fields:
                            if field in container:
                                _require(container[field] is None)
                                del container[field]
            _require(_equal(node, value))
    servers = config.get('mcp_servers', {})
    _require(type(servers) is dict and len(servers) <= 1000)
    for name, server in servers.items():
        _string(name)
        _require(re.fullmatch(r'[A-Za-z0-9_-]+', name) is not None
                 and type(server) is dict and server.get('enabled') is False)
    catalog_names = {row['name'] for page in catalog_pages for row in page['data']}
    _require(catalog_names == set(servers))
    _require(type(registry_names) is list and len(registry_names) == 7
             and all(type(name) is str for name in registry_names)
             and set(registry_names) == _TOOLS | {'apply_patch', 'clock__curr_time'})
    _require(type(release_evidence) is dict and set(release_evidence) == {'version', 'hashes'}
             and release_evidence['version'] == '0.160.0'
             and release_evidence['hashes'] == _HASHES)
    result['permission_profile'] = 'control_task'
    return result
