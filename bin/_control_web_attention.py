"""Bounded, read-only attention projection over injected owner-side snapshots.

This module performs no filesystem, transport, registry or HTTP operations.  The
trusted view supplies current binding and authorization proof; production source
adapters and deployment wiring are deliberately outside this module.
"""
import copy
import hashlib
import importlib.util
from pathlib import Path
import json
import re
import time
import uuid

# Reuse the established display redactor without constructing a backend.
_redactor_spec = importlib.util.spec_from_file_location(
    "_attention_display_broker", Path(__file__).with_name("_control_web_broker.py"))
_redactor_module = importlib.util.module_from_spec(_redactor_spec)
_redactor_spec.loader.exec_module(_redactor_module)
_redact = _redactor_module.redact

_TASK_LIMIT = 1000
_QUESTION_LIMIT = 1000
_SESSION_LIMIT = 256
_REASON_LIMIT = 512
_UNLINKED_LIMIT = 128
_BYTE_LIMIT = 128 * 1024
_METHODS = frozenset(("item/fileChange/requestApproval",
                      "item/commandExecution/requestApproval",
                      "item/permissions/requestApproval", "item/tool/requestUserInput"))
_SOURCES = ("task_registry", "activity", "native_callbacks")
_STATES = frozenset(("fresh", "stale", "unavailable", "incomplete", "unsupported"))
_HEALTH = frozenset((None, "binding_incomplete", "unavailable", "disconnected",
                     "unsupported", "limit", "invalid_source"))
_KIND_RANK = {"decision": 0, "question": 1, "completed": 2, "delivery_pending": 3}
_PRIMARY_RANK = {"decision": 0, "question": 1, "running": 2, "completed": 3,
                 "unknown": 4, "idle": 5}


class _Invalid(ValueError):
    pass


class _Expired(Exception):
    pass


def _exact(value, keys):
    if type(value) is not dict or set(value) != set(keys.split()):
        raise _Invalid()


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise _Invalid()


def _boolean(value):
    if type(value) is not bool:
        raise _Invalid()


def _match(value, pattern):
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise _Invalid()


def _text(value, limit):
    if type(value) is not str or not value or len(value) > limit:
        raise _Invalid()
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise _Invalid()
    value.encode("utf-8")


def _root(value):
    _text(value, 4096)
    if not value.startswith("/") or (value != "/" and
            (value.endswith("/") or any(p in ("", ".", "..") for p in value[1:].split("/")))):
        raise _Invalid()


def _uuid(value):
    if type(value) is not str:
        raise _Invalid()
    try:
        if str(uuid.UUID(value)) != value:
            raise _Invalid()
    except (ValueError, AttributeError):
        raise _Invalid() from None


def _hex(value, size):
    _match(value, "[0-9a-f]{%d}" % size)


def _enum(value, values):
    if type(value) is not str or value not in values:
        raise _Invalid()


def _digest(value):
    return hashlib.sha256(_encode(value)).hexdigest()


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _project(binding):
    _exact(binding, "project root registry_epoch registry_revision")
    _match(binding["project"], r"[a-zA-Z0-9_-]{1,32}")
    _root(binding["root"])
    _hex(binding["registry_epoch"], 32)
    _integer(binding["registry_revision"])


def _session(binding):
    _exact(binding, "project_binding context_id context_kind route_id route_epoch route_revision vendor sid label context_label identity_epoch identity_generation")
    _project(binding["project_binding"])
    _hex(binding["context_id"], 64)
    _enum(binding["context_kind"], ("legacy_unbound",))
    _hex(binding["route_id"], 64)
    _hex(binding["route_epoch"], 32)
    _integer(binding["route_revision"])
    _enum(binding["vendor"], ("codex",))
    _uuid(binding["sid"])
    _text(binding["label"], 120)
    _text(binding["context_label"], 120)
    _hex(binding["identity_epoch"], 32)
    _integer(binding["identity_generation"], 1)


def _native(key):
    _exact(key, "context_id route_id identity_epoch identity_generation root sid turn_id item_id method request_id question_id")
    for field in ("context_id", "route_id"):
        _hex(key[field], 64)
    _hex(key["identity_epoch"], 32)
    _integer(key["identity_generation"], 1)
    _root(key["root"])
    _uuid(key["sid"])
    for field in ("turn_id", "item_id"):
        _text(key[field], 500)
    _enum(key["method"], _METHODS)
    if type(key["request_id"]) is not int:
        _text(key["request_id"], 500)
    if key["method"] == "item/tool/requestUserInput":
        _text(key["question_id"], 500)
    elif key["question_id"] is not None:
        raise _Invalid()


