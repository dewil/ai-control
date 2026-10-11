"""Independent public-contract checks for the full CI shard runner.

The runner is copied into a temporary repository containing only tiny controlled
tests. No production test, provider command, browser or review fixture is run.
"""
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "ci/control_web_contracts.py"
WORKFLOW = ROOT / ".github/workflows/web.yml"
BASELINE_COLLECTOR = r'''
import json, unittest
def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield {"id": item.id(), "module": item.__class__.__module__}
loader = unittest.TestLoader()
found = list(cases(loader.discover("tests", pattern="test_control_web*.py")))
found += list(cases(loader.discover("tests", pattern="test_ai_control_names.py")))
assert not loader.errors, loader.errors
print(json.dumps(found))
'''


class ShardRunnerContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="control-ci-contract-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "ci").mkdir()
        (self.repo / "tests").mkdir()
        # A missing implementation is a real RED failure, never a skip or fake
        # executable that can claim success without running unittest cases.
        self.assertTrue(RUNNER.is_file(), "public runner ci/control_web_contracts.py is missing")
        shutil.copy2(RUNNER, self.repo / "ci/control_web_contracts.py")
        self.write("_fixture_cases.py", '''import os, unittest
ready = False
def setUpModule():
    global ready
    ready = True
def tearDownModule():
    global ready
    ready = False
class BaseMethods:
    def test_inherited_a(self): self.check()
    def test_inherited_b(self): self.check()
class SharedCase(BaseMethods, unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.class_ready = True
    @classmethod
    def tearDownClass(cls): cls.class_ready = False
    def check(self):
        self.assertTrue(ready, "actual defining-module fixture was lost")
        self.assertTrue(self.class_ready, "class fixture was lost")
        if os.environ.get("FAIL_TEST_ID") == self.id(): self.fail("intentional shard failure")
''')
        for module, count in (("alpha", 7), ("beta", 5), ("gamma", 3), ("delta", 2)):
            self.add_module("test_control_web_" + module, count, shared=module in ("alpha", "beta"))
        self.add_module("test_ai_control_names", 1)

    def write(self, name, source):
        (self.repo / "tests" / name).write_text(source, encoding="utf-8")

    def add_module(self, name, count, shared=False):
        source = "import os, unittest\n"
        if shared:
            source += "from _fixture_cases import SharedCase\n"
        if name == "test_control_web_gamma":
            source += "from _fixture_cases import BaseMethods\n"
        bases = "BaseMethods, unittest.TestCase" if name == "test_control_web_gamma" else "unittest.TestCase"
        source += f"class LocalCase({bases}):\n" + '''\
    @classmethod
    def setUpClass(cls): cls.ready = True
    @classmethod
    def tearDownClass(cls): cls.ready = False
    def check(self):
        self.assertTrue(self.ready, "class fixture was lost")
        if os.environ.get("FAIL_TEST_ID") == self.id(): self.fail("intentional shard failure")
'''
        for index in range(count):
            source += f"    def test_{index:02d}(self): self.check()\n"
        self.write(name + ".py", source)

    def call(self, *arguments, env=None):
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("FAIL_TEST_ID", None)
        if env:
            environment.update(env)
        return subprocess.run([sys.executable, "ci/control_web_contracts.py", *arguments],
                              cwd=self.repo, env=environment, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def original_cases(self):
        result = subprocess.run([sys.executable, "-c", BASELINE_COLLECTOR],
                                cwd=self.repo, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def plan(self):
        result = self.call("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_partition(self, plan, original):
        self.assertEqual(set(plan), {"total_test_count", "inventory_hash", "shards"})
        self.assertEqual(plan["total_test_count"], len(original))
        self.assertEqual(plan["inventory_hash"], self.inventory_hash([c["id"] for c in original]))
        shards = plan["shards"]
        self.assertEqual([s["index"] for s in shards], list(range(4)))
        expected = [[] for _ in range(4)]
        modules = defaultdict(list)
        for case in original:
            modules[case["module"]].append(case["id"])
        loads = [0] * 4
        assignment = {}
        for module in sorted(modules, key=lambda m: (-len(modules[m]), m)):
            index = min(range(4), key=lambda n: (loads[n], n))
            assignment[module] = index
            loads[index] += len(modules[module])
        for case in original:
            expected[assignment[case["module"]]].append(case["id"])
        actual_union = Counter()
        actual_modules = []
        for index, shard in enumerate(shards):
            self.assertEqual(set(shard), {"index", "test_count", "test_ids", "modules", "inventory_hash"})
            self.assertEqual(shard["test_ids"], expected[index], "selection/order must follow original discovery")
            self.assertEqual(shard["test_count"], len(expected[index]))
            self.assertEqual(shard["inventory_hash"], self.inventory_hash(expected[index]))
            self.assertEqual(shard["modules"], sorted(m for m, n in assignment.items() if n == index))
            actual_modules.extend(shard["modules"])
            actual_union.update(shard["test_ids"])
        self.assertEqual(actual_union, Counter(case["id"] for case in original))
        self.assertEqual(len(actual_modules), len(set(actual_modules)), "defining modules must be disjoint")

    @staticmethod
    def inventory_hash(test_ids):
        serialized = json.dumps(sorted(test_ids), ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def test_original_multiset_balancing_order_and_inherited_duplicates(self):
        original = self.original_cases()
        self.assertEqual(len(original), 24)
        self.assertIn({"id": "test_control_web_gamma.LocalCase.test_inherited_a",
                       "module": "test_control_web_gamma"}, original)
        duplicates = {case_id: count for case_id, count in Counter(c["id"] for c in original).items() if count > 1}
        self.assertEqual(duplicates, {"_fixture_cases.SharedCase.test_inherited_a": 2,
                                      "_fixture_cases.SharedCase.test_inherited_b": 2})
        self.assert_partition(self.plan(), original)

    def test_plan_is_deterministic_across_processes(self):
        first = self.call("--list")
        second = self.call("--list")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assert_partition(json.loads(first.stdout), self.original_cases())

    def test_new_matching_module_is_discovered_without_manifest_edit(self):
        before = self.plan()
        self.add_module("test_control_web_new_unlisted_contract", 11)
        after = self.plan()
        self.assertEqual(after["total_test_count"], before["total_test_count"] + 11)
        self.assert_partition(after, self.original_cases())

    def test_import_failure_fails_collection_and_every_selected_shard(self):
        self.write("test_control_web_broken.py", "raise ImportError('intentional collection failure')\n")
        for args in (("--list",), *(("--shard", str(i)) for i in range(4))):
            with self.subTest(arguments=args):
                self.assertNotEqual(self.call(*args).returncode, 0)

    def test_import_stdout_does_not_corrupt_json_inventory(self):
        path = self.repo / "tests/test_control_web_alpha.py"
        path.write_text("print('intentional import chatter')\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
        result = self.call("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["total_test_count"], 24)
        self.assertNotIn("intentional import chatter", result.stdout)
        self.assertIn("intentional import chatter", result.stderr)

    def test_each_shard_runs_fixtures_and_propagates_real_test_failure(self):
        plan = self.plan()
        for shard in plan["shards"]:
            with self.subTest(shard=shard["index"]):
                arguments = ("--shard", str(shard["index"]))
                passed = self.call(*arguments)
                self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
                failed = self.call(*arguments, env={"FAIL_TEST_ID": shard["test_ids"][0]})
                self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
                self.assertIn("intentional shard failure", failed.stdout + failed.stderr)
                self.assertNotEqual(self.call("--aggregate", "failure").returncode, 0)

    def test_empty_selected_shards_are_rejected(self):
        for path in (self.repo / "tests").glob("test_*.py"):
            path.unlink()
        self.add_module("test_control_web_only", 1)
        # A single defining module must be assigned to shard 0 by the tie rule.
        self.assertEqual([s["test_count"] for s in self.plan()["shards"]], [1, 0, 0, 0])
        for index in (1, 2, 3):
            with self.subTest(shard=index):
                self.assertNotEqual(self.call("--shard", str(index)).returncode, 0)

    def test_invalid_shard_arguments_are_rejected(self):
        for value in ("-1", "4", "abc", "1.0", "", "01x"):
            with self.subTest(value=value):
                self.assertNotEqual(self.call("--shard", value).returncode, 0)
        self.assertNotEqual(self.call("--shard").returncode, 0)

    def test_aggregate_accepts_only_exact_success(self):
        self.assertEqual(self.call("--aggregate", "success").returncode, 0)
        for status in ("failure", "cancelled", "skipped", "missing", "unknown", "pending",
                       "", "Success", "SUCCESS", "success ", "null", "true"):
            with self.subTest(status=status):
                self.assertNotEqual(self.call("--aggregate", status).returncode, 0)
        self.assertNotEqual(self.call("--aggregate").returncode, 0)


class WorkflowContracts(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text(encoding="utf-8")
        # Jobs are top-level mappings below jobs:, independent of step names.
        self.jobs = dict(re.findall(r"(?ms)^  ([a-zA-Z_][\w-]*):\n(.*?)(?=^  [a-zA-Z_][\w-]*:\n|\Z)", self.source))

    def test_exact_seven_groups_and_independent_completion(self):
        matrix_jobs = [(name, block) for name, block in self.jobs.items() if re.search(r"^    strategy:", block, re.M)]
        self.assertEqual(len(matrix_jobs), 1)
        _, block = matrix_jobs[0]
        self.assertRegex(block, r"fail-fast:\s*false")
        matrix = re.search(r"(?ms)^      matrix:\n(.*?)(?=^    \S|\Z)", block)
        self.assertIsNotNone(matrix)
        group = re.search(r"(?ms)^\s+group:\s*(.*)", matrix.group(1))
        self.assertIsNotNone(group)
        labels = re.findall(r"[A-Za-z_]\w*", group.group(1))
        self.assertCountEqual(labels, ["web_0", "web_1", "web_2", "web_3", "android_publication", "provider", "deployment_install"])
        self.assertNotIn("continue-on-error:", block)

    def test_final_required_contracts_job_checks_matrix_result_even_on_failure(self):
        block = self.jobs["contracts"]
        matrix_names = [name for name, body in self.jobs.items() if re.search(r"^    strategy:", body, re.M)]
        self.assertEqual(len(matrix_names), 1)
        self.assertRegex(block, rf"needs:\s*(?:\[\s*)?{re.escape(matrix_names[0])}\b")
        self.assertIn("always()", block)
        self.assertRegex(block, rf"needs\.{re.escape(matrix_names[0])}\.result")
        self.assertIn("--aggregate", block)
        self.assertNotIn("continue-on-error:", block)

    def test_checkout_pins_and_clean_tree_guard_before_execution(self):
        checkout_blocks = [(name, body) for name, body in self.jobs.items() if "actions/checkout@" in body]
        self.assertTrue(checkout_blocks)
        for name, body in checkout_blocks:
            self.assertIn("actions/checkout@v6", body)
            self.assertIn("actions/setup-python@v6", body)
            self.assertRegex(body, r"fetch-depth:\s*0")
            self.assertRegex(body, r"ref:.*github\.event\.pull_request\.head\.sha.*github\.sha")
            self.assertRegex(body, r"git rev-parse HEAD")
            self.assertIn("github.event.pull_request.head.sha", body)
            self.assertIn("git diff --exit-code HEAD --", body)
            self.assertIn("git ls-files --others --exclude-standard", body)
            guard = body.index("git diff --exit-code HEAD --")
            execution_pattern = (
                r"ci/control_web_contracts\.py\s+--aggregate\b" if name == "contracts" else
                r"(?:--shard|python tests/test-provider|unittest discover -s tests -p 'test_control_android)"
            )
            executions = [m.start() for m in re.finditer(execution_pattern, body)]
            self.assertTrue(executions)
            self.assertTrue(all(guard < pos for pos in executions))
        self.assertIn("73eb36b4eba7b13b893014e400b30b7f918de986", self.source)
        self.assertIn("CONTROL_LIVE_UX_QA_REPO: ${{ github.workspace }}", self.source)

    def test_all_original_nonweb_commands_compile_gates_and_prerequisites_survive(self):
        commands = [
            "python -m unittest discover -s tests -p 'test_control_android_publish*.py'",
            "python -m py_compile bin/_control_web.py bin/_control_web_live.py bin/_control_web_broker.py bin/_control_web_sessions.py bin/_codex_rc.py bin/ai-control-web",
            "python tests/test-web-universal-deploy.py",
            "python -m py_compile deployment/ai-control-web-deploy.py",
            "bash tests/test-agent-io.sh", "python tests/test-codex-task-runtime.py",
            "bash tests/test-install-completeness.sh", "bash tests/test-install-idempotent.sh", "bash tests/test-install-macos-legacy.sh",
        ]
        provider_scripts = ["accounts", "account-binding", "account-config-pointer", "account-lower-admission",
                            "profile-registration", "profile-publication", "profile-capture-reference",
                            "profile-sticky-ancestor", "profile-cli", "task-publication-guard", "publication-committed-outcome"]
        commands += [f"python tests/test-provider-{name}.py" for name in provider_scripts]
        for command in commands:
            with self.subTest(command=command):
                self.assertIn(command, self.source)
        for pin in ("requirements-web.lock -r requirements-devbus.lock", "httpx==0.28.1", "playwright==1.63.0",
                    "python -m playwright install --with-deps chromium", "nats-server-v2.15.0-linux-amd64",
                    "5d2c51caca950333aba84911df7d377f826f3a59ec36061c6539105084f65c92",
                    "v4.53.3/yq_linux_amd64", "fa52a4e758c63d38299163fbdd1edfb4c4963247918bf9c1c5d31d84789eded4"):
            with self.subTest(prerequisite=pin):
                self.assertIn(pin, self.source)
        self.assertIn('export CLAUDE_BIN="$fixture_bin/claude"', self.source)
        self.assertIn('if [ "${1:-}" = --version ]; then', self.source)
        self.assertIn("echo 'Claude inert installation fixture'", self.source)
        self.assertIn("exit 99", self.source)
        self.assertIn('chmod 700 "$fixture_bin/claude"', self.source)


if __name__ == "__main__":
    unittest.main()
