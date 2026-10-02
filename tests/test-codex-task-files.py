#!/usr/bin/env python3
"""Blind public-contract acceptance tests for CXTASK-FILES (stdlib only)."""
import contextlib
import importlib
import json
import math
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from _codex_task_bridge import TaskBinding


class Contract(unittest.TestCase):
    def setUp(self):
        # Missing implementation is an intentional RED, never a skipped test.
        self.module = importlib.import_module('_codex_task_files')
        self.Error = self.module.FileToolError
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agent = Path(self.tmp.name) / 'registry/agents/taskone'
        self.work = self.agent / 'work'
        self.work.mkdir(parents=True, mode=0o700)
        self.binding = TaskBinding('a' * 32, 'event', str(self.agent), 'thread', 'turn')
        self.active = False
        self.calls = 0
        self.now = 0.0
        self.on_exit = None
        self.api = self.module.CodexTaskFiles(self.binding, guard=self.guard, clock=lambda: self.now)

    @contextlib.contextmanager
    def guard(self, binding, *, deadline):
        self.assertEqual(binding, self.binding)
        self.assertFalse(self.active)
        self.calls += 1
        self.active = True
        try:
            yield True
        finally:
            if self.on_exit:
                self.on_exit()
            self.active = False

    def put(self, name, value=b'hello\n'):
        p = self.work / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(value if isinstance(value, bytes) else value.encode())
        return p

    def call(self, tool, args=None, deadline=100):
        return self.api.handle(tool, {} if args is None else args, deadline=deadline)

    def refuse(self, tool, args, deadline=100):
        with self.assertRaises(self.Error) as caught:
            self.call(tool, args, deadline)
        self.assertNotIn(str(self.work), str(caught.exception))
        self.assertNotIn('PRIVATE_PAYLOAD', str(caught.exception))

    def test_constructor_validation(self):
        for binding, guard in [(None, self.guard), (self.binding, None), ({}, self.guard)]:
            with self.subTest(binding=type(binding)):
                with self.assertRaises(self.Error):
                    self.module.CodexTaskFiles(binding, guard=guard)

    def test_constructor_inert_and_readonly(self):
        self.put('a', 'hello')
        before = sorted(str(p) for p in self.agent.rglob('*'))
        original = os.open
        def opening(path, flags, *args, **kwargs):
            self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            return original(path, flags, *args, **kwargs)
        with patch('os.open', opening), patch('os.read', side_effect=AssertionError('constructor read')), patch('subprocess.run', side_effect=AssertionError('subprocess')), patch('subprocess.Popen', side_effect=AssertionError('subprocess')):
            self.module.CodexTaskFiles(self.binding, guard=self.guard)
        self.assertEqual(before, sorted(str(p) for p in self.agent.rglob('*')))
        self.assertEqual(self.calls, 0)

    def test_operations_guarded_and_readonly(self):
        self.put('a', 'hello\n')
        original_open, original_read, original_scan = os.open, os.read, os.scandir
        def opening(path, flags, *args, **kwargs):
            self.assertTrue(self.active)
            self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            return original_open(path, flags, *args, **kwargs)
        def reading(*args, **kwargs):
            self.assertTrue(self.active)
            return original_read(*args, **kwargs)
        def scanning(*args, **kwargs):
            self.assertTrue(self.active)
            return original_scan(*args, **kwargs)
        with patch('os.open', opening), patch('os.read', reading), patch('os.scandir', scanning), patch('subprocess.run', side_effect=AssertionError('subprocess')), patch('subprocess.Popen', side_effect=AssertionError('subprocess')):
            self.call('task_read', {'path': 'a'})
            self.call('task_search', {'query': 'hello'})
            self.call('task_list')
        self.assertEqual(self.calls, 3)
        self.assertEqual((self.work / 'a').read_text(), 'hello\n')

    def test_exact_arguments_and_invalid_deadlines_before_guard(self):
        invalid = [('bogus', {}), ('task_read', {}), ('task_read', {'path': 'a', 'root': '.'}), ('task_search', {'query': 'x', 'regex': True}), ('task_list', {'cursor': 1})]
        for tool, key in [('task_read', 'start_line'), ('task_read', 'limit'), ('task_search', 'limit'), ('task_list', 'limit')]:
            for value in [True, 0, -1, 1.5, '1', None, 501 if tool != 'task_search' else 101]:
                args = {'path': 'a'} if tool == 'task_read' else {'query': 'x'} if tool == 'task_search' else {}
                if key == 'start_line' and value == 501:
                    continue
                invalid.append((tool, dict(args, **{key: value})))
        for tool, args in invalid:
            with self.subTest(tool=tool, args=args): self.refuse(tool, args)
        for deadline in [True, None, '100', math.nan, math.inf, -math.inf, 0, -1]:
            with self.subTest(deadline=deadline): self.refuse('task_list', {}, deadline)
        self.assertEqual(self.calls, 0)

    def test_paths_canonical_and_bounded(self):
        for path in ['', '/tmp/a', '../a', 'a/../b', './a', 'a//b', 'a/', 'a\\b', 'a\x00b', 'a\x7fb', 'a\x85b', 'é' * 2049]:
            for tool, args in [('task_read', {'path': path}), ('task_list', {'path': path}), ('task_search', {'path': path, 'query': 'x'})]:
                with self.subTest(tool=tool, path=repr(path)): self.refuse(tool, args)
        self.refuse('task_read', {'path': '.'})
        self.assertEqual(self.calls, 0)

    def test_guard_false_and_errors_static(self):
        self.put('a', 'PRIVATE_PAYLOAD')
        for value in [False, None, 1, 'true']:
            @contextlib.contextmanager
            def guard(binding, *, deadline): yield value
            api = self.module.CodexTaskFiles(self.binding, guard=guard)
            with self.assertRaises(self.Error): api.handle('task_read', {'path': 'a'}, deadline=100)
        @contextlib.contextmanager
        def failed(binding, *, deadline):
            raise RuntimeError('PRIVATE_PAYLOAD ' + str(self.work))
            yield True
        self.api = self.module.CodexTaskFiles(self.binding, guard=failed)
        self.refuse('task_read', {'path': 'a'})

    def test_read_lines_and_defaults(self):
        self.put('a', 'α\r\nb\rc\nlast')
        self.assertEqual(self.call('task_read', {'path': 'a', 'start_line': 2, 'limit': 2}), {'path': 'a', 'start_line': 2, 'end_line': 3, 'total_lines': 4, 'text': 'b\rc\n', 'truncated': True})
        result = self.call('task_read', {'path': 'a', 'start_line': 4})
        self.assertEqual(result['text'], 'last')
        self.assertFalse(result['truncated'])
        result = self.call('task_read', {'path': 'a', 'start_line': 9})
        self.assertEqual((result['text'], result['end_line'], result['truncated']), ('', 8, False))
        self.put('empty', b'')
        self.assertEqual(self.call('task_read', {'path': 'empty'})['total_lines'], 0)
        self.put('many', 'x\n' * 201)
        self.assertEqual(self.call('task_read', {'path': 'many'})['end_line'], 200)

    def test_read_utf8_byte_cap(self):
        self.put('a', '€' * 30000 + '\nend')
        r = self.call('task_read', {'path': 'a'})
        self.assertLessEqual(len(r['text'].encode()), 65536)
        self.assertEqual(r['text'], '€' * (65536 // 3))
        self.assertEqual(r['end_line'], 1)
        self.assertTrue(r['truncated'])

    def test_binary_unicode_and_size(self):
        for name, content in [('binary', b'x\x00PRIVATE_PAYLOAD'), ('utf8', b'\xffPRIVATE_PAYLOAD'), ('large', b'x' * 1048577)]:
            self.put(name, content)
            self.refuse('task_read', {'path': name})
            self.refuse('task_search', {'path': name, 'query': 'x'})
        self.assertEqual(self.call('task_search', {'query': 'x'})['matches'], [])
        self.put('exact', b'x' * 1048576)
        self.assertTrue(self.call('task_read', {'path': 'exact'})['truncated'])

    def test_search_literal_order_line_ends_and_clip(self):
        self.put('z', 'a.*b\r\na.*b a.*b\n')
        self.put('a', 'aZZb\na.*b' + '€' * 300 + '\r')
        r = self.call('task_search', {'query': 'a.*b'})
        self.assertEqual([(m['path'], m['line']) for m in r['matches']], [('a', 2), ('z', 1), ('z', 2)])
        self.assertTrue(all(len(m['text'].encode()) <= 512 for m in r['matches']))
        self.assertFalse(any(m['text'].endswith(('\r', '\n')) for m in r['matches']))
        self.assertFalse(r['truncated'])
        self.assertTrue(self.call('task_search', {'query': 'a.*b', 'limit': 2})['truncated'])
        self.assertFalse(self.call('task_search', {'query': 'a.*b', 'limit': 3})['truncated'])

    def test_search_query_validation(self):
        for query in ['', None, 1, 'x\x00', 'x\ny', 'x\ry', 'é' * 257]:
            with self.subTest(query=repr(query)): self.refuse('task_search', {'query': query})
        self.assertEqual(self.calls, 0)

    def test_list_sorted_prefix_and_types(self):
        self.put('z', 'x'); self.put('dir/b', 'x'); self.put('dir/a', 'x')
        self.assertEqual(self.call('task_list')['entries'], [{'path': 'dir', 'type': 'directory'}, {'path': 'dir/a', 'type': 'file'}, {'path': 'dir/b', 'type': 'file'}, {'path': 'z', 'type': 'file'}])
        r = self.call('task_list', {'path': 'dir', 'limit': 1})
        self.assertEqual(r['entries'], [{'path': 'dir/a', 'type': 'file'}]); self.assertTrue(r['truncated'])
        self.refuse('task_list', {'path': 'z'})
        self.refuse('task_read', {'path': 'dir'})

    def test_forbidden_names_and_exceptions(self):
        forbidden = ['.git', '.ENV', '.env.local', '.netrc', '.npmrc', '.pypirc', 'AUTH.JSON', 'credentials.json', 'cookies.json', 'id_rsa', 'id_ed25519', 'id_dsa', 'id_ecdsa', 'x.PEM', 'x.key', 'x.p12', 'x.pfx', '.ssh/a', '.aws/a', '.azure/a', '.kube/a', 'browser-sessions/a']
        for name in forbidden: self.put(name, 'PRIVATE_PAYLOAD')
        for name in ['.env.example', '.env.sample', '.env.template']: self.put(name, 'placeholder')
        for name in forbidden:
            with self.subTest(name=name):
                self.refuse('task_read', {'path': name})
                self.refuse('task_search', {'path': name, 'query': 'PRIVATE_PAYLOAD'})
        self.assertEqual(self.call('task_search', {'query': 'PRIVATE_PAYLOAD'})['matches'], [])
        self.assertEqual([e['path'] for e in self.call('task_list')['entries']], ['.env.example', '.env.sample', '.env.template'])

    def test_real_unsafe_files_and_outside(self):
        outside = Path(self.tmp.name) / 'outside'; outside.write_text('PRIVATE_PAYLOAD')
        os.symlink(outside, self.work / 'link')
        os.link(outside, self.work / 'hard')
        os.mkfifo(self.work / 'fifo')
        sock = socket.socket(socket.AF_UNIX); sock.bind(str(self.work / 'socket')); self.addCleanup(sock.close)
        os.symlink(outside.parent, self.work / 'dirlink')
        for name in ['link', 'hard', 'fifo', 'socket', 'dirlink/outside']:
            self.refuse('task_read', {'path': name})
            self.refuse('task_search', {'path': name, 'query': 'PRIVATE_PAYLOAD'})
        self.assertEqual(self.call('task_list')['entries'], [])
        self.assertEqual(self.call('task_search', {'query': 'PRIVATE_PAYLOAD'})['matches'], [])

    def test_environment_does_not_redirect(self):
        self.put('a', 'correct')
        with patch.dict(os.environ, {'HOME': self.tmp.name, 'CODEX_TASK_ROOT': self.tmp.name, 'TASK_WORK_ROOT': self.tmp.name}):
            self.assertEqual(self.call('task_read', {'path': 'a'})['text'], 'correct')

    def test_root_and_ancestor_symlinks_refused(self):
        self.work.rename(self.agent / 'actual')
        os.symlink(self.agent / 'actual', self.work)
        with self.assertRaises(self.Error):
            api = self.module.CodexTaskFiles(self.binding, guard=self.guard)
            api.handle('task_list', {}, deadline=100)
        self.work.unlink(); (self.agent / 'actual').rename(self.work)
        alias = Path(self.tmp.name) / 'alias'; os.symlink(self.agent.parent, alias)
        binding = TaskBinding('a' * 32, 'event', str(alias / 'taskone'), 'thread', 'turn')
        with self.assertRaises(self.Error): self.module.CodexTaskFiles(binding, guard=self.guard)

    def test_modification_during_actual_read(self):
        p = self.put('a', 'PRIVATE_PAYLOAD\n')
        original = os.read; changed = False
        def reading(fd, n):
            nonlocal changed
            data = original(fd, n)
            if data and not changed:
                changed = True
                p.write_text('changed-size')
            return data
        with patch('os.read', reading): self.refuse('task_read', {'path': 'a'})
        self.assertTrue(changed)

    def test_replacement_during_actual_read(self):
        p = self.put('dir/a', 'PRIVATE_PAYLOAD\n')
        original = os.read; changed = False
        def reading(fd, n):
            nonlocal changed
            data = original(fd, n)
            if data and not changed:
                changed = True
                p.parent.rename(self.work / 'old')
                self.put('dir/a', 'replacement')
            return data
        with patch('os.read', reading): self.refuse('task_read', {'path': 'dir/a'})
        self.assertTrue(changed)

    def test_deadline_during_read_and_before_return(self):
        self.put('a', 'hello')
        original = os.read
        def reading(fd, n):
            data = original(fd, n); self.now = 100; return data
        with patch('os.read', reading): self.refuse('task_read', {'path': 'a'})
        self.now = 0
        self.on_exit = lambda: setattr(self, 'now', 100)
        self.refuse('task_list', {})

    def test_entry_bound_counts_forbidden(self):
        for i in range(513): self.put(f'.env.{i:04}', 'x')
        r = self.call('task_list', {'limit': 500})
        self.assertEqual(r['entries'], []); self.assertTrue(r['truncated'])
        self.assertTrue(self.call('task_search', {'query': 'x'})['truncated'])

    def test_depth_bound_relative_to_selected_start(self):
        name = '/'.join('d' + str(i) for i in range(10)) + '/a'
        self.put(name, 'needle')
        self.assertTrue(self.call('task_list', {'limit': 500})['truncated'])
        self.assertEqual(self.call('task_search', {'query': 'needle'})['matches'], [])
        r = self.call('task_search', {'query': 'needle', 'path': 'd0/d1/d2'})
        self.assertEqual(len(r['matches']), 1)

    def test_aggregate_search_budget(self):
        for i in range(17): self.put(f'{i:02}', b'x' * 1048576)
        self.assertTrue(self.call('task_search', {'query': 'absent'})['truncated'])

    def test_list_json_cap(self):
        prefix = '/'.join(['d' * 240] * 3)
        for i in range(150): self.put(prefix + '/' + f'{i:03}' + 'x' * 200)
        r = self.call('task_list', {'limit': 500})
        self.assertLessEqual(len(json.dumps(r).encode()), 65536)
        self.assertTrue(r['truncated'])
        self.assertEqual(r, self.call('task_list', {'limit': 500}))

    def test_search_json_cap_with_long_paths(self):
        prefix = '/'.join(['d' * 240] * 3)
        for i in range(100): self.put(prefix + '/' + f'{i:03}' + 'x' * 200, 'needle' + '€' * 200)
        r = self.call('task_search', {'query': 'needle', 'limit': 100})
        self.assertLessEqual(len(json.dumps(r).encode()), 65536)
        self.assertTrue(r['truncated'])
        self.assertEqual(r, self.call('task_search', {'query': 'needle', 'limit': 100}))

    def test_deadline_during_enumeration(self):
        self.put('a', 'hello')
        original = os.scandir
        def scanning(*args, **kwargs):
            iterator = original(*args, **kwargs)
            self.now = 100
            return iterator
        with patch('os.scandir', scanning): self.refuse('task_list', {})

    def test_ordinary_group_writable_source_allowed(self):
        p = self.put('a', 'ordinary')
        p.chmod(0o664)
        self.assertEqual(self.call('task_read', {'path': 'a'})['text'], 'ordinary')

    def test_dynamic_tools_exact_and_independent(self):
        descriptors = self.module.CodexTaskFiles.dynamic_tools()
        self.assertEqual({d['name'] for d in descriptors}, {'task_read', 'task_search', 'task_list'})
        expected = {'task_read': ({'path', 'start_line', 'limit'}, {'path'}), 'task_search': ({'query', 'path', 'limit'}, {'query'}), 'task_list': ({'path', 'limit'}, set())}
        for d in descriptors:
            self.assertTrue(d['description'])
            self.assertFalse({'namespace', 'permissions', 'defaultmodelsettings'} & set(d))
            schema = d['inputSchema']
            self.assertEqual(schema['type'], 'object'); self.assertIs(schema['additionalProperties'], False)
            props, required = expected[d['name']]
            self.assertEqual(set(schema['properties']), props)
            self.assertEqual(set(schema.get('required', [])), required)
        pristine = json.loads(json.dumps(descriptors))
        descriptors[0]['inputSchema']['properties'].clear(); descriptors.clear()
        self.assertEqual(self.module.CodexTaskFiles.dynamic_tools(), pristine)


if __name__ == '__main__':
    unittest.main()
