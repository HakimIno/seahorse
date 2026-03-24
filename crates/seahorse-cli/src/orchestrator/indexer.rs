//! Parallel Codebase Indexer
//!
//! Ultra-fast indexing using:
//! - Parallel file parsing (Rayon)
//! - AST metadata extraction
//! - Python embeddings generation
//! - HNSW memory storage

use color_eyre::Result;
use rayon::prelude::*;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use tracing::{info, instrument};
use std::time::Instant;

/// Indexing statistics
#[derive(Debug, Clone)]
pub struct IndexStats {
    pub files_scanned: usize,
    pub files_indexed: usize,
    pub files_failed: usize,
    pub indexing_time_secs: f64,
    pub files_per_second: f64,
}

/// File metadata for indexing
#[derive(Debug, Clone)]
pub struct FileMetadata {
    pub path: PathBuf,
    pub language: String,
}

/// Code chunk for embedding
#[derive(Debug, Clone)]
pub struct CodeChunk {
    pub id: usize,
    pub file_path: PathBuf,
    pub language: String,
    pub chunk_type: String,  // "function", "class", "module", "snippet"
    pub name: String,
    pub code: String,
    pub line_start: usize,
    pub line_end: usize,
}

/// Parallel indexer
pub struct ParallelIndexer {
    memory: Arc<seahorse_core::memory::AgentMemory>,
}


impl ParallelIndexer {
    /// Create new parallel indexer
    pub fn new(memory: Arc<seahorse_core::memory::AgentMemory>) -> Self {
        Self {
            memory,
        }
    }

    /// Index a project directory
    #[instrument(skip(self, path))]
    pub async fn index_project(
        &self,
        path: PathBuf,
        force: bool,
        num_threads: Option<usize>,
    ) -> Result<IndexStats> {
        let start = Instant::now();

        info!("🔍 Starting index of: {:?}", path);
        info!("🔄 Force re-index: {}", force);

        // Configure thread pool
        let thread_count = num_threads.unwrap_or_else(|| {
            std::thread::available_parallelism()
                .map(|n| n.get())
                .unwrap_or(4)
        });

        info!("🧵 Using {} threads", thread_count);

        // Step 1: Scan all source files
        let files = self.scan_source_files(&path)?;
        let files_count = files.len();
        info!("📁 Found {} source files", files_count);

        // Step 2: Parse files in parallel
        let parsed_files = self.parse_files_parallel(files, thread_count)?;
        info!("✅ Parsed {} files successfully", parsed_files.len());

        // Step 3: Extract code chunks
        let chunks = self.extract_code_chunks(parsed_files)?;
        info!("📦 Extracted {} code chunks", chunks.len());

        // Step 4: Generate embeddings and store
        let indexed_count = self.index_chunks(chunks).await?;
        info!("💾 Indexed {} chunks", indexed_count);

        let elapsed = start.elapsed().as_secs_f64();
        let files_per_sec = files_count as f64 / elapsed;

        let stats = IndexStats {
            files_scanned: files_count,
            files_indexed: indexed_count,
            files_failed: files_count - indexed_count,
            indexing_time_secs: elapsed,
            files_per_second: files_per_sec,
        };

        info!("✨ Indexing complete in {:.2}s ({:.1} files/sec)", elapsed, files_per_sec);

        Ok(stats)
    }

    /// Scan directory for source files
    fn scan_source_files(&self, path: &Path) -> Result<Vec<PathBuf>> {
        let mut files = Vec::new();

        let extensions = vec![
            "py", "pyi",      // Python
            "rs",             // Rust
            "js", "ts", "jsx", "tsx",  // JavaScript/TypeScript
            "go",             // Go
            "java",           // Java
            "cpp", "cc", "cxx", "hpp", "h",  // C/C++
        ];

        walkdir::WalkDir::new(path)
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().is_file())
            .filter(|e| {
                e.path()
                    .extension()
                    .and_then(|ext| ext.to_str())
                    .map(|ext| extensions.contains(&ext))
                    .unwrap_or(false)
            })
            .filter(|e| {
                // Skip common non-source directories
                e.path()
                    .parent()
                    .and_then(|p| p.file_name())
                    .map(|name| {
                        !matches!(
                            name.to_str(),
                            Some("node_modules" | "target" | "venv" | ".venv" | "__pycache__" | "dist" | "build")
                        )
                    })
                    .unwrap_or(true)
            })
            .for_each(|e| files.push(e.path().to_path_buf()));

