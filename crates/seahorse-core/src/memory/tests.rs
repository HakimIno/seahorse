use super::AgentMemory;

fn make_vec(seed: f32, dim: usize) -> Vec<f32> {
    (0..dim).map(|i| (seed + i as f32) / dim as f32).collect()
}

#[test]
fn insert_and_search_finds_exact_match_with_meta() {
    let mem = AgentMemory::new(8, 100, 8, 100);
    let vec = make_vec(1.0, 8);
    mem.insert(42, &vec, "hello world".to_string(), "{}".to_string());
    let results = mem.search(&vec, 1, 50);
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].0, 42);
    assert_eq!(results[0].2, "hello world");
}
