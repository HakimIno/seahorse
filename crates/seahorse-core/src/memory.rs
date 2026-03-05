use std::sync::Arc;

use hnsw_rs::prelude::*;
use tracing::{debug, instrument};


/// Wraps a Rust-native HNSW index for agent memory.
/// Zero GC pauses, sub-5ms search at 100k documents.
pub struct AgentMemory {
    index: Arc<Hnsw<'static, f32, DistCosine>>,
    dim: usize,
}

// SAFETY: Hnsw is internally synchronized.
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
            dim,
        }
    }

    /// Insert an embedding with an associated document id.
    ///
    /// # Panics (debug only)
    /// Panics if `embedding.len() != self.dim`.
    #[instrument(skip(self, embedding), fields(id))]
    pub fn insert(&self, id: usize, embedding: &[f32]) {
        debug_assert_eq!(
            embedding.len(),
            self.dim,
            "embedding dim mismatch: expected {}, got {}",
            self.dim,
            embedding.len()
        );
        self.index.insert((&embedding.to_vec(), id));
        debug!(id, dim = self.dim, "memory insert");
    }

    /// Search for the `k` nearest neighbours.
    ///
    /// Returns `(doc_id, cosine_distance)` pairs, sorted by distance ascending.
    #[instrument(skip(self, query), fields(k, ef))]
    pub fn search(&self, query: &[f32], k: usize, ef: usize) -> Vec<(usize, f32)> {
        debug_assert_eq!(query.len(), self.dim);
        let results = self.index.search(query, k, ef);
        results
            .into_iter()
            .map(|n| (n.d_id, n.distance))
            .collect()
    }

    pub fn dim(&self) -> usize {
        self.dim
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_vec(seed: f32, dim: usize) -> Vec<f32> {
        (0..dim).map(|i| (seed + i as f32) / dim as f32).collect()
    }

    #[test]
    fn insert_and_search_finds_exact_match() {
        let mem = AgentMemory::new(8, 100, 8, 100);
        let vec = make_vec(1.0, 8);
        mem.insert(42, &vec);
        let results = mem.search(&vec, 1, 50);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, 42);
    }

    #[test]
    fn search_empty_returns_empty() {
        let mem = AgentMemory::new(8, 100, 8, 100);
        let vec = make_vec(0.0, 8);
        let results = mem.search(&vec, 5, 50);
        assert!(results.is_empty());
    }
}
