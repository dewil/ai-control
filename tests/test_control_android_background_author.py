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

    def test_native_ACTIVE_precedes_current_page_activate(self):self.scenario('two-phase')
    def test_admit_timeout_cancels_before_pause_and_fences_late_callback(self):self.scenario('admit-timeout')
    def test_activate_timeout_has_independent_cancellation_deadline(self):self.scenario('activate-timeout')
    def test_navigation_fences_pending_admission(self):self.scenario('navigation-admit')
    def test_navigation_preserves_original_suspend_deadline(self):self.scenario('navigation-suspend-deadline')
    def test_cookie_callback_after_background_cannot_resume(self):self.scenario('cookie-background')
    def test_cookie_callback_after_navigation_cannot_resume(self):self.scenario('cookie-navigation')
