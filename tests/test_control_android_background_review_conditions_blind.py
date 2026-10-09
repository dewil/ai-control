"""Narrow independent delta for DESIGN conditions in spec commit75f1f56.

Reuses frozen host compilation and doubles; does not change their tests or read
implementation. Public Activity/WebView callbacks provide all stimuli.
"""
import subprocess
import unittest
import test_control_android_background_host_blind as frozen


class AndroidBackgroundReviewConditionsBlind(unittest.TestCase):
    setUpClass=classmethod(frozen.AndroidBackgroundHostBlind.setUpClass.__func__)

    def scenario(self,name):
        result=subprocess.run([self.java,'-cp',self.cp,'ru.dewil.aicontrol.ReviewConditionsProbe',name],
            capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_unconfirmed_return_never_reprobes_or_readmits(self):
        self.scenario('unconfirmed-return')

    def test_monotonic_deadline_is_not_reset_or_bypassed_by_late_ACK(self):
        for scenario in ['invalid-at400','late-ack-before-timer']:
            with self.subTest(scenario=scenario):self.scenario(scenario)

    def test_navigation_renderer_change_fences_old_suspend_ACK(self):
        for scenario in ['navigation-old-ack','renderer-old-ack']:
            with self.subTest(scenario=scenario):self.scenario(scenario)
