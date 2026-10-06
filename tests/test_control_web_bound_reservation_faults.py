"""Independent Linux fault RED for the public R+G reservation store contract.

Only invented records in fresh private temporary directories are used. The tests
observe public operations and OS directory calls; they do not inspect store source.
"""

import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock


BIN = Path(__file__).resolve().parents[1] / "bin"
LINUX = sys.platform.startswith("linux")
OP = "123e4567-e89b-42d3-a456-426614174002"
SID = "123e4567-e89b-42d3-a456-426614174000"
PROJECT = "Control"
PROJECT_ROOT = "/synthetic/project"


def reference():
    return {
        "schema": 2, "provider_id": "codex", "account_id": "alpha",
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


def r_name(ref, operation):
    digest = hashlib.sha256(canonical({
        "context_ref": ref, "project": PROJECT,
        "root": PROJECT_ROOT, "operation_id": operation,
    })).hexdigest()
    return f"BC-{digest}.R.json"


class MutableClock:
    def __init__(self, value=100.0):
        self.value = value
        self.calls = 0
        self.callback = None

    def __call__(self):
        self.calls += 1
        if self.callback is not None:
            self.callback()
        return self.value


class ScandirCounter:
    """Preserve the real iterator while counting entries actually consumed."""

    def __init__(self, iterator, observed, clock=None, expire_after=None,
                 on_entry=None):
        self.iterator = iterator
        self.observed = observed
        self.clock = clock
        self.expire_after = expire_after
        self.on_entry = on_entry
        self.completed = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            entry = next(self.iterator)
        except StopIteration:
            self._complete()
            raise
        self.observed["entries"] += 1
        if self.clock is not None and self.observed["entries"] >= self.expire_after:
            self.clock.value = 111.0
        if self.on_entry is not None:
            self.on_entry(self.observed["entries"])
        return entry

    def _complete(self):
        if not self.completed:
            self.observed["completed"] += 1
            self.completed = True

    def __enter__(self):
        self.iterator.__enter__()
        return self

    def __exit__(self, *args):
        self._complete()
        return self.iterator.__exit__(*args)

    def close(self):
        return self.iterator.close()


@unittest.skipUnless(LINUX, "actual Linux anchored FD/scan behavior required")
class LinuxBoundReservationFaults(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(BIN))
        self.addCleanup(lambda: sys.path.remove(str(BIN)))
        self.module = importlib.import_module("_control_web_bound_session_store")
        self.catalog = importlib.import_module("_control_provider_accounts")
        self.ref = reference()
        self.clock = MutableClock()
        self.wall = lambda: 111
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-bound-fault-")
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name) / "selected"
        self.parent.mkdir(mode=0o700)
        self.namespace = self.parent / "bound"
        self.store = self.module.BoundSessionStore(
            str(self.namespace), self.ref, clock=self.wall,
            monotonic_clock=self.clock,
        )

    def unavailable(self, call):
        with self.assertRaises(self.catalog.AccountError) as caught:
            call()
        self.assertEqual(caught.exception.code, "store_unavailable")
        self.assertEqual(str(caught.exception), "store_unavailable")

    def prepare(self, operation=OP, session=SID):
        return self.store.prepare_create(
            self.ref, PROJECT, PROJECT_ROOT, session, operation, 110.0,
        )

    def write_leaf(self, name, data):
        self.namespace.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(self.namespace / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    def add_pair(self):
        operation = str(uuid.uuid4())
        session = str(uuid.uuid4())
        record = self.prepare(operation, session).record
        raw = canonical(record)
        name = r_name(self.ref, operation)
        self.write_leaf(name, raw)
        info = (self.namespace / name).stat()
        r_parent = {
            "filename": name, "dev": info.st_dev, "ino": info.st_ino,
            "ctime_ns": info.st_ctime_ns,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        g = {
            "schema": 1, "kind": "bound_session_reservation",
            "context_ref": self.ref, "project": PROJECT, "root": PROJECT_ROOT,
            "session_ref": session, "operation_id": operation,
            "r_parent": r_parent,
        }
        self.write_leaf(f"BG-S-{session}.json", canonical(g))

    def observe_namespace_iteration(self, *, clock=None, expire_after=None,
                                    on_entry=None, on_listdir=None):
        observed = {"entries": 0, "completed": 0, "listdir": 0, "scans": 0}
        raw_scandir = os.scandir
        raw_listdir = os.listdir
        identity = self.namespace.stat()

        def is_namespace(path):
            if type(path) is int:
                try:
                    item = os.fstat(path)
                    return (item.st_dev, item.st_ino) == (identity.st_dev, identity.st_ino)
                except OSError:
                    return False
            try:
                return Path(path) == self.namespace
            except (TypeError, ValueError):
                return False

        def scandir(path="."):
            iterator = raw_scandir(path)
            if is_namespace(path):
                observed["scans"] += 1
                return ScandirCounter(iterator, observed, clock, expire_after,
                                      on_entry)
            return iterator

        def listdir(path="."):
            if is_namespace(path):
                observed["listdir"] += 1
                if clock is not None:
                    clock.value = 111.0
                if on_listdir is not None:
                    on_listdir()
            return raw_listdir(path)

        return observed, mock.patch("os.scandir", side_effect=scandir), \
            mock.patch("os.listdir", side_effect=listdir)

    def test_absent_old_ancestor_cannot_return_none_after_clock_replacement(self):
        original_open = os.open
        replaced = {"done": False}
        moved = Path(self.temp.name) / "held-old-ancestor"
        original_clock = self.clock

        def open_and_change(path, *args, **kwargs):
            fd = original_open(path, *args, **kwargs)
            if not replaced["done"] and not isinstance(path, int):
                name = os.fsdecode(path)
                if name == "selected" or name.endswith("/selected"):
                    # A trusted clock callback runs just after the old ancestor
                    # has been opened, then the current path gains a namespace.
                    os.rename(self.parent, moved)
                    self.parent.mkdir(mode=0o700)
                    self.namespace.mkdir(mode=0o700)
                    replaced["done"] = True
                    original_clock()
            return fd

        def absent_lock():
            with self.store.locked(self.ref, 110.0, create=False):
                pass
        with mock.patch("os.open", side_effect=open_and_change):
            self.unavailable(absent_lock)
        self.assertTrue(replaced["done"], "ancestor replacement was not exercised")
        self.assertTrue(self.namespace.is_dir())

    def test_large_g_scan_expiry_refuses_absence_and_new_publication(self):
        for _ in range(80):
            self.add_pair()
        prepared = self.prepare()
        real_ns = time.monotonic_ns
        timer = {"baseline": False, "expired": False}

        def measured_ns():
            timer["baseline"] = True
            return real_ns() + (1_000_000_000 if timer["expired"] else 0)

        def advance_after_baseline(entries):
            if timer["baseline"] and entries >= 20:
                timer["expired"] = True

        def advance_listdir():
            if timer["baseline"]:
                timer["expired"] = True

        observed, scan_patch, list_patch = self.observe_namespace_iteration(
            on_entry=advance_after_baseline, on_listdir=advance_listdir)
        with self.store.locked(self.ref, 100.2) as base:
            with scan_patch, list_patch, mock.patch(
                    "time.monotonic_ns", side_effect=measured_ns):
                self.unavailable(lambda: self.store.lookup_create(
                    base, self.ref, PROJECT, PROJECT_ROOT, OP, 100.2))
        self.assertGreaterEqual(observed["entries"] + observed["listdir"], 1)
        self.assertTrue(timer["baseline"] and timer["expired"],
                        "callback-free final pass was not exercised")
        self.assertFalse((self.namespace / r_name(self.ref, OP)).exists())

        timer.update(baseline=False, expired=False)
        observed, scan_patch, list_patch = self.observe_namespace_iteration(
            on_entry=advance_after_baseline, on_listdir=advance_listdir)
        with self.store.locked(self.ref, 100.2) as base:
            with scan_patch, list_patch, mock.patch(
                    "time.monotonic_ns", side_effect=measured_ns):
                self.unavailable(lambda: self.store.publish_create(
                    base, self.ref, prepared, 100.2))
        self.assertGreaterEqual(observed["entries"] + observed["listdir"], 1)
        self.assertTrue(timer["baseline"] and timer["expired"])
        self.assertFalse((self.namespace / r_name(self.ref, OP)).exists())

    def test_replay_receipt_refuses_exact_deadline_at_leaf_fence(self):
        prepared = self.prepare()
        with self.store.locked(self.ref, 110.0, create=True) as base:
            receipt = self.store.publish_create(base, self.ref, prepared, 110.0)
        self.assertEqual(receipt.status, "unknown")
        original_open = os.open
        real_ns = time.monotonic_ns
        observed = {"g_open": False, "baseline": False, "expired": False}

        def measured_ns():
            observed["baseline"] = True
            return real_ns() + (1_000_000_000 if observed["expired"] else 0)

        def expire_after_g_open(path, *args, **kwargs):
            fd = original_open(path, *args, **kwargs)
            if not isinstance(path, int):
                name = os.fsdecode(path)
                if "BG-S-" in name and name.endswith(".json"):
                    observed["g_open"] = True
                    if observed["baseline"]:
                        observed["expired"] = True
            return fd

        with self.store.locked(self.ref, 101.0) as base:
            with mock.patch("os.open", side_effect=expire_after_g_open), \
                 mock.patch("time.monotonic_ns", side_effect=measured_ns):
                self.unavailable(lambda: self.store.lookup_create(
                    base, self.ref, PROJECT, PROJECT_ROOT, OP, 101.0))
        self.assertTrue(observed["g_open"] and observed["baseline"]
                        and observed["expired"], "terminal G fence was not exercised")
        self.assertEqual(len(list(self.namespace.iterdir())), 2)

    def test_over_capacity_scan_consumes_at_most_10001_physical_entries(self):
        self.namespace.mkdir(mode=0o700)
        for index in range(10002):
            self.write_leaf(f"orphan-{index:05d}", b"x")
        observed, scan_patch, list_patch = self.observe_namespace_iteration()
        def capped_lookup():
            with self.store.locked(self.ref, 110.0, create=False) as base:
                self.store.lookup_create(base, self.ref, PROJECT,
                                         PROJECT_ROOT, OP, 110.0)
        with scan_patch, list_patch:
            self.unavailable(capped_lookup)
        self.assertGreater(observed["scans"], 0)
        self.assertEqual(observed["listdir"], 0,
                         "listdir materializes an unbounded namespace")
        self.assertLessEqual(observed["entries"], 10001,
                             "scan consumed beyond the bounded capacity witness")
        self.assertEqual(len(list(self.namespace.iterdir())), 10002)

    def test_clock_adds_future_stage_after_temp_creation_before_r_publish(self):
        prepared = self.prepare()
        future_name = r_name(self.ref, OP).replace(".R.json", ".C.json")
        r_path = self.namespace / r_name(self.ref, OP)
        state = {"temp_seen": False, "injected": False}
        original_open = os.open

        def clock_callback():
            if (state["temp_seen"] and not state["injected"]
                    and observed["scans"] + observed["listdir"] > 0
                    and not r_path.exists()):
                state["injected"] = True
                self.write_leaf(future_name, b"invented-future-stage")

        def watch_temp(path, flags, *args, **kwargs):
            fd = original_open(path, flags, *args, **kwargs)
            if (not state["injected"] and not r_path.exists()
                    and flags & os.O_CREAT and flags & os.O_EXCL):
                state["temp_seen"] = True
            return fd

        with self.store.locked(self.ref, 110.0, create=True) as base:
            observed, scan_patch, list_patch = self.observe_namespace_iteration()
            self.clock.callback = clock_callback
            with scan_patch, list_patch, mock.patch("os.open", side_effect=watch_temp):
                self.unavailable(lambda: self.store.publish_create(
                    base, self.ref, prepared, 110.0))
        self.assertGreater(observed["scans"] + observed["listdir"], 0,
                           "pre-publication namespace listing was not exercised")
        self.assertTrue(state["temp_seen"], "temp publication stage was not observed")
        self.assertTrue(state["injected"], "clock did not inject the future stage")
        self.assertTrue((self.namespace / future_name).exists())
        self.assertFalse(r_path.exists(), "R became visible after a future stage appeared")

    def test_later_clock_mutates_earlier_pinned_g_before_absence_return(self):
        self.add_pair()
        self.add_pair()
        seen = []
        state = {"injected": False}
        original_open = os.open

        def clock_callback():
            if len(seen) >= 2 and not state["injected"]:
                state["injected"] = True
                first = self.namespace / seen[0]
                fd = original_open(first, os.O_WRONLY | os.O_TRUNC)
                try:
                    os.write(fd, b"invented-corruption-after-pin")
                    os.fsync(fd)
                finally:
                    os.close(fd)

        def observe_g(path, flags, *args, **kwargs):
            fd = original_open(path, flags, *args, **kwargs)
            if not isinstance(path, int):
                name = os.path.basename(os.fsdecode(path))
                if name.startswith("BG-S-") and name.endswith(".json"):
                    if name not in seen:
                        seen.append(name)
            return fd

        self.clock.callback = clock_callback
        with self.store.locked(self.ref, 110.0) as base:
            with mock.patch("os.open", side_effect=observe_g):
                self.unavailable(lambda: self.store.lookup_create(
                    base, self.ref, PROJECT, PROJECT_ROOT, OP, 110.0))
        self.assertGreaterEqual(len(seen), 2, "two distinct G leaves were not pinned")
        self.assertTrue(state["injected"], "later clock callback did not mutate G")
        self.assertFalse((self.namespace / r_name(self.ref, OP)).exists())


if __name__ == "__main__":
    unittest.main()
