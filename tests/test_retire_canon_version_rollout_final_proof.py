#!/usr/bin/env python3
"""Independent final-state safety and public pending help contracts."""
import subprocess
import unittest

import test_retire_canon_version_rollout as base


class RetirementFinalProof(unittest.TestCase):
    setUp = base.Retirement.setUp
    tearDown = base.Retirement.tearDown
    legacy = base.Retirement.legacy
    preserved = base.Retirement.preserved

    def stateful_manager(self, mode):
        ctl = self.p/'stub/systemctl'
        ctl.write_text("""#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
old='claude-agent-canon-maintainer'
is_old=any(old in a for a in args)
with open(os.environ['RETIRE_CALLS'],'a') as f:
    f.write(json.dumps(args)+'\\n')
state=Path(os.environ['RETIRE_CALLS']+'.proof-state')
status=state.read_text() if state.exists() else 'active'
if 'stop' in args and is_old:
    status='failed' if os.environ['RETIRE_PROOF_MODE']=='failed' else 'inactive'
    state.write_text(status)
if 'disable' in args and is_old:
    (Path(os.environ['HOME'])/'.config/systemd/user/timers.target.wants'/f'{old}.timer').unlink(missing_ok=True)
    if os.environ['RETIRE_PROOF_MODE']=='reactivate':
        status='active'
        state.write_text(status)
if 'is-active' in args:
    print(status if is_old else 'inactive')
    sys.exit(0 if is_old and status=='active' else 3)
if 'is-enabled' in args:
    print('disabled')
    sys.exit(1)
if 'show' in args:
    values={'LoadState':'loaded','ActiveState':status if is_old else 'inactive','SubState':'running' if status=='active' else 'dead'}
    keys=[]
    for i,arg in enumerate(args):
        if arg in ('-p','--property') and i+1<len(args):
            keys.extend(args[i+1].split(','))
        elif arg.startswith('--property=') or arg.startswith('-p='):
            keys.extend(arg.split('=',1)[1].split(','))
    for key in keys or values:
        if key in values:
            print(values[key] if '--value' in args else key+'='+values[key])
""")
        self.env['RETIRE_PROOF_MODE'] = mode

    def check_refuses_deletion(self, script, mode):
        self.legacy()
        self.stateful_manager(mode)
        files = [self.prefix/'bin'/base.OLD, self.units/f'{base.OLD}.service', self.units/f'{base.OLD}.timer']
        before = {f: f.read_bytes() for f in files}
        result = subprocess.run([str(base.ROOT/script), '--prefix', str(self.prefix)], env=self.env, capture_output=True, text=True, timeout=180)
        self.assertNotEqual(result.returncode, 0, 'unproved final inactive state was accepted')
        for f, contents in before.items():
            self.assertTrue(f.exists(), f'owned artifact deleted without final inactive proof: {f.name}')
            self.assertEqual(f.read_bytes(), contents, f'owned artifact replaced without proof: {f.name}')
        self.preserved()

    def test_INV_CANONRET_02_install_failed_state_is_not_inactive(self):
        self.check_refuses_deletion('install.sh', 'failed')

    def test_INV_CANONRET_03_uninstall_failed_state_is_not_inactive(self):
        self.check_refuses_deletion('uninstall.sh', 'failed')

    def test_INV_CANONRET_02_install_disable_reactivation_refuses_deletion(self):
        self.check_refuses_deletion('install.sh', 'reactivate')

    def test_INV_CANONRET_03_uninstall_disable_reactivation_refuses_deletion(self):
        self.check_refuses_deletion('uninstall.sh', 'reactivate')

    def test_INV_CANONRET_04_pending_help_is_manual_read_only(self):
        result = subprocess.run([str(base.ROOT/'bin/claude-agent-harvest'), '--help'], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0)
        text = result.stdout + result.stderr
        pending_lines = [line for line in text.splitlines() if 'pending' in line.lower()]
        self.assertTrue(pending_lines, 'pending command disappeared from help')
        self.assertFalse(any('maintainer' in line.lower() for line in pending_lines), 'pending help still directs callers to retired maintainer')
        self.assertTrue(any(any(term in line.lower() for term in ('manual', 'read-only', 'read only', 'ручн', 'только чтение')) for line in pending_lines), 'pending help lacks manual/read-only contract')


if __name__ == '__main__':
    unittest.main(verbosity=2)
