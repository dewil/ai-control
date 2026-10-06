"""UI-source-blind attention browser RED with localhost synthetic API fixtures."""
import importlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from test_control_web_attention import make_overview, question, task
from test_control_web_chat_width_browser import PASSWORD, SECRET, totp

ROOT = Path(__file__).resolve().parents[1]


def _write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)


def _serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root / "bin"))
    web = importlib.import_module("_control_web")

    class Backend:
        def snapshot(self): return {"tasks": []}
        def answer(self, *args): return {"error": "unavailable"}
        def verdict(self, *args): return {"error": "unavailable"}
        def session_projects(self):
            return {"projects": [{"name": "alpha"}, {"name": "beta"}]}
        def session_list(self, project, page):
            return {"rows": [{"sid": "11111111-1111-4111-8111-111111111111",
                              "title": project + " synthetic session", "status": "idle"}],
                    "has_more": False}
        def session_history(self, project, sid, cursor):
            return {"turns": [], "next_cursor": None, "truncated": False,
                    "recent_sends": []}
        def session_send(self, *args): return {"error": "unavailable"}
        def session_send_status(self, *args): return {"error": "stale"}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0)); listener.listen(128)
    origin = "http://127.0.0.1:" + str(listener.getsockname()[1])
    app = web.create_app({"origin": origin, "password_hash": web.hash_password(PASSWORD),
                          "totp_secret": SECRET, "session_ttl": 3600,
                          "secure_cookie": False}, Backend())
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]},
                              daemon=True, name="synthetic-attention-ui")
    worker.start()
    deadline = time.monotonic() + 8
    while not server.started and time.monotonic() < deadline:
        if not worker.is_alive(): raise RuntimeError("synthetic attention server exited")
        time.sleep(.01)
    if not server.started: raise RuntimeError("synthetic attention server startup timeout")
    _write_private(evidence / "ready.json", {"url": origin})
    worker.join()


def _attention_fixture(*, questions_per_task=15, revision=1, epoch="b" * 32,
                       observed_at=None, label_prefix="Synthetic task"):
    now = int(time.time()) if observed_at is None else observed_at
    records = []
    qnum = 1
    questions = []
    for _ in range(questions_per_task):
        row = question(kind="info", status="open")
        row["qid"] = "%08x-0000-4000-8000-%012x" % (qnum, qnum)
        qnum += 1
        questions.append(row)
    for _ in range(7):
        row = question(kind="permission", status="open")
        row["qid"] = "%08x-0000-4000-8000-%012x" % (qnum, qnum)
        qnum += 1
        questions.append(row)
    records.append(task(registry_id="1".zfill(64), agent="synthetic-task-00",
                        questions=questions, label=label_prefix + " zero"))

    delivery = question(kind="info", status="closed", answered=True, delivery=True)
    delivery["qid"] = "%08x-0000-4000-8000-%012x" % (qnum, qnum); qnum += 1
    records.append(task(registry_id="2".zfill(64), agent="synthetic-task-01",
                        questions=[delivery], result={"generation": "1234abcd",
                        "state": "requested", "finalized": True, "result_key": "e" * 64},
                        label=label_prefix + " one"))
    for index in range(2, 8):
        row = question(kind="info", status="open")
        row["qid"] = "%08x-0000-4000-8000-%012x" % (qnum, qnum); qnum += 1
        records.append(task(registry_id=format(index + 1, "064x"),
                            agent="synthetic-task-%02d" % index,
                            questions=[row], label=label_prefix + " %d" % index))

    overview, _, _ = make_overview(records)
    payload = overview.snapshot()
    payload["epoch"] = epoch
    payload["revision"] = revision
    payload["observed_at"] = now
    for source in payload["sources"].values():
        if source["state"] == "fresh": source["observed_at"] = now
    return payload


def _stale_fixture():
    q = question(kind="info", status="open")
    q["qid"] = "aaaaaaaa-0000-4000-8000-000000000001"
    record = task(registry_id="f" * 64, agent="synthetic-stale-task", questions=[q],
                  label="Synthetic stale task")
    overview, _, source = make_overview([record])
    overview.snapshot()
    source.value.update(state="unavailable", complete=False, observed_at=None,
                        reason="unavailable", records=[])
    return overview.snapshot()