def _native_matches(key, binding):
    return all(key[f] == binding[f] for f in ("context_id", "route_id", "sid", "identity_epoch", "identity_generation")) and key["root"] == binding["project_binding"]["root"]


def _session_key(binding):
    return _digest({"kind": "attention_session", "context_id": binding["context_id"],
                    "route_id": binding["route_id"], "root": binding["project_binding"]["root"], "sid": binding["sid"]})


def _task_key(record):
    return _digest({"kind": "attention_task", "registry_id": record["registry_id"],
                    "agent": record["agent"], "incarnation": record["incarnation"]})


def _question(row):
    _exact(row, "qid kind status answered pending_delivery blocking native_key")
    _uuid(row["qid"])
    _enum(row["kind"], ("info", "permission"))
    _enum(row["status"], ("open", "closed"))
    _boolean(row["answered"])
    _boolean(row["pending_delivery"])
    _enum(row["blocking"], ("current", "independent", "unknown"))
    if row["pending_delivery"] and not row["answered"]:
        raise _Invalid()
    if row["native_key"] is not None:
        _native(row["native_key"])
        if row["kind"] != "permission" or row["native_key"]["method"] != "item/fileChange/requestApproval":
            raise _Invalid()


def _task(record):
    _exact(record, "registry_id agent incarnation generation attempt_id project_binding session_binding label engine questions result")
    _hex(record["registry_id"], 64)
    _match(record["agent"], r"[a-z][a-z0-9-]{0,30}[a-z0-9]")
    _hex(record["incarnation"], 32)
    _integer(record["generation"])
    if record["attempt_id"] is not None:
        _text(record["attempt_id"], 500)
    if record["project_binding"] is not None:
        _project(record["project_binding"])
    if record["session_binding"] is not None:
        _session(record["session_binding"])
        if record["session_binding"]["project_binding"] != record["project_binding"]:
            raise _Invalid()
    _text(record["label"], 120)
    _enum(record["engine"], ("codex", "claude"))
    if type(record["questions"]) is not list or len(record["questions"]) > _QUESTION_LIMIT:
        raise _Invalid()
    seen = set()
    for row in record["questions"]:
        _question(row)
        if row["qid"] in seen:
            raise _Invalid()
        seen.add(row["qid"])
        if row["native_key"] is not None and (record["engine"] != "codex" or record["session_binding"] is None or not _native_matches(row["native_key"], record["session_binding"])):
            raise _Invalid()
    result = record["result"]
    if result is not None:
        _exact(result, "generation state finalized result_key")
        _hex(result["generation"], 8)
        _enum(result["state"], ("requested", "accepted", "integrated", "cleaned", "archived", "rejected"))
        _boolean(result["finalized"])
        _hex(result["result_key"], 64)


def _activity(record):
    _exact(record, "session_binding turn_id turn_status run_state blocked task_key task_generation attempt_id")
    _session(record["session_binding"])
    if record["turn_id"] is not None:
        _text(record["turn_id"], 500)
    _enum(record["turn_status"], ("inProgress", "completed", "interrupted", "failed", "unknown"))
    _enum(record["run_state"], ("executing", "waiting_input", "waiting_permission", "idle", "unknown"))
    _boolean(record["blocked"])
    fields = (record["task_key"], record["task_generation"], record["attempt_id"])
    if any(x is not None for x in fields):
        if any(x is None for x in fields):
            raise _Invalid()
        _hex(fields[0], 64)
        _integer(fields[1])
        _text(fields[2], 500)


def _callback(record):
    _exact(record, "session_binding native_key state blocking")
    _session(record["session_binding"])
    _native(record["native_key"])
    _enum(record["state"], ("pending", "resolved"))
    _enum(record["blocking"], ("current", "independent", "unknown"))
    if not _native_matches(record["native_key"], record["session_binding"]):
        raise _Invalid()


