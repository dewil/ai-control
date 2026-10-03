#!/usr/bin/env python3
"""Independent legacy-state acceptance additions; public installer only."""
import json
import os
from pathlib import Path
import subprocess
import unittest

import test_retire_canon_version_rollout as base


class RetirementEdges(unittest.TestCase):
    setUp = base.Retirement.setUp
    tearDown = base.Retirement.tearDown
    runcli = base.Retirement.runcli
    legacy = base.Retirement.legacy
    absent = base.Retirement.absent
    preserved = base.Retirement.preserved

    def inventory(self):
        result = {}
        for root in (self.home, self.prefix):
            if not root.exists():
                continue
            for p in root.rglob('*'):
                if p.is_symlink():
                    result[str(p)] = ('symlink', os.readlink(p))
                elif p.is_file():
                    result[str(p)] = ('file', p.read_bytes(), p.stat().st_mode)
                elif p.is_dir():
                    result[str(p)] = ('directory', p.stat().st_mode)
        return result

    def legacy_symlink(self, target):
        self.legacy()
        service = self.units/f'{base.OLD}.service'
        service.unlink()
        service.symlink_to(target)

    def cleanup_twice(self, script):
        for _ in range(2):
            self.runcli(script, '--prefix', str(self.prefix))
            self.absent()
            self.preserved()

    def test_INV_CANONRET_02_masked_service_install_repeat(self):
        self.legacy_symlink('/dev/null')
        self.cleanup_twice('install.sh')

    def test_INV_CANONRET_02_dangling_service_install_repeat(self):
        self.legacy_symlink(self.p/'missing-old-template')
        self.cleanup_twice('install.sh')

    def test_INV_CANONRET_03_masked_service_uninstall_repeat(self):
        self.legacy_symlink('/dev/null')
        self.cleanup_twice('uninstall.sh')

    def test_INV_CANONRET_03_dangling_service_uninstall_repeat(self):
        self.legacy_symlink(self.p/'missing-old-template')
        self.cleanup_twice('uninstall.sh')

    def test_INV_CANONRET_02_dry_run_leaves_legacy_inventory_and_units(self):
        self.legacy_symlink('/dev/null')
        def legacy_inventory():
            return {k: v for k, v in self.inventory().items() if base.OLD in Path(k).name or Path(k) in self.canaries}
        before = legacy_inventory()
        self.runcli('install.sh', '--prefix', str(self.prefix), '--dry-run')
        self.assertEqual(legacy_inventory(), before, 'dry-run changed legacy inventory or unrelated canaries')
        calls = self.preserved()
        mutations = {'stop', 'start', 'restart', 'try-restart', 'reload', 'daemon-reload', 'enable', 'disable', 'mask', 'unmask'}
        self.assertFalse(any(mutations.intersection(c) for c in calls), 'dry-run changed user service state')

    def active_after_successful_stop(self, script):
        self.legacy()
        ctl = self.p/'stub/systemctl'
        # This fixture reports stop success yet independent state remains active.
        # Support both public systemctl state interfaces, without constraining args.
        source = ctl.read_text().replace("active=is_old and bool(os.environ.get('RETIRE_FAIL_STOP'))", "active=is_old")
        source += """
if 'show' in args and is_old:
    fields={'ActiveState':'active','SubState':'running','LoadState':'loaded'}
    requested=[]
    for i,arg in enumerate(args):
        if arg in ('-p','--property') and i+1<len(args):
            requested.extend(args[i+1].split(','))
        elif arg.startswith('--property='):
            requested.extend(arg.split('=',1)[1].split(','))
    for key in requested or fields:
        if key in fields:
            print(fields[key] if '--value' in args else key+'='+fields[key])
"""
        ctl.write_text(source)
        before_binary = (self.prefix/'bin'/base.OLD).read_bytes()
        before_service = (self.units/f'{base.OLD}.service').read_bytes()
        result = subprocess.run([str(base.ROOT/script), '--prefix', str(self.prefix)], env=self.env, capture_output=True, text=True, timeout=180)
        self.assertNotEqual(result.returncode, 0, 'stop success was mistaken for proven inactive state')
        self.assertEqual((self.prefix/'bin'/base.OLD).read_bytes(), before_binary, 'active binary deleted or overwritten')
        self.assertEqual((self.units/f'{base.OLD}.service').read_bytes(), before_service, 'active service removed')
        self.preserved()

    def test_INV_CANONRET_02_install_checks_state_after_stop_success(self):
        self.active_after_successful_stop('install.sh')

    def test_INV_CANONRET_03_uninstall_checks_state_after_stop_success(self):
        self.active_after_successful_stop('uninstall.sh')


if __name__ == '__main__':
    unittest.main(verbosity=2)
