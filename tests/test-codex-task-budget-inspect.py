#!/usr/bin/env python3
"""Blind actual systemd budget observation contract, no systemd calls."""
import importlib
import inspect
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
host = importlib.import_module('_codex_task_host')
BUDGET = dict(memory_max_mb=1024, tasks_max=64, cpu_quota_percent=100)


class BudgetObservation(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.unit = 'cctask-' + str(uuid.uuid4()) + '.service'
        self.token = str(uuid.uuid4())
        self.base_fields = dict(LoadState='loaded', Description='claude-control task ' + self.token,
            InvocationID='a' * 32, ActiveState='active', SubState='running', MainPID='123',
            ControlGroup='/own-fixture', KillMode='control-group', Type='exec', ExitType='main',
            Restart='no', RemainAfterExit='no', SendSIGKILL='yes')
        self.fields = dict(self.base_fields, MemoryMax='1073741824', TasksMax='64', CPUQuotaPerSecUSec='1s')

    def runner(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        output = ''.join(key + '=' + value + '\n' for key, value in self.fields.items())
        return subprocess.CompletedProcess(argv, 0, output, '')

    def manager(self, budget=None):
        if budget is None:
            return host.SystemdTaskManager(runner=self.runner, clock=lambda: 100.0)
        self.assertIn('host_budget', inspect.signature(host.SystemdTaskManager).parameters,
            'INV-CXRUN-04: TASK manager public host_budget contract is absent')
        return host.SystemdTaskManager(runner=self.runner, clock=lambda: 100.0, host_budget=dict(budget))

    def requests_budgets(self):
        argv, kwargs = self.calls[-1]
        self.assertEqual(argv[:4], ['systemctl', '--user', '--no-ask-password', 'show'])
        self.assertIn(self.unit, argv)
        requested = set()
        for arg in argv:
            requested.update(arg.removeprefix('--property=').removeprefix('-p').split(','))
        self.assertTrue({'MemoryMax', 'TasksMax', 'CPUQuotaPerSecUSec'} <= requested,
            'TASK inspect must request actual live cgroup budget properties')
        self.assertGreater(kwargs['timeout'], 0)
        self.assertLessEqual(kwargs['timeout'], 100)
        self.assertFalse(kwargs.get('shell', False))

    def test_exact_actual_live_budget_is_requested_and_accepted(self):
        # INV-CXRUN-04
        status = self.manager(BUDGET).inspect(self.unit, deadline=200)
        self.assertEqual(status['invocation_id'], 'a' * 32)
        self.assertEqual(status['main_pid'], 123)
        self.requests_budgets()

    def test_fractional_cpu_quota_native_duration_is_accepted_exactly(self):
        # Native own-unit observation for CPU150% is 1.500000s.
        self.fields['CPUQuotaPerSecUSec'] = '1.500000s'
        budget = dict(BUDGET, cpu_quota_percent=150)
        status = self.manager(budget).inspect(self.unit, deadline=200)
        self.assertEqual(status['main_pid'], 123)
        self.requests_budgets()

    def test_missing_budget_property_refuses_admission(self):
        # INV-CXRUN-04
        manager = self.manager(BUDGET)
        for field in ('MemoryMax', 'TasksMax', 'CPUQuotaPerSecUSec'):
            with self.subTest(field=field):
                self.fields = dict(self.base_fields, MemoryMax='1073741824', TasksMax='64', CPUQuotaPerSecUSec='1s')
                self.fields.pop(field)
                with self.assertRaises(host.HostError):
                    manager.inspect(self.unit, deadline=200)
                self.requests_budgets()

    def test_malformed_or_unlimited_observed_budgets_refuse_admission(self):
        # INV-CXRUN-04
        manager = self.manager(BUDGET)
        invalid = dict(MemoryMax=('', 'true', 'infinity', '-1', '1024M', '1073741824.0'),
            TasksMax=('', 'true', 'infinity', '-1', '64.0'),
            CPUQuotaPerSecUSec=('', 'true', 'infinity', '-1s', '100%', '1fortnight', '1.0seconds'))
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.fields = dict(self.base_fields, MemoryMax='1073741824', TasksMax='64', CPUQuotaPerSecUSec='1s')
                    self.fields[field] = value
                    with self.assertRaises(host.HostError):
                        manager.inspect(self.unit, deadline=200)

    def test_changed_live_budget_after_prior_success_cannot_use_cached_admission(self):
        # INV-CXRUN-04
        manager = self.manager(BUDGET)
        manager.inspect(self.unit, deadline=200)
        for field, value in (('MemoryMax', '2147483648'), ('TasksMax', '128'), ('CPUQuotaPerSecUSec', '2s')):
            with self.subTest(field=field):
                self.fields = dict(self.base_fields, MemoryMax='1073741824', TasksMax='64', CPUQuotaPerSecUSec='1s')
                self.fields[field] = value
                with self.assertRaises(host.HostError):
                    manager.inspect(self.unit, deadline=200)

    def test_cpu_microsecond_mismatch_cannot_round_to_expected_quota(self):
        # INV-CXRUN-04
        manager = self.manager(BUDGET)
        for value in ('0.999999s', '1.000001s'):
            with self.subTest(value=value):
                self.fields['CPUQuotaPerSecUSec'] = value
                with self.assertRaises(host.HostError):
                    manager.inspect(self.unit, deadline=200)

    def test_default_non_task_manager_retains_existing_show_contract(self):
        # Default None outside TASK requires no new budget observations.
        self.fields = dict(self.base_fields)
        status = self.manager().inspect(self.unit, deadline=200)
        self.assertEqual(status['main_pid'], 123)
        argv, _ = self.calls[-1]
        self.assertFalse(any('MemoryMax' in arg or 'CPUQuotaPerSecUSec' in arg or 'TasksMax' in arg for arg in argv))


if __name__ == '__main__':
    unittest.main()
