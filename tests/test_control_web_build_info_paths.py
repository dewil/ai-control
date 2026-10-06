"""Blind INV-WBUILD-04 local target ownership fault tests (spec48941db).

Copied utility bytes only; synthetic Git/HTML inside private own fixture.
No source body inspection, native/auth/network/server/deployment operations.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UTILITY = ROOT / 'deployment/build-web-info.py'
HTML = b'<!doctype html>\n<main>owned fixture sentinel</main>\n<!-- BUILD-INFO:START -->\nunknown\n<!-- BUILD-INFO:END -->\n'


class BuildInfoPaths(unittest.TestCase):
    def setUp(self):
        self.assertTrue(UTILITY.is_file(), 'public build-web-info utility must exist before path fault checks')
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='build-info-paths-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.checkout = self.root / 'checkout'
        (self.checkout / 'deployment').mkdir(parents=True, mode=0o700)
        self.script = self.checkout / 'deployment/build-web-info.py'
        shutil.copyfile(UTILITY, self.script)  # Opaque implementation, never read.
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update(HOME=str(self.root / 'home'), GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
        (self.root / 'home').mkdir(mode=0o700)
        self.git('init')
        self.git('config', 'user.name', 'Owned Path Fixture')
        self.git('config', 'user.email', 'paths@example.invalid')
        self.git('add', 'deployment/build-web-info.py')
        self.git('commit', '-m', 'synthetic owned utility checkout')
        self.git('checkout', '-b', 'fixture/build-paths')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.checkout, env=self.env,
            text=True, capture_output=True, check=True)

    def stamp(self):
        return subprocess.run([sys.executable, str(self.script), '--release-id', '3'],
            cwd=self.checkout, env=self.env, text=True, capture_output=True, timeout=5)

    def test_symlink_html_leaf_refuses_and_preserves_external_bytes_and_link(self):
        outside = self.root / 'outside-owned.html'
        outside.write_bytes(HTML)
        (self.checkout / 'bin').mkdir(mode=0o700)
        target = self.checkout / 'bin/_control_web.html'
        target.symlink_to(outside)
        before_bytes = outside.read_bytes()
        before_link = os.readlink(target)
        before_inode = target.lstat().st_ino
        result = self.stamp()
        self.assertNotEqual(result.returncode, 0, 'symlink leaf must refuse before stamp publication')
        self.assertEqual(outside.read_bytes(), before_bytes, 'outside HTML must remain byte-identical')
        self.assertTrue(target.is_symlink())
        self.assertEqual(os.readlink(target), before_link)
        self.assertEqual(target.lstat().st_ino, before_inode)

    def test_symlink_bin_parent_refuses_and_preserves_external_html_and_parent_link(self):
        outside = self.root / 'outside-owned-bin'
        outside.mkdir(mode=0o700)
        html = outside / '_control_web.html'
        html.write_bytes(HTML)
        parent = self.checkout / 'bin'
        parent.symlink_to(outside, target_is_directory=True)
        before_bytes = html.read_bytes()
        before_link = os.readlink(parent)
        before_inode = parent.lstat().st_ino
        result = self.stamp()
        self.assertNotEqual(result.returncode, 0, 'symlink bin parent must refuse before stamp publication')
        self.assertEqual(html.read_bytes(), before_bytes, 'sibling HTML must remain byte-identical')
        self.assertTrue(parent.is_symlink())
        self.assertEqual(os.readlink(parent), before_link)
        self.assertEqual(parent.lstat().st_ino, before_inode)


if __name__ == '__main__':
    unittest.main(verbosity=2)
