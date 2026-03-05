---
name: ffi-bridge
description: PyO3 + maturin FFI bridge — zero-copy data transfer between Rust Core and Python AI
---

# Seahorse — FFI Bridge Skill

## Scope

`crates/seahorse-ffi/` — PyO3 bindings that expose Rust Core to Python AI layer.
This is the **performance-critical boundary**. Every decision here affects end-to-end latency.

---

## Core Principle: Zero-Copy on Hot Path

```
Rust ──[&[u8] / memoryview]──► Python   ✅ zero-copy
Rust ──[Vec<u8> → PyBytes]───► Python   ⚠️  one allocation, acceptable
Rust ──[serde JSON string]───► Python   ❌ never on hot path
```

**Rule**: never serialize to JSON across the FFI boundary for hot-path data (embeddings, token streams, memory results). Use raw bytes + `memoryview` or pass structured PyO3 objects directly.

---

## Project Setup

```toml
# crates/seahorse-ffi/Cargo.toml
[package]
name = "seahorse-ffi"
version = "0.1.0"
edition = "2021"

[lib]
name = "seahorse_ffi"
crate-type = ["cdylib"]

[dependencies]
pyo3   = { version = "0.21", features = ["extension-module", "abi3-py311"] }
seahorse-core = { path = "../seahorse-core" }
tokio  = { version = "1", features = ["full"] }

[features]
extension-module = ["pyo3/extension-module"]
```

```toml
# pyproject.toml (workspace root)
[build-system]
requires = ["maturin>=1.5,<2.0"]
build-backend = "maturin"

[tool.maturin]
features = ["pyo3/extension-module"]
python-source = "python"
module-name = "seahorse_ffi._core"
```

---

## GIL Management — Critical Rules

```rust
use pyo3::prelude::*;
use pyo3::types::PyBytes;

// ✅ CORRECT: Release GIL for heavy Rust work
#[pyfunction]
fn memory_search(py: Python<'_>, query: &[u8], k: usize) -> PyResult<Vec<(usize, f32)>> {
    // Release GIL while Rust does HNSW search
    py.allow_threads(|| {
        let core = get_core();
        let embedding = bytemuck::cast_slice(query);
        core.memory().search(embedding, k, 50)
    })
    .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

// ❌ WRONG: holding GIL during Rust compute
#[pyfunction]
fn memory_search_bad(query: &[u8], k: usize) -> PyResult<Vec<(usize, f32)>> {
    let core = get_core();  // GIL held the whole time — blocks all Python threads
    let embedding = bytemuck::cast_slice(query);
    core.memory().search(embedding, k, 50)
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}
```

**GIL rules:**

1. Always call `py.allow_threads()` for any Rust work > ~10µs
2. Acquire GIL with `Python::with_gil()` only at FFI boundary, not deep in Rust
3. Never hold both GIL and a `Mutex` — deadlock risk

---

## Zero-Copy Bytes Transfer

```rust
/// Embedding search: Python sends f32 array as bytes, Rust returns bytes
#[pyfunction]
fn search_memory<'py>(
    py: Python<'py>,
    query_bytes: &[u8],   // memoryview from Python — zero copy
    k: usize,
    ef: usize,
) -> PyResult<Bound<'py, PyBytes>> {
    let query: &[f32] = bytemuck::cast_slice(query_bytes);

    let results: Vec<(usize, f32)> = py.allow_threads(|| {
        GLOBAL_CORE.memory().search(query, k, ef)
    })?;

    // Serialize result struct as bytes — one allocation
    let result_bytes: Vec<u8> = bytemuck::cast_slice(&results).to_vec();
    Ok(PyBytes::new(py, &result_bytes))
}
```

Python side:

```python
import numpy as np
from seahorse_ffi._core import search_memory

query = np.array([0.1, 0.2, ...], dtype=np.float32)
# .tobytes() is zero-copy memoryview
raw = search_memory(query.tobytes(), k=10, ef=100)
results = np.frombuffer(raw, dtype=np.dtype([('id', np.uint64), ('dist', np.float32)]))
```

