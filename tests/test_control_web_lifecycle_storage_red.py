"""Independent synthetic RED for the public lifecycle receipt-store contract."""
import hashlib
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "_control_web_lifecycle.py"
_spec = (importlib.util.spec_from_file_location("_lifecycle_storage_red", MODULE_PATH)
         if MODULE_PATH.exists() else None)
_lifecycle = importlib.util.module_from_spec(_spec) if _spec else None
if _spec and _spec.loader:
    _spec.loader.exec_module(_lifecycle)
else:
    _lifecycle = None

try:
    from _control_web_sessions import _DomainError
except Exception:
    _DomainError = None

CONTEXT = "a" * 64
ROOT_PATH = "/var/tmp/lifecycle-project"
SID = "11111111-1111-4111-8111-111111111111"
OP = "22222222-2222-4222-8222-222222222222"


def deadline():
    return time.monotonic() + 8.0


def digest(context_id=CONTEXT, root=ROOT_PATH, sid=SID, action="unarchive",
           confirmation="restore_target"):
    payload = {"kind": "session_lifecycle", "context_id": context_id,
               "root": root, "sid": sid, "action": action,
               "confirmation": confirmation}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def prepared_record(**changes):
    record = {"schema": 1, "kind": "session_lifecycle", "context_id": CONTEXT,
              "root": ROOT_PATH, "sid": SID, "operation_id": OP,
              "action": "unarchive", "confirmation": "restore_target",
              "digest": digest(), "created": 1_800_000_000_000_000_000,
              "status": "unknown"}
    record.update(changes)
    return record


def json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def receipt_key(context_id=CONTEXT, root=ROOT_PATH, sid=SID, operation_id=OP):
    payload = {"kind": "session_lifecycle_key", "context_id": context_id,
               "root": root, "sid": sid, "operation_id": operation_id}
    return hashlib.sha256(json_bytes(payload)).hexdigest()


