"""_agent_question_io: общий код создания вопроса под questions/.lock -
единственный вопрос-creation путь для claude-agent-ask (kind=info, V2.3
§2) и claude-agent-permit (kind=permission, V2.4 §2). Singleton (не больше
одного status=open) и fail-closed на битом состоянии (аудит V2.3 major 7)
реализованы здесь ровно один раз.

durable_write/durable_json/fsync_dir - тот же протокол tmp+fsync+rename+
fsync(dir), что в claude-agent-run.
"""

import fcntl
import json
import os
import uuid
import math
import stat
import time
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_write(path, data, *, deadline=None, clock=time.monotonic):
    remaining(deadline, clock)
    d = os.path.dirname(os.path.abspath(path)) or "."
    tmp = os.path.join(d, ".%s.tmp.%d" % (os.path.basename(path), os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        mv = memoryview(data.encode() if isinstance(data, str) else data)
        while mv:
            mv = mv[os.write(fd, mv):]
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        remaining(deadline, clock)
        os.replace(tmp, path)
        fsync_dir(d)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def durable_json(path, doc, *, deadline=None, clock=time.monotonic):
    durable_write(path, json.dumps(doc, ensure_ascii=False) + "\n", deadline=deadline, clock=clock)


def envelope_in_inflight(agent_dir, envelope_key):
    """True - envelope_key реально лежит в inbox/inflight/ этого агента
    сейчас (V2.3 major 6 / V2.4 major 6: произвольный/устаревший ключ не
    должен создавать вопрос, не привязанный ни к одному живому прогону, но
    безусловно морозящий очередь). Общая проверка для claude-agent-ask и
    claude-agent-permit."""
    # containment ДО вывода "да" (тот же протокол, что qid_safe_path в
    # V2.3): без него ключ вида "../../tmp/x" проходил бы проверку при
    # существовании любого чужого .json - то есть создавал бы ровно тот
    # осиротевший вопрос, ради которого проверка и заводилась. Форму ключа
    # тут НЕ фиксируем: она задана продюсером конвертов, а не этим слоем.
    if not envelope_key:
        return False
    inflight = os.path.realpath(os.path.join(agent_dir, "inbox", "inflight"))
    path = os.path.realpath(os.path.join(inflight, envelope_key + ".json"))
    if os.path.dirname(path) != inflight:
        return False
    return os.path.isfile(path)


class QuestionError(Exception):
    """Отказ создания вопроса: message + exit code (по умолчанию 2 - как
    остальные валидационные отказы CLI в этом репо)."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def create_question(agent_dir, envelope_key, kind, question, options=None,
                    context=None, extra=None):
    """Singleton-создание вопроса под questions/.lock (V2.3 §1-3, §3.1;
    аудит major 7 - fail-closed на битом файле). Возвращает qid.
    QuestionError - открытый вопрос уже есть, либо questions/ повреждена."""
    qdir = os.path.join(agent_dir, "questions")
    os.makedirs(qdir, mode=0o700, exist_ok=True)
    lk = os.open(os.path.join(qdir, ".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lk, fcntl.LOCK_EX)
        return create_question_locked(agent_dir, envelope_key, kind, question, options, context, extra)
    finally:
        fcntl.flock(lk, fcntl.LOCK_UN)
        os.close(lk)


def remaining(deadline, clock=time.monotonic, cap=30):
    if deadline is None:
        return cap
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("invalid deadline")
    budget = deadline - clock()
    if budget <= 0:
        raise ValueError("expired deadline")
    return min(cap, budget)

def strict_json(path, *, deadline=None, clock=time.monotonic):
    remaining(deadline, clock)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600
                or st.st_size > 1024 * 1024):
            raise ValueError("unsafe evidence")
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversize evidence")
        def pairs(items):
            doc = {}
            for key, value in items:
                if key in doc:
                    raise ValueError("duplicate key")
                doc[key] = value
            return doc
        def invalid_constant(value):
            raise ValueError("invalid JSON constant")
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
        current = os.lstat(path)
        if (current.st_dev, current.st_ino) != (st.st_dev, st.st_ino):
            raise ValueError("replaced evidence")
        if not isinstance(result, dict):
            raise ValueError("invalid evidence")
        remaining(deadline, clock)
        return result
    finally:
        os.close(fd)

def validate_done(doc):
    if (doc.get('workspace') != 'worktree' or doc.get('state') != 'requested'
            or not isinstance(doc.get('envelope_key'), str) or not doc['envelope_key']
            or not isinstance(doc.get('summary'), str)
            or type(doc.get('finalized')) is not bool
            or not isinstance(doc.get('requested_at'), str) or not doc['requested_at']):
        raise ValueError("invalid done evidence")

def create_question_locked(agent_dir, envelope_key, kind, question, options=None,
                           context=None, extra=None, *, strict=False, deadline=None, clock=time.monotonic):
    """Trusted caller only: questions/.lock and operation fencing must be held."""
    remaining(deadline, clock)
    qdir = os.path.join(agent_dir, "questions")
    for fn in os.listdir(qdir):
        if not fn.endswith(".json"):
            continue
        try:
            d = (strict_json(os.path.join(qdir, fn), deadline=deadline, clock=clock)
                         if strict else json.load(open(os.path.join(qdir, fn))))
            if strict:
                if (not isinstance(d, dict) or str(uuid.UUID(fn[:-5])) != fn[:-5]
                        or d.get("qid") != fn[:-5] or not isinstance(d.get("envelope_key"), str)
                        or not d["envelope_key"] or d.get("kind") not in ("info", "permission")
                        or d.get("status") not in ("open", "closed")):
                    raise ValueError("invalid question")
        except (OSError, ValueError):
            raise QuestionError(
                "состояние вопросов повреждено (нечитаемый файл %s) - "
                "разберись вручную перед новым вопросом" % fn)
        if isinstance(d, dict) and d.get("status") == "open":
            raise QuestionError(
                "уже есть открытый вопрос, объедини формулировки")
    qid = str(uuid.uuid4())
    asked_at = now_iso()
    doc = {
        "qid": qid, "envelope_key": envelope_key, "asked_at": asked_at,
        "kind": kind, "question": question, "options": options,
        "context": context, "status": "open", "answer": None,
        "decision": None, "answered_at": None, "answered_by": None,
        "closed_by_envelope": None,
        "reminder": {"step": 0, "next_push_at": asked_at,
                    "snoozed_until": None}}
    if extra:
        doc.update(extra)
    remaining(deadline, clock)
    durable_json(os.path.join(qdir, qid + ".json"), doc, deadline=deadline, clock=clock)
    remaining(deadline, clock)
    return qid
