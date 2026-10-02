"""Offline native task admission. Request flags are not permission evidence.

Caller owns host/thread, obtains unfiltered thread-scoped inventory, and must
revalidate after configuration changes. No process, RPC or task writer effects.
"""
import os
import re
from uuid import UUID


class TaskPolicyError(ValueError):
    pass


def _require(condition):
    if not condition:
        raise TaskPolicyError('Native task policy is not confirmed')


def _canonical(path, *, directory=False):
    _require(isinstance(path, str) and bool(path) and '\x00' not in path)
    try:
        _require(os.path.isabs(path) and os.path.realpath(path) == path)
        if directory:
            _require(os.path.isdir(path))
    except (OSError, ValueError):
        raise TaskPolicyError('Native task policy is not confirmed') from None
    return path


def host_argv(socket, *, executable='codex'):
    _canonical(socket)
    _require(not os.path.lexists(socket))
    _require(isinstance(executable, str) and bool(executable) and '\x00' not in executable)
    return [executable, 'app-server', '--listen', 'unix://' + socket,
            '-c', 'features.plugins=false', '-c', 'features.remote_plugin=false',
            '-c', 'features.apps=false']


def task_thread_params(cwd, mcp_names):
    _canonical(cwd, directory=True)
    _require(isinstance(mcp_names, list))
    names = set()
    for name in mcp_names:
        _require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_-]+', name) is not None)
        _require(name not in names)
        names.add(name)
    config = {'features.plugins': False, 'features.remote_plugin': False,
              'features.apps': False, 'sandbox_workspace_write.network_access': False,
              'sandbox_workspace_write.exclude_tmpdir_env_var': True,
              'sandbox_workspace_write.exclude_slash_tmp': True}
    for name in mcp_names:
        config['mcp_servers.' + name + '.enabled'] = False
    return {'cwd': cwd, 'runtimeWorkspaceRoots': [cwd], 'ephemeral': False,
            'sandbox': 'workspace-write', 'approvalPolicy': 'on-request',
            'environments': [], 'config': config}


def _catalog(pages):
    _require(isinstance(pages, list) and 1 <= len(pages) <= 100)
    cursors, names = set(), set()
    for index, page in enumerate(pages):
        _require(isinstance(page, dict) and isinstance(page.get('data'), list))
        _require('nextCursor' in page)
        cursor = page['nextCursor']
        if index == len(pages) - 1:
            _require(cursor is None)
        else:
            _require(isinstance(cursor, str) and bool(cursor) and cursor not in cursors)
            cursors.add(cursor)
        for row in page['data']:
            _require(isinstance(row, dict))
            name = row.get('name')
            _require(isinstance(name, str) and bool(name) and name not in names)
            names.add(name)
            _require(row.get('runtimeStatus') == 'disabled')
            _require(isinstance(row.get('tools'), dict) and not row['tools'])
            for key in ('resources', 'resourceTemplates'):
                _require(isinstance(row.get(key), list) and not row[key])
            _require(row.get('pluginId') is None and row.get('toolsError') is None)
            _require(row.get('serverCapabilities') in (None, {}))


def validate_task_policy(response, cwd, catalog_pages):
    try:
        _canonical(cwd, directory=True)
        _require(isinstance(response, dict))
        thread = response.get('thread')
        _require(isinstance(thread, dict))
        sid = thread.get('id')
        _require(isinstance(sid, str) and str(UUID(sid)) == sid)
        _require(response.get('cwd') == cwd and thread.get('cwd') == cwd)
        _require(thread.get('ephemeral') is False)
        _require(response.get('approvalPolicy') == 'on-request')
        _require(response.get('approvalsReviewer') == 'user')
        roots = response.get('runtimeWorkspaceRoots')
        _require(isinstance(roots, list) and roots in ([], [cwd]))
        sandbox = response.get('sandbox')
        _require(isinstance(sandbox, dict) and sandbox.get('type') == 'workspaceWrite')
        _require(sandbox.get('networkAccess', False) is False)
        _require(sandbox.get('excludeTmpdirEnvVar', False) is True)
        _require(sandbox.get('excludeSlashTmp', False) is True)
        writable = sandbox.get('writableRoots', [])
        _require(isinstance(writable, list))
        for root in writable:
            _canonical(root)
            _require(os.path.commonpath((cwd, root)) == cwd)
        _require('reasoningEffort' in response)
        model, effort = response.get('model'), response.get('reasoningEffort')
        _require(isinstance(model, str) and bool(model.strip()))
        _require(effort is None or isinstance(effort, str))
        _catalog(catalog_pages)
        return {'thread_id': sid, 'model': model, 'reasoning_effort': effort}
    except (ValueError, TypeError, OSError, AttributeError):
        raise TaskPolicyError('Native task policy is not confirmed') from None