class LifecycleStorageRed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lifecycle-storage-red-", dir="/var/tmp"))
        self.tmp.chmod(0o700)
        self.store_path = self.tmp / "web-lifecycle-receipts"
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def types(self):
        self.assertIsNotNone(_lifecycle, "public lifecycle storage module should load")
        names = ("LifecycleStore", "LifecycleReservation", "PreparedLifecycle")
        missing = [name for name in names if not callable(getattr(_lifecycle, name, None))]
        self.assertEqual(missing, [], "lifecycle storage contract RED: missing public type(s): " +
                         ", ".join(missing))
        self.assertIsNotNone(_DomainError, "existing public domain error should be importable")
        return tuple(getattr(_lifecycle, name) for name in names)

    def store(self, clock=None):
        Store, _, _ = self.types()
        kwargs = {} if clock is None else {"clock": clock}
        return Store(str(self.store_path), **kwargs)

    def reserve(self, store, *, operation_id=OP, context_id=CONTEXT,
                root=ROOT_PATH, sid=SID, action="unarchive", confirmation="restore_target"):
        with store.locked(deadline(), create=True) as base:
            return store.reserve(base, context_id, root, sid, operation_id,
                                 action, confirmation, deadline())

    def assert_code(self, code, call):
        self.assertIsNotNone(_DomainError, "existing public domain error should be importable")
        with self.assertRaises(_DomainError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_constructor_is_lazy_and_dtos_copy_and_freeze_input(self):
        Store, Reservation, Prepared = self.types()
        store = Store(str(self.store_path), clock=lambda: 10)
        self.assertFalse(self.store_path.exists(), "constructor must not create/open namespace")
        raw = prepared_record()
        prepared = Prepared(raw)
        raw["action"] = "delete"
        self.assertEqual(prepared.record["action"], "unarchive")
        with self.assertRaises((TypeError, AttributeError)):
            prepared.record["action"] = "delete"
        self.assertIsNone(prepared.r_parent)
        self.assertEqual(prepared.record["status"], "unknown")
        reservation = Reservation(prepared.record, None)
        self.assertEqual(reservation.record["digest"], digest())
        self.assertFalse(self.store_path.exists())

    def test_prepare_validates_action_and_clock_once_before_filesystem_publication(self):
        calls = []
        def clock():
            calls.append("clock")
            return 1_800_000_000_000_000_000
        store = self.store(clock=clock)
        prepared = store.prepare_reservation(CONTEXT, ROOT_PATH, SID, OP,
                                             "unarchive", "restore_target", deadline())
        self.assertEqual(calls, ["clock"])
        self.assertEqual(prepared.record["created"], 1_800_000_000_000_000_000)
        self.assertFalse(self.store_path.exists(), "prepare does not reserve storage")
        for action, confirmation in (("archive", "cascade_archive"),
                                     ("delete", "cascade_delete")):
            self.assert_code("invalid_request", lambda a=action, c=confirmation:
                store.prepare_reservation(CONTEXT, ROOT_PATH, SID, OP, a, c, deadline()))
        for value in (True, 0, -1, 2**63):
            bad = self.store(clock=lambda v=value: v)
            self.assert_code("invalid_request", lambda b=bad:
                b.prepare_reservation(CONTEXT, ROOT_PATH, SID, OP,
                                      "unarchive", "restore_target", deadline()))
        exhausted = deadline() - 9.0
        self.assert_code("unavailable", lambda:
            store.prepare_reservation(CONTEXT, ROOT_PATH, SID, OP,
                                      "unarchive", "restore_target", exhausted))

    def test_absent_lookup_is_lazy_and_does_not_create_namespace_or_lockfile(self):
        store = self.store()
        with store.locked(deadline(), create=False) as base:
            self.assertIsNone(base)
            self.assertIsNone(store.lookup(base, CONTEXT, ROOT_PATH, SID, OP, deadline()))
        self.assertFalse(self.store_path.exists())

    def test_reserve_replay_is_once_only_and_identity_isolated(self):
        calls = []
        store = self.store(clock=lambda: calls.append(1) or 123456789)
        first = self.reserve(store)
        self.assertEqual(first.record["status"], "unknown")
        self.assertEqual(calls, [1])
        replay = self.reserve(store)
        self.assertEqual(replay.record, first.record)
        self.assertEqual(replay.r_parent, first.r_parent)
        self.assertEqual(calls, [1], "replay returns prior created time without clock")
        self.assert_code("invalid_request", lambda: self.reserve(
            store, operation_id=OP, confirmation="different"))
        with store.locked(deadline(), create=False) as base:
            self.assertIsNone(store.lookup(base, "b" * 64, ROOT_PATH, SID, OP, deadline()))
            self.assertIsNone(store.lookup(base, CONTEXT, "/var/tmp/other-project", SID, OP, deadline()))
            self.assertIsNone(store.lookup(base, CONTEXT, ROOT_PATH,
                                           "33333333-3333-4333-8333-333333333333", OP, deadline()))
            self.assertIsNone(store.lookup(base, CONTEXT, ROOT_PATH, SID,
                                           "44444444-4444-4444-8444-444444444444", deadline()))
        self.assertEqual(calls, [1])

    def test_accept_is_bound_to_exact_parent_and_known_acceptance_never_republishes(self):
        calls = []
        store = self.store(clock=lambda: calls.append(1) or 123456789)
        unknown = self.reserve(store)
        with store.locked(deadline(), create=False) as base:
            accepted = store.accept(base, unknown, deadline())
            self.assertEqual(accepted.record["status"], "accepted")
            replay = store.accept(base, accepted, deadline())
            self.assertEqual(replay.record, accepted.record)
            self.assertEqual(replay.r_parent, accepted.r_parent)
        self.assertEqual(calls, [1])
        r_name = "L-" + receipt_key() + ".R.json"
        a_name = "L-" + receipt_key() + ".A.json"
        a_path = self.store_path / a_name
        corrupted = json.loads(a_path.read_text(encoding="utf-8"))
        corrupted["parent"]["sha256"] = "0" * 64
        a_path.write_bytes(json_bytes(corrupted)); a_path.chmod(0o600)
        with store.locked(deadline(), create=False) as base:
            self.assert_code("unavailable", lambda: store.lookup(base, CONTEXT, ROOT_PATH,
                                                                  SID, OP, deadline()))
            self.assert_code("unavailable", lambda: store.accept(base, accepted, deadline()))
        a_path.unlink()
        with store.locked(deadline(), create=False) as base:
            self.assert_code("unavailable", lambda: store.accept(base, accepted, deadline()))
        self.assertTrue((self.store_path / r_name).exists())
        self.assertFalse((self.store_path / a_name).exists(), "known accepted state is never republished")

    def test_malformed_or_orphan_receipts_never_look_absent(self):
        store = self.store()
        # A without its matching R is corruption, not a cache miss.
        key = receipt_key()
        orphan_a = self.store_path / ("L-" + key + ".A.json")
        with store.locked(deadline(), create=True):
            orphan_a.write_text("{}", encoding="utf-8")
            orphan_a.chmod(0o600)
        with store.locked(deadline(), create=False) as base:
            self.assert_code("unavailable", lambda: store.lookup(base, CONTEXT, ROOT_PATH,
                                                                  SID, OP, deadline()))
        # Duplicate keys and non-finite constants in an existing R are invalid.
        self.store_path.unlink(missing_ok=True) if self.store_path.is_symlink() else None
        shutil.rmtree(self.store_path)
        self.store_path.mkdir(mode=0o700)
        r_path = self.store_path / ("L-" + key + ".R.json")
        valid = json_bytes(prepared_record()).decode("utf-8")
        for raw in (valid[:-1] + ',"status":"accepted"}',
                    valid[:-1] + ',"unused":NaN}'):
            r_path.write_text(raw, encoding="utf-8")
            r_path.chmod(0o600)
            with store.locked(deadline(), create=False) as base:
                self.assert_code("unavailable", lambda: store.lookup(base, CONTEXT,
                    ROOT_PATH, SID, OP, deadline()))

    def test_metadata_permissions_symlink_linkcount_and_namespace_replacement_fail_closed(self):
        store = self.store()
        self.reserve(store)
        path = self.store_path / ("L-" + receipt_key() + ".R.json")
        original = path.read_bytes()
        path.chmod(0o622)
        with store.locked(deadline(), create=False) as base:
            self.assert_code("unavailable", lambda: store.lookup(base, CONTEXT, ROOT_PATH,
                                                                  SID, OP, deadline()))
        path.chmod(0o600)
        link = self.tmp / "outside-link"
        os.link(path, link)
        with store.locked(deadline(), create=False) as base:
            self.assert_code("unavailable", lambda: store.lookup(base, CONTEXT, ROOT_PATH,
                                                                  SID, OP, deadline()))
        link.unlink()
        path.unlink()
        target = self.tmp / "outside-target"
        target.write_bytes(original); target.chmod(0o600)
        path.symlink_to(target)
        with store.locked(deadline(), create=False) as base:
            self.assert_code("unavailable", lambda: store.lookup(base, CONTEXT, ROOT_PATH,
                                                                  SID, OP, deadline()))
        path.unlink()
        self.reserve(store)
        with store.locked(deadline(), create=False) as base:
            moved = self.tmp / "moved-namespace"
            os.replace(self.store_path, moved)
            self.store_path.mkdir(mode=0o700)
            self.assert_code("unavailable", lambda: store.lookup(base, CONTEXT, ROOT_PATH,
                                                                  SID, OP, deadline()))

    def test_orphan_capacity_is_bounded_and_archive_delete_never_publish(self):
        store = self.store(clock=lambda: 123456789)
        for action, confirmation in (("archive", "cascade_archive"),
                                     ("delete", "cascade_delete")):
            self.assert_code("invalid_request", lambda a=action, c=confirmation:
                store.prepare_reservation(CONTEXT, ROOT_PATH, SID, OP, a, c, deadline()))
        self.assertFalse(self.store_path.exists())
        with store.locked(deadline(), create=True):
            for i in range(10003):
                (self.store_path / (".tmp-" + format(i, "032x"))).touch(mode=0o600)
        with store.locked(deadline(), create=False) as base:
            self.assert_code("unavailable", lambda: store.reserve(base, CONTEXT, ROOT_PATH,
                SID, OP, "unarchive", "restore_target", deadline()))
        self.assertEqual(len(list(self.store_path.iterdir())), 10003,
                         "unknown/temp entries count toward capacity and are retained")

    def test_closed_yielded_fd_reused_for_same_directory_is_not_a_live_lock(self):
        clock_calls = []
        store = self.store(clock=lambda: clock_calls.append("clock") or 123456789)
        probe_locked = False
        looked_up = reserved = None
        before = after = None
        with store.locked(deadline(), create=True) as base:
            yielded_fd = base
            os.close(yielded_fd)
            replacement = os.open(self.store_path, os.O_RDONLY | os.O_DIRECTORY)
            if replacement != yielded_fd:
                os.dup2(replacement, yielded_fd)
                os.close(replacement)
            self.assertEqual(os.fstat(yielded_fd).st_ino, self.store_path.stat().st_ino)

            probe_fd = os.open(self.store_path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                try:
                    fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    probe_locked = True
                except BlockingIOError:
                    pass
                before = sorted(path.name for path in self.store_path.iterdir())

                def outcome(call):
                    try:
                        return call()
                    except _DomainError as error:
                        return "error:" + error.code

                looked_up = outcome(lambda: store.lookup(
                    yielded_fd, CONTEXT, ROOT_PATH, SID, OP, deadline()))
                reserved = outcome(lambda: store.reserve(
                    yielded_fd, CONTEXT, ROOT_PATH, SID, OP,
                    "unarchive", "restore_target", deadline()))
                after = sorted(path.name for path in self.store_path.iterdir())
            finally:
                if probe_locked:
                    fcntl.flock(probe_fd, fcntl.LOCK_UN)
                os.close(probe_fd)
        self.assertTrue(probe_locked,
                        "closed yielded FD must release its namespace flock")
        observed = (looked_up,
                    "error:" + reserved if isinstance(reserved, str) and reserved.startswith("error:")
                    else type(reserved).__name__,
                    after == before, len(clock_calls))
        self.assertEqual(observed, ("error:unavailable", "error:unavailable", True, 0),
                         "same-thread/same-inode FD reuse must fail closed before lookup, "
                         "reservation publication, or clock sampling")


if __name__ == "__main__":
    unittest.main()
