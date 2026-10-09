"""UX-only independent public HTTP/DOM acceptance, contractf393396.

INV-WSESS-47 INV-WSESS-48 INV-WSESS-49 INV-WSESS-50
No runtime source reads, real credentials/provider data/NATS, or optional skips.
Run: PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages
 /var/tmp/control-web-test-venv/bin/python -m unittest test_control_web_live_ux_blind_red
"""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import time
import unittest
import urllib.request
from urllib.parse import parse_qs, urlsplit
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import expect, sync_playwright
expect.set_options(timeout=1500)

import live_observability_blind_support as fixture
from control_browser_helpers import choose_project

ROOT = Path(os.environ.get("CONTROL_LIVE_UX_QA_REPO", str(Path(__file__).resolve().parents[1])))
BASELINE = "0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde"
WIDTHS = (320, 390, 412, 1280)
UNKNOWN = "Сессия: модель неизвестна · Размышление: уровень неизвестен"
CURRENT16 = {
    "bin/ai-control-web": 0o755, "bin/_control_web.py": 0o644,
    "bin/_control_web_broker.py": 0o644, "bin/_control_web_sessions.py": 0o644,
    "bin/_codex_rc.py": 0o644, "bin/_rc_projects.sh": 0o755,
    "bin/_control_web.html": 0o644, "bin/_control_web.css": 0o644,
    "bin/_control_web.js": 0o644, "requirements-web.lock": 0o644,
    "systemd/ai-control-web.service.tmpl": 0o644,
    "systemd/ai-control-web-broker.service.tmpl": 0o644,
    "bin/_control_web.svg": 0o644, "bin/_control_web_configured_create.py": 0o644,
    "bin/_control_web_android_auth.py": 0o644, "bin/_control_web_android_download.py": 0o644}
UX_RUNTIME = {"bin/_control_web.html", "bin/_control_web.css", "bin/_control_web.js",
              "bin/_control_web_android_download.py"}


# Inclusive normal-flow geometry independent of implementation stylesheet rules.
GEOMETRY = r"""() => {
 const h=document.querySelector('#chat-items'),f=document.querySelector('#build-info'),form=document.querySelector('#chat-form');
 const visible=e=>{let n=e;while(n){const s=getComputedStyle(n);if(s.display==='none'||['hidden','collapse'].includes(s.visibility)||Number(s.opacity)===0)return false;if(n.tagName==='DETAILS'&&!n.open&&e!==n&&!n.querySelector(':scope>summary')?.contains(e))return false;n=n.parentElement;}const r=e.getBoundingClientRect();return r.width>0&&r.height>0;};
 const inRange=e=>e!==h&&e!==f&&!h.contains(e)&&!f.contains(e)&&!e.contains(h)&&!e.contains(f)&&(h.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)&&(e.compareDocumentPosition(f)&Node.DOCUMENT_POSITION_FOLLOWING);
 const bottom=e=>e.getBoundingClientRect().bottom+scrollY;
 const candidates=[...document.querySelectorAll('body *')].filter(e=>inRange(e)&&visible(e));
 const actual=Math.max(...candidates.map(bottom)),originalScroll=scrollY;
 const saved=[...document.querySelectorAll('body *')].filter(e=>getComputedStyle(e).position==='sticky').map(e=>[e,e.getAttribute('style')]);
 saved.forEach(([e])=>e.style.setProperty('position','static','important'));
 const normal=Math.max(...candidates.filter(visible).map(bottom)),normalScroll=scrollY;
 saved.forEach(([e,s])=>s===null?e.removeAttribute('style'):e.setAttribute('style',s));
 const mandatory=[document.querySelector('#current-model-status'),document.querySelector('#next-model-status'),form.querySelector('textarea'),form.querySelector('button[type=submit]')];
 const antiCheat=mandatory.map(e=>{const styles=[];let n=e;while(n&&n!==document.body){const s=getComputedStyle(n);styles.push({position:s.position,transform:s.transform,margin:[s.marginTop,s.marginBottom,s.marginLeft,s.marginRight].map(parseFloat),clip:s.clipPath,overflowX:s.overflowX,overflowY:s.overflowY});n=n.parentElement;}return {present:!!e,visible:visible(e),range:inRange(e),top:e.getBoundingClientRect().top+scrollY,bottom:bottom(e),styles};});
 return {B:bottom(form)-bottom(h),C:Math.max(actual,normal)-bottom(h),historyBottom:bottom(h),footerTop:f.getBoundingClientRect().top+scrollY,overflow:Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth,textarea:form.querySelector('textarea').getBoundingClientRect().height,antiCheat,stableStickyScroll:originalScroll===normalScroll&&originalScroll===scrollY,
 fonts:{message:parseFloat(getComputedStyle(h.querySelector('article p')).fontSize),current:parseFloat(getComputedStyle(mandatory[0]).fontSize),next:parseFloat(getComputedStyle(mandatory[1]).fontSize)},fontFamily:getComputedStyle(h.querySelector('article p')).fontFamily,
 emptySlots:['send-status','model-status','receipt-list'].map(id=>{const e=document.getElementById(id);return !e||e.textContent.trim()?null:{id,height:e.getBoundingClientRect().height};}).filter(Boolean),
 atEnd:Math.abs(scrollY-(Math.max(document.body.scrollHeight,document.documentElement.scrollHeight)-innerHeight))<=1};
}"""


HIT = r"""e => {
 const r=e.getBoundingClientRect(),s=getComputedStyle(e),radii=[s.borderTopLeftRadius,s.borderTopRightRadius,s.borderBottomLeftRadius,s.borderBottomRightRadius].map(v=>Math.min(parseFloat(v)||0,r.width/2,r.height/2)),a=radii.map(v=>Math.max(1,v*(1-1/Math.sqrt(2))+1)),points=[[r.left+a[0],r.top+a[0]],[r.right-a[1],r.top+a[1]],[r.left+a[2],r.bottom-a[2]],[r.right-a[3],r.bottom-a[3]],[(r.left+r.right)/2,(r.top+r.bottom)/2]];
 return {width:r.width,height:r.height,points:points.map(([x,y])=>({inside:x>=0&&x<innerWidth&&y>=0&&y<innerHeight,owns:e===document.elementFromPoint(x,y)||e.contains(document.elementFromPoint(x,y))})),
 position:getComputedStyle(e).position,transform:getComputedStyle(e).transform,margins:[getComputedStyle(e).marginTop,getComputedStyle(e).marginBottom].map(parseFloat)};
}"""


