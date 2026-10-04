"""Independent naming/migration contracts, written before implementation.

Only synthetic private homes are used. Migration never reaches the real user
manager: a PATH stub records invocations and supplies deterministic unit states.
"""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import uuid
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = '''ai-agent-answer ai-agent-ask ai-agent-checkrun ai-agent-done
ai-agent-harvest ai-agent-io ai-agent-limits-digest ai-agent-model-advice
ai-agent-permit ai-agent-reconciler ai-agent-review ai-agent-run ai-agent-session
ai-agent-tgbot ai-agent-voice-hook ai-agent-waiting-hook ai-control-backup
ai-control-backup-init ai-control-backup-restore-test ai-control-logrotate
ai-control-project-watchdog ai-control-session ai-control-transcript-gc
ai-control-watchdog ai-control-web ai-rc ai-rc-agent ai-rc-takeover
ai-control-migrate-names'''.split()
MOVES = (('.claude-control', '.ai-control'),
         ('.config/claude-control', '.config/ai-control'),
         ('.local/share/claude-control', '.local/share/ai-control'))


def snapshot(root):
    """Include directory modes, regular bytes/modes and symlink targets."""
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        mode = path.lstat().st_mode
        payload = os.readlink(path) if stat.S_ISLNK(mode) else (
            path.read_bytes() if stat.S_ISREG(mode) else None)
        result[str(path.relative_to(root))] = (mode, payload)
    return result


class NamingContract(unittest.TestCase):
    def test_canonical_commands_and_manifest_without_aliases(self):
        manifest = (ROOT / 'scripts.manifest').read_text()
        backup_manifest = (ROOT / 'scripts.manifest.backup').read_text()
        required_entries = {line.strip() for line in manifest.splitlines() if line.strip() and not line.lstrip().startswith('#')}
        optional_entries = {line.strip() for line in backup_manifest.splitlines() if line.strip() and not line.lstrip().startswith('#')}
        for name in COMMANDS:
            with self.subTest(command=name):
                command = ROOT / 'bin' / name
                self.assertTrue(command.is_file(), f'missing canonical command {name}')
                self.assertFalse(command.is_symlink(), 'canonical command must not be alias')
                self.assertTrue(os.access(command, os.X_OK))
                # Baseline backup commands have an explicit optional installation manifest.
                entries = optional_entries if name in ('ai-control-backup', 'ai-control-backup-init', 'ai-control-backup-restore-test') else required_entries
                self.assertIn(name, entries)
        for prefix in ('claude-control', 'claude-agent', 'claude-rc'):
            self.assertFalse(list((ROOT / 'bin').glob(prefix + '*')))
            self.assertFalse(any(prefix in entry for entry in required_entries | optional_entries))
        self.assertTrue((ROOT / 'bin/codex-rc').is_file())

    def test_public_defaults_and_env_names_are_canonical(self):
        texts = []
        for name in COMMANDS:
            if name == 'ai-control-migrate-names':
                continue  # Migration necessarily names its legacy input roots.
            path = ROOT / 'bin' / name
            self.assertTrue(path.is_file(), f'missing canonical default owner {name}')
            text = path.read_text()
            texts.append(text)
            for legacy in ('.claude-control', '.config/claude-control',
                           '.local/share/claude-control', 'CLAUDE_CONTROL_',
                           'CLAUDE_RC_', 'CLAUDE_AGENTS_', 'CLAUDE_AGENT_',
                           'CLAUDE_RECONCILER_', 'CLAUDE_TGBOT_', 'CLAUDE_HARVEST_',
                           'CLAUDE_EVENT_', 'CLAUDE_BACKUP_ENV'):
                self.assertNotIn(legacy, text, f'legacy product default/env in {name}')
        combined = '\n'.join(texts)
        for canonical in ('.ai-control', '.config/ai-control',
                          '.local/share/ai-control', 'AI_CONTROL_', 'AI_RC_', 'AI_AGENTS_DIR'):
            self.assertIn(canonical, combined)

    def test_templates_use_canonical_paths_units_and_web_account(self):
        paths = list((ROOT / 'systemd').glob('*.tmpl')) + list((ROOT / 'launchd').glob('*.tmpl'))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(template=path.name):
                text = path.read_text()
                for old in ('claude-control', 'claude-agent', 'claude-rc',
                            'CLAUDE_CONTROL_', 'CLAUDE_RC_', 'CLAUDE_AGENTS_', 'CLAUDE_AGENT_',
                           'CLAUDE_RECONCILER_', 'CLAUDE_TGBOT_', 'CLAUDE_HARVEST_',
                           'CLAUDE_EVENT_', 'CLAUDE_BACKUP_ENV'):
                    self.assertNotIn(old, path.name + '\n' + text)
        self.assertTrue((ROOT / 'systemd/ai-control-web.service.tmpl').is_file(), 'missing canonical web template')
        self.assertTrue((ROOT / 'systemd/ai-control-web-broker.service.tmpl').is_file(), 'missing canonical broker template')
        frontend = (ROOT / 'systemd/ai-control-web.service.tmpl').read_text()
        broker = (ROOT / 'systemd/ai-control-web-broker.service.tmpl').read_text()
        self.assertIn('ai-panel', frontend)
        self.assertIn('/opt/ai-control-web', frontend)
        self.assertIn('/var/lib/ai-control-web', frontend)
        self.assertIn('ai-control-web', broker)
        self.assertIn('ai-panel', broker)


class OfflineMigrationContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ai-names-tests-', dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name)
        self.private.chmod(0o700)
        self.home = self.private / 'home'
        self.home.mkdir(mode=0o700)
        self.stub = self.private / 'tools'
        self.stub.mkdir(mode=0o700)
        self.log = self.private / 'manager.log'
        systemctl = self.stub / 'systemctl'
        systemctl.write_text('''#!/usr/bin/env python3
import os, sys
with open(os.environ['TEST_MANAGER_LOG'], 'a') as out:
    out.write(' '.join(sys.argv[1:]) + '\\n')
if os.environ.get('TEST_MANAGER_DOWN') == '1':
    sys.exit(1)
if 'list-units' in sys.argv:
    unit = os.environ.get('TEST_ACTIVE_UNIT', '')
    selected_types = []
    for number, argument in enumerate(sys.argv[1:], start=1):
        if argument.startswith('--type='):
            selected_types.extend(argument.split('=', 1)[1].split(','))
        elif argument == '--type' and number + 1 < len(sys.argv):
            selected_types.extend(sys.argv[number + 1].split(','))
    if unit and (not selected_types or unit.rsplit('.', 1)[-1] in selected_types):
        print(unit + ' loaded active running synthetic runtime')
''')
        systemctl.chmod(0o700)
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=str(self.stub) + ':' + os.environ.get('PATH', ''),
                        TEST_MANAGER_LOG=str(self.log))
        for variable in list(self.env):
            if variable.startswith(('CLAUDE_CONTROL_', 'AI_CONTROL_', 'CLAUDE_RC_', 'AI_RC_')) or variable in ('CLAUDE_AGENTS_DIR', 'AI_AGENTS_DIR'):
                self.env.pop(variable)
        for source, _ in MOVES:
            directory = self.home / source
            directory.mkdir(parents=True, mode=0o700)
            directory.chmod(0o700)
            for relative in ('agents/task/spec.yaml', 'questions/q.json', 'spool/item',
                             'lessons/note', 'projects/entry', 'history/event', 'auth.json', 'totp-state.json'):
                file = directory / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.parent.chmod(0o700)
                file.write_bytes(b'synthetic claude-control task text\x00\xff\n')
                file.chmod(0o600)
        for provider in ('.claude', '.codex'):
            directory = self.home / provider
            directory.mkdir(mode=0o700)
            (directory / 'synthetic-settings.json').write_text('{"provider":"unchanged"}')

    def run_migration(self, dry_run=False, retain_checkpoint=False):
        helper = ROOT / 'bin/ai-control-migrate-names'
        self.assertTrue(helper.is_file(), 'offline canonical migration helper is missing')
        args = [str(helper), '--home', str(self.home)]
        if dry_run:
            args.append('--dry-run')
        if retain_checkpoint:
            args.append('--retain-checkpoint')
        return subprocess.run(args, env=self.env, capture_output=True, timeout=15)

    def test_apply_preserves_all_data_modes_provider_dirs_and_repeat_is_noop(self):
        originals = {source: snapshot(self.home / source) for source, _ in MOVES}
        providers = {name: snapshot(self.home / name) for name in ('.claude', '.codex')}
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertFalse((self.home / '.ai-control-naming-transaction').exists())
        for source, target in MOVES:
            self.assertFalse((self.home / source).exists())
            actual = snapshot(self.home / target)
            for relative, value in originals[source].items():
                self.assertEqual(actual.get(relative), value, f'bytes/modes changed: {target}/{relative}')
        for name, original in providers.items():
            self.assertEqual(snapshot(self.home / name), original)
        receipt = self.home / '.ai-control/naming-migration.json'
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        record = json.loads(receipt.read_text())
        self.assertEqual(record['version'], 1)
        self.assertEqual(set(record['migrated_roots']), {target for _, target in MOVES})
        self.assertNotIn('synthetic', receipt.read_text())
        before = snapshot(self.home)
        self.assertEqual(self.run_migration().returncode, 0)
        self.assertEqual(snapshot(self.home), before)
        self.assertIn('--user', self.log.read_text())
        self.assertIn('list-units', self.log.read_text())

    def test_empty_home_is_noop_without_receipt_or_new_directories(self):
        empty = self.private / 'empty'
        empty.mkdir(mode=0o700)
        self.home = empty
        self.env['HOME'] = str(empty)
        before = snapshot(empty)
        self.assertEqual(self.run_migration().returncode, 0)
        self.assertEqual(snapshot(empty), before)

    def test_nonprivate_source_refuses_before_any_move(self):
        (self.home / MOVES[-1][0]).chmod(0o755)
        before = snapshot(self.home)
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertEqual(snapshot(self.home), before)

    def saved_mission_settings(self):
        agent = self.home / '.claude-control/agents/taskone'
        agent.mkdir(parents=True, exist_ok=True, mode=0o700)
        settings = {'permissions': {
            'allow': ['Read(' + str(agent) + '/**)', 'Bash(claude-agent-ask:*)',
                      'Bash(claude-agent-done:*)', 'Read(/external/provider/**)',
                      'Bash(claude --model provider-model:*)'],
            'deny': ['Bash(custom-denied:*)']},
            'custom': {'opaque': 'claude-agent-ask and .claude-control remain user text'}}
        path = agent / 'agent-settings.json'
        path.write_text(json.dumps(settings))
        path.chmod(0o600)
        return path, settings

    def test_saved_mission_permissions_relocate_exact_scope_and_commands(self):
        _, settings = self.saved_mission_settings()
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        new_agent = self.home / '.ai-control/agents/taskone'
        expected = json.loads(json.dumps(settings))
        expected['permissions']['allow'][:3] = ['Read(' + str(new_agent) + '/**)',
                                               'Bash(ai-agent-ask:*)', 'Bash(ai-agent-done:*)']
        actual_path = new_agent / 'agent-settings.json'
        self.assertEqual(json.loads(actual_path.read_text()), expected)
        self.assertEqual(stat.S_IMODE(actual_path.stat().st_mode), 0o600)

    def test_generated_double_slash_read_scope_and_blanket_bash_are_preserved(self):
        path, settings = self.saved_mission_settings()
        old_agent = path.parent
        settings['permissions']['allow'][0] = 'Read(//' + str(old_agent).strip('/') + '/**)'
        settings['permissions']['allow'].append('Bash')
        path.write_text(json.dumps(settings))
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        new_agent = self.home / '.ai-control/agents/taskone'
        expected = json.loads(json.dumps(settings))
        expected['permissions']['allow'][:3] = ['Read(//' + str(new_agent).strip('/') + '/**)',
                                               'Bash(ai-agent-ask:*)', 'Bash(ai-agent-done:*)']
        self.assertEqual(json.loads((new_agent / 'agent-settings.json').read_text()), expected)

    def test_allow_deny_event_scopes_and_generated_hook_relocate_exactly(self):
        path, settings = self.saved_mission_settings()
        agent = path.parent
        old_scope = '///' + str(agent).strip('/')
        custom = self.stub / 'ai-agent-mine'
        custom.write_text('#!/bin/sh\nexit 0\n')
        custom.chmod(0o700)
        settings['permissions']['allow'].append('Bash(claude-agent-mine:*)')
        settings['permissions']['allow'] += ['Read(' + old_scope + '/work/**)',
                                              'Edit(' + old_scope + '/run/**)']
        settings['permissions']['deny'] += ['Bash(claude-agent-ask:*)',
                                             'Bash(claude-rc agent run:*)',
                                             'Bash(claude-control-web:*)']
        for operation in ('Edit', 'Write', 'NotebookEdit'):
            for suffix in ('questions/**', 'reject_comments/**', 'lessons.json', 'done.json'):
                settings['permissions']['deny'].append(operation + '(' + old_scope + '/' + suffix + ')')
        command = str(ROOT / 'bin/claude-agent-permit') + ' --hook'
        settings['hooks'] = {'PreToolUse': [{'matcher': 'Bash|Edit|Write|NotebookEdit',
                           'hooks': [{'type': 'command', 'command': command}]}]}
        path.write_text(json.dumps(settings))
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        new_agent = self.home / '.ai-control/agents/taskone'
        expected = json.loads(json.dumps(settings))
        for field in ('allow', 'deny'):
            expected['permissions'][field] = [
                rule.replace(str(agent), str(new_agent)).replace('Bash(claude-agent-ask:', 'Bash(ai-agent-ask:')
                    .replace('Bash(claude-agent-done:', 'Bash(ai-agent-done:')
                    .replace('Bash(claude-control-web:', 'Bash(ai-control-web:').replace('Bash(claude-rc ', 'Bash(ai-rc ')
                for rule in settings['permissions'][field]]
        expected['hooks']['PreToolUse'][0]['hooks'][0]['command'] = str(ROOT / 'bin/ai-agent-permit') + ' --hook'
        self.assertEqual(json.loads((new_agent / 'agent-settings.json').read_text()), expected)

    def test_unsupported_permissions_or_legacy_hooks_refuse_inert(self):
        for number, unsupported in enumerate(('permission-field', 'unknown-hook')):
            with self.subTest(unsupported=unsupported):
                self.home = self.private / ('unsupported-case-' + str(number))
                self.home.mkdir(mode=0o700)
                self.env['HOME'] = str(self.home)
                path, settings = self.saved_mission_settings()
                if unsupported == 'permission-field':
                    settings['permissions']['ask'] = ['Bash(claude-agent-ask:*)']
                else:
                    settings['hooks'] = {'PreToolUse': [{'matcher': 'Bash', 'hooks': [
                        {'type': 'command', 'command': str(ROOT / 'bin/claude-agent-unknown') + ' --hook'}]}]}
                path.write_text(json.dumps(settings))
                before = snapshot(self.home)
                self.assertNotEqual(self.run_migration().returncode, 0)
                self.assertEqual(snapshot(self.home), before)

    def test_retain_checkpoint_success_preserves_original_settings_and_blocks_repeat(self):
        settings_path, _ = self.saved_mission_settings()
        original = settings_path.read_bytes()
        result = self.run_migration(retain_checkpoint=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertTrue((self.home / '.ai-control/naming-migration.json').is_file())
        checkpoint = self.home / '.ai-control-naming-transaction'
        self.assertTrue(checkpoint.is_dir())
        self.assertEqual(stat.S_IMODE(checkpoint.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((checkpoint / 'plan.json').stat().st_mode), 0o600)
        backups = [path for path in checkpoint.rglob('*') if path.is_file() and path.name != 'plan.json']
        self.assertIn(original, [path.read_bytes() for path in backups])
        for backup in backups:
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        before = snapshot(self.home)
        for dry_run in (False, True):
            self.assertNotEqual(self.run_migration(dry_run=dry_run).returncode, 0)
            self.assertEqual(snapshot(self.home), before)

    def test_malformed_known_mission_settings_refuse_before_any_move(self):
        for number, malformed in enumerate(('{', '[]', '{"permissions":{"allow":"Read(*)","deny":[]}}',
                                             '{"permissions":{"allow":[true],"deny":[]}}')):
            with self.subTest(malformed=malformed):
                self.home = self.private / ('malformed-case-' + str(number))
                self.home.mkdir(mode=0o700)
                self.env['HOME'] = str(self.home)
                path, _ = self.saved_mission_settings()
                path.write_text(malformed)
                before = snapshot(self.home)
                self.assertNotEqual(self.run_migration().returncode, 0)
                self.assertEqual(snapshot(self.home), before)

    def test_dry_run_is_completely_inert(self):
        before = snapshot(self.home)
        self.assertEqual(self.run_migration(dry_run=True).returncode, 0)
        self.assertEqual(snapshot(self.home), before)

    def test_last_destination_conflict_refuses_before_any_move(self):
        (self.home / MOVES[-1][1]).mkdir(mode=0o700)
        before = snapshot(self.home)
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertEqual(snapshot(self.home), before)

    def test_source_or_destination_symlink_refuses_before_any_move(self):
        for position in ('source', 'target'):
            with self.subTest(position=position):
                source, target = MOVES[-1]
                link = self.home / (source if position == 'source' else target)
                if position == 'source':
                    parked = self.private / 'parked'
                    link.rename(parked)
                else:
                    parked = self.home / source
                link.symlink_to(parked, target_is_directory=True)
                before = snapshot(self.home)
                self.assertNotEqual(self.run_migration().returncode, 0)
                self.assertEqual(snapshot(self.home), before)
                link.unlink()
                if position == 'source':
                    parked.rename(link)

    def test_active_old_new_and_transient_units_refuse_without_mutation(self):
        for unit in ('claude-control.service', 'claude-agent-tgbot.service',
                     'ai-control.service', 'ai-agent-reconciler.service', 'ccsession-test.service',
                     'cctask-test.service', 'ai-agent-limits-digest.timer',
                     'claude-control-logrotate.timer', 'ai-control-backup.timer'):
            with self.subTest(unit=unit):
                self.env['TEST_ACTIVE_UNIT'] = unit
                before = snapshot(self.home)
                self.assertNotEqual(self.run_migration().returncode, 0)
                self.assertEqual(snapshot(self.home), before)

    def test_apply_requires_available_user_manager(self):
        self.env['TEST_MANAGER_DOWN'] = '1'
        before = snapshot(self.home)
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertEqual(snapshot(self.home), before)


class StoppedMetadataMigrationContract(unittest.TestCase):
    """Use established public operation-store fixture methods, never inspect bin."""
    setUp = OfflineMigrationContract.setUp
    run_migration = OfflineMigrationContract.run_migration
    saved_mission_settings = OfflineMigrationContract.saved_mission_settings

    def make_operation(self):
        previous_umask = os.umask(0o077)
        self.addCleanup(os.umask, previous_umask)
        spec = importlib.util.spec_from_file_location(
            'naming_public_operation_fixture', ROOT / 'tests/test-codex-task-operation-store.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = module.OperationStoreContract()
        fixture.Store = module.store_module.CodexTaskOperationStore
        fixture.Error = module.store_module.StoreError
        fixture.root = self.home / '.claude-control'
        fixture.stage = fixture.root / 'agents/.staging'
        fixture.agent = fixture.root / 'agents/taskone'
        fixture.private = fixture.root / 'codex-task-state'
        fixture.project = self.private / 'external-project'
        for directory in (fixture.stage / 'work', fixture.stage / 'inbox/inflight',
                          fixture.private, fixture.project):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for directory in fixture.root.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o700)
        for path in (fixture.stage / '.lock', fixture.stage / 'inbox/.inbox.lock'):
            path.touch(mode=0o600)
        fixture.control = dict(schema=1, incarnation=module.INC, generation=0,
            desired='paused', hold=None, mission_base='a' * 40,
            acceptance={'status': 'pending'}, lease={'state': 'none', 'start_attempt_id': None},
            seq=0, session_id=None, attention=None, handoff=None)
        module.save(fixture.stage / 'control.json', fixture.control)
        (fixture.stage / 'spec.yaml').write_text('engine: codex\ntype: event\nruntime: drain\nworkspace: worktree\nproject: ' + str(fixture.project) + '\n')
        fixture.sid = str(uuid.uuid4())
        fixture.now, fixture.deadline = 100.0, 110.0
        fixture.clock = lambda: fixture.now
        fixture.index = fixture.private / fixture.sid / 'index.json'
        operation, envelope = fixture.historical()
        self.assertIs(fixture.store.snapshot(deadline=fixture.deadline)['reconciliation_required'], False)
        return fixture, operation, envelope

    def test_stopped_operation_relocates_trusted_paths_preserving_authority(self):
        fixture, operation, envelope = self.make_operation()
        old_root = self.home / '.claude-control'
        new_root = self.home / '.ai-control'
        index_before = fixture.read_index()
        host_before = Path(index_before['operations'][operation]['host_state_dir'])
        journal_before = json.loads((host_before / 'journal.json').read_text())
        opaque_before = (fixture.agent / 'spec.yaml').read_bytes()
        identities_before = {str(path.relative_to(old_root)): json.loads(path.read_text())
                             for path in old_root.rglob('directory-identity.json')}
        self.assertTrue(identities_before, 'public fixture must provide pinned directory identity')
        directories = {str(path.relative_to(old_root)): (path.stat().st_dev, path.stat().st_ino)
                       for path in [old_root, *old_root.rglob('*')] if path.is_dir()}
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        new_agent = new_root / 'agents/taskone'
        new_index = new_root / 'codex-task-state' / fixture.sid / 'index.json'
        index_after = json.loads(new_index.read_text())
        self.assertEqual(index_after['agent_dir'], str(new_agent))
        old_op = index_before['operations'][operation]
        new_op = index_after['operations'][operation]
        expected_host = str(new_root / host_before.relative_to(old_root))
        self.assertEqual(new_op['host_state_dir'], expected_host)
        self.assertEqual(new_op['drain_evidence']['host_state_dir'], expected_host)
        expected_op = json.loads(json.dumps(old_op))
        expected_op['host_state_dir'] = expected_host
        expected_op['drain_evidence']['host_state_dir'] = expected_host
        self.assertEqual(new_op, expected_op, 'authority proofs must remain unchanged')
        journal_after = json.loads((Path(expected_host) / 'journal.json').read_text())
        expected_journal = dict(journal_before, cwd=str(new_agent / 'work'),
                                socket=str(Path(expected_host) / 'server.sock'))
        self.assertEqual(journal_after, expected_journal)
        self.assertEqual((new_agent / 'spec.yaml').read_bytes(), opaque_before)
        projection = json.loads((new_agent / 'inbox/done' / envelope.name).read_text())
        self.assertEqual(projection['meta']['codex_operation']['host_state_dir'], expected_host)
        for relative, identity in directories.items():
            path = new_root / relative
            self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity)
        for relative, identity in identities_before.items():
            expected_identity = dict(identity)
            expected_identity['directories'] = {
                str(new_root / Path(key).relative_to(old_root)) if Path(key).is_relative_to(old_root) else key: value
                for key, value in identity['directories'].items()}
            self.assertEqual(json.loads((new_root / relative).read_text()), expected_identity)
        reopened = fixture.Store(str(new_agent), state_root=str(new_root / 'codex-task-state'))
        self.assertIs(reopened.snapshot(deadline=time.monotonic() + 10)['reconciliation_required'], False)

    def test_stopped_socket_target_relocates_preserving_identity_pairs(self):
        for product_owned in (True, False):
            with self.subTest(product_owned=product_owned):
                # Each case gets its own private fixture home; prior completed roots
                # must never be merged into a subsequent source fixture.
                case_home = self.private / ('socket-product' if product_owned else 'socket-provider')
                case_home.mkdir(mode=0o700)
                self.home = case_home
                self.env['HOME'] = str(case_home)
                old_root = case_home / '.claude-control'
                old_root.mkdir(mode=0o700)
                fixture, operation, _ = self.make_operation()
                old_host = Path(fixture.read_index()['operations'][operation]['host_state_dir'])
                journal_path = old_host / 'journal.json'
                journal = json.loads(journal_path.read_text())
                target = old_host / 'native.sock' if product_owned else self.private / 'external-provider.sock'
                identity = {'link': [123, 456], 'target_path': str(target), 'target': [789, 1011]}
                journal['socket_identity'] = identity
                journal_path.write_text(json.dumps(journal))
                self.assertIs(fixture.store.snapshot(deadline=fixture.deadline)['reconciliation_required'], False,
                              'nonnull identity fixture must validate before migration')
                result = self.run_migration()
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                new_root = case_home / '.ai-control'
                new_host = new_root / old_host.relative_to(old_root)
                actual = json.loads((new_host / 'journal.json').read_text())['socket_identity']
                expected = dict(identity, target_path=str(new_host / 'native.sock') if product_owned else str(target))
                self.assertEqual(actual, expected)
                reopened = fixture.Store(str(new_root / 'agents/taskone'),
                                         state_root=str(new_root / 'codex-task-state'))
                self.assertIs(reopened.snapshot(deadline=time.monotonic() + 10)['reconciliation_required'], False)

    def test_stopped_executable_in_product_share_root_relocates(self):
        fixture, operation, _ = self.make_operation()
        executable = self.home / '.local/share/claude-control/codex-venv/bin/python'
        executable.parent.mkdir(parents=True, mode=0o700)
        executable.write_bytes(b'synthetic interpreter placeholder\n')
        executable.chmod(0o600)
        host = Path(fixture.read_index()['operations'][operation]['host_state_dir'])
        journal_path = host / 'journal.json'
        journal = json.loads(journal_path.read_text())
        journal['executable'] = str(executable)
        journal_path.write_text(json.dumps(journal))
        self.assertIs(fixture.store.snapshot(deadline=fixture.deadline)['reconciliation_required'], False,
                      'share executable fixture must validate before migration')
        before = executable.read_bytes(), stat.S_IMODE(executable.stat().st_mode)
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        new_root = self.home / '.ai-control'
        new_host = new_root / host.relative_to(self.home / '.claude-control')
        new_executable = self.home / '.local/share/ai-control/codex-venv/bin/python'
        actual = json.loads((new_host / 'journal.json').read_text())
        self.assertEqual(actual, dict(journal, cwd=str(new_root / 'agents/taskone/work'),
                                    socket=str(new_host / 'server.sock'), executable=str(new_executable)))
        self.assertEqual((new_executable.read_bytes(), stat.S_IMODE(new_executable.stat().st_mode)), before)
        reopened = fixture.Store(str(new_root / 'agents/taskone'),
                                 state_root=str(new_root / 'codex-task-state'))
        self.assertIs(reopened.snapshot(deadline=time.monotonic() + 10)['reconciliation_required'], False)

    def injected_migration(self, injection):
        helper = ROOT / 'bin/ai-control-migrate-names'
        self.assertTrue(helper.is_file(), 'offline canonical migration helper is missing')
        script = """import json, os, pathlib, runpy, sys
helper, home, injection = sys.argv[1:]
original_rename = os.rename
original_replace = os.replace
original_fsync = os.fsync
fsynced = []
root = pathlib.Path(home)
def fsync(fd):
    result = original_fsync(fd)
    fsynced.append(os.readlink('/proc/self/fd/' + str(fd)))
    return result
os.fsync = fsync
def rename(source, target, *args, **kwargs):
    result = original_rename(source, target, *args, **kwargs)
    if injection == 'interrupt' and pathlib.Path(source) == root / '.claude-control' and pathlib.Path(target) == root / '.ai-control':
        (root.parent / 'fsync-events.json').write_text(json.dumps(fsynced))
        os._exit(73)
    return result
failed = False
def replace(source, target, *args, **kwargs):
    global failed
    target_path = pathlib.Path(target)
    if injection == 'write-failure' and not failed and (root / '.ai-control').exists() and not (root / '.claude-control').exists() and target_path.is_relative_to(root / '.ai-control'):
        failed = True
        (root.parent / 'metadata-failure-injected').write_text('injected')
        raise OSError('synthetic metadata write failure')
    return original_replace(source, target, *args, **kwargs)
os.rename = rename
os.replace = replace
sys.path.insert(0, str(pathlib.Path(helper).parent))
sys.argv = [helper, '--home', home]
runpy.run_path(helper, run_name='__main__')
"""
        return subprocess.run(['python3', '-c', script, str(helper), str(self.home), injection],
                              env=self.env, capture_output=True, timeout=15)

    def test_interruption_retains_private_checkpoint_originals_and_blocks_repeat(self):
        fixture, _, _ = self.make_operation()
        self.saved_mission_settings()
        originals = [path.read_bytes() for path in (self.home / '.claude-control').rglob('*.json')
                     if path.name in ('index.json', 'directory-identity.json', 'journal.json', 'event-1.json', 'agent-settings.json')]
        self.assertTrue(originals)
        result = self.injected_migration('interrupt')
        self.assertEqual(result.returncode, 73, result.stderr.decode(errors='replace'))
        checkpoint = self.home / '.ai-control-naming-transaction'
        self.assertTrue(checkpoint.is_dir(), 'checkpoint must precede first root rename')
        self.assertEqual(stat.S_IMODE(checkpoint.stat().st_mode), 0o700)
        plan_path = checkpoint / 'plan.json'
        self.assertEqual(stat.S_IMODE(plan_path.stat().st_mode), 0o600)
        plan = json.loads(plan_path.read_text())
        self.assertEqual(plan.get('version', plan.get('schema')), 1)
        backups = [path for path in checkpoint.rglob('*') if path.is_file() and path != plan_path]
        backup_bytes = [path.read_bytes() for path in backups]
        for original in originals:
            self.assertIn(original, backup_bytes, 'checkpoint must retain each original metadata file')
        for path in backups:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        synced = json.loads((self.home.parent / 'fsync-events.json').read_text())
        for path in [checkpoint, plan_path, *backups]:
            self.assertIn(str(path), synced, 'checkpoint file/directory must be fsynced before rename')
        before = snapshot(self.home)
        for dry_run in (False, True):
            self.assertNotEqual(self.run_migration(dry_run=dry_run).returncode, 0)
            self.assertEqual(snapshot(self.home), before)

    def test_injected_metadata_failure_restores_verified_original_state(self):
        fixture, _, _ = self.make_operation()
        self.saved_mission_settings()
        before = snapshot(self.home)
        result = self.injected_migration('write-failure')
        self.assertTrue((self.home.parent / 'metadata-failure-injected').is_file(),
                        'must reach injected metadata write after root moves; setup refusal is not rollback evidence')
        self.assertNotEqual(result.returncode, 0, 'write failure must not report completed migration')
        checkpoint = self.home / '.ai-control-naming-transaction'
        if checkpoint.exists():
            self.assertEqual(stat.S_IMODE(checkpoint.stat().st_mode), 0o700)
            self.assertTrue((checkpoint / 'plan.json').is_file())
            preserved = snapshot(self.home)
            self.assertNotEqual(self.run_migration().returncode, 0)
            self.assertEqual(snapshot(self.home), preserved)
        else:
            self.assertEqual(snapshot(self.home), before, 'verified clean rollback must restore bytes/modes/roots')
            self.assertIs(fixture.store.snapshot(deadline=fixture.deadline)['reconciliation_required'], False)

    def stopped_bridge(self):
        fixture, operation, _ = self.make_operation()
        module = importlib.import_module('_codex_task_bridge')
        host = Path(fixture.read_index()['operations'][operation]['host_state_dir'])
        bridge_dir = host.parent / 'bridge'
        binding = module.TaskBinding(fixture.control['incarnation'], 'event-1',
                                     str(fixture.agent), 'thread-1', 'turn-1')
        @contextlib.contextmanager
        def guard(actual, *, deadline):
            self.assertEqual(actual, binding)
            yield True
        calls = []
        result = {'qid': str(uuid.uuid4())}
        def writer(actual, tool, arguments, *, deadline):
            self.assertEqual(actual, binding)
            calls.append((tool, arguments))
            return result
        request = {'id': 1, 'method': 'item/tool/call', 'params': {
            'threadId': 'thread-1', 'turnId': 'turn-1', 'callId': 'retained-call',
            'tool': 'task_ask', 'arguments': {'question': 'synthetic retained question'}}}
        bridge = module.CodexTaskBridge(bridge_dir, binding, guard=guard, writer=writer, clock=lambda: 1.0)
        response = bridge.handle(request, deadline=100.0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(bridge.handle(request, deadline=100.0), response)
        self.assertEqual(len(calls), 1, 'baseline bridge must already replay cached result')
        return fixture, module, binding, bridge_dir, request, response

    def test_stopped_bridge_binding_relocates_and_cached_call_never_rewrites(self):
        fixture, module, binding, bridge_dir, request, response = self.stopped_bridge()
        journal = bridge_dir / 'journal.json'
        original = json.loads(journal.read_text())
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        old_root = self.home / '.claude-control'
        new_root = self.home / '.ai-control'
        new_agent = new_root / 'agents/taskone'
        new_bridge_dir = new_root / bridge_dir.relative_to(old_root)
        expected = json.loads(json.dumps(original))
        expected['binding']['agent_dir'] = str(new_agent)
        self.assertEqual(json.loads((new_bridge_dir / 'journal.json').read_text()), expected)
        new_binding = module.TaskBinding(binding.task_incarnation, binding.event_key, str(new_agent),
                                         binding.thread_id, binding.turn_id)
        @contextlib.contextmanager
        def guard(actual, *, deadline):
            self.assertEqual(actual, new_binding)
            yield True
        def forbidden_writer(*args, **kwargs):
            self.fail('cached migrated call must not invoke writer again')
        replay = module.CodexTaskBridge(new_bridge_dir, new_binding, guard=guard,
                                       writer=forbidden_writer, clock=lambda: 1.0)
        self.assertEqual(replay.handle(request, deadline=100.0), response)

    def test_unknown_or_malformed_bridge_refuses_before_any_move(self):
        for number in (0, 1):
            with self.subTest(case=number):
                self.home = self.private / ('bridge-malformed-' + str(number))
                self.home.mkdir(mode=0o700)
                self.env['HOME'] = str(self.home)
                fixture, _, _, bridge_dir, _, _ = self.stopped_bridge()
                path = bridge_dir / 'journal.json'
                record = json.loads(path.read_text())
                path.write_text('{' if number == 0 else json.dumps(dict(record, schema=987654)))
                before = snapshot(self.home)
                self.assertNotEqual(self.run_migration().returncode, 0)
                self.assertEqual(snapshot(self.home), before)

    def test_retained_native_admission_valid_recovery_then_inert_migration_refusal(self):
        self.home = self.private / 'native-home'
        self.home.mkdir(mode=0o700)
        self.env['HOME'] = str(self.home)
        old_root = self.home / '.claude-control'
        old_root.mkdir(mode=0o700)
        module_spec = importlib.util.spec_from_file_location(
            'naming_public_runtime_fixture', ROOT / 'tests/test-codex-task-runtime.py')
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        class FixtureDirectory:
            name = str(old_root)
            def cleanup(self):
                pass  # Outer private TemporaryDirectory owns cleanup.
        case = module.RuntimeContract()
        self.addCleanup(case.doCleanups)
        with patch.object(module.tempfile, 'TemporaryDirectory', return_value=FixtureDirectory()):
            case.setUp()
        state = old_root / 'codex-task-state'
        case.state.rename(state)
        case.state = state
        # Preserve the existing authoritative recovery assertions verbatim via
        # its public fixture test before isolating the naming boundary.
        case.test_drained_bootstrap_publication_crash_repairs_only_from_exact_durable_proof()
        admission = state / case.control['codex_state_id'] / 'admission.json'
        self.assertTrue(admission.is_file())
        self.assertEqual(len(list(state.rglob('bootstrap-proof.json'))), 1)
        # This private fixture's git marker independently blocks migration;
        # remove only that marker after successful native recovery so the test
        # specifically requires the unsupported retained-native barrier.
        (case.agent / 'work/.git').unlink()
        before = snapshot(self.home)
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertEqual(snapshot(self.home), before)

    def test_retained_native_artifact_existence_refuses_even_malformed_or_unbound(self):
        cases = ('admission-malformed', 'admission-directory', 'proof-bound-malformed',
                 'proof-unbound', 'lifecycle-bound', 'lifecycle-unbound')
        for number, kind in enumerate(cases):
            with self.subTest(kind=kind):
                self.home = self.private / ('native-artifact-' + str(number))
                self.home.mkdir(mode=0o700)
                self.env['HOME'] = str(self.home)
                fixture, operation, _ = self.make_operation()
                state_dir = fixture.private / fixture.sid
                host = Path(fixture.read_index()['operations'][operation]['host_state_dir'])
                if kind.startswith('admission'):
                    artifact = state_dir / 'admission.json'
                elif kind == 'proof-bound-malformed':
                    artifact = host.parent / 'bootstrap-proof.json'
                elif kind == 'proof-unbound':
                    artifact = state_dir / 'unbound/bootstrap-proof.json'
                elif kind == 'lifecycle-bound':
                    artifact = host.parent / 'lifecycle/retained.json'
                else:
                    artifact = state_dir / 'unbound/lifecycle/retained.json'
                artifact.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if kind == 'admission-directory':
                    artifact.mkdir(mode=0o700)
                else:
                    artifact.write_bytes(b'{ malformed synthetic retained native metadata')
                    artifact.chmod(0o600)
                before = snapshot(self.home)
                self.assertNotEqual(self.run_migration().returncode, 0)
                self.assertEqual(snapshot(self.home), before)

    def test_unknown_schema_refuses_before_any_root_move(self):
        fixture, _, _ = self.make_operation()
        record = fixture.read_index()
        record['schema'] = 987654
        fixture.index.write_text(json.dumps(record))
        before = snapshot(self.home)
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertEqual(snapshot(self.home), before)

    def test_nonstopped_journal_refuses_before_any_root_move(self):
        fixture, operation, _ = self.make_operation()
        journal = Path(fixture.read_index()['operations'][operation]['host_state_dir']) / 'journal.json'
        record = json.loads(journal.read_text())
        record['phase'] = 'running'
        journal.write_text(json.dumps(record))
        before = snapshot(self.home)
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertEqual(snapshot(self.home), before)


if __name__ == '__main__':
    unittest.main()
