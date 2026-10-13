"""INV-WATT-09 supplemental ordering regressions, independent RED unchanged."""
from pathlib import Path
import subprocess
import unittest
import test_control_android_attachment_chooser_host_blind as fixture

class AndroidAttachmentChooserAuthor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.AndroidAttachmentChooserHostBlind.setUpClass.__func__(cls)
        source=Path(__file__).parent/'android_attachments_author/AttachmentChooserAuthorProbe.java'
        result=subprocess.run(['/home/dwl/android-tools/jdk-17.0.20.1+1/bin/javac','-d',cls.temp.name,'-cp',cls.cp,str(source)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)

    def scenario(self,name):
        result=subprocess.run([self.java,'-cp',self.cp,'ru.dewil.aicontrol.AttachmentChooserAuthorProbe',name],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_result_before_resume_waits_for_successful_admission(self):self.scenario('before-resume')
    def test_replaced_picker_late_result_cannot_satisfy_successor(self):self.scenario('replace-late')
    def test_cancellation_releases_callback_while_backgrounded(self):self.scenario('cancel-background')
    def test_mixed_content_and_foreign_uri_rejects_whole_selection(self):self.scenario('mixed-uri')

    def test_provider_huge_count_rejected_before_allocation_or_iteration(self):self.scenario('huge-count')
    def test_nine_files_rejected_as_whole_selection(self):self.scenario('nine-files')
    def test_eight_files_accepted(self):self.scenario('eight-files')
