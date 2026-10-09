"""INV-BATT-01/05/06/07: real MainActivity, recording and controlled native host.

Offline prebuilt dependencies reused, production source passed directly to javac
without source inspection. No device/network/battery acceptance claim.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent

class AndroidBackgroundHostBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='android-background-host-');cls.addClassCleanup(cls.temp.cleanup)
        directory=Path(cls.temp.name);overrides=HERE/'android_background_host';base=HERE/'android_login_host/stubs'
        dependency=Path(os.environ.get('ANDROID_HOST_DEPENDENCIES_ROOT','/data/git/ai-control-android-ux-package'))
        jsonjar=sorted(Path('/home/dwl/.gradle/caches/modules-2/files-2.1/org.json/json').glob('*/*/*.jar'))[-1]
        runtime=[]
        for artifact in ['org.jetbrains.kotlin/kotlin-stdlib','org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm','org.jetbrains.kotlinx/kotlinx-coroutines-android']:
            runtime.extend(sorted((Path('/home/dwl/.gradle/caches/modules-2/files-2.1')/artifact).glob('*/*/*.jar')))
        cls.cp=os.pathsep.join(map(str,[directory,dependency/'android/policy/build/libs/policy.jar',jsonjar,
            dependency/'android/updater/build/intermediates/built_in_kotlinc/debug/compileDebugKotlin/classes',*runtime,
            '/home/dwl/android-tools/sdk/platforms/android-36/android.jar']))
        cls.java='/home/dwl/android-tools/jdk-17.0.20.1+1/bin/java'
        # Fixture superclass previously omitted onPause/onResume entirely.
        component=(base/'androidx/activity/ComponentActivity.java').read_text().replace('public void onStart(){}','public void onStart(){}protected void onResume(){}protected void onPause(){}')
        (directory/'ComponentActivity.java').write_text(component)
        (directory/'UpdatesActivity.java').write_text('package ru.dewil.aicontrol;public class UpdatesActivity extends androidx.activity.ComponentActivity {}')
        excluded={p.name for p in overrides.glob('*.java')}|{'ComponentActivity.java'}
        sources=[p for p in base.glob('**/*.java') if p.name not in excluded]+list(overrides.glob('*.java'))+list(directory.glob('*.java'))
        sources.append(ROOT/'android/app/src/main/java/ru/dewil/aicontrol/MainActivity.java')
        result=subprocess.run(['/home/dwl/android-tools/jdk-17.0.20.1+1/bin/javac','-d',str(directory),'-cp',cls.cp,*map(str,sources)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError('Host fixture compilation failure (not semantic RED): '+result.stderr)

    def case(self,name):
        result=subprocess.run([self.java,'-cp',self.cp,'ru.dewil.aicontrol.BackgroundProbe',name],capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_native_immediate_block_async_suspend(self):self.case('immediate')
    def test_missing_callback_deadline_retains_page_no_retry(self):self.case('timeout')
    def test_onStop_is_idempotent(self):self.case('duplicate')
    def test_destroy_before_global_resume_detached_receiver(self):self.case('destroy')
    def test_return_invalidates_stale_stop_deadline(self):self.case('return')
    def test_native_sets_v2_user_agent_marker(self):self.case('ua')
    def test_unsubmitted_login_focus_selection_retained(self):self.case('login')
    def test_exact_bootstrap_allowlist(self):self.case('bootstrap')
    def test_valid_ACK_cancels_independent_deadline(self):self.case('ack')
    def test_wrong_serial_ACK_is_not_confirmation(self):self.case('wrongack')
    def test_late_ACK_does_not_pause_twice(self):self.case('lateack')
    def test_missing_malformed_v2_protocol_blocks_retains_and_requires_web_update(self):
        for name in ['protocolmissing','protocolstring','protocolother','protocolobject']:
            with self.subTest(protocol=name):self.case(name)
