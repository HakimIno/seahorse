---
name: architecture
description: Seahorse Agent system design — Rust Core + Python AI hybrid architecture
---

# Seahorse Agent — Architecture Skill

## What Is Seahorse?

**Seahorse** is a high-performance AI Agent framework with a hybrid Rust/Python architecture.

- **Rust Core** owns every hot path requiring < 1ms latency (routing, memory search, streaming, sandboxing)
- **Python AI Brain** owns all AI logic (LLM calls, planning, RAG, tool use, embeddings)
- **PyO3 FFI Bridge** connects the two with zero-copy data transfer

### Why Not Pure Python?

| Problem            | Cause             | Impact                      |
| ------------------ | ----------------- | --------------------------- |
| GIL                | Python design     | No true parallelism         |
| GC Pauses          | Garbage Collector | 10–100ms latency spikes     |
| Memory overhead    | Python runtime    | ~50MB+ per agent instance   |
| Slow vector search | numpy wrappers    | Memory retrieval bottleneck |

---

## Layered Architecture

```
┌─────────────────────────────────────────┐
│         Python AI Layer                  │
│  LLM · Planning · RAG · Tools · API      │
│  (LiteLLM, FastAPI, ReAct, embeddings)   │
├──────────────────────────────────────────┤
│         PyO3 FFI Bridge                  │
│  Zero-copy data transfer, GIL-aware      │
├──────────────────────────────────────────┤
│         Rust Core Layer                  │
│  Router · Memory · Sandbox · Streaming   │
│  (Tokio, Axum, HNSW, Wasmtime)           │
└──────────────────────────────────────────┘
```

---

## Crate Layout

```
crates/
  seahorse-core/      # Tokio runtime, agent scheduler, HNSW memory, task queue
  seahorse-router/    # Axum HTTP router, WebSocket streaming, auth middleware
  seahorse-ffi/       # PyO3 bindings, GIL lock management, zero-copy bridges
python/
  seahorse_ai/        # LLM clients, ReAct planner, RAG pipeline, tool registry
  seahorse_api/       # FastAPI app, Pydantic schemas, background tasks
```

---

## Canonical Data Flow

```
Client Request
     │
     ▼
[seahorse-router] ← Axum (Rust) — auth, rate-limit, parse
     │
     ▼
[seahorse-core]   ← scheduler assigns agent, retrieves HNSW memory context
     │  PyO3 FFI (zero-copy bytes)
     ▼
[seahorse_ai]     ← Python ReAct planner → LiteLLM → LLM API
     │  tool calls, embedding lookups
     ▼
[seahorse_ai]     ← tool results → synthesize final response
     │  PyO3 FFI
     ▼
[seahorse-core]   ← stream tokens via Tokio channel
     │
     ▼
[seahorse-router] ← SSE / WebSocket back to Client
```

---

## Architecture Principles

1. **GIL-aware crossing**: always release GIL in Rust before heavy CPU work; acquire only for Python object access
2. **Zero-copy on hot path**: pass `&[u8]` / `memoryview` across FFI — never clone large buffers
3. **Backpressure built-in**: Tokio bounded channels between router ↔ core ↔ ffi; reject fast not queue forever
4. **Async everywhere**: `tokio::spawn` in Rust, `asyncio`+`anyio` in Python; no blocking calls on event loop
5. **Observability first**: every span crosses the FFI boundary with OpenTelemetry trace propagation

---

## Design Decisions

| Decision        | Choice             | Rationale                                  |
| --------------- | ------------------ | ------------------------------------------ |
| Async runtime   | Tokio              | work-stealing, proven scale                |
| HTTP framework  | Axum               | Tower ecosystem, type-safe extractors      |
| Vector index    | HNSW (rust native) | no GC pauses, tunable M/ef                 |
| LLM abstraction | LiteLLM            | one interface → Claude/GPT/Gemini/local    |
| Sandbox         | Wasmtime           | memory-safe, deterministic execution       |
| FFI             | PyO3               | zero-overhead, maintained by Rust team     |
| Build           | maturin            | wheel + cargo in one command               |
| Linker          | mold               | 5-10x faster than ld on incremental builds |

---

## When Designing New Features

- **CPU/IO hot path** → implement in `seahorse-core` (Rust), expose via PyO3 in `seahorse-ffi`
- **AI logic / prompt engineering** → implement in `seahorse_ai` (Python)
- **New HTTP endpoint** → add route in `seahorse-router`, delegate to core or ffi
- **New tool** → add `@tool` decorated function in `seahorse_ai/tools/`, register in `ToolRegistry`
- **New memory strategy** → extend HNSW index wrapper in `seahorse-core/src/memory.rs`

---

## Performance Targets

| Metric                              | Target             |
| ----------------------------------- | ------------------ |
| Agent routing latency               | < 1ms p99          |
| Vector memory search (100k docs)    | < 5ms              |
| FFI call overhead                   | < 50µs             |
| LLM first-token latency (streaming) | < 500ms            |
| Memory per agent instance           | < 10MB (Rust only) |
| GC pause budget                     | 0ms (Rust layers)  |
