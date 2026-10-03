#!/usr/bin/env python3
"""Blind default owned-rollout registry reader contract; own JSONL only."""
import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
try:
    runtime = importlib.import_module('_codex_task_runtime')
except ModuleNotFoundError as exc:
    if exc.name != '_codex_task_runtime':
        raise
    runtime = None

NAMES = sorted(['apply_patch', 'clock__curr_time', 'task_read', 'task_search', 'task_list', 'task_ask', 'task_done'])
FIXED = 'text(ALL_TOOLS.map(t=>t.name).sort())'


def row(kind, payload):
    return dict(timestamp='2026-10-03T00:00:00.000Z', type=kind, payload=payload)


class NativeRegistryReader(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(runtime, 'read_registry_evidence', None)),
            'public default read_registry_evidence is absent; owned native rollout proof is required')
        self.reader = runtime.read_registry_evidence
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='native-registry-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.codex_home = self.root / 'codex'
        self.sessions = self.codex_home / 'sessions/2026/10/03'
        self.sessions.mkdir(parents=True, mode=0o700)
        self.cwd = self.root / 'work'
        self.cwd.mkdir(mode=0o700)
        self.thread = str(uuid.uuid4())
        self.turn = str(uuid.uuid4())
        self.operation = str(uuid.uuid4())
        self.path = self.sessions / ('rollout-owned-' + self.thread + '.jsonl')
        from _codex_task_files import CodexTaskFiles
        from _codex_task_bridge import dynamic_tools
        descriptors = CodexTaskFiles.dynamic_tools() + dynamic_tools()
        for descriptor in descriptors:
            descriptor.update(type='function', deferLoading=False)
        self.call = dict(type='custom_tool_call', name='exec', call_id='owned-registry', input=FIXED)
        self.output = dict(type='custom_tool_call_output', call_id='owned-registry',
            output=[dict(type='input_text', text='native metadata prelude'),
                    dict(type='input_text', text=json.dumps(NAMES))])
        self.rows = [
            row('session_meta', dict(id=self.thread, cwd=str(self.cwd), cli_version='0.160.0',
                                    history_mode='legacy', dynamic_tools=descriptors)),
            row('event_msg', dict(type='task_started', turn_id=self.turn)),
            row('turn_context', dict(turn_id=self.turn, cwd=str(self.cwd))),
            row('event_msg', dict(type='user_message', client_id=self.operation, message='owned fixture prompt')),
            row('response_item', self.call), row('response_item', self.output)]
        self.environment = mock.patch.dict(os.environ, {'CODEX_HOME': str(self.codex_home)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.write()

    def write(self, rows=None, trailing=b''):
        with self.path.open('wb') as stream:
            for value in self.rows if rows is None else rows:
                stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b'\n')
            stream.write(trailing)
        self.path.chmod(0o600)

    def read(self, **overrides):
        args = dict(thread_path=str(self.path), thread_id=self.thread, turn_id=self.turn,
                    cwd=str(self.cwd), operation_id=self.operation)
        args.update(overrides)
        return self.reader(args['thread_path'], args['thread_id'], args['turn_id'], args['cwd'],
                           args['operation_id'], deadline=time.monotonic() + 3)

    def refused(self, **overrides):
        # None is reserved for incomplete owned records; forgery is hard refusal.
        try:
            value = self.read(**overrides)
        except Exception as exc:
            self.assertNotIsInstance(exc, (TypeError, AttributeError, AssertionError))
        else:
            self.fail('unsafe/foreign rollout returned instead of refusing: ' + repr(type(value)))

    def expected(self):
        return dict(schema=1, thread_id=self.thread, turn_id=self.turn, operation_id=self.operation,
            events=[dict(method='rawResponseItem/completed', params=dict(threadId=self.thread,
                turnId=self.turn, item=copy.deepcopy(item))) for item in (self.call, self.output)])

    def test_exact_native_raw_pair_has_only_bound_normalized_events(self):
        self.assertEqual(self.read(), self.expected())

    def test_benign_metadata_and_postproof_task_exec_do_not_enter_returned_evidence(self):
        post = dict(type='custom_tool_call', name='exec', call_id='ordinary-read',
                    input='text(await task_read({path:"tracked.txt"}))')
        self.write(self.rows + [row('response_item', post)])
        self.assertEqual(self.read(), self.expected())

    def test_partial_output_waits_then_complete_append_yields_exact_proof(self):
        encoded = json.dumps(self.rows[-1]).encode() + b'\n'
        self.write(self.rows[:-1], encoded[:-5])
        self.assertIsNone(self.read())
        with self.path.open('ab') as stream:
            stream.write(encoded[-5:])
        self.assertEqual(self.read(), self.expected())

    def test_owned_section_without_raw_pair_is_incomplete(self):
        self.write(self.rows[:4])
        self.assertIsNone(self.read())

    def test_old_turn_pair_is_ignored_before_exact_current_section(self):
        older = copy.deepcopy(self.rows[1:])
        old_turn = str(uuid.uuid4())
        old_operation = str(uuid.uuid4())
        older[0]['payload']['turn_id'] = old_turn
        older[1]['payload']['turn_id'] = old_turn
        older[2]['payload']['client_id'] = old_operation
        self.write(self.rows[:1] + older + self.rows[1:])
        self.assertEqual(self.read(), self.expected())

    def test_partial_trailing_foreign_json_cannot_supply_registry(self):
        self.write(self.rows[:4], json.dumps(self.rows[-1]).encode()[:-1])
        self.assertIsNone(self.read())

    def test_foreign_header_thread_cwd_release_or_history_refuses(self):
        for key, value in [('id', str(uuid.uuid4())), ('cwd', str(self.root)),
                           ('cli_version', '0.159.0'), ('history_mode', 'paginated')]:
            with self.subTest(key=key):
                rows = copy.deepcopy(self.rows)
                rows[0]['payload'][key] = value
                self.write(rows)
                self.refused()

    def test_wrong_current_turn_or_operation_never_borrows_old_registry(self):
        for field in ('turn', 'operation'):
            with self.subTest(field=field):
                if field == 'turn':
                    self.refused(turn_id=str(uuid.uuid4()))
                else:
                    self.refused(operation_id=str(uuid.uuid4()))

    def test_out_of_order_current_section_refuses(self):
        for order in ([0, 2, 1, 3, 4, 5], [0, 1, 3, 2, 4, 5], [0, 4, 5, 1, 2, 3]):
            with self.subTest(order=order):
                self.write([self.rows[i] for i in order])
                self.refused()

    def test_preproof_extra_exec_or_output_refuses(self):
        for item in (dict(type='custom_tool_call', name='exec', call_id='foreign', input='text(1)'),
                     dict(type='custom_tool_call_output', call_id='foreign', output='not registry')):
            with self.subTest(type=item['type']):
                self.write(self.rows[:4] + [row('response_item', item)] + self.rows[4:])
                self.refused()

    def test_fixed_program_and_call_output_correlation_are_exact(self):
        for field, value in [('input', FIXED + '; text(1)'), ('call_id', 'foreign')]:
            with self.subTest(field=field):
                rows = copy.deepcopy(self.rows)
                rows[4 if field == 'input' else 5]['payload'][field] = value
                self.write(rows)
                self.refused()

    def test_registry_missing_extra_or_conflicting_names_refuses(self):
        for names in (NAMES[:-1], NAMES + ['exec_command'], NAMES + [NAMES[0]]):
            with self.subTest(names=names):
                rows = copy.deepcopy(self.rows)
                rows[-1]['payload']['output'][-1]['text'] = json.dumps(names)
                self.write(rows)
                self.refused()

    def test_conflicting_second_fixed_pair_cannot_replace_first_proof(self):
        call = dict(self.call, call_id='conflicting-second')
        output = dict(self.output, call_id='conflicting-second', output=json.dumps(NAMES + ['exec_command']))
        self.write(self.rows + [row('response_item', call), row('response_item', output)])
        self.refused()

    def test_missing_header_and_foreign_turn_context_cwd_refuse(self):
        self.write(self.rows[1:])
        self.refused()
        rows = copy.deepcopy(self.rows)
        rows[2]['payload']['cwd'] = str(self.root)
        self.write(rows)
        self.refused()

    def test_duplicate_json_keys_nonfinite_and_invalid_json_refuse(self):
        for raw in (b'{"type":"event_msg","type":"response_item","payload":{}}\n',
                    b'{"type":"event_msg","payload":{"value":NaN}}\n', b'not-json\n'):
            with self.subTest(raw=raw):
                self.write(self.rows[:4], raw)
                self.refused()

    def test_symlink_and_hardlink_files_refuse(self):
        target = self.root / 'outside.jsonl'
        self.path.rename(target)
        for kind in ('symlink', 'hardlink'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    self.path.symlink_to(target)
                else:
                    os.link(target, self.path)
                self.refused()
                self.path.unlink()

    def test_symlink_parent_and_outside_sessions_path_refuse(self):
        outside = self.root / 'outside-sessions'
        self.sessions.rename(outside)
        self.sessions.symlink_to(outside, target_is_directory=True)
        self.refused()
        self.refused(thread_path=str(outside / self.path.name))

    def test_unsafe_file_or_ancestor_permissions_refuse(self):
        self.path.chmod(0o644)
        self.refused()
        self.path.chmod(0o600)
        self.sessions.chmod(0o777)
        self.refused()

    def test_line_record_and_snapshot_size_bounds_refuse_complete_json(self):
        benign = row('event_msg', dict(type='agent_message', message='x'))
        cases = [self.rows[:4] + [benign] * 100001 + self.rows[4:],
                 self.rows[:4] + [row('event_msg', dict(type='agent_message', message='x' * (1024 * 1024)))] + self.rows[4:],
                 self.rows[:4] + [row('event_msg', dict(type='agent_message', message='x' * 400000))] * 85 + self.rows[4:]]
        for rows in cases:
            with self.subTest(records=len(rows)):
                self.write(rows)
                self.refused()


if __name__ == '__main__':
    unittest.main()
