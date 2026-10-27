#!/usr/bin/env python3
import unittest
from zig_syntax_repair import repair


class ZigRepairTests(unittest.TestCase):
    def test_index_capture_one_case(self):
        x, rules = repair('for (input) |byte, idx| { sum += idx; }')
        self.assertIn('for (input, 0..) |byte, idx|', x)
        self.assertEqual(rules, ['zig_for_index_capture:1'])

    def test_already_valid_code_untouched(self):
        text = 'for (input, 0..) |byte, i| { _ = i; }'
        self.assertEqual(repair(text), (text, []))

    def test_old_intcast(self):
        a, rules = repair('const v = @intCast(u64, x);')
        self.assertIn('@as(u64, @intCast(x))', a)
        self.assertEqual(rules, ['zig_old_intcast:1'])

    def test_trusted_core_path_only_in_restricted(self):
        s = 'const core = @import("core");'
        self.assertIn('core.zig', repair(s, restricted=True)[0])
        self.assertEqual(repair(s)[0], s)

    def test_missing_std_import(self):
        text = 'pub fn f() void { std.debug.print("x", .{}); }'
        x, rules = repair(text)
        self.assertTrue(x.startswith('const std = @import("std");'))
        self.assertEqual(rules, ['explicit_std_import'])

    def test_does_not_touch_pointer_or_threading(self):
        text = 'const data = @ptrFromInt(999); std.Thread.spawn(.{}, f, .{});'
        fixed, rules = repair(text)
        self.assertIn('@ptrFromInt(999)', fixed)
        self.assertIn('std.Thread.spawn', fixed)
        self.assertEqual(rules, ['explicit_std_import'])


if __name__ == "__main__":
    unittest.main(verbosity=2)
