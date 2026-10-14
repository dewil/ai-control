"""Private durable task ledger. No transport, executors, or credentials.

The private service-UID directory is the filesystem trust boundary; this does
not isolate against another malicious process running as the same UID.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import threading
import time
import uuid

from _control_web_devbus import decode_event, _pairs
from _control_node_protocol import (canonical_v2, decode_event_v2, validate_submit_v2,
                                    validate_profile_snapshot_v2, validate_result_v2,
                                    validate_binding_v2)

SCHEMA_VERSION = 3

_store_hook = ContextVar('control_node_tasks_store_hook', default=None)


@contextmanager
def _test_dependencies(*, store_hook=None):
    token = _store_hook.set(store_hook)
    try:
        yield
    finally:
        _store_hook.reset(token)


def _notify_store(label, value):
    hook = _store_hook.get()
    if hook is not None:
        hook(label, value)


def _migration_step(connection, ordinal, operation):
    connection.execute(operation)
    _notify_store('migration_step', dict(connection=connection, ordinal=ordinal,
                                         operation=operation))

_TERMINAL = ('completed', 'failed', 'needs_attention')
_FIELDS = {'message_id', 'task_id', 'correlation_id', 'source', 'target',
           'kind', 'created_at', 'payload'}

_SCHEMA = {
    'tasks': """CREATE TABLE tasks(
        task_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, prompt TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        delivery TEXT NOT NULL, execution TEXT NOT NULL, coverage TEXT NOT NULL,
        result TEXT, terminal_kind TEXT, terminal_digest TEXT,
        message_id TEXT NOT NULL UNIQUE, wire BLOB NOT NULL, wire_sha256 TEXT NOT NULL,
        retry_at REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
        first_sequence INTEGER, last_sequence INTEGER)""",
    'events': """CREATE TABLE events(
        event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
        digest TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL,
        conflicted INTEGER NOT NULL DEFAULT 0)""",
    'events_task': 'CREATE INDEX events_task ON events(task_id)',
    'metadata': 'CREATE TABLE metadata(singleton INTEGER PRIMARY KEY CHECK(singleton=1), fence TEXT)',
    'diagnostics': 'CREATE TABLE diagnostics(name TEXT PRIMARY KEY, count INTEGER NOT NULL)',
}
_SCHEMA2 = dict(_SCHEMA)
_SCHEMA['task_v2'] = '''CREATE TABLE task_v2(
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id), request TEXT NOT NULL,
    profile TEXT NOT NULL, binding TEXT NOT NULL,
    session_verification TEXT NOT NULL, observed_session_uuid TEXT,
    native_model TEXT, effort_state TEXT NOT NULL)'''


def _schema_sql(sql):
    # The schema is fixed: compare definitions, including keys/FK/index, before
    # modifying an existing file. Formatting changes alone remain compatible.
    return ''.join(sql.split()).lower()


def _ancestor(info, path):
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()):
        return False
    if not info.st_mode & 0o022:
        return True
    return info.st_uid == 0 and path in ('/tmp', '/var/tmp') and bool(info.st_mode & stat.S_ISVTX)


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def _valid_result(value):
    return (type(value) is dict
            and set(value) in ({'text', 'executor'}, {'text', 'executor', 'output_truncated'})
            and type(value['text']) is str and value['executor'] == 'codex'
            and ('output_truncated' not in value or type(value['output_truncated']) is bool)
            and len(_json(value).encode('utf-8')) <= 60000)


def _uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _private(info, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    return (kind(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
            and (directory or info.st_nlink == 1))


class NodeTaskStore:
    def __init__(self, path, clock=time.time):
        self._clock = clock
        self._lock = threading.RLock()
        self._db = None
        self._fd = None
        self._dir = None
        self._commits = 0
        ready = False
        try:
            absolute = os.path.abspath(os.fspath(path))
            parts = absolute.split(os.sep)
            self._dir = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
            ancestor_path = '/'
            if not _ancestor(os.fstat(self._dir), ancestor_path):
                raise ValueError()
            for part in parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=self._dir)
                os.close(self._dir)
                self._dir = child
                ancestor_path = os.path.join(ancestor_path, part)
                if not _ancestor(os.fstat(self._dir), ancestor_path):
                    raise ValueError()
            if not _private(os.fstat(self._dir), True):
                raise ValueError()
            leaf = parts[-1]
            try:
                self._fd = os.open(leaf, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                   dir_fd=self._dir)
                new = False
            except FileNotFoundError:
                self._fd = os.open(leaf, os.O_RDWR | os.O_NOFOLLOW | os.O_CREAT | os.O_EXCL,
                                   0o600, dir_fd=self._dir)
                new = True
                os.fsync(self._dir)
            before = os.fstat(self._fd)
            if not _private(before):
                raise ValueError()
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for suffix in ('-wal', '-shm', '-journal'):
                try:
                    info = os.stat(leaf + suffix, dir_fd=self._dir, follow_symlinks=False)
                    if not _private(info):
                        raise ValueError()
                except FileNotFoundError:
                    pass
            self._db = sqlite3.connect(absolute, timeout=1, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            after = os.stat(leaf, dir_fd=self._dir, follow_symlinks=False)
            if not _private(after) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise ValueError()
            version = self._db.execute('PRAGMA user_version').fetchone()[0]
            tables = {r[0] for r in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not new and (version not in (2, SCHEMA_VERSION) or
                    tables != set(name for name in (_SCHEMA2 if version == 2 else _SCHEMA)
                                  if name != 'events_task')):
                raise ValueError()
            if not new:
                actual = {name: _schema_sql(sql) for name, sql in self._db.execute(
                    'SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL')}
                expected = _SCHEMA2 if version == 2 else _SCHEMA
                if actual != {name: _schema_sql(sql) for name, sql in expected.items()}:
                    raise ValueError()
                metadata = self._db.execute('SELECT singleton,fence FROM metadata').fetchall()
                if (len(metadata) != 1 or metadata[0]['singleton'] != 1
                        or metadata[0]['fence'] not in (None, 'retention_gap', 'invalid_event', 'id_conflict')):
                    raise ValueError()
            self._db.execute('PRAGMA journal_mode=WAL')
            self._db.execute('PRAGMA synchronous=FULL')
            self._db.execute('PRAGMA foreign_keys=ON')
            self._db.execute('PRAGMA wal_autocheckpoint=256')
            pagesize = self._db.execute('PRAGMA page_size').fetchone()[0]
            maxpages = 256 * 1024 * 1024 // pagesize
            if self._db.execute('PRAGMA page_count').fetchone()[0] > maxpages:
                raise ValueError()
            self._db.execute('PRAGMA max_page_count=' + str(maxpages))
            if new:
                self._db.execute('BEGIN IMMEDIATE')
                for ordinal, sql in enumerate(_SCHEMA.values()):
                    _migration_step(self._db, ordinal, sql)
                self._db.execute("INSERT INTO diagnostics VALUES('invalid',0),('ignored',0),('conflict',0),('capacity',0)")
                self._db.execute('INSERT INTO metadata VALUES(1,NULL)')
                _migration_step(self._db, len(_SCHEMA),
                                'PRAGMA user_version=' + str(SCHEMA_VERSION))
                _notify_store('before_migration_commit', self._db)
                self._db.commit()
            elif version == 2:
                # Only the exact accepted schema2 is eligible. Existing rows and
                # v1 wire bytes remain untouched; unknown schemas are not repaired.
                self._db.execute('BEGIN IMMEDIATE')
                _migration_step(self._db, 0, _SCHEMA['task_v2'])
                _migration_step(self._db, 1,
                                'PRAGMA user_version=' + str(SCHEMA_VERSION))
                _notify_store('before_migration_commit', self._db)
                self._db.commit()
            _notify_store('store_ready', self._db)
            ready = True
        except (OSError, sqlite3.Error, ValueError, TypeError):
            raise ValueError('unsafe or unavailable task store') from None
        finally:
            if not ready:
                self.close()

    def close(self):
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
            for name in ('_fd', '_dir'):
                fd = getattr(self, name, None)
                if fd is not None:
                    os.close(fd)
                    setattr(self, name, None)

    def _time(self):
        return datetime.fromtimestamp(self._clock(), timezone.utc).isoformat().replace('+00:00', 'Z')

    def _run(self, operation):
        with self._lock:
            if self._db is None:
                return {'error': 'storage'}
            try:
                self._db.execute('BEGIN IMMEDIATE')
                result = operation()
                self._db.commit()
            except (sqlite3.Error, ValueError, TypeError, RecursionError, OverflowError) as error:
                # Stored-data decoding failures are storage failures too; leave
                # no open transaction to poison an independent healthy read.
                try:
                    self._db.rollback()
                except sqlite3.Error:
                    pass
                if isinstance(error, sqlite3.Error):
                    _notify_store('sqlite_error', error)
                return {'error': 'storage'}
            self._commits += 1
            if self._commits % 64 == 0:
                # No long-lived readers in this owner; autocheckpoint also bounds WAL.
                try:
                    self._db.execute('PRAGMA wal_checkpoint(PASSIVE)')
                except sqlite3.Error:
                    pass  # Committed transaction remains authoritative.
            return result

    def _row(self, task):
        return self._db.execute('SELECT * FROM tasks WHERE task_id=?', (task,)).fetchone()

    def _dto(self, row):
        v2 = self._db.execute('SELECT * FROM task_v2 WHERE task_id=?',
                              (row['task_id'],)).fetchone()
        result = None
        if row['result'] is not None:
            raw = row['result']
            if type(raw) is not str or len(raw.encode('utf-8')) > 60000:
                raise ValueError()
            result = json.loads(raw, object_pairs_hook=_pairs,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if v2:
                validate_result_v2(result)
            elif not _valid_result(result):
                raise ValueError()
        dto = dict(schema=1, task_id=row['task_id'], node_id=row['node_id'],
                    prompt=row['prompt'], created_at=row['created_at'], updated_at=row['updated_at'],
                    delivery=row['delivery'], execution=row['execution'], coverage=row['coverage'],
                    result=result,
                    quality='unreviewed', usage=None)
        if v2:
            binding = json.loads(v2['binding'], object_pairs_hook=_pairs)
            validate_binding_v2(binding)
            dto.update(schema=2, execution_profile_id=binding['execution_profile_id'],
                       attempt_id=binding['attempt_id'], binding=binding,
                       session_verification=v2['session_verification'],
                       observed_session_uuid=v2['observed_session_uuid'],
                       native_model=v2['native_model'], effort_state=v2['effort_state'])
        return dto

    def _counter(self, name):
        self._db.execute('UPDATE diagnostics SET count=min(count+1,2147483647) WHERE name=?', (name,))

    def _attention(self, task):
        self._db.execute("""UPDATE tasks SET execution='needs_attention', coverage='partial', updated_at=?
            WHERE task_id=? AND (execution!='needs_attention' OR coverage!='partial')""",
                         (self._time(), task))

    def submit(self, request_id, node_id, prompt):
        try:
            valid = (_uuid(request_id) and node_id == 'alp' and type(prompt) is str
                     and '\0' not in prompt and 1 <= len(prompt.encode('utf-8')) <= 32768)
        except UnicodeError:
            valid = False
        if not valid:
            return {'error': 'invalid_request'}

        def operation():
            row = self._row(request_id)
            if row:
                if self._db.execute('SELECT 1 FROM task_v2 WHERE task_id=?', (request_id,)).fetchone():
                    return {'error': 'conflict'}
                return self._dto(row) if (row['node_id'], row['prompt']) == (node_id, prompt) else {'error': 'conflict'}
            total, unfinished = self._db.execute("SELECT count(*), sum(execution NOT IN ('completed','failed','needs_attention')) FROM tasks").fetchone()
            if total >= 1000 or (unfinished or 0) >= 32:
                return {'error': 'capacity'}
            now, mid = self._time(), str(uuid.uuid4())
            wire = _json(dict(message_id=mid, task_id=request_id, correlation_id=request_id,
                              source='control-web', target='codex-ai-dev-1', kind='submit',
                              created_at=now, payload={'prompt': prompt})).encode('utf-8')
            if len(wire) > 126 * 1024:
                return {'error': 'invalid_request'}
            self._db.execute('''INSERT INTO tasks(task_id,node_id,prompt,created_at,updated_at,
                delivery,execution,coverage,message_id,wire,wire_sha256)
                VALUES(?,?,?,?,?,'pending','waiting','complete',?,?,?)''',
                (request_id, node_id, prompt, now, now, mid, wire, hashlib.sha256(wire).hexdigest()))
            return self._dto(self._row(request_id))
        return self._run(operation)

    def submit_v2(self, request, profile_snapshot):
        try:
            validate_submit_v2(request)
            request_json = canonical_v2(request).decode('utf-8')
            request = json.loads(request_json)
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            return {'error': 'invalid_request'}

        def operation():
            task = request['request_id']
            existing = self._row(task)
            if existing:
                record = self._db.execute('SELECT request FROM task_v2 WHERE task_id=?', (task,)).fetchone()
                return (self._dto(existing) if record and record['request'] == request_json
                        else {'error': 'conflict'})
            try:
                validate_profile_snapshot_v2(profile_snapshot)
                profile_json = canonical_v2(profile_snapshot).decode('utf-8')
                profile = json.loads(profile_json)
            except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
                return {'error': 'invalid_request'}
            if profile['account_attestation']['status'] != 'verified':
                return {'error': 'profile_unverified'}
            total, unfinished = self._db.execute("SELECT count(*), sum(execution NOT IN ('completed','failed','needs_attention')) FROM tasks").fetchone()
            if total >= 1000 or (unfinished or 0) >= 32:
                return {'error': 'capacity'}
            binding = {key: profile[key] for key in (
                'execution_profile_id', 'profile_revision', 'provider', 'requested_model',
                'requested_effort', 'account_ref', 'workspace_ref', 'base_sha')}
            binding.update(task_id=task, node_id=request['node_id'],
                           attempt_id=str(uuid.uuid4()), worktree_ref=str(uuid.uuid4()),
                           requested_session_uuid=str(uuid.uuid4()))
            now = datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(
                timespec='microseconds').replace('+00:00', 'Z')
            mid = str(uuid.uuid4())
            wire = canonical_v2(dict(message_id=mid, task_id=task, correlation_id=task,
                source='control-web', target=profile['executor_target'], kind='submit',
                created_at=now, payload=dict(schema=2, operation='submit', request=request, binding=binding)))
            if len(wire) > 129024:
                return {'error': 'invalid_request'}
            self._db.execute('''INSERT INTO tasks(task_id,node_id,prompt,created_at,updated_at,
                delivery,execution,coverage,message_id,wire,wire_sha256)
                VALUES(?,?,?,?,?,'pending','waiting_slot','complete',?,?,?)''',
                (task, request['node_id'], request['prompt'], now, now, mid, wire,
                 hashlib.sha256(wire).hexdigest()))
            self._db.execute('''INSERT INTO task_v2(task_id,request,profile,binding,
                session_verification,effort_state) VALUES(?,?,?,?,'pending','requested_unverified')''',
                (task, request_json, profile_json, canonical_v2(binding).decode('utf-8')))
            return self._dto(self._row(task))
        return self._run(operation)

    def get(self, task_id):
        if not _uuid(task_id):
            return {'error': 'invalid_request'}
        def operation():
            row = self._row(task_id)
            return self._dto(row) if row else {'error': 'not_found'}
        return self._run(operation)

    def list(self, limit=50):
        if type(limit) is not int or not 1 <= limit <= 50:
            return {'error': 'invalid_request'}
        return self._run(lambda: [self._dto(r) for r in self._db.execute(
            'SELECT * FROM tasks ORDER BY created_at,task_id LIMIT ?', (limit,))])

    def recent(self, limit=50, *, schema=None):
        if (type(limit) is not int or not 1 <= limit <= 50 or
                schema is not None and (type(schema) is not int or schema not in (1, 2))):
            return {'error': 'invalid_request'}
        condition = ('' if schema is None else
                     ' WHERE ' + ('' if schema == 2 else 'NOT ') +
                     'EXISTS(SELECT 1 FROM task_v2 WHERE task_v2.task_id=tasks.task_id)')
        return self._run(lambda: [self._dto(r) for r in self._db.execute(
            'SELECT * FROM tasks' + condition + ' ORDER BY created_at DESC,task_id DESC LIMIT ?', (limit,))])

    def count(self, *, schema=None):
        if schema is not None and (type(schema) is not int or schema not in (1, 2)):
            return {'error': 'invalid_request'}
        condition = ('' if schema is None else
                     ' WHERE ' + ('' if schema == 2 else 'NOT ') +
                     'EXISTS(SELECT 1 FROM task_v2 WHERE task_v2.task_id=tasks.task_id)')
        return self._run(lambda: {'total': self._db.execute('SELECT count(*) FROM tasks' + condition).fetchone()[0]})

    def runtime_state(self):
        return self._run(lambda: {'fence': self._db.execute('SELECT fence FROM metadata WHERE singleton=1').fetchone()[0]})

    def pending(self, limit=1):
        if type(limit) is not int or not 1 <= limit <= 50:
            return {'error': 'invalid_request'}
        return self._run(lambda: [dict(r) for r in self._db.execute('''
            SELECT task_id,message_id,wire,wire_sha256 FROM tasks
            WHERE delivery IN ('pending','unknown') AND execution IN ('waiting','waiting_slot')
              AND coverage='complete' AND retry_at<=?
              AND NOT EXISTS(SELECT 1 FROM events WHERE events.task_id=tasks.task_id AND kind='queued')
              AND (SELECT fence FROM metadata WHERE singleton=1) IS NULL ORDER BY created_at,task_id LIMIT ?''',
            (self._clock(), limit))])

    def publication_started(self, task_id):
        if not _uuid(task_id):
            return {'error': 'invalid_request'}
        def operation():
            row = self._row(task_id)
            if row is None:
                return {'error': 'not_found'}
            if (self._db.execute('SELECT fence FROM metadata WHERE singleton=1').fetchone()[0] is not None
                    or row['delivery'] == 'published' or row['execution'] not in ('waiting','waiting_slot')
                    or row['coverage'] != 'complete' or row['retry_at'] > self._clock()):
                return {'publish': False}
            self._db.execute("UPDATE tasks SET delivery='unknown',updated_at=? WHERE task_id=?",
                             (self._time(), task_id))
            return {'publish': True}
        return self._run(operation)

    def publication(self, task_id, message_id, wire_sha256, sequence):
        if not _uuid(task_id) or type(sequence) is not int or not 1 <= sequence <= 9223372036854775807:
            return {'error': 'invalid_request'}
        def operation():
            row = self._row(task_id)
            if row is None:
                return {'error': 'not_found'}
            if message_id != row['message_id'] or wire_sha256 != row['wire_sha256']:
                return {'error': 'conflict'}
            self._db.execute("""UPDATE tasks SET delivery='published',updated_at=?,
                first_sequence=coalesce(first_sequence,?),last_sequence=? WHERE task_id=?""",
                (self._time(), sequence, sequence, task_id))
            return self._dto(self._row(task_id))
        return self._run(operation)

    def publish_failed(self, task_id):
        if not _uuid(task_id):
            return {'error': 'invalid_request'}
        def operation():
            row = self._row(task_id)
            if row is None:
                return {'error': 'not_found'}
            if row['delivery'] != 'published' and row['execution'] in ('waiting','waiting_slot'):
                failures = min(row['failures'] + 1, 31)
                self._db.execute("""UPDATE tasks SET delivery='unknown',failures=?,retry_at=?,updated_at=?
                    WHERE task_id=?""", (failures, self._clock() + min(2 ** (failures-1), 60), self._time(), task_id))
            return self._dto(self._row(task_id))
        return self._run(operation)

    @staticmethod
    def _event(raw):
        if type(raw) is not bytes or len(raw) > 126 * 1024:
            raise ValueError()
        # Reuse the bus's strict duplicate-key, nonfinite, ID and timestamp checks.
        candidate = json.loads(raw.decode('utf-8'))
        if (type(candidate) is dict and type(candidate.get('payload')) is dict
                and candidate['payload'].get('schema') == 2):
            obj = decode_event_v2(raw)
            return obj, hashlib.sha256(canonical_v2(obj['payload'])).hexdigest()
        source = candidate.get('source') if type(candidate) is dict else None
        if type(source) is not str:
            raise ValueError()
        obj = decode_event(raw, 'devbus.events.' + source, 1, require_created_at=True)
        if set(obj) != _FIELDS:
            raise ValueError()
        kind, payload = obj['kind'], obj['payload']
        if kind in ('heartbeat', 'registration'):
            # Shared-subject metadata have no task authority; the strict v1
            # envelope/dict payload was checked above. Do not interpret it.
            return obj, None
        if kind in ('accepted', 'running'):
            valid = payload == {}
        elif kind == 'completed':
            valid = _valid_result(payload)
        elif kind == 'failed':
            valid = (set(payload) in ({'reason'}, {'reason', 'exit_code'})
                     and type(payload.get('reason')) is str
                     and payload['reason'] in {'timeout', 'output_limit', 'executor_exit', 'local_executor_error'}
                     and (payload.get('exit_code') is None or type(payload['exit_code']) is int)
                     and (payload['reason'] != 'local_executor_error' or 'exit_code' not in payload))
        elif kind == 'needs_attention':
            valid = payload == {'reason': 'interrupted; outcome unknown; automatic retry disabled'}
        else:
            valid = False
        serialized = _json(payload).encode('utf-8')
        if not valid or len(serialized) > 60000:
            raise ValueError()
        return obj, hashlib.sha256(serialized).hexdigest()

    def ingest(self, raw):
        try:
            obj, payload_digest = self._event(raw)
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            def invalid():
                self._counter('invalid')
                return {'outcome': 'invalid', 'task_id': None}
            return self._run(invalid)
        digest = hashlib.sha256(raw).hexdigest()
        def operation():
            if obj['kind'] in ('heartbeat', 'registration'):
                self._counter('ignored')
                return {'outcome': 'ignored', 'task_id': None}
            task = obj['task_id']
            row = self._row(task)
            record = self._db.execute('SELECT * FROM task_v2 WHERE task_id=?', (task,)).fetchone()
            v2 = type(obj['payload'].get('schema')) is int and obj['payload']['schema'] == 2
            source = 'claude-alp-worktree-1' if record else 'codex-ai-dev-1'
            if (not row or bool(record) != v2 or obj['source'] != source or obj['target'] != 'control-web'
                    or obj['correlation_id'] != task):
                self._counter('ignored')
                return {'outcome': 'ignored', 'task_id': None}
            previous = self._db.execute('SELECT * FROM events WHERE event_id=?', (obj['message_id'],)).fetchone()
            if previous:
                if previous['digest'] == digest:
                    return {'outcome': 'duplicate', 'task_id': task}
                self._attention(previous['task_id'])
                self._db.execute('UPDATE events SET conflicted=1 WHERE event_id=?', (obj['message_id'],))
                self._counter('conflict')
                return {'outcome': 'conflict', 'task_id': previous['task_id']}
            if v2:
                payload = obj['payload']
                binding = json.loads(record['binding'], object_pairs_hook=_pairs)
                mismatch = canonical_v2(payload['binding']).decode('utf-8') != record['binding']
                if payload['session_verification'] == 'verified':
                    mismatch |= (payload['observed_session_uuid'] != binding['requested_session_uuid']
                                 or payload['native_model'] != binding['requested_model'])
                if mismatch:
                    self._attention(task)
                    self._counter('conflict')
                    return {'outcome': 'conflict', 'task_id': task}
            count = self._db.execute('SELECT count(*) FROM events WHERE task_id=?', (task,)).fetchone()[0]
            if count >= 256:
                self._attention(task)
                self._counter('capacity')
                return {'outcome': 'applied', 'task_id': task}
            kind, old = obj['kind'], row['execution']
            self._db.execute('INSERT INTO events(event_id,task_id,digest,kind,created_at) VALUES(?,?,?,?,?)',
                             (obj['message_id'], task, digest, kind, obj['created_at']))
            if v2:
                return self._apply_v2(row, record, obj, payload_digest)
            if old == 'needs_attention' and kind == 'completed' and row['result'] is None:
                # Keep the first late result for review; uncertainty is sticky.
                self._db.execute('''UPDATE tasks SET result=?,terminal_kind=?,terminal_digest=?,
                    updated_at=? WHERE task_id=?''',
                    (_json(obj['payload']), kind, payload_digest, self._time(), task))
            if old != 'needs_attention':
                if kind == 'needs_attention':
                    self._attention(task)
                elif kind in ('completed', 'failed'):
                    if old in _TERMINAL:
                        if kind != row['terminal_kind'] or payload_digest != row['terminal_digest']:
                            self._attention(task)
                    else:
                        result = _json(obj['payload']) if kind == 'completed' else None
                        self._db.execute('''UPDATE tasks SET execution=?,result=?,terminal_kind=?,
                            terminal_digest=?,updated_at=? WHERE task_id=?''',
                            (kind, result, kind, payload_digest, self._time(), task))
                elif old not in _TERMINAL:
                    order = {'waiting': 0, 'accepted': 1, 'running': 2}
                    if order[kind] > order[old]:
                        self._db.execute('UPDATE tasks SET execution=?,updated_at=? WHERE task_id=?',
                                         (kind, self._time(), task))
            return {'outcome': 'applied', 'task_id': task}
        return self._run(operation)

    def _apply_v2(self, row, record, obj, payload_digest):
        task, kind, payload = obj['task_id'], obj['kind'], obj['payload']
        old = row['execution']
        result = payload['result']
        if old in _TERMINAL:
            if (row['terminal_kind'] is not None and
                    (kind != row['terminal_kind'] or payload_digest != row['terminal_digest']) and
                    payload['sequence'] == 3):
                self._attention(task)
            return {'outcome': 'applied', 'task_id': task}
        if payload['sequence'] == 3:
            self._db.execute('''UPDATE tasks SET execution=?,result=?,terminal_kind=?,
                terminal_digest=?,updated_at=? WHERE task_id=?''',
                (kind, _json(result) if result is not None else None, kind,
                 payload_digest, self._time(), task))
            if kind == 'needs_attention' or payload['session_verification'] != 'verified':
                self._attention(task)
        elif kind in ('accepted', 'running'):
            order = {'waiting_slot': 0, 'accepted': 1, 'running': 2}
            if order[kind] > order[old]:
                self._db.execute('UPDATE tasks SET execution=?,updated_at=? WHERE task_id=?',
                                 (kind, self._time(), task))
        # A replayed queued/accepted observation cannot erase later native proof.
        if (record['session_verification'] == 'pending' or payload['sequence'] == 3):
            self._db.execute('''UPDATE task_v2 SET session_verification=?,observed_session_uuid=?,
                native_model=? WHERE task_id=?''',
                (payload['session_verification'], payload['observed_session_uuid'],
                 payload['native_model'], task))
        return {'outcome': 'applied', 'task_id': task}

    def mark_gap(self, reason='retention_gap'):
        if type(reason) is not str or reason not in {'retention_gap', 'invalid_event', 'id_conflict'}:
            return {'error': 'invalid_request'}
        def operation():
            self._db.execute('UPDATE metadata SET fence=coalesce(fence,?) WHERE singleton=1', (reason,))
            cursor = self._db.execute("""UPDATE tasks SET coverage='partial',updated_at=?
                WHERE execution NOT IN ('completed','failed','needs_attention') AND coverage='complete'""",
                (self._time(),))
            return {'affected': cursor.rowcount}
        return self._run(operation)
