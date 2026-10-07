"""Public installation file-list contract; no installer or feature source reads."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


# INV-AUTHAND-04 INV-AND-12
class AndroidFeatureDeliveryManifestContract(unittest.TestCase):
    def test_installed_web_receives_both_android_feature_modules(self):
        entries = {line.strip() for line in (ROOT / 'scripts.manifest').read_text().splitlines()
                   if line.strip() and not line.lstrip().startswith('#')}
        for name in ('_control_web_android_auth.py', '_control_web_android_download.py'):
            with self.subTest(module=name):
                self.assertIn(name, entries, 'installed web cannot import missing Android helper')


if __name__ == '__main__':
    unittest.main()
