<div align="center">
  <img src="assets/logo-icon-rounded.png" alt="Seahorse Logo" width="160">
  <h1>Seahorse Agent</h1>
  <p><strong>The High-Performance, Real-Time Multi-Agent Orchestration Framework</strong></p>

  <p>
    <a href="https://www.rust-lang.org/"><img src="https://img.shields.io/badge/rust-v1.75+-orange.svg?style=for-the-badge&logo=rust&logoColor=white&labelColor=1a1a2e" alt="Rust"></a>
    <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-v3.11+-blue.svg?style=for-the-badge&logo=python&logoColor=white&labelColor=1a1a2e" alt="Python"></a>
    <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge&labelColor=1a1a2e" alt="License: MIT"></a>
  </p>

  <div style="width: 100%; height: 2px; margin: 20px 0; background: linear-gradient(90deg, transparent, #00d9ff, transparent);"></div>

  <a href="#-quick-start" style="text-decoration: none;">
    <img src="https://img.shields.io/badge/Quick%20Start-Get%20Started%20Now-00d9ff?style=for-the-badge&logo=rocket&logoColor=white&labelColor=1a1a2e">
  </a>
</div>

## Overview

Seahorse is a next-generation AI agent framework engineered for enterprise-grade performance, safety, and scalability. By bridging the raw speed of **Rust** with the rich intelligence of **Python**, Seahorse enables true parallel collaboration among agents in a real-time, event-driven architecture.

Unlike traditional hierarchical agents, Seahorse utilizes a high-performance Pub/Sub message bus to facilitate asynchronous swarm collaboration, eliminating blocking bottlenecks and maximizing throughput.

---

## Key Pillars

### Real-Time Swarm Orchestration

Move beyond synchronous delegation. Seahorse agents communicate over a **Rust-powered event-driven bus**, allowing scouts, commanders, and workers to collaborate in parallel.

- **Sub-ms Latency:** Native message routing with zero-copy communication.
- **Event-Driven:** Reactive architecture that responds to environment changes in real-time.

### Hybrid RAG & Long-Term Memory

Experience intelligence that never forgets. Seahorse integrates a dual-memory system for superior retrieval accuracy.

- **Vector Search (HNSW):** Blazing fast similarity search powered by Rust.
- **Knowledge Graph:** Capture complex relationships for deep contextual reasoning.

### Secure Tool Sandboxing

Deploy with confidence. Seahorse executes untrusted tool code within a **Wasmtime-sandboxed environment**, ensuring host isolation and memory safety.

---

## Technical Architecture

Seahorse leverages a hybrid stack designed for speed and flexibility. The system distinguishes between the high-level orchestration in Python and the performance-critical core in Rust.

<div align="center">
  <img src="assets/seahorse-architecture.png" alt="Seahorse Architecture" width="800">
  <p><i>Figure 1: High-level System Architecture</i></p>
</div>

### Multi-modal Knowledge Grounding

The pipeline supports sophisticated content parsing and graph-based grounding for diverse data types.

<div align="center">
  <img src="assets/ara.png" alt="RAG Pipeline" width="800">
  <p><i>Figure 2: Multi-modal RAG Pipeline Workflow</i></p>
</div>

---

## Quick Start

### Prerequisites

- **Rust** 1.75+
- **Python** 3.11+
- **uv** (Ultra-fast package manager)

### Installation

1. **Clone & Sync**

   ```bash
   git clone https://github.com/HakimIno/seahorse.git
   cd seahorse
   uv sync
   ```

2. **Build FFI Core**

   ```bash
   uv run maturin develop -m crates/seahorse-ffi/Cargo.toml
   ```

3. **Run Server**
   ```bash
   ./dev.sh
   ```

---

## Enterprise Verification

Seahorse maintains a rigorous testing standard across both layers:

- **Core Performance:** `cargo nextest run`
- **Intelligence Layer:** `uv run pytest python/tests/`

---

<div align="center">
  <p>Built for the next wave of autonomous agents.</p>
  <img src="https://img.shields.io/badge/Built%20With-Advanced%20Agentic%20AI-00d9ff?style=flat-square&labelColor=1a1a2e" alt="Built With">
</div>
