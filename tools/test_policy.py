#!/usr/bin/env python3
"""Adversarial regression cases for the restricted Zig source policy."""
import unittest
from pathlib import Path
from policy_check import check_text

ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
    def test_actual_restricted_app_accepted(self):
        self.assertEqual(check_text((ROOT / "zig_restricted/app.zig").read_text()), [])

    def test_literals_and_comments_cannot_trigger_false_alarms(self):
        text = 'const std = @import("std"); // std.Thread.spawn\nconst s = "a.free(4) and @ptrCast(ptr)";'
        self.assertEqual(check_text(text), [])

    def test_core_import_is_allowed(self):
        self.assertEqual(check_text('const core = @import("core.zig");'), [])

    def test_valid_array_type_and_literal(self):
        self.assertEqual(check_text('const a: [4]u8 = @splat(1);\nconst b = [_]u8{1,2};'), [])

    def test_block_unsafe_patterns(self):
        bad = {
            "heap allocation": ('const x = try a.alloc(u8, 4);', "raw_heap"),
            "heap alias": ('const maker = allocator . alloc;', "raw_heap"),
            "free": ('a.free(data);', "raw_heap"),
            "pointer cast": ('const p = @ptrFromInt(1234);', "raw_pointer_ops"),
            "pointer cast alias": ('const x = @field(p, "ptr");', "unapproved_builtin"),
            "pointer field": ('const p = bytes.ptr;', "raw_pointer_ops"),
            "pointer dereference": ('ptr.* = 1;', "raw_pointer_ops"),
            "raw many pointer": ('const p: [*]u8 = undefined;', "raw_pointer_ops"),
            "raw typed pointer": ('fn evil(p: *u8) void {}', "raw_pointer_ops"),
            "thread spawn": ('const t = try std.Thread.spawn(.{}, f, .{});', "direct_threading"),
            "thread alias": ('const T = std . Thread;', "direct_threading"),
            "thread method alias": ('const maker = T.spawn;', "direct_threading"),
            "threadlocal": ('threadlocal var n: usize = 0;', "unsafe_control"),
            "atomic access": ('const a = std.atomic.Value(u32).init(0);', "raw_pointer_ops"),
            "index": ('const x = buf[buf.len];', "unchecked_index"),
            "expression index": ('const x = getBuffer()[5];', "unchecked_index"),
            "unapproved import": ('const raw = @import("raw_ptr.zig");', "unauthorized_import"),
            "dynamic import": ('const x = @import(file);', "unauthorized_import"),
            "unsafe control": ('var bytes: [8]u8 = undefined;', "unsafe_control"),
            "runtime safety override": ('@setRuntimeSafety(false);', "unsafe_control"),
            "manual memcpy": ('@memcpy(dst, src);', "manual_copy"),
            "inline assembly": ('asm volatile ("nop");', "unsafe_control"),
            "ffi": ('extern fn touch() void;', "unsafe_control"),
            "multiline literal": ('const x = \\\\hello;', "unsupported_multiline_string"),
        }
        for name, (source, expected) in bad.items():
            with self.subTest(name=name):
                self.assertTrue(
                    any(expected in message for message in check_text(source)),
                    f"{name} escaped: {source}",
                )

    def test_comment_does_not_hide_live_unsafe_code(self):
        self.assertTrue(any("direct_threading" in e for e in check_text(
            'const safe = "std.Thread"; // ignored\nconst x = std.Thread;\n'
        )))

    def test_safe_algorithmic_code_is_not_rejected(self):
        self.assertEqual(check_text("""
const std = @import("std");
const core = @import("core.zig");
pub fn solve(input: []const u8) u64 {
    var total: u64 = 0;
    for (input) |x| total += x;
    return total;
}
"""), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
