"""Source-blind phase-two cache identity and deadline contracts.

Public source is docs/dev/2026-10-06-spec-web-configured-session-create.md at
3301559997d93bc9c323917b75b968d07b1cb7b2. All roots, records and RPC data are
private synthetic fixtures.
"""
from dataclasses import dataclass
import importlib
import inspect
import json
import math
from pathlib import Path
from types import MappingProxyType
import os
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))

import _control_web_sessions as web_sessions  # noqa: E402

SID1 = '11111111-1111-4111-8111-111111111111'
SID2 = '22222222-2222-4222-8222-222222222222'
OP = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
CONTEXT = {
    'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
    'context_id': 'a' * 64, 'transport_generation': 3,
    'context_generation': 7, 'native_version': '0.160.0',
}


@dataclass(frozen=True)
class FakeCacheIdentity:
    context: object
    namespace: object


class SyntheticOwnerRPC:
    def __init__(self, root, *, loaded=(SID1,)):
        self.root = str(root)
        self.loaded = list(loaded)
        self.calls = []
        self.context_calls = []

    def prepare_context(self, timeout=None):
        self.context_calls.append((time.monotonic(), timeout))
        return dict(CONTEXT)

    def model_context(self):
        return dict(CONTEXT)

    def receipt_context(self):
        return {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                'context_id': CONTEXT['context_id']}

    def call_in_generation(self, method, params, *, transport_generation,
                           context_generation, timeout=None):
        self.calls.append((time.monotonic(), method, dict(params), timeout))
        if (transport_generation, context_generation) != (3, 7):
            raise AssertionError('synthetic generation mismatch')
        if method == 'thread/loaded/list':
            return {'data': list(self.loaded), 'nextCursor': None}
        if method == 'thread/read':
            sid = params['threadId']
            return {'thread': {'id': sid, 'cwd': self.root, 'name': 'Synthetic title',
                               'status': {'type': 'idle'}, 'updatedAt': 1700000000}}
        raise AssertionError('unexpected owner RPC: ' + method)


class SyntheticSessionRPC:
    def __init__(self, root):
        self.root = Path(root)
        self.generation = 1
        self.rows = [{'id': SID1, 'cwd': str(self.root), 'name': 'Native row',
                      'status': {'type': 'idle'}, 'updatedAt': 100, 'source': 'cli',
                      'archived': False}]
        self.calls = []
        self.list_error = None

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method == 'thread/list':
            if self.list_error:
                raise self.list_error
            return {'data': list(self.rows), 'nextCursor': None}
        if method == 'thread/read':
            sid = params['threadId']
            row = next(row for row in self.rows if row['id'] == sid)
            return {'thread': {'id': sid, 'cwd': str(self.root), 'name': row['name'],
                               'status': dict(row['status']), 'updatedAt': row['updatedAt']}}
        raise AssertionError('unexpected SessionChat RPC: ' + method)


class SyntheticCreator:
    def __init__(self, namespace=None, sessions=()):
        self.context = MappingProxyType(dict(CONTEXT))
        self.namespace = namespace
        self.sessions = list(sessions)
        self.truncated = False
        self.cache_deadlines = []
        self.overlay_deadlines = []
        self.cache_sequence = None

    def cache_identity(self, *, deadline=None):
        self.cache_deadlines.append(deadline)
        if self.cache_sequence:
            return self.cache_sequence.pop(0) if len(self.cache_sequence) > 1 else self.cache_sequence[0]
        namespace = None if self.namespace is None else MappingProxyType(dict(self.namespace))
        return FakeCacheIdentity(self.context, namespace)

    def overlay(self, project, *, deadline=None):
        self.overlay_deadlines.append(deadline)
        return {'sessions': list(self.sessions), 'truncated': self.truncated}

    def loaded_origin(self, project, sid, *, deadline=None):
        return None

    def unavailable_history(self, project, sid, *, deadline=None):
        return None

    def publish_origin(self, *, mtime_ns, session):
        self.namespace = {'dev': 1, 'ino': 2, 'mtime_ns': mtime_ns, 'ctime_ns': mtime_ns}
        self.sessions = [dict(session)]


