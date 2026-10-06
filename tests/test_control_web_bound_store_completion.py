"""Blind RED for the complete pure C/I/A/S/T store contract.

Only public signatures, normative disk formats and OS seams are used. Fixtures
are invented in private temporary namespaces. Receipts never authorize native
launch, ownership or drain; no production capability is used here.
"""

import ctypes
import fcntl
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


BIN = Path(__file__).resolve().parents[1] / "bin"
SESSION = "123e4567-e89b-42d3-a456-426614174000"
SESSION_B = "123e4567-e89b-42d3-a456-426614174001"
OP = "123e4567-e89b-42d3-a456-426614174002"
OP_B = "123e4567-e89b-42d3-a456-426614174003"
HOST = "123e4567-e89b-42d3-a456-426614174005"
STOP_OP = "123e4567-e89b-42d3-a456-426614174006"
# Native SID is canonical UUID, deliberately not v4.
NATIVE = "123e4567-e89b-12d3-a456-426614174007"
OTHER_NATIVE = "123e4567-e89b-12d3-a456-426614174008"
INVOCATION = "a" * 32
PROJECT = "Control"
PROJECT_ROOT = "/synthetic/project"
DEADLINE = 110.0
ROLES = ("R", "G", "C", "I_session", "I_native", "A")
EXTENSION = ("capture_candidate", "publish_origin", "accept_create",
             "lookup_origin", "lookup_stop", "prepare_stop", "publish_stop",
             "accept_stop")


def reference(account="alpha"):
    return {"schema": 2, "provider_id": "codex", "account_id": account,
            "profile_instance_id": "123e4567-e89b-42d3-a456-426614174004",
            "adapter_revision": "codex-chatgpt-external-auth-host-v2",
            "registration_snapshot": {"dev": 1, "ino": 2, "ctime_ns": 3,
                                      "sha256": "a" * 64}}


def plain(value):
    return {key: plain(item) for key, item in value.items()} if hasattr(value, "items") else value


