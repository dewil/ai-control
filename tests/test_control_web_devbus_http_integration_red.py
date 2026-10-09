"""INV-DEVBUS-07 INV-DEVBUS-11: actual shared factory/auth/cache/assets."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib
import unittest
from unittest.mock import patch
import live_devbus_blind_support as s


class BusHttpBlind(s.HttpCase):
    def test_actual_owner_route_exact_DTO_compact_bytes(self):
        connection, response = self.fixture.request("/api/devbus/overview")
        data = response.read(); connection.close()
        self.assertEqual(response.status, 200, "Actual owner BUS route must be integrated")
        self.assertEqual(data, s.canonical(self.backend.bus_value))
        self.assertIn("no-store", response.getheader("cache-control", ""))
        self.assertEqual(response.getheader("x-content-type-options"), "nosniff")
        self.assertEqual(len(self.backend.bus_calls), 1)

    def test_missing_expired_cookie_and_client_claim_never_admitted(self):
        self.expect_error(401, "unauthorized", cookie=False)
        self.expect_error(401, "unauthorized", cookie=False, headers=[("Cookie", "ai_control_session=" + "a" * 43), ("X-Owner", "owner")])
        self.fixture.now += 3601; self.expect_error(401, "unauthorized")
        self.assertEqual(self.backend.bus_calls, [])

    def test_private_legacy_nonowner_and_typed_principal_403(self):
        self.assertTrue(self.fixture.session_store_supported, "PUBLIC-SEAM PREREQUISITE: session_store absent")
        key = self.fixture.cookie.split("=", 1)[1]
        for principal in (None, "project", 1, True, {"principal":"owner"}):
            record = self.fixture.sessions[key]
            if principal is None: record.pop("principal", None)
            else: record["principal"] = principal
            self.expect_error(403, "forbidden")
        self.assertEqual(self.backend.bus_calls, [])

    def test_actual_owner_only_must_be_exact_True(self):
        for flag in (False,1):
            fixture=s.live.Fixture(owner_only=flag);self.addCleanup(fixture.stop);fixture.login()
            connection,response=fixture.request('/api/devbus/overview');value=__import__('json').loads(response.read());connection.close()
            self.assertEqual(response.status,403);self.assertEqual(value,{'error':'forbidden'})

    def test_origin_Fetch_and_query_before_backend(self):
        origin = self.fixture.origin
        for headers in ([('Origin', 'https://evil.invalid')], [('Origin', 'null')], [('Origin', origin), ('Origin', origin)], [('Sec-Fetch-Site', 'same-site')]):
            self.expect_error(403, "forbidden", headers=headers)
        for query in ("?unknown=x", "?task=", "?task=t1&task=t2", "?task=bad.id", "?agent=" + "a" * 81):
            self.expect_error(400, "invalid_request", suffix=query)
        self.assertEqual(self.backend.bus_calls, [])

    def test_backend_errors_and_malformed_collapse_without_leak(self):
        for outcome in ({"error":"busy"}, {"error":"unsupported"}, {"error":"unavailable"},
                        RuntimeError("synthetic-private-error"), self.backend.bus_value | {"private":"synthetic"}):
            self.backend.bus_outcome = outcome
            self.expect_error(503)

    def test_cache_hit_still_rechecks_current_principal(self):
        response, value = self.response(); self.assertEqual(response.status, 200)
        self.fixture.sessions[self.fixture.cookie.split("=", 1)[1]]["principal"] = "project"
        self.expect_error(403, "forbidden")
        self.assertEqual(len(self.backend.bus_calls), 1)

    def test_actual_device_revoke_before_cached_read(self):
        token = self.fixture.login(app=True)["device_token"]
        auth = importlib.import_module("_control_web_android_auth")
        store = auth.DeviceGrantStore(self.fixture.directory / "devices.sqlite", lambda:self.fixture.now)
        device = store.admit(token, foreground_open=False); self.assertIsInstance(device, str)
        response, _ = self.response(); self.assertEqual(response.status,200)
        store.revoke(device); self.expect_error(401,"unauthorized")
        self.assertEqual(len(self.backend.bus_calls),1)

    def test_device_store_corruption_503_before_backend(self):
        self.fixture.login(app=True)
        (self.fixture.directory / "devices.sqlite").write_bytes(b"synthetic corrupt sqlite")
        self.expect_error(503); self.assertEqual(self.backend.bus_calls,[])

    def test_shared_per_cookie_capacity_two_live_streams_then_BUS429(self):
        response, _ = self.response(); self.assertEqual(response.status,200,"Actual BUS admission prerequisite")
        for _ in range(2):
            connection, response = self.fixture.request('/api/session-events?project=demo&sid='+s.live.SID,
                headers=[('Accept','text/event-stream')])
            self.addCleanup(connection.close); self.assertEqual(response.status,200); s.live.event(response)
        self.expect_error(429); self.assertEqual(len(self.backend.bus_calls),1)

    def test_revocation_while_backend_pending_before_response(self):
        # Delete the private server record while a synchronized request owns IO.
        # Actual device-store revocation belongs to the shared authority suite.
        self.backend.bus_gate.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.response)
            entered = self.backend.wait_bus(1, 2)
            if not entered:
                self.backend.bus_gate.set(); response, _ = future.result(3)
                self.assertEqual(response.status, 200, "Actual BUS dispatch prerequisite")
            self.assertTrue(entered)
            self.fixture.sessions.pop(self.fixture.cookie.split("=", 1)[1]); self.backend.bus_gate.set()
            response, value = future.result(3)
        self.assertEqual(response.status, 401); self.assertEqual(value, {"error":"unauthorized"})

    def test_GET_only_and_fixed_assets_accepted_pins(self):
        response, _ = self.response(method="POST")
        self.assertIn(response.status, (404, 405)); self.assertEqual(self.backend.bus_calls, [])
        for url, path in (("/devbus.js", "bin/_control_web_devbus.js"), ("/devbus.css", "bin/_control_web_devbus.css")):
            connection, response = self.fixture.request(url); data = response.read(); connection.close()
            self.assertEqual(response.status, 200, "Accepted fixed local BUS assets must be exposed")
            expected = __import__("subprocess").check_output(["git", "-C", str(s.ROOT), "show", s.OBSERVER_COMMIT + ":" + path])
            self.assertEqual(data, expected); self.assertIn("no-store", response.getheader("cache-control", ""))
            self.assertEqual(response.getheader("x-content-type-options"), "nosniff")

    def test_factory_init_auth_perform_no_owner_config_or_NATS_io(self):
        broker = importlib.import_module("_control_web_broker")
        loader = getattr(broker, "load_devbus_config", None)
        self.assertTrue(callable(loader), "PUBLIC-SEAM PREREQUISITE: loader absent")
        with patch.object(broker, "load_devbus_config", side_effect=AssertionError("Frontend read owner config")):
            factory = self.fixture.web.create_app
            app = factory(dict(origin="http://127.0.0.1:1", password_hash=self.fixture.web.hash_password(s.live.PASSWORD),
                totp_secret=s.live.SECRET, secure_cookie=False), self.backend)
            self.assertIsNotNone(app)
        self.assertEqual(self.backend.bus_calls, [])


class DevbusFrontendBlind(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Frontend = s.seam(self, "_control_web", "DevbusFrontend")
        self.backend = s.BusBackend(); self.now = 0.0
        self.frontend = Frontend(self.backend, clock=lambda:self.now)

    async def asyncTearDown(self):
        self.backend.bus_gate.set(); await self.frontend.close()

    async def until(self, predicate, timeout=2):
        start = asyncio.get_running_loop().time()
        while not predicate() and asyncio.get_running_loop().time() - start < timeout: await asyncio.sleep(.01)
        self.assertTrue(predicate(), "Actual backend operation must enter")

    async def test_TTL_is_actual_call_start_not_completion_or_cache_read(self):
        self.backend.bus_gate.clear(); first = asyncio.create_task(self.frontend.overview())
        await self.until(lambda:len(self.backend.bus_calls)==1); self.now = .9; self.backend.bus_gate.set()
        self.assertEqual(await first, self.backend.bus_value)
        self.now = .99; self.assertEqual(await self.frontend.overview(), self.backend.bus_value)
        self.assertEqual(len(self.backend.bus_calls), 1)
        self.now = 1.0; await self.frontend.overview(); self.assertEqual(len(self.backend.bus_calls), 2)

    async def test_one_cache_entry_exact_key(self):
        await self.frontend.overview(task="task1"); await self.frontend.overview(task="task2")
        await self.frontend.overview(task="task1")
        self.assertEqual([(row['task'],row['agent']) for row in self.backend.bus_calls], [("task1",None),("task2",None),("task1",None)])

    async def test_samekey_coalesces_otherkey_busy_without_new_IO(self):
        self.backend.bus_gate.clear(); first = asyncio.create_task(self.frontend.overview(task="task1"))
        await self.until(lambda:len(self.backend.bus_calls)==1)
        same = asyncio.create_task(self.frontend.overview(task="task1")); await asyncio.sleep(.03)
        other = await self.frontend.overview(task="task2")
        self.assertIn(other, ({"error":"busy"},{"error":"unavailable"})); self.assertEqual(len(self.backend.bus_calls), 1)
        self.backend.bus_gate.set(); self.assertEqual(await first, await same)

    async def test_error_not_cached_slow_success_after_TTL_not_cached(self):
        self.backend.bus_outcome = {"error":"unavailable"}
        self.assertEqual(await self.frontend.overview(), {"error":"unavailable"})
        self.backend.bus_outcome = None; self.backend.bus_gate.clear()
        pending = asyncio.create_task(self.frontend.overview()); await self.until(lambda:len(self.backend.bus_calls)==2)
        self.now = 1.1; self.backend.bus_gate.set(); self.assertEqual(await pending, self.backend.bus_value)
        await self.frontend.overview(); self.assertEqual(len(self.backend.bus_calls), 3)

    async def test_caller_cancel_does_not_release_actual_sync_operation(self):
        self.backend.bus_gate.clear(); first = asyncio.create_task(self.frontend.overview())
        await self.until(lambda:len(self.backend.bus_calls)==1); first.cancel()
        try: await first
        except asyncio.CancelledError: pass
        other = await self.frontend.overview(task="task2")
        self.assertIn(other, ({"error":"busy"},{"error":"unavailable"})); self.assertEqual(len(self.backend.bus_calls), 1)
        self.backend.bus_gate.set(); await self.until(lambda:self.backend.bus_active==0)


class BusManifestBlind(unittest.TestCase):
    def test_all_four_passive_entries_once_and_accepted_file_bytes(self):
        entries = (s.ROOT / "scripts.manifest").read_text().splitlines()
        for name in ("_control_web_devbus.py", "_control_web_devbus_nats.py", "_control_web_devbus.js", "_control_web_devbus.css"):
            self.assertEqual(sum(row.strip() == name for row in entries), 1, "Accepted passive manifest entry missing/duplicated: " + name)
            path = s.ROOT / "bin" / name; self.assertTrue(path.is_file(), "Accepted immutable runtime leaf missing: " + name)
            expected = __import__("subprocess").check_output(["git", "-C", str(s.ROOT), "show", s.OBSERVER_COMMIT + ":bin/" + name])
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(expected).digest())
        path = s.ROOT / "requirements-devbus.lock"
        self.assertTrue(path.is_file(), "Accepted immutable dependency lock missing")
        expected = __import__("subprocess").check_output(["git", "-C", str(s.ROOT), "show", s.OBSERVER_COMMIT + ":requirements-devbus.lock"])
        self.assertEqual(path.read_bytes(),expected)
