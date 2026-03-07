use dashmap::DashMap;
use hnsw_rs::hnswio::HnswIo;
use hnsw_rs::prelude::*;
use std::path::Path;
use std::sync::Arc;
use tracing::{debug, instrument};

/// Wraps a Rust-native HNSW index for agent memory.
/// Zero GC pauses, sub-5ms search at 100k documents.
pub struct AgentMemory {
    index: Arc<Hnsw<'static, f32, DistCosine>>,
    // Concurrent map for doc_id -> (text, json_metadata)
    metadata: Arc<DashMap<usize, (String, String)>>,
    dim: usize,
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

    /// Save the HNSW index and metadata to a directory.
    #[instrument(skip(self, path))]
    pub fn save(&self, path: &str) -> anyhow::Result<()> {
        let p = Path::new(path);
        let parent = p.parent().unwrap_or(p);
        let basename = p
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("seahorse_memory");

        // 1. Save HNSW graph
        self.index
            .file_dump(parent, basename)
            .map_err(|e| anyhow::anyhow!("HNSW save failed: {e}"))?;

        // 2. Save Metadata as JSON
        let meta_path = parent.join(format!("{}.metadata.json", basename));
        let meta_file = std::fs::File::create(meta_path)?;
        serde_json::to_writer(meta_file, &*self.metadata)?;

        debug!(path, "memory and metadata saved");
        Ok(())
    }

    /// Load the HNSW index and metadata from a directory.
    #[instrument(skip(path))]
    pub fn load(path: &str, dim: usize) -> anyhow::Result<Self> {
        let p = Path::new(path);
        let parent = p.parent().unwrap_or(p);
        let basename = p
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("seahorse_memory");

        let loader = HnswIo::new(parent, basename);
        let index: Hnsw<'_, f32, DistCosine> = loader
            .load_hnsw_with_dist(DistCosine)
            .map_err(|e| anyhow::anyhow!("HNSW load failed: {e}"))?;

        // SAFETY: The Hnsw index owns its data. Cast to 'static.
        let index_static: Hnsw<'static, f32, DistCosine> = unsafe { std::mem::transmute(index) };

        // Load Metadata
        let meta_path = parent.join(format!("{}.metadata.json", basename));
        let metadata = if meta_path.exists() {
            let file = std::fs::File::open(meta_path)?;
            serde_json::from_reader(file)?
        } else {
            DashMap::new()
        };

        Ok(Self {
            index: Arc::new(index_static),
            metadata: Arc::new(metadata),
            dim,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_vec(seed: f32, dim: usize) -> Vec<f32> {
        (0..dim).map(|i| (seed + i as f32) / dim as f32).collect()
    }

    #[test]
    fn insert_and_search_finds_exact_match_with_meta() {
        let mem = AgentMemory::new(8, 100, 8, 100);
        let vec = make_vec(1.0, 8);
        mem.insert(42, &vec, "hello world".to_string(), "{}".to_string());
        let results = mem.search(&vec, 1, 50);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, 42);
        assert_eq!(results[0].2, "hello world");
    }
}
