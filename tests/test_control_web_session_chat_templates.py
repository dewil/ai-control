"""Blind installed-isolation contracts from socket topology specification d7ba1de."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def service_directives(path):
    """Inspect target systemd [Service] values during acceptance, never print bodies."""
    values = {}
    section = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            continue
        if section == 'Service' and '=' in line:
            name, value = line.split('=', 1)
            values.setdefault(name.strip(), []).append(value.strip())
    return values


class NativeSocketTemplateContract(unittest.TestCase):
    def read(self, filename):
        path = ROOT / 'systemd' / filename
        self.assertTrue(path.is_file(), 'Public systemd template must exist')
        return service_directives(path)

    def test_INV_WSESS_07_broker_private_tmp_exact_optional_read_only_native_bind(self):
        service = self.read('ai-control-web-broker.service.tmpl')
        self.assertEqual(service.get('PrivateTmp', [])[-1:], ['yes'])
        self.assertEqual(service.get('BindReadOnlyPaths'), ['-/tmp/codex-daemon-@OWNER_UID@'])
        # The same directory must not be made writable through an additive bind.
        for value in service.get('BindPaths', []):
            self.assertNotIn('codex-daemon-', value)
            self.assertNotIn('app-server-control', value)
            self.assertNotIn('/tmp', [entry.lstrip('-').split(':', 1)[0] for entry in value.split()])

    def test_INV_WSESS_01_frontend_keeps_data_and_home_isolation(self):
        service = self.read('ai-control-web.service.tmpl')
        self.assertEqual(service.get('ProtectHome', [])[-1:], ['yes'])
        inaccessible = [part for value in service.get('InaccessiblePaths', []) for part in value.split()]
        self.assertIn('/data', inaccessible)

    def test_INV_WSESS_01_frontend_never_binds_native_daemon_directory(self):
        service = self.read('ai-control-web.service.tmpl')
        for directive in ('BindPaths', 'BindReadOnlyPaths'):
            for value in service.get(directive, []):
                self.assertNotIn('codex-daemon-', value)
                self.assertNotIn('app-server-control', value)
                self.assertNotIn('/tmp', [entry.lstrip('-').split(':', 1)[0] for entry in value.split()])


if __name__ == '__main__':
    unittest.main()
