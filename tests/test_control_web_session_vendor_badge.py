"""Source-blind synthetic coverage for the bounded INV-WSESS-28 vendor badge."""
from control_browser_helpers import choose_project
import importlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
SID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
UNKNOWN = "33333333-3333-4333-8333-333333333333"
MALICIOUS = "44444444-4444-4444-8444-444444444444"
NONSTRING = "55555555-5555-4555-8555-555555555555"
CONSTRUCTOR = "66666666-6666-4666-8666-666666666666"
PROTO = "77777777-7777-4777-8777-777777777777"
TOSTRING = "88888888-8888-4888-8888-888888888888"


class NativeRPC:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.pages = {
            None: {"data": [{"id": SID, "cwd": str(root), "name": "Claude is only a title",
                             "status": {"type": "idle"}}], "nextCursor": "opaque-next-page"},
            "opaque-next-page": {"data": [{"id": OTHER, "cwd": str(root),
                             "name": "Another misleading Claude title", "status": {"type": "idle"}}],
                             "nextCursor": None},
        }

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method == "thread/list":
            return self.pages[params.get("cursor")]
        if method == "thread/read":
            return {"thread": {"id": params["threadId"], "cwd": str(self.root)}}
        raise AssertionError("Unexpected synthetic RPC method: " + method)


class SessionVendorProjection(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("_control_web_sessions")
        self.tmp = tempfile.TemporaryDirectory(prefix="web-session-vendor-projection-", dir="/var/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.root = self.base / "project"
        self.root.mkdir(mode=0o700)
        self.receipts = self.base / "receipts"
        self.rpc = NativeRPC(self.root)
        self.resolved = []

        def resolve(project):
            self.resolved.append(project)
            if project != "demo":
                raise ValueError("synthetic unknown project")
            return str(self.root)

        self.chat = self.module.SessionChat(self.rpc, resolve, lambda: ["demo"], str(self.receipts))

    def test_INV_WSESS_28_list_rows_use_fixed_codex_adapter_identity_without_extra_io(self):
        result = self.chat.list_sessions("demo", 0)
        self.assertEqual(result, {"rows": [
            {"sid": SID, "title": "Claude is only a title", "status": "idle", "vendor": "codex"},
            {"sid": OTHER, "title": "Another misleading Claude title", "status": "idle", "vendor": "codex"},
        ], "has_more": False}, repr(self.rpc.calls))
        self.assertEqual(self.resolved, ["demo"])
        self.assertEqual([method for method, _ in self.rpc.calls],
                         ["thread/list", "thread/list", "thread/read", "thread/read"])
        list_params = {"cwd": str(self.root), "limit": 100,
                       "sourceKinds": ["cli", "vscode", "appServer"],
                       "sortKey": "updated_at", "sortDirection": "desc"}
        self.assertEqual([params for method, params in self.rpc.calls if method == "thread/list"],
                         [list_params, {**list_params, "cursor": "opaque-next-page"}])
        self.assertEqual([params for method, params in self.rpc.calls if method == "thread/read"],
                         [{"threadId": SID, "includeTurns": False},
                          {"threadId": OTHER, "includeTurns": False}])


def browser_rows():
    return [
        {"sid": SID, "title": "Claude is only the first title", "status": "idle", "vendor": "codex"},
        {"sid": OTHER, "title": "Codex is only the second title", "status": "idle", "vendor": "claude"},
        {"sid": UNKNOWN, "title": "Unknown synthetic provider", "status": "idle"},
        {"sid": MALICIOUS, "title": "Malicious vendor metadata", "status": "idle",
         "vendor": '<img src=x onerror="window.__vendorProbe=1">'},
        {"sid": NONSTRING, "title": "Non-string vendor metadata", "status": "idle", "vendor": ["claude"]},
        {"sid": CONSTRUCTOR, "title": "Prototype key constructor", "status": "idle", "vendor": "constructor"},
        {"sid": PROTO, "title": "Prototype key proto", "status": "idle", "vendor": "__proto__"},
        {"sid": TOSTRING, "title": "Prototype key toString", "status": "idle", "vendor": "toString"},
    ]


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root / "bin"))
    web = importlib.import_module("_control_web")

    class Backend:
        def snapshot(self): return {"tasks": []}
        def answer(self, *args): return {"error": "unavailable"}
        def verdict(self, *args): return {"error": "unavailable"}
        def session_projects(self): return {"projects": [{"name": "demo"}]}
        def record(self, event):
            with (evidence / "calls.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event) + "\n")
        def session_list(self, project, page):
            self.record({"method": "list", "project": project, "page": page})
            return {"rows": browser_rows(), "has_more": True}
        def session_history(self, project, sid, cursor):
            self.record({"method": "history", "project": project, "sid": sid, "cursor": cursor})
            return {"turns": [{"id": "vendor-badge-turn", "status": "completed", "items": [
                {"id": "vendor-badge-item", "role": "assistant", "text": "Synthetic selected history",
                 "truncated": False}]}], "next_cursor": None, "truncated": False, "recent_sends": []}
        def session_send(self, *args): return {"error": "unavailable"}
        def session_send_status(self, *args): return {"error": "stale"}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    origin = "http://127.0.0.1:" + str(listener.getsockname()[1])
    app = web.create_app({"origin": origin, "password_hash": web.hash_password(PASSWORD),
                          "totp_secret": SECRET, "session_ttl": 3600, "secure_cookie": False}, Backend())
    private_json(evidence / "ready.json", {"url": origin})
    uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)).run(sockets=[listener])


class SessionVendorBadgeBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("Optional Playwright browser dependency unavailable")
        os.umask(0o077)
        cls.evidence = Path(tempfile.mkdtemp(prefix="web-session-vendor-badge-", dir="/var/tmp"))
        cls.evidence.chmod(0o700)
        cls.root = Path(os.environ.get("CONTROL_SESSION_VENDOR_QA_REPO", str(ROOT)))
        interpreter = os.environ.get("CONTROL_SESSION_VENDOR_QA_SERVER_PYTHON", sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), "--serve",
                                       str(cls.root), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        while not (cls.evidence / "ready.json").exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None:
                raise RuntimeError("Synthetic vendor-badge fixture server failed")
            time.sleep(0.02)
        cls.url = json.loads((cls.evidence / "ready.json").read_text(encoding="utf-8"))["url"]
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get("CONTROL_SESSION_VENDOR_QA_BROWSER_EXECUTABLE")
        cls.browser = cls.playwright.chromium.launch(headless=True,
            **({"executable_path": executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={"width": 1280, "height": 900})
        cls.addClassCleanup(cls.context.close)
        login = cls.context.new_page()
        login.goto(cls.url)
        login.locator("input[type=password]").fill(PASSWORD)
        login.get_by_role("textbox", name=re.compile("TOTP|код|однораз", re.I)).fill(totp())
        login.get_by_role("button", name=re.compile("^Войти$", re.I)).click()
        login.get_by_role("button", name=re.compile("^Сессии$", re.I)).or_(
            login.get_by_role("tab", name=re.compile("^Сессии$", re.I))).wait_for()
        login.close()

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(4)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait()

    def setUp(self):
        (self.evidence / "calls.jsonl").unlink(missing_ok=True)
        self.page = self.context.new_page()
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(5000)
        self.network = []
        self.runtime_errors = []
        self.page.on("request", lambda request: self.network.append((request.method, request.url)))
        self.page.on("pageerror", lambda error: self.runtime_errors.append(type(error).__name__))
        self.page.goto(self.url)
        self.page.get_by_role("button", name=re.compile("^Сессии$", re.I)).or_(
            self.page.get_by_role("tab", name=re.compile("^Сессии$", re.I))).click()
        with self.page.expect_response(lambda item: "/api/sessions?" in item.url) as response_info:
            choose_project(self.page, "demo")
        self.list_payload = response_info.value.json()

    def tearDown(self):
        self.assertEqual(self.runtime_errors, [])
        self.assertFalse(any(url.split("/")[2] != self.url.split("/")[2]
                             for _, url in self.network), "Synthetic badge fixture must not use external network")
        self.assertTrue(self.page.evaluate("localStorage.length===0 && sessionStorage.length===0"))

    def test_INV_WSESS_28_badges_are_allowlisted_and_do_not_change_selection_or_pagination(self):
        self.assertEqual(self.list_payload["has_more"], True)
        self.assertEqual([row["sid"] for row in self.list_payload["rows"]],
                         [SID, OTHER, UNKNOWN, MALICIOUS, NONSTRING, CONSTRUCTOR, PROTO, TOSTRING])
        choices = self.page.locator(".session-choice")
        choices.first.wait_for()
        self.assertEqual(choices.count(), 8)
        badges = self.page.locator(".session-choice .session-vendor-badge")
        self.assertEqual(badges.count(), 8, "Each session choice needs a separate vendor badge span")
        expected = ["Codex", "Claude", "Вендор неизвестен", "Вендор неизвестен", "Вендор неизвестен",
                    "Вендор неизвестен", "Вендор неизвестен", "Вендор неизвестен"]
        self.assertEqual([badge.inner_text() for badge in badges.all()], expected)
        self.assertTrue(all(badge.evaluate("el => el.tagName === 'SPAN'") for badge in badges.all()))
        malicious = choices.nth(3)
        self.assertEqual(malicious.locator("img,script,svg").count(), 0,
                         "Untrusted vendor metadata cannot create markup")
        self.assertIsNone(self.page.evaluate("window.__vendorProbe"))
        self.assertIn("Malicious vendor metadata", malicious.inner_text())
        self.assertIn("Unknown synthetic provider", choices.nth(2).inner_text())
        self.assertEqual([choice.get_attribute("aria-pressed") for choice in choices.all()],
                         ["false"] * 8)

        self.page.wait_for_timeout(100)
        list_calls = [json.loads(line) for line in (self.evidence / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(list_calls, [{"method": "list", "project": "demo", "page": 0}],
                         "Displaying badges must preserve the existing first-page request")
        self.assertTrue(any("/api/sessions?" in url for _, url in self.network))

        choices.first.click()
        self.page.get_by_text("Synthetic selected history", exact=True).wait_for()
        self.assertEqual(choices.first.get_attribute("aria-pressed"), "true")
        calls = [json.loads(line) for line in (self.evidence / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([call for call in calls if call["method"] == "history"],
                         [{"method": "history", "project": "demo", "sid": SID, "cursor": None}])


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--serve":
        serve(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main()
