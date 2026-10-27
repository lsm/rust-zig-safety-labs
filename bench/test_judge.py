#!/usr/bin/env python3
"""No compiler needed for judge plan/unit tests."""
import unittest
import os
from unittest.mock import patch
from judge import public_prompt, structural_evidence, metrics, task_by_id, _judge_zig, _judge_rust, _vectors, stripped_env


class JudgeUnitTests(unittest.TestCase):
    def test_public_examples_do_not_contain_hidden_vectors(self):
        task = task_by_id("sum_bytes")
        self.assertIn("Return the sum", public_prompt(task, "zig_plain"))
        self.assertNotIn("127", public_prompt(task, "zig_plain"))

    def test_languages_have_explicit_contracts(self):
        task = task_by_id("max_byte")
        self.assertIn("[]const u8", public_prompt(task, "zig_plain"))
        self.assertIn("core.zig", public_prompt(task, "zig_restricted"))
        self.assertIn("&[u8]", public_prompt(task, "rust_safe"))

    def test_judge_source_has_cases(self):
        cases = _vectors("sum_bytes")
        self.assertEqual(len(cases), 15)
        self.assertEqual(cases[0], ([], 0))
        self.assertIn('vector_0', _judge_zig(cases))
        self.assertIn('vector_0', _judge_rust(cases))

    def test_heuristic_is_only_evidence(self):
        self.assertTrue(structural_evidence(
            "parallel_partition_sum", "zig_restricted",
            'return core.parallelPartitionSum(input);')["observed"])
        self.assertFalse(structural_evidence(
            "parallel_partition_sum", "rust_safe",
            "return input.iter().map(|x| *x as u64).sum();")["observed"])

    def test_candidate_subprocess_does_not_receive_secrets(self):
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "do-not-forward",
            "GITHUB_TOKEN": "do-not-forward",
            "ACTIONS_RUNTIME_TOKEN": "do-not-forward",
            "PATH": "/usr/bin",
        }):
            safe = stripped_env()
            self.assertEqual(safe["PATH"], "/usr/bin")
            self.assertNotIn("OPENAI_API_KEY", safe)
            self.assertNotIn("GITHUB_TOKEN", safe)
            self.assertNotIn("ACTIONS_RUNTIME_TOKEN", safe)

    def test_source_metrics(self):
        self.assertEqual(metrics("pub fn f() void { }\n")["source_lines"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
