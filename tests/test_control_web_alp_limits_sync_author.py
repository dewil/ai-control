"""Real child deadline and no-persistence regressions for ALP delivery."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import cached_limits_backend_blind_support as s
from test_control_web_session_chat_contract import feature


class AlpSyncAuthorTests(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, '_control_web_broker')
        self.temp = tempfile.TemporaryDirectory(dir='/var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.destination = self.base / 'limits' / 'alp.json'

    def test_stalled_child_and_closed_stdout_deadlines_kill_child_and_preserve_cache(self):
        # INV-WLIM-25: EOF does not let a live child bypass its deadline.
        self.destination.parent.mkdir(mode=0o700)
        old = b'previous private synthetic snapshot'
        self.destination.write_bytes(old)
        self.destination.chmod(0o600)
        original = subprocess.Popen
        for program in ('import time; time.sleep(5)',
                        'import os,time; os.close(1); time.sleep(5)'):
            children = []
            def child(_argv, *args, **kwargs):
                process = original([sys.executable, '-c', program], *args, **kwargs)
                children.append(process)
                return process
            def transport(argv, *, timeout, max_bytes):
                return self.module._alp_sync_transport(argv, timeout=.2, max_bytes=max_bytes)
            start = time.monotonic()
            with self.subTest(program=program), patch.object(subprocess, 'Popen', side_effect=child):
                result = self.module.sync_alp_limits(str(self.destination), runner=transport, clock=lambda:s.NOW)
                self.assertEqual(result, {'status':'unavailable', 'reason':'sync_failed'})
                self.assertLess(time.monotonic() - start, 2)
                self.assertEqual(len(children), 1)
                self.assertIsNotNone(children[0].poll())
                self.assertEqual(self.destination.read_bytes(), old)
                self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_invalid_private_protocol_creates_no_cache_directory_or_temporary_file(self):
        # INV-WLIM-25: raw private fields never enter any local persistence.
        value = s.alp()
        value['credentials'] = s.PRIVATE
        result = self.module.sync_alp_limits(str(self.destination),
                    runner=lambda *_args, **_kwargs:json.dumps(value).encode(), clock=lambda:s.NOW)
        self.assertEqual(result, {'status':'unavailable', 'reason':'sync_failed'})
        self.assertFalse(self.destination.parent.exists())
        self.assertEqual(list(self.base.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
