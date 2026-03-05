---
name: python-ai
description: Seahorse Python AI layer — LiteLLM, ReAct planner, RAG, tool registry, FastAPI
---

# Seahorse — Python AI Skill

## Scope

`python/seahorse_ai/` and `python/seahorse_api/` — the AI brain layer.
Python owns: LLM calls, planning loops, RAG pipeline, tool definitions, API serving.

---

## Project Setup

```toml
# pyproject.toml
[project]
name = "seahorse-ai"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "litellm>=1.35",
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.7",
    "anyio>=4.3",
    "opentelemetry-sdk>=1.24",
    "seahorse-ffi",  # built via maturin
]

[tool.uv]
dev-dependencies = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "mypy>=1.10",
    "ruff>=0.4",
]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "ANN", "ASYNC"]

[tool.mypy]
strict = true
python_version = "3.11"
```

```bash
# Install everything (dev mode)
uv sync

# Run
uv run uvicorn seahorse_api.main:app --reload

# Tests
uv run pytest python/ -q
uv run mypy python/ --strict
uv run ruff check python/
```

---

## Module Layout

```
python/
  seahorse_ai/
    __init__.py
    planner.py     # ReAct planning loop
    llm.py         # LiteLLM wrapper + retry
    rag.py         # embedding + FFI memory search
    tools/
      __init__.py  # ToolRegistry
      base.py      # @tool decorator + ToolSpec
      web.py       # web search tool
      code.py      # code execution tool (via Wasmtime sandbox)
    schemas.py     # Pydantic v2 models
  seahorse_api/
    main.py        # FastAPI app
    routers/
      agent.py
      memory.py
    middleware.py  # auth, rate-limit, OTEL
```

---

## Type Annotations — Strict Mypy

All code must pass `mypy --strict`. Key patterns:

```python
from __future__ import annotations
from typing import AsyncIterator, TypeVar, Generic, Protocol

# Always annotate return types, including None
async def run(self, prompt: str) -> AgentResponse: ...

# Use TypeVar for generics
T = TypeVar("T")

# Protocol for duck typing
class MemoryBackend(Protocol):
    async def search(self, query: list[float], k: int) -> list[MemoryResult]: ...

# Never use `Any` unless absolutely necessary (annotate with comment why)
```

---

## LLM Client (LiteLLM)

```python
# seahorse_ai/llm.py
from __future__ import annotations

import asyncio
from typing import AsyncIterator

import litellm
from pydantic import BaseModel

from seahorse_ai.schemas import LLMConfig, Message


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    async def complete(self, messages: list[Message]) -> str:
        response = await litellm.acompletion(
            model=self._config.model,   # "claude-3-5-sonnet", "gpt-4o", "gemini/..."
            messages=[m.model_dump() for m in messages],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )
        return response.choices[0].message.content  # type: ignore[union-attr]

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        response = await litellm.acompletion(
            model=self._config.model,
            messages=[m.model_dump() for m in messages],
            stream=True,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
```

**LiteLLM model strings**: `"claude-3-5-sonnet-20241022"`, `"gpt-4o"`, `"gemini/gemini-2.0-flash"`, `"ollama/llama3.1"`

---

## ReAct Planner

```python
# seahorse_ai/planner.py
from __future__ import annotations

import json
from typing import AsyncIterator

from seahorse_ai.llm import LLMClient
from seahorse_ai.tools import ToolRegistry
from seahorse_ai.schemas import AgentRequest, AgentResponse, Message


REACT_SYSTEM_PROMPT = """You are Seahorse Agent. Use ReAct format:
Thought: reason about what to do
Action: tool_name({"arg": "value"})
Observation: [tool result]
... repeat ...
Answer: final answer to user"""


class ReActPlanner:
    def __init__(self, llm: LLMClient, tools: ToolRegistry, max_steps: int = 10) -> None:
        self._llm = llm
        self._tools = tools
        self._max_steps = max_steps

    async def run(self, request: AgentRequest) -> AgentResponse:
        messages: list[Message] = [
            Message(role="system", content=REACT_SYSTEM_PROMPT),
            Message(role="user", content=request.prompt),
        ]

        for step in range(self._max_steps):
            response = await self._llm.complete(messages)
            messages.append(Message(role="assistant", content=response))

            if response.startswith("Answer:"):
                return AgentResponse(
                    content=response.removeprefix("Answer:").strip(),
                    steps=step + 1,
                )

            if "Action:" in response:
                observation = await self._execute_action(response)
                messages.append(Message(role="user", content=f"Observation: {observation}"))

        return AgentResponse(content="Max steps reached", steps=self._max_steps)

    async def _execute_action(self, response: str) -> str:
        # Parse "Action: tool_name({"key": "val"})"
        action_line = next(
            (l for l in response.splitlines() if l.startswith("Action:")), ""
        )
        tool_name, _, args_str = action_line.removeprefix("Action:").strip().partition("(")
        args = json.loads(args_str.rstrip(")"))
        return await self._tools.call(tool_name.strip(), args)
```