class LiveUXScopeContract(unittest.TestCase):
    def scope_revision(self):
        value = os.environ.get("CONTROL_LIVE_UX_SCOPE_REVISION")
        if value is not None:
            self.assertRegex(value, r"\A[0-9a-f]{40}\Z", "Final CI requires an explicit full reviewed UX commit SHA")
            resolved = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--verify", value + "^{commit}"], text=True).strip()
            self.assertEqual(resolved, value)
        return value

    def test_closed_current16_ux_diff_inventory(self):
        revision = self.scope_revision()
        args = ["git", "-C", str(ROOT), "diff", "--name-only", BASELINE]
        if revision is not None: args.append(revision)
        changed = subprocess.check_output([*args, "--"], text=True).splitlines()
        if revision is None:
            changed += subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "--others", "--exclude-standard"], text=True).splitlines()
        runtime = {p for p in changed if not p.startswith(("docs/", "tests/"))}
        self.assertLessEqual(runtime, UX_RUNTIME, "UX gate expanded beyond four accepted runtime paths")
        self.assertEqual(len(CURRENT16), 16)

    def test_current16_startup_boundary_at_reviewed_UX_revision(self):
        revision = self.scope_revision()
        with tempfile.TemporaryDirectory(prefix="ux-current16-boundary-", dir="/var/tmp") as temporary:
            evidence = Path(temporary); runtime = evidence / "runtime"; runtime.mkdir()
            (evidence / "feed").mkdir(); fixture.private_json(evidence / "control.json", fixture.neutral())
            if revision is None:
                for relative in CURRENT16:
                    target = runtime / relative; target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / relative, target)
            else:
                # Materialize reviewed bytes without interpreting runtime source.
                data = subprocess.check_output(["git", "-C", str(ROOT), "archive", "--format=tar", revision, "--", *CURRENT16])
                with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                    found = set()
                    for member in archive.getmembers():
                        if not member.isfile(): continue
                        self.assertIn(member.name, CURRENT16)
                        target = runtime / member.name; target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.extractfile(member).read()); found.add(member.name)
                    self.assertEqual(found, set(CURRENT16))
            for relative, mode in CURRENT16.items(): (runtime / relative).chmod(mode)
            server = subprocess.Popen([sys.executable, fixture.__file__, str(runtime), str(evidence)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env={**os.environ, "PYTHONDONTWRITEBYTECODE":"1"})
            try:
                deadline = time.monotonic() + 8
                while not (evidence / "ready.json").exists():
                    if server.poll() is not None:
                        self.fail("Actual current16 startup failed: " + server.stderr.read().decode()[:500])
                    self.assertLess(time.monotonic(), deadline, "Actual current16 startup readiness timeout")
                    time.sleep(.02)
                url = json.loads((evidence / "ready.json").read_text())["url"]
                with urllib.request.urlopen(url + "/web.css", timeout=3) as response:
                    self.assertEqual(response.status, 200)
                print("Separate actual current16 startup boundary PASS; revision=" + (revision or "HEAD+workingtree"), flush=True)
            finally:
                server.terminate()
                try: server.wait(4)
                except subprocess.TimeoutExpired: server.kill(); server.wait()
                server.stderr.close()

    def test_frozen_baseline_contains_browser_fonts_following_and_dated_heights(self):
        path = Path(__file__).parent / "fixtures/live-ux-baseline/control-live-ux-bottom-baseline.json"
        doc = json.loads(path.read_text())
        self.assertEqual(doc["source_sha"], BASELINE)
        self.assertEqual(doc["environment"]["chromium"], "153.0.8010.12")
        self.assertEqual({r["width"] for r in doc["rows"]}, set(WIDTHS))
        self.assertEqual({r["width"] for r in doc["dated_rows"]}, set(WIDTHS))
        for row in doc["rows"] + doc["dated_rows"]:
            self.assertTrue(row["followingModeEvidence"]["atDocumentEnd"])
            self.assertIn("system-ui", row["fonts"]["message"]["family"])
        for row in doc["dated_rows"]:
            self.assertEqual(len(row["messages"]), 24)
            self.assertTrue(all(m["rect"]["document"]["height"] == 67 for m in row["messages"]))


class LiveUXBlindBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="live-ux-red-", dir="/var/tmp")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.evidence = Path(cls.tmp.name)
        cls.feed = cls.evidence / "feed"; cls.feed.mkdir()
        fixture.private_json(cls.evidence / "control.json", fixture.neutral())
        # Ordinary browser regressions use the actual final runtime, including
        # later separately authorized leaves. Closed16 is tested independently.
        cls.runtime = ROOT
        cls.server = subprocess.Popen([sys.executable, fixture.__file__, str(cls.runtime), str(cls.evidence)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"})
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        while not (cls.evidence / "ready.json").exists():
            if cls.server.poll() is not None:
                raise RuntimeError("Actual synthetic runtime startup failed: " + cls.server.stderr.read().decode()[:500])
            if time.monotonic() > deadline: raise RuntimeError("Actual runtime fixture readiness timeout")
            time.sleep(.02)
        cls.url = json.loads((cls.evidence / "ready.json").read_text())["url"]
        cls.pw = sync_playwright().start(); cls.addClassCleanup(cls.pw.stop)
        # Chromium failure is a failure, never an optional SKIP.
        cls.browser = cls.pw.chromium.launch(headless=True); cls.addClassCleanup(cls.browser.close)
        if cls.browser.version != "153.0.8010.12":
            raise RuntimeError("Chromium drift requires explicit rebaseline: " + cls.browser.version)
        cls.auth = cls.browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark", has_touch=True)
        cls.addClassCleanup(cls.auth.close)
        r = cls.auth.request.post(cls.url + "/api/login", data={"username": "owner", "password": fixture.PASSWORD,
            "totp": fixture.totp()}, headers={"Origin": cls.url})
        if r.status != 200: raise RuntimeError("Synthetic actual login failed: " + r.text())
        cls.storage = cls.auth.storage_state()
        print("UX Chromium " + cls.browser.version + "; actual runtime fixture startup PASS", flush=True)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try: cls.server.wait(4)
        except subprocess.TimeoutExpired: cls.server.kill(); cls.server.wait()
        cls.server.stderr.close()

    def setUp(self):
        for path in self.feed.iterdir(): path.unlink()
        self.state = fixture.neutral(); self.control()
        (self.evidence / "calls.jsonl").unlink(missing_ok=True)
        self.context = self.browser.new_context(storage_state=self.storage, viewport={"width": 390, "height": 844},
            color_scheme="dark", has_touch=True, timezone_id="America/Los_Angeles")
        self.addCleanup(self.context.close)
        self.page = self.context.new_page(); self.page.set_default_timeout(3500)
        self.errors = []; self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.requests = []; self.page.on("request", lambda request: self.requests.append(request))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def control(self, **changes):
        self.state.update(changes)
        fixture.private_json(self.evidence / "control.json", self.state)

    def calls(self, method):
        path = self.evidence / "calls.jsonl"
        return [r for r in map(json.loads, path.read_text().splitlines()) if r["method"] == method] if path.exists() else []

    def sessions(self):
        self.page.goto(self.url)
        self.page.get_by_role("button", name="Сессии", exact=True).or_(self.page.get_by_role("tab", name="Сессии", exact=True)).click()

    def open(self, dated=False):
        if dated:
            self.control(history=fixture.history(dated=True))
        self.select_session()
        self.wait_history()

    def select_session(self):
        self.sessions(); choose_project(self.page, "demo")
        self.page.get_by_role("button", name=re.compile("^UX synthetic session")).click()

    def wait_history(self):
        self.page.get_by_text("Fixture readable message 23", exact=True).wait_for()
        self.page.locator("#chat-model option").filter(has_text="Model Alpha").wait_for(state="attached")

    def wait_until(self, condition, message, timeout=3):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.page.wait_for_timeout(20)
        self.assertTrue(condition(), message)

    def reveal(self, locator):
        if locator.is_visible(): return
        # Public DOM semantics support any accepted details/ARIA disclosure.
        for summary in locator.locator("xpath=ancestor::details[not(@open)]/summary").all():
            if summary.is_visible(): summary.click()
        if locator.is_visible(): return
        candidates = locator.evaluate("""e=>{const ids=[];for(let n=e;n;n=n.parentElement){if(n.tagName==='DETAILS')ids.push({details:n.id});if(n.id)ids.push({id:n.id});}return ids;}""")
        for candidate in candidates:
            if candidate.get("details"):
                self.page.locator("#" + candidate["details"] + " > summary").click()
            elif candidate.get("id"):
                trigger = self.page.locator('[aria-controls="' + candidate["id"] + '"]')
                if trigger.count() and trigger.first.is_visible() and trigger.first.get_attribute("aria-expanded") != "true": trigger.first.click()
            if locator.is_visible(): return
        self.fail("Required existing action has no reachable touch/keyboard disclosure")

    def refresh(self):
        button = self.page.get_by_role("button", name="Обновить переписку", exact=True)
        self.reveal(button)
        with self.page.expect_response(lambda r: "/api/session-history?" in r.url): button.click()

    def start_refresh(self):
        button = self.page.get_by_role("button", name="Обновить переписку", exact=True)
        self.reveal(button); button.click()

    def refresh_models(self):
        button = self.page.get_by_role("button", name="Обновить список моделей", exact=True)
        self.reveal(button)
        with self.page.expect_response(lambda r: "/api/session-models?" in r.url): button.click()

    def close_model_disclosure(self):
        model = self.page.locator("#chat-model")
        details = model.locator("xpath=ancestor::details")
        count = details.count()
        # Do not mandate a new layout: if controls use a details disclosure,
        # actually close it before checking that the adjacent hint stays visible.
        for detail in details.all(): detail.evaluate("e=>e.open=false")
        if count:
            self.assertFalse(model.is_visible(), "Actual model disclosure must be closed for this hint oracle")
            self.assertTrue(all(not d.evaluate("e=>e.open") for d in details.all()))

    def ready_pair(self, draft="Synthetic nonempty model draft"):
        model = self.page.locator("#chat-model"); self.reveal(model)
        model.select_option(label="Model Alpha")
        self.page.locator("#chat-effort").select_option("high")
        self.page.locator("textarea").fill(draft)
        expect(self.page.get_by_role("button", name="Отправить", exact=True)).to_be_enabled()
        return model, self.page.locator("#chat-effort")

    def history_models_requests(self):
        return [r for r in self.requests if "/api/session-history?" in r.url or "/api/session-models?" in r.url]

    def follow(self):
        button = self.page.locator('[data-page-scroll="down"]').last
        self.reveal(button); button.click()
        # Close only a disclosure opened for navigation, preserving following.
        self.page.evaluate("""()=>{for(const e of document.querySelectorAll('details[open]'))e.open=false;}""")
        self.page.evaluate("async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}")

    def assert_hit(self, target):
        target.scroll_into_view_if_needed()
        result = target.evaluate(HIT)
        self.assertGreaterEqual(result["width"], 43.5, result)
        self.assertGreaterEqual(result["height"], 43.5, result)
        self.assertTrue(all(p["inside"] and p["owns"] for p in result["points"]), result)
        self.assertNotIn(result["position"], ("absolute", "fixed"), result)
        self.assertEqual(result["transform"], "none", result)
        self.assertTrue(all(v >= 0 for v in result["margins"]), result)

    def assert_caption(self, model="gpt-6.1-sol", effort="high"):
        expected = ("Сессия: " +
            ("модель неизвестна" if model is None else model) + " · Размышление: " +
            ("уровень неизвестен" if effort is None else effort))
        line = self.page.locator("#current-model-status")
        expect(line).to_have_text(expected)
        self.assertEqual(line.text_content(), expected, "Settings values must remain literal, without silent trimming")

    def test_INV47_neutral_inclusive_B_C_mandatory_controls(self):
        self.open()
        for width in WIDTHS:
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 900 if width == 1280 else 844})
                self.follow(); result = self.page.evaluate(GEOMETRY)
                print("neutral " + str(width) + " B=" + str(result["B"]) + " C=" + str(result["C"]), flush=True)
                ceiling = 620 if width == 320 else 560
                self.assertTrue(result["atEnd"], result)
                self.assertTrue(result["stableStickyScroll"], "Sticky normal-flow probe moved scrollY")
                self.assertEqual(result["fontFamily"], 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', "Font drift requires explicit rebaseline")
                self.assertLessEqual(max(result["B"], result["C"]), ceiling + .5, {"width":width,"B":result["B"],"C":result["C"],"ceiling":ceiling})
                self.assertLessEqual(result["overflow"], 1)
                self.assertGreaterEqual(result["textarea"], 96)
                self.assertGreaterEqual(result["fonts"]["message"], 14)
                self.assertTrue(all(v >= 12 for k, v in result["fonts"].items() if k != "message"))
                for mandatory in result["antiCheat"]:
                    self.assertTrue(mandatory["present"] and mandatory["visible"] and mandatory["range"], mandatory)
                    self.assertGreaterEqual(mandatory["top"], result["historyBottom"] - .5)
                    self.assertLessEqual(mandatory["bottom"], result["footerTop"] + .5)
                    for style in mandatory["styles"]:
                        self.assertNotIn(style["position"], ("absolute", "fixed")); self.assertEqual(style["transform"], "none")
                        self.assertTrue(all(v >= 0 for v in style["margin"])); self.assertEqual(style["clip"], "none")
                self.assertTrue(all(slot["height"] <= .5 for slot in result["emptySlots"]), result["emptySlots"])

    def test_INV47_dated_actual_hit_and_bubble_growth(self):
        # Existing public DOM seams confirmed by owner: baseline JS838/857,
        # CSS29 and preserved proof show article.chat-message/.message-heading.
        # No new implementation hook is introduced here.
        self.open(dated=True)
        baseline = json.loads((Path(__file__).parent / "fixtures/live-ux-baseline/control-live-ux-bottom-baseline.json").read_text())
        for width in WIDTHS:
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 900 if width == 1280 else 844})
                times = self.page.locator("#chat-items button.message-time")
                self.assertEqual(times.count(), 24)
                old = next(r for r in baseline["dated_rows"] if r["width"] == width)
                for index in (0, 12, 23): self.assert_hit(times.nth(index))
                observed = self.page.locator("#chat-items article.chat-message").evaluate_all("nodes=>nodes.map(e=>({height:e.getBoundingClientRect().height,header:e.querySelector('.message-heading')?.getBoundingClientRect().height??null}))")
                for index, row in enumerate(observed):
                    self.assertIsNotNone(row["header"], "Existing public message heading missing")
                    self.assertLessEqual(row["height"], old["messages"][index]["rect"]["document"]["height"] + 24.5)
                    self.assertAlmostEqual(row["header"], 44, delta=.5)

    def test_INV47_reader_draft_focus_keyboard_and_reachable_actions(self):
        self.open(dated=True)
        area = self.page.locator("textarea"); area.fill("Retained synthetic IME draft"); area.focus()
        area.evaluate("e=>e.setSelectionRange(3,8)")
        for height in (480, 844):
            self.page.set_viewport_size({"width": 390, "height": height})
            self.assertEqual(area.input_value(), "Retained synthetic IME draft")
            self.assertTrue(area.evaluate("e=>e===document.activeElement"))
            self.assertEqual(area.evaluate("e=>[e.selectionStart,e.selectionEnd]"), [3, 8])
            self.assert_hit(self.page.get_by_role("button", name="Отправить", exact=True))
        anchor = self.page.get_by_text("Fixture readable message 12", exact=True)
        anchor.scroll_into_view_if_needed(); before = anchor.bounding_box()["y"]
        before_poll = len(self.calls("history"))
        deadline = time.monotonic() + 7
        while len(self.calls("history")) == before_poll and time.monotonic() < deadline:
            self.page.wait_for_timeout(100)
        self.assertGreater(len(self.calls("history")), before_poll, "Actual same-snapshot automatic history poll must run")
        self.page.wait_for_timeout(120)
        self.assertLessEqual(abs(anchor.bounding_box()["y"] - before), 8)
        for name in ("Обновить переписку", "Переименовать"):
            button = self.page.get_by_role("button", name=name, exact=True)
            self.reveal(button); self.assert_hit(button); button.focus()
            self.assertTrue(button.evaluate("e=>e===document.activeElement"))

    def test_INV48_frozen_chips_geometry_count_area(self):
        self.control(projects=fixture.chips()); self.sessions()
        for width in (320, 390, 412):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 844})
                rects = []
                for name, count in (("zero", 0), ("loww", 3), ("high", 12), ("stle", 20)):
                    tile = self.page.get_by_role("button", name=re.compile("^" + name + r"(?:\b|\s)"))
                    expect(tile).to_contain_text(re.compile(r"(?<!\d)" + str(count) + r"(?!\d)")); expect(tile).to_contain_text("5м")
                    self.assertEqual(tile.get_attribute("type"), "button")
                    box = tile.bounding_box(); rects.append(box)
                    expected = 112 + 4 * min(5, math.floor(math.log2(count + 1)))
                    self.assertAlmostEqual(box["width"], expected, delta=.5)
                    self.assertAlmostEqual(box["height"], 44, delta=.5)
                    self.assertEqual(tile.evaluate("e=>getComputedStyle(e).boxSizing"), "border-box")
                self.assertTrue(all(a["width"] * a["height"] < b["width"] * b["height"] for a, b in zip(rects, rects[1:])))
                self.assertLessEqual(max(r["y"] + r["height"] for r in rects) - min(r["y"] for r in rects), 96.5)
                self.assertLessEqual(self.page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth"), 1)

    def test_INV48_unknown_stale_zero_noactivity_future_and_details(self):
        now = int(time.time())
        self.control(projects=[fixture.project("zero", 0, None, now=now), fixture.project("unkn", None, None, "unknown", now),
            fixture.project("stle", 20, now - 7200, "stale", now), fixture.project("futr", 1, now + 3600, now=now)])
        self.sessions()
        for name, count, activity in (("zero", "0", "—"), ("unkn", "?", "?"), ("stle", "20", "2ч"), ("futr", "1", "?")):
            tile = self.page.get_by_role("button", name=re.compile("^" + name + r"(?:\b|\s)"))
            if name == "unkn": expect(tile).to_contain_text(re.compile(r"\?[\s\S]*\?"))
            else: expect(tile).to_contain_text(re.compile(r"(?<!\d)" + count + r"(?!\d)"))
            text = tile.inner_text()
            if name == "unkn":
                self.assertGreaterEqual(text.count("?"), 2, "Unknown count and unknown activity must both be explicit")
                self.assertNotIn("—", text)
            else:
                self.assertRegex(text, r"(?<!\d)" + count + r"(?!\d)")
                expect(tile).to_contain_text(activity)
                if name == "zero": self.assertNotIn("?", text)
                if name == "futr": self.assertNotIn("—", text)
            if name == "stle": expect(tile).to_contain_text("устар.")
            self.assertNotIn("сейчас", tile.inner_text().lower())
            self.assert_hit(tile)
        # UXC-PROJECTS explicitly allows details of the selected project. Activate
        # stle, wait for its proven selection, then resolve only its bound details.
        tile = self.page.get_by_role("button", name=re.compile("^stle")); tile.focus(); tile.press("Enter")
        expect(tile).to_have_attribute("aria-pressed", "true")
        self.page.get_by_role("button", name=re.compile("^UX synthetic session")).wait_for()
        toggle = self.page.locator("#projects-toggle")
        if toggle.count() and toggle.get_attribute("aria-expanded") == "false": toggle.click()
        related = tile.evaluate("e=>[...new Set([e.id,...(e.getAttribute('aria-describedby')||'').split(/\\s+/),...(e.getAttribute('aria-controls')||'').split(/\\s+/)].filter(Boolean))]")
        containers = []
        for identity in related:
            candidate = self.page.locator("[id=" + json.dumps(identity) + "]")
            if candidate.count(): containers.append(candidate)
        semantic = self.page.get_by_role("region", name=re.compile("stle", re.I)).or_(self.page.get_by_role("group", name=re.compile("stle", re.I)))
        containers += semantic.all()
        # A selected-project disclosure can be a sibling labelled from stle.
        triggers = self.page.get_by_role("button", name=re.compile("stle.*(?:сведени|подроб|информац)|(?:сведени|подроб|информац).*stle", re.I)).or_(
            self.page.locator("summary").filter(has_text=re.compile("stle", re.I)))
        for trigger in triggers.all():
            if trigger.is_visible(): trigger.click()
            control = trigger.get_attribute("aria-controls")
            if control: containers.append(self.page.locator("[id=" + json.dumps(control) + "]"))
            if trigger.evaluate("e=>e.parentElement.tagName==='DETAILS'"): containers.append(trigger.locator(".."))
        matching = [c for c in containers if c.is_visible() and re.search(r"20\s+сессий", c.inner_text())]
        self.assertTrue(matching, "Visible project details must be bound to selected stle by ARIA/name, not unrelated page text")
        exact = datetime.fromtimestamp(now - 7200, ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M") + " МСК"
        self.assertTrue(any(exact in c.inner_text() for c in matching), "stle details must show the actual Europe/Moscow activity time: " + exact)

    def test_INV48_long_unbroken_project_wraps_without_clipping(self):
        name = "long_" + "unbroken" * 14
        self.control(projects=[fixture.project(name, 99999, int(time.time()) - 300)])
        self.sessions()
        tile = self.page.get_by_role("button", name=re.compile("^" + name))
        expect(tile).to_be_visible()
        for width in (320, 390, 412, 1280):
            self.page.set_viewport_size({"width": width, "height": 844})
            observation = tile.evaluate("e=>({overflow:Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth,height:e.getBoundingClientRect().height,clipped:e.scrollWidth>e.clientWidth+1||e.scrollHeight>e.clientHeight+1,ellipsis:[e,...e.querySelectorAll('*')].some(n=>getComputedStyle(n).textOverflow==='ellipsis')})")
            self.assertLessEqual(observation["overflow"], 1, observation)
            self.assertGreater(observation["height"], 44, "Long generic aliases must wrap, preserving full text")
            self.assertFalse(observation["clipped"] or observation["ellipsis"], observation)

    def test_INV47_delivery_unknown_stays_visible_inband_and_manual_no_resend(self):
        self.control(send_status="delivery_unknown"); self.open()
        area = self.page.locator("textarea"); area.fill("Synthetic unresolved message")
        self.page.get_by_role("button", name="Отправить", exact=True).click()
        status = self.page.locator("#send-status")
        expect(status).to_contain_text(re.compile("доставк.*неизвест", re.I))
        check = self.page.get_by_role("button", name="Проверить доставку", exact=True)
        expect(check).to_be_visible()
        for width in (320, 390, 412):
            self.page.set_viewport_size({"width": width, "height": 844}); self.follow()
            band = self.page.evaluate(GEOMETRY)
            for target in (status, check):
                bounds = target.evaluate("e=>({top:e.getBoundingClientRect().top+scrollY,bottom:e.getBoundingClientRect().bottom+scrollY})")
                self.assertGreaterEqual(bounds["top"], band["historyBottom"] - .5)
                self.assertLessEqual(bounds["bottom"], band["footerTop"] + .5)
            self.assertLessEqual(band["overflow"], 1)
        check.click(); self.page.wait_for_timeout(120)
        self.assertEqual(len(self.calls("send")), 1)
        self.assertEqual(len(self.calls("send_status")), 1)

    def test_INV49_known_current_next_and_initial_HTML_placeholder(self):
        # INV-WSESS-44 / UXC-MODEL preserves these existing IDs, source-note text
        # and aria-describedby. Canonical captions come only from feature D13.
        response = self.context.request.get(self.url + "/")
        self.assertRegex(response.text(), r'<option[^>]*value=""[^>]*>\s*Использовать текущую модель\s*</option>')
        self.open(); self.assert_caption()
        model = self.page.locator("#chat-model"); self.reveal(model)
        expect(model.locator('option[value=""]')).to_have_text("Использовать текущую модель")
        expect(self.page.locator("#next-model-status")).to_have_text("Следующая отправка: настройки сессии")
        model.select_option(label="Model Alpha"); self.page.locator("#chat-effort").select_option(label="high")
        expect(self.page.locator("#next-model-status")).to_have_text("Следующая отправка: Model Alpha · Размышление: high")
        self.assert_caption()
        note = self.page.locator("#session-settings-note"); self.reveal(note)
        expect(note).to_contain_text("активный ответ может")
        self.assertIn("session-settings-note", (self.page.locator("#current-model-status").get_attribute("aria-describedby") or "") + " " + (self.page.locator("textarea").get_attribute("aria-describedby") or ""))

    def test_INV49_nullable_custom256_and_invalid_fields(self):
        self.open()
        for model, effort in ((None, "high"), ("gpt-6.1-sol", None), (None, None), ("😀" * 256, "custom:X"), (" model with spaces ", "high")):
            with self.subTest(model=model, effort=effort):
                value = fixture.history(); value["session_settings"] = fixture.settings(model, effort)
                self.control(history=value); self.refresh(); self.assert_caption(model, effort)
                self.assertLessEqual(self.page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth"), 1)
        malformed = [{**fixture.settings(), "schema": True}, {**fixture.settings(), "model": ""}, {**fixture.settings(), "effort": 1},
            {**fixture.settings(), "model": "😀" * 257}, {**fixture.settings(), "model": " \u2003 "}, {**fixture.settings(), "age_ms": .5},
            {**fixture.settings(), "expires_in_ms": 14999}, {**fixture.settings(), "extra": "unsupported"}]
        # Feature "Уточнение UX-D01 и D03": expires_in_ms equals15000-age_ms,
        # so age0/expires14999 is explicitly invalid, not an inferred restriction.
        for settings in malformed:
            with self.subTest(settings=settings):
                # Every invalid input starts from independently confirmed known
                # state. A previous UNKNOWN must never satisfy the next case.
                self.control(history=fixture.history()); self.refresh(); self.assert_caption()
                before = len(self.calls("history"))
                value = fixture.history(); value["session_settings"] = settings
                self.control(history=value); self.refresh()
                self.assertGreater(len(self.calls("history")), before)
                expect(self.page.locator("#current-model-status")).to_have_text(UNKNOWN)

    def test_INV49_local_expiry_uses_request_start_without_extra_network(self):
        now = int(time.time() * 1000)
        self.page.clock.install(time=now); self.page.clock.pause_at(now + 1000)
        data = fixture.history(); data["session_settings"] = fixture.settings(age_ms=14600)
        self.page.route("**/api/session-history?*", lambda route: route.fulfill(json=data))
        self.open(); self.assert_caption()
        before = len(self.history_models_requests())
        self.page.clock.run_for(399); self.assert_caption()
        self.page.clock.run_for(1)
        self.assertEqual(self.page.locator("#current-model-status").text_content(), UNKNOWN, "No retry: caption must expire exactly at its own request-start deadline")
        self.assertEqual(len(self.history_models_requests()), before, "Settings expiry issued an extra history/model read")

    def test_INV49_delayed_response_does_not_extend_settings_lease(self):
        now = int(time.time() * 1000)
        self.page.clock.install(time=now); self.page.clock.pause_at(now + 1000)
        held = []
        self.page.route("**/api/session-history?*", lambda route: held.append(route))
        data = fixture.history(); data["session_settings"] = fixture.settings(age_ms=14600)
        self.select_session()
        self.wait_until(lambda: len(held) == 1, "Public initial history request must be held")
        before = sum("/api/session-history?" in r.url for r in self.requests)
        self.page.clock.run_for(700)
        held.pop().fulfill(json=data); self.wait_history()
        # Receipt-start lease would remain known for400ms on this paused clock.
        # A retry would conceal the bug, so test the first committed render exactly.
        self.assertEqual(self.page.locator("#current-model-status").text_content(), UNKNOWN, "Delayed response must already be expired, without retry")
        self.assertEqual(sum("/api/session-history?" in r.url for r in self.requests), before)

    def test_INV49_deterministic_deadline_minus_one_and_deadline_no_network(self):
        # Playwright controls only the test browser clock. API/DTO and rendered
        # application remain actual public surfaces, not a shadow renderer.
        now = int(time.time() * 1000)
        self.page.clock.install(time=now); self.page.clock.pause_at(now + 1000)
        data = fixture.history(); data["session_settings"] = fixture.settings(age_ms=14000)
        self.page.route("**/api/session-history?*", lambda route: route.fulfill(json=data))
        self.open(); self.assert_caption()
        count = len(self.history_models_requests())
        self.page.clock.run_for(999); self.assert_caption()
        self.page.clock.run_for(1)
        self.assertEqual(self.page.locator("#current-model-status").text_content(), UNKNOWN)
        self.assertEqual(len(self.history_models_requests()), count, "Exact deadline created an extra history/model read")

    def test_INV49_samekey_refresh_retains_until_deadline_then_failure_clears(self):
        self.open(); self.assert_caption()
        held = []
        self.page.route("**/api/session-history?*", lambda route: held.append(route))
        self.start_refresh(); self.wait_until(lambda: bool(held), "Same-key public refresh must be held")
        self.assert_caption()
        held.pop().fulfill(status=503, json={"error": "unavailable"})
        expect(self.page.locator("#current-model-status")).to_have_text(UNKNOWN)
        self.page.unroute("**/api/session-history?*")

    def test_INV49_A_B_A_old_selection_cannot_restore_snapshot(self):
        self.open()
        held = []
        self.page.route("**/api/session-history?*", lambda route: held.append(route))
        self.start_refresh(); self.wait_until(lambda: bool(held), "Old A public refresh must be held")
        old_A = held.pop()
        self.page.get_by_role("button", name="Other UX synthetic session", exact=False).click()
        self.page.wait_for_timeout(80)
        expect(self.page.locator("#current-model-status")).to_have_text(UNKNOWN)
        self.page.get_by_role("button", name=re.compile("^UX synthetic session")).click()
        self.page.wait_for_timeout(80)
        expect(self.page.locator("#current-model-status")).to_have_text(UNKNOWN)
        for route in held:
            sid = parse_qs(urlsplit(route.request.url).query)["sid"][0]
            value = fixture.history(); value["session_settings"] = fixture.settings("foreign-B" if sid == fixture.OTHER else "fresh-selected", "high")
            route.fulfill(json=value)
        held.clear()
        self.assert_caption("fresh-selected", "high")
        stale = fixture.history(); stale["session_settings"] = fixture.settings("old-generation", "low")
        old_A.fulfill(json=stale); self.page.wait_for_timeout(100)
        self.assert_caption("fresh-selected", "high")

    def test_INV49_stale_catalog_hint_near_selection_retains_pair_draft(self):
        self.control(catalog=fixture.catalog(expires_in_ms=3000)); self.open()
        model, effort = self.ready_pair("Retained synthetic catalog draft")
        self.close_model_disclosure()
        before = len(self.calls("models")); self.page.wait_for_timeout(3150)
        hint = self.page.get_by_text("Каталог устарел", exact=True)
        expect(hint).to_be_visible(); self.assert_caption()
        self.assertEqual(model.input_value(), "model-alpha"); self.assertEqual(effort.input_value(), "high")
        self.assertEqual(self.page.locator("textarea").input_value(), "Retained synthetic catalog draft")
        self.assertTrue(self.page.get_by_role("button", name="Отправить", exact=True).is_disabled())
        self.assertEqual(len(self.calls("models")), before, "Catalog expiry timer created a model read")
        self.assertFalse(hint.evaluate("e=>!!e.closest('#send-status,[data-local-outgoing],details:not([open])')"), "Hint must be visible outside pending/live region and closed model details")
        self.assertTrue(hint.evaluate("e=>{const next=document.querySelector('#next-model-status');for(let n=e.parentElement;n&&n!==document.body;n=n.parentElement){if(n.contains(next)&&n.querySelector('select'))return true;if(n===document.querySelector('#chat-form'))break;}return false;}"), "Hint and next caption must share the semantic model-selection group; chat-form is allowed")

    def test_INV49_missing_effort_hint_and_inherit_remains_usable(self):
        self.open(); model, effort = self.ready_pair("Synthetic inherited choice")
        effort.select_option("")
        expect(self.page.get_by_text("Выберите уровень", exact=True)).to_be_visible()
        expect(self.page.locator("#next-model-status")).to_have_text("Следующая отправка: Model Alpha · Размышление: выберите уровень")
        self.assertTrue(self.page.get_by_role("button", name="Отправить", exact=True).is_disabled())
        model.select_option("")
        expect(self.page.locator("#next-model-status")).to_have_text("Следующая отправка: настройки сессии")
        self.assertFalse(self.page.get_by_role("button", name="Отправить", exact=True).is_disabled())

    def test_INV49_loading_then_unavailable_hint_visible_outside_closed_menu(self):
        self.open(); model, effort = self.ready_pair()
        held = []
        self.page.route("**/api/session-models?*", lambda route: held.append(route))
        refresh = self.page.get_by_role("button", name="Обновить список моделей", exact=True)
        self.reveal(refresh); refresh.click()
        self.wait_until(lambda: bool(held), "Public model refresh must be held")
        self.close_model_disclosure()
        expect(self.page.get_by_text("Проверяем выбор", exact=True)).to_be_visible()
        self.assertTrue(held)
        for route in held: route.fulfill(status=503, json={"error": "unavailable"})
        held.clear()
        expect(self.page.get_by_text("Каталог недоступен", exact=True)).to_be_visible()
        self.assertTrue(self.page.get_by_role("button", name="Отправить", exact=True).is_disabled())
        self.assert_caption()

    def test_INV49_removed_model_and_unsupported_effort_hints(self):
        self.open()
        for index, (rows, expected) in enumerate((([{ "id":"model-beta","label":"Model Beta","efforts":["high"]}], "Модель недоступна"),
                               ([{"id":"model-alpha","label":"Model Alpha","efforts":["medium"]}], "Уровень недоступен"))):
            with self.subTest(hint=expected):
                self.control(catalog=fixture.catalog()); self.refresh_models()
                self.ready_pair("Nonempty removed/unsupported case " + str(index))
                value = fixture.catalog(); value["catalog_id"] = ("b" if index == 0 else "c") * 64; value["rows"] = rows
                self.control(catalog=value)
                self.refresh_models(); self.close_model_disclosure()
                expect(self.page.get_by_text(expected, exact=True)).to_be_visible()
                self.assertTrue(self.page.get_by_role("button", name="Отправить", exact=True).is_disabled())
                self.assertEqual(len(self.calls("send")), 0)

    def test_INV49_pending_attempt_has_immutable_UUID_pair(self):
        self.control(send_delay=.8, send_status="delivery_unknown"); self.open()
        model, effort = self.ready_pair("Synthetic immutable attempt")
        self.page.get_by_role("button", name="Отправить", exact=True).click()
        self.wait_until(lambda: bool(self.calls("send")), "Actual send must be observed")
        sends = self.calls("send"); self.assertEqual(len(sends), 1)
        immutable = sends[0]
        self.assertRegex(immutable["message_id"], r"\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
        self.assertEqual(immutable["selection"], {"catalog_id": "a" * 64, "model_id": "model-alpha", "effort": "high"})
        # Owner adjudication of review D06: existing pending flow locks these
        # controls. Do not require an extra catalog RPC or bypass disabled UI.
        refresh = self.page.get_by_role("button", name="Обновить список моделей", exact=True)
        self.assertTrue(model.is_disabled(), "Pending model selector must remain locked")
        self.assertTrue(effort.is_disabled(), "Pending effort selector must remain locked")
        self.assertTrue(refresh.is_disabled(), "Pending catalog refresh must remain locked")
        expect(self.page.locator("#send-status")).to_contain_text(re.compile("доставк.*неизвест", re.I))
        self.page.locator("textarea").fill("Changed future draft must not resend the unknown attempt")
        self.assertEqual(self.page.locator("textarea").input_value(), "Changed future draft must not resend the unknown attempt")
        expect(self.page.locator("#next-model-status")).to_have_text("Следующая отправка: Model Alpha · Размышление: high")
        self.assert_caption()
        self.assertEqual(self.calls("send"), [immutable])

    def assert_landing(self, code=None, version=None):
        response = self.page.goto(self.url + "/download/android/")
        self.assertEqual(response.status, 200)
        self.assertIn("no-store", response.headers.get("cache-control", ""))
        expect(self.page.get_by_role("link", name="В главное меню", exact=True)).to_be_visible()
        self.assertEqual(self.page.get_by_role("link", name="В главное меню", exact=True).get_attribute("href"), "/")
        colors = self.page.evaluate("()=>({background:getComputedStyle(document.body).backgroundColor,color:getComputedStyle(document.body).color,font:getComputedStyle(document.body).fontFamily})")
        self.assertEqual(colors["background"], "rgb(21, 21, 23)", colors)
        self.assertEqual(colors["color"], "rgb(230, 230, 233)", colors)
        self.assertIn("sans", colors["font"])
        self.assertEqual(self.page.locator('script[src*="web.js"]').count(), 0)
        self.assertEqual(self.page.locator('link[rel="stylesheet"][href="/web.css"]').count(), 1)
        if code:
            expect(self.page.locator("body")).to_contain_text(version)
            links = self.page.locator('a[href$=".apk"]'); self.assertEqual(links.count(), 1)
            self.assertTrue(links.first.get_attribute("href").endswith("/ai-control-" + str(code) + ".apk"))
        else: self.assertEqual(self.page.locator('a[href$=".apk"]').count(), 0)
        for width in WIDTHS:
            self.page.set_viewport_size({"width": width, "height": 900 if width == 1280 else 844})
            self.assertLessEqual(self.page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth"), 1)
            self.assert_hit(self.page.get_by_role("link", name="В главное меню", exact=True))

    def test_INV50_actual_anonymous_dark_empty_broken_public_css_return(self):
        anon = self.browser.new_context(); self.addCleanup(anon.close)
        self.page = anon.new_page(); self.assert_landing()
        css = anon.request.get(self.url + "/web.css"); self.assertEqual(css.status, 200)
        self.assertEqual(anon.cookies(), [])
        fixture.private_json(self.feed / "version.json", {"versionCode": 1})
        self.assert_landing()
        self.page.get_by_role("link", name="В главное меню", exact=True).click()
        expect(self.page.locator('input[type="password"]')).to_be_visible()
        (self.feed / "version.json").unlink()

    def test_INV50_existing_public_css_uses_actual_anonymous_HTTP(self):
        anon = self.browser.new_context(); self.addCleanup(anon.close)
        response = anon.request.get(self.url + "/web.css")
        self.assertEqual(response.status, 200)
        self.assertIn("text/css", response.headers.get("content-type", ""))
        self.assertIn("no-store", response.headers.get("cache-control", ""))
        self.assertEqual(anon.cookies(), [])

    def test_INV50_atomic_publication_persists_actual_renderer_and_bytes(self):
        anon = self.browser.new_context(); self.addCleanup(anon.close)
        self.page = anon.new_page()
        first = fixture.publish(self.feed, 1, "0.1.0"); self.assert_landing(1, "0.1.0")
        second = fixture.publish(self.feed, 2, "0.2.0"); self.assert_landing(2, "0.2.0")
        feed = anon.request.get(self.url + "/download/android/version.json").json()
        downloaded = anon.request.get(self.url + "/download/android/ai-control-2.apk")
        self.assertEqual(downloaded.body(), second); self.assertEqual(hashlib.sha256(downloaded.body()).hexdigest(), feed["sha256"])
        self.assertEqual(anon.request.get(self.url + "/download/android/ai-control-1.apk").body(), first)
        fixture.publish(self.feed, 2, "0.2.0"); self.assert_landing(2, "0.2.0")
        for path in self.feed.iterdir(): path.unlink()

    def test_INV50_single_short_download_navigation_login_tasks_sessions(self):
        for admitted in (False, True):
            context = self.browser.new_context(**({"storage_state": self.storage} if admitted else {})); self.addCleanup(context.close)
            page = context.new_page(); page.goto(self.url)
            link = page.get_by_role("link", name="Андроид", exact=True)
            expect(link).to_have_count(1); expect(link).to_be_visible()
            self.assertEqual(link.get_attribute("href"), "/download/android/")
        self.open()
        link = self.page.get_by_role("link", name="Андроид", exact=True)
        expect(link).to_have_count(1); self.assert_hit(link)


if __name__ == "__main__":
    unittest.main()