class AttentionOverview:
    """Compose granted compact records; all injected calls share a five-second deadline."""

    def __init__(self, task_source, *, activity_source=None, callback_source=None,
                 view, monotonic=None, wall_clock=None):
        self._sources = dict(zip(_SOURCES, (task_source, activity_source, callback_source)))
        self._view = view
        self._monotonic = monotonic or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._cache = {name: {} for name in _SOURCES}
        self._scope = None
        self._revision = 0
        self._versions = {}

    def _check(self):
        if self._monotonic() >= self._deadline:
            raise _Expired()

    def _call(self, obj, method, *args):
        self._check()
        value = getattr(obj, method)(*args, deadline=self._deadline)
        self._check()
        return value

    def _view_snapshot(self):
        if self._view is None or any(not callable(getattr(self._view, m, None)) for m in ("snapshot", "resolve_project", "authorize", "current")):
            return None
        value = self._call(self._view, "snapshot")
        _exact(value, "schema principal epoch revision registry_epoch registry_revision context_id route_id route_epoch route_revision owner_only")
        if type(value["schema"]) is not int or value["schema"] != 1:
            raise _Invalid()
        _match(value["principal"], r"[a-z][a-z0-9_-]{0,31}")
        for f in ("epoch", "registry_epoch", "route_epoch"):
            _hex(value[f], 32)
        for f in ("revision", "registry_revision", "route_revision"):
            _integer(value[f])
        for f in ("context_id", "route_id"):
            _hex(value[f], 64)
        _boolean(value["owner_only"])
        return copy.deepcopy(value) if value["owner_only"] else None

    def _binding(self, binding):
        if binding is None:
            return False
        _project(binding)
        alias = binding["project"]
        if alias not in self._resolved:
            resolved = self._call(self._view, "resolve_project", alias, self._vs)
            if resolved is not None:
                _project(resolved)
                resolved = copy.deepcopy(resolved)
                if resolved["registry_epoch"] != self._vs["registry_epoch"] or resolved["registry_revision"] != self._vs["registry_revision"]:
                    resolved = None
            allowed = resolved is not None and self._call(self._view, "authorize", resolved, self._vs) is True
            self._resolved[alias] = resolved if allowed else None
        return self._resolved[alias] == binding

    def _linked(self, binding, coverage):
        if binding is None:
            return False
        _session(binding)
        return (self._binding(binding["project_binding"]) and
                all(binding[f] == self._vs[f] for f in ("context_id", "route_id", "route_epoch", "route_revision")) and
                binding["context_id"] in coverage["context_ids"] and binding["route_id"] in coverage["route_ids"])

    def _source(self, name, adapter):
        if adapter is None:
            return {"schema": 1, "source": name, "epoch": None, "revision": 0,
                    "observed_at": None, "state": "unsupported", "complete": False,
                    "reason": "unsupported", "coverage": {"scope": "none", "registry_epoch": None,
                    "registry_revision": None, "context_ids": [], "route_ids": [],
                    "session_set_revision": None, "global_complete": False, "supported_methods": []}, "records": []}
        value = self._call(adapter, "snapshot")
        _exact(value, "schema source epoch revision observed_at state complete reason coverage records")
        if type(value["schema"]) is not int or value["schema"] != 1 or value["source"] != name:
            raise _Invalid()
        _integer(value["revision"])
        if value["epoch"] is not None:
            _hex(value["epoch"], 32)
        if value["observed_at"] is not None:
            _integer(value["observed_at"], 1)
        _enum(value["state"], _STATES)
        _boolean(value["complete"])
        if value["reason"] not in _HEALTH:
            raise _Invalid()
        if value["state"] == "fresh" and value["complete"]:
            if value["epoch"] is None or value["observed_at"] is None or value["reason"] is not None:
                raise _Invalid()
        elif value["complete"]:
            raise _Invalid()
        cov = value["coverage"]
        _exact(cov, "scope registry_epoch registry_revision context_ids route_ids session_set_revision global_complete supported_methods")
        _enum(cov["scope"], ("task_registry", "declared_sessions", "registered_project_pool", "none"))
        for f in ("registry_epoch", "session_set_revision"):
            if cov[f] is not None:
                _hex(cov[f], 32 if f == "registry_epoch" else 64)
        if cov["registry_revision"] is not None:
            _integer(cov["registry_revision"])
        for f in ("context_ids", "route_ids", "supported_methods"):
            seq = cov[f]
            if type(seq) is not list or len(seq) > 256 or any(type(x) is not str for x in seq) or seq != sorted(set(seq)):
                raise _Invalid()
            for x in seq:
                _enum(x, _METHODS) if f == "supported_methods" else _hex(x, 64)
        _boolean(cov["global_complete"])
        if name == "task_registry" and cov["scope"] not in ("task_registry", "none"):
            raise _Invalid()
        if name == "task_registry" and (cov["session_set_revision"] is not None or cov["supported_methods"]):
            raise _Invalid()
        if cov["scope"] == "declared_sessions" and cov["global_complete"]:
            raise _Invalid()
        if type(value["records"]) is not list or len(value["records"]) > _TASK_LIMIT:
            raise _Invalid()
        validator = {"task_registry": _task, "activity": _activity, "native_callbacks": _callback}[name]
        questions = 0
        prefix = []
        limited = False
        for record in value["records"]:
            self._check()
            validator(record)
            if name == "task_registry":
                questions += len(record["questions"])
                if questions > _QUESTION_LIMIT:
                    limited = True
                    break
            prefix.append(copy.deepcopy(record))
        value = {**value, "coverage": copy.deepcopy(cov), "records": prefix}
        if limited:
            self._degrade(value, "limit")
        # Epochs are separate clocks. A regressing revision within one epoch
        # cannot resolve cached reasons or supply current execution evidence.
        previous = self._versions.get(name)
        if previous and value["epoch"] == previous[0] and value["revision"] < previous[1]:
            raise _Invalid()
        return value

    @staticmethod
    def _degrade(source, reason):
        source["complete"] = False
        source["reason"] = reason
        if source["state"] == "fresh":
            source["state"] = "incomplete"

    def snapshot(self):
        self._deadline = self._monotonic() + 5.0
        try:
            self._vs = self._view_snapshot()
            if self._vs is None:
                self._cache = {name: {} for name in _SOURCES}
                return {"error": "forbidden"}
            self._resolved = {}
            scope = tuple(self._vs[f] for f in ("principal", "epoch", "registry_epoch", "context_id", "route_id", "route_epoch"))
            if scope != self._scope:
                self._cache = {name: {} for name in _SOURCES}
                self._versions = {}
                self._scope = scope
            sources = {}
            for name, adapter in self._sources.items():
                try:
                    sources[name] = self._source(name, adapter)
                except _Invalid:
                    raise
                except _Expired:
                    raise
                except Exception:
                    sources[name] = self._source(name, None)
                    sources[name].update(state="unavailable", reason="unavailable")
            result, new_cache = self._compose(sources)
            self._check()
            if self._call(self._view, "current", self._vs) is not True:
                self._cache = {name: {} for name in _SOURCES}
                return {"error": "stale"}
            self._cache = new_cache
            for name, src in sources.items():
                if src["epoch"] is not None:
                    self._versions[name] = (src["epoch"], src["revision"])
            self._revision += 1
            return result
        except _Invalid:
            return {"error": "invalid_source"}
        except Exception:
            return {"error": "unavailable"}

    def _compose(self, sources):
        tasks, callbacks, activities = {}, {}, []
        new_cache = {name: {} for name in _SOURCES}
        validators = {"task_registry": _task, "activity": _activity, "native_callbacks": _callback}
        question_count = 0
        for name in _SOURCES:
            src = sources[name]
            coverage = src["coverage"]
            records = {}
            # Every admitted record is validated and authorized before identity,
            # labels, deduplication or aggregation are constructed.
            for record in src["records"]:
                self._check()
                validators[name](record)
                pb = record["project_binding"] if name == "task_registry" else record["session_binding"]["project_binding"]
                if not self._binding(pb):
                    self._degrade(src, "binding_incomplete")
                    continue
                if coverage["registry_epoch"] != self._vs["registry_epoch"] or coverage["registry_revision"] != self._vs["registry_revision"]:
                    self._degrade(src, "binding_incomplete")
                    continue
                if name == "task_registry":
                    question_count += len(record["questions"])
                    if question_count > _QUESTION_LIMIT:
                        self._degrade(src, "limit")
                        break
                    key = _task_key(record)
                elif not self._linked(record["session_binding"], coverage):
                    self._degrade(src, "binding_incomplete")
                    continue
                elif name == "native_callbacks":
                    if record["native_key"]["method"] not in coverage["supported_methods"]:
                        self._degrade(src, "invalid_source")
                        continue
                    key = _digest(record["native_key"])
                else:
                    key = _session_key(record["session_binding"])
                if key in records and records[key]["record"] != record:
                    raise _Invalid()
                records[key] = {"record": record, "coverage": coverage, "observed_at": src["observed_at"],
                                "fresh": src["state"] in ("fresh", "incomplete")}
            retained = {} if src["state"] == "fresh" and src["complete"] else dict(self._cache[name])
            # Cached reason metadata is reauthorized against the current view;
            # stale activity is never cached as execution proof.
            for key, item in list(retained.items()):
                record = item["record"]
                pb = record["project_binding"] if name == "task_registry" else record["session_binding"]["project_binding"]
                if not self._binding(pb):
                    del retained[key]
                    continue
                item = copy.deepcopy(item)
                item["fresh"] = False
                retained[key] = item
            if src["state"] not in ("fresh", "incomplete"):
                records = {key: item for key, item in records.items() if key not in retained}
            retained.update(records)
            retained = dict(sorted(retained.items(), key=lambda pair: (not pair[1]["fresh"], pair[0]))[:_TASK_LIMIT])
            new_cache[name] = retained if name != "activity" else {}
            if name == "task_registry":
                tasks = retained
            elif name == "native_callbacks":
                callbacks = retained
            else:
                activities = list(records.values())

        sessions, unlinked, reasons = {}, {}, {}
        native_task_reasons = {}
        native_task_rows = {}

        def session_entry(binding, item):
            key = _session_key(binding)
            metadata = (item["observed_at"] or 0, binding["identity_epoch"], binding["identity_generation"])
            entry = sessions.get(key)
            if entry is not None:
                old = entry["_metadata"]
                if metadata == old and (entry["label"] != _redact(binding["label"])[:120] or entry["context_label"] != _redact(binding["context_label"])[:120]):
                    raise _Invalid()
                if metadata[0] == old[0] and metadata[1] != old[1]:
                    raise _Invalid()
                if metadata[0] > old[0] or (metadata[1] == old[1] and metadata[2] > old[2]):
                    entry.update(label=_redact(binding["label"])[:120], context_label=_redact(binding["context_label"])[:120], _metadata=metadata, _binding=binding)
                entry["_fresh"] = entry["_fresh"] or item["fresh"]
                entry["project"] = min(entry["project"], binding["project_binding"]["project"])
            else:
                entry = {"session_key": key, "project": binding["project_binding"]["project"], "sid": binding["sid"],
                         "vendor": "codex", "context_label": _redact(binding["context_label"])[:120], "label": _redact(binding["label"])[:120],
                         "activity_state": "unknown", "primary_state": "unknown", "reason_ids": [],
                         "_metadata": metadata, "_binding": binding, "_fresh": item["fresh"]}
                sessions[key] = entry
            return key

        def add_reason(reason, blocking="independent", native_key=None):
            reason["_blocking"] = blocking
            reason["_native"] = native_key
            reasons[reason["reason_id"]] = reason

        for task_key, item in tasks.items():
            record = item["record"]
            sb = record["session_binding"]
            linked = record["engine"] == "codex" and self._linked(sb, item["coverage"])
            if record["engine"] == "codex" and sb is not None and not linked:
                self._degrade(sources["task_registry"], "binding_incomplete")
            skey = session_entry(sb, item) if linked else None
            pending = []
            for row in record["questions"]:
                if linked and row["native_key"] is not None:
                    native_task_rows[_digest(row["native_key"])] = (task_key, row, skey, record, item)
                kind = "delivery_pending" if row["answered"] and row["pending_delivery"] else ("decision" if row["kind"] == "permission" else "question") if row["status"] == "open" and not row["answered"] else None
                if kind is None:
                    continue
                rid = _digest({"kind": "attention_reason", "task_key": task_key, "qid": row["qid"]})
                target = {"kind": "session", "project": record["project_binding"]["project"], "sid": sb["sid"]} if linked else {"kind": "task", "agent": record["agent"], "task_key": task_key, "qid": row["qid"], "result_generation": None}
                native_key = row["native_key"] if linked else None
                reason = {"reason_id": rid, "session_key": skey, "task_key": None if linked else task_key,
                          "kind": kind, "source": "task_registry", "state": "pending" if item["fresh"] else "stale", "target": target}
                add_reason(reason, row["blocking"] if kind in ("question", "decision") else "independent", native_key)
                pending.append(rid)
                if native_key is not None:
                    native_task_reasons[_digest(native_key)] = rid
            result = record["result"]
            if result is not None and result["state"] == "requested" and result["finalized"]:
                rid = _digest({"kind": "attention_result_reason", "task_key": task_key, "result_key": result["result_key"]})
                target = {"kind": "session", "project": record["project_binding"]["project"], "sid": sb["sid"]} if linked else {"kind": "task", "agent": record["agent"], "task_key": task_key, "qid": None, "result_generation": result["generation"]}
                add_reason({"reason_id": rid, "session_key": skey, "task_key": None if linked else task_key, "kind": "completed", "source": "task_registry", "state": "pending" if item["fresh"] else "stale", "target": target})
                pending.append(rid)
            if not linked and pending:
                unlinked[task_key] = {"task_key": task_key, "project": record["project_binding"]["project"], "label": _redact(record["label"])[:120], "engine": record["engine"], "reason_ids": [], "_fresh": item["fresh"]}

        for nkey, item in callbacks.items():
            record = item["record"]
            skey = session_entry(record["session_binding"], item)
            correlated = native_task_reasons.get(nkey)
            if correlated:
                reason = reasons[correlated]
                # A saved TASK answer and still-pending native receipt are an
                # ambiguity, not a new decision or a resolved question.
                expected = "resolved" if reason["kind"] == "delivery_pending" else "pending"
                if record["state"] != expected:
                    reason["state"] = "unknown"
                    reason["_blocking"] = "unknown"
                continue
            if record["state"] == "resolved":
                continue
            saved = native_task_rows.get(nkey)
            if saved and saved[1]["answered"]:
                task_key, row, task_session, task_record, task_item = saved
                rid = _digest({"kind": "attention_reason", "task_key": task_key, "qid": row["qid"]})
                add_reason({"reason_id": rid, "session_key": task_session, "task_key": None,
                            "kind": "delivery_pending", "source": "task_registry", "state": "unknown",
                            "target": {"kind": "session", "project": task_record["project_binding"]["project"], "sid": task_record["session_binding"]["sid"]}}, "unknown", row["native_key"])
                native_task_reasons[nkey] = rid
                continue
            nk = record["native_key"]
            rid = _digest({"kind": "attention_native_reason", "native_key": nk})
            add_reason({"reason_id": rid, "session_key": skey, "task_key": None,
                        "kind": "question" if nk["method"] == "item/tool/requestUserInput" else "decision",
                        "source": "native_callbacks", "state": "pending" if item["fresh"] else "stale",
                        "target": {"kind": "session", "project": record["session_binding"]["project_binding"]["project"], "sid": record["session_binding"]["sid"]}}, record["blocking"], nk)

        for item in activities:
            record = item["record"]
            key = session_entry(record["session_binding"], item)
            state = "unknown"
            if item["fresh"]:
                if record["run_state"] == "executing" and (record["turn_status"] != "inProgress" or record["turn_id"] is None or record["blocked"]):
                    self._degrade(sources["activity"], "invalid_source")
                    continue
                if record["task_key"] is not None:
                    task = tasks.get(record["task_key"])
                    if not task or not task["fresh"] or task["record"]["generation"] != record["task_generation"] or task["record"]["attempt_id"] != record["attempt_id"] or task["record"]["engine"] != "codex" or task["record"]["session_binding"] != record["session_binding"]:
                        self._degrade(sources["activity"], "invalid_source")
                        continue
                state = {"executing": "running", "waiting_input": "waiting", "waiting_permission": "waiting", "idle": "idle", "unknown": "unknown"}[record["run_state"]]
                if record["blocked"]:
                    state = "waiting"
            sessions[key]["activity_state"] = state

        for rid, reason in reasons.items():
            target = sessions[reason["session_key"]] if reason["session_key"] else unlinked[reason["task_key"]]
            target["reason_ids"].append(rid)
        for entry in sessions.values():
            rs = [reasons[rid] for rid in entry["reason_ids"]]
            if any(r["kind"] in ("decision", "question") and (r["_blocking"] != "independent" or r["state"] != "pending") for r in rs):
                entry["activity_state"] = "waiting" if any(r["state"] == "pending" for r in rs) else "stale"
            kinds = {r["kind"] for r in rs}
            entry["primary_state"] = "decision" if "decision" in kinds else "question" if "question" in kinds else "running" if entry["activity_state"] == "running" else "completed" if "completed" in kinds else "idle" if entry["activity_state"] == "idle" else "unknown"

        complete = all(s["state"] == "fresh" and s["complete"] for s in sources.values())
        ac, cb = sources["activity"]["coverage"], sources["native_callbacks"]["coverage"]
        complete = complete and ac["global_complete"] and cb["global_complete"] and ac["scope"] == cb["scope"] == "registered_project_pool" and ac["session_set_revision"] is not None and ac["session_set_revision"] == cb["session_set_revision"]
        result = {"schema": 1, "epoch": self._vs["epoch"], "revision": self._revision + 1,
                  "observed_at": int(self._wall_clock()), "complete": bool(complete), "truncated": False,
                  "sources": {n: {f: s[f] for f in ("state", "complete", "observed_at", "reason")} for n, s in sources.items()},
                  "pool": dict.fromkeys(("known_sessions", "running", "decision", "question", "completed"), 0),
                  "sessions": [], "reasons": [], "unlinked_tasks": []}
        _integer(result["observed_at"], 1)

        def clean(entry):
            return {k: v for k, v in entry.items() if not k.startswith("_")}

        entries = [("sessions", entry) for entry in sessions.values()] + [("unlinked_tasks", entry) for entry in unlinked.values()]
        def order(pair):
            entry = pair[1]
            rank = _PRIMARY_RANK[entry["primary_state"]] if pair[0] == "sessions" else min((_KIND_RANK[reasons[r]["kind"]] for r in entry["reason_ids"]), default=4)
            return (not entry["_fresh"], rank, entry["project"], entry.get("session_key", entry.get("task_key")))
        for group, entry in sorted(entries, key=order):
            self._check()
            rids = sorted(entry["reason_ids"], key=lambda rid: (_KIND_RANK[reasons[rid]["kind"]], rid))
            entry["reason_ids"] = rids
            cap = _SESSION_LIMIT if group == "sessions" else _UNLINKED_LIMIT
            if len(result[group]) >= cap or len(result["reasons"]) + len(rids) > _REASON_LIMIT:
                result["truncated"] = True
                break
            oldpool = dict(result["pool"])
            result[group].append(clean(entry))
            result["reasons"].extend(clean(reasons[r]) for r in rids)
            if group == "sessions":
                result["pool"]["known_sessions"] += 1
                result["pool"]["running"] += entry["activity_state"] == "running"
                kinds = {reasons[r]["kind"] for r in rids}
                for kind in ("decision", "question", "completed"):
                    result["pool"][kind] += kind in kinds
            if len(_encode(result)) > _BYTE_LIMIT:
                result[group].pop()
                if rids:
                    del result["reasons"][-len(rids):]
                result["pool"] = oldpool
                result["truncated"] = True
                break
        if result["truncated"]:
            result["complete"] = False
        result["reasons"].sort(key=lambda r: (_KIND_RANK[r["kind"]], r["reason_id"]))
        # Keep only records supporting exported reasons. This bounds retention by
        # the export caps as well as the compact source/question caps, rather
        # than accumulating hidden questions across incomplete polls.
        emitted = {r["reason_id"] for r in result["reasons"]}
        bounded_tasks, cached_questions = {}, 0
        for key, item in new_cache["task_registry"].items():
            row = item["record"]
            ids = {_digest({"kind": "attention_reason", "task_key": key, "qid": q["qid"]}) for q in row["questions"]}
            if row["result"] is not None:
                ids.add(_digest({"kind": "attention_result_reason", "task_key": key, "result_key": row["result"]["result_key"]}))
            if ids & emitted and cached_questions + len(row["questions"]) <= _QUESTION_LIMIT:
                bounded_tasks[key] = item
                cached_questions += len(row["questions"])
        new_cache["task_registry"] = bounded_tasks
        new_cache["native_callbacks"] = {key: item for key, item in new_cache["native_callbacks"].items()
            if item["record"]["state"] == "pending" and
            (_digest({"kind": "attention_native_reason", "native_key": item["record"]["native_key"]}) in emitted
             or native_task_reasons.get(key) in emitted)}
        return result, new_cache