---

## Tool Registry

```python
# seahorse_ai/tools/base.py
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, TypeVar, overload

from pydantic import BaseModel


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


F = TypeVar("F", bound=Callable[..., Any])


def tool(description: str) -> Callable[[F], F]:
    """Decorator to register a function as an agent tool."""
    def decorator(fn: F) -> F:
        fn._tool_spec = ToolSpec(  # type: ignore[attr-defined]
            name=fn.__name__,
            description=description,
            parameters=_extract_schema(fn),
        )
        return fn
    return decorator


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[Callable[..., Any], ToolSpec]] = {}

    def register(self, fn: Callable[..., Any]) -> None:
        spec: ToolSpec = fn._tool_spec  # type: ignore[attr-defined]
        self._tools[spec.name] = (fn, spec)

    async def call(self, name: str, args: dict[str, Any]) -> str:
        if name not in self._tools:
            return f"Error: unknown tool '{name}'"
        fn, _ = self._tools[name]
        result = fn(**args)
        if inspect.isawaitable(result):
            result = await result
        return str(result)

    @property
    def specs(self) -> list[ToolSpec]:
        return [spec for _, spec in self._tools.values()]
```

---

## RAG Pipeline (FFI Memory Integration)

```python
# seahorse_ai/rag.py
from __future__ import annotations

import numpy as np
import litellm

from seahorse_ffi._core import PyAgentMemory  # Rust HNSW via PyO3


class RAGPipeline:
    def __init__(self, dim: int = 1536, max_docs: int = 100_000) -> None:
        # Rust HNSW — zero GC pause
        self._memory = PyAgentMemory(dim=dim, max_elements=max_docs)
        self._texts: dict[int, str] = {}
        self._next_id = 0

    async def add(self, text: str) -> int:
        embedding = await self._embed(text)
        doc_id = self._next_id
        # Zero-copy: numpy.tobytes() → Rust &[u8] → cast_slice → &[f32]
        self._memory.insert(doc_id, embedding.astype(np.float32).tobytes())
        self._texts[doc_id] = text
        self._next_id += 1
        return doc_id

    async def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        embedding = await self._embed(query)
        results = self._memory.search(embedding.astype(np.float32).tobytes(), k=k)
        return [(self._texts[doc_id], dist) for doc_id, dist in results]

    async def _embed(self, text: str) -> np.ndarray:
        response = await litellm.aembedding(
            model="text-embedding-3-small",
            input=text,
        )
        return np.array(response.data[0]["embedding"], dtype=np.float32)
```

---

## FastAPI App

```python
# seahorse_api/main.py
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from seahorse_api.routers import agent, memory


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown

app = FastAPI(title="Seahorse Agent API", version="0.1.0", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)

app.include_router(agent.router,  prefix="/v1/agent",  tags=["agent"])
app.include_router(memory.router, prefix="/v1/memory", tags=["memory"])
```

```python
# seahorse_api/routers/agent.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from seahorse_ai.schemas import AgentRequest, AgentResponse
from seahorse_ai.planner import ReActPlanner

router = APIRouter()

@router.post("/run", response_model=AgentResponse)
async def run_agent(request: AgentRequest) -> AgentResponse:
    planner = get_planner()  # injected via dependency
    return await planner.run(request)

@router.post("/stream")
async def stream_agent(request: AgentRequest) -> StreamingResponse:
    planner = get_planner()
    return StreamingResponse(
        planner.stream(request),
        media_type="text/event-stream",
    )
```

---

## Pydantic v2 Schemas

```python
# seahorse_ai/schemas.py
from __future__ import annotations
from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: str


class LLMConfig(BaseModel):
    model: str = "claude-3-5-sonnet-20241022"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=128_000)


class AgentRequest(BaseModel):
    prompt: str
    agent_id: str = "default"
    config: LLMConfig = Field(default_factory=LLMConfig)


class AgentResponse(BaseModel):
    content: str
    steps: int
    agent_id: str = "default"
```

Always use `model_dump()` / `model_validate()` — never `.dict()` / `.parse_obj()` (Pydantic v1 API).
