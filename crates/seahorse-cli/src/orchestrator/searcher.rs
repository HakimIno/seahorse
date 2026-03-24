//! Semantic Search Orchestrator
//!
//! Fast semantic code search using HNSW vector database

use color_eyre::Result;
use std::sync::Arc;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// Search result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub file_path: PathBuf,
    pub language: String,
    pub chunk_type: String,
    pub name: String,
    pub code: String,
    pub score: f32,
    pub line_start: usize,
    pub line_end: usize,
    pub rank: usize,
}

/// Semantic searcher
pub struct SemanticSearcher {
    memory: Arc<seahorse_core::memory::AgentMemory>,
}

impl SemanticSearcher {
    /// Create new semantic searcher
    pub fn new(memory: Arc<seahorse_core::memory::AgentMemory>) -> Self {
        Self {
            memory,
        }
    }

    /// Search codebase by semantic query
    pub fn search(
        &self,
        query: &str,
        limit: usize,
        language_filter: Option<&str>,
    ) -> Result<Vec<SearchResult>> {
        // Generate query embedding
        let query_embedding = self.generate_query_embedding(query)?;

        // Search HNSW index
        let raw_results = self.memory.search(&query_embedding, limit, 200)?;

        // Parse and filter results
        let mut results: Vec<SearchResult> = raw_results
            .into_iter()
            .enumerate()
            .filter_map(|(rank, (id, score, code, meta_str))| {
                self.parse_search_result(id, score, code, meta_str, rank, language_filter)
            })
            .collect();

        // Apply additional scoring boost for exact matches
        self.apply_exact_match_boost(&mut results, query);

        Ok(results)
    }

    /// Parse search result from HNSW metadata
    fn parse_search_result(
        &self,
        _id: usize,
        score: f32,
        code: String,
        meta_str: String,
        rank: usize,
        language_filter: Option<&str>,
    ) -> Option<SearchResult> {
        // Parse metadata JSON
        let meta: serde_json::Value = serde_json::from_str(&meta_str).ok()?;

        let file_path = meta.get("file_path")?.as_str()?.to_string();
        let language = meta.get("language")?.as_str()?.to_string();
        let chunk_type = meta.get("chunk_type")?.as_str()?.to_string();
        let name = meta.get("name")?.as_str()?.to_string();
        let line_start = meta.get("line_start")?.as_u64()? as usize;
        let line_end = meta.get("line_end")?.as_u64()? as usize;

        // Apply language filter
        if let Some(filter_lang) = language_filter {
            if language != filter_lang {
                return None;
            }
        }

        Some(SearchResult {
            file_path: PathBuf::from(file_path),
            language,
            chunk_type,
            name,
            code,
            score: 1.0 - score,  // Convert distance to similarity
            line_start,
            line_end,
            rank,
        })
    }

    /// Apply exact match boost
    fn apply_exact_match_boost(&self, results: &mut [SearchResult], query: &str) {
        let query_lower = query.to_lowercase();

        for result in results.iter_mut() {
            let code_lower = result.code.to_lowercase();

            // Boost for exact query match
            if code_lower.contains(&query_lower) {
                result.score = (result.score * 0.7 + 1.0 * 0.3).min(1.0);
            }

            // Boost for function name match
            if result.name.to_lowercase().contains(&query_lower) {
                result.score = (result.score * 0.6 + 1.0 * 0.4).min(1.0);
            }
        }

        // Re-sort by boosted score
        results.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        // Update ranks after boosting
        for (i, result) in results.iter_mut().enumerate() {
            result.rank = i;
        }
    }

    /// Generate query embedding using Python FFI
    fn generate_query_embedding(&self, query: &str) -> Result<Vec<f32>> {
        use pyo3::prelude::*;

        // Initialize Python interpreter if needed
        pyo3::prepare_freethreaded_python();

        Python::with_gil(|py| {
            let embedding = seahorse_ffi::embeddings::generate_embedding(py, query, None)
                .map_err(|e| color_eyre::eyre::eyre!("generate_embedding call failed: {}", e))?;

            tracing::debug!(
                "Generated {}-dim embedding for query ({} chars)",
                embedding.len(),
                query.len()
            );

            Ok(embedding)
        })
    }

    /// Format search results for display
    pub fn format_results(&self, results: &[SearchResult], format_type: &str) -> String {
        match format_type {
            "json" => serde_json::to_string_pretty(results).unwrap_or_default(),
            _ => self.format_text(results),
        }
    }

    /// Format results as text
    fn format_text(&self, results: &[SearchResult]) -> String {
        if results.is_empty() {
            return "No results found.".to_string();
        }

        let mut output = String::new();
        output.push_str(&format!("Found {} result(s):\n\n", results.len()));

        for (i, result) in results.iter().enumerate() {
            output.push_str(&format!(
                "{}. [Score: {:.2}] {}::{} ({})\n",
                i + 1,
                result.score,
                result.language,
                result.chunk_type,
                result.name
            ));
            output.push_str(&format!("   File: {:?}\n", result.file_path));
            output.push_str(&format!("   Lines: {}-{}\n", result.line_start, result.line_end));

            // Show code snippet
            let lines: Vec<&str> = result.code.lines().collect();
            let snippet_lines = lines.iter().take(5).collect::<Vec<_>>();
            output.push_str("   Code:\n");
            for line in snippet_lines {
                output.push_str(&format!("     {}\n", line));
            }
            if lines.len() > 5 {
                output.push_str("     ...\n");
            }

            output.push('\n');
        }

        output
    }
}
