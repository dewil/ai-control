#!/usr/bin/env python3
"""Blind runtime CLI integration tests, INV-CXRUN-01/02/07/08.

Only public commands and established test fixtures are used. All child HOME,
config, agent, reconciler and executable paths are private temporary fixtures.
No native/model/systemd/network operation is permitted by the fixture binaries.
"""
import importlib.machinery
import importlib.util
import json
import fcntl
import os
import sys
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[1]


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='cxtask-wiring-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bin = self.base / 'bin'
        shutil.copytree(ROOT / 'bin', self.bin)
        self.home = self.base / 'home'
        self.agents = self.base / 'agents'
        self.project = self.base / 'project'
        self.mockbin = self.base / 'mockbin'
        for directory in (self.home, self.agents, self.project, self.mockbin):
            directory.mkdir(mode=0o700)
        self.effects = self.base / 'effects.jsonl'
        self.env = dict(os.environ, HOME=str(self.home),
                        XDG_CONFIG_HOME=str(self.home / 'config'),
                        XDG_STATE_HOME=str(self.home / 'state'),
                        XDG_RUNTIME_DIR=str(self.base / 'runtime'),
                        CLAUDE_CONFIG_DIR=str(self.base / 'claude'),
                        CODEX_HOME=str(self.base / 'codex'),
                        CLAUDE_AGENTS_DIR=str(self.agents),
                        CLAUDE_AGENT_SPOOL_BASE=str(self.base / 'spool'),
                        CLAUDE_RECONCILER_DIR=str(self.base / 'reconciler'),
                        CLAUDE_RC_PROJECTS_FILE=str(self.base / 'projects.yaml'),
                        CLAUDE_RC_TASK_TEMPLATE=str(self.base / 'task-template.yaml'),
                        CLAUDE_AGENT_PROBE_CMD='/usr/bin/true',
                        CLAUDE_AGENT_GENERATION='1', CLAUDE_AGENT_ATTEMPT='fixture-attempt',
                        PATH=str(self.mockbin) + ':' + os.environ['PATH'])
        # Boundary stubs use literal paths, never production environment hooks.
        for name in ('claude', 'codex', 'systemd-run', 'systemctl', 'gh'):
            script = self.mockbin / name
            script.write_text('#!/usr/bin/env python3\nimport json,sys\n'
                              f'with open({str(self.effects)!r},"a") as f: '
                              'f.write(json.dumps(sys.argv)+"\\n")\n'
                              'if "show" in sys.argv:\n'
                              ' print("LoadState=not-found\\nActiveState=inactive\\nControlGroup=")\n'
                              ' sys.exit(0)\n'
                              'if "is-active" in sys.argv: sys.exit(3)\n'
                              'sys.exit(2)\n')
            script.chmod(0o700)
        self.env['CLAUDE_BIN'] = str(self.mockbin / 'claude')
        codex_template = ROOT / 'examples/task-codex-template.yaml.example'
        self.codex_template = self.base / 'task-codex-template.yaml'
        if codex_template.is_file():
            shutil.copyfile(codex_template, self.codex_template)
        self.env['CLAUDE_RC_CODEX_TASK_TEMPLATE'] = str(self.codex_template)
        (self.base / 'projects.yaml').write_text(yaml.safe_dump({'fixture': {'path': str(self.project), 'integrate': 'none'}}))
        (self.base / 'task-template.yaml').write_text(self.template())
        self.git('init', '-q', '--initial-branch=main', str(self.project))
        (self.project / 'base.txt').write_text('base\n')
        self.git('-C', str(self.project), 'add', 'base.txt')
        self.git('-C', str(self.project), '-c', 'user.name=Fixture',
                 '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'base')

    def template(self, extra=''):
        return ('schema: 1\nname: {{name}}\ntype: event\nrole: none\n'
                'project: {{project}}\ngoal: {{goal}}\nautonomy: suggest\n'
                'memory_max_mb: 100\nlimits: {runs_per_day: 100, run_timeout_s: 20}\n'
                'source: {kind: spool, replay_window_h: 72}\n' + extra)

    def run_cmd(self, command, *args):
        return subprocess.run([str(self.bin / command), *map(str, args)], env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=25)

    def git(self, *args):
        return subprocess.run(['git', *args], env=self.env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=10).stdout.strip()

    def create(self, engine=None, name='task-fixture'):
        args = ['agent', 'new-task', '--name', name, '--project', 'fixture', '--text', 'owned fixture task']
        if engine is not None:
            args += ['--engine', engine]
        return self.run_cmd('claude-rc', *args)

    def spec(self, name):
        return yaml.safe_load((self.agents / name / 'spec.yaml').read_text())

    def bot_handle(self, text, update_id=120001):
        # Existing public parse_command/handle entry used by TG polling. No send.
        script = '''import importlib.machinery,importlib.util,json,sys
loader=importlib.machinery.SourceFileLoader('wiring_bot',sys.argv[1])
spec=importlib.util.spec_from_loader(loader.name,loader)
bot=importlib.util.module_from_spec(spec); loader.exec_module(bot)
cmd,arg=bot.parse_command(sys.argv[2])
result=bot.handle(cmd,arg,update_id=int(sys.argv[3]),from_id=555)
print(json.dumps(result,ensure_ascii=False))
'''
        return subprocess.run(['python3', '-c', script, str(self.bin / 'claude-agent-tgbot'),
                               text, str(update_id)], env=self.env, text=True,
                              capture_output=True, timeout=25)

    def test_default_creator_remains_claude_without_acl_translation(self):
        # INV-CXRUN-01
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = self.spec('task-fixture')
        self.assertIn(spec.get('engine'), (None, 'claude'))
        self.assertNotIn('codex_state_id', json.loads((self.agents / 'task-fixture/control.json').read_text()))

    def test_explicit_codex_creates_worktree_drain_and_private_identity(self):
        # INV-CXRUN-01
        result = self.create('codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        agent = self.agents / 'task-fixture'
        spec = self.spec('task-fixture')
        self.assertEqual((spec['engine'], spec['type'], spec['runtime'], spec['workspace']),
                         ('codex', 'event', 'drain', 'worktree'))
        control = json.loads((agent / 'control.json').read_text())
        self.assertIs(type(control['codex_state_id']), str)
        self.assertEqual(str(uuid.UUID(control['codex_state_id'])), control['codex_state_id'])
        self.assertTrue((agent / 'work/.git').is_file())
        state_root = self.base / 'codex-task-state'
        self.assertTrue(state_root.is_dir(), 'published Codex TASK has no private registry')
        self.assertEqual(state_root.stat().st_mode & 0o777, 0o700)
        records = list(state_root.rglob('*.json'))
        self.assertTrue(records, 'published Codex TASK has no durable registry record')
        self.assertTrue(any(control['codex_state_id'] in record.read_text() or
                            control['codex_state_id'] in str(record.relative_to(state_root))
                            for record in records), 'registry must bind published identity')
        for record in records:
            self.assertEqual(record.stat().st_mode & 0o777, 0o600)
            self.assertEqual(record.stat().st_uid, os.getuid())
            self.assertEqual(record.stat().st_nlink, 1)
        for path in (agent / '.lock', agent / 'inbox/.inbox.lock'):
            self.assertTrue(path.is_file(), str(path))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('session_id', spec)
        self.assertFalse(any('Bash' in str(spec.get(key, '')) for key in ('allow_tools', 'allowed_tools')))

    def creator_snapshot(self, name):
        # Only disposable fixture files; byte snapshots catch mutations/new events.
        roots = [self.agents / name, self.base / 'spool' / name, self.base / 'codex-task-state']
        result = {}
        for root in roots:
            for path in root.rglob('*') if root.exists() else []:
                if path.is_symlink():
                    result[str(path.relative_to(self.base))] = ('symlink', os.readlink(path))
                elif path.is_file():
                    result[str(path.relative_to(self.base))] = ('file', path.read_bytes())
        return result

    def matching_legacy_worktree_template(self):
        # Match Codex's type/project/workspace/runtime so a refusal cannot be
        # explained by an unrelated compatibility mismatch.
        (self.base / 'task-template.yaml').write_text(self.template('workspace: worktree\nruntime: drain\n'))

    def test_existing_claude_cannot_silently_satisfy_explicit_codex_request(self):
        # INV-CXRUN-01: absence engine is immutable default Claude, not migration.
        self.matching_legacy_worktree_template()
        for stored_engine in (None, 'claude'):
            name = 'task-engine-default' if stored_engine is None else 'task-engine-explicit'
            with self.subTest(stored_engine=stored_engine):
                created = self.create(name=name)
                self.assertEqual(created.returncode, 0, created.stderr)
                if stored_engine is not None:
                    spec_path = self.agents / name / 'spec.yaml'
                    spec = yaml.safe_load(spec_path.read_text())
                    spec['engine'] = stored_engine
                    spec_path.write_text(yaml.safe_dump(spec))
                agent = self.agents / name
                (agent / 'work/keep-dirty.txt').write_text('existing private work must survive\n')
                before = self.creator_snapshot(name)
                head = self.git('-C', str(agent / 'work'), 'rev-parse', 'HEAD')
                branches = self.git('-C', str(self.project), 'branch', '--list')
                result = self.create('codex', name=name)
                self.assertNotEqual(result.returncode, 0, 'existing Claude must not report Codex request success')
                self.assertEqual(self.creator_snapshot(name), before)
                self.assertEqual(self.git('-C', str(agent / 'work'), 'rev-parse', 'HEAD'), head)
                self.assertEqual(self.git('-C', str(self.project), 'branch', '--list'), branches)

    def test_existing_codex_cannot_silently_satisfy_default_or_explicit_claude(self):
        # INV-CXRUN-01: reverse request also refuses immutable engine migration.
        self.matching_legacy_worktree_template()
        name = 'task-existing-codex'
        created = self.create('codex', name=name)
        self.assertEqual(created.returncode, 0, created.stderr)
        agent = self.agents / name
        (agent / 'work/keep-dirty.txt').write_text('existing Codex work must survive\n')
        for requested_engine in (None, 'claude'):
            with self.subTest(requested_engine=requested_engine):
                before = self.creator_snapshot(name)
                head = self.git('-C', str(agent / 'work'), 'rev-parse', 'HEAD')
                branches = self.git('-C', str(self.project), 'branch', '--list')
                result = self.create(requested_engine, name=name)
                self.assertNotEqual(result.returncode, 0, 'existing Codex must not report Claude request success')
                self.assertEqual(self.creator_snapshot(name), before)
                self.assertEqual(self.git('-C', str(agent / 'work'), 'rev-parse', 'HEAD'), head)
                self.assertEqual(self.git('-C', str(self.project), 'branch', '--list'), branches)

    def test_existing_same_engine_creation_remains_idempotent_without_new_events(self):
        # INV-CXRUN-01: default Claude and explicit Codex each keep positive replay.
        self.matching_legacy_worktree_template()
        for engine, name in ((None, 'task-same-claude'), ('codex', 'task-same-codex')):
            with self.subTest(engine=engine):
                first = self.create(engine, name=name)
                self.assertEqual(first.returncode, 0, first.stderr)
                before = self.creator_snapshot(name)
                result = self.create(engine, name=name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.creator_snapshot(name), before)

    def test_unknown_engine_has_no_claude_fallback_or_publication(self):
        # INV-CXRUN-01
        result = self.create('unknown-engine')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip() or result.stdout.strip())
        self.assertFalse((self.agents / 'task-fixture').exists())
        self.assertFalse((self.base / 'spool/task-fixture').exists())

    def test_tg_codex_routes_to_real_creator(self):
        # INV-CXRUN-01
        result = self.bot_handle('/new --engine codex fixture owned task text')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.agents / 'task-tg120001/spec.yaml').exists(), result.stdout)
        self.assertEqual(self.spec('task-tg120001')['engine'], 'codex')

    def test_tg_default_creator_preserved(self):
        # INV-CXRUN-01
        result = self.bot_handle('/new fixture owned task text')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.spec('task-tg120001').get('engine'), (None, 'claude'))

    def test_tg_engine_parser_refuses_unknown_missing_duplicate_and_misplaced_flags(self):
        # INV-CXRUN-01
        for index, text in enumerate(('/new --engine unknown fixture task', '/new --engine',
                                      '/new --engine codex --engine claude fixture task',
                                      '/new --engine codex --bad fixture task')):
            with self.subTest(text=text):
                result = self.bot_handle(text, 120010 + index)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((self.agents / f'task-tg{120010 + index}').exists(), result.stdout)

    def test_codex_template_is_separate_from_legacy_and_rejects_incompatible_profile(self):
        # INV-CXRUN-01
        self.assertTrue(self.codex_template.is_file(), 'dedicated Codex template is not shipped')
        original = self.codex_template.read_text()
        for field, value in (('workspace', 'direct'), ('runtime', 'handoff'), ('type', 'mission')):
            with self.subTest(field=field):
                template = yaml.safe_load(original.replace('{{name}}', 'task-fixture')
                                           .replace('{{project}}', str(self.project))
                                           .replace('{{goal}}', 'fixture'))
                template[field] = value
                self.codex_template.write_text(yaml.safe_dump(template))
                result = self.create('codex')
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.agents / 'task-fixture').exists())
        self.codex_template.write_text(original)

    def test_creator_initializes_private_final_binding_before_control_publication(self):
        # INV-CXRUN-01. Intercept established control IO CLI in trusted BIN tree.
        actual_io = self.bin / 'fixture-real-control-io'
        shutil.copyfile(self.bin / 'claude-agent-io', actual_io)
        actual_io.chmod(0o700)
        observed = self.base / 'publication.jsonl'
        state_root = self.base / 'codex-task-state'
        wrapper = self.bin / 'claude-agent-io'
        wrapper.write_text('#!/usr/bin/env python3\nimport os,sys,json,pathlib\n'
            'if __name__ != "__main__":\n'
            ' from importlib.machinery import SourceFileLoader\n'
            ' import importlib.util\n'
            f' loader=SourceFileLoader("fixture_real_control_io",{str(actual_io)!r})\n'
            ' spec=importlib.util.spec_from_loader(loader.name,loader)\n'
            ' module=importlib.util.module_from_spec(spec)\n'
            ' sys.modules[loader.name]=module\n'
            ' loader.exec_module(module)\n'
            ' validate_control=module.validate_control\n'
            'else:\n'
            f' root=pathlib.Path({str(state_root)!r})\n'
            ' if any("codex_state_id" in arg for arg in sys.argv[1:]):\n'
            '  records=list(root.rglob("*.json")) if root.is_dir() else []\n'
            '  valid=bool(records) and root.stat().st_mode & 0o777 == 0o700\n'
            f'  with open({str(observed)!r},"a") as f: f.write(json.dumps(dict(valid=valid))+"\\n")\n'
            '  if not valid: sys.exit(2)\n'
            f' os.execv({str(actual_io)!r},[{str(actual_io)!r},*sys.argv[1:]])\n')
        wrapper.chmod(0o700)
        compile(wrapper.read_text(), str(wrapper), 'exec')
        result = self.create('codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(observed.is_file(), 'Codex identity was not published through existing control IO')
        self.assertTrue(all(json.loads(line)['valid'] for line in observed.read_text().splitlines()))
        final = str(self.agents / 'task-fixture')
        records = list(state_root.rglob('*.json'))
        self.assertTrue(any(final in record.read_text() for record in records), 'index must pin final agent path')
        self.assertFalse(any('.new-task-fixture.' in record.read_text() for record in records))

    def test_strict_usd_cap_refuses_codex_before_claim(self):
        # INV-CXRUN-08/02
        agent = self.hook_fixture()
        (agent / 'done.json').unlink()
        spec_path = agent / 'spec.yaml'
        spec = yaml.safe_load(spec_path.read_text())
        spec['limits']['week_usd_cap'] = 1
        spec_path.write_text(yaml.safe_dump(spec))
        inflight = agent / 'inbox/inflight/fixture-key.json'
        pending = agent / 'inbox/pending'
        pending.mkdir(exist_ok=True)
        target = pending / inflight.name
        inflight.rename(target)
        before = target.read_bytes()
        result = self.run_cmd('claude-agent-run', 'drain', agent)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(inflight.exists())

    def test_shim_execute_requires_actual_live_lease(self):
        # INV-CXRUN-02
        shim = self.bin / 'codex-task-runtime'
        self.assertTrue(shim.is_file(), 'runtime CLI shim is not implemented')
        created = self.create('codex')
        self.assertEqual(created.returncode, 0, created.stderr)
        agent = self.agents / 'task-fixture'
        before = (agent / 'control.json').read_bytes()
        result = self.run_cmd('codex-task-runtime', 'execute', agent,
                              '--event', 'unclaimed', '--generation', '1', '--attempt', 'fixture-attempt')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual((agent / 'control.json').read_bytes(), before)
        if self.effects.exists():
            self.assertNotIn('app-server', self.effects.read_text())

    def test_shim_rejects_arbitrary_rpc_config_and_adapter_flags(self):
        # INV-CXRUN-02/04
        self.assertTrue((self.bin / 'codex-task-runtime').is_file(), 'runtime CLI shim is not implemented')
        for flag in ('--rpc-method', '--config', '--adapters', '--executable'):
            with self.subTest(flag=flag):
                result = self.run_cmd('codex-task-runtime', 'preflight', self.agents / 'nonexistent', flag, 'untrusted')
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.effects.exists())


    def hook_fixture(self, state='requested', finalized=True, lease='none'):
        """Real existing creator/worktree/done IO; Codex marker models orphan host."""
        name = 'task-hook'
        spec = self.base / 'hook.yaml'
        spec.write_text(yaml.safe_dump(dict(schema=1, name=name, type='event', role='none',
            project=str(self.project), goal='hook fixture', autonomy='suggest', memory_max_mb=100,
            limits=dict(runs_per_day=100, run_timeout_s=20), source=dict(kind='spool'), workspace='worktree')))
        result = self.run_cmd('claude-rc', 'agent', 'create', name, '--spec', spec)
        self.assertEqual(result.returncode, 0, result.stderr)
        agent = self.agents / name
        (agent / 'work/change.txt').write_text('owned committed change\n')
        self.git('-C', str(agent / 'work'), 'add', 'change.txt')
        self.git('-C', str(agent / 'work'), '-c', 'user.name=Fixture', '-c',
                 'user.email=fixture@example.invalid', 'commit', '-qm', 'task')
        inbox = agent / 'inbox/inflight'
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / 'fixture-key.json').write_text(json.dumps(dict(schema=1, key='fixture-key',
            source_ns='test', native_id='0', received_at='2026-01-01T00:00:00Z',
            meta=dict(attempts=0, recoveries=0, quarantined=False, next_attempt_at=None, history=[]),
            payload=dict(text='fixture'))))
        done_env = dict(self.env, CLAUDE_AGENT_DIR=str(agent), CLAUDE_AGENT_EVENT_KEY='fixture-key')
        done = subprocess.run([str(self.bin / 'claude-agent-done'), '--summary', 'owned done'],
                              env=done_env, capture_output=True, text=True, timeout=15)
        self.assertEqual(done.returncode, 0, done.stderr)
        path = agent / 'done.json'
        data = json.loads(path.read_text())
        data.update(state=state, finalized=finalized, verdict_at='2026-01-01T00:00:00Z',
                    verdict_by='fixture', verdict_comment=None, integrate_mode=None, integrate_ref=None,
                    phase_attempts=0, phase_error=None)
        path.write_text(json.dumps(data))
        spec_data = yaml.safe_load((agent / 'spec.yaml').read_text())
        spec_data.update(engine='codex', runtime='drain')
        (agent / 'spec.yaml').write_text(yaml.safe_dump(spec_data))
        control_path = agent / 'control.json'
        control = json.loads(control_path.read_text())
        control['codex_state_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        control['lease']['state'] = lease
        control['desired'] = 'stopped'
        control['attention'] = dict(reason='resume_failed', since='2026-01-01T00:00:00Z', episode='fixture', count=1)
        control_path.write_text(json.dumps(control))
        (agent / 'work/private-dirty.txt').write_text('must remain reviewable\n')
        self.barrier_log = self.base / 'native-barrier.jsonl'
        # Trusted test installation directory only. Public API names/signatures
        # from the spec; no production environment loader or private function.
        module = self.bin / '_codex_task_runtime.py'
        module.write_text("import json\nclass RuntimeError(Exception): pass\n"
            "class CodexTaskRuntime:\n"
            " def __init__(self,agent_dir,**kwargs): self.agent_dir=str(agent_dir)\n"
            " def static_preflight(self,*,deadline): return self.require_drained(deadline=deadline)\n"
            " def require_drained(self,*,deadline):\n"
            f"  with open({str(self.barrier_log)!r},'a') as f: f.write(json.dumps(['barrier',self.agent_dir])+'\\n')\n"
            "  raise RuntimeError('native drain refused')\n"
            " def revoke_and_drain(self,reason,*,deadline): return self.require_drained(deadline=deadline)\n"
            " def reconcile(self,*,deadline): return self.require_drained(deadline=deadline)\n")
        shim = self.bin / 'codex-task-runtime'
        shim.write_text('#!/usr/bin/env python3\nimport json,sys\n'
            f'with open({str(self.barrier_log)!r},"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
            'print(json.dumps(dict(drained=False, reason="native drain refused")))\n'
            'sys.exit(2)\n')
        shim.chmod(0o700)
        compile(module.read_text(), str(module), 'exec')
        compile(shim.read_text(), str(shim), 'exec')
        # Creation/fixture effects excluded; ensuing systemd effects are observed.
        self.effects.unlink(missing_ok=True)
        return agent

    def assert_refused_effects(self, agent, command, *args):
        done_before = json.loads((agent / 'done.json').read_text())
        control_before = json.loads((agent / 'control.json').read_text())
        head_before = self.git('-C', str(self.project), 'rev-parse', 'HEAD')
        branches_before = self.git('-C', str(self.project), 'branch', '--list')
        work_head_before = self.git('-C', str(agent / 'work'), 'rev-parse', 'HEAD')
        result = self.run_cmd(command, *args)
        self.assertTrue(self.barrier_log.is_file(),
                        'native barrier was never invoked; stdout=' + result.stdout[:200] + ' stderr=' + result.stderr[:200])
        calls = [json.loads(line) for line in self.barrier_log.read_text().splitlines()]
        self.assertTrue(any('barrier' in call for call in calls), calls)
        self.assertTrue(agent.is_dir(), 'agent must remain reviewable')
        self.assertEqual((agent / 'work/private-dirty.txt').read_text(), 'must remain reviewable\n')
        self.assertEqual(self.git('-C', str(self.project), 'rev-parse', 'HEAD'), head_before)
        self.assertEqual(self.git('-C', str(self.project), 'branch', '--list'), branches_before)
        self.assertEqual(self.git('-C', str(agent / 'work'), 'rev-parse', 'HEAD'), work_head_before)
        done_after = json.loads((agent / 'done.json').read_text())
        for field in ('state', 'finalized', 'commit_sha', 'cleaned_at', 'archived_at', 'integrated_at'):
            self.assertEqual(done_after.get(field), done_before.get(field), field)
        control_after = json.loads((agent / 'control.json').read_text())
        self.assertEqual(control_after['lease'], control_before['lease'])
        self.assertFalse((self.base / 'tombstones/task-hook.json').exists())
        if self.effects.exists():
            effects = [json.loads(line) for line in self.effects.read_text().splitlines()]
            self.assertFalse(any('stop' in call or 'kill' in call for call in effects), effects)

    def test_runner_explicit_codex_preflight_refuses_before_claim_and_claude_fallback(self):
        # INV-CXRUN-02
        agent = self.hook_fixture()
        (agent / 'done.json').unlink()
        inflight = agent / 'inbox/inflight/fixture-key.json'
        pending = agent / 'inbox/pending'
        pending.mkdir(exist_ok=True)
        target = pending / inflight.name
        inflight.rename(target)
        before = target.read_bytes()
        result = self.run_cmd('claude-agent-run', 'drain', agent)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertTrue(target.is_file(), 'preflight refusal must leave event unclaimed')
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(inflight.exists())
        if self.effects.exists():
            self.assertFalse(any(Path(json.loads(line)[0]).name in ('claude', 'codex', 'systemd-run')
                                 for line in self.effects.read_text().splitlines()))

    def test_runner_unknown_engine_refuses_without_claude_fallback(self):
        # INV-CXRUN-01/02
        agent = self.hook_fixture()
        spec_path = agent / 'spec.yaml'
        spec = yaml.safe_load(spec_path.read_text())
        spec['engine'] = 'unsupported-engine'
        spec_path.write_text(yaml.safe_dump(spec))
        result = self.run_cmd('claude-agent-run', 'drain', agent)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.barrier_log.exists(), 'unknown engine must not dispatch Codex')
        if self.effects.exists():
            self.assertFalse(any(Path(json.loads(line)[0]).name == 'claude'
                                 for line in self.effects.read_text().splitlines()))

    def test_status_reports_codex_and_unknown_usd(self):
        # INV-CXRUN-08
        agent = self.hook_fixture()
        result = self.run_cmd('claude-rc', 'agent', 'status', agent.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('codex', result.stdout.lower())
        self.assertRegex(result.stdout.lower(), r'неизвест|unknown|null')

    def test_codex_status_does_not_turn_null_or_unpriced_zero_into_known_usd(self):
        # INV-CXRUN-08
        agent = self.hook_fixture()
        usage = agent / 'inbox/usage.json'
        for value in (None, 0):
            with self.subTest(cost_usd=value):
                usage.write_text(json.dumps(dict(day='2026-10-03', day_runs=0,
                    week='2026-W40', week_runs=0, cost_usd=value, exhausted_until=None)))
                result = self.run_cmd('claude-rc', 'agent', 'status', agent.name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertRegex(result.stdout.lower(), r'неизвест|unknown|null')
                self.assertNotRegex(result.stdout, r'cost=\$0(?:\s|$)')

    def bot_render(self, function, *args):
        script = """import importlib.machinery,importlib.util,json,sys
loader=importlib.machinery.SourceFileLoader('wiring_renderer',sys.argv[1])
spec=importlib.util.spec_from_loader(loader.name,loader)
bot=importlib.util.module_from_spec(spec);loader.exec_module(bot)
print(json.dumps(getattr(bot,sys.argv[2])(*json.loads(sys.argv[3])),ensure_ascii=False))
"""
        result = subprocess.run(['python3', '-c', script, str(self.bin / 'claude-agent-tgbot'),
                                 function, json.dumps(args)], env=self.env, capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_task_done_cards_show_codex_phase_operation_thread_turn_and_unknown_usd(self):
        # INV-CXRUN-08. Existing TASK done-card entry, separate interactive sessions UI.
        detail = dict(kind='done', agent='task-fixture', project='fixture',
            summary='owned done', commit_sha='a' * 40, branch='task/task-fixture',
            changes=None, empty=False, engine='codex',
            operation_id='12345678-1234-4000-8000-000000000001',
            thread_id='native-thread-fixture', turn_id='native-turn-fixture',
            cost_usd=None, reason='native bounded refusal')
        for phase in ('bootstrap', 'running', 'waiting_approval', 'asked', 'draining', 'blocked'):
            with self.subTest(phase=phase):
                detail['phase'] = phase
                text, keyboard = self.bot_render('question_card', detail)
                self.assertIsInstance(text, str)
                for value in ('codex', phase, detail['operation_id'], detail['thread_id'], detail['turn_id']):
                    self.assertIn(value, text.lower())
                self.assertRegex(text.lower(), r'неизвест|unknown|null')
                buttons = [button for row in keyboard['inline_keyboard'] for button in row]
                self.assertFalse(any('model' in button.get('callback_data', '').lower() or
                                     'модель' in button.get('text', '').lower() for button in buttons))

    def test_actual_task_menu_routes_from_agents_and_preserves_codex_identity(self):
        # INV-CXRUN-08. Level obtained from real public menu callback, no invented /tasks command.
        agent = self.hook_fixture()
        text, keyboard = self.bot_render('menu_view', 'agents')
        buttons = [button for row in keyboard['inline_keyboard'] for button in row]
        entry = next(button for button in buttons if button['text'] == agent.name)
        self.assertTrue(entry['callback_data'].startswith('m:'))
        text, keyboard = self.bot_render('menu_view', entry['callback_data'][2:])
        self.assertIn('codex', text.lower())
        self.assertRegex(text.lower(), r'неизвест|unknown|null')
        buttons = [button for row in keyboard['inline_keyboard'] for button in row]
        self.assertFalse(any('model' in button.get('callback_data', '').lower() or
                             'модель' in button.get('text', '').lower() for button in buttons))

    def isolated_installer(self):
        # Existing test-install-idempotent.sh public Darwin harness. Never live install.
        launchctl = self.mockbin / 'launchctl'
        launchctl.write_text('#!/bin/sh\nexit 0\n')
        launchctl.chmod(0o700)
        for name in ('curl', 'wget', 'pip', 'pip3'):
            guard = self.mockbin / name
            guard.write_text('#!/bin/sh\nexit 91\n')
            guard.chmod(0o700)
        (self.home / 'Library/LaunchAgents').mkdir(parents=True, exist_ok=True)
        env = dict(self.env, CLAUDE_CONTROL_OS='Darwin')
        return subprocess.run([str(ROOT / 'install.sh'), '--prefix', str(self.base / 'installed'),
                               '--label', 'com.test.codex-task-wiring'], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_install_seeds_dedicated_codex_template_and_is_idempotent(self):
        # INV-CXRUN-01/08
        result = self.isolated_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        template = self.home / '.claude-control/task-codex-template.yaml'
        self.assertTrue(template.is_file(), 'installer did not seed dedicated Codex template')
        before = template.read_bytes()
        legacy = self.home / '.claude-control/task-template.yaml'
        legacy_before = legacy.read_bytes()
        result = self.isolated_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(template.read_bytes(), before)
        self.assertEqual(legacy.read_bytes(), legacy_before)
        for name in ('codex-task-runtime', '_codex_task_runtime.py'):
            self.assertTrue((self.base / 'installed/bin' / name).is_file(), name)

    def test_install_preserves_custom_codex_and_legacy_templates(self):
        # INV-CXRUN-01/08
        directory = self.home / '.claude-control'
        directory.mkdir()
        codex = directory / 'task-codex-template.yaml'
        legacy = directory / 'task-template.yaml'
        codex.write_text('# user custom Codex template\ncustom: codex-sentinel\n')
        legacy.write_text('# user custom Claude template\ncustom: claude-sentinel\n')
        before = codex.read_bytes(), legacy.read_bytes()
        result = self.isolated_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((codex.read_bytes(), legacy.read_bytes()), before)

    def dependency_fixture(self, agent, with_venv, *, symlinks=False, original_has_websockets=False):
        # Public Python dependency discovery boundary. No production bypass added.
        import venv
        hookdir = self.base / 'python-startup-fixture'
        hookdir.mkdir()
        interpreter = self.home / '.local/share/claude-control/codex-venv/bin/python'
        venv_root = interpreter.parent.parent
        if with_venv:
            venv.EnvBuilder(with_pip=False, symlinks=symlinks).create(venv_root)
            site = next((venv_root / 'lib').glob('python*/site-packages'))
            package = site / 'websockets'
            package.mkdir()
            (package / '__init__.py').write_text('__version__ = "15.0.1"\n')
            metadata = site / 'websockets-15.0.1.dist-info'
            metadata.mkdir()
            (metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: websockets\nVersion: 15.0.1\n')
        if original_has_websockets:
            outside_package = hookdir / 'websockets'
            outside_package.mkdir()
            (outside_package / '__init__.py').write_text('__version__ = "15.0.1"\n')
            outside_metadata = hookdir / 'websockets-15.0.1.dist-info'
            outside_metadata.mkdir()
            (outside_metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: websockets\nVersion: 15.0.1\n')
        self.reexec_log = self.base / 'reexec.jsonl'
        # Record native interpreter startup before the shared command dispatcher.
        # Missing dependency applies only to original interpreter; the private
        # venv has a versioned dependency fixture. Real transport is never called.
        source = ('import sys,json,importlib.util\n'
            f'if sys.prefix == {str(venv_root)!r}:\n'
            f' with open({str(self.reexec_log)!r},"a") as f: f.write(json.dumps(sys.argv)+"\\n")\n'
            'else:\n'
            + (' pass\n' if original_has_websockets else
               ' original=importlib.util.find_spec\n'
               ' importlib.util.find_spec=lambda name,*a,**k: None if name=="websockets" else original(name,*a,**k)\n'))
        (hookdir / 'sitecustomize.py').write_text(source)
        compile(source, 'sitecustomize.py', 'exec')
        self.env['PYTHONPATH'] = str(hookdir)
        self.env.pop('CODEX_RC_PYTHON', None)

    def test_missing_websockets_is_visible_refusal_before_executor_flock(self):
        # INV-CXRUN-02
        agent = self.hook_fixture()
        self.dependency_fixture(agent, with_venv=False)
        lockpath = agent / 'inbox/.executor.lock'
        with lockpath.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.run_cmd('claude-agent-run', 'drain', agent)
        self.assertNotEqual(result.returncode, 5, 'missing dependency was checked after executor flock')
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex((result.stderr + result.stdout).lower(), r'websockets|dependenc|venv')
        self.assertFalse(self.reexec_log.exists())
        self.assertFalse(self.effects.exists(), 'dependency refusal must precede unit/model effects')

    def test_codex_venv_reexec_precedes_flock_and_preserves_loop_and_drain_argv(self):
        # INV-CXRUN-02
        agent = self.hook_fixture()
        self.dependency_fixture(agent, with_venv=True)
        lockpath = agent / 'inbox/.executor.lock'
        with lockpath.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for mode in ('loop', 'drain'):
                with self.subTest(mode=mode):
                    self.reexec_log.unlink(missing_ok=True)
                    result = self.run_cmd('claude-agent-run', mode, agent)
                    self.assertTrue(self.reexec_log.is_file(),
                                    'verified venv must start before executor flock; ' + result.stderr)
                    calls = [json.loads(line) for line in self.reexec_log.read_text().splitlines()]
                    self.assertTrue(any(call[1:] == [mode, str(agent)] for call in calls), calls)
                    self.assertFalse(self.effects.exists())

    def test_standard_symlink_venv_reexec_precedes_flock_and_preserves_argv(self):
        # INV-CXRUN-02. Standard installed venv shares the system Python ELF;
        # matching realpath is not evidence that sys.prefix already is the venv.
        agent = self.hook_fixture()
        self.dependency_fixture(agent, with_venv=True, symlinks=True)
        interpreter = self.home / '.local/share/claude-control/codex-venv/bin/python'
        self.assertTrue(interpreter.is_symlink(), 'fixture must exercise actual shared-ELF venv')
        self.assertEqual(interpreter.resolve(), Path(sys.executable).resolve())
        lockpath = agent / 'inbox/.executor.lock'
        with lockpath.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for mode in ('loop', 'drain'):
                with self.subTest(mode=mode):
                    self.reexec_log.unlink(missing_ok=True)
                    result = self.run_cmd('claude-agent-run', mode, agent)
                    self.assertTrue(self.reexec_log.is_file(),
                                    'shared-ELF native venv must start before executor flock; ' + result.stderr)
                    calls = [json.loads(line) for line in self.reexec_log.read_text().splitlines()]
                    self.assertTrue(any(call[1:] == [mode, str(agent)] for call in calls), calls)
                    self.assertFalse(self.effects.exists())

    def test_importable_websockets_outside_verified_venv_still_reexecs_before_flock(self):
        # INV-CXRUN-02. Correct importable dependency version alone does not
        # establish the verified interpreter/prefix required by the launcher.
        agent = self.hook_fixture()
        self.dependency_fixture(agent, with_venv=True, symlinks=True, original_has_websockets=True)
        venv_root = self.home / '.local/share/claude-control/codex-venv'
        probe = subprocess.run([sys.executable, '-c',
            'import json,sys,websockets;print(json.dumps(dict(version=websockets.__version__,prefix=sys.prefix,path=websockets.__file__)))'],
            env=self.env, text=True, capture_output=True, timeout=5)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        dependency = json.loads(probe.stdout)
        self.assertEqual(dependency['version'], '15.0.1')
        self.assertNotEqual(Path(dependency['prefix']).resolve(), venv_root.resolve())
        self.assertFalse(Path(dependency['path']).is_relative_to(venv_root))
        self.assertFalse(self.reexec_log.exists(), 'original dependency probe must not impersonate verified venv')
        lockpath = agent / 'inbox/.executor.lock'
        with lockpath.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for mode in ('loop', 'drain'):
                with self.subTest(mode=mode):
                    self.reexec_log.unlink(missing_ok=True)
                    result = self.run_cmd('claude-agent-run', mode, agent)
                    self.assertTrue(self.reexec_log.is_file(),
                        'importable correct websockets outside verified venv cannot bypass reexec; ' + result.stderr)
                    calls = [json.loads(line) for line in self.reexec_log.read_text().splitlines()]
                    self.assertTrue(any(call[1:] == [mode, str(agent)] for call in calls), calls)
                    self.assertFalse(self.effects.exists())

    def test_actual_barrier_refuses_missing_registry_and_keeps_dirty_worktree(self):
        # INV-CXRUN-07. Actual controller/shim, NOT the refusal routing stub.
        self.assertTrue((ROOT / 'bin/codex-task-runtime').is_file(), 'actual runtime shim is absent')
        self.assertTrue((ROOT / 'bin/_codex_task_runtime.py').is_file(), 'actual runtime controller is absent')
        agent = self.hook_fixture()
        for name in ('codex-task-runtime', '_codex_task_runtime.py'):
            shutil.copyfile(ROOT / 'bin' / name, self.bin / name)
        before = (agent / 'control.json').read_bytes()
        result = self.run_cmd('codex-task-runtime', 'barrier', agent, '--reason', 'shutdown')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(agent.is_dir())
        self.assertEqual((agent / 'work/private-dirty.txt').read_text(), 'must remain reviewable\n')
        self.assertEqual((agent / 'control.json').read_bytes(), before)
        self.assertFalse((self.base / 'codex-task-state').exists(), 'barrier may not initialize lost registry')
        if self.effects.exists():
            self.assertFalse(any(Path(json.loads(line)[0]).name in ('codex', 'systemd-run')
                                 for line in self.effects.read_text().splitlines()))

    def test_direct_done_accept_must_gate_before_acceptance(self):
        # INV-CXRUN-07
        agent = self.hook_fixture()
        sha = json.loads((agent / 'done.json').read_text())['commit_sha']
        self.assert_refused_effects(agent, 'claude-agent-run', 'done-verdict', agent, '--accept', '--expect-sha', sha[:8])

    def test_direct_cancel_must_gate_before_branch_handling(self):
        # INV-CXRUN-07
        agent = self.hook_fixture()
        self.assert_refused_effects(agent, 'claude-agent-run', 'done-verdict', agent, '--cancel')

    def test_direct_finalize_must_gate_before_git_checkpoint(self):
        # INV-CXRUN-07
        agent = self.hook_fixture(finalized=False)
        self.assert_refused_effects(agent, 'claude-agent-run', 'done-advance', agent)

    def test_direct_integrate_must_gate_before_project_git(self):
        # INV-CXRUN-07
        agent = self.hook_fixture(state='accepted')
        self.assert_refused_effects(agent, 'claude-agent-run', 'done-advance', agent)

    def test_direct_cleanup_must_gate_before_worktree_delete(self):
        # INV-CXRUN-07
        agent = self.hook_fixture(state='integrated')
        self.assert_refused_effects(agent, 'claude-agent-run', 'done-advance', agent)

    def test_direct_cancelled_cleanup_must_gate_even_with_forced_dirty_policy(self):
        # INV-CXRUN-07
        agent = self.hook_fixture(state='cancelled')
        self.assert_refused_effects(agent, 'claude-agent-run', 'done-advance', agent)

    def test_direct_archive_must_gate_before_name_reuse(self):
        # INV-CXRUN-07
        agent = self.hook_fixture(state='cleaned')
        self.assert_refused_effects(agent, 'claude-agent-run', 'done-advance', agent)

    def test_rc_task_cancel_force_cannot_bypass_native_drain(self):
        # INV-CXRUN-07
        agent = self.hook_fixture()
        self.assert_refused_effects(agent, 'claude-rc', 'agent', 'task-cancel', agent.name, '--force')

    def test_rc_stop_must_gate_orphan_native_with_no_executor_lease(self):
        # INV-CXRUN-07
        agent = self.hook_fixture()
        self.assert_refused_effects(agent, 'claude-rc', 'agent', 'stop', agent.name)

    def test_rc_resolve_must_gate_before_releasing_native_hold(self):
        # INV-CXRUN-07
        agent = self.hook_fixture()
        self.assert_refused_effects(agent, 'claude-rc', 'agent', 'resolve', agent.name, '--resume')

    def test_reconciler_shutdown_must_gate_before_lease_none_fastpath(self):
        # INV-CXRUN-07
        agent = self.hook_fixture(lease='none')
        self.assert_refused_effects(agent, 'claude-agent-reconciler', '--once')

    def test_reconciler_shutdown_must_gate_before_active_lease_release(self):
        # INV-CXRUN-07
        agent = self.hook_fixture(lease='active')
        self.assert_refused_effects(agent, 'claude-agent-reconciler', '--once')


if __name__ == '__main__':
    unittest.main()
