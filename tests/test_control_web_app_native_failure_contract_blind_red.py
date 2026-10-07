"""Independent structural native failure contracts; NOT instrumented/E2E proof.

Checks bind the public AuthGate predicate to admission and ensure credential
clear failure cannot skip cookie teardown. Runtime control flow/device behavior
still require independent SOURCE review and actual Android execution.
"""
import os
from pathlib import Path
import re
import unittest

ROOT = Path(os.environ.get('APP_CONTRACT_ROOT', Path(__file__).resolve().parents[1]))


def balanced_block(text, brace):
    depth = 0
    for position in range(brace, len(text)):
        if text[position] == '{':
            depth += 1
        elif text[position] == '}':
            depth -= 1
            if depth == 0:
                return text[brace + 1:position], position
    raise AssertionError('structural fixture could not locate a complete Java block')


class NativeFailureContract(unittest.TestCase):
    # INV-APP-03 INV-APP-04 INV-APP-06
    def method(self, name):
        path = ROOT / 'android/app/src/main/java/ru/dewil/aicontrol/MainActivity.java'
        self.assertTrue(path.is_file(), 'MainActivity public contract source absent')
        source = path.read_text()
        declaration = re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
        self.assertIsNotNone(declaration, 'declared lifecycle method absent: ' + name)
        return balanced_block(source, declaration.end() - 1)[0]

    def test_admission_binds_gate_before_loading_or_network_queue(self):
        body = self.method('admit')
        effects = list(re.finditer(r'\bloading\s*=\s*true\b|\bio\.execute\s*\(', body))
        self.assertTrue(effects, 'admission structural seam has no loading/network boundary')
        prefix = body[:effects[0].start()]
        self.assertTrue(re.search(r'\b\w+\.canApply\s*\(\s*authGeneration\s*\)', prefix),
            'admit must bind the sticky AuthGate predicate before loading or IO enqueue')
        # Presence/order is structural evidence only: a predicate call alone does
        # not prove that every Java branch obeys it; SOURCE review remains required.

    def test_terminal_clear_failure_does_not_return_before_cookie_teardown(self):
        body = self.method('terminal')
        cleanup = re.search(r'\bremoveAllCookies\s*\(', body)
        self.assertIsNotNone(cleanup, 'terminal denial requires explicit native cookie teardown')
        clear = re.search(r'\bstore\.clear\s*\(', body)
        self.assertIsNotNone(clear, 'terminal denial requires credential clearing')
        self.assertLess(clear.start(), cleanup.start())
        catches = list(re.finditer(r'\bcatch\s*\([^)]*\)\s*\{', body[:cleanup.start()]))
        self.assertTrue(catches, 'credential clear failure must have an explicit handled branch')
        for catch in catches:
            block, _ = balanced_block(body, catch.end() - 1)
            self.assertFalse(re.search(r'\breturn\s*;', block),
                'credential-clear catch must not return before terminal cookie teardown')


if __name__ == '__main__':
    unittest.main()
