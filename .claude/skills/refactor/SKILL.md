---
name: refactor
description: Seahorse refactoring — safely restructure Rust/Python/FFI without breaking the hot path
---

# Seahorse — Refactor Skill

## Refactor Principles

1. **Tests first**: never refactor without tests covering the code being changed
2. **Compile at each step**: for Rust, `cargo check` after every meaningful change
3. **FFI boundary is the riskiest**: changes crossing Rust ↔ Python require both ends updated atomically
4. **Benchmark before+after** any hot-path refactor
5. **One concern per PR**: don't mix refactor with feature additions

---

## Rust Refactoring Patterns

### Extract Into Trait

When multiple types share behavior, extract a trait:

```rust
// Before: concrete type everywhere
pub struct HnswMemory { ... }
impl HnswMemory {
    pub fn search(&self, q: &[f32], k: usize) -> Vec<(usize, f32)> { ... }
}

// After: trait abstraction
pub trait MemoryBackend: Send + Sync {
    fn search(&self, query: &[f32], k: usize, ef: usize) -> Vec<(usize, f32)>;
    fn insert(&self, id: usize, embedding: &[f32]);
}

pub struct HnswMemory { ... }
impl MemoryBackend for HnswMemory { ... }

// Core uses trait object — swappable in tests
pub struct SeahorseCore {
    memory: Arc<dyn MemoryBackend>,
}
```

### Split Large Modules

```
// Before: crates/seahorse-core/src/lib.rs (500+ lines)

// After:
crates/seahorse-core/src/
  lib.rs          // re-exports only
  memory.rs       // AgentMemory + MemoryBackend
  scheduler.rs    // AgentScheduler, task queue
  sandbox.rs      // ToolSandbox (Wasmtime)
  error.rs        // CoreError
  config.rs       // Config struct + from_env()
```

```rust
// lib.rs after split
pub mod memory;
pub mod scheduler;
pub mod sandbox;
pub mod error;
pub mod config;

pub use memory::{AgentMemory, MemoryBackend};
pub use scheduler::AgentScheduler;
pub use error::CoreError;
pub use config::Config;
```

### Builder Pattern for Config

```rust
// Before: positional args, hard to extend
let core = SeahorseCore::new(16, 200, 100_000, 4);

// After: builder
let core = SeahorseCore::builder()
    .hnsw_m(16)
    .hnsw_ef_construction(200)
    .max_memory_elements(100_000)
    .worker_threads(4)
    .build()
    .await?;
```

---

## Python Refactoring Patterns

### Extract Service from Handler

```python
# Before: business logic in FastAPI handler
@router.post("/run")
async def run_agent(req: AgentRequest) -> AgentResponse:
    messages = [{"role": "user", "content": req.prompt}]
    response = await litellm.acompletion(model="gpt-4o", messages=messages)
    content = response.choices[0].message.content
    return AgentResponse(content=content, steps=1)

# After: logic in service, handler is thin
# seahorse_ai/planner.py
class ReActPlanner:
    async def run(self, request: AgentRequest) -> AgentResponse: ...

# seahorse_api/routers/agent.py
@router.post("/run")
async def run_agent(
    req: AgentRequest,
    planner: Annotated[ReActPlanner, Depends(get_planner)],
) -> AgentResponse:
    return await planner.run(req)
```

### Dependency Injection with FastAPI

```python
# seahorse_api/dependencies.py
from functools import lru_cache
from seahorse_ai.planner import ReActPlanner
from seahorse_ai.llm import LLMClient

@lru_cache(maxsize=1)
def get_llm() -> LLMClient:
    return LLMClient(config=LLMConfig())

@lru_cache(maxsize=1)
def get_planner() -> ReActPlanner:
    return ReActPlanner(llm=get_llm(), tools=get_tool_registry())
```

### Protocol-Based Abstraction

```python
# Before: concrete LLMClient type throughout
class ReActPlanner:
    def __init__(self, llm: LLMClient) -> None: ...

# After: Protocol — easily mockable in tests
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMBackend(Protocol):
    async def complete(self, messages: list[Message]) -> str: ...
    async def stream(self, messages: list[Message]) -> AsyncIterator[str]: ...

class ReActPlanner:
    def __init__(self, llm: LLMBackend) -> None: ...  # accepts any impl
```

---

## FFI Refactoring — Extra Care Required

When changing FFI signatures, both Rust and Python must be updated together:

```bash
# Step-by-step FFI breaking change
# 1. Add new function/signature alongside old (keep old)
# 2. Update Python callers to use new
# 3. Run: uv run maturin develop && uv run pytest python/
# 4. Remove old Rust function
# 5. uv run maturin develop && uv run pytest python/
# 6. cargo nextest run --workspace
```

**Never remove a PyO3-exported function without first verifying no Python code uses it:**

```bash
grep -r "from seahorse_ffi" python/ --include="*.py"
grep -r "import seahorse_ffi" python/ --include="*.py"
```

---

## Refactor Validation Checklist

- [ ] `cargo check` passes at each Rust change step
- [ ] `cargo nextest run --workspace` passes after full Rust refactor
- [ ] `uv run mypy python/ --strict` passes (type signatures kept correct)
- [ ] `uv run pytest python/ -q` passes (behavior unchanged)
- [ ] Benchmark run before+after for any hot-path change
- [ ] Public API documented with doc comments (`///` Rust, `"""` Python)
- [ ] Old code deleted — no commented-out dead code committed
