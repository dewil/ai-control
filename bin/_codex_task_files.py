"""Bounded, guarded readonly task worktree tools (no shell or runtime effects)."""
from contextlib import ExitStack
import json
import math
import os
import re
import stat
import time

from _codex_task_bridge import TaskBinding


class FileToolError(Exception):
    pass


class _SkipFile(Exception):
    pass


def _require(value):
    if not value:
        raise FileToolError('Task file operation rejected')


def _identity(info):
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_uid,
            None if stat.S_ISDIR(info.st_mode) else info.st_nlink)


def _content(info):
    return _identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _forbidden(name):
    lower = name.lower()
    return (lower in {'.git', '.netrc', '.npmrc', '.pypirc', 'auth.json',
                     'credentials.json', 'cookies.json', 'id_rsa', 'id_ed25519',
                     'id_dsa', 'id_ecdsa', '.ssh', '.aws', '.azure', '.kube',
                     'browser-sessions'} or
            lower.endswith(('.pem', '.key', '.p12', '.pfx')) or
            ((lower == '.env' or lower.startswith('.env.')) and
             name not in {'.env.example', '.env.sample', '.env.template'}))


def _path(value, *, root=True):
    _require(isinstance(value, str) and 0 < len(value.encode('utf-8')) <= 4096)
    _require('\\' not in value and all(not (ord(c) < 32 or 127 <= ord(c) <= 159)
                                         for c in value))
    if value == '.' and root:
        return []
    parts = value.split('/')
    _require(all(p and p not in ('.', '..') and not _forbidden(p) for p in parts))
    return parts


def _clip(text, size):
    return text.encode('utf-8')[:size].decode('utf-8', errors='ignore')


