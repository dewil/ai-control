"""Blind INV-WBUILD-01..04 tests: pure render and owned local stamp checkout.

No server, auth, provider, current config, remote Git or deployment operations.
Implementation availability is asserted before import/CLI, never import ERROR.
"""
import datetime as dt
from html.parser import HTMLParser
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UTILITY = ROOT / 'deployment/build-web-info.py'
START = '<!-- BUILD-INFO:START -->'
END = '<!-- BUILD-INFO:END -->'
STAMP = dt.datetime(2026, 10, 6, 13, 2, 3, tzinfo=dt.timezone(dt.timedelta(hours=3)))
PREFIX = '<!doctype html>\n<main>owned unrelated interface</main>\n'
SUFFIX = '\n<p>owned unrelated suffix</p>\n'


class HTML(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.feed(value)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
    def handle_data(self, value):
        self.text.append(value)


class BuildInfoContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(UTILITY.is_file(),
            'INV-WBUILD-04: public deployment/build-web-info.py stamp utility is missing')
        spec = importlib.util.spec_from_file_location('blind_build_info_utility', UTILITY)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.assertTrue(callable(getattr(self.module, 'render_build_info', None)),
                        'public pure render_build_info is missing')
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.tmp = tempfile.TemporaryDirectory(prefix='control-build-info-')
        self.addCleanup(self.tmp.cleanup)
        self.checkout = Path(self.tmp.name)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT='0', HOME=str(self.checkout / 'home'))
        (self.checkout / 'home').mkdir(mode=0o700)

    def render(self, release=3, built=STAMP, branch='fixture/feature'):
        return self.module.render_build_info(release, built, branch)

    def parsed(self, value, release=3):
        parsed = HTML(value)
        footers = [attrs for tag, attrs in parsed.tags if tag == 'footer']
        self.assertEqual(len(footers), 1)
        self.assertEqual(footers[0].get('id'), 'build-info')
        self.assertIn('build-info', footers[0].get('class', '').split())
        self.assertEqual(footers[0].get('data-release-id'), str(release))
        times = [attrs for tag, attrs in parsed.tags if tag == 'time']
        self.assertEqual(len(times), 1)
        instant = dt.datetime.fromisoformat(times[0]['datetime'].replace('Z', '+00:00'))
        self.assertIsNotNone(instant.utcoffset())
        self.assertEqual(instant.utcoffset(), dt.timedelta(0))
        return parsed, instant

    def test_pure_render_fixed_release_utc_and_visible_moscow_instant(self):
        value = self.render()
        self.assertEqual(value, self.render(), 'pure fixed artifact identity must not use request clock')
        parsed, instant = self.parsed(value)
        self.assertEqual(instant, STAMP)
        text = ' '.join(parsed.text)
        self.assertIn('ai-control', text)
        self.assertRegex(text, r'\br3\b')
        self.assertIn('2026', text)
        self.assertIn('13:02', text)
        self.assertIn('МСК', text)
        self.assertEqual(value, self.render(built=STAMP.astimezone(dt.timezone.utc)),
                         'the same instant must render stable UTC/MSK in either input zone')

    def test_normal_branches_hidden_feature_and_detached_are_truthful_text(self):
        for branch in ('main', 'origin', 'origin/main'):
            with self.subTest(branch=branch):
                parsed, instant = self.parsed(self.render(branch=branch))
                self.assertNotIn(branch, ''.join(parsed.text))
        for branch in ('feature/owned', 'release/owned', 'detached@abc1234'):
            with self.subTest(branch=branch):
                parsed, instant = self.parsed(self.render(branch=branch))
                self.assertIn(branch, ''.join(parsed.text))

    def test_branch_metacharacters_escape_as_nonexecuting_text(self):
        branch = 'feature/<img src=x onerror="owned">&<script>owned</script>'
        parsed, instant = self.parsed(self.render(branch=branch))
        self.assertIn(branch, ''.join(parsed.text))
        self.assertFalse(any(tag in ('script', 'img', 'iframe') for tag, attrs in parsed.tags))
        self.assertFalse(any(name.lower().startswith('on') for tag, attrs in parsed.tags for name in attrs))

    def test_render_release_is_positive_exact_int(self):
        for invalid in (0, -1, True, False, 1.0, '3', None):
            with self.subTest(invalid=invalid), self.assertRaises(Exception):
                self.render(release=invalid)
        for valid in (1, 3, 1000):
            self.parsed(self.render(release=valid), release=valid)

    def test_render_rejects_naive_timestamp_and_empty_control_branch(self):
        for built in (dt.datetime(2026, 10, 6), None, '2026-10-06T13:02:03+03:00'):
            with self.subTest(built=built), self.assertRaises(Exception):
                self.render(built=built)
        for branch in ('', 'feature/line\nbreak', 'feature/\x00', 'feature/\x7f'):
            with self.subTest(branch=branch), self.assertRaises(Exception):
                self.render(branch=branch)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.checkout, env=self.env,
            check=True, text=True, capture_output=True).stdout.strip()

    def fixture(self, html=None, *, git=True):
        (self.checkout / 'deployment').mkdir()
        self.script = self.checkout / 'deployment/build-web-info.py'
        shutil.copyfile(UTILITY, self.script)  # Opaque utility bytes, no source inspection.
        (self.checkout / 'bin').mkdir()
        self.target = self.checkout / 'bin/_control_web.html'
        self.target.write_text(html if html is not None else PREFIX + START +
                               '\nВерсия сборки неизвестна\n' + END + SUFFIX)
        if git:
            self.git('init')
            self.git('config', 'user.name', 'Owned Build Fixture')
            self.git('config', 'user.email', 'build-fixture@example.invalid')
            self.git('add', 'bin/_control_web.html')
            self.git('commit', '-m', 'owned synthetic interface')
            self.git('checkout', '-b', 'fixture/feature')

    def cli(self, *args):
        return subprocess.run([sys.executable, str(self.script), *args], cwd=self.checkout,
            env=self.env, text=True, capture_output=True, timeout=5)

    def test_cli_exact_block_replacement_captures_real_utc_once_preserves_other_html(self):
        self.fixture()
        before_clock = dt.datetime.now(dt.timezone.utc)
        result = self.cli('--release-id', '3')
        after_clock = dt.datetime.now(dt.timezone.utc)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = self.target.read_text()
        self.assertTrue(value.startswith(PREFIX))
        self.assertTrue(value.endswith(SUFFIX))
        self.assertEqual(value.count(START), 1)
        self.assertEqual(value.count(END), 1)
        self.assertNotIn('Версия сборки неизвестна', value)
        parsed, instant = self.parsed(value)
        self.assertGreaterEqual(instant, before_clock - dt.timedelta(seconds=1))
        self.assertLessEqual(instant, after_clock + dt.timedelta(seconds=1))
        self.assertIn('fixture/feature', ''.join(parsed.text))
        self.assertLess(len(result.stdout), 500)
        self.assertRegex(result.stdout, r'\b3\b|\br3\b')

    def test_cli_default_branch_and_detached_capture_use_own_local_git(self):
        self.fixture()
        args = ('--release-id', '3')
        self.assertEqual(self.cli(*args).returncode, 0)
        parsed, instant = self.parsed(self.target.read_text())
        self.assertIn('fixture/feature', ''.join(parsed.text))
        self.git('checkout', '-b', 'main')
        self.assertEqual(self.cli(*args).returncode, 0)
        parsed, instant = self.parsed(self.target.read_text())
        self.assertNotIn('main', ''.join(parsed.text))
        self.git('checkout', '--detach', 'HEAD')
        revision = self.git('rev-parse', '--short', 'HEAD')
        self.assertEqual(self.cli(*args).returncode, 0)
        parsed, instant = self.parsed(self.target.read_text())
        self.assertIn('detached@' + revision, ''.join(parsed.text))

    def test_cli_invalid_id_and_forbidden_identity_overrides_preserve_source_bytes(self):
        self.fixture()
        before = self.target.read_bytes()
        cases = [('--release-id', value) for value in ('0', '-1', 'not-an-integer')]
        cases += [('--release-id', '3', '--built-at', STAMP.isoformat()),
                  ('--release-id', '3', '--branch', 'main')]
        for args in cases:
            with self.subTest(args=args):
                self.assertNotEqual(self.cli(*args).returncode, 0)
                self.assertEqual(self.target.read_bytes(), before)

    def test_cli_missing_duplicate_or_reversed_markers_preserve_source(self):
        self.fixture()
        cases = [PREFIX + SUFFIX, PREFIX + START + SUFFIX, PREFIX + END + START + SUFFIX,
                 PREFIX + START + END + START + END + SUFFIX,
                 PREFIX + START + START + END + SUFFIX]
        for value in cases:
            with self.subTest(value=value):
                self.target.write_text(value)
                before = self.target.read_bytes()
                self.assertNotEqual(self.cli('--release-id', '3').returncode, 0)
                self.assertEqual(self.target.read_bytes(), before)

    def test_cli_unknown_git_context_refuses_without_fabricating_branch(self):
        self.fixture(git=False)
        before = self.target.read_bytes()
        result = self.cli('--release-id', '3')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target.read_bytes(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
