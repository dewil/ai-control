"""Isolated installed-file smoke: enrollment never emits credentials."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_control_web_contract import ROOT


class InstallSmoke(unittest.TestCase):
    def test_copied_cli_enrollment_private_and_importable(self):
        with tempfile.TemporaryDirectory(dir='/var/tmp',prefix='web-install-') as directory:
            root=Path(directory);root.chmod(0o700)
            installed=root/'bin';installed.mkdir(mode=0o700)
            for name in ('claude-control-web','_control_web.py','_control_web_broker.py','_control_web.html','_control_web.js','_control_web.css'):
                shutil.copy2(ROOT/'bin'/name,installed/name)
            auth=root/'auth.json';state=root/'totp.json'
            output=io.StringIO()
            args=[str(installed/'claude-control-web'),'init-auth','--origin','http://127.0.0.1:8787','--loopback-development','--output',str(auth),'--totp-state',str(state)]
            with patch.object(sys,'argv',args),patch.object(sys,'path',[str(installed),*sys.path]),patch('getpass.getpass',return_value='synthetic-install-password'),contextlib.redirect_stdout(output):
                namespace=runpy.run_path(str(installed/'claude-control-web'),run_name='installed_smoke')
                namespace['main']()
            config=json.loads(auth.read_text())
            self.assertNotIn(config['totp_secret'],output.getvalue())
            self.assertNotIn('synthetic-install-password',output.getvalue())
            self.assertEqual(auth.stat().st_mode&0o777,0o600)
            self.assertEqual(state.stat().st_mode&0o777,0o600)
            self.assertEqual(json.loads(state.read_text()),{'last_step':-1})
            self.assertFalse(config['secure_cookie'])
            with patch.object(sys,'argv',args),patch('getpass.getpass',return_value='synthetic-install-password'):
                with self.assertRaises(ValueError):
                    namespace['main']()