def canonical(value):
    return json.dumps(plain(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def names(ref, operation=OP, session=SESSION, sid=NATIVE):
    key = digest({"context_ref": ref, "project": PROJECT,
                  "root": PROJECT_ROOT, "operation_id": operation})
    native_key = digest({"context_ref": ref, "root": PROJECT_ROOT, "sid": sid})
    return {"R": f"BC-{key}.R.json", "G": f"BG-S-{session}.json",
            "C": f"BC-{key}.C.json", "I_session": f"BI-S-{session}.json",
            "I_native": f"BI-N-{native_key}.json", "A": f"BC-{key}.A.json"}


def stop_names(ref, session=SESSION, operation=STOP_OP):
    key = digest({"context_ref": ref, "root": PROJECT_ROOT,
                  "session_ref": session, "operation_id": operation})
    return {role: f"BS-{key}.{role}.json" for role in ("S", "T")}


class Clock:
    def __init__(self, value):
        self.value, self.calls, self.callback = value, 0, None

    def __call__(self):
        self.calls += 1
        if self.callback is not None:
            self.callback()
        return self.value


class ContractCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue((BIN / "_control_web_bound_session_store.py").is_file(),
                        "public BoundSessionStore module is required")
        sys.path.insert(0, str(BIN))
        self.addCleanup(lambda: sys.path.remove(str(BIN)))
        # Missing modules are assertion diagnostics, never accepted ImportErrors.
        try:
            self.module = importlib.import_module("_control_web_bound_session_store")
            self.dto = importlib.import_module("_control_web_bound_session_records")
            self.catalog = importlib.import_module("_control_provider_accounts")
        except ImportError as error:
            self.fail(f"public contract imports unavailable: {error.name}")
        self.ref = reference()
        self.wall, self.mono = Clock(111), Clock(100.0)
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-complete-bound-")
        self.addCleanup(self.temp.cleanup)
        self.namespace = Path(self.temp.name) / "bound"
        self.store = self.make_store()

    def make_store(self, ref=None, namespace=None):
        return self.module.BoundSessionStore(
            str(self.namespace if namespace is None else namespace),
            self.ref if ref is None else ref, clock=self.wall,
            monotonic_clock=self.mono)

    def api(self, name, store=None):
        method = getattr(self.store if store is None else store, name, None)
        self.assertTrue(callable(method), f"required PUBLIC method absent: BoundSessionStore.{name}")
        return method

    def error(self, code, call):
        with self.assertRaises(self.catalog.AccountError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)
        self.assertNotIn(str(self.namespace), repr(caught.exception))

    def record(self, ref=None, session=SESSION, operation=OP):
        ref = self.ref if ref is None else ref
        return self.dto.BoundRecordCodec(ref).prepare_create(
            ref, PROJECT, PROJECT_ROOT, session, operation, 111).record

    def fake_origin(self, ref=None):
        ref = self.ref if ref is None else ref
        filenames = names(ref)
        parents = {role: {"filename": filenames[role], "dev": 1, "ino": 2,
                          "ctime_ns": 3, "sha256": "a" * 64} for role in ROLES}
        return self.dto.BoundCreateReceipt(self.record(ref), "accepted", parents)

    def fake_unknown(self, ref=None):
        full = self.fake_origin(ref)
        parents = plain(full.parents)
        for role in ROLES[2:]:
            parents[role] = None
        return self.dto.BoundCreateReceipt(full.record, "unknown", parents)

    def fake_stop(self, ref=None, accepted=False):
        ref = self.ref if ref is None else ref
        prepared = self.dto.BoundRecordCodec(ref).prepare_stop(
            ref, self.fake_origin(ref), STOP_OP, HOST, INVOCATION, 111)
        filenames = stop_names(ref)
        parents = {role: {"filename": filenames[role], "dev": 1, "ino": 2,
                          "ctime_ns": 3, "sha256": "a" * 64} for role in ("S", "T")}
        if not accepted:
            parents["T"] = None
        return prepared, self.dto.BoundStopReceipt(
            prepared.record, "accepted" if accepted else "unknown", parents)

class PureCompletion(ContractCase):
    def test_exact_public_signatures_and_pure_constructor(self):
        constructor = inspect.signature(self.module.BoundSessionStore)
        self.assertEqual(list(constructor.parameters), ["path", "context_ref", "clock", "monotonic_clock"])
        for name in ("clock", "monotonic_clock"):
            self.assertEqual(constructor.parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
        signatures = {
            "locked": ["context_ref", "deadline", "create"],
            "lookup_create": ["base", "context_ref", "project", "root", "operation_id", "deadline"],
            "prepare_create": ["context_ref", "project", "root", "session_ref", "operation_id", "deadline"],
            "publish_create": ["base", "context_ref", "prepared", "deadline"],
            "capture_candidate": ["base", "context_ref", "receipt", "sid", "deadline"],
            "publish_origin": ["base", "context_ref", "receipt", "deadline"],
            "accept_create": ["base", "context_ref", "receipt", "deadline"],
            "lookup_origin": ["base", "context_ref", "root", "session_ref", "deadline"],
            "lookup_stop": ["base", "context_ref", "root", "session_ref", "operation_id", "deadline"],
            "prepare_stop": ["context_ref", "origin", "operation_id", "host_id", "invocation_id", "deadline"],
            "publish_stop": ["base", "context_ref", "prepared", "deadline"],
            "accept_stop": ["base", "context_ref", "receipt", "deadline"],
        }
        for name, expected in signatures.items():
            with self.subTest(api=name):
                self.assertEqual(list(inspect.signature(self.api(name)).parameters), expected)
        with mock.patch("os.open", side_effect=AssertionError("filesystem access")):
            self.make_store()
        self.assertEqual((self.wall.calls, self.mono.calls), (0, 0))

    def test_every_api_supplied_fullref_precedes_base_clock_and_io(self):
        prepared = self.dto.PreparedBoundCreate(self.record())
        stop, stop_receipt = self.fake_stop()
        calls = {
            "locked": lambda method, ref: method(ref, True, create=False).__enter__(),
            "lookup_create": lambda method, ref: method(object(), ref, "bad space", "relative", "bad", True),
            "prepare_create": lambda method, ref: method(ref, "bad space", "relative", "bad", "bad", True),
            "publish_create": lambda method, ref: method(object(), ref, prepared, True),
            "capture_candidate": lambda method, ref: method(object(), ref, self.fake_unknown(), "bad", True),
            "publish_origin": lambda method, ref: method(object(), ref, self.fake_unknown(), True),
            "accept_create": lambda method, ref: method(object(), ref, self.fake_unknown(), True),
            "lookup_origin": lambda method, ref: method(object(), ref, "relative", "bad", True),
            "lookup_stop": lambda method, ref: method(object(), ref, "relative", "bad", "bad", True),
            "prepare_stop": lambda method, ref: method(ref, self.fake_origin(), "bad", "bad", "bad", True),
            "publish_stop": lambda method, ref: method(object(), ref, stop, True),
            "accept_stop": lambda method, ref: method(object(), ref, stop_receipt, True),
        }
        with mock.patch("os.open", side_effect=AssertionError("open before context")), \
             mock.patch("os.stat", side_effect=AssertionError("stat before context")), \
             mock.patch("os.scandir", side_effect=AssertionError("scan before context")):
            self.mono.callback = lambda: self.fail("clock before context")
            self.wall.callback = lambda: self.fail("wall clock before context")
            for name, call in calls.items():
                with self.subTest(api=name):
                    method = self.api(name)
                    self.error("context_drift", lambda: call(method, reference("beta")))
                    self.error("context_invalid", lambda: call(method, {"schema": True}))

    def test_foreign_nested_dto_precedes_base_and_clock(self):
        foreign = reference("beta")
        prepared = self.dto.PreparedBoundCreate(self.record(foreign))
        stop, stop_receipt = self.fake_stop(foreign)
        values = {
            "publish_create": (prepared,),
            "capture_candidate": (self.fake_unknown(foreign), NATIVE),
            "publish_origin": (self.fake_unknown(foreign),),
            "accept_create": (self.fake_origin(foreign),),
            "publish_stop": (stop,), "accept_stop": (stop_receipt,),
        }
        with mock.patch("os.open", side_effect=AssertionError("nested context IO")), \
             mock.patch("os.stat", side_effect=AssertionError("nested context stat")):
            self.mono.callback = lambda: self.fail("nested context clock")
            for name, arguments in values.items():
                with self.subTest(api=name):
                    method = self.api(name)
                    self.error("context_drift", lambda: method(object(), self.ref, *arguments, DEADLINE))
            self.error("context_drift", lambda: self.api("prepare_stop")(
                self.ref, self.fake_origin(foreign), "bad", "bad", "bad", True))

    def test_prepare_stop_is_pure_single_sample_and_no_host_proof_fields(self):
        method = self.api("prepare_stop")
        origin = self.fake_origin()
        with mock.patch("os.open", side_effect=AssertionError("prepare_stop IO")), \
             mock.patch("os.stat", side_effect=AssertionError("prepare_stop stat")):
            prepared = method(self.ref, origin, STOP_OP, HOST, INVOCATION, DEADLINE)
        self.assertEqual(self.wall.calls, 1)
        self.assertEqual(prepared.record["created"], 111)
        self.assertEqual(plain(prepared.record["origin_parent"]), plain(origin.parents["A"]))
        self.assertEqual(set(prepared.record), {"schema", "kind", "context_ref", "root",
                         "session_ref", "operation_id", "created", "host_id",
                         "invocation_id", "origin_parent", "digest"})
        self.assertFalse(hasattr(prepared, "parents"))
        self.assertNotIn("synthetic", repr(prepared))
        with self.assertRaises((AttributeError, TypeError)):
            prepared.record["created"] = 112
        with self.assertRaises((AttributeError, TypeError)):
            prepared.record["context_ref"]["registration_snapshot"]["ino"] = 5

    def test_prepare_stop_syntax_deadline_wall_and_unknown_origin(self):
        method = self.api("prepare_stop")
        origin = self.fake_origin()
        for op, host, invocation, deadline in (("bad", HOST, INVOCATION, DEADLINE),
                (STOP_OP, "bad", INVOCATION, DEADLINE),
                (STOP_OP, HOST, "A" * 32, DEADLINE),
                (STOP_OP, HOST, INVOCATION, True),
                (STOP_OP, HOST, INVOCATION, float("inf"))):
            with self.subTest(inputs=(op, host, invocation, deadline)):
                self.error("invalid_request", lambda: method(
                    self.ref, origin, op, host, invocation, deadline))
        self.error("invalid_request", lambda: method(
            self.ref, self.fake_unknown(), STOP_OP, HOST, INVOCATION, DEADLINE))
        self.error("store_unavailable", lambda: method(
            self.ref, origin, STOP_OP, HOST, INVOCATION, 99.0))
        self.assertEqual(self.wall.calls, 0)
        for sample in (True, 0, -1, 2**63, 111.0):
            self.wall.value = sample
            self.error("invalid_request", lambda: method(
                self.ref, origin, STOP_OP, HOST, INVOCATION, DEADLINE))

    def test_malformed_extension_dto_shapes_are_invalid_request_before_clock(self):
        cases = (("capture_candidate", (object(), NATIVE)),
                 ("publish_origin", ({"record": {}},)),
                 ("accept_create", (object(),)),
                 ("publish_stop", (object(),)),
                 ("accept_stop", ({"record": {}},)))
        with mock.patch("os.open", side_effect=AssertionError("malformed DTO IO")):
            self.mono.callback = lambda: self.fail("malformed DTO clock")
            for name, arguments in cases:
                with self.subTest(api=name):
                    method = self.api(name)
                    self.error("invalid_request", lambda: method(object(), self.ref, *arguments, DEADLINE))


class LinuxCompletion(ContractCase):
    def setUp(self):
        super().setUp()
        for name in EXTENSION:
            self.api(name)
        self.assertTrue(sys.platform.startswith("linux"),
                        "actual Linux kernel required; this is not a skipped RED witness")

    def write(self, filename, value):
        self.namespace.mkdir(mode=0o700, exist_ok=True)
        raw = value if type(value) is bytes else canonical(value)
        fd = os.open(self.namespace / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        return self.commit(filename)

    def commit(self, filename):
        path = self.namespace / filename
        info = path.stat()
        return {"filename": filename, "dev": info.st_dev, "ino": info.st_ino,
                "ctime_ns": info.st_ctime_ns, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def seed(self, stage="R_G", *, ref=None, session=SESSION, operation=OP, sid=NATIVE):
        ref = self.ref if ref is None else ref
        record = self.record(ref, session, operation)
        filenames = names(ref, operation, session, sid)
        parents = dict.fromkeys(ROLES)
        parents["R"] = self.write(filenames["R"], record)
        parents["G"] = self.write(filenames["G"], {
            "schema": 1, "kind": "bound_session_reservation", "context_ref": ref,
            "project": PROJECT, "root": PROJECT_ROOT, "session_ref": session,
            "operation_id": operation, "r_parent": parents["R"]})
        if stage != "R_G":
            parents["C"] = self.write(filenames["C"], {
                "schema": 1, "kind": "bound_session_candidate",
                "r_parent": parents["R"], "g_parent": parents["G"], "sid": sid})
        if stage in ("I_session", "I_native", "I_both", "A"):
            origin = {"schema": 1, "kind": "bound_session_origin", "context_ref": ref,
                      "project": PROJECT, "root": PROJECT_ROOT, "session_ref": session,
                      "operation_id": operation, "sid": sid, "r_parent": parents["R"],
                      "g_parent": parents["G"], "c_parent": parents["C"]}
            for role in ("I_session", "I_native"):
                if stage in (role, "I_both", "A"):
                    parents[role] = self.write(filenames[role], origin)
        if stage == "A":
            parents["A"] = self.write(filenames["A"], {
                "schema": 1, "kind": "bound_session_accepted",
                "parents": {role: parents[role] for role in ROLES[:-1]}})
        return self.dto.BoundCreateReceipt(record, "accepted" if stage == "A" else "unknown", parents)

    def seed_stop(self, origin, terminal=False):
        prepared = self.dto.BoundRecordCodec(self.ref).prepare_stop(
            self.ref, origin, STOP_OP, HOST, INVOCATION, 111)
        filenames = stop_names(self.ref)
        parents = {"S": self.write(filenames["S"], prepared.record), "T": None}
        if terminal:
            parents["T"] = self.write(filenames["T"], {
                "schema": 1, "kind": "bound_session_stopped", "s_parent": parents["S"]})
        return prepared, self.dto.BoundStopReceipt(
            prepared.record, "accepted" if terminal else "unknown", parents)

    def locked_call(self, method, *arguments, store=None, ref=None):
        store, ref = (self.store if store is None else store), (self.ref if ref is None else ref)
        with store.locked(ref, DEADLINE, create=True) as base:
            return getattr(store, method)(base, ref, *arguments, DEADLINE)

    def lookup(self, operation=OP, store=None, ref=None):
        return self.locked_call("lookup_create", PROJECT, PROJECT_ROOT, operation,
                                store=store, ref=ref)

    def snapshot(self):
        return {path.name: (path.stat().st_ino, path.stat().st_ctime_ns, path.read_bytes())
                for path in self.namespace.iterdir()}

    def assert_receipt(self, actual, expected):
        self.assertEqual(actual.status, expected.status)
        self.assertEqual(plain(actual.record), plain(expected.record))
        self.assertEqual(plain(actual.parents), plain(expected.parents))
        for commitment in actual.parents.values():
            if commitment is not None:
                self.assertEqual(plain(commitment), self.commit(commitment["filename"]))

    def test_c_exact_schema_non_v4_native_sid_and_read_only_replay_conflict(self):
        rg = self.seed()
        c = self.locked_call("capture_candidate", rg, NATIVE)
        self.assertEqual(c.status, "unknown")
        self.assertEqual({key for key, value in c.parents.items() if value}, {"R", "G", "C"})
        raw = json.loads((self.namespace / names(self.ref)["C"]).read_bytes())
        self.assertEqual(raw, {"schema": 1, "kind": "bound_session_candidate",
                              "r_parent": plain(rg.parents["R"]),
                              "g_parent": plain(rg.parents["G"]), "sid": NATIVE})
        before = self.snapshot()
        self.assert_receipt(self.locked_call("capture_candidate", rg, NATIVE), c)
        self.error("store_unavailable", lambda: self.locked_call("capture_candidate", rg, OTHER_NATIVE))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.wall.calls, 0)

    def test_full_public_create_progression_and_byte_identical_i(self):
        prepared = self.store.prepare_create(self.ref, PROJECT, PROJECT_ROOT, SESSION, OP, DEADLINE)
        rg = self.locked_call("publish_create", prepared)
        c = self.locked_call("capture_candidate", rg, NATIVE)
        origin = self.locked_call("publish_origin", c)
        self.assertEqual(origin.status, "unknown")
        self.assertEqual({key for key, value in origin.parents.items() if value}, set(ROLES[:-1]))
        filenames = names(self.ref)
        self.assertEqual((self.namespace / filenames["I_session"]).read_bytes(),
                         (self.namespace / filenames["I_native"]).read_bytes())
        payload = json.loads((self.namespace / filenames["I_session"]).read_bytes())
        self.assertEqual(payload, {"schema": 1, "kind": "bound_session_origin",
                         "context_ref": self.ref, "project": PROJECT, "root": PROJECT_ROOT,
                         "session_ref": SESSION, "operation_id": OP, "sid": NATIVE,
                         "r_parent": plain(c.parents["R"]), "g_parent": plain(c.parents["G"]),
                         "c_parent": plain(c.parents["C"])})
        accepted = self.locked_call("accept_create", origin)
        self.assertEqual(accepted.status, "accepted")
        self.assertTrue(all(accepted.parents.values()))
        self.assertEqual(json.loads((self.namespace / filenames["A"]).read_bytes()),
                         {"schema": 1, "kind": "bound_session_accepted",
                          "parents": {role: plain(accepted.parents[role]) for role in ROLES[:-1]}})
        self.assert_receipt(self.lookup(), accepted)
        self.assert_receipt(self.locked_call("lookup_origin", PROJECT_ROOT, SESSION), accepted)
        self.assertEqual(self.wall.calls, 1)

    def test_lookup_create_exact_partial_progression_and_no_redispatch(self):
        for stage in ("R_G", "C", "I_session", "I_native", "I_both", "A"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory(dir=self.temp.name) as directory:
                old_namespace, old_store = self.namespace, self.store
                self.namespace = Path(directory) / "bound"
                self.store = self.make_store()
                try:
                    expected = self.seed(stage)
                    before = self.snapshot()
                    self.assert_receipt(self.lookup(), expected)
                    self.assertEqual(before, self.snapshot())
                    self.assertEqual(self.wall.calls, 0)
                finally:
                    self.namespace, self.store = old_namespace, old_store

    def test_each_one_i_order_recovery_uses_original_chain_only(self):
        for role in ("I_session", "I_native"):
            with self.subTest(role=role), tempfile.TemporaryDirectory(dir=self.temp.name) as directory:
                old_namespace, old_store = self.namespace, self.store
                self.namespace = Path(directory) / "bound"
                self.store = self.make_store()
                try:
                    partial = self.seed(role)
                    before = self.snapshot()
                    found = self.lookup()
                    self.assert_receipt(found, partial)
                    located = self.locked_call("lookup_origin", PROJECT_ROOT, SESSION)
                    if role == "I_native":
                        self.assertIsNone(located, "BI-N only is unresolved by the BI-S locator")
                    else:
                        self.assert_receipt(located, partial)
                    completed = self.locked_call("publish_origin", found)
                    self.assertEqual(completed.status, "unknown")
                    self.assertTrue(completed.parents["I_session"])
                    self.assertTrue(completed.parents["I_native"])
                    self.assertIsNone(completed.parents["A"])
                    for name, identity in before.items():
                        self.assertEqual(self.snapshot()[name], identity)
                    self.assertEqual((self.namespace / names(self.ref)["I_session"]).read_bytes(),
                                     (self.namespace / names(self.ref)["I_native"]).read_bytes())
                    self.assertEqual(self.wall.calls, 0)
                finally:
                    self.namespace, self.store = old_namespace, old_store

    def test_absent_origin_is_unresolved_and_r_without_c_stays_unknown(self):
        rg = self.seed()
        before = self.snapshot()
        self.assertIsNone(self.locked_call("lookup_origin", PROJECT_ROOT, SESSION))
        self.assert_receipt(self.lookup(), rg)
        self.error("store_unavailable", lambda: self.locked_call("publish_origin", rg))
        self.error("store_unavailable", lambda: self.locked_call("accept_create", rg))
        self.assertEqual(before, self.snapshot())

    def test_two_i_replay_does_not_accept_or_write_and_unknown_can_observe_a(self):
        both = self.seed("I_both")
        before = self.snapshot()
        self.assert_receipt(self.locked_call("publish_origin", both), both)
        self.assertEqual(before, self.snapshot())
        accepted = self.locked_call("accept_create", both)
        before = self.snapshot()
        for method, args in (("accept_create", (both,)), ("publish_origin", (both,)),
                             ("capture_candidate", (both, NATIVE))):
            with self.subTest(method=method):
                self.assert_receipt(self.locked_call(method, *args), accepted)
        self.assertEqual(before, self.snapshot())

    def test_known_accepted_missing_any_authoritative_stage_never_repairs(self):
        for role in ("C", "I_session", "I_native", "A"):
            with self.subTest(role=role), tempfile.TemporaryDirectory(dir=self.temp.name) as directory:
                old_namespace, old_store = self.namespace, self.store
                self.namespace = Path(directory) / "bound"
                self.store = self.make_store()
                try:
                    accepted = self.seed("A")
                    (self.namespace / names(self.ref)[role]).unlink()
                    before = self.snapshot()
                    for method, args in (("accept_create", (accepted,)),
                                         ("publish_origin", (accepted,)),
                                         ("capture_candidate", (accepted, NATIVE))):
                        self.error("store_unavailable", lambda m=method, a=args: self.locked_call(m, *a))
                    # Missing A can be unknown only for a fresh lookup; a still
                    # present A with missing parent must never downgrade.
                    if role != "A":
                        self.error("store_unavailable", self.lookup)
                    self.assertEqual(before, self.snapshot())
                finally:
                    self.namespace, self.store = old_namespace, old_store

    def test_accept_create_requires_both_i_and_never_repairs_missing_c(self):
        partial = self.seed("I_session")
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.locked_call("accept_create", partial))
        self.assertEqual(before, self.snapshot())
        (self.namespace / names(self.ref)["C"]).unlink()
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.locked_call("publish_origin", partial))
        self.assertEqual(before, self.snapshot())

    def test_fabricated_and_stale_claimed_parents_refuse_fresh_projection(self):
        c = self.seed("C")
        for role in ("R", "G", "C"):
            with self.subTest(role=role):
                parents = plain(c.parents)
                parents[role]["ino"] += 1
                fabricated = self.dto.BoundCreateReceipt(c.record, "unknown", parents)
                before = self.snapshot()
                for method, args in (("capture_candidate", (fabricated, NATIVE)),
                                     ("publish_origin", (fabricated,)),
                                     ("accept_create", (fabricated,))):
                    self.error("store_unavailable", lambda m=method, a=args: self.locked_call(m, *a))
                self.assertEqual(before, self.snapshot())

    def test_unknown_identity_and_created_cannot_be_rebound(self):
        c = self.seed("C")
        record = plain(c.record)
        record["created"] += 1
        record["digest"] = digest({key: value for key, value in record.items() if key != "digest"})
        changed = self.dto.BoundCreateReceipt(record, "unknown", c.parents)
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.locked_call("publish_origin", changed))
        self.assertEqual(before, self.snapshot())

    def test_foreign_global_origin_locator_precedes_damaged_parent_use(self):
        foreign = reference("beta")
        locator = {"schema": 1, "kind": "bound_session_origin", "context_ref": foreign,
                   "project": PROJECT, "root": PROJECT_ROOT, "session_ref": SESSION,
                   "operation_id": OP, "sid": NATIVE,
                   "r_parent": plain(self.fake_origin(foreign).parents["R"]),
                   "g_parent": plain(self.fake_origin(foreign).parents["G"]),
                   "c_parent": plain(self.fake_origin(foreign).parents["C"])}
        self.write(names(foreign)["I_session"], locator)
        # Parent files deliberately absent. Context ownership wins first.
        before = self.snapshot()
        self.error("context_drift", lambda: self.locked_call("lookup_origin", PROJECT_ROOT, SESSION))
        self.assertEqual(before, self.snapshot())

    def test_same_native_sid_across_contexts_distinct_locators(self):
        alpha = self.seed("A")
        beta = reference("beta")
        other = self.make_store(beta)
        beta_origin = self.seed("A", ref=beta, session=SESSION_B, operation=OP_B)
        self.assertNotEqual(alpha.parents["I_native"]["filename"], beta_origin.parents["I_native"]["filename"])
        self.assert_receipt(self.lookup(), alpha)
        self.assert_receipt(self.lookup(OP_B, store=other, ref=beta), beta_origin)
        self.assert_receipt(self.locked_call("lookup_origin", PROJECT_ROOT, SESSION_B,
                                            store=other, ref=beta), beta_origin)

    def test_global_session_collision_never_publishes_foreign_r_or_rebinds(self):
        accepted = self.seed("A")
        beta = reference("beta")
        other = self.make_store(beta)
        prepared = other.prepare_create(beta, PROJECT, PROJECT_ROOT, SESSION, OP_B, DEADLINE)
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.locked_call("publish_create", prepared, store=other, ref=beta))
        self.error("context_drift", lambda: self.locked_call("lookup_origin", PROJECT_ROOT, SESSION, store=other, ref=beta))
        self.assertEqual(before, self.snapshot())
        self.assert_receipt(self.lookup(), accepted)

    def test_retained_r_only_and_g_only_do_not_gain_completion_repair(self):
        rg = self.seed()
        g_path = self.namespace / names(self.ref)["G"]
        g_raw = g_path.read_bytes()
        g_path.unlink()
        before = self.snapshot()
        for method, args in (("capture_candidate", (rg, NATIVE)), ("publish_origin", (rg,)),
                             ("accept_create", (rg,))):
            self.error("store_unavailable", lambda m=method, a=args: self.locked_call(m, *a))
        self.error("store_unavailable", self.lookup)
        self.assertEqual(before, self.snapshot())
        (self.namespace / names(self.ref)["R"]).unlink()
        self.write(names(self.ref)["G"], g_raw)
        before = self.snapshot()
        prepared = self.dto.PreparedBoundCreate(self.record())
        self.error("store_unavailable", lambda: self.locked_call("publish_create", prepared))
        self.error("store_unavailable", self.lookup)
        self.assertEqual(before, self.snapshot())

    def test_stop_public_progression_exact_schema_replay_and_origin_retention(self):
        origin = self.seed("A")
        prepared = self.store.prepare_stop(self.ref, origin, STOP_OP, HOST, INVOCATION, DEADLINE)
        unknown = self.locked_call("publish_stop", prepared)
        self.assertEqual(unknown.status, "unknown")
        self.assertIsNone(unknown.parents["T"])
        self.assertEqual(set(unknown.parents), {"S", "T"})
        self.assertEqual(json.loads((self.namespace / stop_names(self.ref)["S"]).read_bytes()), plain(prepared.record))
        before = self.snapshot()
        self.assert_receipt(self.locked_call("publish_stop", prepared), unknown)
        self.assert_receipt(self.locked_call("lookup_stop", PROJECT_ROOT, SESSION, STOP_OP), unknown)
        self.assertEqual(before, self.snapshot())
        accepted = self.locked_call("accept_stop", unknown)
        self.assertEqual(accepted.status, "accepted")
        self.assertEqual(json.loads((self.namespace / stop_names(self.ref)["T"]).read_bytes()),
                         {"schema": 1, "kind": "bound_session_stopped", "s_parent": plain(accepted.parents["S"])})
        before = self.snapshot()
        self.assert_receipt(self.locked_call("publish_stop", prepared), accepted)
        self.assert_receipt(self.locked_call("accept_stop", unknown), accepted)
        self.assert_receipt(self.locked_call("accept_stop", accepted), accepted)
        self.assert_receipt(self.locked_call("lookup_stop", PROJECT_ROOT, SESSION, STOP_OP), accepted)
        self.assert_receipt(self.locked_call("lookup_origin", PROJECT_ROOT, SESSION), origin)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.wall.calls, 1)

    def test_stop_absent_is_unresolved_t_without_s_is_unavailable(self):
        origin = self.seed("A")
        self.assertIsNone(self.locked_call("lookup_stop", PROJECT_ROOT, SESSION, STOP_OP))
        _, terminal = self.seed_stop(origin, terminal=True)
        (self.namespace / terminal.parents["S"]["filename"]).unlink()
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.locked_call("lookup_stop", PROJECT_ROOT, SESSION, STOP_OP))
        self.error("store_unavailable", lambda: self.locked_call("accept_stop", terminal))
        self.assertEqual(before, self.snapshot())

    def test_known_accepted_missing_t_never_recreates_terminal(self):
        origin = self.seed("A")
        _, accepted = self.seed_stop(origin, terminal=True)
        (self.namespace / accepted.parents["T"]["filename"]).unlink()
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.locked_call("accept_stop", accepted))
        self.assertEqual(before, self.snapshot())
        fresh = self.locked_call("lookup_stop", PROJECT_ROOT, SESSION, STOP_OP)
        self.assertEqual(fresh.status, "unknown")
        self.assertIsNone(fresh.parents["T"])

    def test_stop_requires_exact_current_a_and_rejects_parent_fabrication(self):
        origin = self.seed("A")
        prepared, stop = self.seed_stop(origin)
        forged = plain(prepared.record)
        forged["origin_parent"]["ino"] += 1
        forged["digest"] = digest({key: value for key, value in forged.items() if key != "digest"})
        fake = self.dto.PreparedBoundStop(forged)
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.locked_call("publish_stop", fake))
        parents = plain(stop.parents)
        parents["S"]["sha256"] = "f" * 64
        fake_receipt = self.dto.BoundStopReceipt(stop.record, "unknown", parents)
        self.error("store_unavailable", lambda: self.locked_call("accept_stop", fake_receipt))
        self.assertEqual(before, self.snapshot())
        (self.namespace / origin.parents["A"]["filename"]).unlink()
        before = self.snapshot()
        for method, args in (("publish_stop", (prepared,)), ("accept_stop", (stop,)),
                             ("lookup_stop", (PROJECT_ROOT, SESSION, STOP_OP))):
            self.error("store_unavailable", lambda m=method, a=args: self.locked_call(m, *a))
        self.assertEqual(before, self.snapshot())

    def test_stop_conflicting_host_invocation_or_s_content_never_overwrites(self):
        origin = self.seed("A")
        prepared, _ = self.seed_stop(origin)
        record = plain(prepared.record)
        record["invocation_id"] = "b" * 32
        record["digest"] = digest({key: value for key, value in record.items() if key != "digest"})
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.locked_call("publish_stop", self.dto.PreparedBoundStop(record)))
        self.assertEqual(before, self.snapshot())

    def test_all_bases_opaque_raw_foreign_stale_and_cross_thread_refuse(self):
        c = self.seed("C")
        other = self.make_store()
        with self.store.locked(self.ref, DEADLINE) as base:
            for attribute in ("fd", "fileno", "__dict__", "__index__"):
                self.assertFalse(hasattr(base, attribute))
            self.error("invalid_request", lambda: other.publish_origin(base, self.ref, c, DEADLINE))
            for raw in (0, -1, object()):
                self.error("invalid_request", lambda value=raw: self.store.publish_origin(value, self.ref, c, DEADLINE))
            outcomes = []
            def cross_thread():
                try:
                    self.store.publish_origin(base, self.ref, c, DEADLINE)
                except self.catalog.AccountError as error:
                    outcomes.append(error.code)
            thread = threading.Thread(target=cross_thread)
            thread.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes, ["invalid_request"])
        self.error("invalid_request", lambda: self.store.publish_origin(base, self.ref, c, DEADLINE))

    def test_absent_base_reads_unresolved_and_writers_refuse(self):
        with self.store.locked(self.ref, DEADLINE, create=False) as base:
            self.assertIsNone(base)
            self.assertIsNone(self.store.lookup_origin(base, self.ref, PROJECT_ROOT, SESSION, DEADLINE))
            self.assertIsNone(self.store.lookup_stop(base, self.ref, PROJECT_ROOT, SESSION, STOP_OP, DEADLINE))
            for method, args in (("capture_candidate", (self.fake_unknown(), NATIVE)),
                                 ("publish_origin", (self.fake_unknown(),)),
                                 ("accept_create", (self.fake_origin(),)),
                                 ("publish_stop", (self.fake_stop()[0],)),
                                 ("accept_stop", (self.fake_stop()[1],))):
                self.error("store_unavailable", lambda m=method, a=args: getattr(self.store, m)(base, self.ref, *a, DEADLINE))


