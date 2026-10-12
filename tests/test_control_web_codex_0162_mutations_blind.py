"""Independent INV-COMPAT-03/04 regression from the accepted 0.162.1 spec.

Only public adapters, synthetic Unix wire and existing public test fixtures.
No provider credentials, daemon or working sessions are used.
"""
import importlib
import json
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_control_web_read_capabilities_support import NativeCase, SID, MID, TURN, WRITES
from test_control_web_session_chat_contract import ORIGIN, PASSWORD, SECRET
import test_control_web_session_models_http_broker as broker_fixture
import native_queue_blind_support as queue_fixture
from test_control_web_native_queue_admission_blind import UnloadedQueueRPC

VERSION = '0.162.1'
TEXT = 'Synthetic 0.162.1 compatibility nonce'


def reviewed_capabilities():
    return dict(schema=1, native_version=VERSION, version_source='initialize_reported',
                version_review='reviewed', read_status='compatible', operations={
        'sessions_read': dict(supported=True, reason=None),
        'history_read': dict(supported=None, reason='not_observed'),
        'model_selection': dict(supported=True, reason=None),
        'send': dict(supported=True, reason=None),
        'create': dict(supported=True, reason=None),
        'rename': dict(supported=True, reason=None),
        'queue': dict(supported=None, reason='not_observed')})


class Codex0162WireBlind(NativeCase):
    def setUp(self):
        super().setUp()
        self.native.agent = 'codex/' + VERSION + ' (synthetic)'

    def fenced(self, method, params, context):
        return self.rpc.call_in_generation(method, params,
            transport_generation=context['transport_generation'],
            context_generation=context['context_generation'], timeout=1)

    def test_reviewed_capabilities_enable_send_without_inventing_observations(self):
        # INV-COMPAT-03: per-session proof remains required after version admission.
        value = self.chat.capabilities('demo', SID)
        self.assertEqual(value, reviewed_capabilities())
        self.assertEqual(self.native.methods(), ['thread/read'])
        self.assertFalse(self.send_path.exists())

    def test_public_send_is_accepted_and_reaches_exactly_one_native_turn(self):
        # INV-COMPAT-03: capability admission must agree with the real send path.
        self.prepare()
        chat = self.sessions.SessionChat(self.rpc, self.resolve, lambda: ['demo'], str(self.send_path),
                                         model_context=self.rpc.model_context)
        result = chat.send('demo', SID, MID, TEXT)
        self.assertEqual(result, dict(status='accepted', message_id=MID, turn_id=TURN))
        starts = [frame['params'] for frame in self.native.frames if frame.get('method') == 'turn/start']
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]['threadId'], SID)
        self.assertEqual(starts[0]['input'][0]['text'], TEXT)
        self.assertEqual(starts[0]['clientUserMessageId'], MID)
        self.assertFalse({'account', 'provider', 'config'} & set(starts[0]))

    def test_both_public_transport_paths_admit_reviewed_ordinary_and_queue_methods(self):
        # INV-COMPAT-03 INV-COMPAT-04: neither ordinary nor fenced dispatch stays version-locked.
        context = self.prepare()
        requests = [
            ('thread/start', {'cwd': str(self.root)}),
            ('thread/resume', {'threadId': SID}),
            ('thread/name/set', {'threadId': SID, 'name': 'Synthetic title'}),
            ('model/list', {'cursor': None, 'limit': 20, 'includeHidden': False}),
            ('turn/start', {'threadId': SID, 'input': [{'type': 'text', 'text': TEXT}], 'clientUserMessageId': MID}),
            ('turn/steer', {'threadId': SID, 'expectedTurnId': TURN, 'input': [{'type': 'text', 'text': TEXT}]}),
            ('thread/queue/list', {'threadId': SID, 'cursor': None, 'limit': 64}),
            ('thread/queue/add', {'threadId': SID, 'input': [{'type': 'text', 'text': TEXT}], 'clientUserMessageId': MID}),
            ('thread/queue/delete', {'threadId': SID, 'queuedSubmissionId': queue_fixture.QID}),
            ('thread/queue/start', {'threadId': SID})]
        for mode in ('ordinary', 'fenced'):
            for method, params in requests:
                with self.subTest(mode=mode, method=method):
                    self.invoke(lambda: self.rpc(method, params) if mode == 'ordinary' else self.fenced(method, params, context))
        self.assertEqual(self.native.methods(), [method for method, _ in requests] * 2)

    def test_generation_and_unsupported_account_context_still_refuse_without_effects(self):
        # INV-COMPAT-03: reviewed version does not replace generation/account proof.
        context = self.prepare()
        self.native.ws.send(json.dumps(dict(method='account/updated', params={})))
        deadline = time.monotonic() + 1
        while self.rpc.model_context()['context_generation'] == context['context_generation'] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertGreater(self.rpc.model_context()['context_generation'], context['context_generation'])
        self.rpc_rejected(lambda: self.fenced('turn/start', {'threadId': SID, 'input': []}, context))
        unsupported = dict(self.rpc.model_context(), context_kind='bound')
        before = self.files()
        with patch.object(self.rpc, 'prepare_context', return_value=unsupported), patch.object(self.rpc, 'model_context', return_value=unsupported):
            chat = self.sessions.SessionChat(self.rpc, self.resolve, lambda: ['demo'], str(self.send_path),
                                            model_context=self.rpc.model_context)
            self.assert_closed(chat.send('demo', SID, MID, TEXT))
        self.assertEqual(self.files(), before)
        self.assertFalse(WRITES & set(self.native.methods()))

    def test_capabilities_survive_registry_owner_broker_socket_and_http(self):
        # INV-COMPAT-03: all production DTO validators agree on the reviewed version.
        self.module = importlib.import_module('_control_web_broker')
        registry = self.base / 'registry'; registry.mkdir(mode=0o700)
        self.backend = self.module.RegistryBackend(str(registry), str(queue_fixture.ROOT / 'bin'), sessions=self.chat)
        self.socket_path = str(self.base / 'broker.sock')
        self.stop = threading.Event(); self.errors = []; self.worker = None
        self.shutdown = lambda: broker_fixture.SessionModelsBroker.shutdown(self)
        broker_fixture.SessionModelsBroker.start(self)
        backend = self.module.SocketBackend(self.socket_path)
        self.assertEqual(backend.session_capabilities('demo', SID), reviewed_capabilities())
        web = importlib.import_module('_control_web'); now = 1800000000
        config = dict(origin=ORIGIN, password_hash=web.hash_password(PASSWORD), totp_secret=SECRET,
                      session_ttl=60, secure_cookie=True)
        with TestClient(web.create_app(config, backend, clock=lambda: now), base_url=ORIGIN) as client:
            login = client.post('/api/login', json=dict(username='owner', password=PASSWORD,
                                totp=web.totp_code(SECRET, now)), headers={'Origin': ORIGIN})
            self.assertEqual(login.status_code, 200)
            response = client.get('/api/session-capabilities?project=demo&sid=' + SID)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), reviewed_capabilities())


