use seahorse_core::AgentMemory;

fn main() {
    // Placeholder bench — real criterion benches added later
    let mem = AgentMemory::new(384, 10_000, 16, 200);
    let vec: Vec<f32> = (0..384).map(|i| i as f32 / 384.0).collect();
    mem.insert(0, &vec);
    let _results = mem.search(&vec, 10, 50);
    println!("bench placeholder ok");
}