class AttentionUIBrowserRED(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("optional Playwright dependency unavailable")
        os.umask(0o077)
        cls.evidence = Path(tempfile.mkdtemp(prefix="control-attention-ui-red-", dir="/var/tmp"))
        cls.evidence.chmod(0o700)
        cls.root = Path(os.environ.get("CONTROL_WEB_ATTENTION_UI_REPO", str(ROOT)))
        interpreter = os.environ.get("CONTROL_WEB_ATTENTION_UI_SERVER_PYTHON", sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), "--serve",
                                       str(cls.root), str(cls.evidence)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        ready = cls.evidence / "ready.json"
        until = time.monotonic() + 8
        while not ready.exists() and time.monotonic() < until:
            if cls.server.poll() is not None: raise RuntimeError("synthetic web server failed")
            time.sleep(.01)
        if not ready.exists(): raise RuntimeError("synthetic web server readiness timeout")
        cls.url = json.loads(ready.read_text(encoding="utf-8"))["url"]
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get("CONTROL_WEB_ATTENTION_UI_BROWSER_EXECUTABLE")
        cls.browser = cls.playwright.chromium.launch(headless=True,
            **({"executable_path": executable} if executable else {}))
        cls.context = cls.browser.new_context(viewport={"width": 1280, "height": 900})
        cls.addClassCleanup(cls.context.close)
        login = cls.context.new_page()
        login.goto(cls.url)
        login.locator('input[type="password"]').fill(PASSWORD)
        login.get_by_role("textbox", name=re.compile("TOTP|код|однораз", re.I)).fill(totp())
        login.get_by_role("button", name=re.compile("^Войти$", re.I)).click()
        login.locator("#workspace").wait_for(state="visible", timeout=3000)
        login.close()
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try: cls.server.wait(4)
        except subprocess.TimeoutExpired:
            cls.server.kill(); cls.server.wait()

    def setUp(self):
        self.payload = _attention_fixture()
        self.raw_attention = json.dumps(self.payload, ensure_ascii=False,
                                        separators=(",", ":"), allow_nan=False)
        self.attention_status = 200
        self.task_rows = []
        self.events = []
        self.pending_attention = None
        self.hold_next_attention = False
        self.page = self.context.new_page()
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(3000)
        self.page.on("request", lambda req: self.events.append((req.method, req.url)))
        self.page.on("pageerror", lambda error: self.events.append(("PAGEERROR", type(error).__name__)))
        self.page.route("**/api/attention*", self._attention_route)
        self.page.route("**/api/tasks*", self._tasks_route)
        self.page.goto(self.url)
        self.page.locator("#workspace").wait_for(state="visible", timeout=3000)

    def _attention_route(self, route):
        self.events.append(("ATTENTION_ROUTE", route.request.method))
        if self.hold_next_attention:
            self.hold_next_attention = False
            self.pending_attention = (route, self.raw_attention, self.attention_status)
            return
        route.fulfill(status=self.attention_status, content_type="application/json",
                      body=self.raw_attention)

    def _tasks_route(self, route):
        self.events.append(("TASKS_ROUTE", route.request.method))
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"tasks": self.task_rows}, ensure_ascii=False))

    def panel(self):
        self.assertEqual(self.page.locator("#attention-overview").count(), 1,
                         "bounded authenticated attention region must be rendered")

    def refresh(self):
        self.page.locator("#attention-refresh").evaluate("el => el.click()")
        self.page.wait_for_timeout(120)

    def test_groups_unsupported_health_unique_task_counts_and_six_row_expansion(self):
        self.panel()
        self.assertEqual(self.page.locator("#attention-running-status").inner_text(),
                         "Статус сессий пока недоступен")
        for selector in ("#attention-decision", "#attention-question", "#attention-completed",
                         "#attention-delivery", "#attention-unlinked"):
            self.assertEqual(self.page.locator(selector).count(), 1)
        self.assertIn("Задач: 1", self.page.locator("#attention-decision").inner_text())
        self.assertIn("Задач: 7", self.page.locator("#attention-question").inner_text())
        self.assertIn("Задач: 1", self.page.locator("#attention-completed").inner_text())
        self.assertIn("Задач: 1", self.page.locator("#attention-delivery").inner_text())
        question_rows = self.page.locator('#attention-question button[data-attention-reason-id]')
        self.assertEqual(question_rows.count(), 6, "initial reason-group prefix is capped at six")
        attention_before_expand = sum(event == ("ATTENTION_ROUTE", "GET") for event in self.events)
        self.page.locator('button[data-attention-expand="question"]').click()
        self.assertEqual(question_rows.count(), 12, "expand adds at most six without another GET")
        self.assertEqual(sum(event == ("ATTENTION_ROUTE", "GET") for event in self.events),
                         attention_before_expand)
        unlinked_rows = self.page.locator('#attention-unlinked [data-attention-task-key]')
        self.assertEqual(unlinked_rows.count(), 6, "initial unlinked TASK prefix is capped at six")
        self.page.locator('button[data-attention-expand="unlinked"]').click()
        self.assertEqual(unlinked_rows.count(), 8)
        self.assertNotIn("0 работают", self.page.locator("#attention-running").inner_text(),
                         "unsupported empty sessions cannot be presented as zero running")
        self.assertIn("Показаны доступные данные", self.page.locator("#attention-status").inner_text())

    def test_duplicate_json_and_refusal_clear_protected_projection_without_writes(self):
        self.panel()
        self.assertGreater(self.page.locator("[data-attention-task-key]").count(), 0)
        raw = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self.raw_attention = raw[:-1] + ',"schema":1}'
        self.refresh()
        self.assertEqual(self.page.locator("[data-attention-task-key]").count(), 0)
        self.assertIn("Обзор пока недоступен", self.page.locator("#attention-status").inner_text())

        self.raw_attention = json.dumps(self.payload, ensure_ascii=False,
                                        separators=(",", ":"), allow_nan=False)
        self.attention_status = 503
        self.refresh()
        self.assertEqual(self.page.locator("[data-attention-task-key]").count(), 0)
        self.assertIn("Обзор пока недоступен", self.page.locator("#attention-status").inner_text())

        self.attention_status = 200
        invalid_top_time = dict(self.payload)
        invalid_top_time["observed_at"] = None
        self.raw_attention = json.dumps(invalid_top_time, ensure_ascii=False,
                                        separators=(",", ":"), allow_nan=False)
        self.refresh()
        self.assertEqual(self.page.locator("[data-attention-task-key]").count(), 0,
                         "top-level null observation is invalid even when source nulls are allowed")
        writers = [url for method, url in self.events if method == "POST"]
        self.assertEqual(writers, [])

    def test_stale_and_future_observation_clocks_disable_navigation(self):
        self.panel()
        self.raw_attention = json.dumps(_stale_fixture(), ensure_ascii=False,
                                        separators=(",", ":"), allow_nan=False)
        self.refresh()
        self.panel()
        stale = self.page.locator('[data-attention-state="stale"]')
        self.assertGreater(stale.count(), 0)
        nav = self.page.locator("button[data-attention-reason-id]").first
        self.assertTrue(nav.is_disabled(), "stale reason cannot navigate")
        future = _attention_fixture(observed_at=int(time.time()) + 301)
        self.raw_attention = json.dumps(future, ensure_ascii=False,
                                        separators=(",", ":"), allow_nan=False)
        self.attention_status = 200
        self.refresh()
        self.assertIn("Время обновления неизвестно", self.page.locator("#attention-age").inner_text())
        self.assertTrue(self.page.locator("button[data-attention-reason-id]").first.is_disabled())

    def test_equal_revision_keeps_focus_and_expansion_higher_revision_clamps_and_epoch_resets(self):
        self.panel()
        self.page.locator('button[data-attention-expand="question"]').click()
        rows = self.page.locator('#attention-question button[data-attention-reason-id]')
        self.assertEqual(rows.count(), 12)
        target = rows.nth(8)
        target_id = target.get_attribute("data-attention-reason-id")
        target.evaluate("el => el.focus()")
        equal = json.loads(self.raw_attention)
        equal["observed_at"] += 1
        equal["sources"]["task_registry"]["observed_at"] += 1
        self.raw_attention = json.dumps(equal, ensure_ascii=False, separators=(",", ":"))
        self.refresh()
        self.assertEqual(rows.count(), 12)
        self.assertEqual(self.page.evaluate("document.activeElement?.getAttribute('data-attention-reason-id')"),
                         target_id, "same revision success must preserve focus/expanded rows")

        higher = _attention_fixture(questions_per_task=18, revision=equal["revision"] + 1,
                                    epoch=equal["epoch"])
        self.raw_attention = json.dumps(higher, ensure_ascii=False, separators=(",", ":"))
        self.refresh()
        rows = self.page.locator('#attention-question button[data-attention-reason-id]')
        self.assertEqual(rows.count(), 12, "higher revision keeps the bounded expansion count")
        epoch = _attention_fixture(questions_per_task=18, revision=1, epoch="c" * 32)
        self.raw_attention = json.dumps(epoch, ensure_ascii=False, separators=(",", ":"))
        self.refresh()
        self.assertEqual(rows.count(), 6, "new view epoch resets expansion")
        self.assertNotEqual(self.page.evaluate("document.activeElement?.getAttribute('data-attention-reason-id')"),
                            target_id, "new view epoch clears old focus references")

    def test_higher_revision_restores_duplicate_reason_in_exact_unlinked_card_surface(self):
        self.panel()
        card = self.page.locator('#attention-unlinked [data-attention-task-key]').first
        task_key = card.get_attribute('data-attention-task-key')
        card_reason = card.locator('button[data-attention-reason-id]').first
        reason_id = card_reason.get_attribute('data-attention-reason-id')
        self.assertRegex(task_key or '', r'^[0-9a-f]{64}$')
        self.assertRegex(reason_id or '', r'^[0-9a-f]{64}$')

        group_reason = None
        group_name = None
        for group in ('decision', 'question', 'completed', 'delivery'):
            candidate = self.page.locator(
                f'#attention-{group} button[data-attention-reason-id="{reason_id}"]')
            while candidate.count() == 0:
                expand = self.page.locator(f'button[data-attention-expand="{group}"]')
                if expand.count() == 0:
                    break
                expand.click()
            if candidate.count():
                group_reason, group_name = candidate, group
                break
        self.assertIsNotNone(group_reason, 'fixture must expose the same pending reason in its group and task card')
        self.assertEqual(group_reason.get_attribute('data-task-key'), task_key)
        self.assertNotEqual(group_name, 'unlinked')

        card_reason.evaluate('el => el.focus()')
        self.assertTrue(card_reason.evaluate('el => document.activeElement === el'))
        # Keep the exact synthetic reason set stable; only advance its revision.
        higher = _attention_fixture(questions_per_task=15, revision=self.payload['revision'] + 1,
                                    epoch=self.payload['epoch'])
        self.raw_attention = json.dumps(higher, ensure_ascii=False, separators=(',', ':'))
        self.refresh()

        same_card_reason = self.page.locator(
            f'#attention-unlinked [data-attention-task-key="{task_key}"] button[data-attention-reason-id="{reason_id}"]')
        self.assertEqual(same_card_reason.count(), 1,
                         'higher revision must retain the same eligible reason in its original card')

        active = self.page.evaluate("""() => {
          const el = document.activeElement;
          return {
            reason: el?.getAttribute('data-attention-reason-id'),
            inCardSurface: !!el?.closest('#attention-unlinked'),
            surface: el?.getAttribute('data-attention-focus-surface'),
            owner: el?.getAttribute('data-attention-focus-owner')
          };
        }""")
        self.assertEqual(active['reason'], reason_id, 'higher revision should keep focus on the same reason')
        self.assertTrue(active['inCardSurface'], 'duplicate reason restoration must not jump back to its group copy')
        self.assertEqual(active['surface'], 'task-card')
        self.assertEqual(active['owner'], task_key)

    def test_final_expand_batch_focuses_same_group_heading_without_another_get(self):
        self.panel()
        rows = self.page.locator('#attention-question button[data-attention-reason-id]')
        self.assertEqual(rows.count(), 6)
        attention_gets = sum(event == ('ATTENTION_ROUTE', 'GET') for event in self.events)
        while True:
            expand = self.page.locator('button[data-attention-expand="question"]')
            self.assertEqual(expand.count(), 1, 'question expansion must end with a final batch')
            expand.evaluate('el => el.focus()')
            expand.click()
            if self.page.locator('button[data-attention-expand="question"]').count() == 0:
                break
        focus = self.page.evaluate("""() => ({
          tag: document.activeElement?.tagName,
          inGroup: !!document.activeElement?.closest('#attention-question'),
          group: document.activeElement?.getAttribute('data-attention-group-heading'),
          tabIndex: document.activeElement?.getAttribute('tabindex')
        })""")
        self.assertEqual(focus['tag'], 'H3', 'removing the focused final Show more must move focus to the group heading')
        self.assertTrue(focus['inGroup'], 'fallback focus must stay inside the expanded question group')
        self.assertEqual(focus['group'], 'question')
        self.assertEqual(focus['tabIndex'], '-1')
        self.assertEqual(sum(event == ('ATTENTION_ROUTE', 'GET') for event in self.events), attention_gets,
                         'expansion is local presentation and must not fetch')

    def test_scope_aba_late_response_and_navigation_require_fresh_exact_task_identity(self):
        self.panel()
        self.page.get_by_role("tab", name="Сессии").click()
        alpha = self.page.get_by_role("button", name=re.compile("^alpha\\b"))
        beta = self.page.get_by_role("button", name=re.compile("^beta\\b"))
        alpha.wait_for(state="visible")
        beta.wait_for(state="visible")
        self.assertEqual(self.page.locator("#project-cloud button").count(), 2)
        old = _attention_fixture(label_prefix="Old scope sentinel")
        self.raw_attention = json.dumps(old, ensure_ascii=False, separators=(",", ":"))
        self.hold_next_attention = True
        self.refresh()
        self.assertIsNotNone(self.pending_attention, "manual refresh should issue one attention GET")
        alpha.click()
        beta.click()
        alpha.click()
        current = _attention_fixture(label_prefix="Current scope sentinel")
        self.raw_attention = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
        pending, delayed_raw, delayed_status = self.pending_attention
        self.refresh()  # explicit current fetch after A→B→A invalidated the held fetch
        try:
            from playwright.sync_api import Error as PlaywrightError
            pending.fulfill(status=delayed_status, content_type="application/json", body=delayed_raw)
        except PlaywrightError:
            pass  # Scope changes may abort the old request before its late response.
        self.pending_attention = None
        self.page.wait_for_timeout(120)
        panel_text = self.page.locator("#attention-overview").inner_text()
        self.assertIn("Current scope sentinel", panel_text)
        self.assertNotIn("Old scope sentinel", panel_text,
                         "A→B→A scope generation must fence delayed former-A response")

        reason = self.page.locator('#attention-question button[data-attention-reason-id]').first
        reason_id = reason.get_attribute("data-attention-reason-id")
        task_key = reason.get_attribute("data-task-key")
        agent = reason.get_attribute("data-agent")
        qid = reason.get_attribute("data-qid")
        self.assertRegex(task_key or "", r"^[0-9a-f]{64}$")
        self.assertIn(reason_id, {row["reason_id"] for row in current["reasons"]})
        self.assertEqual(agent, "synthetic-task-00")
        self.assertRegex(qid or "", r"^[0-9a-f-]{36}$")
        self.task_rows = [{"agent": agent, "task_key": task_key, "name": "Current target",
                           "engine": "claude", "questions": [{"qid": qid, "kind": "info",
                           "status": "open", "answered": False, "question": "Synthetic"}],
                           "result": None}]
        before_tasks = sum(event == ("TASKS_ROUTE", "GET") for event in self.events)
        reason.click()
        self.page.wait_for_timeout(120)
        after_tasks = sum(event == ("TASKS_ROUTE", "GET") for event in self.events)
        self.assertGreater(after_tasks, before_tasks, "navigation must perform a fresh GET /api/tasks")
        card = self.page.locator('article.card[data-agent="synthetic-task-00"][data-task-key="' + task_key + '"]')
        self.assertEqual(card.count(), 1)
        self.assertEqual(card.locator('[data-qid="' + qid + '"]').count(), 1)
        forbidden = [url for method, url in self.events if method == "POST"]
        self.assertEqual(forbidden, [], "attention navigation is read-only")
        self.assertFalse(any("/api/session-history" in url for _, url in self.events),
                         "attention navigation must not request transcript history")


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--serve":
    _serve(Path(sys.argv[2]), Path(sys.argv[3]))
