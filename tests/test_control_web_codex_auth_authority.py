"""Expose the frozen authority suites to the existing CI unittest discovery."""
import importlib.util
from pathlib import Path
import sys
import unittest


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for filename in (
        "test-control-codex-auth-authority.py",
        "test-control-codex-auth-authority-immutability.py",
        "test-control-codex-auth-authority-single-capture.py",
    ):
        name = "_ci_" + filename.removesuffix(".py").replace("-", "_")
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite
