---
name: code-review
description: Seahorse code review — Rust safety, Python typing, FFI correctness, performance checks
---

# Seahorse — Code Review Skill

## Review Checklist

Before approving any PR, verify each layer:

---

## Rust Layer

### Safety & Correctness

- [ ] No `.unwrap()` or `.expect()` in `crates/` — use `?` or explicit match
- [ ] Error types use `thiserror`; no raw `String` errors in library code
- [ ] All `async fn` in hot path have `#[instrument]` for tracing
- [ ] No `std::thread::sleep` or `std::sync::Mutex` inside async context
- [ ] Shared state uses `Arc<RwLock<T>>` or `Arc<Mutex<T>>` — verify no deadlocks
- [ ] Tokio channels are bounded — no `unbounded_channel()` in hot path
- [ ] No `clone()` of large data structures in request path

### FFI Boundary (if touching `seahorse-ffi`)

- [ ] `py.allow_threads()` wraps all Rust compute > 10µs
- [ ] No JSON serialization on hot path — raw bytes or PyO3 objects only
- [ ] `bytemuck::cast_slice` for f32 array passing — no intermediate Vec
- [ ] GIL never held while waiting on a Rust `Mutex`/`RwLock`

### Performance

- [ ] New allocations in hot path are justified with a comment
- [ ] Criterion benchmark added for any new performance-critical function
- [ ] HNSW parameters (M, ef) are documented in code with tuning rationale

```rust
// ❌ Will block: uses std Mutex in async
let guard = std::sync::Mutex::new(data).lock().unwrap();

// ✅ Use tokio::sync::Mutex or RwLock for async contexts
let guard = tokio::sync::Mutex::new(data).lock().await;
```

---

## Python Layer

### Types — Strict Mypy Required

- [ ] All functions have full return type annotations (`-> None` included)
- [ ] No bare `Any` — if needed, add `# type: ignore[<code>]` with comment
- [ ] Pydantic models use v2 API: `model_dump()` not `.dict()`, `model_validate()` not `.parse_obj()`
- [ ] `from __future__ import annotations` at top of every file

```python
# ❌ Missing return type
def run(prompt: str):
    ...

# ✅ Explicit
async def run(prompt: str) -> AgentResponse:
    ...
```

### Async Correctness

- [ ] No `litellm.completion()` (sync) — always `litellm.acompletion()`
- [ ] No `time.sleep()` — use `asyncio.sleep()`
- [ ] No `requests.get()` — use `httpx.AsyncClient`
- [ ] Background tasks properly awaited or scheduled with `asyncio.create_task()`

```python
# ❌ Blocks the event loop
response = litellm.completion(model="gpt-4o", messages=msgs)

# ✅
response = await litellm.acompletion(model="gpt-4o", messages=msgs)
```

### LLM Usage

- [ ] Model string is a constant or config value — not hardcoded inline
- [ ] Retry logic present for LLM calls (or explicit comment why not needed)
- [ ] Token usage tracked and logged (`response.usage`)

---

## Architecture Compliance

- [ ] New CPU/IO hot paths go in Rust (`seahorse-core`), not Python
- [ ] New AI/LLM logic goes in Python (`seahorse_ai`), not Rust
- [ ] New HTTP routes added to `seahorse-router` not `seahorse_api` (Axum is the outer gateway)
- [ ] New tools implement the `@tool` decorator pattern and register in `ToolRegistry`
- [ ] New memory strategies extend `AgentMemory` in Rust, not Python

---

## Observability

- [ ] New Rust functions have `#[instrument]` with meaningful span fields
- [ ] New Python functions have `from opentelemetry import trace; tracer.start_as_current_span()`
- [ ] Error cases emit `error!()` / `logger.error()` with structured context (not just message)
- [ ] No `print()` in Python — use `logging` module or structlog

---

## Security

- [ ] No secrets in code — env vars via `std::env::var` (Rust) or `os.environ` (Python)
- [ ] Wasmtime sandbox used for any user-provided code execution — never `eval()` or `exec()`
- [ ] HTTP auth middleware applied to all routes that accept external input
- [ ] SQL queries (if any) use parameterized queries — no string interpolation

---

## Review Comments Template

Use structured comments:

```
🔴 BLOCK: <critical issue that must be fixed>
🟡 SUGGEST: <improvement worth considering>
🟢 NOTE: <info or praise, no action needed>
```

Examples:

```
🔴 BLOCK: `.unwrap()` on line 42 will panic in production if the channel is closed.
           Replace with `?` and propagate the error.

🟡 SUGGEST: this HNSW search is called with ef=200 on every request — consider lowering
            to ef=50 and only raising for explicit high-recall queries.

🟢 NOTE: nice use of `bytemuck::cast_slice` here — zero-copy as intended.
```
