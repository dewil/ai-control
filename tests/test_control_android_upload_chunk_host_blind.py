"""INV-WATT-09: real active WebView must let exact chunk PUT reach network.

Uses public callbacks and this checkout's policy.jar; no MainActivity source
inspection, APK build, device, or historical-policy artifact acceptance.
"""
from pathlib import Path
import os
import subprocess
import unittest
import test_control_android_attachment_chooser_host_blind as chooser_host
ROOT=Path(__file__).resolve().parents[1]
class AndroidUploadChunkHostBlind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        policy=ROOT/'android/policy/build/libs/policy.jar'
        if not policy.is_file():raise RuntimeError('Build current policy.jar first; missing artifact is not semantic RED')
        chooser_host.AndroidAttachmentChooserHostBlind.setUpClass.__func__(cls)
        cls.cp=os.pathsep.join(str(policy) if p.endswith('/android/policy/build/libs/policy.jar') else p for p in cls.cp.split(os.pathsep))
    def case(self,name):
        result=subprocess.run([self.java,'-cp',self.cp,'ru.dewil.aicontrol.UploadChunkInterceptorProbe',name],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_active_exact_chunk_put_reaches_network(self):self.case('active')
    def test_background_still_blocks_exact_chunk_put(self):self.case('inactive')
    def test_foreign_other_redirect_fragment_mainframe_put_stay_blocked(self):self.case('boundaries')
