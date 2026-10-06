"""Source-blind SessionChat integration contracts for configured origins."""
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import os
import shutil
import sys
import tempfile
import unittest
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))

import _control_web_sessions as web_sessions  # noqa: E402

SID = '11111111-1111-4111-8111-111111111111'
OTHER = '44444444-4444-4444-8444-444444444444'
MESSAGE = '22222222-2222-4222-8222-222222222222'
UNKNOWN_MESSAGE = '55555555-5555-4555-8555-555555555555'
TURN = '33333333-3333-4333-8333-333333333333'
CONTEXT = {
    'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
    'context_id': 'a' * 64, 'transport_generation': 3,
    'context_generation': 7, 'native_version': '0.160.0',
}


@dataclass(frozen=True)
class Reservation:
    record: object


@dataclass(frozen=True)
class LoadedWitness:
    reservation: object
    context: object
    session: object


@dataclass(frozen=True)
class UnavailableHistoryWitness:
    reservation: object
    context: object
    session: object
    needs_native_attention: bool


def witness(sid, root, *, attention=False):
    reservation = Reservation(MappingProxyType({
        'schema': 1, 'kind': 'configured_session_create', 'project': 'demo',
        'operation_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        'context_id': CONTEXT['context_id'], 'root': str(root), 'digest': 'b' * 64,
        'status': 'accepted', 'sid': sid, 'created': 1700000000000000000,
    }))
    frozen_context = MappingProxyType(dict(CONTEXT))
    session = MappingProxyType({
        'sid': sid, 'project': 'demo', 'vendor': 'codex',
        'context_mode': 'configured', 'title': None,
    })
    if attention:
        return UnavailableHistoryWitness(reservation, frozen_context, session, True)
    return LoadedWitness(reservation, frozen_context, session)


class SyntheticRPC:
    def __init__(self, root):
        self.root = Path(root)
        self.calls = []
        self.fenced_calls = []
        self.turn_start_error = None
        self.turns_error = None
        self.turns_response = {'data': [], 'nextCursor': None}
        self.list_response = {'data': [], 'nextCursor': None}
        self.metadata_status = {'type': 'idle'}
        self.context = dict(CONTEXT)
        self.models_response = {'data': [{
            'id': 'gpt-ui', 'model': 'gpt-wire', 'displayName': 'Synthetic model',
            'description': 'Synthetic model fixture',
            'supportedReasoningEfforts': [
                {'reasoningEffort': 'low', 'description': 'Low'}],
            'defaultReasoningEffort': 'low', 'isDefault': True, 'hidden': False,
        }], 'nextCursor': None}

    def receipt_context(self):
        return {'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
                'context_id': CONTEXT['context_id']}

    def model_context(self):
        return dict(self.context)

    def call_in_generation(self, method, params, *, transport_generation,
                           context_generation, timeout=None):
        self.fenced_calls.append((method, dict(params), transport_generation, context_generation))
        if (transport_generation, context_generation) != (
                self.context['transport_generation'], self.context['context_generation']):
            raise RuntimeError('synthetic generation changed')
        return self(method, params)

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method in ('thread/read', 'thread/resume'):
            return {'thread': {'id': params.get('threadId'), 'cwd': str(self.root),
                               'name': 'Synthetic native title',
                               'status': dict(self.metadata_status)}}
        if method == 'thread/list':
            return self.list_response
        if method == 'thread/turns/list':
            if self.turns_error:
                raise self.turns_error
            return self.turns_response
        if method == 'model/list':
            return self.models_response
        if method == 'turn/start':
            if self.turn_start_error:
                raise self.turn_start_error
            return {'turn': {'id': TURN}}
        raise AssertionError('unexpected synthetic RPC method: ' + method)

    def methods(self):
        return [method for method, _ in self.calls]


