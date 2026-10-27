pub fn solve(input: &[u8]) -> u64 {
    std::thread::scope(|scope| {
        let (left, right) = input.split_at(input.len() / 2);
        let t1 = scope.spawn(|| left.iter().map(|&x| u64::from(x)).sum::<u64>());
        let t2 = scope.spawn(|| right.iter().map(|&x| u64::from(x)).sum::<u64>());
        t1.join().expect("thread 1") + t2.join().expect("thread 2")
    })
}
