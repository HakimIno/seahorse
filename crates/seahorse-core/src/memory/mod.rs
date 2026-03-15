mod io;
#[cfg(test)]
mod tests;
pub mod graph;

use dashmap::DashMap;
use hnsw_rs::prelude::*;
use std::sync::Arc;
use tracing::{debug, instrument};

/// Wraps a Rust-native HNSW index for agent memory.
/// Zero GC pauses, sub-5ms search at 100k documents.
pub struct AgentMemory {
    pub(crate) index: Arc<std::sync::RwLock<Hnsw<'static, f32, DistCosine>>>,
    // SAFETY: keep the loader alive so the index's borrows remain valid
    pub(crate) _loader: Option<hnsw_rs::hnswio::HnswIo>,
    // Concurrent map for doc_id -> (text, json_metadata)
    pub(crate) metadata: Arc<DashMap<usize, (String, String)>>,
    // Concurrent Directed Knowledge Graph
    pub graph: Arc<std::sync::RwLock<graph::KnowledgeGraph>>,
    pub(crate) dim: usize,
}

// AgentMemory is now safely Send + Sync.

impl AgentMemory {
    /// Create a new HNSW index.
    ///
    /// # Parameters
    /// - `dim`: embedding vector dimension
    /// - `max_elements`: pre-allocated capacity (no realloc on insert)
    /// - `m`: graph connectivity (8–32, default 16)
    /// - `ef_construction`: build quality (100–500, default 200)
    pub fn new(dim: usize, max_elements: usize, m: usize, ef_construction: usize) -> Self {
        let index = Hnsw::new(m, max_elements, 16, ef_construction, DistCosine);
        Self {
            index: Arc::new(std::sync::RwLock::new(index)),
            _loader: None,
            metadata: Arc::new(DashMap::new()),
            graph: Arc::new(std::sync::RwLock::new(graph::KnowledgeGraph::new())),
            dim,
        }
    }

    /// Insert an embedding with associated text and metadata.
    #[instrument(skip(self, embedding, text, meta), fields(id))]
    pub fn insert(&self, id: usize, embedding: &[f32], text: String, meta: String) -> crate::error::CoreResult<()> {
        if embedding.len() != self.dim {
            return Err(crate::error::CoreError::Memory(format!(
                "embedding dim mismatch: expected {}, got {}",
                self.dim,
                embedding.len()
            )));
        }
        let index = self.index.write().expect("HNSW lock poisoned");
        // NOTE: .to_vec() is an allocation hot spot, but required by hnsw_rs::Hnsw::insert API
        index.insert((&embedding.to_vec(), id));
        self.metadata.insert(id, (text, meta));
        debug!(id, dim = self.dim, "memory insert including metadata");
        Ok(())
    }

    /// Search for the `k` nearest neighbours.
    ///
    /// Returns `(doc_id, distance, text, metadata)` tuples.
    #[instrument(skip(self, query), fields(k, ef))]
    pub fn search(&self, query: &[f32], k: usize, ef: usize) -> crate::error::CoreResult<Vec<(usize, f32, String, String)>> {
        if query.len() != self.dim {
            return Err(crate::error::CoreError::Memory(format!(
                "query dim mismatch: expected {}, got {}",
                self.dim,
                query.len()
            )));
        }
        let index = self.index.read().expect("HNSW lock poisoned");
        let results = index.search(query, k, ef);
        Ok(results
            .into_iter()
            .filter_map(|n| {
                self.metadata.get(&n.d_id).map(|entry| {
                    (n.d_id, n.distance, entry.0.clone(), entry.1.clone())
                })
            })
            .collect())
    }

    /// Remove a document from the metadata map (Soft Delete).
    /// The vector remains in HNSW but will be ignored by search.
    pub fn remove(&self, id: usize) -> Option<(String, String)> {
        self.metadata.remove(&id).map(|(_, v)| v)
    }

    pub fn dim(&self) -> usize {
        self.dim
    }

    pub fn len(&self) -> usize {
        self.metadata.len()
    }

    pub fn is_empty(&self) -> bool {
        self.metadata.is_empty()
    }
}
