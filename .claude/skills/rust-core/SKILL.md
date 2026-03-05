---
name: rust-core
description: Seahorse Rust Core — Tokio async, Axum routing, HNSW memory, Wasmtime sandbox
---

# Seahorse — Rust Core Skill

## Scope

Everything in `crates/seahorse-core/` and `crates/seahorse-router/`. This skill governs:

- Async task scheduling (Tokio)
- HTTP + WebSocket layer (Axum)
- Vector memory (HNSW)
- Tool sandbox (Wasmtime)
- Streaming pipeline (SSE/WS via Tokio channels)

---

## Project Standards

```toml
# Cargo.toml
[workspace]
resolver = "2"
members = ["crates/seahorse-core", "crates/seahorse-router", "crates/seahorse-ffi"]

[workspace.dependencies]
tokio    = { version = "1", features = ["full"] }
axum     = { version = "0.7", features = ["ws", "macros"] }
serde    = { version = "1", features = ["derive"] }
thiserror = "1"
anyhow   = "1"
tracing  = "0.1"
```

```toml
# .cargo/config.toml
[target.x86_64-unknown-linux-gnu]
linker = "clang"
rustflags = ["-C", "link-arg=-fuse-ld=mold"]
```

---

## Error Handling — Mandate

Every crate defines its own typed error with `thiserror`:

```rust
// crates/seahorse-core/src/error.rs
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CoreError {
    #[error("memory index error: {0}")]
    Memory(#[from] HnswError),
    #[error("sandbox panic: {kind}")]
    Sandbox { kind: String },
    #[error("channel closed")]
    ChannelClosed,
}
```

**Rules:**

- `thiserror` for library errors (typed, structured)
- `anyhow` for binary / CLI entry points only
- No `.unwrap()` in `crates/` — use `?` or explicit `match`
- All errors must be `Send + Sync` for async compatibility

---

## Async Architecture (Tokio)

```rust
// Entrypoint pattern
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Init tracing first
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .json()  // structured logs
        .init();

    let core = SeahorseCore::new(Config::from_env()?).await?;
    let router = build_router(core.clone());

    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await?;
    axum::serve(listener, router).await?;
    Ok(())
}
```

**Concurrency rules:**

- Use `tokio::spawn` for independent tasks; propagate `JoinHandle` errors
- Use bounded `mpsc::channel(N)` for producer-consumer; never unbounded in hot paths
- Use `broadcast::channel` for fan-out (streaming tokens to multiple clients)
- CPU-heavy work → `tokio::task::spawn_blocking`
- Prefer `Arc<T>` over `Mutex<T>` for read-heavy shared state

---

## HTTP Router (Axum)

```rust
// crates/seahorse-router/src/lib.rs
use axum::{Router, routing::post, Extension};

pub fn build_router(core: Arc<SeahorseCore>) -> Router {
    Router::new()
        .route("/v1/agent/run",    post(handlers::run_agent))
        .route("/v1/agent/stream", post(handlers::stream_agent))
        .route("/v1/memory/search", post(handlers::memory_search))
        .layer(Extension(core))
        .layer(middleware::from_fn(auth_middleware))
        .layer(OtelAxumLayer::default())  // tracing
}
```

**Handler pattern:**

```rust
async fn run_agent(
    Extension(core): Extension<Arc<SeahorseCore>>,
    Json(req): Json<AgentRequest>,
) -> Result<Json<AgentResponse>, AppError> {
    core.run(req).await.map(Json)
}
```

Always use `AppError` (implements `IntoResponse`) — never panic in handlers.

---

## HNSW Vector Memory

