#!/usr/bin/env python3
"""Blind executor ownership checks for completion-bearing registered recovery.

Actual accepted store/inbox/control fixture; only the public controller and
native process boundary are fakes. No Git checkpoint/model/native call occurs.
"""
import fcntl
import importlib.util
import json
import shutil
from pathlib import Path
import subprocess
import time
import unittest
import venv

ROOT = Path(__file__).resolve().parents[1]
fixture_spec = importlib.util.spec_from_file_location(
    'native_answer_ownership_fixture', ROOT / 'tests/test-codex-task-native-answer.py')
fixture_module = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture_module)


class RecoveryOwnership(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.NativeAnswerContract('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.completion = f.opdir / 'completion.json'
        fixture_module.save(self.completion, dict(schema=1, operation_id=f.operation,
            task_incarnation=fixture_module.INC, generation=7, attempt_id='attempt-1',
            event_key=fixture_module.EVENT, thread_id='native-thread', turn_id='native-turn',
            request_id=31, call_id='native-done-call', request_digest='d' * 64,
            summary='owned staged completion awaiting trusted checkpoint', phase='requested',
            checkpoint=None, done_receipt=None))
        (f.opdir / 'completion.lock').touch(mode=0o600)
        self.before = self.completion.read_bytes()
        self.log = f.root / 'recovery-controller-calls.jsonl'
        self.effect = f.root / 'checkpoint-done-effect'
        # Preserve the real module and CLI main/parser/flock implementation.
        # NativeAnswerContract's unrelated controller-only seam is replaced
        # here by a test executable driver overriding ONLY public runtime_for.
        actual_runtime = ROOT / 'bin/_codex_task_runtime.py'
        if actual_runtime.is_file():
            shutil.copyfile(actual_runtime, f.bin / '_codex_task_runtime.py')
            driver = f.bin / 'codex-task-runtime'
            source = ('#!/usr/bin/env python3\nimport sys,json,pathlib\n'
                'import _codex_task_runtime as runtime\n'
                'RuntimeError=runtime.RuntimeError\n'
                'class FakeRecoveryController:\n'
                ' def __init__(self,agent_dir,**kwargs): self.agent_dir=str(agent_dir)\n'
                ' def static_preflight(self,*,deadline): return dict(ready=True,version="0.160.0",permission_profile="control_task",release_hashes={})\n'
                ' def reconcile(self,*,deadline):\n'
                f'  with open({str(self.log)!r},"a") as f: f.write(json.dumps(["reconcile",self.agent_dir])+"\\n")\n'
                f'  pathlib.Path({str(self.effect)!r}).write_text("trusted checkpoint/done continuation invoked")\n'
                f'  return dict(outcome="recovered",operations=[{f.operation!r}],reason=None)\n'
                ' def execute(self,event_key,generation,attempt_id,*,deadline):\n'
                f'  with open({str(self.log)!r},"a") as f: f.write(json.dumps(["execute",self.agent_dir])+"\\n")\n'
                '  raise RuntimeError("unexpected competing execute")\n'
                ' def require_drained(self,*,deadline): raise RuntimeError("fixture drain not granted")\n'
                ' def revoke_and_drain(self,reason,*,deadline): raise RuntimeError("fixture drain not granted")\n'
                'runtime.runtime_for=lambda agent_dir,*args,**kwargs: FakeRecoveryController(agent_dir,**kwargs)\n'
                'if __name__ == "__main__": sys.exit(runtime.main())\n')
            compile(source, str(driver), 'exec')
            driver.write_text(source)
            driver.chmod(0o700)
        # Existing verified-venv launcher path, actual offline Python venv. The
        # versioned dependency is only a discovery fixture; no transport runs.
        f.env.pop('CODEX_RC_PYTHON', None)
        venv_root = f.home / '.local/share/claude-control/codex-venv'
        venv.EnvBuilder(with_pip=False, symlinks=True).create(venv_root)
        site = next((venv_root / 'lib').glob('python*/site-packages'))
        package = site / 'websockets'
        package.mkdir()
        (package / '__init__.py').write_text('__version__="15.0.1"\n')
        metadata = site / 'websockets-15.0.1.dist-info'
        metadata.mkdir()
        (metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: websockets\nVersion: 15.0.1\n')
        self.lock = f.agent / 'inbox/.executor.lock'
        self.lock.touch(mode=0o600)

    def command(self, executable, *args):
        started = time.monotonic()
        result = subprocess.run([str(self.fixture.bin / executable), *map(str, args)],
            env=self.fixture.env, capture_output=True, text=True, timeout=5)
        self.assertLess(time.monotonic() - started, 3, 'competing executor refusal must be nonblocking')
        return result

    def unchanged(self):
        self.assertFalse(self.log.exists(), 'competing owner must prevent ALL controller.reconcile/execute calls')
        self.assertFalse(self.effect.exists(), 'competing owner must prevent checkpoint/done continuation')
        self.assertEqual(self.completion.read_bytes(), self.before)
        self.assertFalse(self.fixture.effects.exists(), 'competing owner must prevent native/process effects')

    def test_direct_reconcile_refuses_external_executor_owner_before_controller_effects(self):
        # INV-CXRUN-07: spec8413e4b direct reconcile is an executor writer.
        self.assertTrue((self.fixture.bin / 'codex-task-runtime').is_file(), 'public runtime CLI shim is absent')
        with self.lock.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.command('codex-task-runtime', 'reconcile', self.fixture.agent)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.unchanged()

    def test_direct_reconcile_free_owner_invokes_controller_once(self):
        # Positive control: busy refusal may not be an unrelated fixture error.
        self.assertTrue((self.fixture.bin / 'codex-task-runtime').is_file(), 'public runtime CLI shim is absent')
        result = self.command('codex-task-runtime', 'reconcile', self.fixture.agent)
        self.assertEqual(result.returncode, 0, result.stderr)
        outcome = json.loads(result.stdout)
        self.assertEqual(outcome['outcome'], 'recovered')
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(calls, [['reconcile', str(self.fixture.agent)]])
        self.assertTrue(self.effect.is_file())
        self.assertFalse(self.fixture.effects.exists())

    def test_shared_runner_recovery_refuses_external_executor_owner(self):
        # INV-CXRUN-07: shared recovery cannot race completion continuation.
        with self.lock.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.command('claude-agent-run', 'drain', self.fixture.agent)
        self.assertEqual(result.returncode, 5, result.stderr)
        self.unchanged()

    def test_direct_execute_competing_owner_preserves_existing_refusal(self):
        # Existing direct execute ownership baseline remains intact.
        self.assertTrue((self.fixture.bin / 'codex-task-runtime').is_file(), 'public runtime CLI shim is absent')
        with self.lock.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.command('codex-task-runtime', 'execute', self.fixture.agent,
                '--event', fixture_module.EVENT, '--generation', '7', '--attempt', 'attempt-1')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.unchanged()


if __name__ == '__main__':
    unittest.main()
