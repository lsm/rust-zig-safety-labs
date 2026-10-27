pub fn solve(input: &[u8]) -> u64 {
    input.iter().map(|&byte| u64::from(byte)).sum()
}
