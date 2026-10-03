#!/usr/bin/env python3
"""Independent systemd manager-versus-disk acceptance scenarios."""
import subprocess
import unittest

import test_retire_canon_version_rollout as base


class RetirementManager(unittest.TestCase):
    setUp = base.Retirement.setUp
    tearDown = base.Retirement.tearDown
    runcli = base.Retirement.runcli
    legacy = base.Retirement.legacy
    absent = base.Retirement.absent
    preserved = base.Retirement.preserved

    def binary_only(self):
        binary = self.prefix/'bin'/base.OLD
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text('#!/bin/sh\nexit 99\n')
        binary.chmod(0o755)

    def test_INV_CANONRET_02_binary_only_with_missing_peer_units(self):
        self.binary_only()
        for _ in range(2):
            self.runcli('install.sh', '--prefix', str(self.prefix))
            self.absent()
            self.preserved()

    def test_INV_CANONRET_02_manager_loaded_active_without_disk_units(self):
        self.env.update(RETIRE_MANAGER_LOADED='1', RETIRE_MANAGER_ACTIVE='1')
        self.runcli('install.sh', '--prefix', str(self.prefix))
        self.absent()
        calls = self.preserved()
        self.assertTrue(any('stop' in c and any(base.OLD in a for a in c) for c in calls), 'manager-loaded old operator was not stopped')
        self.assertTrue(self.calls.with_name(self.calls.name+'.state').exists(), 'manager state remains active')

    def test_INV_CANONRET_02_show_query_failure_is_fail_closed(self):
        self.legacy()
        binary = self.prefix/'bin'/base.OLD
        service = self.units/f'{base.OLD}.service'
        before_binary, before_service = binary.read_bytes(), service.read_bytes()
        result = subprocess.run([str(base.ROOT/'install.sh'), '--prefix', str(self.prefix)], env=dict(self.env, RETIRE_SHOW_FAILURE='1'), capture_output=True, text=True, timeout=180)
        self.assertNotEqual(result.returncode, 0, 'failed state query was accepted as inactivity')
        self.assertEqual(binary.read_bytes(), before_binary, 'unproven operator deleted or replaced')
        self.assertEqual(service.read_bytes(), before_service, 'unproven service deleted or replaced')
        self.preserved()


if __name__ == '__main__':
    unittest.main(verbosity=2)
