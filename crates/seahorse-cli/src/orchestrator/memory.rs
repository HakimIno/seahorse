//! Memory Persistence Manager
//!
//! Handles automatic save/load of HNSW index with versioning

use color_eyre::Result;
use std::path::PathBuf;
use std::sync::Arc;
use tracing::{info, debug};

/// Memory persistence manager
pub struct MemoryManager {
    index_dir: PathBuf,
    index_name: String,
    auto_save: bool,
}

impl MemoryManager {
    /// Create new memory manager
    pub fn new(base_dir: PathBuf) -> Self {
        let index_dir = base_dir.join(".seahorse");
        Self {
            index_dir,
            index_name: "index".to_string(),
            auto_save: true,
        }
    }



    /// Get the full index path (directory + basename)
    fn get_full_path(&self) -> PathBuf {
        self.index_dir.join(&self.index_name)
    }

    /// Save memory to disk
    pub fn save_memory(
        &self,
        memory: &Arc<seahorse_core::memory::AgentMemory>,
    ) -> Result<()> {
        if !self.auto_save {
            return Ok(());
        }

        // Create directory if it doesn't exist
        std::fs::create_dir_all(&self.index_dir)?;

        let path_str = self.get_full_path().to_string_lossy().to_string();
        memory.save(&path_str)
            .map_err(|e| color_eyre::eyre::eyre!("Failed to save memory: {}", e))?;

        info!("💾 Index saved to: {:?}", self.get_full_path());
        Ok(())
    }

    /// Load memory from disk
    pub fn load_memory(&self, dim: usize) -> Result<Arc<seahorse_core::memory::AgentMemory>> {
        if !self.index_exists() {
            debug!("📭 No existing index found, creating new one");
            return Ok(Arc::new(seahorse_core::memory::AgentMemory::new(
                dim,
                100_000,
                16,
                200,
            )));
        }

        let path_str = self.get_full_path().to_string_lossy().to_string();
        let memory = Arc::new(seahorse_core::memory::AgentMemory::load(&path_str, dim)
            .map_err(|e| color_eyre::eyre::eyre!("Failed to load memory: {}", e))?);

        info!("📂 Index loaded from: {:?}", self.get_full_path());
        info!("📊 Index contains {} items", memory.len());

        Ok(memory)
    }

    /// Check if index exists
    pub fn index_exists(&self) -> bool {
        // Check if any HNSW files exist
        let hnsw_data = self.index_dir.join(format!("{}.hnsw.data", self.index_name));
        let hnsw_graph = self.index_dir.join(format!("{}.hnsw.graph", self.index_name));
        let metadata = self.index_dir.join(format!("{}.metadata.json", self.index_name));

        hnsw_data.exists() || hnsw_graph.exists() || metadata.exists()
    }

    /// Get index info
    pub fn get_index_info(&self) -> Result<IndexInfo> {
        if !self.index_exists() {
            return Ok(IndexInfo {
                exists: false,
                items: 0,
                path: self.get_full_path(),
                modified: None,
            });
        }

        // Get modification time from the metadata file
        let metadata_path = self.index_dir.join(format!("{}.metadata.json", self.index_name));
        let modified = if metadata_path.exists() {
            let metadata = std::fs::metadata(&metadata_path)?;
            Some(
                metadata
                    .modified()?
                    .duration_since(std::time::UNIX_EPOCH)?
                    .as_secs()
            )
        } else {
            None
        };

        // Try to load and get item count
        let items = if self.index_exists() {
            // Create a temporary memory to get count
            let path_str = self.get_full_path().to_string_lossy().to_string();
            let memory = seahorse_core::memory::AgentMemory::load(&path_str, 384)
                .map_err(|e| color_eyre::eyre::eyre!("Failed to load memory: {}", e))?;
            memory.len()
        } else {
            0
        };

        Ok(IndexInfo {
            exists: true,
            items,
            path: self.get_full_path(),
            modified,
        })
    }

    /// Clear the index
    pub fn clear_index(&self) -> Result<()> {
        // Remove all index files
        let patterns = vec![
            format!("{}.hnsw.data", self.index_name),
            format!("{}.hnsw.graph", self.index_name),
            format!("{}.metadata.json", self.index_name),
            format!("{}.graph.json", self.index_name),
        ];

        for pattern in patterns {
            let file_path = self.index_dir.join(&pattern);
            if file_path.exists() {
                std::fs::remove_file(&file_path)?;
            }
        }

        info!("🗑️  Index cleared");
        Ok(())
    }
}

/// Index information
#[derive(Debug, Clone)]
pub struct IndexInfo {
    pub exists: bool,
    pub items: usize,
    pub path: PathBuf,
    pub modified: Option<u64>,
}
