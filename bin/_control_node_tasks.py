"""Private durable task ledger. No transport, executors, or credentials.

The private service-UID directory is the filesystem trust boundary; this does
not isolate against another malicious process running as the same UID.
"""
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

from _control_web_devbus import decode_event

_TERMINAL = ('completed', 'failed', 'needs_attention')
_FIELDS = {'message_id', 'task_id', 'correlation_id', 'source', 'target',
           'kind', 'created_at', 'payload'}


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


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
        try:
            absolute = os.path.abspath(os.fspath(path))
            parts = absolute.split(os.sep)
            self._dir = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
            for part in parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=self._dir)
                os.close(self._dir)
                self._dir = child
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
            self._db = sqlite3.connect(absolute, timeout=5, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            after = os.stat(leaf, dir_fd=self._dir, follow_symlinks=False)
            if not _private(after) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise ValueError()
            version = self._db.execute('PRAGMA user_version').fetchone()[0]
            tables = {r[0] for r in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not new and (version != 1 or tables != {'tasks', 'events', 'diagnostics'}):
                raise ValueError()
            if not new:
                # Reject incompatible schemas before changing journal or other settings.
                self._db.execute('''SELECT task_id,node_id,prompt,created_at,updated_at,
                    delivery,execution,coverage,result,terminal_kind,terminal_digest,
                    message_id,wire,wire_sha256,retry_at,failures,first_sequence,last_sequence
                    FROM tasks LIMIT 0''')
                self._db.execute('SELECT event_id,task_id,digest,kind,created_at,conflicted FROM events LIMIT 0')
                self._db.execute('SELECT name,count FROM diagnostics LIMIT 0')
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
                self._db.executescript('''
                    BEGIN IMMEDIATE;
                    CREATE TABLE tasks(
                      task_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, prompt TEXT NOT NULL,
                      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                      delivery TEXT NOT NULL, execution TEXT NOT NULL, coverage TEXT NOT NULL,
                      result TEXT, terminal_kind TEXT, terminal_digest TEXT,
                      message_id TEXT NOT NULL UNIQUE, wire BLOB NOT NULL, wire_sha256 TEXT NOT NULL,
                      retry_at REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
                      first_sequence INTEGER, last_sequence INTEGER);
                    CREATE TABLE events(
                      event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                      digest TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL,
                      conflicted INTEGER NOT NULL DEFAULT 0);
                    CREATE INDEX events_task ON events(task_id);
                    CREATE TABLE diagnostics(name TEXT PRIMARY KEY, count INTEGER NOT NULL);
                    INSERT INTO diagnostics VALUES('invalid',0),('ignored',0),('conflict',0),('capacity',0);
                    PRAGMA user_version=1;
                    COMMIT;
                ''')
        except (OSError, sqlite3.Error, ValueError, TypeError):
            self.close()
            raise ValueError('unsafe or unavailable task store') from None

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
            except sqlite3.Error:
                try:
                    self._db.rollback()
                except sqlite3.Error:
                    pass
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

    @staticmethod
    def _dto(row):
        return dict(schema=1, task_id=row['task_id'], node_id=row['node_id'],
                    prompt=row['prompt'], created_at=row['created_at'], updated_at=row['updated_at'],
                    delivery=row['delivery'], execution=row['execution'], coverage=row['coverage'],
                    result=json.loads(row['result']) if row['result'] is not None else None,
                    quality='unreviewed', usage=None)

    def _counter(self, name):
        self._db.execute('UPDATE diagnostics SET count=min(count+1,2147483647) WHERE name=?', (name,))

    def _attention(self, task):
        self._db.execute("UPDATE tasks SET execution='needs_attention', coverage='partial', updated_at=? WHERE task_id=?",
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
                return self._dto(row) if (row['node_id'], row['prompt']) == (node_id, prompt) else {'error': 'conflict'}
            total, unfinished = self._db.execute("SELECT count(*), sum(execution NOT IN ('completed','failed','needs_attention')) FROM tasks").fetchone()
            if total >= 1000 or (unfinished or 0) >= 32:
                return {'error': 'capacity'}
            now, mid = self._time(), str(uuid.uuid4())
            wire = _json(dict(message_id=mid, task_id=request_id, correlation_id=request_id,
                              source='control-web', target='codex-ai-dev-1', kind='submit',
                              created_at=now, payload={'prompt': prompt})).encode('utf-8')
            self._db.execute('''INSERT INTO tasks(task_id,node_id,prompt,created_at,updated_at,
                delivery,execution,coverage,message_id,wire,wire_sha256)
                VALUES(?,?,?,?,?,'pending','waiting','complete',?,?,?)''',
                (request_id, node_id, prompt, now, now, mid, wire, hashlib.sha256(wire).hexdigest()))
            return self._dto(self._row(request_id))
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

    def pending(self, limit=1):
        if type(limit) is not int or not 1 <= limit <= 50:
            return {'error': 'invalid_request'}
        return self._run(lambda: [dict(r) for r in self._db.execute('''
            SELECT task_id,message_id,wire,wire_sha256 FROM tasks
            WHERE delivery IN ('pending','unknown') AND execution='waiting'
              AND coverage='complete' AND retry_at<=? ORDER BY created_at,task_id LIMIT ?''',
            (self._clock(), limit))])

    def publication_started(self, task_id):
        if not _uuid(task_id):
            return {'error': 'invalid_request'}
        def operation():
            row = self._row(task_id)
            if row is None:
                return {'error': 'not_found'}
            if (row['delivery'] == 'published' or row['execution'] != 'waiting'
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
            if row['delivery'] != 'published' and row['execution'] == 'waiting':
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
        source = candidate.get('source') if type(candidate) is dict else None
        if type(source) is not str:
            raise ValueError()
        obj = decode_event(raw, 'devbus.events.' + source, 1, require_created_at=True)
        if set(obj) != _FIELDS:
            raise ValueError()
        kind, payload = obj['kind'], obj['payload']
        if kind in ('accepted', 'running'):
            valid = payload == {}
        elif kind == 'completed':
            valid = (set(payload) in ({'text', 'executor'}, {'text', 'executor', 'output_truncated'})
                     and type(payload['text']) is str and payload['executor'] == 'codex'
                     and ('output_truncated' not in payload or type(payload['output_truncated']) is bool))
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
            task = obj['task_id']
            row = self._row(task)
            if (not row or obj['source'] != 'codex-ai-dev-1' or obj['target'] != 'control-web'
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
            count = self._db.execute('SELECT count(*) FROM events WHERE task_id=?', (task,)).fetchone()[0]
            if count >= 256:
                self._attention(task)
                self._counter('capacity')
                return {'outcome': 'applied', 'task_id': task}
            kind, old = obj['kind'], row['execution']
            self._db.execute('INSERT INTO events(event_id,task_id,digest,kind,created_at) VALUES(?,?,?,?,?)',
                             (obj['message_id'], task, digest, kind, obj['created_at']))
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

    def mark_gap(self):
        def operation():
            cursor = self._db.execute("""UPDATE tasks SET coverage='partial',updated_at=?
                WHERE execution NOT IN ('completed','failed','needs_attention') AND coverage='complete'""",
                (self._time(),))
            return {'affected': cursor.rowcount}
        return self._run(operation)
