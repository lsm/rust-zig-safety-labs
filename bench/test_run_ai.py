#!/usr/bin/env python3
"""Unit tests for model response parsing and honest empty accounting."""
import unittest
from run_ai import code_only, response_text, summary


class RunnerTests(unittest.TestCase):
    def test_output_parser(self):
        obj = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "pub fn solve() void {}"}
        ]}]}
        self.assertIn("pub fn", response_text(obj))

    def test_fenced_output(self):
        tick = chr(96) * 3
        self.assertEqual(code_only(tick + "zig\nlet n = 1;\n" + tick), "let n = 1;\n")
        self.assertEqual(code_only("plain"), "plain\n")

    def test_no_traces_mean_no_passes(self):
        for row in summary([]).values():
            self.assertEqual(row["judged"], 0)
            self.assertEqual(row["final_pass"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
