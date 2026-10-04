"""Independent naming/migration contracts, written before implementation.

Only synthetic private homes are used. Migration never reaches the real user
manager: a PATH stub records invocations and supplies deterministic unit states.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
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
        for name in COMMANDS:
            with self.subTest(command=name):
                command = ROOT / 'bin' / name
                self.assertTrue(command.is_file(), f'missing canonical command {name}')
                self.assertFalse(command.is_symlink(), 'canonical command must not be alias')
                self.assertTrue(os.access(command, os.X_OK))
                self.assertIn(name, manifest)
        for prefix in ('claude-control', 'claude-agent', 'claude-rc'):
            self.assertFalse(list((ROOT / 'bin').glob(prefix + '*')))
            self.assertNotIn(prefix, manifest)
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
                           'CLAUDE_RC_', 'CLAUDE_AGENTS_DIR'):
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
                            'CLAUDE_CONTROL_', 'CLAUDE_RC_', 'CLAUDE_AGENTS_DIR'):
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
    if unit:
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
                     'ai-control.service', 'ai-agent-reconciler.service', 'ccsession-test.service'):
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


if __name__ == '__main__':
    unittest.main()
