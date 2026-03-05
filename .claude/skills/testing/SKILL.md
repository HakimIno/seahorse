---
name: testing
description: Seahorse testing strategy — cargo-nextest, pytest-asyncio, integration tests, coverage
---

# Seahorse — Testing Skill

## Testing Stack

| Layer                   | Tool             | Command                                   |
| ----------------------- | ---------------- | ----------------------------------------- |
| Rust unit + integration | cargo-nextest    | `cargo nextest run --workspace`           |
| Rust benchmarks         | criterion        | `cargo bench`                             |
| Python unit + async     | pytest-asyncio   | `uv run pytest python/ -q`                |
| Python type checking    | mypy strict      | `uv run mypy python/ --strict`            |
| Python lint             | ruff             | `uv run ruff check python/`               |
| FFI integration         | pytest + maturin | `uv run maturin develop && uv run pytest` |
| Full pre-commit gate    | pre_commit.sh    | `.claude/hooks/pre_commit.sh`             |

---

## Rust: cargo-nextest Setup

```toml
# .config/nextest.toml
[profile.default]
retries = 1
test-threads = "num-cpus"
fail-fast = false

[profile.ci]
retries = 2
fail-fast = true
```

```bash
# Install once
cargo install cargo-nextest

# Run all tests
cargo nextest run --workspace

# Run specific crate
cargo nextest run -p seahorse-core

# Run with output on failure
cargo nextest run --workspace --no-capture

# Run and get JUnit XML (CI)
cargo nextest run --workspace --profile ci --reporter junit > results.xml
```

---

## Rust: Test Patterns

```rust
// ✅ Unit test with async
#[cfg(test)]
mod tests {
    use super::*;
    use tokio::test;

    #[tokio::test]
    async fn agent_runs_single_step() {
        let core = SeahorseCore::new_test().await.unwrap();
        let req = AgentRequest { prompt: "say hello".into(), ..Default::default() };
        let resp = core.run(req).await.unwrap();
        assert!(!resp.content.is_empty());
    }

    // ✅ Test error path explicitly
    #[tokio::test]
    async fn memory_search_empty_returns_none() {
        let mem = AgentMemory::new(384, 1000);
        let query = vec![0.0f32; 384];
        let results = mem.search(&query, 5, 50);
        assert!(results.is_empty());
    }
}
```

```rust
// ✅ Integration test (tests/ directory, compiled as separate binary)
// crates/seahorse-router/tests/api_test.rs
use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::ServiceExt;

#[tokio::test]
async fn health_endpoint_returns_200() {
    let app = build_router(Arc::new(SeahorseCore::new_test().await.unwrap()));
    let req = Request::builder().uri("/health").body(Body::empty()).unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
}
```

---

## Python: pytest-asyncio Setup

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"  # all async tests auto-detected
testpaths = ["python"]
addopts = "-q --tb=short"

[tool.pytest.ini_options.markers]
integration = "integration tests (slow, require external services)"
unit = "pure unit tests (fast, no I/O)"
```

---

## Python: Test Patterns

```python
# python/tests/test_planner.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from seahorse_ai.planner import ReActPlanner
from seahorse_ai.schemas import AgentRequest, LLMConfig


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.complete.return_value = "Answer: Hello, World!"
    return llm


@pytest.fixture
def mock_tools() -> MagicMock:
    tools = MagicMock()
    tools.call = AsyncMock(return_value="tool result")
    return tools


@pytest.mark.asyncio
async def test_planner_returns_answer_on_first_step(
    mock_llm: AsyncMock,
    mock_tools: MagicMock,
) -> None:
    planner = ReActPlanner(llm=mock_llm, tools=mock_tools, max_steps=10)
    req = AgentRequest(prompt="What is 2+2?")
    resp = await planner.run(req)
    assert resp.content == "Hello, World!"
    assert resp.steps == 1


@pytest.mark.asyncio
async def test_planner_calls_tool_when_action_present(
    mock_llm: AsyncMock,
    mock_tools: MagicMock,
) -> None:
    mock_llm.complete.side_effect = [
        'Thought: I need to search\nAction: web_search({"query": "test"})',
        "Answer: Found it",
    ]
    planner = ReActPlanner(llm=mock_llm, tools=mock_tools, max_steps=10)
    resp = await planner.run(AgentRequest(prompt="Search for something"))
    mock_tools.call.assert_awaited_once()
    assert resp.steps == 2
```

---

## Python: FFI Integration Tests

```python
# python/tests/test_ffi_memory.py
"""Integration tests — requires maturin build first."""
from __future__ import annotations

import numpy as np
import pytest

# Skip all if seahorse_ffi not built
pytest.importorskip("seahorse_ffi")
from seahorse_ffi._core import PyAgentMemory


def make_embedding(seed: int, dim: int = 384) -> bytes:
    rng = np.random.default_rng(seed)
    vec = rng.random(dim).astype(np.float32)
    return vec.tobytes()


def test_insert_and_search_returns_correct_id() -> None:
    mem = PyAgentMemory(dim=384, max_elements=100)
    mem.insert(42, make_embedding(seed=42))
    results = mem.search(make_embedding(seed=42), k=1)
    assert len(results) == 1
    assert results[0][0] == 42


def test_search_empty_index_returns_nothing() -> None:
    mem = PyAgentMemory(dim=384, max_elements=100)
    results = mem.search(make_embedding(seed=0), k=5)
    assert results == []
```

Run:

```bash
uv run maturin develop  # build .so first
uv run pytest python/tests/test_ffi_memory.py -v
```

---

## FastAPI Integration Tests

```python
# python/tests/test_api.py
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from seahorse_api.main import app


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_run_agent_returns_200(client: AsyncClient) -> None:
    resp = await client.post("/v1/agent/run", json={"prompt": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert "content" in data
```

---

## Coverage

```bash
# Rust coverage (llvm-cov)
cargo install cargo-llvm-cov
cargo llvm-cov --workspace --html

# Python coverage
uv run pytest python/ --cov=python --cov-report=html
open htmlcov/index.html
```

**Coverage targets:**

- Rust core logic: ≥ 80%
- Python AI logic: ≥ 85%
- FFI boundary: ≥ 70% (hard to mock, supplement with integration tests)

---

## CI Fast-Fail Order

Run in this order (fastest → slowest):

```
1. cargo fmt --all -- --check        (~1s)
2. cargo clippy -- -D warnings       (~10s)
3. cargo nextest run --workspace     (~30s)
4. uv run ruff check python/         (~2s)
5. uv run mypy python/ --strict      (~15s)
6. uv run pytest python/ -q          (~20s)
7. cargo bench (optional, main only) (~5min)
```
