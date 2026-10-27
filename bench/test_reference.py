#!/usr/bin/env python3
import unittest
from reference import reference, load_suite, check_examples


class OracleTests(unittest.TestCase):
    def test_task_definitions(self):
        check_examples()
        self.assertEqual(len(load_suite()["tasks"]), 10)

    def test_edge_cases(self):
        self.assertEqual(reference("first_repeat_index", []), 0)
        self.assertEqual(reference("first_repeat_index", [4, 5, 4]), 2)
        self.assertEqual(reference("longest_run", [2, 2, 4, 4, 4]), 3)
        self.assertEqual(reference("bounded_copy_sum", [1] * 65), 0)
        self.assertEqual(reference("mirror_matches", [5, 2, 5]), 1)
        self.assertEqual(reference("even_index_sum", [1, 2, 3, 4]), 4)
        self.assertEqual(reference("count_digits", [48, 55, 127]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
