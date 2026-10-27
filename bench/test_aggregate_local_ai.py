#!/usr/bin/env python3
import unittest
from aggregate_local_ai import analyze, wilson, summarize_markdown


def fake(arm: str, task: str, rep: int, first: str, final: str) -> dict:
    return {
        "task": task, "repeat": rep, "arm": arm, "status": "JUDGED",
        "initial_effective": first, "final_effective": final,
        "repair_calls": int(first != final),
        "initial": {"metrics": {"source_lines": 12}},
        "final": {"metrics": {"source_lines": 14}},
    }


class AggregateTests(unittest.TestCase):
    def test_empty_is_not_a_success(self):
        x = analyze([])
        self.assertFalse(x["complete_60_trial_study"])
        self.assertEqual(x["judged_rows"], 0)
        self.assertIsNone(wilson(0, 0))

    def test_success_rate_bounds(self):
        x = wilson(5, 10)
        self.assertLess(x["lower"], 0.5)
        self.assertGreater(x["upper"], 0.5)

    def test_pair_comparison_only_same_task_repeat(self):
        rows = [
            fake("zig_plain", "t", 0, "PASS", "PASS"),
            fake("zig_restricted", "t", 0, "COMPILE_ERROR", "PASS"),
            fake("rust_safe", "t", 0, "PASS", "PASS"),
        ]
        result = analyze([{
            "model_identity": {"name": "qwen", "digest": "sha256:a"},
            "shard": 0, "planned": 3, "rows": rows,
        }])
        pair = result["paired_initial"]["zig_plain vs zig_restricted"]
        self.assertEqual(pair["left_only_passed"], 1)
        self.assertEqual(pair["right_only_passed"], 0)
        self.assertEqual(pair["comparable_pairs"], 1)
        self.assertFalse(result["complete_60_trial_study"])
        self.assertIn("Judged", summarize_markdown(result))

    def test_duplicate_trial_rejected(self):
        same = fake("rust_safe", "t", 0, "PASS", "PASS")
        one = {"model_identity": {"name": "m", "digest": "d"},
               "shard": 0, "planned": 1, "rows": [same]}
        with self.assertRaises(ValueError):
            analyze([one, one])


if __name__ == "__main__":
    unittest.main(verbosity=2)
