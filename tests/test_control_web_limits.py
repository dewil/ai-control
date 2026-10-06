"""Source-blind synthetic contract tests for the pure limits projection.

Oracle: docs/dev/2026-10-06-spec-web-limits-projection.md at 4adf4c3 + amendments 3623ff3 and 584a899.
No existing runtime, provider/session/auth code or caches were read.
"""
import copy
import importlib
import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
NOW = 100_000
SECRET = "SYNTHETIC_SECRET_CANARY_DO_NOT_PROJECT"
WINDOWS = ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet")


def record(**changes):
    value = {"schema": 1, "provider": "codex", "account_id": "account_A",
             "captured_at": NOW - 20, "status": "ok", "plan": "Plus",
             "windows": {"five_hour": {"remaining": 42, "resets_at": NOW + 100}}}
    value.update(changes)
    return value


class HostileDict(dict):
    """A Mapping adapter is forbidden even if its payload otherwise looks valid."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.callbacks = []

    def trap(self, *args, **kwargs):
        self.callbacks.append("callback")
        raise AssertionError("Projection invoked a hostile mapping callback")

    get = __getitem__ = __iter__ = items = keys = values = __len__ = __bool__ = trap


class Uninspectable:
    def trap(self, *args, **kwargs):
        raise AssertionError("Unknown metadata must never be inspected")

    __repr__ = __str__ = __iter__ = __bool__ = __eq__ = trap




class HostileInt(int):
    def trap(self, *args, **kwargs):
        raise AssertionError("Rejected scalar must not invoke magic methods")

    __eq__ = __lt__ = __le__ = __gt__ = __ge__ = __float__ = __sub__ = __rsub__ = trap


class HostileFloat(float):
    def trap(self, *args, **kwargs):
        raise AssertionError("Rejected scalar must not invoke magic methods")

    __eq__ = __lt__ = __le__ = __gt__ = __ge__ = __float__ = __sub__ = __rsub__ = trap


class HostileStr(str):
    def trap(self, *args, **kwargs):
        raise AssertionError("Rejected scalar must not invoke magic methods")

    __eq__ = __str__ = __repr__ = __hash__ = trap


class CollidingKey:
    def __init__(self, target):
        self.target = target
        self.armed = False
        self.callbacks = []

    def __hash__(self):
        if self.armed:
            self.callbacks.append("hash")
            raise AssertionError("Container key validation must not hash hostile keys")
        return hash(self.target)

    def __eq__(self, other):
        if self.armed:
            self.callbacks.append("eq")
            raise AssertionError("Container key validation must precede dict lookup")
        return False


class LimitsProjection(unittest.TestCase):
    def setUp(self):
        # Missing feature is an assertion, never a collection/import error.
        self.assertTrue((ROOT / "bin" / "_control_web_limits.py").is_file(),
                        "INV-WLIM-01: public pure limits projection module is missing")
        module = importlib.import_module("_control_web_limits")
        self.project_limits = getattr(module, "project_limits", None)
        self.assertTrue(callable(self.project_limits),
                        "INV-WLIM-01: project_limits public contract is missing")

    def project(self, value, **context):
        args = {"provider": "codex", "account_id": "account_A", "now": NOW}
        args.update(context)
        return self.project_limits(value, **args)

    def unknown(self, provider="codex", account="account_A"):
        return {"schema": 1, "provider": provider, "account_id": account,
                "status": "unavailable", "plan": None, "captured_at": None,
                "age_seconds": None, "windows": []}

    def test_exact_safe_shape_and_distinct_accounts(self):
        # INV-WLIM-01 INV-WLIM-04
        a = self.project(record())
        b = self.project(record(account_id="account_B", windows={"five_hour": {"remaining": 7}}),
                         account_id="account_B")
        self.assertEqual(a, {"schema": 1, "provider": "codex", "account_id": "account_A",
                             "status": "ok", "plan": "Plus", "captured_at": NOW - 20,
                             "age_seconds": 20, "windows": [{"id": "five_hour",
                             "remaining_percent": 42, "resets_at": NOW + 100}]})
        self.assertEqual(b["windows"], [{"id": "five_hour", "remaining_percent": 7, "resets_at": None}])
        self.assertEqual(b["account_id"], "account_B")
        self.assertEqual(self.project(record(account_id="account_B")), self.unknown())

    def test_both_supported_providers_and_identifier_boundaries(self):
        # INV-WLIM-01 INV-WLIM-04
        for provider in ("claude", "codex"):
            for account in ("A", "a_Z-09", "A" * 80):
                with self.subTest(provider=provider, account=account):
                    view = self.project(record(provider=provider, account_id=account),
                                        provider=provider, account_id=account)
                    self.assertEqual((view["provider"], view["account_id"], view["status"]),
                                     (provider, account, "ok"))

    def test_missing_legacy_foreign_or_malformed_binding_is_unavailable(self):
        # INV-WLIM-01 INV-WLIM-03
        invalid = [None, [], "snapshot", 1, {"received_at": NOW, "snapshot": record()},
                   record(schema=True), record(schema=1.0), record(schema=2),
                   record(provider="claude"), record(account_id="account_B"),
                   record(status="unexpected")]
        for key in ("schema", "provider", "account_id", "captured_at", "status"):
            item = record()
            del item[key]
            invalid.append(item)
        for item in invalid:
            with self.subTest(case=type(item).__name__):
                self.assertEqual(self.project(item), self.unknown())

    def test_remaining_numeric_validation_and_known_zero(self):
        # INV-WLIM-02
        for remaining in (0, 0.0, 100, 12.5):
            with self.subTest(remaining=remaining):
                self.assertEqual(self.project(record(windows={"five_hour": {"remaining": remaining}}))
                                 ["windows"][0]["remaining_percent"], remaining)
        for remaining in (None, True, False, -0.1, 100.1, float("nan"), float("inf"),
                          -float("inf"), "42", [], {}):
            with self.subTest(kind=type(remaining).__name__):
                window = self.project(record(windows={"five_hour": {"remaining": remaining,
                                                                             "resets_at": NOW + 1}}))["windows"][0]
                self.assertIsNone(window["remaining_percent"])
                self.assertEqual(window["resets_at"], NOW + 1)
        self.assertIsNone(self.project(record(windows={"five_hour": {}}))["windows"][0]["remaining_percent"])

    def test_reset_validation_is_independent(self):
        # INV-WLIM-02
        for reset in (None, True, False, -1, float("nan"), float("inf"), "100001", [], {}):
            with self.subTest(kind=type(reset).__name__):
                window = self.project(record(windows={"five_hour": {"remaining": 42, "resets_at": reset}}))["windows"][0]
                self.assertEqual(window, {"id": "five_hour", "remaining_percent": 42, "resets_at": None})
        self.assertEqual(self.project(record(windows={"five_hour": {"remaining": 0,
                       "resets_at": NOW + 0.5}}))["windows"][0]["resets_at"], NOW + 0.5)

    def test_expired_reset_never_invents_remaining(self):
        # INV-WLIM-02
        for reset in (0, NOW - 1, NOW):
            with self.subTest(reset=reset):
                window = self.project(record(windows={"five_hour": {"remaining": 42, "resets_at": reset}}))["windows"][0]
                self.assertEqual(window, {"id": "five_hour", "remaining_percent": None, "resets_at": reset})
        self.assertEqual(self.project(record(windows={"five_hour": {"remaining": 42,
                         "resets_at": NOW + 1}}))["windows"][0]["remaining_percent"], 42)

    def test_fixed_window_order_and_unknown_entries_ignored(self):
        # INV-WLIM-02 INV-WLIM-04
        values = {key: {"remaining": i} for i, key in enumerate(reversed(WINDOWS))}
        values[SECRET] = Uninspectable()
        view = self.project(record(windows=values))
        self.assertEqual([item["id"] for item in view["windows"]], list(WINDOWS))
        self.assertEqual(len(view["windows"]), 4)
        self.assertNotIn(SECRET, json.dumps(view))
        for item in view["windows"]:
            self.assertEqual(set(item), {"id", "remaining_percent", "resets_at"})

    def test_absent_empty_malformed_windows_do_not_invent_limits(self):
        # INV-WLIM-02
        without = record()
        del without["windows"]
        for item in (without, record(windows={}), record(windows=None), record(windows=[]),
                     record(windows="bad"), record(windows={"five_hour": [], "seven_day": None})):
            self.assertEqual(self.project(item)["windows"], [])

    def test_age_boundary_default_custom_and_missing_reset(self):
        # INV-WLIM-03
        for age, status in ((0, "ok"), (2699, "ok"), (2700, "stale"), (2701, "stale")):
            with self.subTest(age=age):
                view = self.project(record(captured_at=NOW - age, windows={"five_hour": {"remaining": 0}}))
                self.assertEqual((view["status"], view["age_seconds"]), (status, age))
                self.assertEqual(view["windows"], [{"id": "five_hour", "remaining_percent": 0, "resets_at": None}])
        self.assertEqual(self.project(record(captured_at=NOW - 20), stale_after=20)["status"], "stale")
        self.assertEqual(self.project(record(captured_at=NOW - 19.5), stale_after=20)["status"], "ok")

    def test_valid_non_ok_status_suppresses_all_windows(self):
        # INV-WLIM-03
        for status in ("error", "stale", "locked", "unavailable"):
            for age in (20, 3000):
                with self.subTest(status=status, age=age):
                    view = self.project(record(status=status, captured_at=NOW - age))
                    self.assertEqual(view, {"schema": 1, "provider": "codex", "account_id": "account_A",
                                           "status": status, "plan": "Plus", "captured_at": NOW - age,
                                           "age_seconds": age, "windows": []})

    def test_invalid_or_future_capture_is_unavailable(self):
        # INV-WLIM-03
        for captured in (NOW + 0.1, None, True, False, -1, float("nan"), float("inf"), "99980", [], {}):
            with self.subTest(kind=type(captured).__name__):
                self.assertEqual(self.project(record(captured_at=captured)), self.unknown())
        view = self.project(record(captured_at=0), now=0)
        self.assertEqual((view["status"], view["captured_at"], view["age_seconds"]), ("ok", 0, 0))

    def test_plan_allowlist_and_secret_metadata_not_projected(self):
        # INV-WLIM-04
        for plan in ("Free", "Plus", "Pro", "Max", "Team", "Business", "Enterprise"):
            self.assertEqual(self.project(record(plan=plan))["plan"], plan)
        for plan in (None, SECRET, "plus", "Pro ", 1, [], {}):
            item = record(plan=plan, detail=SECRET, error=SECRET, email=SECRET,
                          token=SECRET, path=SECRET, raw={"token": SECRET}, metadata=Uninspectable())
            item["windows"]["five_hour"]["token"] = SECRET
            view = self.project(item)
            self.assertIsNone(view["plan"])
            self.assertNotIn(SECRET, json.dumps(view))
        item = record()
        del item["plan"]
        self.assertIsNone(self.project(item)["plan"])

    def test_hostile_dict_subclasses_never_receive_callbacks(self):
        # INV-WLIM-04
        hostile = HostileDict(record())
        self.assertEqual(self.project(hostile), self.unknown())
        self.assertEqual(hostile.callbacks, [])
        hostile = HostileDict({"five_hour": {"remaining": 42}})
        self.assertEqual(self.project(record(windows=hostile))["windows"], [])
        self.assertEqual(hostile.callbacks, [])
        hostile = HostileDict({"remaining": 42})
        self.assertEqual(self.project(record(windows={"five_hour": hostile}))["windows"], [])
        self.assertEqual(hostile.callbacks, [])

    def test_invalid_caller_context_precedes_record_and_has_fixed_error(self):
        # INV-WLIM-04
        invalid = [{"provider": item} for item in (None, SECRET, "Codex", "", 1)]
        invalid += [{"account_id": item} for item in (None, SECRET + "<", "", "a" * 81,
                    "а", "x y", "x\n", "x.y", "<script>", 1)]
        invalid += [{"now": item} for item in (None, True, False, -1, float("nan"), float("inf"), "1")]
        invalid += [{"stale_after": item} for item in (None, True, False, 0, -1, 1.0, "2700")]
        messages = set()
        for context in invalid:
            hostile = HostileDict(record())
            with self.subTest(field=next(iter(context))):
                with self.assertRaises(ValueError) as caught:
                    self.project(hostile, **context)
                message = str(caught.exception)
                self.assertTrue(message, "Caller errors need a fixed generic explanation")
                self.assertNotIn(SECRET, message)
                messages.add(message)
                self.assertEqual(hostile.callbacks, [])
        self.assertEqual(len(messages), 1, "Invalid context uses one fixed generic ValueError text")

    def test_exact_scalar_types_reject_callbacks_before_validation(self):
        # INV-WLIM-04
        for field, value in (("schema", HostileInt(1)), ("provider", HostileStr("codex")),
                             ("account_id", HostileStr("account_A")), ("status", HostileStr("ok")),
                             ("captured_at", HostileInt(NOW - 20)),
                             ("captured_at", HostileFloat(NOW - 20))):
            with self.subTest(field=field):
                self.assertEqual(self.project(record(**{field: value})), self.unknown())
        for field in ("schema", "provider", "account_id", "status", "captured_at"):
            self.assertEqual(self.project(record(**{field: Uninspectable()})), self.unknown())
        self.assertIsNone(self.project(record(plan=HostileStr("Plus")))["plan"])
        for field in ("remaining", "resets_at"):
            for value in (HostileInt(20), HostileFloat(20), Uninspectable()):
                fields = {"remaining": 42, "resets_at": NOW + 1, field: value}
                window = self.project(record(windows={"five_hour": fields}))["windows"][0]
                self.assertIsNone(window["remaining_percent" if field == "remaining" else "resets_at"])
        for field, value in (("provider", HostileStr("codex")), ("account_id", HostileStr("account_A")),
                             ("now", HostileInt(NOW)), ("now", HostileFloat(NOW)),
                             ("stale_after", HostileInt(2700))):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.project(Uninspectable(), **{field: value})

    def test_timestamp_limits_and_huge_integer_validation(self):
        # INV-WLIM-02 INV-WLIM-03 INV-WLIM-04
        upper = 253402300799
        huge = 10 ** 400
        for value in (upper + 1, float(upper + 1), huge, -huge):
            with self.assertRaises(ValueError):
                self.project(None, now=value)
            self.assertEqual(self.project(record(captured_at=value)), self.unknown())
            window = self.project(record(windows={"five_hour": {"remaining": huge, "resets_at": value}}))["windows"][0]
            self.assertEqual(window, {"id": "five_hour", "remaining_percent": None, "resets_at": None})
        view = self.project(record(captured_at=upper, windows={"five_hour": {"remaining": 42, "resets_at": upper}}), now=upper)
        self.assertEqual((view["status"], view["age_seconds"]), ("ok", 0))
        self.assertEqual(view["windows"][0], {"id": "five_hour", "remaining_percent": None, "resets_at": upper})
        self.assertEqual(self.project(record(), stale_after=huge)["status"], "ok")

    def test_non_string_and_subclass_keys_reject_container(self):
        # INV-WLIM-04
        for key in (1,):
            item = record()
            item[key] = Uninspectable()
            self.assertEqual(self.project(item), self.unknown())
            self.assertEqual(self.project(record(windows={key: Uninspectable(), "five_hour": {"remaining": 42}}))["windows"], [])
            self.assertEqual(self.project(record(windows={"five_hour": {key: Uninspectable(), "remaining": 42}}))["windows"], [])
        class StringKey(str):
            pass
        key = StringKey("metadata")
        item = record()
        item[key] = Uninspectable()
        self.assertEqual(self.project(item), self.unknown())
        self.assertEqual(self.project(record(windows={key: Uninspectable(), "five_hour": {"remaining": 42}}))["windows"], [])
        self.assertEqual(self.project(record(windows={"five_hour": {key: Uninspectable(), "remaining": 42}}))["windows"], [])

    def test_hostile_hash_collisions_rejected_without_magic_calls(self):
        # INV-WLIM-04
        for level, target in (("record", "schema"), ("windows", "five_hour"), ("window", "remaining")):
            key = CollidingKey(target)
            container = {key: Uninspectable()}
            if level == "record":
                container.update(record())
                item = container
            elif level == "windows":
                item = record(windows=container)
            else:
                item = record(windows={"five_hour": container})
            key.armed = True
            with self.subTest(level=level):
                view = self.project(item)
                self.assertEqual(view if level == "record" else view["windows"],
                                 self.unknown() if level == "record" else [])
                self.assertEqual(key.callbacks, [])

    def test_container_size_boundary_64_and_65(self):
        # INV-WLIM-04
        item = record()
        item.update({"extra_" + str(i): Uninspectable() for i in range(64 - len(item))})
        self.assertEqual(len(item), 64)
        self.assertEqual(self.project(item)["status"], "ok")
        item["extra_over_limit"] = Uninspectable()
        self.assertEqual(self.project(item), self.unknown())
        windows = {"five_hour": {"remaining": 42}}
        windows.update({"extra_" + str(i): Uninspectable() for i in range(63)})
        self.assertEqual(len(self.project(record(windows=windows))["windows"]), 1)
        windows["extra_over_limit"] = Uninspectable()
        view = self.project(record(windows=windows))
        self.assertEqual((view["status"], view["windows"]), ("ok", []))
        leaf = {"remaining": 42}
        leaf.update({"extra_" + str(i): Uninspectable() for i in range(63)})
        self.assertEqual(len(self.project(record(windows={"five_hour": leaf}))["windows"]), 1)
        leaf["extra_over_limit"] = Uninspectable()
        self.assertEqual(self.project(record(windows={"five_hour": leaf}))["windows"], [])

    def test_no_input_mutation_and_no_output_aliasing(self):
        # INV-WLIM-01 INV-WLIM-03
        item = record()
        before = copy.deepcopy(item)
        a, b = self.project(item), self.project(item)
        self.assertEqual(item, before)
        self.assertIs(type(a), dict)
        self.assertIs(type(a["windows"]), list)
        self.assertIs(type(a["windows"][0]), dict)
        self.assertIsNot(a, b)
        self.assertIsNot(a["windows"], b["windows"])
        self.assertIsNot(a["windows"][0], b["windows"][0])
        a["windows"][0]["remaining_percent"] = 90
        a["windows"].append({"id": "injected"})
        self.assertEqual(item, before)
        self.assertEqual(b["windows"][0]["remaining_percent"], 42)
        item["windows"]["five_hour"]["remaining"] = 3
        self.assertEqual(b["windows"][0]["remaining_percent"], 42)
        unknown_a, unknown_b = self.project(None), self.project(None)
        self.assertIsNot(unknown_a, unknown_b)
        self.assertIsNot(unknown_a["windows"], unknown_b["windows"])
        unknown_a["windows"].append({"id": "injected"})
        self.assertEqual(unknown_b, self.unknown())

    def test_no_io_environment_decoder_or_serialization(self):
        # INV-WLIM-01 INV-WLIM-04
        with ExitStack() as stack:
            environment = HostileDict()
            stack.enter_context(patch("os.environ", environment))
            mocks = [stack.enter_context(patch(name, side_effect=AssertionError("Forbidden pure-projection side effect")))
                     for name in ("builtins.open", "pathlib.Path.open", "os.open", "os.getenv",
                                  "subprocess.Popen", "socket.socket", "json.loads", "json.dumps")]
            view = self.project(record())
            self.assertEqual(view["status"], "ok")
            for mock in mocks:
                mock.assert_not_called()
            self.assertEqual(environment.callbacks, [])


if __name__ == "__main__":
    unittest.main()
