use super::AgentMemory;
use dashmap::DashMap;
use hnsw_rs::hnswio::HnswIo;
use hnsw_rs::prelude::*;
use std::path::Path;
use std::sync::Arc;
use tracing::{debug, instrument};

impl AgentMemory {
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
