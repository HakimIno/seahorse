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
    ) -> PyResult<()> {
        let emb: &[f32] = bytemuck::try_cast_slice(embedding).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "embedding alignment error: {e}"
            ))
        })?;
        // Release GIL during HNSW insert
        py.allow_threads(|| self.inner.insert(doc_id, emb, text, metadata_json))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))?;
        Ok(())
    }

    /// Search and return (doc_id, distance, text, metadata_json).
    #[pyo3(signature = (query, k, ef = 100))]
    pub fn search(
        &self,
        py: Python<'_>,
        query: &[u8],
        k: usize,
        ef: usize,
    ) -> PyResult<Vec<(usize, f32, String, String)>> {
        let q: &[f32] = bytemuck::try_cast_slice(query).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "query alignment error: {e}"
            ))
        })?;
        let results = py.allow_threads(|| self.inner.search(q, k, ef))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))?;
        Ok(results)
    }

    /// Remove a document (Soft Delete).
    pub fn remove(&self, py: Python<'_>, doc_id: usize) -> Option<(String, String)> {
        py.allow_threads(|| self.inner.remove(doc_id))
    }

    #[getter]
    pub fn dim(&self) -> usize {
        self.inner.dim()
    }

    #[getter]
    pub fn size(&self) -> usize {
        self.inner.len()
    }

    /// The number of elements inside the index.
    pub fn count(&self) -> usize {
        self.inner.len()
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

    /// Add a Node to the Knowledge Graph
    pub fn add_node(&self, id: String, label: String, doc_id: Option<usize>) -> PyResult<()> {
        let mut graph = self.inner.graph.write().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Graph Lock Error: {e}"))
        })?;
        graph.add_node(id, label, doc_id);
        Ok(())
    }

    /// Add an Edge to the Knowledge Graph
    pub fn add_edge(&self, source: String, target: String, predicate: String, weight: f32) -> PyResult<()> {
        let mut graph = self.inner.graph.write().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Graph Lock Error: {e}"))
        })?;
        graph.add_edge(source, target, predicate, weight);
        Ok(())
    }

    /// Get outgoing edges from a specific node
    pub fn get_outgoing_edges(&self, source_id: &str) -> PyResult<Vec<(String, String, f32)>> {
        let graph = self.inner.graph.read().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Graph Lock Error: {e}"))
        })?;
        let edges = graph.get_outgoing_edges(source_id);
        let result = edges.into_iter().map(|e| (e.target.clone(), e.predicate.clone(), e.weight)).collect();
        Ok(result)
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
    let q: &[f32] = bytemuck::try_cast_slice(query_bytes).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
            "query alignment error: {e}"
        ))
    })?;
    let results = py.allow_threads(|| memory.inner.search(q, k, ef))
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))?;
    Ok(results)
}
