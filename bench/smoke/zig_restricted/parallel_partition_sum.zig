const core = @import("core.zig");
pub fn solve(input: []const u8) u64 {
    return core.parallelPartitionSum(input);
}
