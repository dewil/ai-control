"""Bounded owner-side session chat and interactive shared App Server transport."""
from contextlib import contextmanager
import fcntl
import functools
import hashlib
import json
import math
import os
import re
import socket
import stat
import threading
import time
import uuid

from _codex_rc import CodexSessions, PROJECT_RE, canonical

HISTORY_LIMIT = 96 * 1024
RECEIPT_LIMIT = 10000


class RPCRejected(RuntimeError):
    """Validated server error; does not prove a message was never accepted."""


class _DomainError(Exception):
    def __init__(self, code):
        self.code = code


def _need(condition, code='unavailable'):
    if not condition:
        raise _DomainError(code)


def valid_uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def valid_project(value):
    return type(value) is str and PROJECT_RE.fullmatch(value) is not None


def valid_cursor(value):
    return value is None or (type(value) is str and 0 < len(value) <= 4096)


def _identity(value):
    return type(value) is str and 0 < len(value) <= 500


def _attention(thread):
    status = thread.get('status')
    return (type(status) is dict and status.get('type') == 'active'
            and type(status.get('activeFlags')) is list
            and all(type(flag) is str for flag in status['activeFlags'])
            and any(flag in ('waitingOnApproval', 'waitingOnUserInput') for flag in status['activeFlags']))


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('invalid JSON object')
        result[key] = value
    return result


def _operation(method):
    @functools.wraps(method)
    def bounded(self, *args, **kwargs):
        self._local.deadline = time.monotonic() + 55
        try:
            return method(self, *args, **kwargs)
        except _DomainError as error:
            return {'error': error.code}
        except Exception:
            return {'error': 'unavailable'}
    return bounded


class _Receipts:
    """Digest-only records, sealed by canonical root/thread namespace."""
    def __init__(self, path):
        self.path = os.path.abspath(path)

    @staticmethod
    def _check(fd, directory=False):
        info = os.fstat(fd)
        _need((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
              and info.st_uid == os.getuid()
              and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
              and (directory or info.st_nlink == 1))

    def _base(self, create):
        _need(self.path != '/data' and not self.path.startswith('/data/'))
        parts = self.path.split('/')[1:]
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for index, part in enumerate(parts):
                _need(part not in ('', '.', '..'))
                if create and index == len(parts) - 1:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            self._check(fd, True)
            return fd
        except Exception:
            os.close(fd)
            raise

    @contextmanager
    def namespace(self, root, sid, deadline, create=False):
        base = ns = lock = None
        try:
            try:
                base = self._base(create)
            except FileNotFoundError:
                if create:
                    raise
                yield None
                return
            name = hashlib.sha256((root + '\0' + sid).encode('utf-8')).hexdigest()
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=base)
                    os.fsync(base)
                except FileExistsError:
                    pass
            try:
                ns = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
            except FileNotFoundError:
                yield None
                return
            self._check(ns, True)
            lock = os.open('.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=ns)
            self._check(lock)
            while True:
                _need(time.monotonic() < deadline)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(.01, max(0, deadline - time.monotonic())))
            # Locks live on stable inodes; reject path replacement after waiting.
            info = os.stat(name, dir_fd=base, follow_symlinks=False)
            opened = os.fstat(ns)
            _need((info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino))
            lock_info = os.stat('.lock', dir_fd=ns, follow_symlinks=False)
            _need((lock_info.st_dev, lock_info.st_ino) ==
                  (os.fstat(lock).st_dev, os.fstat(lock).st_ino))
            current_base = self._base(False)
            try:
                _need((os.fstat(current_base).st_dev, os.fstat(current_base).st_ino) ==
                      (os.fstat(base).st_dev, os.fstat(base).st_ino))
            finally:
                os.close(current_base)
            yield ns
        finally:
            for fd in (lock, ns, base):
                if fd is not None:
                    os.close(fd)

    def read(self, ns, root, sid, mid):
        if ns is None:
            return None
        try:
            fd = os.open(mid + '.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=ns)
        except FileNotFoundError:
            return None
        try:
            self._check(fd)
            _need(os.fstat(fd).st_size <= 4096)
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                record = json.loads(stream.read(4097), object_pairs_hook=_pairs)
            _need(type(record) is dict and set(record) ==
                  {'root', 'sid', 'message_id', 'digest', 'status', 'turn_id', 'created'})
            _need(record['root'] == root and record['sid'] == sid and record['message_id'] == mid)
            _need(type(record['digest']) is str and re.fullmatch('[0-9a-f]{64}', record['digest']))
            _need(record['status'] in ('accepted', 'delivery_unknown', 'rejected'))
            _need(record['turn_id'] is None or _identity(record['turn_id']))
            _need(record['status'] != 'accepted' or _identity(record['turn_id']))
            _need(type(record['created']) is int and record['created'] > 0)
            return record
        finally:
            os.close(fd)

    def write(self, ns, record):
        data = _json(record)
        _need(len(data) <= 4096)
        temp = '.tmp-' + uuid.uuid4().hex
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=ns)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(fd)
            os.replace(temp, record['message_id'] + '.json', src_dir_fd=ns, dst_dir_fd=ns)
            os.fsync(ns)
        finally:
            os.close(fd)
            try:
                os.unlink(temp, dir_fd=ns)
            except FileNotFoundError:
                pass

    @staticmethod
    def result(record):
        return {key: record[key] for key in ('status', 'message_id', 'turn_id')}

    def names(self, ns):
        if ns is None:
            return []
        names = []
        # SIMPLIFIED: bounded per-thread metadata enumeration; retain all dedup
        # records. A future tombstone/index scheme must preserve UUID protection.
        with os.scandir(ns) as entries:
            for entry in entries:
                if entry.name == '.lock' or entry.name.startswith('.tmp-'):
                    continue
                _need(entry.name.endswith('.json') and valid_uuid(entry.name[:-5]))
                names.append(entry.name[:-5])
                _need(len(names) <= RECEIPT_LIMIT)
        return names

    def recent(self, ns, root, sid):
        records = [self.read(ns, root, sid, mid) for mid in self.names(ns)]
        _need(all(record is not None for record in records))
        records.sort(key=lambda record: (record['created'], record['message_id']), reverse=True)
        return [self.result(record) for record in records[:8]]


