mod io;
#[cfg(test)]
mod tests;
pub mod graph;
pub mod embedding;

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
    /// Uses a Two-Phase Search to fetch a wider net (k*5), apply penalty scores
    /// natively in Rust to avoid Top-K starvation in Python, and returns the true Top K.
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
        // Phase 1: Over-fetch
        let expanded_k = k * 5;
        let raw_results = index.search(query, expanded_k, ef);
        
        // Phase 2: Metadata-Aware Scoring
        let mut scored_results: Vec<(usize, f32, String, String)> = raw_results
            .into_iter()
            .filter_map(|n| {
                self.metadata.get(&n.d_id).map(|entry| {
                    let text = entry.0.clone();
                    let meta_str = entry.1.clone();
                    
                    let mut penalty = 0.0_f32;
                    if let Ok(meta_json) = serde_json::from_str::<serde_json::Value>(&meta_str) {
                         if let Some(p) = meta_json.get("penalty_score").and_then(|v| v.as_f64()) {
                             penalty = p as f32;
                         }
                    }
                    
                    let effective_dist = n.distance + penalty;
                    (n.d_id, effective_dist, text, meta_str)
                })
            })
            .collect();
            
        // Phase 3: Resort by effective distance (ascending)
        scored_results.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
        // Phase 4: Truncate to requested k
        scored_results.truncate(k);
        
        Ok(scored_results)
    }

    /// Remove a document from the metadata map (Soft Delete).
    /// The vector remains in HNSW but will be ignored by search.
    pub fn remove(&self, id: usize) -> Option<(String, String)> {
        self.metadata.remove(&id).map(|(_, v)| v)
    }

    /// Atomically update the JSON metadata for a specific document ID.
    /// Safely merges the new JSON fields into the existing JSON object natively.
    /// Returns true if the document existed and was updated, false otherwise.
    pub fn update_metadata(&self, id: usize, meta_json: String) -> bool {
        if let Some(mut entry) = self.metadata.get_mut(&id) {
            let old_str = entry.value().1.clone();
            
            // Try to merge JSON objects safely
            if let (Ok(mut old_val), Ok(new_val)) = (
                serde_json::from_str::<serde_json::Value>(&old_str),
                serde_json::from_str::<serde_json::Value>(&meta_json)
            ) {
                if let (Some(old_map), Some(new_map)) = (old_val.as_object_mut(), new_val.as_object()) {
                    for (k, v) in new_map {
                        old_map.insert(k.clone(), v.clone());
                    }
                    if let Ok(merged_str) = serde_json::to_string(&old_val) {
                        entry.value_mut().1 = merged_str;
                        return true;
                    }
                }
            }
            
            // Fallback: literal overwrite if not valid objects
            entry.value_mut().1 = meta_json;
            true
        } else {
            false
        }
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

