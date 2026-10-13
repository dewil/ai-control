"""INV-WATT-09: blind real MainActivity chooser contract, recording host only.

MainActivity is passed directly to javac; no source inspection. These host tests
prove public callback/Intent/lifecycle behavior, not device chooser/provider UI,
APK update, or retained Android login across installation.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
class AndroidAttachmentChooserHostBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='android-background-host-');cls.addClassCleanup(cls.temp.cleanup)
        directory=Path(cls.temp.name);overrides=HERE/'android_attachments_host';background=HERE/'android_background_host';base=HERE/'android_login_host/stubs'
        dependency=Path(os.environ.get('ANDROID_HOST_DEPENDENCIES_ROOT','/data/git/ai-control-android-ux-package'))
        jsonjar=sorted(Path('/home/dwl/.gradle/caches/modules-2/files-2.1/org.json/json').glob('*/*/*.jar'))[-1]
        runtime=[]
        for artifact in ['org.jetbrains.kotlin/kotlin-stdlib','org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm','org.jetbrains.kotlinx/kotlinx-coroutines-android']:
            runtime.extend(sorted((Path('/home/dwl/.gradle/caches/modules-2/files-2.1')/artifact).glob('*/*/*.jar')))
        cls.cp=os.pathsep.join(map(str,[directory,dependency/'android/policy/build/libs/policy.jar',jsonjar,
            dependency/'android/updater/build/intermediates/built_in_kotlinc/debug/compileDebugKotlin/classes',*runtime,
            '/home/dwl/android-tools/sdk/platforms/android-36/android.jar']))
        cls.java='/home/dwl/android-tools/jdk-17.0.20.1+1/bin/java'
        # Shared historical fixture now supplies the SDK lifecycle signatures.
        component=(overrides/'ComponentActivity.java').read_text()
        (directory/'ComponentActivity.java').write_text(component)
        (directory/'UpdatesActivity.java').write_text('package ru.dewil.aicontrol;public class UpdatesActivity extends androidx.activity.ComponentActivity {}')
        excluded={p.name for p in overrides.glob('*.java')}|{'ComponentActivity.java'}
        sources=[p for p in base.glob('**/*.java') if p.name not in excluded and p.name not in {f.name for f in background.glob('*.java')}]+[p for p in background.glob('*.java') if p.name not in excluded]+[p for p in overrides.glob('*.java') if p.name!='ComponentActivity.java']+list(directory.glob('*.java'))
        sources.append(ROOT/'android/app/src/main/java/ru/dewil/aicontrol/MainActivity.java')
        result=subprocess.run(['/home/dwl/android-tools/jdk-17.0.20.1+1/bin/javac','-d',str(directory),'-cp',cls.cp,*map(str,sources)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError('Host fixture compilation failure (not semantic RED): '+result.stderr)


    def case(self,name):
        result=subprocess.run([self.java,'-cp',self.cp,'ru.dewil.aicontrol.AttachmentChooserProbe',name],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_host_fixture_preserves_existing_background_ack_path(self):
        result=subprocess.run([self.java,'-cp',self.cp,'ru.dewil.aicontrol.BackgroundProbe','ack'],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_single_document_uri_exactly_once(self):self.case('single')
    def test_multiple_document_uris_order_and_intent(self):self.case('multiple')
    def test_cancel_releases_callback_once(self):self.case('cancel')
    def test_provider_exception_releases_callback(self):self.case('provider-error')
    def test_missing_document_provider_releases_callback(self):self.case('provider-unavailable')
    def test_new_picker_releases_previous_callback(self):self.case('replace')
    def test_destroy_releases_callback_and_ignores_late_result(self):self.case('destroy')
    def test_pause_return_retains_pending_callback_page_and_auth_fence(self):self.case('pause-return')
    def test_navigated_login_page_rejects_stale_result(self):self.case('stale-page')
    def test_non_content_provider_uri_is_refused(self):self.case('bad-uri')
    def test_foreign_webview_cannot_launch_picker(self):self.case('foreign-view')
    def test_foreign_origin_cannot_launch_picker(self):self.case('foreign-origin')
    def test_manifest_does_not_add_broad_storage_permissions(self):
        # INV-WATT-09: document-provider read grants replace broad storage access.
        manifest=ET.parse(ROOT/'android/app/src/main/AndroidManifest.xml')
        names={p.get('{http://schemas.android.com/apk/res/android}name') for p in manifest.findall('uses-permission')}
        self.assertFalse(names & {'android.permission.READ_EXTERNAL_STORAGE','android.permission.WRITE_EXTERNAL_STORAGE','android.permission.MANAGE_EXTERNAL_STORAGE','android.permission.READ_MEDIA_IMAGES','android.permission.READ_MEDIA_VIDEO'})
