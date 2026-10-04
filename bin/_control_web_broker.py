"""Narrow owner-side task interface. Never returns raw registry documents."""
import hashlib
import json
import os
import re
import socket
import stat
import struct
import subprocess
import uuid

LIMIT = 128 * 1024
FIELD_LIMIT = 16000
NAME = re.compile(r'[a-z][a-z0-9-]{0,30}[a-z0-9]\Z')
GEN = re.compile(r'[0-9a-f]{8}\Z')


# Intentional per-binary copy of claude-agent-run's complete export policy.
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


class RegistryBackend:
    def __init__(self, registry, bin_dir, runner=None):
        self.registry = os.path.abspath(registry)
        self.bin_dir = os.path.abspath(bin_dir)
        self.runner = runner or subprocess.run

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
            return {'agent': name, 'name': redact(_field(spec, 'name', name)), 'engine': engine,
                    'state': redact(_field(state, 'phase', 'unknown')), 'summary': redact(_field(state, 'status_line')),
                    'questions': questions, 'result': result}
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
            args = [os.path.join(self.bin_dir, 'claude-agent-answer'), os.path.join(self.registry, agent), '--qid', qid]
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
            args = [os.path.join(self.bin_dir, 'claude-agent-run'), 'done-verdict', os.path.join(self.registry, agent), '--' + decision, '--expect-sha', generation]
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
    return json.loads(line)


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
            with conn:
                conn.settimeout(0.5)
                result = {'error': 'unavailable'}
                try:
                    _, uid, _ = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if uid != allowed_uid:
                        result = {'error': 'forbidden'}
                    else:
                        request = _receive(conn)
                        fields = {'snapshot': {'op'}, 'answer': {'op', 'agent', 'qid', 'decision', 'text'}, 'verdict': {'op', 'agent', 'generation', 'decision', 'comment'}}
                        if type(request) is not dict or request.get('op') not in fields or set(request) != fields[request['op']]:
                            result = {'error': 'invalid_or_stale'}
                        elif request['op'] == 'snapshot':
                            result = backend.snapshot()
                        elif request['op'] == 'answer':
                            result = backend.answer(request['agent'], request['qid'], request['decision'], request['text'])
                        else:
                            result = backend.verdict(request['agent'], request['generation'], request['decision'], request['comment'])
                    wire = json.dumps(result).encode() + b'\n'
                    if len(wire) > LIMIT:
                        wire = b'{"error":"unavailable"}\n'
                    conn.sendall(wire)
                except Exception:
                    try:
                        conn.sendall(b'{"error":"unavailable"}\n')
                    except OSError:
                        pass
    finally:
        server.close()
        if 'inode' in locals() and os.path.lexists(socket_path) and os.lstat(socket_path).st_ino == inode:
            os.unlink(socket_path)


class SocketBackend:
    def __init__(self, socket_path):
        self.socket_path = socket_path

    def _call(self, request):
        try:
            wire = json.dumps(request).encode() + b'\n'
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

    def answer(self, agent, qid, decision, text):
        return self._call(dict(op='answer', agent=agent, qid=qid, decision=decision, text=text))

    def verdict(self, agent, generation, decision, comment):
        return self._call(dict(op='verdict', agent=agent, generation=generation, decision=decision, comment=comment))