class Codex0162QueueBlind(queue_fixture.QueueModuleCase):
    def setUp(self):
        super().setUp()
        self.rpc.context['native_version'] = VERSION

    def test_queue_list_enqueue_cancel_and_uuid_replay_keep_native_authority(self):
        # INV-COMPAT-04: scope proof, digest reservation, queue identity and idempotency.
        self.assertEqual(self.queue(), queue_fixture.queue_dto([]))
        self.rpc.before_add = lambda: self.assert_reservation(queue_fixture.MID)
        first = self.enqueue()
        self.assertEqual(first, dict(status='queued', message_id=queue_fixture.MID, queued_submission_id=queue_fixture.QID))
        self.assertEqual(self.invoke('enqueue', 'demo', SID, MID, queue_fixture.TEXT, chat=self.new_chat()), first)
        adds = self.rpc.calls_for('thread/queue/add')
        self.assertEqual(len(adds), 1)
        self.assertEqual(set(adds[0]), {'threadId', 'input', 'clientUserMessageId'})
        self.assertEqual((adds[0]['threadId'], adds[0]['clientUserMessageId']), (SID, MID))
        self.assertEqual([(item['type'], item['text']) for item in adds[0]['input']], [('text', queue_fixture.TEXT)])
        self.assertEqual(self.queue()['rows'], [queue_fixture.public_row()])
        self.assertEqual(self.cancel()['status'], 'cancelled')
        self.assertEqual(self.rpc.calls_for('thread/queue/delete'), [dict(threadId=SID, queuedSubmissionId=queue_fixture.QID)])
        self.assertNotIn('turn/start', self.rpc.methods())

    def test_unloaded_explicit_enqueue_resumes_once_with_captured_context(self):
        # INV-COMPAT-04: admitted queue version also reaches existing resume admission.
        self.rpc = UnloadedQueueRPC(self.project); self.rpc.context['native_version'] = VERSION
        self.chat = self.new_chat(); self.rpc.before_resume = lambda: self.assert_reservation(MID)
        self.assertEqual(self.enqueue().get('status'), 'queued')
        methods = self.rpc.methods()
        self.assertEqual(methods.count('thread/resume'), 1)
        self.assertLess(methods.index('thread/resume'), methods.index('thread/queue/add'))
        self.assertTrue(any(method == 'thread/resume' and (transport, context) == (3, 7)
                            for method, params, transport, context in self.rpc.fenced_calls))

    def test_lost_queue_ack_is_never_automatically_repeated_after_restart(self):
        # INV-COMPAT-04: 0.162.1 does not weaken unknown-delivery handling.
        self.rpc.add_error = TimeoutError('Synthetic ACK loss')
        self.assertEqual(self.enqueue().get('status'), 'delivery_unknown')
        self.rpc.queue_pages[None]['data'] = []; self.rpc.add_error = None
        self.assertEqual(self.invoke('enqueue', 'demo', SID, MID, queue_fixture.TEXT, chat=self.new_chat()).get('status'), 'delivery_unknown')
        self.assertEqual(len(self.rpc.calls_for('thread/queue/add')), 1)
        self.assertNotIn('turn/start', self.rpc.methods())

    def test_old_unreviewed_and_drifted_contexts_do_not_reserve_or_dispatch(self):
        # INV-SOV-06: structural reads never authorize unreviewed mutations.
        # INV-COMPAT-03 INV-COMPAT-04: exact version sets and existing scope fences.
        for version in ('0.160.0', '0.999.0'):
            with self.subTest(version=version):
                self.rpc.context['native_version'] = version
                result = self.queue()
                self.assertEqual((result['supported'], result['reason']), (False, 'unsupported_queue'))
                self.enqueue()
                self.assertEqual(self.mutation_methods(), [])
                self.assertEqual(self.records(), [])
        self.rpc.context['native_version'] = VERSION
        self.rpc.after_queue = lambda: self.rpc.context.update(context_generation=8)
        self.assertIn(self.enqueue().get('error'), ('stale', 'unavailable'))
        self.assertEqual(self.mutation_methods(), [])
        self.assertEqual(self.records(), [])


if __name__ == '__main__':
    unittest.main()
