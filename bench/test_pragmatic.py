#!/usr/bin/env python3
"""Rules for the deliberately pragmatic Zig safe subset."""
import sys
import tempfile
import unittest
from pathlib import Path
from judge import evaluate, public_prompt, task_by_id, structural_evidence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from policy_check import check_text


class PragmaticPolicyTests(unittest.TestCase):
    def test_indexing_is_the_only_deliberately_relaxed_prohibition(self):
        sample = 'pub fn solve(input: []const u8) u64 { return input[0]; }'
        self.assertTrue(any("unchecked_index" in x for x in check_text(sample)))
        self.assertFalse(check_text(sample, allow_indexing=True))

    def test_raw_allocation_and_pointers_still_denied(self):
        for code in ('a.free(memory);',
                     'const p = @ptrFromInt(12);',
                     'std.Thread.spawn(.{}, worker, .{});',
                     'extern fn bad();',
                     '@setRuntimeSafety(false);'):
            with self.subTest(code=code):
                self.assertTrue(check_text(code, allow_indexing=True))

    def test_optimize_mode_is_non_negotiable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate("zig_pragmatic", "sum_bytes",
                              "pub fn solve(input: []const u8) u64 { return 0; }",
                              Path(tmp), release_safe=False)
            self.assertEqual(result["status"], "REQUIRES_RELEASE_SAFE")

    def test_prompt_and_structure(self):
        task = task_by_id("parallel_partition_sum")
        prompt = public_prompt(task, "zig_pragmatic")
        self.assertIn("ReleaseSafe", prompt)
        self.assertIn("ALLOWED", prompt)
        self.assertTrue(structural_evidence(
            "parallel_partition_sum", "zig_pragmatic",
            'return core.parallelPartitionSum(input);')["observed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
