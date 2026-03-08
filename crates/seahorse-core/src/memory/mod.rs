mod io;
#[cfg(test)]
mod tests;

use dashmap::DashMap;
use hnsw_rs::prelude::*;
use std::sync::Arc;
use tracing::{debug, instrument};

/// Wraps a Rust-native HNSW index for agent memory.
/// Zero GC pauses, sub-5ms search at 100k documents.
pub struct AgentMemory {
    pub(crate) index: Arc<Hnsw<'static, f32, DistCosine>>,
    // Concurrent map for doc_id -> (text, json_metadata)
    pub(crate) metadata: Arc<DashMap<usize, (String, String)>>,
    pub(crate) dim: usize,
}

// SAFETY: Hnsw and DashMap are internally synchronized.
unsafe impl Send for AgentMemory {}
unsafe impl Sync for AgentMemory {}

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
            index: Arc::new(index),
            metadata: Arc::new(DashMap::new()),
            dim,
        }
    }

    /// Insert an embedding with associated text and metadata.
    ///
    /// # Panics (debug only)
    /// Panics if `embedding.len() != self.dim`.
    #[instrument(skip(self, embedding, text, meta), fields(id))]
    pub fn insert(&self, id: usize, embedding: &[f32], text: String, meta: String) {
        debug_assert_eq!(
            embedding.len(),
            self.dim,
            "embedding dim mismatch: expected {}, got {}",
            self.dim,
            embedding.len()
        );
        self.index.insert((&embedding.to_vec(), id));
        self.metadata.insert(id, (text, meta));
        debug!(id, dim = self.dim, "memory insert including metadata");
    }

    /// Search for the `k` nearest neighbours.
    ///
    /// Returns `(doc_id, distance, text, metadata)` tuples.
    #[instrument(skip(self, query), fields(k, ef))]
    pub fn search(&self, query: &[f32], k: usize, ef: usize) -> Vec<(usize, f32, String, String)> {
        debug_assert_eq!(query.len(), self.dim);
        let results = self.index.search(query, k, ef);
        results
            .into_iter()
            .filter_map(|n| {
                self.metadata.get(&n.d_id).map(|entry| {
                    (n.d_id, n.distance, entry.0.clone(), entry.1.clone())
                })
            })
            .collect()
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
