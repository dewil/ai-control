"""Narrow owner-side task interface. Never returns raw registry documents."""
from collections import namedtuple
from types import MappingProxyType
import math
import selectors
import hashlib
import json
import os
import re
import socket
import stat
import struct
import subprocess
import threading
import time
import uuid

LIMIT = 128 * 1024
FIELD_LIMIT = 16000
NAME = re.compile(r'[a-z][a-z0-9-]{0,30}[a-z0-9]\Z')
GEN = re.compile(r'[0-9a-f]{8}\Z')
PROJECT = re.compile(r'[a-zA-Z0-9_-]{1,32}\Z')
SESSION_FIELDS = {
    'session_projects': {'op'},
    'session_project_summary': {'op'},
    'session_list': {'op', 'project', 'page'},
    'session_history': {'op', 'project', 'sid', 'cursor'},
    'session_models': {'op', 'project', 'sid'},
    'session_send': {'op', 'project', 'sid', 'message_id', 'text'},
    'session_send_status': {'op', 'project', 'sid', 'message_id'},
    'session_rename': {'op', 'project', 'sid', 'operation_id', 'title'},
    'session_rename_status': {'op', 'project', 'sid', 'operation_id'},
    'session_create_options': {'op', 'project'},
    'session_create': {'op', 'project', 'operation_id', 'context_mode', 'provider_id'},
    'session_create_status': {'op', 'project', 'operation_id', 'context_mode', 'provider_id'},
}


def _valid_session(request):
    if (type(request) is not dict or type(request.get('op')) is not str
            or request['op'] not in SESSION_FIELDS):
        return False
    fields = SESSION_FIELDS[request['op']]
    if set(request) != fields and not (
            request['op'] == 'session_send' and set(request) == fields | {'selection'}):
        return False
    if 'selection' in request:
        from _control_web_sessions import _valid_selection
        if not _valid_selection(request['selection']):
            return False
    if 'project' in request and (type(request['project']) is not str or not PROJECT.fullmatch(request['project'])):
        return False
    if any(not valid_qid(request[key]) for key in ('sid', 'message_id', 'operation_id') if key in request):
        return False
    if 'page' in request and (type(request['page']) is not int or request['page'] < 0):
        return False
    if 'cursor' in request and request['cursor'] is not None and (
            type(request['cursor']) is not str or not 0 < len(request['cursor']) <= 4096):
        return False
    if 'context_mode' in request and (request['context_mode'] != 'configured'
                                      or request['provider_id'] != 'codex'):
        return False
    if 'title' in request and not valid_rename_title(request['title']):
        return False
    return 'text' not in request or valid_text(request['text'], True)


def valid_rename_title(title):
    try:
        from _control_web_sessions import SessionChat
        SessionChat._rename_title(title)
        return True
    except Exception:
        return False


def rename_result(result, operation_id):
    if type(result) is not dict:
        return {'error': 'unavailable'}
    if 'error' in result:
        code = result['error']
        return {'error': code if code in ('invalid_request', 'forbidden', 'stale') else 'unavailable'}
    if result.get('operation_id') != operation_id or result.get('status') not in ('accepted', 'delivery_unknown'):
        return {'error': 'unavailable'}
    safe = {'operation_id': operation_id, 'status': result['status']}
    if result['status'] == 'accepted':
        title = result.get('title')
        if type(title) is not str or not title.strip():
            return {'error': 'unavailable'}
        try:
            title.encode('utf-8')
        except UnicodeError:
            return {'error': 'unavailable'}
        safe['title'] = redact(title)[:500]
    return safe


def configured_create_result(result, project, operation_id=None):
    """Exact public DTO gate; no private object is projected by dropping fields."""
    failure = {'error': 'unavailable'}
    if type(result) is not dict:
        return failure
    if 'error' in result:
        code = result['error']
        return {'error': code if set(result) == {'error'} and code in
                ('invalid_request', 'forbidden', 'stale') else 'unavailable'}
    if operation_id is None:
        if (set(result) != {'schema', 'project', 'options'} or type(result['schema']) is not int
                or result['schema'] != 1 or result['project'] != project
                or type(result['options']) is not list or len(result['options']) != 1):
            return failure
        row = result['options'][0]
        if (type(row) is not dict or set(row) != {'context_mode', 'provider_id', 'available', 'reason'}
                or row['context_mode'] != 'configured' or row['provider_id'] != 'codex'
                or type(row['available']) is not bool
                or row['reason'] != (None if row['available'] else 'unavailable')):
            return failure
        return dict(schema=1, project=project, options=[dict(row)])
    if result.get('operation_id') != operation_id:
        return failure
    if result.get('status') == 'delivery_unknown':
        return dict(result) if set(result) == {'operation_id', 'status'} else failure
    if set(result) != {'operation_id', 'status', 'session'} or result['status'] != 'accepted':
        return failure
    session = result['session']
    if (type(session) is not dict or set(session) != {'sid', 'project', 'vendor', 'context_mode', 'title'}
            or not valid_qid(session['sid']) or session['project'] != project
            or session['vendor'] != 'codex' or session['context_mode'] != 'configured'
            or session['title'] is not None and (type(session['title']) is not str or len(session['title']) > 500)):
        return failure
    title = session['title']
    if title is not None:
        try:
            title.encode('utf-8')
        except UnicodeError:
            return failure
        title = redact(title)[:500]
    return dict(operation_id=operation_id, status='accepted', session=dict(session, title=title))


