"""Source-blind public RED for configured-create origin index I."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

_BIN = str(Path(__file__).resolve().parents[1] / 'bin')
if _BIN not in sys.path:
    sys.path.insert(0, _BIN)

try:
    import _control_web_configured_create as configured_create
except Exception as exc:  # Keep the absent feature a semantic RED, not import ERROR.
    configured_create = None
    _IMPORT_ERROR = type(exc).__name__
else:
    _IMPORT_ERROR = None


PROJECT = 'alpha'
CONTEXT = 'c' * 64
ROOT_NAME = 'project-alpha'
OPS = [
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
]
SIDS = [
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333333',
    '44444444-4444-4444-8444-444444444444',
]


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def locator(kind, **fields):
    return hashlib.sha256(canonical_json({'kind': kind, **fields})).hexdigest() + '.json'


def r_name(project, operation_id):
    return locator('configured_create_receipt', project=project, operation_id=operation_id)


def c_name(project, operation_id):
    return locator('configured_create_candidate', project=project, operation_id=operation_id)


def a_name(project, operation_id):
    return locator('configured_create_accepted', project=project, operation_id=operation_id)


def i_name(context_id, root, sid):
    return locator('configured_session_origin', context_id=context_id, root=root, sid=sid)


class ConfiguredOriginIndex(unittest.TestCase):
    def setUp(self):
        self.private = Path(tempfile.mkdtemp(prefix='control-configured-origin-', dir='/var/tmp'))
        self.private.chmod(0o700)
        self.root = self.private / ROOT_NAME
        self.root.mkdir(mode=0o700)
        self.root = self.root.resolve(strict=True)
        self.store_path = self.private / 'configured-create-receipts'
        self.addCleanup(shutil.rmtree, self.private, ignore_errors=True)

    def store_api(self):
        self.assertIsNotNone(
            configured_create,
            'ConfiguredCreateStore origin index module is absent'
            + (': ' + _IMPORT_ERROR if _IMPORT_ERROR else ''),
        )
        self.assertTrue(hasattr(configured_create, 'ConfiguredCreateStore'),
                        'ConfiguredCreateStore public type is absent')
        self.assertTrue(hasattr(configured_create, 'ConfiguredCreateReservation'),
                        'ConfiguredCreateReservation public handle is absent')
        return configured_create.ConfiguredCreateStore(
            str(self.store_path), clock=lambda: 1700000000000000123)

    @staticmethod
    def deadline():
        return time.monotonic() + 8

    def _reserve_candidate(self, store, base, project, context_id, root, operation_id, sid):
        reservation = store.reserve(base, project, context_id, root, operation_id, self.deadline())
        candidate = store.candidate(base, reservation, sid, self.deadline())
        return reservation, candidate

    def _accept(self, store, base, project, context_id, root, operation_id, sid):
        reservation, _ = self._reserve_candidate(
            store, base, project, context_id, root, operation_id, sid)
        store.origin(base, reservation, self.deadline())
        return store.accept(base, reservation, self.deadline())

    def test_prepared_origin_I_commits_exact_candidate_but_is_not_authority_until_A(self):
        store = self.store_api()
        with store.locked(self.deadline(), create=True) as base:
            reservation, _candidate = self._reserve_candidate(
                store, base, PROJECT, CONTEXT, str(self.root), OPS[0], SIDS[0])
            store.origin(base, reservation, self.deadline())
            i_path = self.store_path / i_name(CONTEXT, str(self.root), SIDS[0])
            self.assertTrue(i_path.exists())
            i = json.loads(i_path.read_text(encoding='utf-8'))
            r = json.loads((self.store_path / r_name(PROJECT, OPS[0])).read_text(encoding='utf-8'))
            c = json.loads((self.store_path / c_name(PROJECT, OPS[0])).read_text(encoding='utf-8'))
            self.assertEqual(set(i), {'schema', 'kind', 'project', 'operation_id',
                                      'context_id', 'root', 'sid', 'created', 'parent'})
            self.assertEqual((i['schema'], i['kind']), (1, 'configured_session_origin'))
            self.assertEqual((i['project'], i['operation_id'], i['context_id'],
                              i['root'], i['sid']),
                             (PROJECT, OPS[0], CONTEXT, str(self.root), SIDS[0]))
            self.assertEqual(i['created'], r['created'])
            self.assertEqual(set(i['parent']), {'filename', 'dev', 'ino', 'ctime_ns', 'sha256'})
            self.assertEqual(i['parent']['filename'], c_name(PROJECT, OPS[0]))
            self.assertTrue(all(type(i['parent'][key]) is int and i['parent'][key] >= 0
                                for key in ('dev', 'ino', 'ctime_ns')))
            self.assertRegex(i['parent']['sha256'], r'^[0-9a-f]{64}$')
            self.assertEqual(i['parent']['sha256'], hashlib.sha256(
                (self.store_path / c_name(PROJECT, OPS[0])).read_bytes()).hexdigest())
            self.assertIsNone(store.origin_lookup(
                base, CONTEXT, str(self.root), SIDS[0], self.deadline()),
                'prepared I without accepted A must not grant loaded-session authority')

            accepted = store.accept(base, reservation, self.deadline())
            self.assertEqual(accepted.record['status'], 'accepted')
            a = json.loads((self.store_path / a_name(PROJECT, OPS[0])).read_text(encoding='utf-8'))
            self.assertEqual(set(a), {'schema', 'kind', 'record', 'parent', 'origin'})
            self.assertEqual(a['origin']['filename'], i_name(CONTEXT, str(self.root), SIDS[0]))
            self.assertEqual(set(a['origin']), {'filename', 'dev', 'ino', 'ctime_ns', 'sha256'})
            self.assertTrue(all(type(a['origin'][key]) is int and a['origin'][key] >= 0
                                for key in ('dev', 'ino', 'ctime_ns')))
            self.assertRegex(a['origin']['sha256'], r'^[0-9a-f]{64}$')
            indexed = store.origin_lookup(base, CONTEXT, str(self.root), SIDS[0], self.deadline())
            self.assertIsInstance(indexed, configured_create.ConfiguredCreateReservation)
            self.assertEqual(indexed.record['status'], 'accepted')
            self.assertEqual(indexed.record['operation_id'], OPS[0])

    def test_same_sid_origin_key_collision_refuses_second_operation_without_overwrite(self):
        store = self.store_api()
        with store.locked(self.deadline(), create=True) as base:
            first, _ = self._reserve_candidate(
                store, base, PROJECT, CONTEXT, str(self.root), OPS[0], SIDS[0])
            store.origin(base, first, self.deadline())
            path = self.store_path / i_name(CONTEXT, str(self.root), SIDS[0])
            original = path.read_bytes()
            second, _ = self._reserve_candidate(
                store, base, PROJECT, CONTEXT, str(self.root), OPS[1], SIDS[0])
            try:
                store.origin(base, second, self.deadline())
            except Exception as exc:
                self.assertEqual(getattr(exc, 'code', None), 'unavailable')
            else:
                self.fail('origin locator collision must fail unavailable, not overwrite')
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(json.loads(original)['operation_id'], OPS[0])

    def test_known_accepted_handle_with_missing_I_or_A_never_downgrades(self):
        store = self.store_api()
        with store.locked(self.deadline(), create=True) as base:
            accepted = self._accept(store, base, PROJECT, CONTEXT,
                                    str(self.root), OPS[0], SIDS[0])
            (self.store_path / i_name(CONTEXT, str(self.root), SIDS[0])).unlink()
            for callback in (
                lambda: store.lookup(base, PROJECT, OPS[0], self.deadline()),
                lambda: store.accept(base, accepted, self.deadline()),
            ):
                try:
                    callback()
                except Exception as exc:
                    self.assertEqual(getattr(exc, 'code', None), 'unavailable')
                else:
                    self.fail('known accepted missing I must fail unavailable')
            self.assertIsNone(store.origin_lookup(
                base, CONTEXT, str(self.root), SIDS[0], self.deadline()),
                'stateless absent I is not proof and must not scan receipts')

            accepted_without_a = self._accept(
                store, base, PROJECT, CONTEXT, str(self.root), OPS[1], SIDS[1])
            (self.store_path / a_name(PROJECT, OPS[1])).unlink()
            try:
                store.accept(base, accepted_without_a, self.deadline())
            except Exception as exc:
                self.assertEqual(getattr(exc, 'code', None), 'unavailable')
            else:
                self.fail('known accepted missing A must fail unavailable, not downgrade')

    def test_origins_are_bounded_to_exact_project_context_and_root(self):
        store = self.store_api()
        other_root = self.private / 'project-other'
        other_root.mkdir(mode=0o700)
        other_root = str(other_root.resolve(strict=True))
        other_context = 'e' * 64
        with store.locked(self.deadline(), create=True) as base:
            self._accept(store, base, PROJECT, CONTEXT, str(self.root), OPS[0], SIDS[0])
            self._accept(store, base, PROJECT, CONTEXT, str(self.root), OPS[1], SIDS[1])
            self._accept(store, base, 'beta', CONTEXT, str(self.root), OPS[2], SIDS[2])
            self._accept(store, base, PROJECT, other_context, other_root, OPS[3], SIDS[3])
            result = store.origins(base, PROJECT, CONTEXT, str(self.root), self.deadline())
        self.assertEqual(set(result), {'records', 'truncated'})
        self.assertIs(type(result['records']), tuple)
        self.assertIs(result['truncated'], False)
        self.assertEqual({handle.record['operation_id'] for handle in result['records']},
                         {OPS[0], OPS[1]})
        self.assertTrue(all(handle.record['project'] == PROJECT
                            and handle.record['context_id'] == CONTEXT
                            and handle.record['root'] == str(self.root)
                            and handle.record['status'] == 'accepted'
                            for handle in result['records']))
        self.assertNotIn(SIDS[2], json.dumps([dict(row.record) for row in result['records']]))
        self.assertNotIn(SIDS[3], json.dumps([dict(row.record) for row in result['records']]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