class PublicationFaults(ContractCase):
    def setUp(self):
        super().setUp()
        for name in EXTENSION:
            self.api(name)
        self.assertTrue(sys.platform.startswith("linux"), "actual Linux publication semantics required")

    # Share fixture/OS helpers only, not any private production representation.
    write = LinuxCompletion.write
    commit = LinuxCompletion.commit
    seed = LinuxCompletion.seed
    seed_stop = LinuxCompletion.seed_stop
    locked_call = LinuxCompletion.locked_call
    lookup = LinuxCompletion.lookup
    snapshot = LinuxCompletion.snapshot
    assert_receipt = LinuxCompletion.assert_receipt

    def next_stage(self, stage):
        if stage == "C":
            receipt = self.seed()
            return "capture_candidate", (receipt, NATIVE), names(self.ref)[stage]
        if stage in ("I_session", "I_native"):
            # Exercise each I publication as the next leaf after its opposite.
            receipt = self.seed("I_native" if stage == "I_session" else "I_session")
            return "publish_origin", (receipt,), names(self.ref)[stage]
        if stage == "A":
            receipt = self.seed("I_both")
            return "accept_create", (receipt,), names(self.ref)[stage]
        origin = self.seed("A")
        if stage == "S":
            prepared = self.dto.BoundRecordCodec(self.ref).prepare_stop(
                self.ref, origin, STOP_OP, HOST, INVOCATION, 111)
            return "publish_stop", (prepared,), stop_names(self.ref)[stage]
        _, receipt = self.seed_stop(origin)
        return "accept_stop", (receipt,), stop_names(self.ref)[stage]

    def observe_stage(self, stage):
        if stage in ("S", "T"):
            return self.locked_call("lookup_stop", PROJECT_ROOT, SESSION, STOP_OP)
        return self.lookup()

    def test_namespace_replacement_and_ancestor_replacement_refuse(self):
        for ancestor in (False, True):
            with self.subTest(ancestor=ancestor), tempfile.TemporaryDirectory(dir=self.temp.name) as directory:
                self.namespace = Path(directory) / "selected" / "bound"
                self.namespace.parent.mkdir(mode=0o700)
                self.store = self.make_store()
                receipt = self.seed("C")
                with self.store.locked(self.ref, DEADLINE) as base:
                    path = self.namespace.parent if ancestor else self.namespace
                    os.rename(path, path.with_name(path.name + "-held"))
                    path.mkdir(mode=0o700)
                    if ancestor:
                        self.namespace.mkdir(mode=0o700)
                    self.error("store_unavailable", lambda: self.store.publish_origin(base, self.ref, receipt, DEADLINE))
                    self.error("store_unavailable", lambda: self.store.lookup_origin(base, self.ref, PROJECT_ROOT, SESSION, DEADLINE))
                self.assertEqual(list(self.namespace.iterdir()), [])

    def test_strict_json_and_nlink_for_each_extension_leaf(self):
        mutations = ("duplicate", "bool_schema", "extra", "nonfinite", "utf8", "oversize", "hardlink", "symlink", "mode")
        for role in ("C", "I_session", "I_native", "A", "S", "T"):
            for mutation in mutations:
                with self.subTest(role=role, mutation=mutation), tempfile.TemporaryDirectory(dir=self.temp.name) as directory:
                    self.namespace = Path(directory) / "bound"
                    self.store = self.make_store()
                    origin = self.seed("A")
                    if role in ("S", "T"):
                        self.seed_stop(origin, terminal=True)
                        filename = stop_names(self.ref)[role]
                    else:
                        filename = names(self.ref)[role]
                    path = self.namespace / filename
                    if mutation == "hardlink":
                        os.link(path, self.namespace / "retained-hardlink")
                    elif mutation == "symlink":
                        moved = self.namespace / "retained-original"
                        path.rename(moved)
                        os.symlink(moved, path)
                    elif mutation == "mode":
                        path.chmod(0o640)
                    else:
                        value = json.loads(path.read_bytes())
                        if mutation == "duplicate":
                            raw = canonical(value)[:-1] + b',"schema":1}'
                        elif mutation == "bool_schema":
                            value["schema"] = True
                            raw = canonical(value)
                        elif mutation == "extra":
                            value["invented"] = 1
                            raw = canonical(value)
                        elif mutation == "nonfinite":
                            raw = b'{"schema":NaN}'
                        elif mutation == "utf8":
                            raw = b'\xff'
                        else:
                            raw = b" " * 4097
                        path.write_bytes(raw)
                    before = self.snapshot()
                    self.error("store_unavailable", lambda r=role: self.observe_stage(r))
                    self.assertEqual(before, self.snapshot())

    def test_each_stage_conflicting_committed_content_refuses(self):
        for role in ("C", "I_session", "I_native", "A", "S", "T"):
            with self.subTest(role=role), tempfile.TemporaryDirectory(dir=self.temp.name) as directory:
                self.namespace = Path(directory) / "bound"
                self.store = self.make_store()
                origin = self.seed("A")
                prepared, stop = self.seed_stop(origin, terminal=True)
                filename = stop_names(self.ref)[role] if role in ("S", "T") else names(self.ref)[role]
                path = self.namespace / filename
                value = json.loads(path.read_bytes())
                if role == "C" or role.startswith("I_"):
                    value["sid"] = OTHER_NATIVE
                elif role == "A":
                    value["parents"]["C"]["sha256"] = "b" * 64
                elif role == "T":
                    value["s_parent"]["ino"] += 1
                else:
                    value["host_id"] = SESSION_B
                    value["digest"] = digest({key: item for key, item in value.items() if key != "digest"})
                path.write_bytes(canonical(value))
                before = self.snapshot()
                self.error("store_unavailable", lambda r=role: self.observe_stage(r))
                if role in ("S", "T"):
                    self.error("store_unavailable", lambda: self.locked_call("publish_stop", prepared))
                    self.error("store_unavailable", lambda: self.locked_call("accept_stop", stop))
                else:
                    self.error("store_unavailable", lambda: self.locked_call("publish_origin", origin))
                    self.error("store_unavailable", lambda: self.locked_call("accept_create", origin))
                self.assertEqual(before, self.snapshot())

    def test_unknown_can_advance_null_roles_but_fresh_map_never_projects_fields(self):
        c = self.seed("C")
        parents = plain(c.parents)
        parents["C"] = None
        old_rg = self.dto.BoundCreateReceipt(c.record, "unknown", parents)
        self.assert_receipt(self.locked_call("capture_candidate", old_rg, NATIVE), c)
        observed = self.locked_call("publish_origin", old_rg)
        self.assertIsNotNone(observed.parents["C"])
        self.assertIsNotNone(observed.parents["I_session"])
        self.assertIsNotNone(observed.parents["I_native"])
        self.assertEqual(observed.record["created"], old_rg.record["created"])
        accepted = self.locked_call("accept_create", old_rg)
        self.assert_receipt(self.locked_call("accept_create", old_rg), accepted)

    def test_lookup_origin_root_mismatch_refuses_before_parent_access(self):
        origin = self.seed("I_session")
        # Leave only global locator; its root mismatch must win before absent R.
        for role in ("R", "G", "C"):
            (self.namespace / origin.parents[role]["filename"]).unlink()
        self.error("context_drift", lambda: self.locked_call("lookup_origin", "/synthetic/other", SESSION))

    def test_orphan_recognized_stage_names_never_become_absence(self):
        for filename in ("BC-bad.C.json", "BI-S-not-a-uuid.json", "BI-N-bad.json", "BS-bad.T.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(dir=self.temp.name) as directory:
                self.namespace = Path(directory) / "bound"
                self.store = self.make_store()
                self.write(filename, b"garbage")
                self.error("store_unavailable", self.lookup)
                self.error("store_unavailable", lambda: self.locked_call("lookup_origin", PROJECT_ROOT, SESSION))
                self.error("store_unavailable", lambda: self.locked_call("lookup_stop", PROJECT_ROOT, SESSION, STOP_OP))

    def test_overcapacity_stream_bounded_to_10001_retains_10002(self):
        self.namespace.mkdir(mode=0o700)
        for index in range(10002):
            self.write(f"retained-orphan-{index}", b"x")
        real_scandir = os.scandir
        observed = {"maximum": 0, "scans": 0}
        class Counting:
            def __init__(self, iterator):
                self.iterator, self.count = iterator, 0
            def __enter__(self):
                self.iterator.__enter__()
                return self
            def __exit__(self, *args):
                return self.iterator.__exit__(*args)
            def __iter__(self):
                return self
            def __next__(self):
                item = next(self.iterator)
                self.count += 1
                observed["maximum"] = max(observed["maximum"], self.count)
                return item
            def close(self):
                self.iterator.close()
        identity = self.namespace.stat()
        def scandir(path="."):
            iterator = real_scandir(path)
            if type(path) is int:
                info = os.fstat(path)
                is_namespace = (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino)
            else:
                is_namespace = Path(path) == self.namespace
            if is_namespace:
                observed["scans"] += 1
                return Counting(iterator)
            return iterator
        with mock.patch("os.scandir", side_effect=scandir), \
             mock.patch("os.listdir", side_effect=AssertionError("unbounded listdir")):
            for method, args in (("lookup_create", (PROJECT, PROJECT_ROOT, OP)),
                                 ("lookup_origin", (PROJECT_ROOT, SESSION)),
                                 ("lookup_stop", (PROJECT_ROOT, SESSION, STOP_OP))):
                self.error("store_unavailable", lambda m=method, a=args: self.locked_call(m, *a))
        self.assertGreater(observed["scans"], 0)
        self.assertLessEqual(observed["maximum"], 10001)
        self.assertEqual(len(list(self.namespace.iterdir())), 10002)

    def test_actual_namespace_flock_blocks_extension_with_original_deadline(self):
        receipt = self.seed("C")
        fd = os.open(self.namespace, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            outcomes = []
            def contender():
                store = self.module.BoundSessionStore(str(self.namespace), self.ref,
                    clock=self.wall, monotonic_clock=time.monotonic)
                deadline = time.monotonic() + 0.1
                try:
                    with store.locked(self.ref, deadline) as base:
                        store.publish_origin(base, self.ref, receipt, deadline)
                    outcomes.append("published")
                except self.catalog.AccountError as error:
                    outcomes.append(error.code)
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes, ["store_unavailable"])
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_complete_pure_receipts_do_not_invoke_native_effects(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("native launch/drain")), \
             mock.patch("subprocess.run", side_effect=AssertionError("native run")), \
             mock.patch("os.system", side_effect=AssertionError("native shell")):
            prepared_create = self.store.prepare_create(self.ref, PROJECT, PROJECT_ROOT, SESSION, OP, DEADLINE)
            rg = self.locked_call("publish_create", prepared_create)
            c = self.locked_call("capture_candidate", rg, NATIVE)
            both = self.locked_call("publish_origin", c)
            origin = self.locked_call("accept_create", both)
            # Invented host journal strings pass grammar only; no ownership or
            # drain boolean/proof field exists in this pure store's schema.
            prepared = self.store.prepare_stop(self.ref, origin, STOP_OP, HOST, INVOCATION, DEADLINE)
            stop = self.locked_call("publish_stop", prepared)
            terminal = self.locked_call("accept_stop", stop)
            self.assertEqual(terminal.status, "accepted")
            self.assertEqual(set(terminal.record), set(prepared.record))
            self.assertEqual(terminal.record["host_id"], HOST)
            self.assertEqual(terminal.record["invocation_id"], INVOCATION)

    def test_initial_i_pair_capacity_counts_each_permanent_and_transient(self):
        for free in (1, 2):
            with self.subTest(free=free), tempfile.TemporaryDirectory(dir=self.temp.name) as directory:
                self.namespace = Path(directory) / "bound"
                self.store = self.make_store()
                c = self.seed("C")
                count = len(list(self.namespace.iterdir()))
                for index in range(10000 - free - count):
                    self.write(f"retained-orphan-{index}", b"x")
                existing = self.snapshot()
                if free == 1:
                    self.error("store_unavailable", lambda: self.locked_call("publish_origin", c))
                    present = [role for role in ("I_session", "I_native")
                               if (self.namespace / names(self.ref)[role]).exists()]
                    # Either refusing the whole pair before writing, or retaining
                    # the first I on exhaustion is fail closed. No cleanup/repair.
                    self.assertLessEqual(len(present), 1)
                    self.assertFalse((self.namespace / names(self.ref)["A"]).exists())
                else:
                    both = self.locked_call("publish_origin", c)
                    self.assertEqual(both.status, "unknown")
                    self.assertTrue(both.parents["I_session"])
                    self.assertTrue(both.parents["I_native"])
                    self.assertEqual(len(list(self.namespace.iterdir())), 10000)
                now = self.snapshot()
                for filename, identity in existing.items():
                    self.assertEqual(now[filename], identity)
                self.assertLessEqual(len(now), 10002, "all retained uncertainty temps count")


def publication_fault_test(stage, fault):
    def test(self):
        method, arguments, target = self.next_stage(stage)
        original_cdll = ctypes.CDLL
        original_fsync = os.fsync
        original_monotonic_ns = time.monotonic_ns
        observed = {"renamed": False, "injected": False, "flags": []}

        class Rename:
            def __init__(self, function):
                self.function = function
            def __call__(self, oldfd, old, newfd, new, flags):
                destination = os.fsdecode(new)
                if destination == target:
                    observed["flags"].append(flags)
                result = self.function(oldfd, old, newfd, new, flags)
                if destination == target and result == 0:
                    observed["renamed"] = True
                    if fault == "rename_after":
                        observed["injected"] = True
                        raise OSError("synthetic uncertainty after actual rename")
                    if fault == "deadline_after":
                        observed["injected"] = True
                return result

            @property
            def argtypes(self):
                return self.function.argtypes

            @argtypes.setter
            def argtypes(self, value):
                self.function.argtypes = value

            @property
            def restype(self):
                return self.function.restype

            @restype.setter
            def restype(self, value):
                self.function.restype = value

        class Library:
            def __init__(self, library):
                self.library = library
                self.renameat2 = Rename(library.renameat2)
            def __getattr__(self, name):
                return getattr(self.library, name)

        def cdll(*args, **kwargs):
            return Library(original_cdll(*args, **kwargs))
        def fsync(fd):
            original_fsync(fd)
            if (fault == "fsync_after" and observed["renamed"]
                    and stat.S_ISDIR(os.fstat(fd).st_mode) and not observed["injected"]):
                observed["injected"] = True
                raise OSError("synthetic uncertainty after directory fsync")
        def monotonic_ns():
            # Exhaust the original ten-second budget even inside a callback-free
            # fence window; a fresh injected-clock sample is not required.
            offset = 11_000_000_000 if fault == "deadline_after" and observed["renamed"] else 0
            return original_monotonic_ns() + offset
        # Install the public libc seam before locked() obtains renameat2.
        with mock.patch("ctypes.CDLL", side_effect=cdll), \
             mock.patch("os.fsync", side_effect=fsync), \
             mock.patch("time.monotonic_ns", side_effect=monotonic_ns):
            self.error("store_unavailable", lambda: self.locked_call(method, *arguments))
        self.assertTrue(observed["renamed"], f"actual NOREPLACE rename of {stage} was not reached")
        self.assertTrue(observed["injected"], f"{fault} injection was not reached")
        self.assertTrue(observed["flags"])
        self.assertTrue(all(flag == 1 for flag in observed["flags"]), "Linux RENAME_NOREPLACE is required")
        self.assertTrue((self.namespace / target).exists(), "uncertain committed leaf must be retained")
        self.mono.value = 100.0
        before = self.snapshot()
        found = self.observe_stage(stage)
        self.assertEqual(found.status, "accepted" if stage in ("A", "T") else "unknown")
        role = stage
        self.assertEqual(plain(found.parents[role]), self.commit(target))
        self.assertEqual(before, self.snapshot(), "explicit re-observation must be read-only")
        self.assertEqual(self.wall.calls, 0)
    return test


def capacity_test(stage):
    def test(self):
        method, arguments, target = self.next_stage(stage)
        count = len(list(self.namespace.iterdir()))
        for index in range(9999 - count):
            self.write(f"retained-temp-orphan-{index}", b"x")
        maximum = {"entries": 0}
        real_open = os.open
        def opened(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            if flags & os.O_CREAT and flags & os.O_EXCL:
                maximum["entries"] = max(maximum["entries"], len(list(self.namespace.iterdir())))
            return fd
        with mock.patch("os.open", side_effect=opened):
            result = self.locked_call(method, *arguments)
        self.assertTrue((self.namespace / target).exists())
        self.assertEqual(len(list(self.namespace.iterdir())), 10000)
        self.assertLessEqual(maximum["entries"], 10002)
        before = self.snapshot()
        # Read-only replay remains possible at capacity, no extra transient.
        self.locked_call(method, *arguments)
        self.assertEqual(before, self.snapshot())
        self.write("retained-malformed-cap-witness", b"x")
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.observe_stage(stage))
        self.assertEqual(len(list(self.namespace.iterdir())), 10001)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(result.status, "accepted" if stage in ("A", "T") else "unknown")
    return test


def full_capacity_test(stage):
    def test(self):
        method, arguments, target = self.next_stage(stage)
        count = len(list(self.namespace.iterdir()))
        for index in range(10000 - count):
            self.write(f"retained-orphan-{index}", b"x")
        before = self.snapshot()
        self.error("store_unavailable", lambda: self.locked_call(method, *arguments))
        self.assertFalse((self.namespace / target).exists())
        self.assertEqual(before, self.snapshot(), "capacity refusal must precede temp creation")
    return test


def deadline_test(stage):
    def test(self):
        method, arguments, target = self.next_stage(stage)
        before = self.snapshot()
        with self.store.locked(self.ref, DEADLINE) as base:
            self.mono.value = DEADLINE
            self.error("store_unavailable", lambda: getattr(self.store, method)(base, self.ref, *arguments, DEADLINE))
            self.mono.value = 100.0
            # Enlarging the locked deadline is invalid, never a renewed budget.
            self.error("invalid_request", lambda: getattr(self.store, method)(base, self.ref, *arguments, DEADLINE + 1))
        self.assertFalse((self.namespace / target).exists())
        self.assertEqual(before, self.snapshot())
    return test


def pinned_inode_test(stage):
    def test(self):
        method, arguments, target = self.next_stage(stage)
        parent_role = "R" if stage == "C" else "C" if stage in ("I_session", "I_native", "A") else "A"
        parent = names(self.ref)[parent_role]
        original_open = os.open
        injected = {"done": False}
        raw = (self.namespace / parent).read_bytes()
        replacement = Path(self.temp.name) / "synthetic-inode-replacement"
        fd = original_open(replacement, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, raw)
        os.close(fd)
        original_inode = (self.namespace / parent).stat().st_ino
        before_fds = len(list(Path("/proc/self/fd").iterdir()))
        def open_and_replace(path, flags, *args, **kwargs):
            fd = original_open(path, flags, *args, **kwargs)
            if (not injected["done"] and not isinstance(path, int)
                    and os.path.basename(os.fsdecode(path)) == parent
                    and not flags & (os.O_WRONLY | os.O_RDWR)):
                # Preserve old held FD while replacing the pathname with equal
                # strict bytes: inode/ctime commitment must still fence it.
                os.replace(replacement, self.namespace / parent)
                injected["done"] = True
            return fd
        with mock.patch("os.open", side_effect=open_and_replace):
            self.error("store_unavailable", lambda: self.locked_call(method, *arguments))
        self.assertTrue(injected["done"], "held FD/path inode race not exercised")
        self.assertNotEqual((self.namespace / parent).stat().st_ino, original_inode)
        self.assertFalse((self.namespace / target).exists())
        self.assertEqual(len(list(Path("/proc/self/fd").iterdir())), before_fds,
                         "failed pinned read leaked FDs")
    return test


def callback_fence_test(stage):
    def test(self):
        method, arguments, target = self.next_stage(stage)
        parent_role = "R" if stage == "C" else "C" if stage in ("I_session", "I_native", "A") else "A"
        parent = names(self.ref)[parent_role]
        original_open = os.open
        state = {"opened": False, "injected": False, "callbacks": 0}
        def opened(path, flags, *args, **kwargs):
            fd = original_open(path, flags, *args, **kwargs)
            if not isinstance(path, int) and os.path.basename(os.fsdecode(path)) == parent:
                state["opened"] = True
            return fd
        def callback():
            state["callbacks"] += 1
            if state["opened"] and not state["injected"]:
                state["injected"] = True
                (self.namespace / parent).write_bytes(b"synthetic clock corruption")
        self.mono.callback = callback
        result = None
        with mock.patch("os.open", side_effect=opened):
            try:
                result = self.locked_call(method, *arguments)
            except self.catalog.AccountError as error:
                result = error
        self.mono.callback = None
        self.assertTrue(state["opened"])
        self.assertGreater(state["callbacks"], 0)
        if state["injected"]:
            self.assertIsInstance(result, self.catalog.AccountError)
            self.assertEqual(result.code, "store_unavailable")
            # Even when the target already renamed, never return an accepted
            # chain built from a parent corrupted by a callback.
            self.error("store_unavailable", lambda: self.observe_stage(stage))
        else:
            self.assertFalse(isinstance(result, self.catalog.AccountError))
            self.assertTrue((self.namespace / target).exists())
    return test


def noreplace_collision_test(stage):
    def test(self):
        method, arguments, target = self.next_stage(stage)
        original_cdll = ctypes.CDLL
        state = {"injected": False, "flags": None}
        sentinel = b"retained synthetic competing leaf"
        self_outer = self
        class Rename:
            def __init__(self, function):
                object.__setattr__(self, "function", function)
            def __setattr__(self, key, value):
                setattr(self.function, key, value)
            def __getattr__(self, key):
                return getattr(self.function, key)
            def __call__(self, oldfd, old, newfd, new, flags):
                if os.fsdecode(new) == target and not state["injected"]:
                    state["injected"] = True
                    state["flags"] = flags
                    self_outer.write(target, sentinel)
                return self.function(oldfd, old, newfd, new, flags)
        class Library:
            def __init__(self, library):
                self.library = library
                self.renameat2 = Rename(library.renameat2)
            def __getattr__(self, key):
                return getattr(self.library, key)
        with mock.patch("ctypes.CDLL", side_effect=lambda *a, **k: Library(original_cdll(*a, **k))):
            self.error("store_unavailable", lambda: self.locked_call(method, *arguments))
        self.assertTrue(state["injected"], "actual Linux collision was not exercised")
        self.assertEqual(state["flags"], 1)
        self.assertEqual((self.namespace / target).read_bytes(), sentinel,
                         "NOREPLACE must preserve the competing leaf")
        self.error("store_unavailable", lambda: self.observe_stage(stage))
    return test


def first_i_uncertainty_test(fault):
    def test(self):
        c = self.seed("C")
        targets = {names(self.ref)[role]: role for role in ("I_session", "I_native")}
        original_cdll, original_fsync = ctypes.CDLL, os.fsync
        original_ns = time.monotonic_ns
        state = {"target": None, "injected": False}
        class Rename:
            def __init__(self, function):
                object.__setattr__(self, "function", function)
            def __setattr__(self, key, value):
                setattr(self.function, key, value)
            def __getattr__(self, key):
                return getattr(self.function, key)
            def __call__(self, oldfd, old, newfd, new, flags):
                result = self.function(oldfd, old, newfd, new, flags)
                destination = os.fsdecode(new)
                if result == 0 and destination in targets and state["target"] is None:
                    state["target"] = destination
                    if fault == "rename_after":
                        state["injected"] = True
                        raise OSError("synthetic first I rename uncertainty")
                    if fault == "deadline_after":
                        state["injected"] = True
                return result
        class Library:
            def __init__(self, library):
                self.library = library
                self.renameat2 = Rename(library.renameat2)
            def __getattr__(self, key):
                return getattr(self.library, key)
        def fsync(fd):
            original_fsync(fd)
            if (fault == "fsync_after" and state["target"] is not None
                    and stat.S_ISDIR(os.fstat(fd).st_mode) and not state["injected"]):
                state["injected"] = True
                raise OSError("synthetic first I directory fsync uncertainty")
        def monotonic_ns():
            return original_ns() + (11_000_000_000 if fault == "deadline_after" and state["target"] else 0)
        with mock.patch("ctypes.CDLL", side_effect=lambda *a, **k: Library(original_cdll(*a, **k))), \
             mock.patch("os.fsync", side_effect=fsync), \
             mock.patch("time.monotonic_ns", side_effect=monotonic_ns):
            self.error("store_unavailable", lambda: self.locked_call("publish_origin", c))
        self.assertTrue(state["injected"])
        self.assertIsNotNone(state["target"])
        committed_role = targets[state["target"]]
        missing_role = "I_native" if committed_role == "I_session" else "I_session"
        self.assertFalse((self.namespace / names(self.ref)[missing_role]).exists())
        before = self.snapshot()
        found = self.lookup()
        self.assertEqual(found.status, "unknown")
        self.assertEqual(plain(found.parents[committed_role]), self.commit(state["target"]))
        self.assertIsNone(found.parents[missing_role])
        self.assertIsNone(found.parents["A"])
        located = self.locked_call("lookup_origin", PROJECT_ROOT, SESSION)
        if committed_role == "I_native":
            self.assertIsNone(located)
        else:
            self.assert_receipt(located, found)
        self.assertEqual(before, self.snapshot())
        recovered = self.locked_call("publish_origin", found)
        self.assertEqual(recovered.status, "unknown")
        self.assertTrue(recovered.parents[missing_role])
        self.assertIsNone(recovered.parents["A"])
        self.assertEqual(self.wall.calls, 0)
    return test


for _stage in ("C", "I_session", "I_native", "A", "S", "T"):
    for _fault in ("rename_after", "fsync_after", "deadline_after"):
        setattr(PublicationFaults, f"test_{_stage}_{_fault}_unknown_then_fenced_read",
                publication_fault_test(_stage, _fault))
    setattr(PublicationFaults, f"test_{_stage}_capacity_one_free_with_transient", capacity_test(_stage))
    setattr(PublicationFaults, f"test_{_stage}_full_capacity_no_temp", full_capacity_test(_stage))
    setattr(PublicationFaults, f"test_{_stage}_expiry_no_budget_renewal", deadline_test(_stage))
    setattr(PublicationFaults, f"test_{_stage}_pinned_fd_inode_no_leak", pinned_inode_test(_stage))
    setattr(PublicationFaults, f"test_{_stage}_clock_callback_final_fence", callback_fence_test(_stage))
    setattr(PublicationFaults, f"test_{_stage}_actual_noreplace_collision_retained", noreplace_collision_test(_stage))

for _fault in ("rename_after", "fsync_after", "deadline_after"):
    setattr(PublicationFaults, f"test_first_I_{_fault}_unknown_then_matching_recovery",
            first_i_uncertainty_test(_fault))


if __name__ == "__main__":
    unittest.main()
