#!/usr/bin/env python3
"""Project-scoped sessions on the shared Codex App Server."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

PAGE_SIZE = 8
MAX_PAGES = 100
PROJECT_RE = re.compile(r'[a-zA-Z0-9_-]{1,32}\Z')
SHORT_RE = re.compile(r'[0-9a-f]{12}\Z')
SEED = ('Служебное открытие сессии для продолжения с телефона. Ничего не выполняй: '
        'не читай и не меняй файлы, не вызывай инструменты. Ответь одним словом: Готов.')


def canonical(path):
    if not isinstance(path, str) or not path or not os.path.isabs(os.path.expanduser(path)):
        raise ValueError('Invalid project directory')
    return os.path.realpath(os.path.expanduser(path))


class MetadataError(ValueError):
    """Controlled metadata validation error safe for preparation diagnostics."""


def apply_metadata(row, source):
    """Merge known API configuration metadata without inventing defaults."""
    for api_key, row_key in (('model', 'model'), ('reasoningEffort', 'reasoning_effort')):
        value = source.get(api_key)
        if value is not None and not isinstance(value, str):
            raise MetadataError('Invalid ' + api_key + ' metadata')
        if value:
            row[row_key] = value
    return row


def normalize_thread(thread):
    if not isinstance(thread, dict):
        raise ValueError('Invalid thread record')
    try:
        sid = str(uuid.UUID(thread['id']))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError('Invalid thread UUID') from None
    cwd = canonical(thread.get('cwd'))
    status = thread.get('status', {})
    if not isinstance(status, dict) or not isinstance(status.get('type'), str):
        raise ValueError('Invalid thread status')
    row = {'sid': sid, 'short': sid.replace('-', '')[:12],
           'title': thread.get('name') or thread.get('preview') or 'Codex',
           'mtime': thread.get('updatedAt', 0), 'cwd': cwd, 'status': status['type']}
    return apply_metadata(row, thread)


class CodexSessions:
    def __init__(self, rpc, project_path):
        self.rpc = rpc
        self.project_path = project_path

    def _cwd(self, project):
        if not isinstance(project, str) or not PROJECT_RE.fullmatch(project):
            raise ValueError('Invalid project name')
        cwd = canonical(self.project_path(project))
        if not os.path.isdir(cwd):
            raise ValueError('Project directory does not exist')
        return cwd

    def _pages(self, method, params):
        cursor = None
        seen = set()
        for _ in range(MAX_PAGES):
            response = self.rpc(method, dict(params, **({'cursor': cursor} if cursor else {})))
            if not isinstance(response, dict) or not isinstance(response.get('data'), list):
                raise ValueError('Invalid ' + method + ' response')
            yield response['data']
            cursor = response.get('nextCursor')
            if not cursor:
                return
            if not isinstance(cursor, str) or cursor in seen:
                raise ValueError('Repeated or invalid pagination cursor')
            seen.add(cursor)
        raise ValueError('Pagination limit exceeded')

    def _rows(self, cwd):
        rows = []
        identities = {}
        params = {'cwd': cwd, 'limit': 100, 'sourceKinds': ['cli', 'vscode', 'appServer'],
                  'sortKey': 'updated_at', 'sortDirection': 'desc'}
        for page in self._pages('thread/list', params):
            for thread in page:
                row = normalize_thread(thread)
                previous = identities.get(row['sid'])
                if previous is not None:
                    if previous != row:
                        raise ValueError('Inconsistent duplicate thread identity')
                    continue
                identities[row['sid']] = row
                if row['cwd'] == cwd:
                    rows.append(row)
        return rows

    def list_sessions(self, project, page=0):
        if isinstance(page, bool) or not isinstance(page, int) or page < 0:
            raise ValueError('Invalid page')
        rows = self._rows(self._cwd(project))
        offset = page * PAGE_SIZE
        return {'rows': rows[offset:offset + PAGE_SIZE], 'has_more': len(rows) > offset + PAGE_SIZE}

    def get_session(self, project, short):
        if not isinstance(short, str) or not SHORT_RE.fullmatch(short):
            raise ValueError('Invalid session prefix')
        rows = [r for r in self._rows(self._cwd(project)) if r['short'] == short]
        if len(rows) != 1:
            raise ValueError('Session missing or prefix ambiguous')
        return rows[0]

    def _connected(self):
        if self.rpc('remoteControl/status/read', {}).get('status') != 'connected':
            raise RuntimeError('Codex Remote Control is not connected')

    def _owned(self, thread, cwd, sid=None):
        row = normalize_thread(thread)
        if row['cwd'] != cwd or (sid is not None and row['sid'] != sid):
            raise ValueError('Thread identity or project directory mismatch')
        return row

    def create_session(self, project):
        cwd = self._cwd(project)
        self._connected()
        result = self.rpc('thread/start', {'cwd':cwd, 'ephemeral':False,
                                         'sandbox':'workspace-write', 'approvalPolicy':'on-request'})
        try:
            sid = str(uuid.UUID(result['thread']['id']))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise RuntimeError('thread/start returned an invalid session identity') from None
        name = project + ' · Codex · ' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            row = apply_metadata(self._owned(result['thread'], cwd, sid), result)
            self.rpc('thread/name/set', {'threadId':sid, 'name':name})
            self.rpc('turn/start', {'threadId':sid, 'input':[{'type':'text', 'text':SEED}]})
        except Exception as error:
            raise RuntimeError('Session ' + sid + ' was created but preparation failed; ' + (str(error) if isinstance(error, MetadataError) else type(error).__name__)) from None
        row.update(title=name, status='active')
        return row

    def resume_session(self, project, short):
        row = self.get_session(project, short)
        self._connected()
        result = self.rpc('thread/resume', {'threadId':row['sid']})
        current = self._owned(result['thread'], row['cwd'], row['sid'])
        for key in ('model', 'reasoning_effort'):
            if key not in current and key in row:
                current[key] = row[key]
        return apply_metadata(current, result)

    def interrupt_session(self, project, short):
        row = self.get_session(project, short)
        thread = self.rpc('thread/read', {'threadId':row['sid'], 'includeTurns':True})['thread']
        refreshed = self._owned(thread, row['cwd'], row['sid'])
        active = [turn for turn in thread.get('turns', []) if turn.get('status') == 'inProgress']
        if len(active) > 1:
            raise ValueError('Multiple active turns')
        if active:
            turn_id = active[0].get('id')
            if not isinstance(turn_id, str) or not turn_id:
                raise ValueError('Invalid active turn identity')
            self.rpc('turn/interrupt', {'threadId':row['sid'], 'turnId':turn_id})
        return refreshed


class WebSocketRPC:
    """No credentials, conversation payloads or server errors enter diagnostics."""
    def __init__(self, socket, timeout=25, deadline=None):
        from websockets.sync.client import unix_connect
        self.timeout = timeout
        self.completed_turns = {}
        self.seed_turns = {}
        self.deadline = deadline if deadline is not None else time.monotonic() + timeout
        try:
            self.ws = unix_connect(socket, uri='ws://localhost', open_timeout=self._remaining(10), close_timeout=1, max_size=16*1024*1024)
        except Exception as error:
            raise RuntimeError('App Server connection failed (' + type(error).__name__ + ')') from None
        try:
            self.call('initialize', {'clientInfo':{'name':'claude_control', 'version':'0.1'},
                                     'capabilities':{'experimentalApi':True}})
            self._remaining()
            self.ws.send(json.dumps({'method':'initialized'}))
        except Exception as error:
            self.close()
            if type(error) in (RuntimeError, ValueError, TimeoutError):
                raise
            raise RuntimeError('App Server initialization failed (' + type(error).__name__ + ')') from None

    def _remaining(self, cap=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('App Server operation deadline exceeded')
        return min(remaining, cap) if cap is not None else remaining

    def _event(self, timeout):
        try:
            event = json.loads(self.ws.recv(timeout=self._remaining(timeout)))
        except TimeoutError:
            raise TimeoutError('App Server response timed out') from None
        except Exception as error:
            raise RuntimeError('App Server response failed (' + type(error).__name__ + ')') from None
        if not isinstance(event, dict):
            raise ValueError('Invalid App Server event')
        if event.get('method') == 'turn/completed':
            params = event.get('params')
            if isinstance(params, dict) and isinstance(params.get('turn'), dict):
                sid, turn = params.get('threadId'), params['turn']
                if isinstance(sid, str) and isinstance(turn.get('id'), str):
                    self.completed_turns[(sid, turn['id'])] = turn.get('status')
        # Server requests are shared with the native client. Even an error reply
        # would consume its pending approval callback; this observer sends none.
        return event

    def call(self, method, params, timeout=None):
        self._remaining()
        request_id = str(uuid.uuid4())
        try:
            self.ws.send(json.dumps({'id':request_id, 'method':method, 'params':params}))
        except Exception as error:
            raise RuntimeError(method + ' send failed (' + type(error).__name__ + ')') from None
        deadline = min(self.deadline, time.monotonic() + (self.timeout if timeout is None else timeout))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(method + ' timed out')
            event = self._event(remaining)
            if event.get('id') != request_id or 'method' in event:
                continue
            if 'error' in event:
                code = event['error'].get('code') if isinstance(event['error'],dict) else None
                code = code if isinstance(code, int) and not isinstance(code, bool) else 'unknown'
                raise RuntimeError(method + ' failed (code ' + str(code) + ')')
            if not isinstance(event.get('result'), dict):
                raise ValueError(method + ' returned invalid result')
            if method == 'turn/start':
                turn = event['result'].get('turn')
                if not isinstance(turn, dict) or not isinstance(turn.get('id'), str) or not turn['id']:
                    raise ValueError('turn/start returned invalid turn identity')
                self.seed_turns[params['threadId']] = turn['id']
            return event['result']

    def materialize(self, row):
        """Wait for our seed completion before reading its newly written rollout."""
        deadline = min(self.deadline, time.monotonic() + 90)
        turn_id = self.seed_turns.get(row['sid'])
        if not turn_id:
            raise ValueError('Missing seed turn identity')
        key = (row['sid'], turn_id)
        # thread/read includeTurns cannot load a rollout before the first turn
        # finishes. Completion may arrive before turn/start's response, so _event
        # records it while any RPC is waiting, not only inside this loop.
        while key not in self.completed_turns:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Session ' + row['sid'] + ' preparation timed out')
            self._event(remaining)
        if self.completed_turns[key] != 'completed':
            raise RuntimeError('Session ' + row['sid'] + ' preparation did not complete')
        result = self.call('thread/read', {'threadId':row['sid'], 'includeTurns':True},
                           timeout=min(self.timeout, max(.01, deadline-time.monotonic())))
        current = normalize_thread(result['thread'])
        if current['sid'] != row['sid'] or current['cwd'] != row['cwd']:
            raise ValueError('Materialized thread identity mismatch')
        seed = [t for t in result['thread'].get('turns', []) if t.get('id') == turn_id]
        if len(seed) != 1 or seed[0].get('status') != 'completed':
            raise ValueError('Seed completion is not persisted')
        row['status'] = current['status']
        for key in ('model', 'reasoning_effort'):
            if key in current:
                row[key] = current[key]
        return row

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def resolve_project(name, deadline=None):
    if not PROJECT_RE.fullmatch(name):
        raise ValueError('Invalid project name')
    helper = str(Path(__file__).resolve().with_name('_rc_projects.sh'))
    remaining = 10 if deadline is None else min(10, deadline - time.monotonic())
    if remaining <= 0:
        raise TimeoutError('Project resolution deadline exceeded')
    result = subprocess.run(['bash', '-c', '. "$1"; project_path "$2"', '_', helper, name],
                            capture_output=True, text=True, timeout=remaining)
    if result.returncode or not result.stdout.rstrip('\n'):
        raise ValueError('Project registry resolution failed')
    return canonical(result.stdout.rstrip('\n'))


def socket_path():
    if os.environ.get('CODEX_RC_SOCKET'):
        return os.path.expanduser(os.environ['CODEX_RC_SOCKET'])
    codex_home = os.environ.get('CODEX_HOME')
    if not codex_home:
        shared = Path('/data/.codex/app-server-control/app-server-control.sock')
        if shared.exists():
            return str(shared)
        codex_home = str(Path.home()/'.codex')
    return str(Path(codex_home).expanduser()/'app-server-control'/'app-server-control.sock')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('sessions'); listing.add_argument('project'); listing.add_argument('--page', type=int, default=0)
    commands.add_parser('new').add_argument('project')
    for action in ('show','resume','interrupt'):
        sub = commands.add_parser(action); sub.add_argument('project'); sub.add_argument('short')
    commands.add_parser('doctor')
    args = parser.parse_args(argv)
    deadline = time.monotonic() + (110 if args.command == 'new' else 20)
    rpc = None
    try:
        rpc = WebSocketRPC(socket_path(), deadline=deadline)
        service = CodexSessions(rpc.call, lambda name: resolve_project(name, deadline))
        if args.command == 'doctor':
            status = rpc.call('remoteControl/status/read', {})
            result = {'status':status.get('status'), 'connected':status.get('status') == 'connected'}
        elif args.command == 'sessions':
            result = service.list_sessions(args.project, args.page)
        elif args.command == 'new':
            result = service.create_session(args.project)
            try:
                result = rpc.materialize(result)
            except Exception as error:
                raise RuntimeError('Session ' + result['sid'] + ' preparation failed; ' + type(error).__name__) from None
        else:
            action = {'show':service.get_session,'resume':service.resume_session,'interrupt':service.interrupt_session}[args.command]
            result = action(args.project, args.short)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyError, ImportError, subprocess.TimeoutExpired) as error:
        # Only our controlled ValueError/RuntimeError text is safe to expose.
        message = str(error) if type(error) in (ValueError,RuntimeError,TimeoutError) else type(error).__name__
        print('Codex: ' + message, file=sys.stderr)
        return 1
    finally:
        if rpc is not None:
            rpc.close()