def history_result(result):
    """Validate the honest unavailable variant, leaving ordinary history unchanged."""
    if type(result) is not dict:
        return {'error': 'unavailable'}
    if 'history_state' not in result:
        return result
    if (set(result) not in ({'history_state', 'reason', 'recent_sends'},
                           {'history_state', 'reason', 'recent_sends', 'needs_native_attention'})
            or result['history_state'] != 'unavailable' or result['reason'] != 'unavailable'
            or 'needs_native_attention' in result and result['needs_native_attention'] is not True
            or type(result['recent_sends']) is not list or len(result['recent_sends']) > 8):
        return {'error': 'unavailable'}
    recent = []
    for row in result['recent_sends']:
        if (type(row) is not dict or set(row) != {'status', 'message_id', 'turn_id'}
                or not valid_qid(row['message_id'])
                or row['status'] not in ('accepted', 'delivery_unknown', 'rejected')
                or row['status'] in ('delivery_unknown', 'rejected') and row['turn_id'] is not None
                or row['status'] == 'accepted' and
                   (type(row['turn_id']) is not str or not 0 < len(row['turn_id']) <= 500)):
            return {'error': 'unavailable'}
        recent.append(dict(row))
    safe = dict(history_state='unavailable', reason='unavailable', recent_sends=recent)
    if result.get('needs_native_attention') is True:
        safe['needs_native_attention'] = True
    try:
        if len(json.dumps(safe, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 96 * 1024:
            return {'error': 'unavailable'}
    except (ValueError, UnicodeError):
        return {'error': 'unavailable'}
    return safe


def _send_request(project, sid, message_id, text, selection):
    request = dict(op='session_send', project=project, sid=sid, message_id=message_id, text=text)
    if selection is not None:
        request['selection'] = selection
    return request


def _forward_send(target, request):
    args = (request['project'], request['sid'], request['message_id'], request['text'])
    if 'selection' in request:
        return target(*args, selection=request['selection'])
    return target(*args)


# Intentional per-binary copy of ai-agent-run's complete export policy.
# Keep the established credential aliases without importing writer runtime.
SECRET_RE = re.compile(
    # покрытие расширено (аудит V2.7a, major 7): pwd/passwd/access_key -
    # смежные формы того же класса секрета, которые прежний список слов не
    # ловил (changes теперь тоже проходят через redact(), см. ниже).
    r'(?i)((?:api[_-]?key|access[_-]?key|token|secret|password|passwd|pwd|'
    r'authorization)"?\s*[=:]\s*"?'
    r'(?:bearer\s+)?)[^\s&"]+'
    r'|(\bbearer\s+)\S+'
    r'|\b(?:sk|xox[a-z]|ghp|gho|github_pat)-[A-Za-z0-9_-]{8,}'
    r'|\b[A-Za-z0-9+/_-]{40,}\b')


def redact(s):
    return SECRET_RE.sub(lambda m: (m.group(1) or m.group(2) or "") + "***", s)



def canonical_callback(callback, saved):
    if type(callback) is not dict:
        return False
    return (
        all(type(callback.get(key)) is str and callback[key]
            for key in ('attempt_id', 'thread_id', 'turn_id', 'item_id'))
        and valid_qid(callback.get('operation_id'))
        and type(callback.get('task_incarnation')) is str
        and bool(re.fullmatch(r'[0-9a-f]{32}', callback['task_incarnation']))
        and type(callback.get('generation')) is int and callback['generation'] > 0
        and (type(callback.get('request_id')) is int or
             (type(callback.get('request_id')) is str and bool(callback['request_id'])))
        and callback.get('method') == 'item/fileChange/requestApproval'
        and callback.get('status') in (('pending', 'answered') if saved else ('pending',))
        and all(type(callback.get(key)) is str and re.fullmatch(r'[0-9a-f]{64}', callback[key])
                for key in ('payload_fingerprint', 'changes_digest'))
        and callback.get('allowed_decisions') in (['reject'], ['approve', 'reject']))


def valid_agent(value):
    return type(value) is str and bool(NAME.fullmatch(value))


def valid_qid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def valid_text(value, nonempty=False):
    return type(value) is str and len(value) <= FIELD_LIMIT and (not nonempty or bool(value.strip()))


def _read(parent, name, optional=False, yaml=False):
    """Read relative to an anchored directory; no traversal or symlink races."""
    if '/' in name or name in ('.', '..'):
        raise ValueError('invalid record')
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except FileNotFoundError:
        if optional:
            return None
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('invalid record')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('large record')
        text = data.decode('utf-8')
        try:
            doc = json.loads(text)
        except ValueError:
            if not yaml:
                raise
            # Reuse Control's existing YAML parser, over bounded stdin bytes.
            # No registry path reaches yq and its stderr never reaches the UI.
            result = subprocess.run(['yq', '-p=yaml', '-o=json', '.', '-'],
                                    input=text, capture_output=True, text=True,
                                    shell=False, timeout=5)
            if result.returncode != 0 or len(result.stdout.encode()) > LIMIT:
                raise ValueError('invalid specification')
            doc = json.loads(result.stdout)
        if type(doc) is not dict:
            raise ValueError('invalid record')
        return doc
    finally:
        os.close(fd)


def _dir(parent, name):
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _field(doc, key, default=''):
    value = doc.get(key, default)
    if not valid_text(value):
        raise ValueError('invalid field')
    return value


# All reader helpers debit the same capture budget, including fences and parsing.
_ProjectCapture = namedtuple('_ProjectCapture', 'epoch revision identity entries')
_GrantCapture = namedtuple('_GrantCapture', 'principal owner_only epoch revision projects')


class _AttentionLimit(ValueError):
    pass


class _AttentionBinding(ValueError):
    pass


def _attention_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _attention_text(value, limit):
    return (type(value) is str and 0 < len(value) <= limit
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value))


def _attention_root(value):
    return (_attention_text(value, 4096) and value.startswith('/') and
            (value == '/' or not value.endswith('/') and
             all(p not in ('', '.', '..') for p in value[1:].split('/'))))


class _AttentionBudget:
    def __init__(self, deadline, monotonic):
        self.deadline, self.monotonic, self.bytes = deadline, monotonic, 0
        self.check()

    def check(self):
        now = self.monotonic()
        if (type(self.deadline) not in (int, float) or not math.isfinite(self.deadline)
                or type(now) not in (int, float) or not math.isfinite(now)
                or now >= self.deadline):
            raise _AttentionLimit('limit')
        return self.deadline - now

    def consume(self, amount):
        self.check()
        self.bytes += amount
        if self.bytes > 16 * 1024 * 1024:
            raise _AttentionLimit('limit')


def _attention_metadata(info, directory=False):
    if ((not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))
            or info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise ValueError('invalid metadata')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _attention_directory(path, parent=None):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        _attention_metadata(os.fstat(fd), True)
        return fd
    except Exception:
        os.close(fd)
        raise


def _attention_anchor(fd, path, parent=None):
    held = os.fstat(fd)
    current = os.stat(path, dir_fd=parent, follow_symlinks=False)
    _attention_metadata(held, True)
    _attention_metadata(current, True)
    if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
        raise _AttentionBinding('binding incomplete')


def _attention_bytes(parent, name, budget, optional=False):
    budget.check()
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except FileNotFoundError:
        if optional:
            return None
        raise
    try:
        before = _attention_metadata(os.fstat(fd))
        data = bytearray()
        while len(data) <= 65536:
            block = os.read(fd, min(8192, 65537 - len(data)))
            budget.consume(len(block))
            if not block:
                break
            data.extend(block)
        if len(data) > 65536:
            raise _AttentionLimit('limit')
        after = _attention_metadata(os.fstat(fd))
        bound = _attention_metadata(os.stat(name, dir_fd=parent, follow_symlinks=False))
        if before != after or after != bound:
            raise _AttentionBinding('binding incomplete')
        return bytes(data), before
    finally:
        os.close(fd)


def _attention_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate field')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('nonfinite value')
    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('nonfinite value')
        return result
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=constant, parse_float=floating)
    except RecursionError:
        raise ValueError('invalid document') from None


def _attention_yaml_runner(argv, *, input, capture_output, text, shell, timeout):
    """Fixed yq over pipes: bound both output streams before materializing them."""
    expires = time.monotonic() + timeout
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, shell=False)
    streams = (proc.stdin, proc.stdout, proc.stderr)
    outgoing, offset = input.encode('utf-8'), 0
    stdout, stderr = bytearray(), bytearray()
    try:
        with selectors.DefaultSelector() as poll:
            for stream in streams:
                os.set_blocking(stream.fileno(), False)
            poll.register(proc.stdin, selectors.EVENT_WRITE, None)
            poll.register(proc.stdout, selectors.EVENT_READ, stdout)
            poll.register(proc.stderr, selectors.EVENT_READ, stderr)
            while poll.get_map():
                remaining = expires - time.monotonic()
                if remaining <= 0:
                    raise _AttentionLimit('limit')
                for key, _ in poll.select(remaining):
                    stream, buffer = key.fileobj, key.data
                    if buffer is None:
                        if offset < len(outgoing):
                            try:
                                offset += os.write(stream.fileno(), outgoing[offset:offset + 4096])
                            except BrokenPipeError:
                                offset = len(outgoing)
                        if offset == len(outgoing):
                            poll.unregister(stream)
                            stream.close()
                    else:
                        block = os.read(stream.fileno(), 8192)
                        if not block:
                            poll.unregister(stream)
                            stream.close()
                        else:
                            buffer.extend(block)
                            if len(buffer) > 65536:
                                raise _AttentionLimit('limit')
            remaining = expires - time.monotonic()
            if remaining <= 0:
                raise _AttentionLimit('limit')
            proc.wait(timeout=remaining)
        return subprocess.CompletedProcess(argv, proc.returncode,
                                           stdout.decode('utf-8'), stderr.decode('utf-8'))
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        for stream in streams:
            if not stream.closed:
                stream.close()


def _attention_document(raw, budget, runner, yaml=False):
    data = raw[0]
    try:
        doc = _attention_json(data)
    except json.JSONDecodeError:
        if not yaml:
            raise
        budget.consume(len(data))
        try:
            result = runner(['yq', '-p=yaml', '-o=json', '.', '-'],
                            input=data.decode('utf-8'), capture_output=True, text=True,
                            shell=False, timeout=budget.check())
        except subprocess.TimeoutExpired:
            raise _AttentionLimit('limit') from None
        budget.check()
        if result.returncode != 0 or len(result.stdout.encode('utf-8')) > 65536:
            raise ValueError('invalid document')
        budget.consume(len(result.stdout.encode('utf-8')))
        doc = _attention_json(result.stdout.encode('utf-8'))
    if type(doc) is not dict:
        raise ValueError('invalid document')
    return doc


