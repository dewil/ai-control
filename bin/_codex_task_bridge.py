"""Offline owned-call dispatcher. Runtime supplies the authoritative task fence."""
import copy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
import uuid


class BridgeError(Exception):
    pass


def _require(value):
    if not value:
        raise BridgeError('Task bridge rejected operation')


def _text(value, limit, *, nonblank=False, identity=False):
    _require(isinstance(value, str) and len(value.encode('utf-8')) <= limit)
    _require(not nonblank or bool(value.strip()))
    _require(all(not (ord(c) < 32 or 127 <= ord(c) <= 159) or
                 (not identity and c in '\n\t') for c in value))
    if identity:
        _require(value == value.strip() and '/' not in value and '\\' not in value)


@dataclass(frozen=True)
class TaskBinding:
    task_incarnation: str
    event_key: str
    agent_dir: str
    thread_id: str
    turn_id: str


def dynamic_tools():
    text = {'type': 'string'}
    return [dict(type='function', name='task_ask', description='Request task clarification.',
                 deferLoading=False, inputSchema=dict(type='object', additionalProperties=False,
                 required=['question'], properties=dict(question=dict(text, minLength=1, maxLength=4096),
                 context=dict(text, maxLength=8192), options=dict(type='array', minItems=2,
                 maxItems=8, uniqueItems=True, items=dict(text, minLength=1, maxLength=256))))),
            dict(type='function', name='task_done', description='Request task completion review.',
                 deferLoading=False, inputSchema=dict(type='object', additionalProperties=False,
                 properties=dict(summary=dict(text, maxLength=4096))))]


