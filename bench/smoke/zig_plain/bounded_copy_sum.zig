const std = @import("std");
pub fn solve(input: []const u8) u64 {
    if (input.len > 64) return 0;
    const owned = std.heap.page_allocator.alloc(u8, input.len) catch return 0;
    defer std.heap.page_allocator.free(owned);
    @memcpy(owned, input);
    var result: u64 = 0;
    for (owned) |byte| result += byte;
    return result;
}
