"""Source-blind configured-create publication and loaded-overlay contracts.

Public contract: docs/dev/2026-10-06-spec-web-configured-session-create.md
(frozen public revision b8949ed57e2cf480b28c91cbe11738863cfaa9e6). Fixtures are
synthetic and private; no native service, credentials, or user history is used.
"""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))

import _control_web_sessions as web_sessions  # noqa: E402

SID_A = '11111111-1111-4111-8111-111111111111'
SID_B = '44444444-4444-4444-8444-444444444444'
SID_C = '55555555-5555-4555-8555-555555555555'
OP_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
OP_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
OP_C = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
OP_CLOCK = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
CONTEXT = {
    'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
    'context_id': 'a' * 64, 'transport_generation': 3,
    'context_generation': 7, 'native_version': '0.160.0',
}


class SyntheticRPC:
    def __init__(self, root, loaded_scans=None, outcomes=None):
        self.root = str(root)
        self.loaded_scans = list(loaded_scans or ([SID_A, SID_B, SID_C],))
        self.outcomes = outcomes or {}
        self.loaded_scan_count = 0
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
            index = min(self.loaded_scan_count, len(self.loaded_scans) - 1)
            self.loaded_scan_count += 1
            page = self.loaded_scans[index]
            if isinstance(page, BaseException):
                raise page
            return dict(page) if isinstance(page, dict) else {'data': list(page), 'nextCursor': None}
        if method == 'thread/read':
            sid = params.get('threadId')
            outcome = self.outcomes.get(sid, 'valid')
            if isinstance(outcome, BaseException):
                raise outcome
            if outcome == 'missing-null':
                return {'thread': None}
            thread_id = sid if outcome != 'wrong-id' else '66666666-6666-4666-8666-666666666666'
            root = self.root if outcome != 'wrong-root' else str(Path(self.root).parent)
            return {'thread': {'id': thread_id, 'cwd': root, 'name': 'Synthetic title',
                               'status': {'type': 'idle'}, 'updatedAt': 1700000000}}
        raise AssertionError('unexpected synthetic RPC method: ' + method)


