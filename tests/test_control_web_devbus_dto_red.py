"""INV-DEVBUS-06 INV-DEVBUS-10: independent exact public export contract."""
from copy import deepcopy
import unittest
import live_devbus_blind_support as s


class DevbusDtoBlind(unittest.TestCase):
    def export(self, value, **filters):
        self.projection = s.ProjectionData(value)
        function = s.seam(self, "_control_web_broker", "bounded_devbus_snapshot")
        result = function(self.projection, **filters)
        self.assertEqual(self.projection.value, value, "Exporter mutated retained projection")
        return result

    def validate(self, value):
        return s.seam(self, "_control_web_broker", "devbus_result")(value)

    def test_exact_valid_DTO_and_strict_schema(self):
        value = s.empty(); value["tasks"] = [s.task(result="safe synthetic result")]
        self.assertEqual(self.validate(value), value)
        for field in (True, 1.0, "1", 2):
            with self.subTest(schema=field):
                self.assertEqual(self.validate(value | {"schema": field}), {"error": "unavailable"})

    def test_unknown_top_and_nested_fields_rejected_without_echo(self):
        value = s.empty(); value["tasks"] = [s.task()]; value["agents"] = [s.agent()]
        value["events"] = [s.event(1)]
        for target in ((), ("connection",), ("coverage",), ("tasks", 0), ("agents", 0), ("events", 0)):
            with self.subTest(target=target):
                data = deepcopy(value); node = data
                for key in target: node = node[key]
                node["_private_internal"] = "synthetic-private"
                self.assertEqual(self.validate(data), {"error": "unavailable"})

    def test_invalid_enums_bool_numbers_caps_and_nonfinite(self):
        value = s.empty(known=True); value["tasks"] = [s.task()]; value["events"] = [s.event(1)]
        changes = (("connection", "state", "degraded"), ("coverage", "first_seq", True),
                   ("coverage", "max_bytes", float("nan")), ("coverage", "issues", ["made_up"]),
                   ("coverage", "replay_complete", 1))
        for parent, key, replacement in changes:
            data = deepcopy(value); data[parent][key] = replacement
            self.assertEqual(self.validate(data), {"error": "unavailable"})
        for key, replacement in (("sequence", True), ("sequence", 0), ("kind", "submit")):
            data = deepcopy(value); data["events"][0][key] = replacement
            self.assertEqual(self.validate(data), {"error": "unavailable"})
        for key, replacement in (("delivery", "acked"), ("quality", "accepted"),
                                 ("duration_seconds", 1), ("result", "x" * 4097)):
            data = deepcopy(value); data["tasks"][0][key] = replacement
            self.assertEqual(self.validate(data), {"error": "unavailable"})
        data = deepcopy(value); data["tasks"] = [s.task(i) for i in range(257)]
        self.assertEqual(self.validate(data), {"error": "unavailable"})

    def test_first_seq_none_requires_unknown_mode(self):
        for mode in ("window", "partial", "replaying"):
            value = s.empty(); value["coverage"]["mode"] = mode
            self.assertEqual(self.validate(value), {"error": "unavailable"})

    def test_lone_result_surrogate_replaced_without_losing_unrelated_task(self):
        for known in (False, True):
            value = s.empty(known=known); value["tasks"] = [s.task(1, result="prefix\ud800suffix"), s.task(2, result="retained")]
            expected = deepcopy(value); expected["tasks"][0]["result"] = "prefix�suffix"
            expected["tasks"][0]["output_truncated"] = True; s.mark_limited(expected)
            self.assertEqual(self.export(value), expected)
            self.assertEqual(self.validate(value), {"error": "unavailable"}, "Wire validator must not repair raw backend values")

    def test_otherfield_surrogate_not_repaired(self):
        value = s.empty(); value["tasks"] = [s.task()]; value["tasks"][0]["task_id"] = "bad\ud800"
        self.assertEqual(self.export(value), {"error": "unavailable"})

    def test_utf8_json_escapes_and_first_clipping_batch(self):
        value = s.empty(known=True)
        value["tasks"] = [s.task(i, result=("🙂\"\\\n" * 700)[:4096]) for i in range(1, 17)]
        self.assertGreater(len(s.canonical(value)), s.LIMIT)
        expected = deepcopy(value)
        for row in expected["tasks"]:
            row["result"] = row["result"][:256]; row["output_truncated"] = True
        s.mark_limited(expected)
        self.assertLess(len(s.canonical(expected)), s.LIMIT)
        observed = self.export(value)
        self.assertEqual(observed, expected, "Every result in first clipping batch must be processed before measurement")
        self.assertLessEqual(len(s.canonical(observed)), s.LIMIT)
        self.assertLessEqual(len(s.canonical(observed)) + 1, 131072)

    def test_minimal_oldest_event_prefix_with_equal_sequence_tie(self):
        value = s.dense(task_count=40, result="🙂" * 256)
        value["events"][0]["sequence"] = value["events"][1]["sequence"] = 1
        value["events"][0]["message_id"], value["events"][1]["message_id"] = "z-first", "a-first"
        ordered = sorted(value["events"], key=lambda row: (row["sequence"], row["message_id"]))
        def remove(data, count):
            if count > len(ordered): return False
            data["events"] = ordered[count:]; return True
        expected = s.smallest_fitting_prefix(value, remove)
        self.assertIsNotNone(expected, "Independent event-prefix fixture must reach this stage")
        count, oracle = expected; self.assertGreater(count, 0)
        self.assertEqual(self.export(value), oracle)

    def test_transition_trim_retains_state_and_uses_minimal_global_prefix(self):
        value = s.dense(task_count=32, event_count=0, transition_count=32, result=None)
        ordered = sorted((row["sequence"], row["message_id"], task["task_id"])
                         for task in value["tasks"] for row in task["transitions"])
        def remove(data, count):
            if count > len(ordered): return False
            removed = set(ordered[:count])
            for task in data["tasks"]:
                task["transitions"] = [row for row in task["transitions"]
                    if (row["sequence"], row["message_id"], task["task_id"]) not in removed]
            return True
        expected = s.smallest_fitting_prefix(value, remove); self.assertIsNotNone(expected)
        self.assertEqual(self.export(value), expected[1])
        self.assertTrue(all(row["state"] == "completed" for row in expected[1]["tasks"]))

    def test_captured_task_rank_before_transition_trim(self):
        value = s.dense(task_count=256, event_count=0, transition_count=1, result="🙂" * 256)
        # Highest numeric task is oldest by observable sequence; ID order must
        # not replace the rank when transition clipping removes its evidence.
        for index, row in enumerate(value["tasks"]): row["transitions"][0]["sequence"] = 256 - index
        expected = deepcopy(value)
        for row in expected["tasks"]: row["transitions"] = []
        s.mark_limited(expected)
        ranks = sorted(value["tasks"], key=lambda row: (row["transitions"][0]["sequence"], row["task_id"]))
        def remove(data, count):
            if count > len(ranks): return False
            removed = {row["task_id"] for row in ranks[:count]}
            data["tasks"] = [row for row in data["tasks"] if row["task_id"] not in removed]; return True
        oracle = s.smallest_fitting_prefix(expected, remove); self.assertIsNotNone(oracle)
        self.assertEqual(self.export(value), oracle[1])

    def test_minimal_agent_prefix_in_source_order(self):
        value = s.dense(task_count=0, event_count=0, agent_count=64, dense_agents=True, result=None)
        value["agents"].reverse()
        def remove(data, count):
            if count > len(value["agents"]): return False
            data["agents"] = data["agents"][count:]; return True
        oracle = s.smallest_fitting_prefix(value, remove); self.assertIsNotNone(oracle)
        self.assertEqual(self.export(value), oracle[1])

    def test_filter_before_clipping_preserves_small_selected_window(self):
        value = s.dense(task_count=256, event_count=0)
        expected = s.ProjectionData(value).snapshot(task="task256", agent="worker1")
        self.assertLess(len(s.canonical(expected)), s.LIMIT)
        self.assertEqual(self.export(value, task="task256", agent="worker1"), expected)
        self.assertEqual(self.projection.calls, [("task256", "worker1")])

    def test_unknown_coverage_and_producer_flag_idempotent(self):
        value = s.dense(task_count=16, event_count=0, known=False)
        value["tasks"][0]["output_truncated"] = True
        observed = self.export(value)
        self.assertEqual(observed["coverage"]["mode"], "unknown")
        self.assertTrue(observed["coverage"]["truncated"])
        self.assertEqual(observed["coverage"]["issues"], ["local_eviction"])
        self.assertTrue(observed["tasks"][0]["output_truncated"])
        self.assertEqual(self.export(observed), observed)