class OwnerProjectMap:
    def __init__(self, config_path, *, runner=None, monotonic=None):
        self.path = os.path.abspath(config_path)
        self.runner = runner or _attention_yaml_runner
        self.monotonic = monotonic or time.monotonic
        self._anchors, self._config_fd, self._capture = [], None, None
        self._incarnation, self._epoch, self._revision, self._identity = None, None, 0, None
        self._entries_identity = None
        self._budget, self._closed = None, False

    def _release(self):
        for _, fd in self._anchors:
            os.close(fd)
        self._anchors = []
        if self._config_fd is not None:
            os.close(self._config_fd)
            self._config_fd = None
        self._capture = None

    def close(self):
        self._release()
        self._closed = True

    def capture(self, *, deadline):
        return self._capture_budget(_AttentionBudget(deadline, self.monotonic))

    def _capture_budget(self, budget):
        if self._closed:
            raise RuntimeError('unavailable')
        # Keep old incarnations alive until their successor anchors are open,
        # so unlink/recreate cannot recycle an inode in a capture gap.
        previous_anchors, previous_config_fd = self._anchors, self._config_fd
        self._anchors, self._config_fd, self._capture = [], None, None
        self._budget = budget
        try:
            raw = _attention_bytes(None, self.path, budget)
            self._config_fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            if _attention_metadata(os.fstat(self._config_fd)) != raw[1]:
                raise _AttentionBinding()
            doc = _attention_document(raw, budget, self.runner, True)
            if len(doc) > 1000:
                raise _AttentionLimit()
            entries = []
            for alias, item in sorted(doc.items()):
                budget.check()
                if type(alias) is not str or not PROJECT.fullmatch(alias):
                    raise ValueError('invalid project')
                root = item.get('path') if type(item) is dict else item
                if not _attention_root(root):
                    raise ValueError('invalid root')
                root = os.path.realpath(root)
                fd = _attention_directory(root)
                self._anchors.append((root, fd))
                _attention_anchor(fd, root)
                info = os.fstat(fd)
                entries.append(MappingProxyType(dict(project=alias, root=root,
                    root_identity=_attention_digest(dict(root=root, dev=info.st_dev, ino=info.st_ino)))))
            identity = _attention_digest(dict(metadata=raw[1], sha256=hashlib.sha256(raw[0]).hexdigest()))
            incarnation = raw[1][:2]
            if incarnation != self._incarnation:
                self._epoch, self._revision = uuid.uuid4().hex, 0
            entries_identity = _attention_digest([dict(row) for row in entries])
            if incarnation == self._incarnation and (identity != self._identity or entries_identity != self._entries_identity):
                self._revision += 1
            captured = _ProjectCapture(self._epoch, self._revision, identity, tuple(entries))
            self._raw, self._capture = raw, captured
            if not self.current(captured, deadline=budget.deadline):
                raise _AttentionBinding()
            self._incarnation, self._identity = incarnation, identity
            self._entries_identity = entries_identity
            return captured
        except Exception:
            self._release()
            raise RuntimeError('unavailable') from None
        finally:
            for _, fd in previous_anchors:
                os.close(fd)
            if previous_config_fd is not None:
                os.close(previous_config_fd)

    def current(self, capture, *, deadline):
        try:
            budget = self._budget
            if self._closed or capture is not self._capture or budget is None or deadline != budget.deadline:
                return False
            budget.check()
            if _attention_metadata(os.fstat(self._config_fd)) != self._raw[1]:
                return False
            if _attention_bytes(None, self.path, budget) != self._raw:
                return False
            for path, fd in self._anchors:
                budget.check()
                _attention_anchor(fd, path)
            return True
        except Exception:
            return False


class OwnerRegisteredGrants:
    def __init__(self, *, owner_only=True):
        self.owner_only = owner_only

    def capture(self, project_capture, *, deadline):
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise RuntimeError('unavailable')
        return _GrantCapture('owner', self.owner_only is True, project_capture.epoch,
                             project_capture.revision, tuple(sorted(row['project'] for row in project_capture.entries)))

    def current(self, grant_capture, project_capture, *, deadline):
        try:
            return grant_capture == self.capture(project_capture, deadline=deadline)
        except Exception:
            return False


class RegistryAttentionView:
    def __init__(self, registry, *, projects, grants, monotonic=None):
        self.registry = os.path.abspath(registry)
        self.projects, self.grants = projects, grants
        self.monotonic = monotonic or time.monotonic
        self._active, self._root_fd, self._closed = None, None, False
        self._root_identity, self._source_epoch = None, None
        self._epoch, self._revision, self._signature = uuid.uuid4().hex, 0, None

    def close(self):
        self._closed, self._active = True, None
        if self._root_fd is not None:
            os.close(self._root_fd)
            self._root_fd = None
        close = getattr(self.projects, 'close', None)
        if close:
            close()

    def snapshot(self, *, deadline):
        self._active = None
        try:
            if self._closed:
                raise ValueError()
            budget = _AttentionBudget(deadline, self.monotonic)
            pc = (self.projects._capture_budget(budget) if isinstance(self.projects, OwnerProjectMap)
                  else self.projects.capture(deadline=deadline))
            self._validate_projects(pc)
            budget.check()
            if self._root_fd is not None:
                try:
                    _attention_anchor(self._root_fd, self.registry)
                except Exception:
                    os.close(self._root_fd)
                    self._root_fd = None
            if self._root_fd is None:
                self._root_fd = _attention_directory(self.registry)
                self._source_epoch = uuid.uuid4().hex
            _attention_anchor(self._root_fd, self.registry)
            info = os.fstat(self._root_fd)
            self._root_identity = _attention_digest(dict(kind='attention_registry',
                root=os.path.realpath(self.registry), dev=info.st_dev, ino=info.st_ino))
            gc = self.grants.capture(pc, deadline=deadline)
            self._validate_grants(gc, pc)
            if self.grants.current(gc, pc, deadline=deadline) is not True:
                raise ValueError()
            signature = (pc.epoch, pc.revision, pc.identity, gc.epoch, gc.revision,
                         gc.principal, gc.owner_only, tuple(gc.projects), self._root_identity)
            if self._signature != signature:
                self._revision += 1
                self._signature = signature
            vs = dict(schema=1, principal=gc.principal, epoch=self._epoch, revision=self._revision,
                registry_epoch=pc.epoch, registry_revision=pc.revision,
                context_id=_attention_digest(dict(kind='attention_projection_context', epoch=self._epoch)),
                route_id=_attention_digest(dict(kind='attention_projection_route', epoch=self._epoch)),
                route_epoch=self._epoch, route_revision=self._revision,
                owner_only=gc.owner_only is True and gc.principal == 'owner')
            self._active = (pc, gc, vs, budget)
            if not self.current(vs, deadline=deadline):
                raise ValueError()
            return dict(vs)
        except Exception:
            self._active = None
            raise RuntimeError('unavailable') from None

    @staticmethod
    def _validate_projects(pc):
        if (not re.fullmatch('[0-9a-f]{32}', pc.epoch) or type(pc.revision) is not int or pc.revision < 0
                or not re.fullmatch('[0-9a-f]{64}', pc.identity) or len(pc.entries) > 1000):
            raise ValueError()
        seen = set()
        for row in pc.entries:
            if (set(row) != {'project', 'root', 'root_identity'} or type(row['project']) is not str
                    or not PROJECT.fullmatch(row['project']) or not _attention_root(row['root'])
                    or not re.fullmatch('[0-9a-f]{64}', row['root_identity']) or row['project'] in seen):
                raise ValueError()
            seen.add(row['project'])

    @staticmethod
    def _validate_grants(gc, pc):
        if (type(gc.principal) is not str or not re.fullmatch('[a-z][a-z0-9_-]{0,31}', gc.principal)
                or type(gc.owner_only) is not bool or not re.fullmatch('[0-9a-f]{32}', gc.epoch)
                or type(gc.revision) is not int or gc.revision < 0
                or tuple(gc.projects) != tuple(sorted(set(gc.projects)))
                or any(p not in {r['project'] for r in pc.entries} for p in gc.projects)):
            raise ValueError()

    def current(self, view_snapshot, *, deadline):
        try:
            if self._closed or self._active is None:
                return False
            pc, gc, vs, budget = self._active
            if view_snapshot != vs or deadline != budget.deadline:
                return False
            budget.check()
            _attention_anchor(self._root_fd, self.registry)
            return (self.projects.current(pc, deadline=deadline) is True
                    and self.grants.current(gc, pc, deadline=deadline) is True)
        except Exception:
            return False

    def resolve_project(self, project, view_snapshot, *, deadline):
        if self._active is None or view_snapshot != self._active[2]:
            return None
        pc, gc, vs, budget = self._active
        if deadline != budget.deadline:
            return None
        budget.check()
        for row in pc.entries:
            if row['project'] == project:
                return dict(project=project, root=row['root'], registry_epoch=pc.epoch,
                            registry_revision=pc.revision)
        return None

    def authorize(self, project_binding, view_snapshot, *, deadline):
        if self._active is None or view_snapshot != self._active[2] or type(project_binding) is not dict:
            return False
        pc, gc, vs, budget = self._active
        budget.check()
        return (vs['owner_only'] and project_binding.get('project') in gc.projects
                and project_binding == self.resolve_project(project_binding.get('project'), vs, deadline=deadline))


