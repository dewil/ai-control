"""Source-blind INV-INST-DRY contract: synthetic installer profiles only.

Oracle: docs/dev/2026-10-06-spec-install-dry-run-template.md at c2d13a2.
Installer/uninstaller/runtime source was not read. Service/provider stubs are
inert; their logs are outside the HOME/prefix trees whose inventories matter.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/task-codex-template.yaml.example"


def inventory(root):
    """Full tree oracle: no symlink traversal, including root's mode/type."""
    rows = {}
    def visit(path, rel):
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            rows[rel] = ("symlink", mode, os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            rows[rel] = ("directory", mode)
            for child in sorted(path.iterdir()):
                visit(child, str(Path(rel) / child.name))
        elif stat.S_ISREG(info.st_mode):
            rows[rel] = ("file", mode, path.read_bytes())
        else:
            rows[rel] = ("other", mode, info.st_mode)
    if os.path.lexists(root):
        visit(root, ".")
    return rows


class InstallDryRun(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="install-dry-contract-", dir="/var/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.stub = self.base / "stub"
        self.stub.mkdir()
        self.log = self.base / "stub-calls.jsonl"
        stub_script = '''#!/usr/bin/python3
import json, os, sys
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ['INSTALL_FIXTURE_CALLS'], 'a') as stream:
    stream.write(json.dumps([name, *args]) + '\\n')
if name in ('curl', 'wget', 'ssh', 'scp', 'codex'):
    print('fixture blocks network/native provider execution', file=sys.stderr)
    sys.exit(97)
if name == 'claude':
    if args == ['--version']:
        print('2.0.0 (synthetic Claude CLI)')
        sys.exit(0)
    print('fixture blocks provider execution', file=sys.stderr)
    sys.exit(97)
if name == 'yq':
    if '--version' in args or '-V' in args:
        print('yq (https://github.com/mikefarah/yq/) version v4.44.1')
    else:
        print('{}')
    sys.exit(0)
if name == 'systemctl':
    if 'show' in args:
        fields = {'ActiveState':'inactive', 'SubState':'dead', 'LoadState':'not-found'}
        requested = []
        for i, arg in enumerate(args):
            if arg in ('-p', '--property') and i + 1 < len(args):
                requested.extend(args[i + 1].split(','))
            elif arg.startswith('--property=') or arg.startswith('-p='):
                requested.extend(arg.split('=', 1)[1].split(','))
        for key in requested or fields:
            if key in fields:
                print(fields[key] if '--value' in args else key+'='+fields[key])
    if 'is-active' in args:
        print('inactive')
        sys.exit(3)
    if 'is-enabled' in args:
        print('disabled')
        sys.exit(1)
    sys.exit(0)
if name in ('launchctl', 'systemd-analyze'):
    sys.exit(0)
sys.exit(98)
'''
        for name in ("claude", "yq", "systemctl", "launchctl", "systemd-analyze", "codex", "curl", "wget", "ssh", "scp"):
            path = self.stub / name
            path.write_text(stub_script)
            path.chmod(0o755)
        self.assertTrue(EXAMPLE.is_file(), "Fixture prerequisite: shipped Codex example is missing")
        self.assertTrue((ROOT / "install.sh").is_file(), "Fixture prerequisite: installer is missing")

    def profile(self, os_name, label, runtime_exists=False):
        base = self.base / (os_name + "-" + label)
        home, prefix = base / "home", base / "prefix"
        home.mkdir(parents=True)
        prefix.mkdir()
        (home / "unrelated").mkdir(mode=0o750)
        (home / "unrelated/keep").write_bytes(b"synthetic canary\x00\n")
        (home / "unrelated/keep").chmod(0o640)
        (home / "unrelated/dangling").symlink_to("absent-canary-target")
        (prefix / "keep").write_bytes(b"prefix canary\n")
        if runtime_exists:
            (home / ".ai-control").mkdir(mode=0o700)
        env = {"HOME": str(home), "USER": "synthetic_operator", "LOGNAME": "synthetic_operator", "SHELL": "/bin/bash", "PATH": str(self.stub) + ":/usr/bin:/bin",
               "AI_CONTROL_OS": os_name, "INSTALL_FIXTURE_CALLS": str(self.log),
               "TMPDIR": str(self.base), "XDG_CONFIG_HOME": str(home / ".config"),
               "XDG_DATA_HOME": str(home / ".local/share"),
               "XDG_CACHE_HOME": str(home / ".cache"),
               "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        return home, prefix, env

    def run_install(self, prefix, env, dry=False):
        args = ["/bin/bash", str(ROOT / "install.sh"), "--prefix", str(prefix)]
        if dry:
            args.append("--dry-run")
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=45)
        output = result.stdout + result.stderr
        if "fixture blocks" in output or "command not found" in output or "unbound variable" in output:
            self.fail("Fixture prerequisite failure, not semantic RED:\n" + output[-2500:])
        self.assertEqual(result.returncode, 0,
                         "Synthetic installer must exit0; verify prerequisite diagnostics before classifying RED:\n" + output[-3000:])
        return output

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def assert_no_service_mutation(self):
        mutations = {"start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask",
                     "daemon-reload", "try-restart", "reload-or-restart", "try-reload-or-restart", "reset-failed", "set-environment", "unset-environment",
                     "bootstrap", "bootout", "load", "unload", "kickstart", "remove", "submit",
                     "setenv", "unsetenv", "kill", "freeze", "thaw", "revert"}
        for call in self.calls():
            if call[0] in ("systemctl", "launchctl"):
                self.assertFalse(mutations.intersection(call[1:]), "Dry-run executed service mutation: " + repr(call))
            if call[0] == "claude":
                self.assertEqual(call[1:], ["--version"], "Fixture must not invoke provider")
            self.assertNotIn(call[0], ("codex", "curl", "wget", "ssh", "scp"), "Forbidden native/network invocation")

    def check_dry(self, os_name, runtime_exists):
        home, prefix, env = self.profile(os_name, "dry", runtime_exists)
        before = (inventory(home), inventory(prefix))
        output = self.run_install(prefix, env, dry=True)
        self.assert_no_service_mutation()
        with self.subTest(oracle="filesystem"):
            self.assertEqual((inventory(home), inventory(prefix)), before,
                             "Dry-run changed synthetic HOME or prefix filesystem inventory")
        with self.subTest(oracle="intended_action"):
            self.assertTrue("task-codex-template.yaml" in output,
                            "Absent Codex template creation must be reported as an intended action")

    def test_directory_only_dry_run_linux(self):
        # INV-INST-DRY-01 INV-INST-DRY-03
        self.check_dry("Linux", True)

    def test_directory_only_dry_run_darwin(self):
        # INV-INST-DRY-01 INV-INST-DRY-03
        self.check_dry("Darwin", True)

    def test_absent_runtime_dry_run_linux(self):
        # INV-INST-DRY-02 INV-INST-DRY-03
        self.check_dry("Linux", False)

    def test_absent_runtime_dry_run_darwin(self):
        # INV-INST-DRY-02 INV-INST-DRY-03
        self.check_dry("Darwin", False)

    def test_real_synthetic_install_seeds_exact_example_0600_and_repeat_preserves(self):
        # INV-INST-DRY-03
        for os_name in ("Linux", "Darwin"):
            with self.subTest(os=os_name):
                home, prefix, env = self.profile(os_name, "seed")
                target = home / ".ai-control/task-codex-template.yaml"
                self.run_install(prefix, env)
                self.assertTrue(target.is_file(), "Normal install must seed absent Codex template")
                self.assertEqual(target.read_bytes(), EXAMPLE.read_bytes())
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                target.write_bytes(b"synthetic operator edit\n")
                target.chmod(0o640)
                before = inventory(home / ".ai-control")
                self.run_install(prefix, env)
                self.assertEqual(inventory(home / ".ai-control"), before,
                                 "Repeat install changed operator's existing Codex template")

    def test_custom_existing_template_preserved(self):
        # INV-INST-DRY-03
        for os_name in ("Linux", "Darwin"):
            with self.subTest(os=os_name):
                home, prefix, env = self.profile(os_name, "custom", True)
                target = home / ".ai-control/task-codex-template.yaml"
                target.write_bytes(b"schema: 1\nsynthetic_operator: custom\n")
                target.chmod(0o640)
                before = inventory(target)
                self.run_install(prefix, env, dry=True)
                self.assertEqual(inventory(target), before)
                self.run_install(prefix, env)
                self.assertEqual(inventory(target), before)

    def test_existing_and_dangling_template_symlinks_preserved(self):
        # INV-INST-DRY-03
        for os_name in ("Linux", "Darwin"):
            for dangling in (False, True):
                with self.subTest(os=os_name, dangling=dangling):
                    home, prefix, env = self.profile(os_name, "link-" + str(dangling), True)
                    target = home / ".ai-control/task-codex-template.yaml"
                    destination = home / "operator-template.yaml"
                    if not dangling:
                        destination.write_bytes(b"synthetic operator-owned target\n")
                        destination.chmod(0o640)
                    target.symlink_to("../operator-template.yaml")
                    before = (inventory(target), inventory(destination))
                    self.run_install(prefix, env, dry=True)
                    self.assertEqual((inventory(target), inventory(destination)), before)
                    self.run_install(prefix, env)
                    self.assertEqual((inventory(target), inventory(destination)), before,
                                     "Install replaced a Codex template symlink or changed its destination")


if __name__ == "__main__":
    unittest.main()
