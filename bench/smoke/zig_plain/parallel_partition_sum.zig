const std = @import("std");
fn worker(input: []const u8, result: *u64) void {
    var acc: u64 = 0;
    for (input) |byte| acc += byte;
    result.* = acc;
}
pub fn solve(input: []const u8) u64 {
    const mid = input.len / 2;
    var a: u64 = 0;
    var b: u64 = 0;
    const t1 = std.Thread.spawn(.{}, worker, .{ input[0..mid], &a }) catch return 0;
    const t2 = std.Thread.spawn(.{}, worker, .{ input[mid..], &b }) catch {
        t1.join();
        return 0;
    };
    t1.join();
    t2.join();
    return a + b;
}
