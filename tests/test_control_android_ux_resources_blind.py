"""INV-AND-16/18 resource declarations + actual compiled launcher evidence.

No device launcher diagnosis, no assumed vector-icon bug. Compiled APK required.
"""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(os.environ.get('APP_CONTRACT_ROOT',Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('ux_theme_contract',Path(__file__).parent/'android_login_host/theme_contract.py')
resources=importlib.util.module_from_spec(spec);spec.loader.exec_module(resources)

def luminance(value):
    value=value.lstrip('#')[-6:];components=[int(value[i:i+2],16)/255 for i in (0,2,4)]
    return sum(weight*(c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4) for c,weight in zip(components,(.2126,.7152,.0722)))

class AndroidUxResourceContract(unittest.TestCase):
    def test_first_frame_all_owned_activity_themes_are_dark_with_readable_text(self):
        for sdk in (26,27,28,36):
            for activity,theme in resources.themes(ROOT,sdk).items():
                with self.subTest(sdk=sdk,activity=activity):
                    self.assertNotIn('.Light.',theme['platform_parent'],'Native platform widgets must retain dark theme stateful defaults')
                    self.assertEqual(theme['android:windowBackground'].lower(),'#141414')
                    self.assertEqual(theme.get('android:statusBarColor','').lower(),'#141414')
                    self.assertEqual(theme.get('android:navigationBarColor','').lower(),'#141414')
                    self.assertEqual(theme.get('android:windowLightStatusBar'),'false')
                    if sdk>=27:self.assertEqual(theme.get('android:windowLightNavigationBar'),'false')
                    for key in ('android:textColorPrimary','android:textColorSecondary','android:textColorHint'):
                        self.assertGreaterEqual((luminance(theme[key])+.05)/(luminance(theme['android:windowBackground'])+.05),4.5)

    def test_api26_common_resources_qualify_new_bar_attributes(self):
        minimum={'android:windowLightNavigationBar':27,'android:enforceStatusBarContrast':29,'android:enforceNavigationBarContrast':29}
        for directory in (ROOT/'android/app/src/main/res').glob('values*'):
            match=re.search(r'-v(\d+)',directory.name);sdk=int(match.group(1)) if match else 26
            for path in directory.glob('*.xml'):
                for item in ET.parse(path).getroot().iter('item'):
                    key=item.attrib.get('name')
                    if key in minimum:self.assertGreaterEqual(sdk,minimum[key],str(path)+' unqualified newer API attribute')

    def test_actual_compiled_launcher_and_min26_resources_exist_without_cause_claim(self):
        apk=ROOT/'android/app/build/outputs/apk/debug/app-debug.apk'
        self.assertTrue(apk.is_file(),'Compile debug APK before compiled launcher proof')
        sdk=Path(os.environ.get('ANDROID_HOME','/home/dwl/android-tools/sdk'))
        aapt=sdk/'build-tools/36.0.0/aapt2'
        manifest=subprocess.check_output([str(aapt),'dump','xmltree',str(apk),'--file','AndroidManifest.xml'],text=True)
        self.assertIn('android.intent.action.MAIN',manifest)
        self.assertIn('android.intent.category.LAUNCHER',manifest)
        self.assertIn('ru.dewil.aicontrol.MainActivity',manifest)
        self.assertRegex(manifest,r'minSdkVersion[^\n]*=(?:26|0x0000001a)(?:\n|$)')
        icon=subprocess.check_output([str(aapt),'dump','xmltree',str(apk),'--file','res/drawable/ic_launcher.xml'],text=True)
        self.assertIn('E: vector',icon)
        table=subprocess.check_output([str(aapt),'dump','resources',str(apk)],text=True)
        self.assertIn('style/AppTheme',table)
        # Compiled declarations are evidence only; actual Nexus drawer remains NOT RUN.

if __name__=='__main__':unittest.main()
