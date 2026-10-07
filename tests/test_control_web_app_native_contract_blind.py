"""Independent structural contract checks, NOT native execution/device proof.

Expected behavior comes from frozen app-auth specs. APP_CONTRACT_ROOT may
point at an authored tree without copying or modifying its runtime files.
These source checks do not establish async/cookie/Keystore behavior.
"""
import os
from pathlib import Path
import re
import unittest

ROOT = Path(os.environ.get('APP_CONTRACT_ROOT', Path(__file__).resolve().parents[1]))
JAVA = ROOT / 'android/app/src/main/java/ru/dewil/aicontrol'


class NativePublicContract(unittest.TestCase):
    # INV-APP-05 INV-APP-06 INV-APP-08
    def source(self, path):
        self.assertTrue(path.is_file(), 'public native contract source absent')
        return path.read_text()

    def test_release_identity_and_sdk_contract(self):
        source = self.source(ROOT / 'android/app/build.gradle.kts')
        for pattern in (r'applicationId\s*=\s*"ru\.dewil\.aicontrol"',
            r'versionName\s*=\s*"0\.1\.2"', r'versionCode\s*=\s*3\b',
            r'minSdk\s*=\s*26\b', r'targetSdk\s*=\s*36\b'):
            self.assertRegex(source, pattern)

    def test_auth_http_uses_exact_common_api_allowlist_and_username_payload(self):
        source = self.source(JAVA / 'AuthHttp.java')
        paths = set(re.findall(r'"(/api/[A-Za-z0-9_/-]+)"', source))
        self.assertEqual(paths, {'/api/app/login', '/api/app/session', '/api/app/logout'})
        self.assertNotIn('/api/android/', source)
        payload_source = source + '\n' + self.source(JAVA / 'MainActivity.java')
        values = re.findall(r'\.put\(\s*"username"\s*,\s*'
            r'([A-Za-z_$][A-Za-z0-9_$]*(?:\.getText\(\)\.toString\(\))?)\s*\)', payload_source)
        self.assertTrue(values,
            'login JSON must carry an unmodified username identifier or exact EditText value')
        self.assertNotRegex(source, r'\.put\(\s*"(?:owner|principal|role|platform)"')

    def test_native_username_is_editable_and_sent_without_normalization(self):
        source = self.source(JAVA / 'MainActivity.java')
        declarations = re.findall(r'EditText\s+([A-Za-z_$][A-Za-z0-9_$]*)', source)
        usernames = [name for name in declarations if 'username' in name.lower()]
        self.assertTrue(usernames, 'native form must expose a username EditText')
        for username in usernames:
            self.assertRegex(source, re.escape(username) + r'\.getText\(\)\.toString\(\)')
            self.assertNotRegex(source, re.escape(username) +
                r'\.getText\(\)\.toString\(\)\.(?:trim|strip|toLowerCase|toUpperCase)\(')
            self.assertNotRegex(source, re.escape(username) + r'\.setEnabled\(false\)')
        # Hint and field insertion are observable form contract, not acceptance of device login.
        hints = list(re.finditer(r'([A-Za-z_$][A-Za-z0-9_$]*)\.setHint\("([^"]+)"\)', source))
        name_hints = [h for h in hints if h.group(1) in usernames]
        self.assertTrue(name_hints, 'username needs a visible login hint')
        self.assertTrue(any(h.group(2).lower() in ('login', 'логин', 'username') for h in name_hints))
        password_hints = [h for h in hints if 'password' in h.group(1).lower()]
        self.assertTrue(password_hints)
        self.assertLess(name_hints[0].start(), password_hints[0].start())


if __name__ == '__main__':
    unittest.main()
