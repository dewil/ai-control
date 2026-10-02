"""Specification tests: server-selected Codex model and reasoning effort."""
import importlib.machinery
import importlib.util
import pathlib
import tempfile
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('codex_defaults_test', ROOT / 'bin' / '_codex_rc.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
loader = importlib.machinery.SourceFileLoader('bot_defaults_test', str(ROOT / 'bin' / 'claude-agent-tgbot'))
spec = importlib.util.spec_from_loader(loader.name, loader)
bot = importlib.util.module_from_spec(spec)
loader.exec_module(bot)


class SystemDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = self.tmp.name
        self.calls = []
        self.rows = []
        self.responses = {}
        self.service = mod.CodexSessions(self.rpc, lambda _: self.cwd)

    def thread(self, **metadata):
        return dict(id=str(uuid.uuid4()), cwd=self.cwd, name='Session', preview='Seed',
                    updatedAt=123, status={'type': 'idle'}, **metadata)

    def rpc(self, method, params):
        self.calls.append((method, params))
        if method in self.responses:
            response = self.responses[method]
            if isinstance(response, Exception):
                raise response
            return response
        return {
            'thread/list': {'data': self.rows, 'nextCursor': None},
            'remoteControl/status/read': {'status': 'connected'},
            'model/list': {'data': [{'model': 'gpt-6-astra'}], 'nextCursor': None},
            'thread/name/set': {},
            'turn/start': {'turn': {'id': 'seed', 'status': 'inProgress'}},
        }[method]

    def assert_metadata(self, row, model, effort):
        self.assertEqual(row.get('model'), model)
        self.assertEqual(row.get('reasoning_effort'), effort)

    def test_two_creations_inherit_changing_defaults_without_overrides(self):
        for model, effort in [('gpt-6.1-sol', 'low'), ('server-next-model', 'high')]:
            with self.subTest(model=model):
                self.calls.clear()
                thread = self.thread()
                self.responses['thread/start'] = dict(thread=thread, model=model, reasoningEffort=effort)
                row = self.service.create_session('project')
                self.assert_metadata(row, model, effort)
                self.assertEqual(row['sid'], thread['id'])
                for method, params in self.calls:
                    if method in ('thread/start', 'turn/start'):
                        self.assertFalse(set(params) & {'model', 'effort', 'reasoningEffort',
                                                       'collaborationMode', 'serviceTier'})
                        self.assertNotIn('model_reasoning_effort', params.get('config', {}))
                start = next(p for m, p in self.calls if m == 'thread/start')
                for key, value in dict(cwd=self.cwd, ephemeral=False, sandbox='workspace-write',
                                       approvalPolicy='on-request').items():
                    self.assertEqual(start[key], value)
                self.assertEqual(sum(m == 'turn/start' for m, _ in self.calls), 1)
                self.assertNotIn('model/list', [m for m, _ in self.calls])

    def test_creation_does_not_require_model_list_or_astra(self):
        self.responses['model/list'] = AssertionError('model/list is not a creation prerequisite')
        self.responses['thread/start'] = dict(thread=self.thread(), model='server-only-model', reasoningEffort='medium')
        self.assert_metadata(self.service.create_session('project'), 'server-only-model', 'medium')
        self.assertNotIn('model/list', [m for m, _ in self.calls])

    def test_start_top_level_metadata_is_authoritative(self):
        self.responses['thread/start'] = dict(thread=self.thread(model='nested', reasoningEffort='low'),
                                              model='effective', reasoningEffort='high')
        self.assert_metadata(self.service.create_session('project'), 'effective', 'high')

    def test_missing_null_and_empty_start_metadata_preserve_nested_values(self):
        for metadata in ({}, {'model': None, 'reasoningEffort': None}, {'model': '', 'reasoningEffort': ''}):
            with self.subTest(metadata=metadata):
                self.responses['thread/start'] = dict(thread=self.thread(model='nested', reasoningEffort='medium'), **metadata)
                self.assert_metadata(self.service.create_session('project'), 'nested', 'medium')
                self.responses['thread/start'] = dict(thread=self.thread(), **metadata)
                self.assert_metadata(self.service.create_session('project'), None, None)

    def test_invalid_create_metadata_reports_known_uuid_and_never_seeds(self):
        for location in ('top', 'thread'):
            for field in ('model', 'reasoningEffort'):
                for invalid in (42, False, [], {}):
                    with self.subTest(location=location, field=field, invalid=invalid):
                        self.calls.clear()
                        thread = self.thread()
                        response = {'thread': thread}
                        (response if location == 'top' else thread)[field] = invalid
                        self.responses['thread/start'] = response
                        with self.assertRaises(Exception) as raised:
                            self.service.create_session('project')
                        error = raised.exception
                        self.assertIn(field, str(error))
                        self.assertIn(thread['id'], str(error) + repr(vars(error)))
                        self.assertNotIn('turn/start', [m for m, _ in self.calls])

    def test_normalization_maps_optional_effort_and_rejects_invalid_types(self):
        self.assert_metadata(mod.normalize_thread(self.thread(model='server', reasoningEffort='high')), 'server', 'high')
        for unknown in (None, ''):
            self.assert_metadata(mod.normalize_thread(self.thread(model=unknown, reasoningEffort=unknown)), None, None)
        self.assert_metadata(mod.normalize_thread(self.thread()), None, None)
        for field in ('model', 'reasoningEffort'):
            for invalid in (0, True, [], {}):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError) as raised:
                        mod.normalize_thread(self.thread(**{field: invalid}))
                    self.assertIn(field, str(raised.exception))

    def test_get_and_list_expose_metadata_without_per_thread_rpc(self):
        thread = self.thread(model='server', reasoningEffort='low')
        self.rows = [thread]
        short = thread['id'].replace('-', '')[:12]
        self.assert_metadata(self.service.get_session('project', short), 'server', 'low')
        self.calls.clear()
        result = self.service.list_sessions('project')
        self.assert_metadata(result['rows'][0], 'server', 'low')
        self.assertEqual([m for m, _ in self.calls], ['thread/list'])

    def test_resume_authoritative_metadata_preserves_identity_without_overrides(self):
        thread = self.thread(model='previous', reasoningEffort='low')
        self.rows = [thread]
        self.responses['thread/resume'] = dict(thread=thread, model='effective', reasoningEffort='high')
        row = self.service.resume_session('project', thread['id'].replace('-', '')[:12])
        self.assertEqual(row['sid'], thread['id'])
        self.assert_metadata(row, 'effective', 'high')
        self.assertEqual(next(p for m, p in self.calls if m == 'thread/resume'), {'threadId': thread['id']})
        self.assertFalse({'thread/start', 'turn/start', 'model/list'} & {m for m, _ in self.calls})

    def test_resume_missing_or_null_metadata_keeps_known_values(self):
        thread = self.thread(model='known', reasoningEffort='medium')
        self.rows = [thread]
        for metadata in ({}, {'model': None, 'reasoningEffort': None}):
            with self.subTest(metadata=metadata):
                self.responses['thread/resume'] = dict(thread=thread, **metadata)
                self.assert_metadata(self.service.resume_session('project', thread['id'].replace('-', '')[:12]), 'known', 'medium')

    def test_creation_button_is_generic_codex(self):
        kb = bot.codex_list_kb('project', [])
        button = next(b for row in kb['inline_keyboard'] for b in row if b.get('callback_data') == 'c:n:project')
        self.assertIn('Codex', button['text'])
        self.assertNotIn('astra', button['text'].lower())
        self.assertNotIn('sol', button['text'].lower())

    def test_card_escapes_effective_model_and_effort_and_omits_unknown_effort(self):
        row = dict(sid=str(uuid.uuid4()), short='123456781234', title='Session', cwd=self.cwd,
                   status='idle', mtime=123, model='<model&>', reasoning_effort='<effort&>')
        text, _ = bot.codex_card_view('project', row)
        self.assertIn('&lt;model&amp;&gt;', text)
        self.assertIn('&lt;effort&amp;&gt;', text)
        self.assertNotIn('<effort&>', text)
        for unknown in (None, ''):
            row['reasoning_effort'] = unknown
            text, _ = bot.codex_card_view('project', row)
            self.assertNotIn('medium', text.lower())
            self.assertNotIn('high', text.lower())
            self.assertNotIn('default', text.lower())


if __name__ == '__main__':
    unittest.main()