class SessionChat:
    def __init__(self, rpc, project_path, project_names, receipt_dir):
        self.rpc, self.project_path, self.project_names = rpc, project_path, project_names
        self.receipts = _Receipts(receipt_dir)
        self._local = threading.local()

    def _remaining(self):
        value = self._local.deadline - time.monotonic()
        _need(value > 0)
        return value

    def _rpc(self, method, params):
        remaining = self._remaining()
        result = (self.rpc.call(method, params, timeout=remaining)
                  if isinstance(self.rpc, InteractiveRPC) else self.rpc(method, params))
        self._remaining()
        _need(type(result) is dict)
        return result

    def _names(self):
        self._remaining()
        names = self._provider(self.project_names)
        _need(type(names) is list and len(names) <= 1000
              and all(valid_project(name) for name in names) and len(set(names)) == len(names))
        return names

    def _root(self, project):
        _need(valid_project(project), 'invalid_request')
        _need(project in self._names(), 'invalid_request')
        self._remaining()
        root = self._provider(self.project_path, project)
        _need(type(root) is str and os.path.isabs(root))
        root = canonical(root)
        _need(os.path.isdir(root))
        self._remaining()
        return root

    def _provider(self, provider, *args):
        # Real owner resolvers accept a remaining deadline; simple synthetic
        # callables keep the public positional-only injection contract.
        bounded = getattr(provider, 'deadline_call', None)
        return bounded(self._local.deadline, *args) if callable(bounded) else provider(*args)

    def _proof(self, root, sid, method='thread/read'):
        params = {'threadId': sid}
        if method == 'thread/read':
            params['includeTurns'] = False
        thread = self._rpc(method, params).get('thread')
        _need(type(thread) is dict and valid_uuid(thread.get('id'))
              and type(thread.get('cwd')) is str and os.path.isabs(thread['cwd']))
        _need(thread['id'] == sid and canonical(thread['cwd']) == root, 'stale')
        return thread

    def _page(self, sid, cursor):
        params = {'threadId': sid, 'itemsView': 'full', 'sortDirection': 'desc', 'limit': 8}
        if cursor is not None:
            params['cursor'] = cursor
        response = self._rpc('thread/turns/list', params)
        _need(type(response.get('data')) is list and len(response['data']) <= 8
              and 'nextCursor' in response and valid_cursor(response['nextCursor']))
        _need(response['nextCursor'] is None or response['nextCursor'] != cursor)
        for turn in response['data']:
            _need(type(turn) is dict and _identity(turn.get('id'))
                  and turn.get('status') in ('completed', 'interrupted', 'failed', 'inProgress')
                  and type(turn.get('items')) is list and len(turn['items']) <= 10000)
            for item in turn['items']:
                _need(type(item) is dict and _identity(item.get('id')) and type(item.get('type')) is str)
                if item['type'] == 'userMessage':
                    _need(type(item.get('content')) is list)
                    for content in item['content']:
                        _need(type(content) is dict and type(content.get('type')) is str)
                        if content['type'] == 'text':
                            _need(type(content.get('text')) is str)
                    if item.get('clientId') is not None:
                        _need(type(item['clientId']) is str)
                elif item['type'] == 'agentMessage':
                    _need(type(item.get('text')) is str)
        return response

    @_operation
    def projects(self):
        names = self._names()
        for name in names:
            self._root(name)
        return {'projects': [{'name': name} for name in names]}

    @_operation
    def list_sessions(self, project, page=0):
        _need(type(page) is int and page >= 0, 'invalid_request')
        root = self._root(project)
        def checked_rpc(method, params):
            response = self._rpc(method, params)
            _need(type(response.get('data')) is list and 'nextCursor' in response
                  and valid_cursor(response['nextCursor']))
            for thread in response['data']:
                _need(type(thread) is dict and valid_uuid(thread.get('id')))
            return response
        result = CodexSessions(checked_rpc, lambda alias: root).list_sessions(project, page)
        from _control_web_broker import redact
        rows = []
        for row in result['rows']:
            thread = self._proof(root, row['sid'])
            _need(type(row['title']) is str and _identity(row['status']))
            export = {'sid': row['sid'], 'title': redact(row['title'])[:500], 'status': redact(row['status'])[:500]}
            if _attention(thread):
                export['needs_native_attention'] = True
            rows.append(export)
        return {'rows': rows, 'has_more': result['has_more']}

    @_operation
    def history(self, project, sid, cursor=None):
        _need(valid_uuid(sid) and valid_cursor(cursor), 'invalid_request')
        root = self._root(project)
        thread = self._proof(root, sid)
        page = self._page(sid, cursor)
        from _control_web_broker import redact
        turns, clipped = [], False
        for turn in page['data']:
            items = []
            for item in turn['items']:
                if item['type'] == 'userMessage':
                    parts = [part['text'] for part in item['content'] if part['type'] == 'text']
                    if not parts:
                        continue
                    text, role = '\n'.join(parts), 'user'
                elif item['type'] == 'agentMessage':
                    text, role = item['text'], 'assistant'
                else:
                    continue
                text = redact(text)
                truncated = len(text) > 8000
                clipped |= truncated
                items.append({'id': item['id'], 'role': role, 'text': text[:8000], 'truncated': truncated})
            turns.append({'id': turn['id'], 'status': turn['status'], 'items': items})
        with self.receipts.namespace(root, sid, self._local.deadline) as ns:
            recent = self.receipts.recent(ns, root, sid)
        result = {'turns': turns, 'next_cursor': page['nextCursor'], 'truncated': clipped, 'recent_sends': recent}
        if _attention(thread):
            result['needs_native_attention'] = True
        # Preserve visible prefixes, then omit tail items only when metadata
        # alone cannot fit. The original cursor never promises omitted content.
        while len(_json(result)) > HISTORY_LIMIT:
            result['truncated'] = True
            candidates = [item for turn in turns for item in turn['items'] if item['text']]
            if candidates:
                item = max(candidates, key=lambda value: len(value['text'].encode('utf-8')))
                item['text'] = item['text'][:len(item['text']) // 2]
                item['truncated'] = True
            elif turns and turns[-1]['items']:
                turns[-1]['items'].pop()
            elif turns:
                turns.pop()
            else:
                _need(False)
        return result

    @_operation
    def send(self, project, sid, message_id, text):
        _need(valid_uuid(sid) and valid_uuid(message_id) and type(text) is str
              and 0 < len(text) <= 16000 and bool(text.strip()), 'invalid_request')
        root = self._root(project)
        self._proof(root, sid)
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        with self.receipts.namespace(root, sid, self._local.deadline, create=True) as ns:
            record = self.receipts.read(ns, root, sid, message_id)
            if record is not None:
                _need(record['digest'] == digest, 'invalid_request')
                return self.receipts.result(record)
            _need(len(self.receipts.names(ns)) < RECEIPT_LIMIT)
            self._proof(root, sid, 'thread/resume')
            _need(self._root(project) == root, 'stale')
            self._remaining()
            record = {'root': root, 'sid': sid, 'message_id': message_id, 'digest': digest,
                      'status': 'delivery_unknown', 'turn_id': None, 'created': time.time_ns()}
            self.receipts.write(ns, record)
            try:
                response = self._rpc('turn/start', {'threadId': sid,
                    'input': [{'type': 'text', 'text': text}], 'clientUserMessageId': message_id})
                turn = response.get('turn')
                _need(type(turn) is dict and _identity(turn.get('id')))
                record.update(status='accepted', turn_id=turn['id'])
                self.receipts.write(ns, record)
            except Exception:
                # Reserve remains durable. Server errors, timeout and failed ACK
                # persistence never authorize automatic turn/start repetition.
                return {'status': 'delivery_unknown', 'message_id': message_id, 'turn_id': None}
            return self.receipts.result(record)

    @_operation
    def send_status(self, project, sid, message_id):
        _need(valid_uuid(sid) and valid_uuid(message_id), 'invalid_request')
        root = self._root(project)
        self._proof(root, sid)
        with self.receipts.namespace(root, sid, self._local.deadline) as ns:
            record = self.receipts.read(ns, root, sid, message_id)
            _need(record is not None, 'stale')
            if record['status'] != 'delivery_unknown':
                return self.receipts.result(record)
            cursor, seen = None, set()
            for _ in range(8):
                if time.monotonic() >= self._local.deadline:
                    break
                page = self._page(sid, cursor)
                for turn in page['data']:
                    if any(item['type'] == 'userMessage' and item.get('clientId') == message_id
                           for item in turn['items']):
                        record.update(status='accepted', turn_id=turn['id'])
                        self.receipts.write(ns, record)
                        return self.receipts.result(record)
                cursor = page['nextCursor']
                if cursor is None:
                    break
                _need(cursor not in seen)
                seen.add(cursor)
            return self.receipts.result(record)


class InteractiveRPC:
    """One receiver per connection; never responds to native server requests."""
    METHODS = {'initialize', 'thread/read', 'thread/list', 'thread/turns/list', 'thread/resume', 'turn/start'}

    def __init__(self, socket_path, timeout=25):
        if type(socket_path) is not str or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 55:
            raise ValueError('invalid RPC configuration')
        self.socket_path, self.timeout = socket_path, timeout
        self._lock = threading.RLock()
        self._connect_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._ws = None
        self._generation = 0
        self._pending = {}
        self._closed = False

    def _fail(self, ws, generation):
        with self._lock:
            if self._ws is not ws or self._generation != generation:
                return
            self._ws = None
            for waiter in self._pending.values():
                waiter['error'] = RuntimeError('RPC connection unavailable')
                waiter['event'].set()
            self._pending.clear()
        try:
            ws.close()
        except Exception:
            pass

    def _expire(self, ws, generation):
        with self._lock:
            if self._ws is not ws or self._generation != generation:
                return
        # A peer that stops reading must not leave sync ws.send blocked past
        # the operation deadline. Shutdown also wakes the independent receiver.
        try:
            ws.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._fail(ws, generation)

    def _receive(self, ws, generation):
        try:
            while True:
                value = json.loads(ws.recv(), object_pairs_hook=_pairs)
                if type(value) is not dict:
                    raise ValueError('invalid response')
                # Both callbacks and notifications are observational only.
                if 'method' in value:
                    continue
                if type(value.get('id')) is not str:
                    continue
                with self._lock:
                    if self._ws is not ws or self._generation != generation:
                        return
                    waiter = self._pending.pop(value['id'], None)
                    if waiter is None:
                        continue
                    error = value.get('error')
                    if ('error' in value and 'result' not in value and type(error) is dict
                            and set(error) in ({'code', 'message'}, {'code', 'message', 'data'})
                            and type(error['code']) is int and type(error['message']) is str):
                        waiter['error'] = RPCRejected('RPC server rejected request (code ' + str(error['code']) + ')')
                    elif 'error' not in value and type(value.get('result')) is dict:
                        waiter['result'] = value['result']
                    else:
                        waiter['error'] = RuntimeError('RPC invalid response')
                    waiter['event'].set()
        except Exception:
            self._fail(ws, generation)

    def _request(self, ws, generation, method, params, deadline):
        waiter = {'event': threading.Event()}
        request_id = str(uuid.uuid4())
        with self._lock:
            if self._ws is not ws or self._generation != generation or len(self._pending) >= 64:
                raise RuntimeError('RPC unavailable')
            self._pending[request_id] = waiter
        timer = threading.Timer(max(0, deadline - time.monotonic()), self._expire, args=(ws, generation))
        timer.daemon = True
        timer.start()
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._send_lock.acquire(timeout=max(0, remaining)):
                raise TimeoutError('RPC deadline exceeded')
            try:
                if time.monotonic() >= deadline:
                    raise TimeoutError('RPC deadline exceeded')
                ws.send(_json({'id': request_id, 'method': method, 'params': params}).decode('utf-8'))
            finally:
                self._send_lock.release()
            if not waiter['event'].wait(max(0, deadline - time.monotonic())):
                raise TimeoutError('RPC deadline exceeded')
            if 'error' in waiter:
                raise waiter['error']
            return waiter['result']
        except RPCRejected:
            raise
        except Exception:
            self._fail(ws, generation)
            raise RuntimeError('RPC operation unavailable') from None
        finally:
            timer.cancel()
            with self._lock:
                self._pending.pop(request_id, None)

    def _connect(self, deadline):
        if not self._connect_lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise RuntimeError('RPC connection unavailable')
        try:
            with self._lock:
                if self._closed:
                    raise RuntimeError('RPC closed')
                if self._ws is not None:
                    return self._ws, self._generation
            from websockets.sync.client import unix_connect
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('RPC connection unavailable')
            try:
                before = os.lstat(self.socket_path)
                if not stat.S_ISSOCK(before.st_mode) or before.st_uid != os.getuid():
                    raise ValueError('RPC socket ownership refused')
                ws = unix_connect(self.socket_path, uri='ws://localhost', open_timeout=remaining,
                                  close_timeout=1, max_size=4 * 1024 * 1024)
                after = os.lstat(self.socket_path)
                if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                    ws.close()
                    raise ValueError('RPC socket changed')
            except Exception:
                raise RuntimeError('RPC connection unavailable') from None
            with self._lock:
                if self._closed:
                    ws.close()
                    raise RuntimeError('RPC closed')
                self._generation += 1
                generation = self._generation
                self._ws = ws
            threading.Thread(target=self._receive, args=(ws, generation), daemon=True).start()
            try:
                self._request(ws, generation, 'initialize', {
                    'clientInfo': {'name': 'ai_control_web', 'version': '0.1'},
                    'capabilities': {'experimentalApi': True}}, deadline)
                if not self._send_lock.acquire(timeout=max(0, deadline - time.monotonic())):
                    raise RuntimeError('RPC deadline exceeded')
                timer = threading.Timer(max(0, deadline - time.monotonic()), self._expire, args=(ws, generation))
                timer.daemon = True
                timer.start()
                try:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('RPC deadline exceeded')
                    ws.send('{"method":"initialized"}')
                finally:
                    timer.cancel()
                    self._send_lock.release()
            except Exception:
                self._fail(ws, generation)
                raise RuntimeError('RPC initialization unavailable') from None
            return ws, generation
        finally:
            self._connect_lock.release()

    def call(self, method, params, timeout=None):
        if type(method) is not str or method not in self.METHODS or type(params) is not dict:
            raise ValueError('RPC method refused')
        duration = self.timeout if timeout is None else min(self.timeout, timeout)
        if type(duration) not in (float, int) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('RPC deadline refused')
        deadline = time.monotonic() + duration
        ws, generation = self._connect(deadline)
        return self._request(ws, generation, method, params, deadline)

    def __call__(self, method, params):
        return self.call(method, params)

    def close(self):
        with self._lock:
            self._closed = True
            ws, generation = self._ws, self._generation
        if ws is not None:
            self._fail(ws, generation)