# Equivalent read-only ai-agent-io structural rules, including private references.
# Importing that writer pulls provider runtime helpers into the fixed web closure.
def _attention_control(doc):
    if (type(doc.get('schema')) is not int or doc['schema'] != 1
            or type(doc.get('seq')) is not int or doc['seq'] < 0
            or type(doc.get('generation')) is not int or doc['generation'] < 0
            or type(doc.get('incarnation')) is not str or not re.fullmatch('[0-9a-f]{32}', doc['incarnation'])
            or doc.get('desired') not in ('running', 'paused', 'stopped')
            or type(doc.get('lease')) is not dict or doc['lease'].get('state') not in ('none', 'acquiring', 'active', 'stopping')
            or type(doc.get('acceptance')) is not dict or doc['acceptance'].get('status') not in ('pending', 'needs-human', 'revise', 'accepted', 'rejected')
            or doc.get('hold') not in (None, 'luks_locked', 'budget_exhausted', 'admission_queue')):
        raise ValueError()
    att, ho = doc.get('attention'), doc.get('handoff')
    if (att is not None and (type(att) is not dict or not att.get('reason'))
            or ho is not None and (type(ho) is not dict or ho.get('phase') not in ('prepared', 'adopting', 'adopted', 'expired', 'aborted'))):
        raise ValueError()
    binding = doc.get('provider_binding')
    if 'provider_binding' in doc and (type(binding) is not dict or set(binding) != {'schema', 'provider_id', 'account_id'}
            or type(binding['schema']) is not int or binding['schema'] != 1
            or any(type(binding[k]) is not str or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', binding[k]) for k in ('provider_id', 'account_id'))):
        raise ValueError()
    if 'provider_context' in doc:
        ref = doc['provider_context']
        if (type(ref) is not dict or set(ref) != {'schema', 'provider_id', 'account_id', 'profile_instance_id', 'adapter_revision', 'registration_snapshot'}
                or type(ref['schema']) is not int or ref['schema'] != 1 or ref['provider_id'] != 'codex'
                or type(ref['account_id']) is not str or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', ref['account_id'])
                or not valid_qid(ref['profile_instance_id']) or uuid.UUID(ref['profile_instance_id']).version != 4
                or ref['adapter_revision'] != 'codex-managed-chatgpt-file-v1' or binding is None
                or any(ref[k] != binding[k] for k in ('provider_id', 'account_id'))):
            raise ValueError()
        snap = ref['registration_snapshot']
        if (type(snap) is not dict or set(snap) != {'dev', 'ino', 'ctime_ns', 'sha256'}
                or any(type(snap[k]) is not int or snap[k] < 0 for k in ('dev', 'ino', 'ctime_ns'))
                or type(snap['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', snap['sha256'])):
            raise ValueError()


def _attention_state(doc, generation, control):
    if (type(doc.get('schema')) is not int or doc['schema'] != 1
            or type(doc.get('generation')) is not int or doc['generation'] != generation
            or not _attention_text(doc.get('attempt_id'), 500)
            or doc.get('phase') not in ('working', 'sleeping', 'waiting_input', 'blocked')
            or doc.get('agent_claim') not in ('running', 'done', 'blocked')):
        raise ValueError()
    if doc['attempt_id'] != control['lease'].get('start_attempt_id'):
        raise _AttentionBinding()


class RegistryAttentionSource:
    def __init__(self, view, *, monotonic=None, wall_clock=None):
        self.view = view
        self.monotonic, self.wall_clock = monotonic or time.monotonic, wall_clock or time.time
        self._revision, self._state_digest, self._epoch = 0, None, None

    def _task(self, name, pc, gc, vs, budget, questions_count):
        root = self.view._root_fd
        fd = _attention_directory(name, root)
        try:
            spec_raw = _attention_bytes(fd, 'spec.yaml', budget)
            spec = _attention_document(spec_raw, budget, getattr(self.view.projects, 'runner', _attention_yaml_runner), True)
            if spec.get('type') != 'task':
                if spec.get('type') in ('mission', 'event'):
                    return None
                raise ValueError()
            engine = spec.get('engine', 'claude')
            if engine not in ('codex', 'claude'):
                raise ValueError()
            candidate = spec.get('project')
            aliases = sorted(r['project'] for r in pc.entries if r['root'] == candidate and r['project'] in gc.projects)
            if not aliases:
                raise _AttentionBinding()
            binding = self.view.resolve_project(aliases[0], vs, deadline=budget.deadline)
            control_raw = _attention_bytes(fd, 'control.json', budget)
            control = _attention_document(control_raw, budget, None)
            if type(control.get('incarnation')) is not str or not re.fullmatch('[0-9a-f]{32}', control['incarnation']):
                raise _AttentionBinding()
            _attention_control(control)
            generation = control['generation']
            state_raw = _attention_bytes(fd, 'state.%d.json' % generation, budget, optional=True)
            if generation > 0 and state_raw is None:
                raise _AttentionBinding()
            state = _attention_document(state_raw, budget, None) if state_raw else None
            if state is not None:
                _attention_state(state, generation, control)
            attempt = state['attempt_id'] if state else None
            label = spec.get('name', name)
            if not _attention_text(label, 16000):
                raise ValueError()
            label = redact(label)[:120]
            questions = []
            question_files = []
            try:
                qfd = _attention_directory('questions', fd)
            except FileNotFoundError:
                qfd = None
            if qfd is not None:
                try:
                    with os.scandir(qfd) as entries:
                        for entry in entries:
                            budget.check()
                            questions_count[0] += 1
                            if questions_count[0] > 1000:
                                raise _AttentionLimit()
                            filename = entry.name
                            if not filename.endswith('.json'):
                                continue
                            if not valid_qid(filename[:-5]):
                                raise ValueError()
                            question_raw = _attention_bytes(qfd, filename, budget)
                            question_files.append((filename, question_raw))
                            doc = _attention_document(question_raw, budget, None)
                            qid = filename[:-5]
                            if doc.get('qid') != qid or doc.get('kind') not in ('info', 'permission') or doc.get('status') not in ('open', 'closed'):
                                raise ValueError()
                            answered = doc.get('answered_at') is not None
                            published = doc.get('event_published_at') is not None
                            if answered and (not _attention_text(doc['answered_at'], 500) or not _attention_text(doc.get('answered_by'), 500)):
                                raise ValueError()
                            if published and not _attention_text(doc['event_published_at'], 500):
                                raise ValueError()
                            if answered and doc['kind'] == 'permission' and doc.get('decision') not in ('approve', 'reject'):
                                raise ValueError()
                            if answered and doc['kind'] == 'info' and not valid_text(doc.get('answer')):
                                raise ValueError()
                            questions.append(dict(qid=qid, kind=doc['kind'], status=doc['status'], answered=answered,
                                pending_delivery=answered and not published, blocking='unknown', native_key=None))
                    for filename, raw in question_files:
                        if _attention_bytes(qfd, filename, budget) != raw:
                            raise _AttentionBinding()
                    _attention_anchor(qfd, 'questions', fd)
                finally:
                    os.close(qfd)
            done_raw = _attention_bytes(fd, 'done.json', budget, True)
            result = None
            if done_raw is not None:
                done = _attention_document(done_raw, budget, None)
                key, commit = done.get('envelope_key'), done.get('commit_sha')
                if commit is None:
                    commit = ''
                if (not _attention_text(key, 500) or done.get('state') not in ('requested', 'accepted', 'integrated', 'cleaned', 'archived', 'rejected')
                        or type(done.get('finalized')) is not bool or type(commit) is not str
                        or commit and not re.fullmatch('(?:[0-9a-f]{40}|[0-9a-f]{64})', commit)):
                    raise ValueError()
                task_key = _attention_digest(dict(kind='attention_task', registry_id=self.view._root_identity,
                                                 agent=name, incarnation=control['incarnation']))
                result = dict(generation=hashlib.sha256(('done-gen:' + key + ':' + commit).encode()).hexdigest()[:8],
                              state=done['state'], finalized=done['finalized'],
                              result_key=_attention_digest(dict(kind='attention_result', task_key=task_key,
                                                              envelope_key=key, commit_sha=commit)))
            if (_attention_bytes(fd, 'control.json', budget) != control_raw
                    or _attention_bytes(fd, 'state.%d.json' % generation, budget, optional=generation == 0) != state_raw
                    or _attention_bytes(fd, 'spec.yaml', budget) != spec_raw
                    or _attention_bytes(fd, 'done.json', budget, True) != done_raw):
                raise _AttentionBinding()
            _attention_anchor(fd, name, root)
            return dict(registry_id=self.view._root_identity, agent=name, incarnation=control['incarnation'],
                generation=generation, attempt_id=attempt, project_binding=binding, session_binding=None,
                label=label, engine=engine, questions=sorted(questions, key=lambda q: q['qid']), result=result)
        finally:
            os.close(fd)

    def snapshot(self, *, deadline):
        active = getattr(self.view, '_active', None)
        coverage = dict(scope='none', registry_epoch=None, registry_revision=None, context_ids=[], route_ids=[],
                        session_set_revision=None, global_complete=False, supported_methods=[])
        snapshot = dict(schema=1, source='task_registry', epoch=None, revision=0, observed_at=None,
                        state='unavailable', complete=False, reason='unavailable', coverage=coverage, records=[])
        if active is None:
            return snapshot
        pc, gc, vs, budget = active
        snapshot['epoch'] = self.view._source_epoch
        snapshot['revision'] = self._revision
        coverage.update(scope='task_registry', registry_epoch=pc.epoch, registry_revision=pc.revision)
        records, reason, state = [], None, 'fresh'
        try:
            if deadline != budget.deadline or not vs['owner_only']:
                raise _AttentionBinding()
            _AttentionBudget(deadline, self.monotonic).check()
            budget.check()
            _attention_anchor(self.view._root_fd, self.view.registry)
            if not self.view.current(vs, deadline=deadline):
                budget.check()
                if budget.bytes > 16 * 1024 * 1024:
                    raise _AttentionLimit()
                raise _AttentionBinding()
            questions_count, count = [0], 0
            with os.scandir(self.view._root_fd) as entries:
                for entry in entries:
                    budget.check()
                    count += 1
                    if count > 1000:
                        raise _AttentionLimit()
                    if not valid_agent(entry.name):
                        continue
                    try:
                        record = self._task(entry.name, pc, gc, vs, budget, questions_count)
                        if record is not None:
                            records.append(record)
                    except _AttentionLimit:
                        raise
                    except _AttentionBinding:
                        state, reason = 'incomplete', 'binding_incomplete'
                    except (ValueError, OSError, TypeError, subprocess.SubprocessError):
                        state, reason = 'incomplete', 'invalid_source'
            _attention_anchor(self.view._root_fd, self.view.registry)
            if not self.view.current(vs, deadline=deadline):
                budget.check()
                if budget.bytes > 16 * 1024 * 1024:
                    raise _AttentionLimit()
                raise _AttentionBinding()
        except _AttentionLimit:
            state, reason = 'incomplete', 'limit'
        except _AttentionBinding:
            records, state, reason = [], 'incomplete', 'binding_incomplete'
        except (OSError, ValueError, TypeError):
            records, state, reason = [], 'unavailable', 'unavailable'
        records.sort(key=lambda r: r['agent'])
        snapshot.update(state=state, reason=reason, records=records, complete=state == 'fresh')
        coverage['global_complete'] = snapshot['complete']
        if records or snapshot['complete']:
            now = self.wall_clock()
            if type(now) in (int, float) and math.isfinite(now) and now > 0:
                snapshot['observed_at'] = int(now)
            else:
                snapshot.update(observed_at=None, records=[], complete=False, state='unavailable', reason='unavailable')
                coverage['global_complete'] = False
        signature = _attention_digest(dict(records=snapshot['records'], state=snapshot['state'], reason=snapshot['reason'],
                                           complete=snapshot['complete'], coverage=coverage))
        if self._epoch != snapshot['epoch']:
            self._epoch, self._revision, self._state_digest = snapshot['epoch'], 0, None
        if signature != self._state_digest:
            self._revision += 1
            self._state_digest = signature
        snapshot['revision'] = self._revision
        return snapshot


def attention_result(result):
    """Validate the entire compact export; never sanitize an arbitrary raw DTO."""
    failure = {'error': 'unavailable'}
    if type(result) is not dict:
        return failure
    if 'error' in result:
        return {'error': 'forbidden'} if result == {'error': 'forbidden'} else failure
    def exact(value, fields):
        if type(value) is not dict or set(value) != set(fields.split()):
            raise ValueError()
    def integer(value, minimum=0):
        if type(value) is not int or value < minimum:
            raise ValueError()
    def hexadecimal(value, length=64):
        if type(value) is not str or not re.fullmatch('[0-9a-f]{%d}' % length, value):
            raise ValueError()
    def enum(value, choices):
        if type(value) is not str or value not in choices.split():
            raise ValueError()
    def label(value):
        if not _attention_text(value, 120) or redact(value) != value:
            raise ValueError()
    def alias(value):
        if type(value) is not str or not PROJECT.fullmatch(value):
            raise ValueError()
    def ids(value, cap):
        if type(value) is not list or len(value) > cap:
            raise ValueError()
        for item in value:
            hexadecimal(item)
        if len(value) != len(set(value)):
            raise ValueError()
    try:
        exact(result, 'schema epoch revision observed_at complete truncated sources pool sessions reasons unlinked_tasks')
        integer(result['schema'], 1)
        if result['schema'] != 1:
            raise ValueError()
        hexadecimal(result['epoch'], 32)
        integer(result['revision'])
        integer(result['observed_at'], 1)
        if type(result['complete']) is not bool or type(result['truncated']) is not bool or result['complete'] and result['truncated']:
            raise ValueError()
        exact(result['sources'], 'task_registry activity native_callbacks')
        for source in result['sources'].values():
            exact(source, 'state complete observed_at reason')
            enum(source['state'], 'fresh incomplete unavailable unsupported stale')
            if type(source['complete']) is not bool:
                raise ValueError()
            if source['observed_at'] is not None:
                integer(source['observed_at'], 1)
            if source['reason'] is not None:
                enum(source['reason'], 'unavailable disconnected binding_incomplete unsupported limit invalid_source')
            if source['complete'] and (source['state'] != 'fresh' or source['observed_at'] is None or source['reason'] is not None):
                raise ValueError()
        if result['complete'] and any(not s['complete'] or s['state'] != 'fresh' for s in result['sources'].values()):
            raise ValueError()
        exact(result['pool'], 'known_sessions running decision question completed')
        for value in result['pool'].values():
            integer(value)
        if (type(result['sessions']) is not list or len(result['sessions']) > 256
                or type(result['unlinked_tasks']) is not list or len(result['unlinked_tasks']) > 128
                or type(result['reasons']) is not list or len(result['reasons']) > 512):
            raise ValueError()
        sessions, tasks, reasons = {}, {}, {}
        for row in result['sessions']:
            exact(row, 'session_key project sid vendor context_label label activity_state primary_state reason_ids')
            hexadecimal(row['session_key'])
            alias(row['project'])
            if not valid_qid(row['sid']) or row['vendor'] != 'codex':
                raise ValueError()
            label(row['context_label'])
            label(row['label'])
            enum(row['activity_state'], 'running waiting idle unknown stale')
            enum(row['primary_state'], 'decision question running completed idle unknown')
            ids(row['reason_ids'], 512)
            if row['session_key'] in sessions:
                raise ValueError()
            sessions[row['session_key']] = row
        for row in result['unlinked_tasks']:
            exact(row, 'task_key project label engine reason_ids')
            hexadecimal(row['task_key'])
            alias(row['project'])
            label(row['label'])
            enum(row['engine'], 'codex claude')
            ids(row['reason_ids'], 512)
            if not row['reason_ids'] or row['task_key'] in tasks:
                raise ValueError()
            tasks[row['task_key']] = row
        for row in result['reasons']:
            exact(row, 'reason_id session_key task_key kind source state target')
            hexadecimal(row['reason_id'])
            enum(row['kind'], 'decision question completed delivery_pending')
            enum(row['source'], 'task_registry native_callbacks')
            enum(row['state'], 'pending stale unknown')
            if row['reason_id'] in reasons:
                raise ValueError()
            target = row['target']
            if row['session_key'] is not None:
                hexadecimal(row['session_key'])
                if row['task_key'] is not None or row['session_key'] not in sessions:
                    raise ValueError()
                exact(target, 'kind project sid')
                owner = sessions[row['session_key']]
                if target != dict(kind='session', project=owner['project'], sid=owner['sid']):
                    raise ValueError()
            else:
                hexadecimal(row['task_key'])
                if row['task_key'] not in tasks or row['source'] != 'task_registry':
                    raise ValueError()
                exact(target, 'kind agent task_key qid result_generation')
                owner = tasks[row['task_key']]
                if target['kind'] != 'task' or not valid_agent(target['agent']) or target['task_key'] != row['task_key']:
                    raise ValueError()
                if row['kind'] == 'completed':
                    if target['qid'] is not None:
                        raise ValueError()
                    hexadecimal(target['result_generation'], 8)
                elif not valid_qid(target['qid']) or target['result_generation'] is not None:
                    raise ValueError()
            if row['reason_id'] not in owner['reason_ids']:
                raise ValueError()
            reasons[row['reason_id']] = row
        used = []
        expected = dict(known_sessions=len(sessions), running=0, decision=0, question=0, completed=0)
        for row in list(sessions.values()) + list(tasks.values()):
            for rid in row['reason_ids']:
                if rid not in reasons:
                    raise ValueError()
                reason = reasons[rid]
                if (reason['session_key'] != row.get('session_key') or reason['task_key'] != row.get('task_key')):
                    raise ValueError()
                used.append(rid)
            if 'session_key' in row:
                expected['running'] += row['activity_state'] == 'running'
                kinds = {reasons[rid]['kind'] for rid in row['reason_ids']}
                for kind in ('decision', 'question', 'completed'):
                    expected[kind] += kind in kinds
                primary = ('decision' if 'decision' in kinds else 'question' if 'question' in kinds
                           else 'running' if row['activity_state'] == 'running'
                           else 'completed' if 'completed' in kinds else 'idle' if row['activity_state'] == 'idle' else 'unknown')
                if row['primary_state'] != primary:
                    raise ValueError()
        if len(used) != len(set(used)) or set(used) != set(reasons) or result['pool'] != expected:
            raise ValueError()
        wire = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(wire) > LIMIT:
            raise ValueError()
        return _attention_json(wire)
    except (ValueError, TypeError, KeyError, UnicodeError):
        return failure


class RegistryBackend:
    def __init__(self, registry, bin_dir, runner=None, sessions=None, configured_creator=None,
                 attention=None, owner_only=True):
        self.registry = os.path.abspath(registry)
        self.bin_dir = os.path.abspath(bin_dir)
        self.runner = runner or subprocess.run
        self.sessions = sessions
        self.configured_creator = configured_creator
        self.attention, self.owner_only = attention, owner_only
        self._attention_lock = threading.Lock()

    def attention_snapshot(self):
        if self.owner_only is not True:
            return {'error': 'forbidden'}
        if self.attention is None or not self._attention_lock.acquire(blocking=False):
            return {'error': 'unavailable'}
        try:
            return attention_result(self.attention.snapshot())
        except Exception:
            return {'error': 'unavailable'}
        finally:
            self._attention_lock.release()

    def _session(self, request):
        if not _valid_session(request):
            return {'error': 'invalid_request'}
        if request['op'] in ('session_create_options', 'session_create', 'session_create_status'):
            if self.configured_creator is None:
                return {'error': 'unavailable'}
            try:
                method = {'session_create_options': 'options', 'session_create': 'create',
                          'session_create_status': 'status'}[request['op']]
                args = (request['project'],) if method == 'options' else (
                    request['project'], request['operation_id'], request['context_mode'], request['provider_id'])
                result = getattr(self.configured_creator, method)(*args)
            except Exception as exc:
                result = {'error': getattr(exc, 'code', 'unavailable')}
            return configured_create_result(result, request['project'], request.get('operation_id'))
        if self.sessions is None:
            return {'error': 'unavailable'}
        try:
            op = request['op']
            if op == 'session_projects':
                result = self.sessions.projects()
            elif op == 'session_project_summary':
                result = self.sessions.project_summary()
            elif op == 'session_list':
                result = self.sessions.list_sessions(request['project'], request['page'])
            elif op == 'session_history':
                result = self.sessions.history(request['project'], request['sid'], request['cursor'])
            elif op == 'session_models':
                result = self.sessions.models(request['project'], request['sid'])
            elif op == 'session_send':
                result = _forward_send(self.sessions.send, request)
            elif op == 'session_rename':
                result = self.sessions.rename(request['project'], request['sid'], request['operation_id'], request['title'])
            elif op == 'session_rename_status':
                result = self.sessions.rename_status(request['project'], request['sid'], request['operation_id'])
            else:
                result = self.sessions.send_status(request['project'], request['sid'], request['message_id'])
            if op == 'session_history':
                return history_result(result)
            if op in ('session_rename', 'session_rename_status'):
                return rename_result(result, request['operation_id'])
            return result if type(result) is dict else {'error': 'unavailable'}
        except Exception:
            return {'error': 'unavailable'}

    def session_projects(self):
        return self._session({'op': 'session_projects'})

    def session_project_summary(self):
        return self._session({'op': 'session_project_summary'})

    def session_list(self, project, page):
        return self._session(dict(op='session_list', project=project, page=page))

    def session_history(self, project, sid, cursor):
        return self._session(dict(op='session_history', project=project, sid=sid, cursor=cursor))

    def session_models(self, project, sid):
        return self._session(dict(op='session_models', project=project, sid=sid))

    def session_send(self, project, sid, message_id, text, selection=None):
        return self._session(_send_request(project, sid, message_id, text, selection))

    def session_send_status(self, project, sid, message_id):
        return self._session(dict(op='session_send_status', project=project, sid=sid, message_id=message_id))

    def session_create_options(self, project):
        return self._session(dict(op='session_create_options', project=project))

    def session_create(self, project, operation_id, context_mode, provider_id):
        return self._session(dict(op='session_create', project=project, operation_id=operation_id,
                                  context_mode=context_mode, provider_id=provider_id))

    def session_create_status(self, project, operation_id, context_mode, provider_id):
        return self._session(dict(op='session_create_status', project=project, operation_id=operation_id,
                                  context_mode=context_mode, provider_id=provider_id))

    def session_rename(self, project, sid, operation_id, title):
        return self._session(dict(op='session_rename', project=project, sid=sid, operation_id=operation_id, title=title))

    def session_rename_status(self, project, sid, operation_id):
        return self._session(dict(op='session_rename_status', project=project, sid=sid, operation_id=operation_id))

    def _root(self):
        return os.open(self.registry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def _raw_question(self, agent, qid):
        root = self._root()
        try:
            fd = _dir(root, agent)
            try:
                qfd = _dir(fd, 'questions')
                try:
                    return _read(qfd, qid + '.json')
                finally:
                    os.close(qfd)
            finally:
                os.close(fd)
        finally:
            os.close(root)

    def _question(self, fd, qid, engine):
        doc = _read(fd, qid + '.json')
        if doc.get('qid') != qid or doc.get('kind') not in ('info', 'permission') or doc.get('status') not in ('open', 'closed'):
            raise ValueError('invalid question')
        saved = doc.get('answered_at') is not None
        published = doc.get('event_published_at') is not None
        if saved and (not valid_text(doc['answered_at'], True) or not valid_text(doc.get('answered_by'), True)):
            raise ValueError('invalid saved answer')
        if published and not valid_text(doc['event_published_at'], True):
            raise ValueError('invalid publication')
        allowed, saved_answer, saved_decision = [], '', None
        if doc['kind'] == 'permission':
            allowed = ['approve', 'reject']
            if saved:
                saved_decision = doc.get('decision')
                if saved_decision not in allowed:
                    raise ValueError('invalid saved decision')
            if engine == 'codex' or doc.get('native_callback') is not None:
                callback = doc.get('native_callback')
                if engine != 'codex' or doc.get('engine') != 'codex' or not canonical_callback(callback, saved):
                    raise ValueError('invalid callback')
                allowed = callback['allowed_decisions']
                if saved and saved_decision not in allowed:
                    raise ValueError('invalid saved native decision')
        elif doc.get('native_callback') is not None:
            raise ValueError('invalid callback kind')
        elif saved:
            saved_answer = redact(_field(doc, 'answer'))
        return {'qid': qid, 'kind': doc['kind'], 'status': doc['status'],
                'question': redact(_field(doc, 'question')),
                'allowed_decisions': [] if saved or doc['status'] != 'open' else allowed,
                'answered': saved, 'pending_delivery': saved and not published,
                'saved_answer': saved_answer, 'saved_decision': saved_decision}

    def _optional_task_key(self, root, fd, name, spec, control):
        """Separate local proof; never touches attention capture or its lock."""
        try:
            budget = _AttentionBudget(time.monotonic() + 5, time.monotonic)
            _attention_anchor(root, self.registry)
            _attention_anchor(fd, name, root)
            raw = _attention_bytes(fd, 'control.json', budget)
            current = _attention_document(raw, budget, None)
            _attention_control(current)
            if current != control or spec.get('type') != 'task':
                return None
            spec_raw = _attention_bytes(fd, 'spec.yaml', budget)
            if _attention_document(spec_raw, budget, _attention_yaml_runner, True) != spec:
                return None
            if (_attention_bytes(fd, 'control.json', budget) != raw
                    or _attention_bytes(fd, 'spec.yaml', budget) != spec_raw):
                return None
            _attention_anchor(fd, name, root)
            _attention_anchor(root, self.registry)
            info = os.fstat(root)
            registry_id = _attention_digest(dict(kind='attention_registry', root=os.path.realpath(self.registry),
                                                dev=info.st_dev, ino=info.st_ino))
            return _attention_digest(dict(kind='attention_task', registry_id=registry_id,
                                          agent=name, incarnation=current['incarnation']))
        except Exception:
            return None

    def _task(self, root, name):
        fd = _dir(root, name)
        try:
            spec = _read(fd, 'spec.yaml', yaml=True)
            if spec.get('type') not in ('task', 'mission', 'event'):
                raise ValueError('invalid spec type')
            for key in ('type', 'engine', 'name'):
                if key in spec and not valid_text(spec[key], True):
                    raise ValueError('invalid spec scalar')
            if spec.get('type') != 'task':
                return None
            engine = spec.get('engine', 'claude')
            if engine not in ('claude', 'codex'):
                raise ValueError('invalid engine')
            control = _read(fd, 'control.json')
            generation = control.get('generation')
            if not isinstance(generation, (str, int)) or type(generation) is bool or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(generation)):
                raise ValueError('invalid generation')
            state = _read(fd, 'state.' + str(generation) + '.json', optional=True) or {}
            questions = []
            try:
                qfd = _dir(fd, 'questions')
            except FileNotFoundError:
                qfd = None
            if qfd is not None:
                try:
                    filenames = [n for n in os.listdir(qfd) if n.endswith('.json')]
                    if len(filenames) > 1000:
                        raise ValueError('many questions')
                    for filename in sorted(filenames):
                        qid = filename[:-5]
                        if not valid_qid(qid):
                            raise ValueError('invalid qid')
                        questions.append(self._question(qfd, qid, engine))
                finally:
                    os.close(qfd)
            done = _read(fd, 'done.json', optional=True)
            result = None
            if done is not None:
                key = _field(done, 'envelope_key')
                commit = _field(done, 'commit_sha') if done.get('commit_sha') is not None else ''
                if commit and not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', commit):
                    raise ValueError('invalid commit')
                result = {'generation': hashlib.sha256(('done-gen:' + key + ':' + commit).encode()).hexdigest()[:8],
                          'state': redact(_field(done, 'state')), 'summary': redact(_field(done, 'summary')),
                          'commit_sha': commit, 'finalized': done.get('finalized') is True}
            task = {'agent': name, 'name': redact(_field(spec, 'name', name)), 'engine': engine,
                    'state': redact(_field(state, 'phase', 'unknown')), 'summary': redact(_field(state, 'status_line')),
                    'status_line': redact(_field(state, 'status_line')),
                    'questions': questions, 'result': result}
            task_key = self._optional_task_key(root, fd, name, spec, control)
            if task_key is not None:
                task['task_key'] = task_key
            return task
        finally:
            os.close(fd)

    def snapshot(self):
        try:
            root = self._root()
            try:
                names = os.listdir(root)
                tasks = []
                agents = 0
                for name in sorted(names):
                    if not valid_agent(name):
                        continue
                    info = os.stat(name, dir_fd=root, follow_symlinks=False)
                    if not stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                        continue
                    agents += 1
                    if agents > 1000:
                        return {'error': 'unavailable'}
                    try:
                        task = self._task(root, name)
                        if task is not None:
                            tasks.append(task)
                    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
                        tasks.append({'agent': name, 'unavailable': True, 'questions': [], 'result': None})
                return {'tasks': tasks}
            finally:
                os.close(root)
        except (OSError, ValueError):
            return {'error': 'unavailable'}

    def _checked_task(self, agent):
        if not valid_agent(agent):
            raise ValueError('invalid agent')
        root = self._root()
        try:
            task = self._task(root, agent)
            if task is None:
                raise ValueError('not task')
            return task
        finally:
            os.close(root)

    def _run(self, argv):
        # Only owner-configured helpers; no client env, executable or argv.
        return self.runner(argv, shell=False, capture_output=True, text=True, timeout=60)

    def answer(self, agent, qid, decision, text):
        if not valid_agent(agent) or not valid_qid(qid) or decision not in ('text', 'approve', 'reject', 'recover') or not valid_text(text, decision == 'text') or (decision == 'recover' and text != ''):
            return {'error': 'invalid_or_stale'}
        try:
            task = self._checked_task(agent)
            q = next((q for q in task['questions'] if q['qid'] == qid), None)
            if q is None or q['status'] != 'open':
                return {'error': 'invalid_or_stale'}
            if decision == 'recover':
                if not q['answered']:
                    return {'error': 'invalid_or_stale'}
            elif (decision == 'text' and q['kind'] != 'info') or (decision != 'text' and q['kind'] != 'permission'):
                return {'error': 'invalid_or_stale'}
            elif not q['answered'] and decision != 'text' and decision not in q['allowed_decisions']:
                return {'error': 'invalid_or_stale'}
            args = [os.path.join(self.bin_dir, 'ai-agent-answer'), os.path.join(self.registry, agent), '--qid', qid]
            args += ['--text', text] if decision == 'text' else ['--' + decision]
            args += ['--by', 'web']
            result = self._run(args)
            if result.returncode != 0:
                return {1: {'error': 'invalid_or_stale'}, 2: {'error': 'invalid_or_stale'}, 7: {'error': 'saved_pending'}}.get(result.returncode, {'error': 'unavailable'})
            # The writer owns the durable first answer, including a racing caller.
            # A successful publication must not falsely confirm later client text.
            original = self._raw_question(agent, qid)
            if original.get('qid') != qid or original.get('kind') != q['kind'] or original.get('answered_at') is None:
                return {'error': 'unavailable'}
            if original.get('event_published_at') is None:
                return {'error': 'saved_pending'}
            matching = original.get('answer') == text if decision == 'text' else original.get('decision') == decision
            return {'status': 'already' if q['answered'] or decision == 'recover' or not matching else 'applied'}
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            return {'error': 'unavailable'}

    def verdict(self, agent, generation, decision, comment):
        if not valid_agent(agent) or type(generation) is not str or not GEN.fullmatch(generation) or decision not in ('accept', 'reject') or not valid_text(comment):
            return {'error': 'invalid_or_stale'}
        try:
            task = self._checked_task(agent)
            done = task['result']
            if done is None or done['generation'] != generation:
                return {'error': 'stale'}
            if done['state'] == 'requested' and not done['finalized']:
                return {'error': 'invalid_or_stale'}
            args = [os.path.join(self.bin_dir, 'ai-agent-run'), 'done-verdict', os.path.join(self.registry, agent), '--' + decision, '--expect-sha', generation]
            if comment:
                args += ['--comment', comment]
            result = self._run(args)
            if result.returncode == 0 and result.stdout.strip() in ('applied', 'already'):
                return {'status': result.stdout.strip()}
            return {'error': {3: 'stale', 2: 'invalid_or_stale'}.get(result.returncode, 'unavailable')}
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            return {'error': 'unavailable'}


def _receive(conn):
    data = bytearray()
    while b'\n' not in data:
        block = conn.recv(min(4096, LIMIT + 1 - len(data)))
        if not block:
            raise ValueError('incomplete request')
        data.extend(block)
        if len(data) > LIMIT:
            raise ValueError('large request')
    line, rest = bytes(data).split(b'\n', 1)
    if rest:
        raise ValueError('multiple requests')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate field')
            result[key] = value
        return result
    return json.loads(line, object_pairs_hook=pairs)


def serve_broker(socket_path, backend, allowed_uid, stop_event=None):
    parent = os.path.dirname(os.path.abspath(socket_path))
    info = os.stat(parent, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o007:
        raise ValueError('private owner directory required')
    if os.path.lexists(socket_path):
        info = os.lstat(socket_path)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('refusing socket replacement')
        # A live owner socket must not be displaced either.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(socket_path)
            except ConnectionRefusedError:
                os.unlink(socket_path)
            else:
                raise ValueError('broker already running')
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    slots = threading.BoundedSemaphore(4)
    workers = set()
    workers_lock = threading.Lock()
    fields = {'snapshot': {'op'}, 'attention_snapshot': {'op'}, 'answer': {'op', 'agent', 'qid', 'decision', 'text'},
              'verdict': {'op', 'agent', 'generation', 'decision', 'comment'}, **SESSION_FIELDS}

    def reply(conn, result):
        wire = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'
        if len(wire) > LIMIT:
            wire = b'{"error":"unavailable"}\n'
        conn.sendall(wire)

    def execute(conn, request):
        try:
            with conn:
                try:
                    op = request['op']
                    if op == 'snapshot':
                        result = backend.snapshot()
                    elif op == 'attention_snapshot':
                        result = attention_result(backend.attention_snapshot())
                    elif op == 'answer':
                        result = backend.answer(request['agent'], request['qid'], request['decision'], request['text'])
                    elif op == 'verdict':
                        result = backend.verdict(request['agent'], request['generation'], request['decision'], request['comment'])
                    elif op == 'session_projects':
                        result = backend.session_projects()
                    elif op == 'session_project_summary':
                        result = backend.session_project_summary()
                    elif op == 'session_list':
                        result = backend.session_list(request['project'], request['page'])
                    elif op == 'session_history':
                        result = backend.session_history(request['project'], request['sid'], request['cursor'])
                    elif op == 'session_models':
                        result = backend.session_models(request['project'], request['sid'])
                    elif op == 'session_send':
                        result = _forward_send(backend.session_send, request)
                    elif op == 'session_create_options':
                        result = backend.session_create_options(request['project'])
                    elif op == 'session_create':
                        result = backend.session_create(request['project'], request['operation_id'], request['context_mode'], request['provider_id'])
                    elif op == 'session_create_status':
                        result = backend.session_create_status(request['project'], request['operation_id'], request['context_mode'], request['provider_id'])
                    elif op == 'session_rename':
                        result = backend.session_rename(request['project'], request['sid'], request['operation_id'], request['title'])
                    elif op == 'session_rename_status':
                        result = backend.session_rename_status(request['project'], request['sid'], request['operation_id'])
                    else:
                        result = backend.session_send_status(request['project'], request['sid'], request['message_id'])
                    if op in ('session_create_options', 'session_create', 'session_create_status'):
                        result = configured_create_result(result, request['project'], request.get('operation_id'))
                    elif op == 'session_history':
                        result = history_result(result)
                    if op in ('session_rename', 'session_rename_status'):
                        result = rename_result(result, request['operation_id'])
                    reply(conn, result)
                except Exception:
                    try:
                        reply(conn, {'error': 'unavailable'})
                    except OSError:
                        pass
        finally:
            slots.release()
            with workers_lock:
                workers.discard(threading.current_thread())
    try:
        server.bind(socket_path)
        os.chmod(socket_path, 0o660)
        inode = os.lstat(socket_path).st_ino
        server.listen(8)
        server.settimeout(0.25)
        while stop_event is None or not stop_event.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            conn.settimeout(0.5)
            try:
                _, uid, _ = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != allowed_uid:
                    result = {'error': 'forbidden'}
                else:
                    request = _receive(conn)
                    if (type(request) is not dict or type(request.get('op')) is not str
                            or request['op'] not in fields
                            or (set(request) != fields[request['op']] and not (
                                request['op'] == 'session_send'
                                and set(request) == fields[request['op']] | {'selection'}))):
                        result = {'error': 'invalid_request' if type(request) is dict and request.get('op') in ('session_project_summary', 'attention_snapshot') else 'invalid_or_stale'}
                    elif request['op'] in SESSION_FIELDS and not _valid_session(request):
                        result = {'error': 'invalid_request'}
                    elif slots.acquire(blocking=False):
                        worker = threading.Thread(target=execute, args=(conn, request), daemon=True)
                        with workers_lock:
                            workers.add(worker)
                        worker.start()
                        continue
                    else:
                        result = {'error': 'unavailable'}
                reply(conn, result)
            except ValueError as exc:
                try:
                    reply(conn, {'error': 'invalid_request' if str(exc) == 'duplicate field' else 'unavailable'})
                except OSError:
                    pass
            except Exception:
                try:
                    conn.sendall(b'{"error":"unavailable"}\n')
                except OSError:
                    pass
            conn.close()
    finally:
        server.close()
        # Active calls are bounded: task writers retain their existing 60s
        # deadline; session operations have one overall 55s deadline.
        deadline = time.monotonic() + 61
        with workers_lock:
            active = list(workers)
        for worker in active:
            worker.join(max(0, deadline - time.monotonic()))
        if 'inode' in locals() and os.path.lexists(socket_path) and os.lstat(socket_path).st_ino == inode:
            os.unlink(socket_path)


class SocketBackend:
    def __init__(self, socket_path):
        self.socket_path = socket_path

    def _call(self, request):
        try:
            wire = json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'
            if len(wire) > LIMIT:
                return {'error': 'invalid_or_stale'}
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(65)
                conn.connect(self.socket_path)
                conn.sendall(wire)
                result = _receive(conn)
                return result if type(result) is dict else {'error': 'unavailable'}
        except (OSError, ValueError, TypeError):
            return {'error': 'unavailable'}

    def snapshot(self):
        return self._call({'op': 'snapshot'})

    def attention_snapshot(self):
        return attention_result(self._call({'op': 'attention_snapshot'}))

    def answer(self, agent, qid, decision, text):
        return self._call(dict(op='answer', agent=agent, qid=qid, decision=decision, text=text))

    def verdict(self, agent, generation, decision, comment):
        return self._call(dict(op='verdict', agent=agent, generation=generation, decision=decision, comment=comment))

    def _session(self, request):
        if not _valid_session(request):
            return {'error': 'invalid_request'}
        result = self._call(request)
        if request['op'] in ('session_create_options', 'session_create', 'session_create_status'):
            return configured_create_result(result, request['project'], request.get('operation_id'))
        if request['op'] == 'session_history':
            return history_result(result)
        return result

    def session_projects(self):
        return self._session({'op': 'session_projects'})

    def session_project_summary(self):
        return self._session({'op': 'session_project_summary'})

    def session_list(self, project, page):
        return self._session(dict(op='session_list', project=project, page=page))

    def session_history(self, project, sid, cursor):
        return self._session(dict(op='session_history', project=project, sid=sid, cursor=cursor))

    def session_models(self, project, sid):
        return self._session(dict(op='session_models', project=project, sid=sid))

    def session_send(self, project, sid, message_id, text, selection=None):
        return self._session(_send_request(project, sid, message_id, text, selection))

    def session_send_status(self, project, sid, message_id):
        return self._session(dict(op='session_send_status', project=project, sid=sid, message_id=message_id))

    def session_create_options(self, project):
        return self._session(dict(op='session_create_options', project=project))

    def session_create(self, project, operation_id, context_mode, provider_id):
        return self._session(dict(op='session_create', project=project, operation_id=operation_id,
                                  context_mode=context_mode, provider_id=provider_id))

    def session_create_status(self, project, operation_id, context_mode, provider_id):
        return self._session(dict(op='session_create_status', project=project, operation_id=operation_id,
                                  context_mode=context_mode, provider_id=provider_id))

    def session_rename(self, project, sid, operation_id, title):
        return self._session(dict(op='session_rename', project=project, sid=sid, operation_id=operation_id, title=title))

    def session_rename_status(self, project, sid, operation_id):
        return self._session(dict(op='session_rename_status', project=project, sid=sid, operation_id=operation_id))