```rust
// crates/seahorse-core/src/memory.rs
use hnsw_rs::prelude::*;

pub struct AgentMemory {
    index: Hnsw<f32, DistCosine>,
    dim: usize,
}

impl AgentMemory {
    pub fn new(dim: usize, max_elements: usize) -> Self {
        // M=16, ef_construction=200 — balanced for 100k docs
        let index = Hnsw::new(16, max_elements, 16, 200, DistCosine);
        Self { index, dim }
    }

    pub fn insert(&self, id: usize, embedding: &[f32]) {
        debug_assert_eq!(embedding.len(), self.dim);
        self.index.insert((&embedding.to_vec(), id));
    }

    pub fn search(&self, query: &[f32], k: usize, ef: usize) -> Vec<(usize, f32)> {
        self.index
            .search(query, k, ef)
            .into_iter()
            .map(|n| (n.d_id, n.distance))
            .collect()
    }
}
```

**Tuning guidelines:**
| Parameter | Default | Effect |
|---|---|---|
| M | 16 | graph connectivity; higher = better recall, more mem |
| ef_construction | 200 | build quality; higher = better recall, slower build |
| ef (search) | 50–200 | search quality; tune per latency budget |

---

## Wasmtime Sandbox

```rust
// crates/seahorse-core/src/sandbox.rs
use wasmtime::{Engine, Linker, Module, Store};

pub struct ToolSandbox {
    engine: Engine,
}

impl ToolSandbox {
    pub fn new() -> anyhow::Result<Self> {
        let mut config = wasmtime::Config::new();
        config.consume_fuel(true);  // deterministic execution limit
        Ok(Self { engine: Engine::new(&config)? })
    }

    pub fn run(&self, wasm: &[u8], input: &[u8], fuel: u64) -> anyhow::Result<Vec<u8>> {
        let module = Module::new(&self.engine, wasm)?;
        let mut store = Store::new(&self.engine, ());
        store.set_fuel(fuel)?;

        let linker = Linker::new(&self.engine);
        let instance = linker.instantiate(&mut store, &module)?;

        let run = instance.get_typed_func::<(i32, i32), (i32, i32)>(&mut store, "run")?;
        // ... memory handling
        todo!("implement input/output memory passing")
    }
}
```

---

## Streaming (SSE)

```rust
// SSE streaming pattern
use axum::response::sse::{Event, Sse};
use tokio_stream::wrappers::ReceiverStream;

async fn stream_agent(
    Extension(core): Extension<Arc<SeahorseCore>>,
    Json(req): Json<AgentRequest>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let (tx, rx) = tokio::sync::mpsc::channel::<String>(64);

    tokio::spawn(async move {
        core.run_streaming(req, tx).await.ok();
    });

    let stream = ReceiverStream::new(rx)
        .map(|token| Ok(Event::default().data(token)));

    Sse::new(stream).keep_alive(KeepAlive::default())
}
```

---

## Observability

```rust
use tracing::{info, instrument, warn, error};

#[instrument(skip(core), fields(agent_id = %req.agent_id))]
async fn run_agent_internal(core: &SeahorseCore, req: AgentRequest) -> Result<AgentResponse> {
    let span = tracing::Span::current();

    info!("agent started");
    let result = core.execute(&req).await;

    match &result {
        Ok(r)  => info!(tokens = r.total_tokens, "agent completed"),
        Err(e) => error!(err = %e, "agent failed"),
    }
    result
}
```

Use `#[instrument]` on every public async fn. Emit structured fields, not formatted strings.

---

## Clippy Lints (workspace)

```toml
# Cargo.toml (workspace)
[workspace.lints.clippy]
all = "warn"
pedantic = "warn"
# explicit allow-listed exceptions:
must_use_candidate = "allow"    # too noisy for handler returns
module_name_repetitions = "allow"
```

Run before every commit: `cargo clippy --workspace --all-features -- -D warnings`

---

## Testing

```rust
// Unit test with tokio
#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn memory_search_returns_top_k() {
        let mem = AgentMemory::new(384, 1000);
        let vec: Vec<f32> = (0..384).map(|i| i as f32 / 384.0).collect();
        mem.insert(0, &vec);
        let results = mem.search(&vec, 1, 50);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, 0);
    }
}
```

Run: `cargo nextest run --workspace`