class ConfiguredCacheAndDeadlineContract(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        try:
            self.feature = importlib.import_module('_control_web_configured_create')
        except ImportError:
            self.feature = None
        self.tmp = tempfile.TemporaryDirectory(prefix='control-cache-identity-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.base.chmod(0o700)
        self.root = self.base / 'project'
        self.root.mkdir(mode=0o700)

    def require_owner_feature(self):
        self.assertIsNotNone(self.feature,
                             'phase-two configured cache/deadline owner is required')
        self.assertTrue(callable(getattr(self.feature, 'ConfiguredCreateStore', None)))
        self.assertTrue(callable(getattr(self.feature, 'ConfiguredSessionCreate', None)))

    def safe_result(self, function, allowed):
        try:
            return function()
        except Exception as exc:
            code = getattr(exc, 'code', None)
            if code in allowed:
                return {'error': code}
            self.fail(f'public call raised unexpectedly: {type(exc).__name__}, code={code!r}')

    def owner(self, rpc, store):
        return self.feature.ConfiguredSessionCreate(
            rpc, lambda project: str(self.root), lambda: ['demo'],
            str(self.base / 'send-receipts'), store=store)

    def session_chat(self, rpc, creator, *, summary_clock=None):
        params = inspect.signature(web_sessions.SessionChat).parameters
        self.assertIn('configured_creator', params,
                      'SessionChat must accept only trusted configured_creator injection')
        kwargs = {'configured_creator': creator}
        if summary_clock is not None:
            kwargs.update(summary_clock=summary_clock, summary_wall_clock=lambda: 1800000000,
                          summary_generation=lambda: rpc.generation)
        return web_sessions.SessionChat(
            rpc, lambda project: str(self.root), lambda: ['demo'],
            str(self.base / 'chat-receipts'), **kwargs)

    def test_INV_WSESS_35_cache_identity_is_exact_frozen_read_only_and_absent_namespace_stays_absent(self):
        self.require_owner_feature()
        store_path = self.base / 'absent-private-namespace'
        rpc = SyntheticOwnerRPC(self.root)
        def no_provider(*args):
            raise AssertionError('cache identity cannot resolve projects or roots')
        store = self.feature.ConfiguredCreateStore(str(store_path))
        owner = self.feature.ConfiguredSessionCreate(
            rpc, no_provider, no_provider, str(self.base / 'send-receipts'), store=store)
        deadline = time.monotonic() + 3
        identity = self.safe_result(lambda: owner.cache_identity(deadline=deadline),
                                    ('unavailable', 'stale'))
        self.assertTrue(hasattr(identity, 'context') and hasattr(identity, 'namespace'),
                        'cache identity is a frozen typed context/namespace pair')
        self.assertEqual(dict(identity.context), CONTEXT)
        self.assertEqual(set(identity.context), set(CONTEXT))
        self.assertIsNone(identity.namespace,
                          'absent private namespace is represented as None, not created or guessed')
        if hasattr(type(identity), '__dataclass_fields__'):
            self.assertEqual(set(type(identity).__dataclass_fields__), {'context', 'namespace'})
        elif hasattr(type(identity), '_fields'):
            self.assertEqual(set(type(identity)._fields), {'context', 'namespace'})
        else:
            self.assertEqual(set(vars(identity)), {'context', 'namespace'})
        with self.assertRaises((AttributeError, TypeError)):
            identity.context = {}
        with self.assertRaises((TypeError, AttributeError)):
            identity.context['context_id'] = 'b' * 64
        self.assertFalse(store_path.exists(), 'cache identity must not create an absent namespace')
        self.assertEqual(rpc.calls, [], 'identity capture cannot issue native thread RPCs')
        self.assertTrue(rpc.context_calls)
        for started, timeout in rpc.context_calls:
            self.assertIsInstance(timeout, (int, float))
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, deadline - started + 0.01,
                                 'cache identity must preserve caller deadline')

        present_path = self.base / 'present-private-namespace'
        present_path.mkdir(mode=0o700)
        before = present_path.stat()
        present_store = self.feature.ConfiguredCreateStore(str(present_path))
        present_rpc = SyntheticOwnerRPC(self.root)
        present_owner = self.feature.ConfiguredSessionCreate(
            present_rpc, no_provider, no_provider,
            str(self.base / 'send-receipts'), store=present_store)
        present = self.safe_result(lambda: present_owner.cache_identity(
            deadline=time.monotonic() + 3), ('unavailable', 'stale'))
        self.assertTrue(hasattr(present, 'namespace'))
        self.assertEqual(set(present.namespace), {'dev', 'ino', 'mtime_ns', 'ctime_ns'})
        self.assertTrue(all(type(value) is int and value >= 0
                            for value in present.namespace.values()))
        with self.assertRaises((TypeError, AttributeError)):
            present.namespace['ino'] = 0
        after = present_path.stat()
        self.assertEqual((before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns),
                         (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns))
        self.assertEqual(present_rpc.calls, [])

    def test_INV_WSESS_35_short_absolute_deadline_reaches_cache_origin_overlay_and_history_proofs(self):
        self.require_owner_feature()
        store = self.feature.ConfiguredCreateStore(str(self.base / 'accepted-origin-store'))
        required = ('locked', 'reserve', 'candidate', 'origin', 'accept', 'origin_lookup', 'origins')
        for method in required:
            self.assertTrue(callable(getattr(type(store), method, None)),
                            'public store method required for deadline proof: ' + method)
        deadline = time.monotonic() + 5
        with store.locked(deadline, create=True) as base:
            r = store.reserve(base, 'demo', CONTEXT['context_id'], str(self.root), OP, deadline)
            c = store.candidate(base, r, SID1, deadline)
            i = store.origin(base, c, deadline)
            store.accept(base, i, deadline)
        rpc = SyntheticOwnerRPC(self.root)
        owner = self.owner(rpc, store)
        for method in ('cache_identity', 'overlay', 'loaded_origin', 'unavailable_history'):
            self.assertTrue(callable(getattr(owner, method, None)),
                            'public deadline-aware owner method required: ' + method)
            self.assertIn('deadline', inspect.signature(getattr(owner, method)).parameters,
                          'one caller deadline must be accepted by ' + method)

        lock_deadlines, origin_deadlines = [], []
        original_locked, original_lookup, original_origins = store.locked, store.origin_lookup, store.origins
        def capture_lock(value, *args, **kwargs):
            lock_deadlines.append(value)
            return original_locked(value, *args, **kwargs)
        def capture_lookup(*args, **kwargs):
            value = kwargs.get('deadline', args[-1] if args else None)
            origin_deadlines.append(value)
            return original_lookup(*args, **kwargs)
        def capture_origins(*args, **kwargs):
            value = kwargs.get('deadline', args[-1] if args else None)
            origin_deadlines.append(value)
            return original_origins(*args, **kwargs)
        store.locked = capture_lock
        store.origin_lookup = capture_lookup
        store.origins = capture_origins
        try:
            ident = self.safe_result(lambda: owner.cache_identity(deadline=deadline),
                                     ('unavailable', 'stale'))
            self.assertTrue(hasattr(ident, 'context') and hasattr(ident, 'namespace'))
            self.assertEqual(dict(ident.context), CONTEXT)
            overlay = self.safe_result(lambda: owner.overlay('demo', deadline=deadline),
                                       ('unavailable', 'stale', 'forbidden'))
            self.assertEqual(overlay, {'sessions': [{
                'sid': SID1, 'project': 'demo', 'vendor': 'codex',
                'context_mode': 'configured', 'title': 'Synthetic title',
                'status': 'idle', 'updated_at': 1700000000,
            }], 'truncated': False})
            loaded = self.safe_result(lambda: owner.loaded_origin('demo', SID1, deadline=deadline),
                                      ('unavailable', 'stale', 'forbidden'))
            unavailable = self.safe_result(lambda: owner.unavailable_history(
                'demo', SID1, deadline=deadline), ('unavailable', 'stale', 'forbidden'))
        finally:
            store.locked, store.origin_lookup, store.origins = original_locked, original_lookup, original_origins
        for witness in (loaded, unavailable):
            self.assertFalse(isinstance(witness, dict) and 'error' in witness)
            for attribute in ('reservation', 'context', 'session'):
                self.assertTrue(hasattr(witness, attribute),
                                'deadline-aware origin proof must return its frozen witness')
        self.assertTrue(lock_deadlines and origin_deadlines)
        self.assertTrue(all(value == deadline for value in lock_deadlines + origin_deadlines),
                        'nested store operations must retain the caller’s one absolute deadline')
        self.assertTrue(rpc.calls, 'loaded-origin proofs exercise the fenced native metadata seam')
        for started, _method, _params, timeout in rpc.calls:
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, deadline - started + 0.02,
                                 'nested RPC timeout cannot reset to a fresh 55-second allowance')

    def test_INV_WSESS_35_summary_cache_identity_change_invalidates_counts_within_ttl_and_context_drift_never_reuses_them(self):
        self.require_owner_feature()
        rpc = SyntheticSessionRPC(self.root)
        creator = SyntheticCreator()
        now = [2000.0]
        chat = self.session_chat(rpc, creator, summary_clock=lambda: now[0])
        first = chat.project_summary()['projects'][0]
        self.assertEqual((first['session_count'], first['last_activity'], first['summary_state']),
                         (1, 100, 'fresh'))
        initial_calls = len([method for method, _ in rpc.calls if method == 'thread/list'])

        creator.publish_origin(mtime_ns=10, session={
            'sid': SID2, 'project': 'demo', 'vendor': 'codex',
            'context_mode': 'configured', 'title': 'Synthetic new origin',
            'status': 'idle', 'updated_at': 500,
        })
        second = chat.project_summary()['projects'][0]
        self.assertEqual((second['session_count'], second['last_activity']), (2, 500))
        self.assertEqual(second['summary_state'], 'fresh')
        self.assertGreater(len([method for method, _ in rpc.calls if method == 'thread/list']),
                           initial_calls,
                           'a changed private origin namespace invalidates a still-young cached view')

        changed_context = dict(CONTEXT)
        changed_context['context_id'] = 'b' * 64
        creator.context = MappingProxyType(changed_context)
        rpc.list_error = RuntimeError('synthetic new-context list failure')
        third = chat.project_summary()['projects'][0]
        self.assertNotEqual(third['summary_state'], 'fresh')
        self.assertIsNone(third['session_count'],
                          'counts from another configured context cannot be reused as stale truth')
        self.assertIsNone(third['last_activity'])

    def test_INV_WSESS_35_summary_final_identity_fence_and_existing_operation_budgets_are_preserved(self):
        self.require_owner_feature()
        rpc = SyntheticSessionRPC(self.root)
        creator = SyntheticCreator()
        changed_context = dict(CONTEXT)
        changed_context['context_generation'] = CONTEXT['context_generation'] + 1
        identity_a = FakeCacheIdentity(MappingProxyType(dict(CONTEXT)), None)
        identity_b = FakeCacheIdentity(MappingProxyType(changed_context), None)
        creator.cache_sequence = [identity_a, identity_b]
        now = [4000.0]
        chat = self.session_chat(rpc, creator, summary_clock=lambda: now[0])
        result = chat.project_summary()['projects'][0]
        self.assertNotEqual(result['summary_state'], 'fresh',
                            'identity change across the scan cannot publish fresh mixed evidence')
        self.assertIsNone(result['session_count'])
        self.assertIsNone(result['last_activity'])

        # A fresh owner demonstrates SessionChat keeps its existing list and summary budgets.
        creator.cache_sequence = None
        creator.context = MappingProxyType(dict(CONTEXT))
        started = time.monotonic()
        listed = chat.list_sessions('demo')
        self.assertIn('rows', listed)
        self.assertTrue(creator.overlay_deadlines)
        self.assertTrue(all(isinstance(d, (int, float)) and started < d <= started + 55
                            for d in creator.overlay_deadlines),
                        'list overlay shares SessionChat’s existing 55-second operation deadline')
        creator.cache_deadlines.clear()
        creator.overlay_deadlines.clear()
        started = time.monotonic()
        summary = chat.project_summary()
        self.assertIn('projects', summary)
        self.assertTrue(creator.cache_deadlines and creator.overlay_deadlines)
        self.assertTrue(all(isinstance(d, (int, float)) and started < d <= started + 15
                            for d in creator.cache_deadlines + creator.overlay_deadlines),
                        'summary/cache/overlay share the existing 15-second summary budget')


if __name__ == '__main__':
    unittest.main()
