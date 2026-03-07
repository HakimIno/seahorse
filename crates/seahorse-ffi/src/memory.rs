use std::sync::Arc;

use pyo3::prelude::*;
use seahorse_core::AgentMemory;

/// Python-accessible wrapper around the Rust HNSW vector memory.
///
/// Usage:
///
/// ```python
/// from seahorse_ffi._core import PyAgentMemory
/// import numpy as np
///
/// mem = PyAgentMemory(dim=384, max_elements=100_000)
/// vec = np.random.rand(384).astype(np.float32)
/// mem.insert(0, vec.tobytes())
/// results = mem.search(vec.tobytes(), k=5)  # [(id, dist), ...]
/// ```
#[pyclass(name = "PyAgentMemory")]
pub struct PyAgentMemory {
    inner: Arc<AgentMemory>,
}

#[pymethods]
impl PyAgentMemory {
    /// Create a new HNSW index.
    ///
    /// Args:
    ///     dim: Embedding vector dimension (must match your embedding model).
    ///     max_elements: Pre-allocated capacity — no realloc on insert.
    ///     m: HNSW graph connectivity (default 16).
    ///     ef_construction: HNSW build quality (default 200).
    #[new]
    #[pyo3(signature = (dim, max_elements, m = 16, ef_construction = 200))]
    pub fn new(dim: usize, max_elements: usize, m: usize, ef_construction: usize) -> Self {
        Self {
            inner: Arc::new(AgentMemory::new(dim, max_elements, m, ef_construction)),
        }
    }

    /// Insert an embedding with text and metadata.
    pub fn insert(
        &self,
        py: Python<'_>,
        doc_id: usize,
        embedding: &[u8],
        text: String,
        metadata_json: String,
    ) {
        let emb: &[f32] = bytemuck::cast_slice(embedding);
        // Release GIL during HNSW insert
        py.allow_threads(|| self.inner.insert(doc_id, emb, text, metadata_json));
    }

    /// Search and return (doc_id, distance, text, metadata_json).
    #[pyo3(signature = (query, k, ef = 100))]
    pub fn search(
        &self,
        py: Python<'_>,
        query: &[u8],
        k: usize,
        ef: usize,
    ) -> Vec<(usize, f32, String, String)> {
        let q: &[f32] = bytemuck::cast_slice(query);
        py.allow_threads(|| self.inner.search(q, k, ef))
    }

    /// Remove a document (Soft Delete).
    pub fn remove(&self, py: Python<'_>, doc_id: usize) -> Option<(String, String)> {
        py.allow_threads(|| self.inner.remove(doc_id))
    }

    /// The embedding dimension of this index.
    #[getter]
    pub fn dim(&self) -> usize {
        self.inner.dim()
    }

    /// Save the HNSW index to a directory.
    pub fn save(&self, py: Python<'_>, path: &str) -> PyResult<()> {
        py.allow_threads(|| self.inner.save(path))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    /// Load a HNSW index from a directory.
    #[staticmethod]
    pub fn load(path: &str, dim: usize) -> PyResult<Self> {
        let inner = AgentMemory::load(path, dim)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))?;
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    pub fn __repr__(&self) -> String {
        format!("PyAgentMemory(dim={})", self.inner.dim())
    }
}

/// Zero-copy search function: accepts raw bytes, returns ``(id, distance)`` list.
///
/// This is the low-overhead variant — prefer it when calling from hot loops.
#[pyfunction]
#[pyo3(signature = (memory, query_bytes, k, ef = 100))]
pub fn search_memory(
    py: Python<'_>,
    memory: &PyAgentMemory,
    query_bytes: &[u8],
    k: usize,
    ef: usize,
) -> PyResult<Vec<(usize, f32, String, String)>> {
    let q: &[f32] = bytemuck::cast_slice(query_bytes);
    let results = py.allow_threads(|| memory.inner.search(q, k, ef));
    Ok(results)
}
