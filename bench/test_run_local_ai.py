#!/usr/bin/env python3
"""Unit tests for an honest local-model scoreboard and repair feedback."""
import unittest
from run_local_ai import effective_status, repair_feedback, per_arm


class LocalRunnerTests(unittest.TestCase):
    def test_no_trials_never_count_as_success(self):
        for score in per_arm([]).values():
            self.assertEqual(score["judged"], 0)
            self.assertEqual(score["initial_pass"], 0)

    def test_structural_shortcut_not_success(self):
        example = {
            "status": "PASS",
            "structural_evidence": {"required": True, "observed": False},
        }
        self.assertEqual(effective_status(example), "STRUCTURE_MISSING")
        self.assertIn("OS threading", repair_feedback(example))

    def test_actual_pass(self):
        self.assertEqual(effective_status({
            "status": "PASS", "structural_evidence": {"required": False}
        }), "PASS")

    def test_hidden_runtime_failure_not_feedback(self):
        self.assertEqual(repair_feedback({
            "status": "TEST_FAILED", "test_log_tail": "secret held-out vector"
        }), "")

    def test_policy_feedback_reports_only_denial(self):
        s = repair_feedback({"status": "POLICY_BLOCKED",
                             "policy_issues": ["L3: raw_heap"]})
        self.assertIn("raw_heap", s)

    def test_compiler_feedback_strips_test_vectors(self):
        s = repair_feedback({"status": "COMPILE_ERROR", "runs": [{
            "log_tail": (
                "judge.zig:2:3: error: vector_0\n"
                "submission.zig:5:3: error: expected expression\n"
            )
        }]})
        self.assertNotIn("vector_0", s)
        self.assertIn("submission.zig", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
