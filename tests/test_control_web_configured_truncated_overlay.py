"""Public 330 regression: a truncated accepted-origin overlay cannot page partially."""
from dataclasses import dataclass
import importlib
import inspect
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
SID = '11111111-1111-4111-8111-111111111111'
OVERLAY_SID = '22222222-2222-4222-8222-222222222222'


@dataclass(frozen=True)
class CacheIdentity:
    context: object
    namespace: object


class RPC:
    def __init__(self, root):
        self.root = root
        self.calls = []

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method == 'thread/list':
            return {'data': [{'id': SID, 'cwd': str(self.root), 'name': 'Synthetic native row',
                              'status': {'type': 'idle'}}], 'nextCursor': None}
        if method == 'thread/read':
            return {'thread': {'id': params['threadId'], 'cwd': str(self.root),
                               'name': 'Synthetic native row', 'status': {'type': 'idle'}}}
        raise AssertionError('Unexpected synthetic RPC method: ' + method)


class TruncatedCreator:
    def __init__(self):
        self.calls = []
        self.identity = CacheIdentity(
            context={'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                     'context_id': 'a' * 64, 'transport_generation': 0,
                     'context_generation': 0, 'native_version': '0.160.0'},
            namespace=None,
        )

    def cache_identity(self, *, deadline=None):
        return self.identity

    def overlay(self, project, *, deadline=None):
        self.calls.append((project, deadline))
        return {'sessions': [{'sid': OVERLAY_SID, 'project': project, 'vendor': 'codex',
                              'context_mode': 'configured', 'title': None, 'status': 'idle',
                              'updated_at': 1}], 'truncated': True}


class ConfiguredCreateTruncatedOverlay(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-create-truncated-overlay-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)
        self.project = self.base / 'project'
        self.project.mkdir(mode=0o700)
        self.rpc = RPC(self.project)
        self.creator = TruncatedCreator()

        def resolve(alias):
            if alias != 'demo':
                raise ValueError('synthetic-invalid-project')
            return str(self.project)

        signature = inspect.signature(self.module.SessionChat)
        kwargs = {'configured_creator': self.creator} if 'configured_creator' in signature.parameters else {}
        self.chat = self.module.SessionChat(self.rpc, resolve, lambda: ['demo'],
                                            str(self.base / 'receipts'), **kwargs)
        # The baseline predates this optional public injection point. Setting the
        # same trusted attribute lets its unmodified list method run and fail by
        # behavior (it ignores truncated creator evidence), rather than TypeError.
        if not kwargs:
            self.chat.configured_creator = self.creator

    def test_truncated_origin_overlay_makes_every_requested_page_unavailable(self):
        for page in (0, 7):
            with self.subTest(page=page):
                result = self.chat.list_sessions('demo', page)
                self.assertTrue(self.creator.calls,
                                'SessionChat must consult the injected trusted origin overlay')
                self.assertEqual(self.creator.calls[-1][0], 'demo')
                self.assertEqual(result, {'error': 'unavailable'},
                                 'Truncated origin evidence cannot produce a partial page or has_more claim')
                self.assertNotIn(OVERLAY_SID, repr(result))


if __name__ == '__main__':
    unittest.main()