        Ok(files)
    }

    /// Parse files in parallel using Rayon
    fn parse_files_parallel(
        &self,
        files: Vec<PathBuf>,
        thread_count: usize,
    ) -> Result<Vec<FileMetadata>> {
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(thread_count)
            .build()?;

        let results = pool.install(|| {
            files.par_iter()
                .map(|path| self.parse_file(path))
                .collect::<Vec<_>>()
        });

        // Filter successful parses
        Ok(results
            .into_iter()
            .filter_map(|r| r.ok())
            .collect())
    }

    /// Parse a single file
    fn parse_file(&self, path: &Path) -> Result<FileMetadata> {
        let extension = path
            .extension()
            .and_then(|ext| ext.to_str())
            .unwrap_or("unknown");

        let language = match extension {
            "py" | "pyi" => "python",
            "rs" => "rust",
            "js" => "javascript",
            "ts" => "typescript",
            "jsx" => "jsx",
            "tsx" => "tsx",
            "go" => "go",
            "java" => "java",
            "cpp" | "cc" | "cxx" => "cpp",
            "hpp" | "h" => "c",
            _ => "unknown",
        };

        let metadata = match language {
            "python" => self.parse_python_file(path)?,
            "rust" => self.parse_rust_file(path)?,
            _ => FileMetadata {
                path: path.to_path_buf(),
                language: language.to_string(),
            },
        };

        Ok(metadata)
    }

    /// Parse Python file
    fn parse_python_file(&self, path: &Path) -> Result<FileMetadata> {
        Ok(FileMetadata {
            path: path.to_path_buf(),
            language: "python".to_string(),
        })
    }

    /// Parse Rust file
    fn parse_rust_file(&self, path: &Path) -> Result<FileMetadata> {
        Ok(FileMetadata {
            path: path.to_path_buf(),
            language: "rust".to_string(),
        })
    }

    /// Extract code chunks from parsed files
    fn extract_code_chunks(&self, files: Vec<FileMetadata>) -> Result<Vec<CodeChunk>> {
        let mut chunks = Vec::new();
        let mut id_counter = 0usize;

        for file in files {
            let code = std::fs::read_to_string(&file.path)?;

            // Create module-level chunk
            chunks.push(CodeChunk {
                id: id_counter,
                file_path: file.path.clone(),
                language: file.language.clone(),
                chunk_type: "module".to_string(),
                name: file.path.file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("unknown")
                    .to_string(),
                code: code.clone(),
                line_start: 1,
                line_end: code.lines().count(),
            });
            id_counter += 1;

            // TODO: Extract function-level chunks
            // TODO: Extract class-level chunks
        }

        Ok(chunks)
    }

    /// Index chunks with embeddings
    async fn index_chunks(&self, chunks: Vec<CodeChunk>) -> Result<usize> {
        let mut indexed = 0usize;

        for chunk in chunks {
            // Generate embedding (TODO: Use Python FFI)
            let embedding = self.generate_embedding(&chunk.code, &chunk.language)?;

            // Create metadata
            let metadata = serde_json::json!({
                "file_path": chunk.file_path,
                "language": chunk.language,
                "chunk_type": chunk.chunk_type,
                "name": chunk.name,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
            });

            // Store in HNSW
            self.memory.insert(
                chunk.id,
                &embedding,
                chunk.code.clone(),
                metadata.to_string(),
            )?;

            indexed += 1;
        }

        Ok(indexed)
    }

    /// Generate embedding for code using Python FFI
    fn generate_embedding(&self, code: &str, language: &str) -> Result<Vec<f32>> {
        use pyo3::prelude::*;

        // Initialize Python interpreter if needed
        pyo3::prepare_freethreaded_python();

        Python::with_gil(|py| {
            // Call with code (optionally specify model based on language)
            let model_opt = match language {
                "python" => Some("sentence-transformers/all-MiniLM-L6-v2"),
                "rust" | "javascript" | "typescript" => Some("sentence-transformers/all-MiniLM-L6-v2"),
                _ => None,
            };

            // Call Rust FFI function directly (it handles Python callbacks internally)
            let embedding = seahorse_ffi::embeddings::generate_embedding(py, code, model_opt)
                .map_err(|e| color_eyre::eyre::eyre!("generate_embedding call failed: {}", e))?;

            tracing::debug!(
                "Generated {}-dim embedding for {} code ({} chars)",
                embedding.len(),
                language,
                code.len()
            );

            Ok(embedding)
        })
    }
}