---

## PyO3 Class Bindings

```rust
use pyo3::prelude::*;
use std::sync::Arc;
use seahorse_core::AgentMemory;

#[pyclass]
pub struct PyAgentMemory {
    inner: Arc<AgentMemory>,
}

#[pymethods]
impl PyAgentMemory {
    #[new]
    fn new(dim: usize, max_elements: usize) -> Self {
        Self {
            inner: Arc::new(AgentMemory::new(dim, max_elements)),
        }
    }

    fn insert(&self, py: Python<'_>, id: usize, embedding: &[u8]) {
        let emb: &[f32] = bytemuck::cast_slice(embedding);
        py.allow_threads(|| self.inner.insert(id, emb));
    }

    fn search(&self, py: Python<'_>, query: &[u8], k: usize) -> Vec<(usize, f32)> {
        let q: &[f32] = bytemuck::cast_slice(query);
        py.allow_threads(|| self.inner.search(q, k, 50))
    }
}
```

---

## Async FFI (Tokio ↔ asyncio)

For async bridging, use a shared Tokio runtime in Rust and call it from Python:

```rust
use once_cell::sync::Lazy;
use tokio::runtime::Runtime;

static RUNTIME: Lazy<Runtime> = Lazy::new(|| {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(4)
        .enable_all()
        .build()
        .expect("tokio runtime")
});

#[pyfunction]
fn run_agent_sync(py: Python<'_>, request_json: &str) -> PyResult<String> {
    let request: AgentRequest = serde_json::from_str(request_json)
        .map_err(|e| PyValueError::new_err(e.to_string()))?;

    py.allow_threads(|| {
        RUNTIME.block_on(async { GLOBAL_CORE.run(request).await })
    })
    .map(|r| serde_json::to_string(&r).unwrap())
    .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}
```

For true async Python ↔ Rust, use `pyo3-asyncio` or run Tokio + asyncio in separate threads with a shared `mpsc` queue.

---

## Module Registration

```rust
// crates/seahorse-ffi/src/lib.rs
use pyo3::prelude::*;

mod memory;
mod agent;

#[pymodule]
fn _core(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<memory::PyAgentMemory>()?;
    m.add_class::<agent::PyAgentCore>()?;
    m.add_function(wrap_pyfunction!(memory::search_memory, m)?)?;
    m.add_function(wrap_pyfunction!(agent::run_agent_sync, m)?)?;
    Ok(())
}
```

---

## Build & Dev Workflow

```bash
# Dev install (editable, no wheel)
uv run maturin develop --features pyo3/extension-module

# Build release wheel
uv run maturin build --release

# Test from Python immediately after change
uv run python -c "from seahorse_ffi._core import PyAgentMemory; print('ok')"
```

---

## Error Conversion Pattern

Always convert Rust errors to typed Python exceptions:

```rust
// Define once per crate
pyo3::create_exception!(seahorse_ffi, SeahorseError, pyo3::exceptions::PyException);
pyo3::create_exception!(seahorse_ffi, MemoryError,   pyo3::exceptions::PyException);

// Use in functions
fn my_fn() -> PyResult<()> {
    do_thing().map_err(|e| SeahorseError::new_err(e.to_string()))
}
```

Python side catches typed: `except SeahorseError as e: ...`

---

## FFI Performance Checklist

- [ ] `py.allow_threads()` wraps all Rust work > 10µs
- [ ] No `serde_json` on hot path — use raw bytes or PyO3 objects
- [ ] `bytemuck::cast_slice` for f32 arrays (zero-copy)
- [ ] `Arc<T>` for shared core — no clone
- [ ] Single global Tokio runtime via `once_cell::Lazy`
- [ ] `abi3-py311` feature set — works with Python 3.11+
