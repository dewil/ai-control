"""Native two-phase and callback ownership gaps, separate from frozen RED."""
from pathlib import Path
import subprocess
import unittest
import test_control_android_background_host_blind as fixture


class AndroidBackgroundAuthor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.AndroidBackgroundHostBlind.setUpClass.__func__(cls)
        sources=list((Path(__file__).parent/'android_background_author').glob('*.java'))
        result=subprocess.run(['/home/dwl/android-tools/jdk-17.0.20.1+1/bin/javac','-d',cls.temp.name,
                               '-cp',cls.cp,*map(str,sources)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)

    def scenario(self,name):
        result=subprocess.run([self.java,'-cp',self.cp,'ru.dewil.aicontrol.AuthorLifecycleProbe',name],
                              capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_old_WebView_navigation_cannot_cancel_replacement_admission(self):self.scenario('old-client-navigation')
    def test_failed_bootstrap_finish_remains_retryable_initial_load(self):self.scenario('bootstrap-error')
    def test_blocked_navigation_finish_is_not_a_ready_shell(self):self.scenario('blocked-navigation-finish')
    def test_unsupported_cancel_ACK_keeps_manual_restart_UI(self):self.scenario('unsupported-cancel-ack')
    def test_renderer_death_releases_old_protocol_latch(self):self.scenario('renderer-clears-latch')
    def test_offline_return_does_not_eval_already_paused_page(self):self.scenario('offline-paused')
    def test_page_admission_false_exposes_only_explicit_native_retry(self):self.scenario('page-401-explicit-retry')
    def test_canceled_bootstrap_finish_does_not_skip_fresh_initial_load(self):self.scenario('bootstrap-stop-finish')
    def test_native_ACTIVE_precedes_current_page_activate(self):self.scenario('two-phase')
    def test_admit_timeout_cancels_before_pause_and_fences_late_callback(self):self.scenario('admit-timeout')
    def test_activate_timeout_has_independent_cancellation_deadline(self):self.scenario('activate-timeout')
    def test_navigation_fences_pending_admission(self):self.scenario('navigation-admit')
    def test_navigation_preserves_original_suspend_deadline(self):self.scenario('navigation-suspend-deadline')
    def test_cookie_callback_after_background_cannot_resume(self):self.scenario('cookie-background')
    def test_cookie_callback_after_navigation_cannot_resume(self):self.scenario('cookie-navigation')
