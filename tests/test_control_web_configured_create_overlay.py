"""Source-blind contracts for the configured-create loaded-origin overlay.

The public contract is docs/dev/2026-10-06-spec-web-configured-session-create.md
and docs/specs/web-sessions.md. Fixtures use only private synthetic storage and
an injected fake RPC; no native service, credentials, or user data are involved.
"""
import importlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))

SID = '11111111-1111-4111-8111-111111111111'
OPERATION = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
_UNSET = object()
CONTEXT = {
    'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
    'context_id': 'a' * 64, 'transport_generation': 3,
    'context_generation': 7, 'native_version': '0.160.0',
}


class SyntheticRPC:
    def __init__(self, root, *, status=_UNSET, updated_at=1700000000.25):
        self.root = str(root)
        self.thread = {'id': SID, 'cwd': self.root, 'name': 'Synthetic title'}
        if status is _UNSET:
            self.thread['status'] = {'type': 'idle'}
        else:
            self.thread['status'] = status
        if updated_at is not _UNSET:
            self.thread['updatedAt'] = updated_at
        self.calls = []

    def prepare_context(self, timeout=None):
        return dict(CONTEXT)

    def model_context(self):
        return dict(CONTEXT)

    def receipt_context(self):
        return {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                'context_id': CONTEXT['context_id']}

    def call_in_generation(self, method, params, *, transport_generation,
                           context_generation, timeout=None):
        self.calls.append((method, dict(params), transport_generation, context_generation))
        if (transport_generation, context_generation) != (3, 7):
            raise AssertionError('synthetic generation mismatch')
        if method == 'thread/loaded/list':
            return {'data': [SID], 'nextCursor': None}
        if method == 'thread/read':
            return {'thread': dict(self.thread)}
        raise AssertionError('overlay called an unapproved synthetic RPC: ' + method)


class ConfiguredCreateOverlayContract(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        try:
            self.feature = importlib.import_module('_control_web_configured_create')
        except ImportError:
            self.feature = None
        self.tmp = tempfile.TemporaryDirectory(prefix='control-create-overlay-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.base.chmod(0o700)
        self.root = self.base / 'project'
        self.root.mkdir(mode=0o700)
        self.receipts = self.base / 'send-receipts'

    def require_feature(self):
        self.assertIsNotNone(
            self.feature,
            'INV-WSESS-35 requires the public ConfiguredSessionCreate overlay module')
        self.assertTrue(callable(getattr(self.feature, 'ConfiguredSessionCreate', None)),
                        'configured overlay owner must be public and callable')
        self.assertTrue(callable(getattr(self.feature, 'ConfiguredCreateStore', None)),
                        'configured overlay must use its trusted public store')

    def accepted_store(self):
        store = self.feature.ConfiguredCreateStore(str(self.base / 'origin-receipts'))
        deadline = time.monotonic() + 20
        with store.locked(deadline, create=True) as base:
            reservation = store.reserve(
                base, 'demo', CONTEXT['context_id'], str(self.root), OPERATION, deadline)
            reservation = store.candidate(base, reservation, SID, deadline)
            reservation = store.origin(base, reservation, deadline)
            return store.accept(base, reservation, deadline)

    def owner(self, rpc, store):
        return self.feature.ConfiguredSessionCreate(
            rpc, lambda project: str(self.root), lambda: ['demo'],
            str(self.receipts), store=store)

    def closed_failure(self, owner):
        try:
            result = owner.overlay('demo')
        except Exception as exc:
            self.assertNotIn(str(self.root), str(exc), 'safe failure cannot expose project path')
            return
        self.assertIsInstance(result, dict, 'overlay must fail closed with a safe DTO')
        self.assertEqual(result.get('sessions'), [],
                         'incomplete native metadata cannot yield an overlay row')
        encoded = json.dumps(result, allow_nan=False)
        self.assertNotIn('updated_at', encoded,
                         'unproved updatedAt cannot be replaced by a guessed timestamp')

    def test_INV_WSESS_35_accepted_loaded_origin_exports_exact_fresh_metadata_without_private_authority(self):
        self.require_feature()
        accepted = self.accepted_store()
        self.assertEqual(accepted.record['status'], 'accepted')
        rpc = SyntheticRPC(self.root, status={'type': 'idle'})
        result = self.owner(rpc, self.feature.ConfiguredCreateStore(
            str(self.base / 'origin-receipts'))).overlay('demo')
        self.assertEqual(set(result), {'sessions', 'truncated'})
        self.assertIs(result['truncated'], False)
        self.assertEqual(len(result['sessions']), 1)
        row = result['sessions'][0]
        self.assertEqual(set(row), {'sid', 'project', 'vendor', 'context_mode',
                                    'title', 'status', 'updated_at'})
        self.assertEqual(row, {
            'sid': SID, 'project': 'demo', 'vendor': 'codex',
            'context_mode': 'configured', 'title': 'Synthetic title',
            'status': 'idle', 'updated_at': 1700000000.25,
        })
        self.assertEqual([call[0] for call in rpc.calls],
                         ['thread/loaded/list', 'thread/read'])
        encoded = json.dumps(result, sort_keys=True)
        for private in (str(self.base), CONTEXT['context_id'], OPERATION, 'digest', 'root'):
            self.assertNotIn(private, encoded)

    def test_INV_WSESS_35_missing_or_malformed_native_status_or_updatedAt_fails_closed(self):
        self.require_feature()
        cases = (
            ('missing-status', _UNSET, 1700000000),
            ('malformed-status', {'type': {'unexpected': 'value'}}, 1700000000),
            ('missing-updatedAt', {'type': 'idle'}, _UNSET),
            ('boolean-updatedAt', {'type': 'idle'}, True),
            ('negative-updatedAt', {'type': 'idle'}, -1),
            ('nonfinite-updatedAt', {'type': 'idle'}, math.nan),
            ('string-updatedAt', {'type': 'idle'}, '1700000000'),
        )
        for label, status, updated_at in cases:
            with self.subTest(case=label):
                case_root = self.base / label
                case_root.mkdir(mode=0o700)
                store_path = self.base / (label + '-receipts')
                store = self.feature.ConfiguredCreateStore(str(store_path))
                deadline = time.monotonic() + 20
                with store.locked(deadline, create=True) as base:
                    reservation = store.reserve(
                        base, 'demo', CONTEXT['context_id'], str(case_root),
                        OPERATION, deadline)
                    reservation = store.candidate(base, reservation, SID, deadline)
                    reservation = store.origin(base, reservation, deadline)
                    store.accept(base, reservation, deadline)
                rpc = SyntheticRPC(case_root, status=status, updated_at=updated_at)
                owner = self.feature.ConfiguredSessionCreate(
                    rpc, lambda project, root=case_root: str(root), lambda: ['demo'],
                    str(self.base / (label + '-send')), store=store)
                self.closed_failure(owner)


if __name__ == '__main__':
    unittest.main()
