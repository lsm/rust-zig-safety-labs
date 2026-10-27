pub fn solve(input: &[u8]) -> u64 {
    if input.len() > 64 { return 0; }
    let owned = input.to_vec();
    owned.iter().map(|&byte| u64::from(byte)).sum()
}