class CodexTaskBridge:
    _LIMIT = 1024 * 1024

    def __init__(self, state_dir, binding, *, guard, writer, clock=time.monotonic):
        try:
            _require(isinstance(binding, TaskBinding))
            _require(callable(guard) and callable(writer) and callable(clock))
            self.binding, self.guard, self.writer, self.clock = binding, guard, writer, clock
            self.state_dir = os.fspath(state_dir)
            _require(isinstance(self.state_dir, str))
            self._binding()
            self._paths()
        except Exception:
            raise BridgeError('Invalid task bridge configuration') from None

    def _binding(self):
        for key in ('task_incarnation', 'event_key', 'thread_id', 'turn_id'):
            _text(getattr(self.binding, key), 256, nonblank=True, identity=True)
        path = self.binding.agent_dir
        _require(isinstance(path, str) and os.path.isabs(path) and
                 os.path.realpath(path) == path and os.path.isdir(path))

    def _paths(self):
        path = self.state_dir
        _require(os.path.isabs(path) and os.path.realpath(path) == path)
        _require(os.path.commonpath((path, self.binding.agent_dir)) not in
                 (path, self.binding.agent_dir))
        _require(os.path.isdir(os.path.dirname(path)))

    def _deadline(self, deadline):
        _require(type(deadline) in (int, float) and math.isfinite(deadline))
        _require(self.clock() < deadline)

    def _request(self, request):
        _require(type(request) is dict and set(request) in
                 ({'id', 'method', 'params'}, {'id', 'method', 'params', 'jsonrpc'}))
        _require('jsonrpc' not in request or request['jsonrpc'] == '2.0')
        rpc = request['id']
        if type(rpc) is int:
            _require(-(2 ** 63) <= rpc < 2 ** 63)
        else:
            _require(isinstance(rpc, str) and 1 <= len(rpc.encode('utf-8')) <= 256)
        p = request['params']
        required = {'threadId', 'turnId', 'callId', 'tool', 'arguments'}
        _require(type(p) is dict and set(p) in (required, required | {'namespace'}))
        _require(p.get('namespace') is None and p['threadId'] == self.binding.thread_id
                 and p['turnId'] == self.binding.turn_id)
        _text(p['callId'], 256, nonblank=True, identity=True)
        tool, args = p['tool'], p['arguments']
        _require(tool in ('task_ask', 'task_done') and type(args) is dict)
        if tool == 'task_ask':
            _require('question' in args and set(args) <= {'question', 'context', 'options'})
            _text(args['question'], 4096, nonblank=True)
            if 'context' in args:
                _text(args['context'], 8192)
            if 'options' in args:
                options = args['options']
                _require(type(options) is list and 2 <= len(options) <= 8)
                for option in options:
                    _text(option, 256, nonblank=True)
                _require(len(set(options)) == len(options))
        else:
            _require(set(args) <= {'summary'})
            if 'summary' in args:
                _text(args['summary'], 4096)
        return rpc, p['callId'], tool, copy.deepcopy(args)

    @staticmethod
    def _result(tool, result):
        _require(type(result) is dict)
        if tool == 'task_done':
            _require(set(result) == {'requested'} and result['requested'] is True)
        else:
            _require(set(result) == {'qid'} and isinstance(result['qid'], str))
            _require(str(uuid.UUID(result['qid'])) == result['qid'])
        return copy.deepcopy(result)

    def _directory(self):
        self._paths()
        info = os.lstat(self.state_dir)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o700)

    def _open(self, name, flags):
        fd = os.open(os.path.join(self.state_dir, name),
                     flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                     and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)
            return fd
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _sync_directory(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def _locked(self):
        self._paths()
        if not os.path.lexists(self.state_dir):
            try:
                os.mkdir(self.state_dir, 0o700)
            except FileExistsError:
                pass
        self._directory()
        self._sync_directory(os.path.dirname(self.state_dir))
        initializing = False
        try:
            fd = self._open('bridge.lock', os.O_RDWR)
        except FileNotFoundError:
            # Only a completely empty directory is a new binding. Never recreate
            # one half of a previously existing pair or reset interrupted setup.
            _require(not os.listdir(self.state_dir))
            fd = self._open('bridge.lock', os.O_RDWR | os.O_CREAT | os.O_EXCL)
            initializing = True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._sync_directory(self.state_dir)
            if initializing:
                _require(os.listdir(self.state_dir) == ['bridge.lock'])
                self._write(dict(schema=1, binding=asdict(self.binding), calls={}))
            yield
        finally:
            os.close(fd)

    @staticmethod
    def _pairs(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result

    def _read(self):
        try:
            fd = self._open('journal.json', os.O_RDONLY)
        except FileNotFoundError:
            raise BridgeError('Missing task bridge journal') from None
        with os.fdopen(fd, 'rb') as stream:
            payload = stream.read(self._LIMIT + 1)
        _require(len(payload) <= self._LIMIT)
        journal = json.loads(payload, object_pairs_hook=self._pairs)
        _require(type(journal) is dict and set(journal) == {'schema', 'binding', 'calls'})
        _require(type(journal['schema']) is int and journal['schema'] == 1)
        _require(journal['binding'] == asdict(self.binding))
        calls = journal['calls']
        _require(type(calls) is dict and len(calls) <= 256)
        for call, entry in calls.items():
            _text(call, 256, nonblank=True, identity=True)
            _require(type(entry) is dict and set(entry) == {'tool', 'fingerprint', 'result'})
            _require(entry['tool'] in ('task_ask', 'task_done'))
            _require(isinstance(entry['fingerprint'], str) and
                     re.fullmatch('[0-9a-f]{64}', entry['fingerprint']) is not None)
            if entry['result'] is not None:
                self._result(entry['tool'], entry['result'])
        return journal

    def _write(self, journal):
        payload = json.dumps(journal, sort_keys=True).encode('utf-8')
        _require(len(payload) <= self._LIMIT)
        self._directory()
        try:
            fd = self._open('journal.json', os.O_RDONLY)
        except FileNotFoundError:
            pass
        else:
            os.close(fd)
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.journal-', dir=self.state_dir)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, os.path.join(self.state_dir, 'journal.json'))
            temporary = None
            self._sync_directory(self.state_dir)
        finally:
            if temporary is not None:
                os.unlink(temporary)

    def handle(self, request, *, deadline):
        if isinstance(request, dict) and request.get('method') != 'item/tool/call':
            return None
        try:
            self._binding()
            rpc, call, tool, args = self._request(request)
            self._deadline(deadline)
            response = None
            with self.guard(self.binding, deadline=deadline) as allowed:
                _require(allowed is True)
                self._binding()
                self._deadline(deadline)
                with self._locked():
                    journal = self._read()
                    fingerprint = hashlib.sha256(json.dumps(args, sort_keys=True,
                        separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
                    entry = journal['calls'].get(call)
                    if entry is not None:
                        _require(entry['tool'] == tool and entry['fingerprint'] == fingerprint)
                        _require(entry['result'] is not None)
                        result = entry['result']
                    else:
                        _require(len(journal['calls']) < 256)
                        entry = dict(tool=tool, fingerprint=fingerprint, result=None)
                        journal['calls'][call] = entry
                        self._deadline(deadline)
                        self._write(journal)
                        self._deadline(deadline)
                        result = self._result(tool, self.writer(self.binding, tool,
                            copy.deepcopy(args), deadline=deadline))
                        self._deadline(deadline)
                        entry['result'] = result
                        self._write(journal)
                    self._deadline(deadline)
                    response = {'id': rpc, 'result': {'success': True, 'contentItems': [
                        {'type': 'inputText', 'text': json.dumps(result)}]}}
            # Exit may consume the remaining deadline or raise; never expose a late success.
            self._deadline(deadline)
            _require(response is not None)
            return response
        except Exception:
            raise BridgeError('Task bridge operation unavailable') from None
