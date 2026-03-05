---
name: performance
description: Seahorse performance engineering — profiling, tuning Rust/Python/FFI, latency targets
---

# Seahorse — Performance Skill

## Latency Targets

| Layer                       | Target          | Measurement     |
| --------------------------- | --------------- | --------------- |
| HTTP routing                | < 1ms p99       | Axum middleware |
| HNSW memory search (100k)   | < 5ms           | Rust bench      |
| PyO3 FFI call overhead      | < 50µs          | criterion       |
| LLM first token (streaming) | < 500ms         | end-to-end      |
| SSE token delivery          | < 5ms per chunk | client timer    |
| Memory per Rust agent       | < 10MB          | `heaptrack`     |
| Python AI layer cold start  | < 2s            | process timer   |

---

## Profiling Toolchain

### Rust Profiling

```bash
# CPU profiling with flamegraph
cargo install flamegraph
CARGO_PROFILE_RELEASE_DEBUG=true cargo flamegraph --bin seahorse-router

# Benchmark with criterion
cargo bench --bench memory_bench

# Memory profiling
cargo install heaptrack
heaptrack ./target/release/seahorse-router

# Tokio async task profiling
TOKIO_CONSOLE=1 cargo run --features tokio-unstable
```

### Python Profiling

```bash
# CPU profiling
uv run python -m cProfile -o prof.out -m seahorse_api.main
uv run python -m pstats prof.out

# Async profiling
uv run pip install pyinstrument
uv run pyinstrument -r html seahorse_ai/planner.py

# Memory
uv run pip install memray
uv run memray run -o output.bin seahorse_api/main.py
uv run memray flamegraph output.bin
```

---

## Criterion Benchmarks (Rust)

```rust
// crates/seahorse-core/benches/memory_bench.rs
use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion};
use seahorse_core::AgentMemory;

fn bench_hnsw_search(c: &mut Criterion) {
    let mem = AgentMemory::new(384, 100_000);
    // Pre-populate
    for i in 0..10_000u64 {
        let v: Vec<f32> = (0..384).map(|j| (i + j) as f32 / 1000.0).collect();
        mem.insert(i as usize, &v);
    }
    let query: Vec<f32> = (0..384).map(|i| i as f32 / 384.0).collect();

    c.bench_function("hnsw_search_k10", |b| {
        b.iter(|| mem.search(&query, 10, 50))
    });
}

criterion_group!(benches, bench_hnsw_search);
criterion_main!(benches);
```

Run: `cargo bench --bench memory_bench -- --output-format bencher`

---

## Hot Path Anti-Patterns

### Rust

```rust
// ❌ Cloning on hot path
fn process(data: Vec<u8>) -> Vec<u8> { data.clone() }  // NEVER

// ✅ Borrow
fn process(data: &[u8]) -> &[u8] { data }

// ❌ String allocation in loop
for item in items { let s = format!("{item}"); }  // allocates every iteration

// ✅ Write to buffer
let mut buf = String::with_capacity(items.len() * 32);
for item in items { write!(buf, "{item}").unwrap(); }

// ❌ Mutex on hot read path
let val = mutex.lock().unwrap().clone();

// ✅ RwLock or dashmap or Arc<AtomicXxx>
let val = rwlock.read().unwrap().clone();
```

### Python

```python
# ❌ JSON round-trip across FFI
import json
result = ffi_fn(json.dumps(data).encode())  # serialize → cross → deserialize

# ✅ Raw bytes / numpy
result = ffi_fn(np.array(data, dtype=np.float32).tobytes())

# ❌ Repeated embedding calls for same text
for query in queries:
    emb = await embed(query)  # N API calls

# ✅ Batch
embeddings = await embed_batch(queries)  # 1 API call

# ❌ Synchronous litellm in async context
response = litellm.completion(...)  # blocks event loop

# ✅ Always async
response = await litellm.acompletion(...)
```

---

## Tokio Tuning

```bash
# Set worker threads to physical cores (default: logical cores)
TOKIO_WORKER_THREADS=8 ./seahorse-router

# Tokio runtime config for latency-sensitive workloads
tokio::runtime::Builder::new_multi_thread()
    .worker_threads(num_cpus::get_physical())
    .max_blocking_threads(64)    # for spawn_blocking (LLM calls)
    .enable_all()
    .build()
```

**Avoid:**

- `tokio::time::sleep` in tight loops — use backpressure instead
- `spawn_blocking` for < 1ms work — overhead exceeds benefit
- Unbounded channels — always set capacity

---

## HNSW Tuning Guide

```rust
// Tune for use case
let index = Hnsw::new(
    M,                // 8–32: higher = better recall + more memory
    max_elements,     // pre-allocate (no realloc on insert)
    max_layers,       // 16 default
    ef_construction,  // 100–500: higher = better build quality
    DistCosine,       // or DistDotProd for normalized vecs
);
```

| Use Case                | M   | ef_construction | ef (search) | Recall@10 |
| ----------------------- | --- | --------------- | ----------- | --------- |
| Fast search, low recall | 8   | 100             | 50          | ~90%      |
| Balanced (default)      | 16  | 200             | 100         | ~97%      |
| High recall             | 32  | 400             | 200         | ~99%      |

---

## Docker / Production Tuning

```dockerfile
FROM rust:1.78-slim as builder
RUN apt-get install -y mold
# Use mold linker for fast builds
ENV RUSTFLAGS="-C link-arg=-fuse-ld=mold"
RUN cargo build --release

FROM gcr.io/distroless/cc-debian12
COPY --from=builder /app/target/release/seahorse-router /app/
```

```bash
# OS-level tuning
echo 'net.core.somaxconn = 65535' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_tw_reuse = 1'  >> /etc/sysctl.conf
sysctl -p

# Set Tokio thread stack size for deep async stacks
RUST_MIN_STACK=8388608 ./seahorse-router
```

---

## Performance PR Checklist

- [ ] Benchmark before+after for any hot path change
- [ ] No `clone()` in loops or request handlers
- [ ] No blocking calls in async functions — use `spawn_blocking`
- [ ] No JSON serialization across FFI on hot path
- [ ] GIL released via `py.allow_threads()` for Rust compute > 10µs
- [ ] Tokio channels bounded with appropriate capacity
- [ ] HNSW `ef` tuned for latency budget (not max recall blindly)
