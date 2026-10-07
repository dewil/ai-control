"""Blind DeviceGrantStore tests derived solely from the public auth spec.

All capabilities below are synthetic test data; no live auth storage is used.
Target violations: idle sliding on background/valid calls, lost revoke on reopen
or concurrent renewal, plaintext persistence, and unsafe storage admission.
"""
import concurrent.futures
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400
WEEK = 7 * DAY
MONTH = 30 * DAY


def load_store():
    path = ROOT / 'bin' / '_control_web_android_auth.py'
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DeviceGrantStore


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


# INV-AUTHAND-02 INV-AUTHAND-03 INV-AUTHAND-04 INV-AUTHAND-05 INV-AUTHAND-06
class DeviceGrantStoreContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='android-auth-contract-')
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.parent.chmod(0o700)
        self.path = self.parent / 'grants.sqlite3'
        self.clock = Clock()
        self.Store = load_store()
        self._store = None

    @property
    def store(self):
        if self._store is None:
            self._store = self.Store(self.path, self.clock)
        return self._store

    def issued(self, store=None):
        store = store or self.store
        token = store.issue()
        self.assertIsInstance(token, str)
        self.assertTrue(token, 'issue must return a nonempty opaque capability')
        device = store.admit(token, foreground_open=False)
        self.assertIsInstance(device, str, 'new token must admit a device')
        self.assertEqual(str(uuid.UUID(device)), device)
        self.assertTrue(store.valid(device))
        return token, device

    def test_issue_unique_tokens_and_independent_device_identities(self):
        records = [self.issued() for _ in range(24)]
        self.assertEqual(len({token for token, _ in records}), 24)
        self.assertEqual(len({device for _, device in records}), 24)
        for token, device in records:
            self.assertNotEqual(token, device)

    def test_persistence_reopen_preserves_identity_and_idle_deadline(self):
        token, device = self.issued()
        self.clock.now += WEEK - 1
        reopened = self.Store(self.path, self.clock)
        self.assertEqual(reopened.admit(token, foreground_open=False), device)
        self.assertTrue(reopened.valid(device))
        self.clock.now += 1
        self.assertIsNone(reopened.admit(token, foreground_open=False))
        self.assertFalse(reopened.valid(device))

    def test_exact_idle_boundary_denies_foreground_and_cannot_resurrect(self):
        token, device = self.issued()
        self.clock.now += WEEK - .001
        self.assertEqual(self.store.admit(token, foreground_open=False), device)
        self.clock.now += .001
        self.assertIsNone(self.store.admit(token, foreground_open=True))
        self.assertFalse(self.store.valid(device))
        self.clock.now += DAY
        self.assertIsNone(self.store.admit(token, foreground_open=True))

    def test_foreground_open_moves_idle_deadline_without_token_rotation(self):
        token, device = self.issued()
        self.clock.now += 6 * DAY
        self.assertEqual(self.store.admit(token, foreground_open=True), device)
        self.clock.now += WEEK - 1
        self.assertEqual(self.store.admit(token, foreground_open=False), device)
        self.clock.now += 1
        self.assertIsNone(self.store.admit(token, foreground_open=True))
        self.assertFalse(self.store.valid(device))

    def test_regular_foreground_opens_keep_same_token_past_initial_month(self):
        token, device = self.issued()
        for _ in range(12):
            self.clock.now += 6 * DAY
            reopened = self.Store(self.path, self.clock)
            self.assertEqual(reopened.admit(token, foreground_open=True), device)
            self.assertTrue(reopened.valid(device))

    def test_background_periodic_admit_does_not_reset_idle(self):
        token, device = self.issued()
        for _ in range(6):
            self.clock.now += DAY
            self.assertEqual(self.store.admit(token, foreground_open=False), device)
        self.clock.now += DAY
        self.assertIsNone(self.store.admit(token, foreground_open=False))
        self.assertFalse(self.store.valid(device))

    def test_valid_checks_do_not_reset_idle(self):
        _, device = self.issued()
        for _ in range(6):
            self.clock.now += DAY
            self.assertTrue(self.store.valid(device))
        self.clock.now += DAY
        self.assertFalse(self.store.valid(device))

    def test_unused_token_denied_at_month_boundary(self):
        # Idle takes precedence earlier; public API cannot isolate expires alone.
        token, device = self.issued()
        self.clock.now += MONTH
        self.assertIsNone(self.store.admit(token, foreground_open=True))
        self.assertFalse(self.store.valid(device))

    def test_revoke_persists_and_does_not_revoke_another_device(self):
        token, device = self.issued()
        other_token, other_device = self.issued()
        self.store.revoke(device)
        self.store.revoke(device)  # repeated logout is harmless
        reopened = self.Store(self.path, self.clock)
        self.assertFalse(reopened.valid(device))
        self.assertIsNone(reopened.admit(token, foreground_open=True))
        self.assertEqual(reopened.admit(other_token, foreground_open=True), other_device)
        self.assertTrue(reopened.valid(other_device))

    def test_unknown_and_malformed_tokens_do_not_create_admission(self):
        _, device = self.issued()
        for token in ['', 'not-a-token', 'x' * 4096, '\x00', '😀', 'A' * 64]:
            with self.subTest(kind=repr(token[:16])):
                self.assertIsNone(self.store.admit(token, foreground_open=False))
                self.assertIsNone(self.store.admit(token, foreground_open=True))
        unknown = str(uuid.uuid4())
        self.assertFalse(self.store.valid(unknown))
        self.store.revoke(unknown)
        self.assertTrue(self.store.valid(device))

    def test_capability_exact_bytes_are_required(self):
        token, device = self.issued()
        for changed in [token + ' ', ' ' + token, token[:-1], token + 'x']:
            self.assertIsNone(self.store.admit(changed, foreground_open=True))
        self.assertEqual(self.store.admit(token, foreground_open=False), device)

    def test_private_sqlite_persists_hash_without_plaintext_token(self):
        token, _ = self.issued()
        self.assertTrue(self.path.is_file(), 'persistent SQLite file must exist')
        self.assertEqual(stat.S_IMODE(self.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertTrue(stat.S_ISREG(self.path.lstat().st_mode))
        payload = b''.join(p.read_bytes() for p in self.parent.iterdir() if p.is_file())
        self.assertNotIn(token.encode(), payload, 'plaintext capability must never persist')
        digest = hashlib.sha256(token.encode()).digest()
        self.assertTrue(digest in payload or digest.hex().encode() in payload,
                        'persistent grant must contain SHA256 lookup digest')

    def test_rejects_parent_with_group_or_world_access(self):
        for mode in [0o755, 0o750, 0o770]:
            with self.subTest(mode=oct(mode)):
                self.parent.chmod(mode)
                with self.assertRaises(ValueError):
                    self.Store(self.path, self.clock)
        self.parent.chmod(0o700)

    @unittest.skipUnless(os.geteuid() == 0, 'requires chown for real foreign-owner fixture')
    def test_rejects_parent_owned_by_another_uid(self):
        owner = self.parent.stat().st_uid
        os.chown(self.parent, owner + 1, -1)
        try:
            with self.assertRaises(ValueError):
                self.Store(self.path, self.clock)
        finally:
            os.chown(self.parent, owner, -1)

    def test_rejects_db_with_group_or_world_permissions(self):
        for mode in [0o644, 0o640, 0o660]:
            with self.subTest(mode=oct(mode)):
                self.path.touch()
                self.path.chmod(mode)
                with self.assertRaises(ValueError):
                    self.Store(self.path, self.clock)

    def test_rejects_symlink_db_without_modifying_target(self):
        target = self.parent / 'target'
        target.write_bytes(b'untouched fixture')
        target.chmod(0o600)
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.Store(self.path, self.clock)
        self.assertEqual(target.read_bytes(), b'untouched fixture')

    def test_rejects_symlink_parent(self):
        link = self.parent / 'linked-parent'
        actual = self.parent / 'actual-parent'
        actual.mkdir(mode=0o700)
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.Store(link / 'grants.sqlite3', self.clock)

    def test_rejects_nonregular_database(self):
        os.mkfifo(self.path, 0o600)
        with self.assertRaises(ValueError):
            self.Store(self.path, self.clock)

    def test_corrupt_private_database_fails_closed(self):
        self.path.write_bytes(b'not a SQLite database')
        self.path.chmod(0o600)
        with self.assertRaises(RuntimeError):
            store = self.Store(self.path, self.clock)
            store.issue()
        self.assertEqual(self.path.read_bytes(), b'not a SQLite database')

    def test_storage_failure_never_exposes_supplied_capability(self):
        synthetic = 'synthetic-private-capability-not-real'
        self.path.write_bytes(b'broken database fixture')
        self.path.chmod(0o600)
        with self.assertRaises(RuntimeError) as raised:
            store = self.Store(self.path, self.clock)
            store.admit(synthetic, foreground_open=True)
        self.assertNotIn(synthetic, str(raised.exception))

    def test_revoke_wins_against_concurrent_foreground_renewal(self):
        token, device = self.issued()
        self.clock.now += DAY
        stores = [self.Store(self.path, self.clock) for _ in range(3)]
        barrier = threading.Barrier(3)

        def renew(store):
            barrier.wait(timeout=5)
            return store.admit(token, foreground_open=True)

        def revoke():
            barrier.wait(timeout=5)
            stores[2].revoke(device)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(renew, stores[0]), pool.submit(renew, stores[1]),
                    pool.submit(revoke)]
            results = [job.result(timeout=10) for job in jobs]
        for result in results[:2]:
            self.assertIn(result, (device, None))
        reopened = self.Store(self.path, self.clock)
        self.assertFalse(reopened.valid(device))
        self.assertIsNone(reopened.admit(token, foreground_open=True),
                          'late renewal must never resurrect revoked device')


if __name__ == '__main__':
    unittest.main()
