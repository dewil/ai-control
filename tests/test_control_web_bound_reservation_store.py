"""Blind RED for the first bound R+G reservation store.

All disk fixtures are invented private temporary namespaces. No auth, native,
provider, registered project, or server capability is exercised by these tests.
"""

import copy
import fcntl
import hashlib
import importlib
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


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
MODULE = BIN / "_control_web_bound_session_store.py"
LINUX = sys.platform.startswith("linux")
SID_A = "123e4567-e89b-42d3-a456-426614174000"
SID_B = "123e4567-e89b-42d3-a456-426614174001"
OP_A = "123e4567-e89b-42d3-a456-426614174002"
OP_B = "123e4567-e89b-42d3-a456-426614174003"
ROOT_PATH = "/synthetic/project"


def ref(account="alpha"):
    return {
        "schema": 2,
        "provider_id": "codex",
        "account_id": account,
        "profile_instance_id": "123e4567-e89b-42d3-a456-426614174004",
        "adapter_revision": "codex-chatgpt-external-auth-host-v2",
        "registration_snapshot": {
            "dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "a" * 64,
        },
    }


def plain(value):
    if hasattr(value, "items"):
        return {key: plain(item) for key, item in value.items()}
    return value


def canonical(value):
    return json.dumps(plain(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def r_name(reference, project="Control", root=ROOT_PATH, operation=OP_A):
    key = hashlib.sha256(canonical({
        "context_ref": reference, "project": project,
        "root": root, "operation_id": operation,
    })).hexdigest()
    return f"BC-{key}.R.json"


def g_name(session_ref=SID_A):
    return f"BG-S-{session_ref}.json"


class Clock:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class BoundReservationContract(unittest.TestCase):
    def setUp(self):
        # All tests fail as assertions while the source module is absent.
        self.assertTrue(MODULE.is_file(), f"contract module unavailable: {MODULE.name}")
        sys.path.insert(0, str(BIN))
        self.addCleanup(lambda: sys.path.remove(str(BIN)))
        self.store_module = importlib.import_module("_control_web_bound_session_store")
        self.records = importlib.import_module("_control_web_bound_session_records")
        self.catalog = importlib.import_module("_control_provider_accounts")
        self.reference = ref()
        self.wall = Clock(111)
        self.mono = Clock(100.0)

    def make_store(self, path="/synthetic/private/bound", reference=None,
                   wall=None, mono=None):
        return self.store_module.BoundSessionStore(
            str(path), self.reference if reference is None else reference,
            clock=self.wall if wall is None else wall,
            monotonic_clock=self.mono if mono is None else mono,
        )

    def prepare(self, store, reference=None, project="Control", root=ROOT_PATH,
                session=SID_A, operation=OP_A, deadline=110.0):
        return store.prepare_create(
            self.reference if reference is None else reference,
            project, root, session, operation, deadline,
        )

    def rejects(self, code, call):
        with self.assertRaises(self.catalog.AccountError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)
        self.assertNotIn("/synthetic", repr(caught.exception))

    def test_constructor_and_prepare_are_portable_pure_and_single_sample(self):
        with mock.patch("os.open", side_effect=AssertionError("os.open")), \
             mock.patch("builtins.open", side_effect=AssertionError("open")), \
             mock.patch("os.stat", side_effect=AssertionError("stat")):
            store = self.make_store()
            self.assertEqual((self.wall.calls, self.mono.calls), (0, 0))
            prepared = self.prepare(store)
        self.assertIsInstance(prepared, self.records.PreparedBoundCreate)
        self.assertEqual(prepared.record["created"], 111)
        self.assertEqual(self.wall.calls, 1)
        self.assertGreaterEqual(self.mono.calls, 1)
        self.assertFalse(hasattr(prepared, "parents"))

    def test_fullref_first_deep_capture_and_safe_errors(self):
        store = self.make_store()
        captured = copy.deepcopy(self.reference)
        self.reference["registration_snapshot"]["sha256"] = "b" * 64
        with mock.patch("os.open", side_effect=AssertionError("os.open")):
            self.rejects("context_drift", lambda: self.prepare(store))
            self.rejects("context_invalid", lambda: store.prepare_create(
                {"bad": 1}, "bad", "relative", "bad", "bad", 110.0))
            self.rejects("context_drift", lambda: store.prepare_create(
                ref("beta"), "bad", "relative", "bad", "bad", 110.0))
        self.prepare(store, reference=captured)
        self.assertEqual(self.wall.calls, 1)
        self.assertEqual(plain(captured)["account_id"], "alpha")

    def test_constructor_path_and_prepare_input_rules(self):
        for path in ("relative/path", "/trailing/", "/double//part", "/dot/./part",
                     "/bad\x00part", "/bad\ud800"):
            self.rejects("invalid_request", lambda p=path: self.make_store(p))
        store = self.make_store()
        self.rejects("invalid_request", lambda: self.prepare(store, project="bad space"))
        self.rejects("invalid_request", lambda: self.prepare(store, session="not-uuid"))
        self.rejects("invalid_request", lambda: self.prepare(store, deadline=True))
        self.rejects("store_unavailable", lambda: self.prepare(store, deadline=99.0))
        self.assertEqual(self.wall.calls, 0)
        self.wall.value = True
        self.rejects("invalid_request", lambda: self.prepare(store))
        self.assertEqual(self.wall.calls, 1)

    def test_raw_base_and_unsupported_platform_are_closed_before_io(self):
        store = self.make_store()
        with mock.patch("os.open", side_effect=AssertionError("os.open")):
            with self.assertRaises(self.catalog.AccountError) as caught:
                store.lookup_create(object(), self.reference, "Control", ROOT_PATH,
                                    OP_A, 110.0)
            self.assertIn(caught.exception.code,
                          ("invalid_request", "store_unavailable"))
            self.rejects("context_drift", lambda: store.lookup_create(
                object(), ref("beta"), "Control", ROOT_PATH, OP_A, 110.0))
            if not LINUX:
                self.rejects("store_unavailable", lambda: store.locked(
                    self.reference, 110.0, create=False).__enter__())


@unittest.skipUnless(LINUX, "actual Linux renameat2/FD/flock behavior required")
class LinuxBoundReservationContract(BoundReservationContract):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-bound-store-")
        self.addCleanup(self.temp.cleanup)
        self.namespace = Path(self.temp.name) / "bound"
        self.store = self.make_store(self.namespace)

    def fresh(self, store=None, reference=None):
        return self.prepare(self.store if store is None else store, reference=reference)

    def publish(self, prepared=None, store=None, reference=None):
        store = self.store if store is None else store
        reference = self.reference if reference is None else reference
        prepared = self.fresh(store, reference) if prepared is None else prepared
        with store.locked(reference, 110.0, create=True) as base:
            return store.publish_create(base, reference, prepared, 110.0)

    def leaf(self, name, data):
        self.namespace.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(self.namespace / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    def test_absent_namespace_and_successful_r_g_are_exact_private_leaves(self):
        with self.store.locked(self.reference, 110.0, create=False) as base:
            self.assertIsNone(base)
            self.assertIsNone(self.store.lookup_create(
                base, self.reference, "Control", ROOT_PATH, OP_A, 110.0))
            self.rejects("store_unavailable", lambda: self.store.publish_create(
                base, self.reference, self.fresh(), 110.0))
        prepared = self.fresh()
        receipt = self.publish(prepared)
        self.assertEqual(receipt.status, "unknown")
        self.assertEqual(set(receipt.parents),
                         {"R", "G", "C", "I_session", "I_native", "A"})
        self.assertEqual({key for key, item in receipt.parents.items() if item},
                         {"R", "G"})
        self.assertEqual({p.name for p in self.namespace.iterdir()},
                         {r_name(self.reference), g_name()})
        self.assertEqual(stat.S_IMODE(self.namespace.stat().st_mode), 0o700)
        for path in self.namespace.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_nlink, 1)
        raw_r = (self.namespace / r_name(self.reference)).read_bytes()
        raw_g = (self.namespace / g_name()).read_bytes()
        self.assertEqual(json.loads(raw_r), plain(prepared.record))
        g = json.loads(raw_g)
        self.assertEqual(set(g), {"schema", "kind", "context_ref", "project", "root",
                                  "session_ref", "operation_id", "r_parent"})
        self.assertEqual(g["kind"], "bound_session_reservation")
        self.assertEqual(g["r_parent"], plain(receipt.parents["R"]))
        self.assertEqual(receipt.parents["R"]["sha256"], hashlib.sha256(raw_r).hexdigest())
        self.assertEqual(receipt.parents["G"]["sha256"], hashlib.sha256(raw_g).hexdigest())

    def test_exact_replay_preserves_inodes_and_created_and_lookup_no_clock(self):
        prepared = self.fresh()
        receipt = self.publish(prepared)
        before = {p.name: (p.stat().st_ino, p.stat().st_ctime_ns, p.read_bytes())
                  for p in self.namespace.iterdir()}
        wall_calls = self.wall.calls
        with self.store.locked(self.reference, 110.0) as base:
            found = self.store.lookup_create(base, self.reference, "Control", ROOT_PATH,
                                             OP_A, 110.0)
            replay = self.store.publish_create(base, self.reference, prepared, 110.0)
        self.assertEqual(self.wall.calls, wall_calls)
        self.assertEqual(plain(found.record), plain(receipt.record))
        self.assertEqual(plain(replay.record), plain(receipt.record))
        self.assertEqual(before, {p.name: (p.stat().st_ino, p.stat().st_ctime_ns,
                                            p.read_bytes()) for p in self.namespace.iterdir()})
        self.wall.value = 112
        changed_created = self.fresh()
        self.rejects("store_unavailable", lambda: self.publish(changed_created))
        self.assertEqual(before, {p.name: (p.stat().st_ino, p.stat().st_ctime_ns,
                                            p.read_bytes()) for p in self.namespace.iterdir()})

    def test_global_uuid_collision_across_accounts_cannot_create_second_r(self):
        self.publish()
        beta = ref("beta")
        other = self.make_store(self.namespace, reference=beta,
                                wall=Clock(112), mono=self.mono)
        prepared = self.prepare(other, reference=beta, operation=OP_B)
        self.rejects("store_unavailable", lambda: self.publish(
            prepared, store=other, reference=beta))
        self.assertFalse((self.namespace / r_name(beta, operation=OP_B)).exists())
        self.assertEqual(len(list(self.namespace.iterdir())), 2)

    def test_r_only_and_g_only_history_refuse_new_session_uuid(self):
        prepared = self.fresh()
        self.leaf(r_name(self.reference), canonical(prepared.record))
        with self.store.locked(self.reference, 110.0) as base:
            self.rejects("store_unavailable", lambda: self.store.lookup_create(
                base, self.reference, "Control", ROOT_PATH, OP_A, 110.0))
            self.rejects("store_unavailable", lambda: self.store.publish_create(
                base, self.reference, prepared, 110.0))
        changed_uuid = self.prepare(self.store, session=SID_B)
        self.rejects("store_unavailable", lambda: self.publish(changed_uuid))
        self.assertFalse((self.namespace / g_name()).exists())
        # Independently valid G identity referring to a missing R. Its operation
        # must remain unavailable even when a new session UUID is proposed.
        (self.namespace / r_name(self.reference)).unlink()
        r_parent = {"filename": r_name(self.reference), "dev": 1, "ino": 1,
                    "ctime_ns": 1,
                    "sha256": hashlib.sha256(canonical(prepared.record)).hexdigest()}
        g = {"schema": 1, "kind": "bound_session_reservation",
             "context_ref": self.reference, "project": "Control", "root": ROOT_PATH,
             "session_ref": SID_A, "operation_id": OP_A, "r_parent": r_parent}
        self.leaf(g_name(), canonical(g))
        with self.store.locked(self.reference, 110.0) as base:
            self.rejects("store_unavailable", lambda: self.store.lookup_create(
                base, self.reference, "Control", ROOT_PATH, OP_A, 110.0))
        proposed = self.prepare(self.store, session=SID_B)
        self.rejects("store_unavailable", lambda: self.publish(proposed))
        self.assertFalse((self.namespace / r_name(self.reference)).exists())

    def test_malformed_g_and_future_stage_names_refuse_absence(self):
        self.leaf(g_name(), b'{"schema":1,"schema":1}')
        with self.store.locked(self.reference, 110.0) as base:
            self.rejects("store_unavailable", lambda: self.store.lookup_create(
                base, self.reference, "Control", ROOT_PATH, OP_A, 110.0))
        (self.namespace / g_name()).unlink()
        self.leaf("BC-uncertain.C.json", b"garbage")
        with self.store.locked(self.reference, 110.0) as base:
            self.rejects("store_unavailable", lambda: self.store.lookup_create(
                base, self.reference, "Control", ROOT_PATH, OP_A, 110.0))
        self.rejects("store_unavailable", lambda: self.publish())
        self.assertFalse((self.namespace / r_name(self.reference)).exists())

    def test_leaf_corruption_and_hardlink_are_not_replayed(self):
        self.publish()
        original = self.namespace / r_name(self.reference)
        link = self.namespace / "synthetic-hardlink"
        os.link(original, link)
        with self.store.locked(self.reference, 110.0) as base:
            self.rejects("store_unavailable", lambda: self.store.lookup_create(
                base, self.reference, "Control", ROOT_PATH, OP_A, 110.0))
        link.unlink()
        g = self.namespace / g_name()
        with g.open("wb") as out:
            out.write(b'{"schema":1,"schema":1}')
        with self.store.locked(self.reference, 110.0) as base:
            self.rejects("store_unavailable", lambda: self.store.lookup_create(
                base, self.reference, "Control", ROOT_PATH, OP_A, 110.0))

    def test_g_parent_must_match_fresh_r(self):
        self.publish()
        g_path = self.namespace / g_name()
        g = json.loads(g_path.read_bytes())
        g["r_parent"]["sha256"] = "b" * 64
        g_path.write_bytes(canonical(g))
        with self.store.locked(self.reference, 110.0) as base:
            self.rejects("store_unavailable", lambda: self.store.lookup_create(
                base, self.reference, "Control", ROOT_PATH, OP_A, 110.0))

    def test_symlink_namespace_refuses_without_publication(self):
        other = Path(self.temp.name) / "another-name"
        other.mkdir(mode=0o700)
        os.symlink(other, self.namespace, target_is_directory=True)
        self.rejects("store_unavailable", lambda: self.publish())
        self.assertEqual(list(other.iterdir()), [])

    def test_capacity_9998_boundary_and_orphans_count(self):
        self.namespace.mkdir(mode=0o700)
        for index in range(9998):
            self.leaf(f"orphan-{index:05d}", b"x")
        receipt = self.publish()
        self.assertEqual(receipt.status, "unknown")
        self.assertEqual(len(list(self.namespace.iterdir())), 10000)
        # A second operation needs two permanent slots and must fail before R.
        prepared = self.prepare(self.store, session=SID_B, operation=OP_B)
        self.rejects("store_unavailable", lambda: self.publish(prepared))
        self.assertFalse((self.namespace / r_name(self.reference, operation=OP_B)).exists())

    def test_active_base_thread_lifetime_and_path_replacement_fences(self):
        self.namespace.mkdir(mode=0o700)
        with self.store.locked(self.reference, 110.0) as base:
            self.assertFalse(hasattr(base, "fileno"))
            self.assertFalse(hasattr(base, "fd"))
            self.assertFalse(hasattr(base, "__dict__"))
            codes = []
            def other_thread():
                try:
                    self.store.lookup_create(base, self.reference, "Control", ROOT_PATH,
                                             OP_A, 110.0)
                except self.catalog.AccountError as error:
                    codes.append(error.code)
            thread = threading.Thread(target=other_thread)
            thread.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(codes), 1)
            moved = self.namespace.with_name("bound-moved")
            os.rename(self.namespace, moved)
            self.namespace.mkdir(mode=0o700)
            self.rejects("store_unavailable", lambda: self.store.publish_create(
                base, self.reference, self.fresh(), 110.0))
        with self.assertRaises(self.catalog.AccountError):
            self.store.lookup_create(base, self.reference, "Control", ROOT_PATH,
                                     OP_A, 110.0)
        self.assertFalse((self.namespace / r_name(self.reference)).exists())

    def test_flock_busy_has_bounded_shared_deadline(self):
        self.namespace.mkdir(mode=0o700)
        fd = os.open(self.namespace, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(lambda: os.close(fd))
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(lambda: fcntl.flock(fd, fcntl.LOCK_UN))
        # Separate thread means the OS lock conflicts even within this process.
        outcome = []
        def contend():
            try:
                with self.store_module.BoundSessionStore(
                    str(self.namespace), self.reference, clock=Clock(111),
                    monotonic_clock=time.monotonic,
                ).locked(self.reference, time.monotonic() + 0.2):
                    outcome.append("entered")
            except self.catalog.AccountError as error:
                outcome.append(error.code)
        thread = threading.Thread(target=contend)
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, ["store_unavailable"])


if __name__ == "__main__":
    unittest.main()
