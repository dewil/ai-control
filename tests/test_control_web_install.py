"""Isolated installed-file smoke: enrollment never emits credentials."""
import contextlib
import importlib
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


@contextlib.contextmanager
def installed_web_import():
    missing=object()
    previous=sys.modules.pop('_control_web',missing)
    try:
        yield
    finally:
        sys.modules.pop('_control_web',None)
        if previous is not missing:
            sys.modules['_control_web']=previous


class InstallSmoke(unittest.TestCase):
    def test_copied_cli_enrollment_private_and_importable(self):
        with installed_web_import(),tempfile.TemporaryDirectory(dir='/var/tmp',prefix='web-install-') as directory:
            root=Path(directory);root.chmod(0o700)
            installed=root/'bin';installed.mkdir(mode=0o700)
            for name in ('ai-control-web','_control_web.py','_control_web_broker.py','_control_web.html','_control_web.js','_control_web.css'):
                shutil.copy2(ROOT/'bin'/name,installed/name)
            auth=root/'auth.json';state=root/'totp.json'
            output=io.StringIO()
            args=[str(installed/'ai-control-web'),'init-auth','--origin','http://127.0.0.1:8787','--loopback-development','--output',str(auth),'--totp-state',str(state)]
            with patch.object(sys,'argv',args),patch.object(sys,'path',[str(installed),*sys.path]),patch('getpass.getpass',return_value='synthetic-install-password'),contextlib.redirect_stdout(output):
                namespace=runpy.run_path(str(installed/'ai-control-web'),run_name='installed_smoke')
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


class InstallSmokeIsolation(unittest.TestCase):
    def setUp(self):
        self.missing=object()
        self.previous=sys.modules.pop('_control_web',self.missing)
        self.addCleanup(self.restore_module)

    def restore_module(self):
        sys.modules.pop('_control_web',None)
        if self.previous is not self.missing:
            sys.modules['_control_web']=self.previous

    def run_smoke(self):
        InstallSmoke('test_copied_cli_enrollment_private_and_importable').test_copied_cli_enrollment_private_and_importable()

    def test_absent_cache_stays_absent_and_next_import_uses_repository(self):
        self.run_smoke()
        self.assertFalse('_control_web' in sys.modules,'Installed module leaked into the import cache')
        with patch.object(sys,'path',[str(ROOT/'bin'),*sys.path]):
            module=importlib.import_module('_control_web')
        self.assertEqual(Path(module.__file__).resolve(),ROOT/'bin/_control_web.py')

    def test_existing_binding_restored_after_both_cli_calls(self):
        previous=object();sys.modules['_control_web']=previous
        self.run_smoke()
        self.assertIs(sys.modules['_control_web'],previous)

    def test_exception_after_installed_import_restores_exact_prior_state(self):
        original=runpy.run_path
        def failing_cli(*args,**kwargs):
            namespace=original(*args,**kwargs);main=namespace['main']
            def fail():
                main()
                raise RuntimeError('synthetic installed CLI failure')
            namespace['main']=fail
            return namespace
        for previous in (self.missing,None,object()):
            with self.subTest(prior='absent' if previous is self.missing else type(previous).__name__):
                sys.modules.pop('_control_web',None)
                if previous is not self.missing:sys.modules['_control_web']=previous
                with patch.object(runpy,'run_path',side_effect=failing_cli):
                    with self.assertRaisesRegex(RuntimeError,'synthetic installed CLI failure'):
                        self.run_smoke()
                if previous is self.missing:self.assertFalse('_control_web' in sys.modules,'Failed CLI leaked its installed module')
                else:self.assertIs(sys.modules['_control_web'],previous)
