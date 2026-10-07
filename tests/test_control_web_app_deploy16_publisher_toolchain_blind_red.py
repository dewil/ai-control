"""Independent fixed-JDK verifier environment; harmless executable fixtures only."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]/'deployment/publish-android-release.py'
JDK = '/home/dwl/android-tools/jdk-17.0.20.1+1'
FIXED_PATH = JDK+'/bin:/usr/bin:/bin'


class PublisherToolchain(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'Public publisher artifact absent')
        spec = importlib.util.spec_from_file_location('blind_fixed_jdk_publisher', SOURCE)
        self.api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.api
        spec.loader.exec_module(self.api)
        self.assertTrue(callable(getattr(self.api,'run_command',None)))
        previous = os.umask(0o077)
        self.addCleanup(os.umask,previous)
        temporary = tempfile.TemporaryDirectory(prefix='publisher-java-blind-',dir='/var/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.jdk = self.root/'jdk';self.jdk.mkdir(mode=0o700)
        self.bin = self.jdk/'bin';self.bin.mkdir(mode=0o700)
        self.system = self.root/'system';self.system.mkdir(mode=0o700)
        self.java = self.bin/'java'
        self.java.write_text('#!/bin/sh\nprintf "synthetic verified java\\n"\n')
        self.java.chmod(0o700)
        self.verifier = self.root/'harmless-apksigner'
        # Mirrors the public SDK launcher property: resolves bare java, ignores JAVA_HOME.
        self.verifier.write_text('#!/bin/sh\nexec java\n')
        self.verifier.chmod(0o700)

    def test_literal_jdk_first_path_and_java_home_never_inherit_caller_env(self):
        captured = []
        def observe(argv,**kwargs):
            captured.append((argv,kwargs))
            return subprocess.CompletedProcess(argv,0,stdout='',stderr='')
        poison = dict(PATH='/unapproved',JAVA_HOME='/unapproved-jdk',JAVA_TOOL_OPTIONS='unapproved',
            _JAVA_OPTIONS='unapproved',WRITER_INHERITED_SENTINEL='unapproved')
        with patch.dict(os.environ,poison),patch('subprocess.run',side_effect=observe):
            result = self.api.run_command([str(self.verifier)],timeout=40)
        self.assertEqual(result.returncode,0)
        self.assertEqual(len(captured),1)
        argv,kwargs = captured[0]
        self.assertEqual(argv,[str(self.verifier)])
        self.assertEqual(kwargs['env'].get('PATH'),FIXED_PATH)
        self.assertEqual(kwargs['env'].get('JAVA_HOME'),JDK)
        self.assertEqual(kwargs['env'].get('LANG'),'C')
        for name in ('JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','WRITER_INHERITED_SENTINEL'):
            self.assertNotIn(name,kwargs['env'])
        self.assertEqual(kwargs['cwd'],'/')
        self.assertEqual(kwargs['timeout'],40)
        self.assertTrue(kwargs['capture_output']);self.assertTrue(kwargs['text'])
        self.assertFalse(kwargs.get('shell',False))

    def invoke_synthetic_verifier(self):
        genuine = subprocess.run
        def mapped_paths(argv,**kwargs):
            # TEST-ONLY mapping of fixed process environment. Production module and
            # shell script receive no path knobs. Empty synthetic system dir ensures
            # this proof is independent of whether the host has /usr/bin/java.
            environment = dict(kwargs['env'])
            mapping = {JDK+'/bin':str(self.bin),'/usr/bin':str(self.system),'/bin':str(self.system)}
            environment['PATH'] = ':'.join(mapping.get(entry,entry) for entry in environment['PATH'].split(':'))
            if environment.get('JAVA_HOME') == JDK:
                environment['JAVA_HOME'] = str(self.jdk)
            kwargs['env'] = environment
            return genuine(argv,**kwargs)
        with patch('subprocess.run',side_effect=mapped_paths):
            return self.api.run_command([str(self.verifier)],timeout=40)

    def test_bare_java_verifier_resolves_reviewed_jdk_without_system_java(self):
        result = self.invoke_synthetic_verifier()
        self.assertEqual(result.returncode,0,'Bare-java verifier cannot resolve reviewed JDK in sanitized PATH')
        self.assertEqual(result.stdout.strip(),'synthetic verified java')

    def test_verification_failure_is_preserved_never_converted_to_success(self):
        self.java.write_text('#!/bin/sh\nexit 9\n')
        self.java.chmod(0o700)
        result = self.invoke_synthetic_verifier()
        self.assertNotEqual(result.returncode,0,'Failed verification was converted to success')


if __name__ == '__main__':
    unittest.main()