class ConfiguredCreatePublicationAndOverlay(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        try:
            self.feature = importlib.import_module('_control_web_configured_create')
        except ImportError:
            self.feature = None
        self.tmp = tempfile.TemporaryDirectory(prefix='control-configured-publish-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.base.chmod(0o700)
        self.root = self.base / 'project'
        self.root.mkdir(mode=0o700)

    def require_feature(self):
        self.assertIsNotNone(self.feature,
                             'INV-WSESS-35 requires the public configured-create module')
        self.assertTrue(callable(getattr(self.feature, 'ConfiguredCreateStore', None)))
        self.assertTrue(callable(getattr(self.feature, 'ConfiguredSessionCreate', None)))

    def store(self, path, clock=None):
        kwargs = {} if clock is None else {'clock': clock}
        return self.feature.ConfiguredCreateStore(str(path), **kwargs)

    def creator(self, rpc, store):
        return self.feature.ConfiguredSessionCreate(
            rpc, lambda project: str(self.root), lambda: ['demo'],
            str(self.base / 'send-receipts'), store=store)

    def accept(self, store, op_id, sid):
        deadline = time.monotonic() + 20
        with store.locked(deadline, create=True) as base:
            r = store.reserve(base, 'demo', CONTEXT['context_id'], str(self.root), op_id, deadline)
            c = store.candidate(base, r, sid, deadline)
            i = store.origin(base, c, deadline)
            return store.accept(base, i, deadline)

    def test_INV_WSESS_35_clock_preparation_is_pure_single_sample_replay_does_not_resample_and_invalid_clock_refuses_create(self):
        self.require_feature()
        samples = []
        def clock():
            samples.append(1700000000000000000 + len(samples))
            return samples[-1]

        path = self.base / 'pure-clock-store'
        store = self.store(path, clock=clock)
        deadline = time.monotonic() + 20
        prepared = store.prepare_reservation(
            'demo', CONTEXT['context_id'], str(self.root), OP_A, deadline)
        self.assertIsInstance(prepared, self.feature.ConfiguredPreparedCreate)
        self.assertEqual(prepared.record['created'], 1700000000000000000)
        self.assertEqual(samples, [1700000000000000000])
        self.assertFalse(path.exists(), 'preparation must not provision or write the store')
        with store.locked(deadline, create=True) as base:
            published = store.publish_reservation(base, prepared, deadline)
            replay = store.reserve(base, 'demo', CONTEXT['context_id'],
                                   str(self.root), OP_A, deadline)
        self.assertEqual(replay.record, published.record)
        self.assertEqual(samples, [1700000000000000000],
                         'replay cannot request a second timestamp sample')

        bad_path = self.base / 'invalid-clock-store'
        bad_store = self.store(bad_path, clock=lambda: 0)
        rpc = SyntheticRPC(self.root)
        result = self.creator(rpc, bad_store).create(
            'demo', OP_CLOCK, context_mode='configured', provider_id='codex')
        self.assertEqual(result, {'error': 'invalid_request'})
        self.assertFalse(any(method == 'thread/start' for method, *_ in rpc.calls),
                         'invalid clock cannot permit native creation')
        if bad_path.exists():
            self.assertEqual(list(bad_path.glob('*.json')), [],
                             'invalid clock cannot publish an initial receipt')

    def test_INV_WSESS_35_publication_entry_uncertainty_is_unknown_and_never_dispatches_or_retries(self):
        self.require_feature()
        store = self.store(self.base / 'uncertain-store', clock=lambda: 1700000000000000000)
        rpc = SyntheticRPC(self.root)
        with patch.object(store, 'publish_reservation', side_effect=OSError('synthetic write uncertainty')) as publish:
            result = self.creator(rpc, store).create(
                'demo', OP_CLOCK, context_mode='configured', provider_id='codex')
        self.assertEqual(result, {'operation_id': OP_CLOCK, 'status': 'delivery_unknown'})
        publish.assert_called_once()
        self.assertFalse(any(method == 'thread/start' for method, *_ in rpc.calls),
                         'unknown publication cannot dispatch thread/start')

    def test_INV_WSESS_35_only_correlated_read_rejections_share_complete_rescan_to_omit_absent_loaded_rows(self):
        self.require_feature()
        store = self.store(self.base / 'origin-store')
        self.accept(store, OP_A, SID_A)
        self.accept(store, OP_B, SID_B)
        self.accept(store, OP_C, SID_C)
        rpc = SyntheticRPC(self.root, loaded_scans=([SID_A, SID_B, SID_C], [SID_B]),
                           outcomes={SID_A: web_sessions.RPCRejected('synthetic code'),
                                     SID_C: web_sessions.RPCRejected('synthetic code')})
        result = self.creator(rpc, store).overlay('demo')
        self.assertEqual(result, {'sessions': [{
            'sid': SID_B, 'project': 'demo', 'vendor': 'codex',
            'context_mode': 'configured', 'title': 'Synthetic title',
            'status': 'idle', 'updated_at': 1700000000,
        }], 'truncated': False})
        self.assertEqual(rpc.loaded_scan_count, 2,
                         'all rejected SIDs share exactly one confirmation scan')
        self.assertEqual([method for method, *_ in rpc.calls].count('thread/loaded/list'), 2)

    def test_INV_WSESS_35_successful_null_malformed_or_unconfirmed_failed_reads_fail_closed(self):
        self.require_feature()
        cases = (
            ('successful-null', [SID_A, SID_B], {SID_A: 'missing-null'}),
            ('wrong-id', [SID_A, SID_B], {SID_A: 'wrong-id'}),
            ('wrong-root', [SID_A, SID_B], {SID_A: 'wrong-root'}),
            ('generic-error', [SID_A, SID_B], {SID_A: RuntimeError('synthetic transport error')}),
            ('still-loaded', [SID_A, SID_B], {SID_A: web_sessions.RPCRejected('synthetic code')}),
            ('partial-confirmation', {'data': [SID_B], 'nextCursor': 'more'},
             {SID_A: web_sessions.RPCRejected('synthetic code')}),
        )
        for label, confirmation, outcomes in cases:
            with self.subTest(case=label):
                store = self.store(self.base / (label + '-store'))
                self.accept(store, OP_A, SID_A)
                self.accept(store, OP_B, SID_B)
                rpc = SyntheticRPC(self.root, loaded_scans=([SID_A, SID_B], confirmation),
                                   outcomes=outcomes)
                result = self.creator(rpc, store).overlay('demo')
                self.assertEqual(result, {'error': 'unavailable'})


if __name__ == '__main__':
    unittest.main()
