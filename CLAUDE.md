# Seahorse Agent

High-Performance AI Agent Framework — Rust Core + Python Intelligence.

---

## Architecture

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

**Rust owns**: everything that must be < 1ms — routing, HNSW memory search, streaming, sandboxing.  
**Python owns**: all AI logic — LLM calls, ReAct planning, RAG, tool definitions.  
**PyO3 bridges**: zero-copy bytes (`bytemuck::cast_slice`), GIL always released during Rust compute.

---

## Directory Layout

```
seahorse/
├── Cargo.toml                    # Rust workspace (all 3 crates)
├── pyproject.toml                # Python package + maturin + uv + ruff/mypy/pytest
├── .cargo/config.toml            # Linker config (mold on Linux)
├── .claude/
│   ├── settings.json             # Project metadata
│   ├── hooks/                    # pre_task.sh, post_task.sh, pre_commit.sh
│   └── skills/                   # 9 SKILL.md files (architecture, rust-core, ffi-bridge, ...)
├── crates/
│   ├── seahorse-core/            # Tokio runtime, HNSW memory, AgentScheduler
│   ├── seahorse-router/          # Axum HTTP gateway, SSE streaming, AppError
│   └── seahorse-ffi/             # PyO3 bindings — PyAgentMemory, search_memory
├── python/
│   ├── seahorse_ai/              # LLM, ReAct planner, RAG pipeline, tool registry
│   ├── seahorse_api/             # FastAPI app + /v1/agent routes
│   ├── seahorse_ffi/             # Python stub wrapping the compiled Rust .so
│   └── tests/                    # pytest unit + integration tests
└── docs/
```

---

## Essential Commands

### Rust

```bash
cargo check --workspace                                    # fast type check
cargo build --workspace                                    # debug build
cargo build --release --workspace                         # production build
cargo nextest run --workspace                             # run all tests
cargo clippy --workspace --all-features -- -D warnings    # lint
cargo fmt --all                                           # format
cargo bench --bench memory_bench                          # benchmark HNSW
```

### Python

```bash
uv sync                                                   # install all deps
uv run maturin develop --features pyo3/extension-module   # build FFI .so
uv run uvicorn seahorse_api.main:app --reload             # dev server
uv run pytest python/ -q                                  # all tests
uv run pytest python/tests/test_ffi_memory.py -v         # FFI tests only
uv run ruff check python/                                 # lint
uv run ruff check python/ --fix                          # lint + autofix
uv run mypy python/ --strict                             # type check
```

### Full pre-commit gate

```bash
.claude/hooks/pre_commit.sh
```

---

## Key Design Decisions

| Decision      | Choice             | Why                                     |
| ------------- | ------------------ | --------------------------------------- |
| Async runtime | Tokio              | work-stealing, proven at scale          |
| HTTP          | Axum               | Tower ecosystem, type-safe extractors   |
| Vector DB     | HNSW (Rust native) | no GC pauses, tunable M/ef              |
| LLM           | LiteLLM            | one API → Claude / GPT / Gemini / local |
| Sandbox       | Wasmtime           | memory-safe tool execution              |
| FFI           | PyO3 + maturin     | zero-overhead, maintained by Rust team  |
| Linker        | mold (Linux)       | 5-10x faster incremental builds than ld |
| Python pkg    | uv                 | fast, deterministic, replaces pip+venv  |

---

## Coding Conventions

### Rust

- `thiserror` for library errors; `anyhow` for binary entrypoints only
- No `.unwrap()` in `crates/` — use `?` or explicit `match`
- `#[instrument]` on all public async functions
- Bounded Tokio channels only — no `unbounded_channel()` in hot paths
- `py.allow_threads()` wraps all Rust FFI work > 10µs

### Python

- `from __future__ import annotations` at top of every file
- Full return type annotations required (including `-> None`)
- `pydantic` v2 API: `model_dump()`, `model_validate()` — not `.dict()` / `.parse_obj()`
- Async everywhere: `litellm.acompletion()`, `asyncio.sleep()`, `httpx.AsyncClient`
- No `print()` — use `logging.getLogger(__name__)`

---

## Performance Targets

| Metric                  | Target    |
| ----------------------- | --------- |
| Agent routing latency   | < 1ms p99 |
| HNSW search (100k docs) | < 5ms     |
| FFI call overhead       | < 50µs    |
| LLM first token         | < 500ms   |
| Memory per Rust agent   | < 10MB    |

---

## Adding New Features

- **New CPU/IO hot path** → `seahorse-core` (Rust), expose in `seahorse-ffi`
- **New AI/LLM logic** → `seahorse_ai` (Python)
- **New HTTP endpoint** → `seahorse-router/src/handlers.rs` + `seahorse_api/routers/`
- **New tool** → `@tool` decorator in `seahorse_ai/tools/`, register in `SeahorseToolRegistry`
- **New memory strategy** → extend `AgentMemory` in `seahorse-core/src/memory.rs`

---

## Skills Reference

| Skill          | Path                                   | When to use                 |
| -------------- | -------------------------------------- | --------------------------- |
| `architecture` | `.claude/skills/architecture/SKILL.md` | system design decisions     |
| `rust-core`    | `.claude/skills/rust-core/SKILL.md`    | Tokio, Axum, HNSW, Wasmtime |
| `ffi-bridge`   | `.claude/skills/ffi-bridge/SKILL.md`   | PyO3, GIL, zero-copy        |
| `python-ai`    | `.claude/skills/python-ai/SKILL.md`    | LLM, ReAct, RAG, tools      |
| `performance`  | `.claude/skills/performance/SKILL.md`  | profiling, tuning           |
| `testing`      | `.claude/skills/testing/SKILL.md`      | nextest, pytest, coverage   |
| `code-review`  | `.claude/skills/code-review/SKILL.md`  | review checklist            |
| `release`      | `.claude/skills/release/SKILL.md`      | versioning, wheel, Docker   |
| `refactor`     | `.claude/skills/refactor/SKILL.md`     | safe restructuring          |
