"""INV-DEVBUS-09 INV-DEVBUS-11: real main-page navigation and auth lifecycle."""
import time
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright
import live_devbus_blind_support as s


class BusMainBrowserBlind(s.HttpCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start(); cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(headless=True); cls.addClassCleanup(cls.browser.close)
        if cls.browser.version != "153.0.8010.12": raise RuntimeError("Mandatory Chromium153 drift; no SKIP")

    def setUp(self):
        super().setUp()
        self.context = self.browser.new_context(viewport={"width":390,"height":844}, has_touch=True)
        self.addCleanup(self.context.close)
        name, value = self.fixture.cookie.split("=", 1)
        self.context.add_cookies([dict(name=name, value=value, url=self.fixture.origin)])
        self.page = self.context.new_page(); self.page.set_default_timeout(1500)
        self.errors = []; self.requests = []
        self.page.on("pageerror", lambda error:self.errors.append(str(error)))
        self.page.on("request", lambda request:self.requests.append(request))

    def tearDown(self): self.assertEqual(self.errors, [])

    def enter(self):
        self.page.goto(self.fixture.origin)
        button = self.page.get_by_role("button", name="Шина", exact=True).or_(self.page.get_by_role("tab", name="Шина", exact=True))
        # Owner-session restoration admits the hidden workspace asynchronously.
        expect(button).to_have_count(1, timeout=4000)
        button.click(); expect(self.page.get_by_text("BUS synthetic result", exact=True)).to_have_count(1, timeout=4000)

    def until(self, predicate, timeout=4):
        deadline = time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline: self.page.wait_for_timeout(20)
        self.assertTrue(predicate(), "Expected public BUS lifecycle outcome")

    def test_real_mount_textContent_mobile_geometry_and_keyboard_tab(self):
        self.backend.bus_value["tasks"][0]["result"] = "<img src=x onerror='window.syntheticXss=true'>"
        self.page.goto(self.fixture.origin)
        tab = self.page.get_by_role("button", name="Шина", exact=True).or_(self.page.get_by_role("tab", name="Шина", exact=True))
        # Wait for asynchronous owner restore before keyboard navigation.
        expect(tab).to_have_count(1, timeout=4000)
        tab.focus(); tab.press("Enter")
        expect(self.page.get_by_text("<img src=x onerror='window.syntheticXss=true'>", exact=True)).to_have_count(1, timeout=4000)
        self.assertIsNone(self.page.evaluate("window.syntheticXss"))
        for width in (320,390,412):
            self.page.set_viewport_size({"width":width,"height":844})
            self.assertLessEqual(self.page.evaluate("Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth"),1)
            self.assertGreater(self.page.locator('[data-devbus-task="task1"]').bounding_box()["height"],0)

    def test_one_mount_poll_and_tabexit_stops_bus_without_chat_SSE(self):
        self.enter(); before_live = len(self.backend.calls)
        before = len(self.backend.bus_calls); self.until(lambda:len(self.backend.bus_calls)>before, timeout=3)
        self.assertEqual(len(self.backend.calls),before_live)
        self.assertFalse(any(urlsplit(request.url).path == "/api/session-events" for request in self.requests))
        self.page.get_by_role("button", name="Задачи", exact=True).or_(self.page.get_by_role("tab", name="Задачи", exact=True)).click()
        count = len(self.backend.bus_calls); self.page.wait_for_timeout(2300)
        self.assertEqual(len(self.backend.bus_calls),count, "BUS poll continued after tab exit")

    def test_pagehide_navigation_stops_old_poll(self):
        self.enter(); self.page.goto(self.fixture.origin+"/download/android")
        count = len(self.backend.bus_calls); self.page.wait_for_timeout(2300)
        self.assertEqual(len(self.backend.bus_calls),count)

    def test_same_mount_keeps_filter_focus_selection_and_no_scroll_jump(self):
        self.enter(); task=self.page.get_by_label("Задача",exact=True); agent=self.page.get_by_label("Агент",exact=True)
        task.fill("task1");agent.fill("worker1");task.focus();task.evaluate("e=>e.setSelectionRange(1,3)")
        before=len(self.backend.bus_calls); scroll=self.page.evaluate("scrollY")
        self.until(lambda:any(row['task']=='task1' and row['agent']=='worker1' for row in self.backend.bus_calls[before:]),timeout=4)
        self.assertEqual(task.input_value(),"task1");self.assertEqual(agent.input_value(),"worker1")
        self.assertTrue(task.evaluate("e=>e===document.activeElement"))
        self.assertEqual(task.evaluate("e=>[e.selectionStart,e.selectionEnd]"),[1,3])
        self.assertLessEqual(abs(self.page.evaluate("scrollY")-scroll),8)

    def test_logout_clears_BUS_without_spontaneous_remount(self):
        self.enter();self.page.get_by_role("button",name="Выйти",exact=True).click()
        expect(self.page.get_by_text("BUS synthetic result",exact=True)).to_have_count(0)
        before=len(self.backend.bus_calls);self.page.wait_for_timeout(2300)
        self.assertEqual(len(self.backend.bus_calls),before)

    def test_old_mount_late_response_cannot_repaint_after_tab_exit(self):
        self.enter(); self.backend.bus_gate.clear(); before = len(self.backend.bus_calls)
        self.until(lambda:len(self.backend.bus_calls)>before, timeout=3)
        self.page.get_by_role("button", name="Задачи", exact=True).or_(self.page.get_by_role("tab", name="Задачи", exact=True)).click()
        self.backend.bus_value["tasks"][0]["result"] = "BUS stale late reply marker"; self.backend.bus_gate.set()
        self.page.wait_for_timeout(150)
        expect(self.page.get_by_text("BUS stale late reply marker", exact=True)).to_have_count(0)

    def test_current_cookie_revocation_clears_private_BUS_and_stops_remount(self):
        self.enter(); self.fixture.sessions.clear()
        self.until(lambda:self.page.get_by_text("BUS synthetic result", exact=True).count()==0, timeout=4)
        count = len(self.backend.bus_calls); self.page.wait_for_timeout(2300)
        self.assertEqual(len(self.backend.bus_calls),count)

    def test_Android403_uses_shared_bridge_once_no_private_remount(self):
        self.page.add_init_script("window.syntheticBusAuthCalls=[];window.AndroidAuth={requestAuth:(...args)=>window.syntheticBusAuthCalls.push(args),requestLogout:()=>{}};")
        self.page.goto(self.fixture.origin); self.page.evaluate("window.aiControlAndroidResume()")
        tab = self.page.get_by_role("button", name="Шина", exact=True).or_(self.page.get_by_role("tab", name="Шина", exact=True))
        # Android resume still requires asynchronous owner admission.
        expect(tab).to_have_count(1, timeout=4000); tab.click()
        expect(self.page.get_by_text("BUS synthetic result",exact=True)).to_have_count(1,timeout=4000)
        before = self.page.evaluate("window.syntheticBusAuthCalls.length")
        self.fixture.sessions[self.fixture.cookie.split("=",1)[1]]["principal"] = "project"
        self.until(lambda:self.page.evaluate("window.syntheticBusAuthCalls.length")==before+1,timeout=4)
        self.assertEqual(self.page.evaluate("window.syntheticBusAuthCalls")[before:], [[]])
        count = len(self.backend.bus_calls); self.page.wait_for_timeout(2300)
        self.assertEqual(self.page.evaluate("window.syntheticBusAuthCalls.length"),before+1)
        self.assertEqual(len(self.backend.bus_calls),count)
