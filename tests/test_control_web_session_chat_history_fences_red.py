"""Source-blind synthetic RED for final history authority and page identity fences."""
import os
from pathlib import Path
import tempfile
import unittest

from test_control_web_session_chat_contract import OTHER, SID, TURN, RPC, feature, turn


class ContextRPC(RPC):
    def __init__(self, root):
        super().__init__(root)
        self.context = {
            'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
            'context_id': 'a' * 64, 'transport_generation': 3,
            'context_generation': 7, 'native_version': 'codex/0.160.0',
        }

    def model_context(self):
        return dict(self.context)

    def receipt_context(self):
        return {key: self.context[key] for key in ('schema', 'vendor', 'context_kind', 'context_id')}


class HistoryFinalFenceRed(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_sessions')
        self.tmp = tempfile.TemporaryDirectory(prefix='web-history-final-fence-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        os.chmod(self.base, 0o700)

    def make_chat(self, label, *, empty=False):
        project = self.base / (label + '-project')
        project.mkdir(mode=0o700)
        other_root = self.base / (label + '-rebound')
        other_root.mkdir(mode=0o700)
        receipts = self.base / (label + '-receipts')
        rpc = ContextRPC(project)
        if empty:
            rpc.pages[None] = {'data': [], 'nextCursor': None}
        state = {'root': project}

        def resolve(alias):
            if alias != 'demo':
                raise ValueError('synthetic-invalid-project')
            return str(state['root'])

        chat = self.module.SessionChat(rpc, resolve, lambda: ['demo'], str(receipts))
        return chat, rpc, state, other_root

    def test_history_rechecks_root_and_receipt_context_after_recent_for_empty_and_nonempty_pages(self):
        violations = []
        for empty in (False, True):
            for fence in ('root', 'context'):
                with self.subTest(empty_metadata=empty, fence=fence):
                    chat, rpc, state, other_root = self.make_chat(f'{fence}-{empty}', empty=empty)
                    changed = {'called': False}
                    original_recent = chat.receipts.recent

                    def recent_then_change(*args, **kwargs):
                        rows = original_recent(*args, **kwargs)
                        changed['called'] = True
                        if fence == 'root':
                            state['root'] = other_root
                        else:
                            rpc.context['context_id'] = 'b' * 64
                        return rows

                    chat.receipts.recent = recent_then_change
                    result = chat.history('demo', SID)
                    if not changed['called']:
                        violations.append(f'empty={empty}, fence={fence}: recent receipt hook did not run')
                    if result not in ({'error': 'stale'}, {'error': 'unavailable'}):
                        violations.append(f'empty={empty}, fence={fence}: exported after scope change')
                    if rpc.starts():
                        violations.append(f'empty={empty}, fence={fence}: history caused a writer call')
        self.assertEqual(violations, [], 'final authority proof must follow receipt loading on every path')

    def test_duplicate_native_item_id_across_turns_is_rejected_but_unique_page_within_caps_is_allowed(self):
        chat, rpc, _state, _other = self.make_chat('duplicate')
        first = turn('synthetic first turn', turn_id=TURN)
        second = turn('synthetic second turn', turn_id=OTHER)
        self.assertEqual(first['items'][0]['id'], second['items'][0]['id'])
        rpc.pages[None] = {'data': [first, second], 'nextCursor': None}
        rejected = chat.history('demo', SID)
        self.assertEqual(rejected, {'error': 'unavailable'},
                         'native item identities must be unique across the requested page, not only per turn')

        allowed_chat, allowed_rpc, _state, _other = self.make_chat('unique')
        unique_first = turn('synthetic first turn', turn_id=TURN)
        unique_second = turn('synthetic second turn', turn_id=OTHER)
        unique_first['items'][0]['id'] = 'agent-item-first'
        unique_second['items'][0]['id'] = 'agent-item-second'
        allowed_rpc.pages[None] = {'data': [unique_first, unique_second], 'nextCursor': None}
        accepted = allowed_chat.history('demo', SID)
        self.assertIn('turns', accepted, 'a well-formed page within the latest turn cap remains exportable')
        self.assertEqual([row['id'] for row in accepted['turns']], [TURN, OTHER])


if __name__ == '__main__':
    unittest.main()