class FakeConfiguredCreator:
    def __init__(self, root):
        self.root = Path(root)
        self.origins = {SID: witness(SID, root)}
        self.overlay_result = {'sessions': [], 'truncated': False}
        self.loaded_calls = []
        self.history_calls = []
        self.loaded_error = {}
        self.history_error = {}
        self.history_none = set()
        self.deadlines = []

    def loaded_origin(self, project, sid, *, deadline=None):
        self.deadlines.append(('loaded_origin', deadline))
        self.loaded_calls.append((project, sid))
        error = self.loaded_error.get(sid)
        if error is not None:
            raise error
        return self.origins.get(sid)

    def unavailable_history(self, project, sid, *, deadline=None):
        self.deadlines.append(('unavailable_history', deadline))
        self.history_calls.append((project, sid))
        error = self.history_error.get(sid)
        if error is not None:
            raise error
        if sid in self.history_none:
            return None
        if sid not in self.origins:
            return None
        return witness(sid, self.root, attention=True)

    def overlay(self, project, *, deadline=None):
        self.deadlines.append(('overlay', deadline))
        return self.overlay_result


class SessionChatConfiguredOrigin(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='control-chat-origin-', dir='/var/tmp'))
        self.base.chmod(0o700)
        self.root = self.base / 'project'
        self.root.mkdir(mode=0o700)
        self.root = self.root.resolve(strict=True)
        self.allowed = {'demo'}
        self.rpc = SyntheticRPC(self.root)
        self.creator = FakeConfiguredCreator(self.root)
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def resolve(self, project):
        if project not in self.allowed:
            raise ValueError('synthetic grant denied')
        return str(self.root)

    def chat(self):
        params = inspect.signature(web_sessions.SessionChat).parameters
        self.assertIn('configured_creator', params,
                      'SessionChat optional trusted configured_creator seam is absent')
        return web_sessions.SessionChat(
            self.rpc, self.resolve, lambda: sorted(self.allowed),
            str(self.base / 'web-send-receipts'), configured_creator=self.creator,
            model_context=self.rpc.model_context, model_clock=lambda: 100.0)

    def assert_error(self, value, code):
        self.assertEqual(value, {'error': code})

    def test_loaded_origin_inherit_send_bypasses_resume_and_replay_needs_no_origin(self):
        chat = self.chat()
        sent = chat.send('demo', SID, MESSAGE, 'Synthetic first message')
        self.assertEqual(sent, {'status': 'accepted', 'message_id': MESSAGE, 'turn_id': TURN})
        self.assertEqual(self.rpc.methods().count('turn/start'), 1)
        self.assertNotIn('thread/resume', self.rpc.methods())
        self.assertGreaterEqual(self.creator.loaded_calls.count(('demo', SID)), 2,
                                'origin must be revalidated under the existing message lock')
        lookup_count = len(self.creator.loaded_calls)

        self.creator.loaded_error[SID] = web_sessions._DomainError('unavailable')
        replay = chat.send('demo', SID, MESSAGE, 'Synthetic first message')
        self.assertEqual(replay, sent)
        self.assertEqual(len(self.creator.loaded_calls), lookup_count,
                         'schema-2 exact receipt replay precedes origin admission')
        self.assertEqual(self.rpc.methods().count('turn/start'), 1)
        self.assertNotIn('thread/resume', self.rpc.methods())

    def test_explicit_model_send_on_loaded_origin_uses_direct_turn_start(self):
        chat = self.chat()
        catalog = chat.models('demo', SID)
        self.assertEqual(catalog['selection_support'], 'available')
        selection = {'catalog_id': catalog['catalog_id'], 'model_id': 'gpt-ui', 'effort': 'low'}
        sent = chat.send('demo', SID, MESSAGE, 'Synthetic selected model message', selection)
        self.assertEqual(sent, {'status': 'accepted', 'message_id': MESSAGE, 'turn_id': TURN})
        starts = [params for method, params in self.rpc.calls if method == 'turn/start']
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]['model'], 'gpt-wire')
        self.assertEqual(starts[0]['effort'], 'low')
        self.assertNotIn('thread/resume', self.rpc.methods())
        self.assertNotIn('thread/start', self.rpc.methods(),
                         'sending to an existing loaded thread starts only a turn')

    def test_unindexed_random_loaded_sid_keeps_existing_resume_path(self):
        self.creator.origins.pop(OTHER, None)
        chat = self.chat()
        sent = chat.send('demo', OTHER, MESSAGE, 'Synthetic ordinary session send')
        self.assertEqual(sent, {'status': 'accepted', 'message_id': MESSAGE, 'turn_id': TURN})
        self.assertEqual(self.creator.loaded_calls, [('demo', OTHER)])
        self.assertEqual(self.rpc.methods().count('thread/resume'), 1)
        self.assertEqual(self.rpc.methods().count('turn/start'), 1)

    def test_malformed_indexed_authority_never_falls_back_to_resume(self):
        self.creator.loaded_error[SID] = web_sessions._DomainError('unavailable')
        chat = self.chat()
        result = chat.send('demo', SID, MESSAGE, 'Synthetic malformed origin')
        self.assert_error(result, 'unavailable')
        self.assertNotIn('thread/resume', self.rpc.methods())
        self.assertNotIn('turn/start', self.rpc.methods())

    def test_initial_history_failure_returns_honest_variant_with_recent_receipt(self):
        self.rpc.turn_start_error = web_sessions.RPCRejected('synthetic acknowledgement uncertain')
        chat = self.chat()
        sent = chat.send('demo', SID, UNKNOWN_MESSAGE, 'Synthetic uncertain message')
        self.assertEqual(sent, {'status': 'delivery_unknown',
                                'message_id': UNKNOWN_MESSAGE, 'turn_id': None})
        self.rpc.turn_start_error = None
        self.rpc.turns_error = web_sessions.RPCRejected('synthetic not materialized')
        self.rpc.metadata_status = {'type': 'active', 'activeFlags': ['waitingOnUserInput']}
        result = chat.history('demo', SID)
        self.assertEqual(result, {
            'history_state': 'unavailable', 'reason': 'unavailable',
            'recent_sends': [{'status': 'delivery_unknown',
                              'message_id': UNKNOWN_MESSAGE, 'turn_id': None}],
            'needs_native_attention': True,
        })
        self.assertFalse({'turns', 'next_cursor', 'truncated'} & set(result))
        self.assertEqual(self.creator.history_calls, [('demo', SID)])
        self.assertEqual(self.rpc.methods().count('turn/start'), 1)
        self.assertNotIn('thread/resume', self.rpc.methods())
        self.assertNotIn('not materialized', json.dumps(result))

    def test_history_failure_without_origin_or_with_bad_cursor_never_fakes_empty_history(self):
        chat = self.chat()
        self.creator.origins.pop(SID)
        self.rpc.turns_error = web_sessions.RPCRejected('synthetic RPC failure')
        self.assert_error(chat.history('demo', SID), 'unavailable')
        self.assertEqual(self.creator.history_calls, [('demo', SID)])

        self.creator.history_calls.clear()
        self.assert_error(chat.history('demo', SID, 'opaque-cursor'), 'unavailable')
        self.assertEqual(self.creator.history_calls, [],
                         'only a failed initial-page request may ask for unavailable-history proof')
        self.assertNotIn('turns', json.dumps(self.rpc.turns_response))

    def test_malformed_history_response_does_not_enter_unavailable_variant(self):
        chat = self.chat()
        self.rpc.turns_response = {'data': 'malformed', 'nextCursor': None}
        self.assert_error(chat.history('demo', SID), 'unavailable')
        self.assertEqual(self.creator.history_calls, [])

    def test_sessionchat_has_no_client_origin_or_identity_switch_and_rejects_bad_cursor(self):
        chat = self.chat()
        send_params = inspect.signature(web_sessions.SessionChat.send).parameters
        self.assertFalse({'context_mode', 'provider_id', 'context_id', 'root', 'sid_override'}
                         & set(send_params))
        self.assert_error(chat.history('demo', SID, ''), 'invalid_request')
        self.assert_error(chat.history('../private', SID), 'invalid_request')
        self.assert_error(chat.send('demo', SID[:8], MESSAGE, 'Synthetic text'), 'invalid_request')
        self.assertEqual(self.creator.loaded_calls, [])
        self.assertEqual(self.creator.history_calls, [])
        self.assertEqual(self.rpc.methods(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
