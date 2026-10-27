pub fn solve(input: []const u8) u64 {
    var result: u64 = 0;
    for (input) |byte| result += byte;
    return result;
}