class CodexTaskFiles:
    _FILE_BYTES = 1048576
    _OUTPUT_BYTES = 65536

    def __init__(self, binding, *, guard, clock=time.monotonic):
        try:
            _require(isinstance(binding, TaskBinding) and callable(guard) and callable(clock))
            _require(isinstance(binding.task_incarnation, str) and
                     re.fullmatch('[0-9a-f]{32}', binding.task_incarnation))
            for field in ('event_key', 'thread_id', 'turn_id'):
                value = getattr(binding, field)
                _require(isinstance(value, str) and value.strip() and
                         len(value.encode('utf-8')) <= 256 and
                         all(not (ord(c) < 32 or 127 <= ord(c) <= 159) for c in value))
            agent = binding.agent_dir
            _require(isinstance(agent, str) and os.path.isabs(agent) and
                     os.path.normpath(agent) == agent and os.path.realpath(agent) == agent)
            a, w = os.lstat(agent), os.lstat(os.path.join(agent, 'work'))
            _require(all(stat.S_ISDIR(i.st_mode) and i.st_uid == os.getuid() for i in (a, w)))
            self.binding, self.guard, self.clock = binding, guard, clock
            self._agent, self._work = _identity(a), _identity(w)
        except Exception:
            raise FileToolError('Invalid task file configuration') from None

    def _deadline(self, deadline):
        _require(type(deadline) in (int, float) and math.isfinite(deadline))
        _require(self.clock() < deadline)

    @staticmethod
    def _args(tool, args):
        _require(type(args) is dict)
        allowed = {'task_read': {'path', 'start_line', 'limit'},
                   'task_search': {'path', 'query', 'limit'},
                   'task_list': {'path', 'limit'}}
        _require(isinstance(tool, str) and tool in allowed and set(args) <= allowed[tool])
        _require(tool != 'task_read' or 'path' in args)
        _path(args.get('path', '.'), root=tool != 'task_read')
        maximum, default = (100, 50) if tool == 'task_search' else (500, 200)
        limit = args.get('limit', default)
        _require(type(limit) is int and 1 <= limit <= maximum)
        start = args.get('start_line', 1)
        _require(type(start) is int and start >= 1)
        if tool == 'task_search':
            query = args.get('query')
            _require(isinstance(query, str) and 0 < len(query.encode('utf-8')) <= 512 and
                     not any(c in query for c in '\x00\r\n'))
        return dict(args, path=args.get('path', '.'), limit=limit, start_line=start)

    def handle(self, tool, arguments, *, deadline):
        try:
            args = self._args(tool, arguments)
            self._deadline(deadline)
            completed = False
            with self.guard(self.binding, deadline=deadline) as guarded:
                _require(guarded is True)
                with ExitStack() as stack:
                    pins = []
                    contents = []
                    def open_at(parent, name, directory=False, expected=None, owned=True, temporary=False):
                        self._deadline(deadline)
                        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                        if directory:
                            flags |= os.O_DIRECTORY
                        fd = os.open(name, flags, dir_fd=parent)
                        if not temporary:
                            stack.callback(os.close, fd)
                        try:
                            info = os.fstat(fd)
                        except Exception:
                            if temporary:
                                os.close(fd)
                            raise
                        try:
                            _require(not owned or info.st_uid == os.getuid())
                            _require(stat.S_ISDIR(info.st_mode) if directory else
                                     stat.S_ISDIR(info.st_mode) or
                                     (stat.S_ISREG(info.st_mode) and info.st_nlink == 1))
                            if expected is not None:
                                _require(_identity(info) == expected)
                        except Exception:
                            if temporary:
                                os.close(fd)
                            raise
                        if not temporary:
                            pins.append((parent, name, fd, _identity(info)))
                        return fd
                    # Pin every absolute ancestor using openat, never following links.
                    fd = open_at(None, '/', True, owned=False)
                    components = self.binding.agent_dir.split('/')[1:]
                    for index, part in enumerate(components):
                        fd = open_at(fd, part, True,
                                     self._agent if index == len(components) - 1 else None,
                                     owned=index == len(components) - 1)
                    root = open_at(fd, 'work', True, self._work)
                    target = root
                    parts = _path(args['path'], root=tool != 'task_read')
                    for index, part in enumerate(parts):
                        target = open_at(target, part, index < len(parts) - 1)
                    info = os.fstat(target)
                    if tool == 'task_read':
                        _require(stat.S_ISREG(info.st_mode))
                        text = self._read(target, deadline, contents=contents)
                        lines = text.splitlines(keepends=True)
                        selected = ''.join(lines[args['start_line'] - 1:
                                                 args['start_line'] - 1 + args['limit']])
                        clipped = _clip(selected, self._OUTPUT_BYTES)
                        result = dict(path=args['path'], start_line=args['start_line'],
                                      end_line=args['start_line'] - 1 + len(clipped.splitlines(keepends=True)),
                                      total_lines=len(lines), text=clipped,
                                      truncated=len(clipped) < len(''.join(lines[args['start_line'] - 1:])))
                    else:
                        result = self._enumerate(tool, args, target, info, open_at, deadline, contents)
                    for content_fd, snapshot in contents:
                        self._deadline(deadline)
                        _require(_content(os.fstat(content_fd)) == snapshot)
                    for parent, name, pinned, identity in pins:
                        self._deadline(deadline)
                        _require(_identity(os.fstat(pinned)) == identity and
                                 _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == identity)
                    self._deadline(deadline)
                    completed = True
            _require(completed)
            self._deadline(deadline)
            return result
        except Exception:
            raise FileToolError('Task file operation rejected') from None

    def _read(self, fd, deadline, *, budget=None, contents):
        self._deadline(deadline)
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                 before.st_uid == os.getuid() and before.st_size <= self._FILE_BYTES)
        if budget is not None:
            _require(before.st_size <= budget)
        chunks, size = [], 0
        while True:
            self._deadline(deadline)
            data = os.read(fd, min(65536, self._FILE_BYTES + 1 - size))
            self._deadline(deadline)
            if not data:
                break
            size += len(data)
            _require(size <= self._FILE_BYTES)
            chunks.append(data)
        _require(_content(os.fstat(fd)) == _content(before))
        contents.append((fd, _content(before)))
        try:
            text = b''.join(chunks).decode('utf-8')
        except UnicodeError:
            raise _SkipFile from None
        if '\x00' in text:
            raise _SkipFile
        return text

    def _enumerate(self, tool, args, target, info, open_at, deadline, contents):
        listing = tool == 'task_list'
        _require(not listing or stat.S_ISDIR(info.st_mode))
        key = 'entries' if listing else 'matches'
        result = {key: [], 'truncated': False}
        visited, read_bytes = 0, 0
        candidates, identities, content_snapshots = [], {}, {}

        def append(item):
            if len(result[key]) >= args['limit']:
                result['truncated'] = True
                return False
            result[key].append(item)
            if len(json.dumps(result, allow_nan=False).encode('utf-8')) > self._OUTPUT_BYTES:
                result[key].pop()
                result['truncated'] = True
                return False
            return True

        def search(fd, path, explicit=False, relative=None):
            nonlocal read_bytes
            self._deadline(deadline)
            size = os.fstat(fd).st_size
            if size > self._FILE_BYTES:
                _require(not explicit)
                return True
            if read_bytes + size > 16 * self._FILE_BYTES:
                result['truncated'] = True
                return False
            read_bytes += size
            snapshots = contents if explicit else []
            try:
                text = self._read(fd, deadline,
                                  budget=16 * self._FILE_BYTES - read_bytes + size,
                                  contents=snapshots)
            except (UnicodeError, _SkipFile):
                self._deadline(deadline)
                _require(not explicit)
                return True
            finally:
                if not explicit and snapshots:
                    content_snapshots[relative] = snapshots[0][1]
            for number, line in enumerate(text.splitlines(), 1):
                self._deadline(deadline)
                if args['query'] in line:
                    if not append(dict(path=path, line=number, text=_clip(line, 512))):
                        return False
            return True

        def walk(fd, relative_prefix, depth):
            nonlocal visited
            self._deadline(deadline)
            # One name lookahead detects cutoff; only the bounded prefix is classified.
            names = []
            with os.scandir(fd) as entries:
                for entry in entries:
                    self._deadline(deadline)
                    names.append(entry.name)
                    if len(names) > 512 - visited:
                        result['truncated'] = True
                        break
            for name in sorted(names)[:512 - visited]:
                if visited >= 512:
                    result['truncated'] = True
                    break
                self._deadline(deadline)
                visited += 1
                relative = name if not relative_prefix else relative_prefix + '/' + name
                path = relative if args['path'] == '.' else args['path'] + '/' + relative
                try:
                    _path(path)
                except (FileToolError, UnicodeError):
                    continue
                child_info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                isdir = stat.S_ISDIR(child_info.st_mode)
                if (not (isdir or stat.S_ISREG(child_info.st_mode)) or
                        child_info.st_uid != os.getuid() or
                        (not isdir and child_info.st_nlink != 1)):
                    continue
                identity = _identity(child_info)
                try:
                    child = open_at(fd, name, isdir, identity, temporary=True)
                except PermissionError:
                    # Known unreadable children may be skipped, but a concurrent
                    # replacement or any resource/IO error refuses the operation.
                    self._deadline(deadline)
                    _require(_identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) == identity)
                    continue
                try:
                    identities[relative] = identity
                    candidates.append((path, isdir, relative))
                    if isdir:
                        if depth >= 8:
                            result['truncated'] = True
                        else:
                            walk(child, relative, depth + 1)
                    self._deadline(deadline)
                    _require(_identity(os.fstat(child)) == identity and
                             _identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) == identity)
                finally:
                    os.close(child)

        def verify_link(parent, name, fd, identity):
            self._deadline(deadline)
            _require(_identity(os.fstat(fd)) == identity and
                     _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == identity)

        def reopen(relative, stack):
            # Snapshots are small; descriptors live only along this one path.
            fd, prefix = target, ''
            parts = relative.split('/')
            for index, part in enumerate(parts):
                prefix = part if not prefix else prefix + '/' + part
                parent = fd
                fd = open_at(parent, part, index < len(parts) - 1,
                             identities[prefix], temporary=True)
                stack.callback(os.close, fd)
                stack.callback(verify_link, parent, part, fd, identities[prefix])
            return fd

        if stat.S_ISDIR(info.st_mode):
            walk(target, '', 1)
            for path, isdir, relative in sorted(candidates):
                self._deadline(deadline)
                if listing:
                    if not append(dict(path=path, type='directory' if isdir else 'file')):
                        break
                elif not isdir:
                    with ExitStack() as stack:
                        child = reopen(relative, stack)
                        if not search(child, path, relative=relative):
                            break
            # Reopen from the pinned start and verify every encountered identity
            # and read content snapshot before releasing the task fence.
            for relative in identities:
                self._deadline(deadline)
                with ExitStack() as stack:
                    child = reopen(relative, stack)
                    if relative in content_snapshots:
                        _require(_content(os.fstat(child)) == content_snapshots[relative])
        else:
            search(target, args['path'], explicit=True)
        # A true flag is one byte shorter than false, so final encoding remains bounded.
        self._deadline(deadline)
        return result

    @staticmethod
    def dynamic_tools():
        descriptors = []
        for name, maximum in [('task_read', 500), ('task_search', 100), ('task_list', 500)]:
            properties = {'path': {'type': 'string', 'minLength': 1, 'maxLength': 4096},
                          'limit': {'type': 'integer', 'minimum': 1, 'maximum': maximum}}
            required = []
            if name == 'task_read':
                properties['start_line'] = {'type': 'integer', 'minimum': 1}
                required = ['path']
            elif name == 'task_search':
                properties['query'] = {'type': 'string', 'minLength': 1, 'maxLength': 512}
                required = ['query']
            descriptors.append(dict(type='function', name=name, deferLoading=False,
                                    description={'task_read': 'Read bounded worktree text.',
                                                 'task_search': 'Search literal worktree text.',
                                                 'task_list': 'List bounded worktree entries.'}[name],
                                    inputSchema=dict(type='object', properties=properties,
                                                     required=required, additionalProperties=False)))
        return descriptors
