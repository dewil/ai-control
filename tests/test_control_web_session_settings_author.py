"""Supplemental public producer/DTO fences; synthetic metadata only."""
import json
import subprocess
import unittest
from pathlib import Path
import test_control_web_session_settings_blind as fixture


class SessionSettingsAuthor(unittest.TestCase):
    setUp = fixture.SessionSettingsBlind.setUp
    get_context = fixture.SessionSettingsBlind.get_context

    def test_project_validation_transport_change_rejects_whole_read(self):
        calls = []; changed = []

        def project_path(project):
            calls.append(project)
            if len(calls) == 2:
                self.context['transport_generation'] += 1
                changed.append(True)
            return str(self.root)

        chat = self.module.SessionChat(
            self.rpc, project_path, lambda: ['demo'], str(self.root.parent / 'receipts'),
            model_context=self.get_context, model_clock=lambda: self.now)
        result = chat.history('demo', fixture.SID)
        # INV-CAP-02: root validation may run again for the final observation fence.
        self.assertEqual(changed, [True], 'The explicit transport change must have been injected')
        self.assertEqual(result, {'error': 'stale'})
        self.assertNotIn('session_settings', result)
        self.assertEqual(sum(method == 'thread/read' for method, _ in self.rpc.calls), 1)

    def test_unicode_word_boundaries_match_existing_export_policy(self):
        broker = fixture.feature(self, '_control_web_broker')
        source = (Path(__file__).resolve().parents[1] / 'bin/_control_web.js').read_text()
        validator = source[source.index('function validSessionSetting('):
                           source.index('function sessionSettingsSnapshot(')]
        values = ['модель' + 'x' * 40, 'x' * 40 + 'модель', '😀' * 256,
                  'x' * 40, 'token=synthetic-private-value', 'bad\ud800',
                  'custom:X', 'bearer synthetic-private-value']
        script = (validator + 'console.log(JSON.stringify(' + json.dumps(values) +
                  '.map(validSessionSetting)));')
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True,
                                timeout=5, check=True)
        self.assertEqual(json.loads(result.stdout),
                         [broker.valid_session_setting(value) for value in values])

    def test_unavailable_dto_validates_optional_settings_without_losing_receipts(self):
        broker = fixture.feature(self, '_control_web_broker')
        base = {'history_state': 'unavailable', 'reason': 'unavailable', 'recent_sends': []}
        value = dict(schema=1, source='thread_read', scope='configured_or_persisted',
                     model='producer-model', effort=None, age_ms=14999, expires_in_ms=1)
        self.assertEqual(broker.history_result({**base, 'session_settings': value}),
                         {**base, 'session_settings': value})
        for invalid in ({**value, 'model': 'token=synthetic-private-value'},
                        {**value, 'schema': True}, {**value, 'expires_in_ms': 2}):
            with self.subTest(invalid=invalid):
                self.assertEqual(broker.history_result({**base, 'session_settings': invalid}), base)
        self.assertEqual(broker.history_result({**base, 'unknown': True}), {'error': 'unavailable'})


if __name__ == '__main__':
    unittest.main()
