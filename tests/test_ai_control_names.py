"""Independent naming/migration contracts, written before implementation.

Only synthetic private homes are used. Migration never reaches the real user
manager: a PATH stub records invocations and supplies deterministic unit states.
"""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import uuid
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

    def run_migration(self, dry_run=False):
        helper = ROOT / 'bin/ai-control-migrate-names'
        self.assertTrue(helper.is_file(), 'offline canonical migration helper is missing')
        args = [str(helper), '--home', str(self.home)]
        if dry_run:
            args.append('--dry-run')
        return subprocess.run(args, env=self.env, capture_output=True, timeout=15)

    def test_apply_preserves_all_data_modes_provider_dirs_and_repeat_is_noop(self):
        originals = {source: snapshot(self.home / source) for source, _ in MOVES}
        providers = {name: snapshot(self.home / name) for name in ('.claude', '.codex')}
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
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
