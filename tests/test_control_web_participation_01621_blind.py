"""Independent INV-PVER01..03 RED over the public PART API and real local RPC wire."""
from copy import deepcopy
from unittest.mock import patch

import participation_blind_support as support
from participation_blind_support import *


class NativeReportedVersion(support.Native):
    reported_version = '0.162.1'

    def result(self, method, params):
        if method == 'initialize':
            return {'userAgent': 'codex/' + self.reported_version + ' (synthetic)'}
        return super().result(method, params)


class Participation01621Blind(WireCase):
    def setUp(self):
        with patch.object(support, 'Native', NativeReportedVersion):
            super().setUp()

    def reconnect_reported_version(self, version):
        self.chat.close()
        self.rpc.close()
        self.native.reported_version = version
        self.rpc = self.module.InteractiveRPC(str(self.native.path), timeout=1)
        self.addCleanup(self.rpc.close)
        self.chat = self.make_chat()
        self.rpc('thread/read', dict(threadId=SID, includeTurns=False))

    def capture_actionable(self, identifier=7, params=None):
        self.questions()
        self.native.emit(support.callback(identifier, params))
        def current_actionable():
            value = self.questions()
            return value if any(item['state'] == 'actionable'
                                for item in value.get('questions', [])) else None
        dto = self.wait_for(current_actionable,
            'Current 0.162.1 callback did not become actionable after bounded source proof', timeout=5)
        row = next(item for item in dto['questions'] if item['state'] == 'actionable')
        return dto, row

    def test_INV_PVER01_01621_sampler_projects_fresh_rows_and_exact_final_witness(self):
        self.assertEqual(self.rpc.model_context()['native_version'], '0.162.1')
        self.native.status = dict(type='idle', activeFlags=[])
        self.native.turns = [dict(id=TURN, status='completed', items=[
            dict(id='completed-final-01621', type='agentMessage', phase='final_answer',
                 text='Synthetic completed response')], completedAt=1800000000)]
        row = self.wait_for(lambda: next((item for item in self.overview().get('rows', [])
                                          if item['sid'] == SID), None),
                            '0.162.1 loaded session was not published by the bounded sampler', timeout=5)
        self.assertEqual(row['activity'], 'idle')
        self.assertEqual(row['freshness']['state'], 'fresh')
        self.assertEqual((row['result']['status'], row['result']['ready'],
                          row['result']['turn_id'], row['result']['item_id']),
                         ('completed', True, TURN, 'completed-final-01621'))
        self.assertTrue(self.overview()['coverage']['partial'])
        self.assert_read_only()

    def test_INV_PVER02_01621_authoritative_callback_is_actionable_and_bound(self):
        dto, row = self.capture_actionable()
        self.assertEqual(self.rpc.model_context()['native_version'], '0.162.1')
        self.assertEqual(row['state'], 'actionable')
        self.assertEqual((row['turn_id'], row['item_id'], row['is_blocking']),
                         (TURN, 'question-item', True))
        self.assertEqual(dto['coverage']['partial'], True)
        self.assert_read_only()

    def test_INV_PVER02_selected_answer_is_once_only_on_native_01621_wire(self):
        dto, row = self.capture_actionable()
        first = self.answer(dto, row, action=ACTION, answers=deepcopy(ANSWER))
        self.assertEqual(first['state'], 'sent')
        repeated = self.answer(dto, row, action=ACTION, answers=deepcopy(ANSWER))
        self.assertEqual(repeated['state'], 'sent')
        self.wait_for(lambda: len(self.native.replies()) == 1,
                      'One selected answer should produce one native reply')
        self.assertEqual(self.native.replies(), [dict(id=7, result={'answers': ANSWER})])
        self.assertEqual(set(self.native.methods()) - support.READS, set())
        self.assertEqual(self.rpc.model_context()['native_version'], '0.162.1')

    def test_INV_SOV01_valid_read_shapes_allow_overview_but_callbacks_stay_closed(self):
        # The old INV-PVER01 version-only read deny is superseded by accepted
        # INV-SOV-01: native_version is diagnostic for bounded read-only reads.
        # Keep the independent callback-authority and no-mutation fences below.
        for version in ('0.160.0', '0.163.0'):
            with self.subTest(native_version=version):
                self.reconnect_reported_version(version)
                self.assertEqual(self.rpc.model_context()['native_version'], version)
                row = self.wait_for(lambda: next((item for item in self.overview().get('rows', [])
                                                  if item['sid'] == SID), None),
                                    'A valid bounded read must not be denied by native_version', timeout=5)
                self.assertEqual(row['freshness']['state'], 'fresh')
                self.questions()
                self.native.emit(support.callback())
                self.synchronize()
                dto = self.questions()
                self.assertFalse(any(row['state'] == 'actionable' for row in dto['questions']))
                self.assertEqual(self.native.replies(), [])
                self.assertEqual(set(self.native.methods()) - support.READS, set())

    def test_INV_PVER02_stale_context_never_answers_captured_01621_callback(self):
        dto, row = self.capture_actionable()
        before = self.rpc.model_context()['context_generation']
        self.native.emit(dict(method='config/updated', params={}))
        self.wait_for(lambda: self.rpc.model_context()['context_generation'] != before,
                      'Synthetic context update was not observed')
        result = self.answer(dto, row)
        self.assertNotEqual(result.get('state'), 'sent')
        self.assertEqual(self.native.replies(), [])
        self.assertNotIn('thread/resume', self.native.methods())

    def test_INV_PVER02_changed_root_revokes_01621_callback_and_answer_authority(self):
        dto, row = self.capture_actionable()
        self.bound_root = self.base / 'different-project-root'
        self.bound_root.mkdir(mode=0o700)
        current = self.questions()
        self.assertFalse(any(item['state'] == 'actionable' for item in current['questions']))
        self.assertNotEqual(self.answer(dto, row).get('state'), 'sent')
        self.assertEqual(self.native.replies(), [])
        self.assertNotIn('thread/resume', self.native.methods())
