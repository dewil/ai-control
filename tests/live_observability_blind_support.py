"""Synthetic public-contract fixtures; no runtime source inspection.

Frozen UX-only support. All passwords, OTPs, IDs and feed bytes are
invented local test data. Importing the real create_app is allowed; its source is
never read. LIVE/BUS/DEPLOY remain waiting; this fixture contains only existing UX seams.
"""
import base64
from copy import deepcopy
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SID = "11111111-1111-4111-8111-111111111111"
OTHER = "44444444-4444-4444-8444-444444444444"
PASSWORD = "synthetic-live-observability-password"
SECRET = "JBSWY3DPEHPK3PXP"
TITLE = "UX synthetic session with a long readable title"


def private_json(path, data):
    temporary = path.with_name(path.name + ".next")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(temporary, path)


def totp(now=None):
    digest = hmac.new(base64.b32decode(SECRET), struct.pack(">Q", int(now or time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return str((struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000).zfill(6)


def settings(model="gpt-6.1-sol", effort="high", age_ms=0):
    return {"schema": 1, "scope": "configured_or_persisted", "source": "thread_read",
            "model": model, "effort": effort, "age_ms": age_ms,
            "expires_in_ms": 15000 - age_ms}


def catalog(expires_in_ms=60000):
    # Frozen UX-NEUTRAL-01 exact public catalog response.
    return {"schema": 1, "vendor": "codex", "context_kind": "legacy_unbound",
            "selection_support": "available", "catalog_id": "a" * 64,
            "expires_in_ms": expires_in_ms,
            "rows": [{"id": "model-alpha", "label": "Model Alpha", "efforts": ["high", "medium"]}]}


def history(snapshot=True, dated=False):
    items = [{"id": "item-" + str(i), "role": "assistant",
              "text": "Fixture readable message " + str(i), "truncated": False}
             for i in range(24)]
    if dated:
        for item in items:
            item["timestamp"] = 1770000000
            item["time_precision"] = "item"
    value = {"turns": [{"id": "fixture-turn", "status": "completed", "items": items}],
             "next_cursor": None, "truncated": False, "recent_sends": []}
    if snapshot:
        value["session_settings"] = settings()
    return value


def project(name="demo", count=12, activity=None, state="fresh", now=None):
    now = int(now or time.time())
    return {"name": name, "session_count": count, "last_activity": activity,
            "summary_state": state, "as_of": now if state in ("fresh", "stale") else None}


def chips(now=None):
    now = int(now or time.time())
    return [project(name, count, now - 300, now=now)
            for name, count in (("zero", 0), ("loww", 3), ("high", 12), ("stle", 20))]


def neutral():
    return {"projects": [project(activity=int(time.time()) - 300)],
            "history": history(), "catalog": catalog()}


class Backend:
    """Existing established public backend contract, controlled by atomic files."""
    def __init__(self, evidence):
        self.evidence = evidence
        self.lock = threading.Lock()

    def state(self):
        return json.loads((self.evidence / "control.json").read_text(encoding="utf-8"))

    def record(self, method, **data):
        with self.lock, (self.evidence / "calls.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"method": method, "monotonic": time.monotonic(), **data}) + "\n")

    def snapshot(self): return {"tasks": []}
    def answer(self, *args): return {"error": "unavailable"}
    def verdict(self, *args): return {"error": "unavailable"}

    def session_projects(self):
        return {"projects": [{"name": row["name"], **({"unavailable": True}
                if row["summary_state"] == "unavailable" else {})} for row in self.state()["projects"]]}

    def session_project_summary(self):
        self.record("summary")
        return {"projects": self.state()["projects"]}

    def session_list(self, project, page):
        self.record("list", project=project, page=page)
        return {"rows": [{"sid": SID, "title": TITLE, "status": "idle"},
                         {"sid": OTHER, "title": "Other UX synthetic session", "status": "idle"}], "has_more": False}

    def session_history(self, project, sid, cursor):
        self.record("history", project=project, sid=sid, cursor=cursor)
        state = self.state()
        time.sleep(state.get("history_delay", 0))
        return state.get("history_by_sid", {}).get(sid, state["history"])

    def session_live_snapshot(self, project, sid):
        # INV-WSESS-53: actual manager/SSE supplies automatic history updates.
        # Record only a completed synthetic observation, never a guessed frame.
        state = self.state()
        value = deepcopy(state.get("history_by_sid", {}).get(sid, state["history"]))
        self.record("live_snapshot", project=project, sid=sid)
        return {"schema": 1, "scope_id": ("1" if sid == SID else "2") * 64,
                "history": value}

    def session_models(self, project, sid):
        self.record("models", project=project, sid=sid)
        state = self.state()
        time.sleep(state.get("catalog_delay", 0))
        return state.get("catalog_by_sid", {}).get(sid, state["catalog"])

    def session_send(self, project, sid, message_id, text, selection=None):
        self.record("send", project=project, sid=sid, message_id=message_id, text=text, selection=selection)
        state = self.state()
        time.sleep(state.get("send_delay", 0))
        status = state.get("send_status", "accepted")
        return {"status": status, "message_id": message_id, "turn_id": SID if status == "accepted" else None}

    def session_send_status(self, project, sid, message_id):
        self.record("send_status", project=project, sid=sid, message_id=message_id)
        return {"status": self.state().get("checked_status", "delivery_unknown"),
                "message_id": message_id, "turn_id": None}


def publish(feed, code=1, name="0.1.0"):
    payload = ("synthetic APK " + str(code)).encode()
    (feed / ("ai-control-" + str(code) + ".apk")).write_bytes(payload)
    private_json(feed / "version.json", {"versionCode": code, "versionName": name,
        "apkUrl": "https://llm-web.dewil.ru:18443/download/android/ai-control-" + str(code) + ".apk",
        "sha256": hashlib.sha256(payload).hexdigest()})
    return payload


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root / "bin"))
    web = importlib.import_module("_control_web")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0)); listener.listen(128)
    origin = "http://127.0.0.1:" + str(listener.getsockname()[1])
    # Trusted private fixture ingress for actual LIVE lifespan. No production
    # state, EnvironmentFile or authentication bypass is used.
    live_state = evidence / "live-state"; live_state.mkdir(mode=0o700)
    replay = live_state / "totp.json"; private_json(replay, {"last_step": -1})
    app = web.create_app({"origin": origin, "password_hash": web.hash_password(PASSWORD),
        "totp_secret": SECRET, "session_ttl": 3600, "secure_cookie": False,
        "totp_state_path": str(replay),
        "android_download_dir": str(evidence / "feed")}, Backend(evidence),
        clock=lambda: json.loads((evidence / "control.json").read_text()).get("clock", time.time()))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 8
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Synthetic fixture startup failed")
        time.sleep(.01)
    private_json(evidence / "ready.json", {"url": origin})
    thread.join()


if __name__ == "__main__":
    serve(Path(sys.argv[1]), Path(sys.argv[2]))
