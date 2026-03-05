## Seahorse Agent

Seahorse is a high-performance AI agent framework built with Rust and Python.
It combines the performance of Rust (Tokio async runtime, HNSW vector index) with the AI flexibility of Python (LiteLLM, ReAct planning loop).

## Architecture

Seahorse consists of three Rust crates:

- seahorse-core: Core data structures, HNSW memory, async task scheduler
- seahorse-ffi: PyO3 FFI bridge connecting Rust and Python
- seahorse-router: Axum HTTP server with SSE streaming endpoints

The Python layer (seahorse_ai) provides:

- ReActPlanner: A multi-step reasoning and action loop
- LLMClient: LiteLLM-backed language model interface
- RAGPipeline: Retrieval-augmented generation with Rust HNSW backend
- Built-in tools: web_search, python_interpreter, filesystem, memory

## API Endpoints

POST /v1/agent/run — Queue a task, returns {"task_id": "...", "status": "queued"}
POST /v1/agent/stream — Stream agent response via Server-Sent Events (SSE)
GET /healthz — Health check, returns {"status": "ok"}

## Tool Usage

The agent uses the ReAct format to call tools:

Thought: I need to search for current information.
Action: web_search({"query": "latest news"})
Observation: [search results]
Answer: Based on my research...

## Memory System

The agent has long-term memory backed by a Rust HNSW vector index.
Use memory_store to save important information and memory_search to retrieve it.
Memories persist across multiple turns within the same process.
