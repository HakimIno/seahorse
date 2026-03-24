//! Multi-Agent Refactoring Orchestrator
//!
//! Coordinates parallel execution of specialized refactoring agents:
//! - Performance Analyst
//! - Security Auditor
//! - Style Fixer
//! - Test Generator

use color_eyre::Result;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use tracing::{info, debug};

/// Refactoring agent type
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum RefactorAgent {
    Performance,
    Security,
    Style,
    Test,
}

impl RefactorAgent {
    /// Parse from string
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "performance" => Some(Self::Performance),
            "security" => Some(Self::Security),
            "style" => Some(Self::Style),
            "test" => Some(Self::Test),
            _ => None,
        }
    }

    /// Get all agents
    pub fn all() -> Vec<Self> {
        vec![Self::Performance, Self::Security, Self::Style, Self::Test]
    }

    /// Get name
    pub fn name(&self) -> &str {
        match self {
            Self::Performance => "performance_analyst",
            Self::Security => "security_auditor",
            Self::Style => "style_fixer",
            Self::Test => "test_generator",
        }
    }

    /// Get display name
    pub fn display_name(&self) -> &str {
        match self {
            Self::Performance => "Performance Analyst",
            Self::Security => "Security Auditor",
            Self::Style => "Style Fixer",
            Self::Test => "Test Generator",
        }
    }
}

impl std::fmt::Display for RefactorAgent {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Performance => write!(f, "performance"),
            Self::Security => write!(f, "security"),
            Self::Style => write!(f, "style"),
            Self::Test => write!(f, "test"),
        }
    }
}

/// Individual refactoring suggestion
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RefactorSuggestion {
    pub agent: RefactorAgent,
    pub file_path: PathBuf,
    pub line_start: usize,
    pub line_end: usize,
    pub title: String,
    pub description: String,
    pub code_before: String,
    pub code_after: String,
    pub severity: RefactorSeverity,
    pub confidence: f64,
    pub category: String,
}

/// Refactoring severity
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum RefactorSeverity {
    Critical,
    High,
    Medium,
    Low,
    Info,
}

/// Refactoring result for a single file
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileRefactorResult {
    pub file_path: PathBuf,
    pub suggestions: Vec<RefactorSuggestion>,
    pub total_changes: usize,
    pub by_severity: HashMap<RefactorSeverity, usize>,
}

/// Aggregate refactoring results
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RefactorSummary {
    pub results: Vec<FileRefactorResult>,
    pub total_files: usize,
    pub total_suggestions: usize,
    pub by_agent: HashMap<RefactorAgent, usize>,
    pub by_severity: HashMap<RefactorSeverity, usize>,
    pub execution_time_secs: f64,
    pub conflicts: Vec<ConflictInfo>,
}

/// Conflict between suggestions
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConflictInfo {
    pub file_path: PathBuf,
    pub line_range: (usize, usize),
    pub suggestions: Vec<usize>,  // Indices into suggestions
    pub description: String,
}

/// Diff preview
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DiffPreview {
    pub file_path: PathBuf,
    pub unified_diff: String,
    pub changes_applied: usize,
    pub changes_pending: usize,
}

/// Multi-agent refactoring orchestrator
#[derive(Debug, Default, Clone, Copy)]
pub struct RefactorOrchestrator {
    // pattern_engine: Option<Arc<super::patterns::PatternEngine>>,
}

impl RefactorOrchestrator {
    /// Create new refactor orchestrator
    pub fn new() -> Self {
        Self {
            // pattern_engine: None,
        }
    }

    /// Create with pattern engine
    /*
    pub fn with_pattern_engine(mut self, pattern_engine: Arc<super::patterns::PatternEngine>) -> Self {
        self.pattern_engine = Some(pattern_engine);
        self
    }
    */

    /// Refactor a file or directory
    pub async fn refactor(
        &self,
        path: PathBuf,
        agents: Vec<RefactorAgent>,
        diff_only: bool,
        auto_apply: bool,
    ) -> Result<RefactorSummary> {
        let start = std::time::Instant::now();

        info!("🔧 Starting refactoring: {:?}", path);
        info!("🤖 Agents: {:?}", agents);
        info!("📋 Diff only: {}", diff_only);
        info!("⚡ Auto-apply: {}", auto_apply);

        // Step 1: Collect files to refactor
        let files = self.collect_files(&path)?;
        info!("📁 Found {} files to analyze", files.len());

        // Step 2: Run agents in parallel
        let results = self.run_agents_parallel(files, agents.clone()).await?;
        info!("✅ Analysis complete: {} suggestions", results.len());

        // Step 3: Detect conflicts
        let conflicts = self.detect_conflicts(&results)?;
        if !conflicts.is_empty() {
            info!("⚠️  Found {} conflicts", conflicts.len());
        }

        // Step 4: Generate summary
        let summary = self.generate_summary(results, conflicts, start.elapsed().as_secs_f64())?;

        // Step 5: Apply changes if requested
        if !diff_only && auto_apply {
            info!("💾 Applying changes...");
            for file_result in &summary.results {
                let mut content = std::fs::read_to_string(&file_result.file_path)?;
                let mut applied = 0;
                
                // Sort suggestions by line (reverse) to avoid shifting issues if we did naive apply,
                // but since we do literal replacement for safety, order matters less if disjoint.
                for suggestion in &file_result.suggestions {
                    if !suggestion.code_before.is_empty() && content.contains(&suggestion.code_before) {
                        content = content.replace(&suggestion.code_before, &suggestion.code_after);
                        applied += 1;
                    }
                }
                
                if applied > 0 {
                    std::fs::write(&file_result.file_path, content)?;
                    info!("✅ Applied {} changes to {:?}", applied, file_result.file_path);
                }
            }
        }

        // Step 6: Learn from successful refactorings
        // TODO: Enable pattern learning after fixing borrow issues
        // if let Some(pattern_engine) = &self.pattern_engine {
        //     for file_result in &results {
        //         for suggestion in &file_result.suggestions {
        //             let agent_str = format!("{}", suggestion.agent);
        //             if let Err(e) = pattern_engine.learn_from_refactoring(
        //                 file_result.file_path.clone(),
        //                 agent_str,
        //                 &suggestion.code_before,
        //                 &suggestion.code_after,
        //                 true,
        //             ) {
        //                 error!("Failed to learn pattern: {}", e);
        //             }
        //         }
        //     }
        // }

        Ok(summary)
    }

    /// Collect files to refactor
    fn collect_files(&self, path: &Path) -> Result<Vec<PathBuf>> {
        let mut files = Vec::new();

        if path.is_file() {
            files.push(path.to_path_buf());
        } else {
            let extensions = ["py", "rs", "js", "ts", "jsx", "tsx", "go", "java"];

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
                .for_each(|e| files.push(e.path().to_path_buf()));
        }

        Ok(files)
    }

    /// Run agents in parallel
    async fn run_agents_parallel(
        &self,
        files: Vec<PathBuf>,
        agents: Vec<RefactorAgent>,
    ) -> Result<Vec<FileRefactorResult>> {
        let mut results = Vec::new();

        // For now, analyze each file with all agents
        for file_path in files {
            debug!("🔍 Analyzing: {:?}", file_path);

            let file_result = self.analyze_file(&file_path, &agents).await?;
            results.push(file_result);
        }

        Ok(results)
    }

    /// Analyze a single file with all agents
    async fn analyze_file(
        &self,
        file_path: &Path,
        agents: &[RefactorAgent],
    ) -> Result<FileRefactorResult> {
        let code = std::fs::read_to_string(file_path)?;
        let language = self.detect_language(file_path);
        let mut suggestions = Vec::new();

        // Run each agent
        for agent in agents {
            let agent_suggestions = self.run_agent(*agent, file_path, &code, &language).await?;
            suggestions.extend(agent_suggestions);
        }

        // Calculate statistics
        let total_changes = suggestions.len();
        let mut by_severity = HashMap::new();
        for suggestion in &suggestions {
            *by_severity.entry(suggestion.severity).or_insert(0) += 1;
        }

        Ok(FileRefactorResult {
            file_path: file_path.to_path_buf(),
            suggestions,
            total_changes,
            by_severity,
        })
    }

    /// Detect language from file extension
    fn detect_language(&self, path: &Path) -> String {
        path.extension()
            .and_then(|ext| ext.to_str())
            .map(|ext| match ext {
                "py" => "python",
                "rs" => "rust",
                "js" => "javascript",
                "ts" => "typescript",
                "jsx" => "jsx",
                "tsx" => "tsx",
                "go" => "go",
                "java" => "java",
                _ => "unknown",
            })
            .unwrap_or("unknown")
            .to_string()
    }

    /// Run a single agent (delegates to RefactorCrew)
    async fn run_agent(
        &self,
        agent: RefactorAgent,
        file_path: &Path,
        code: &str,
        language: &str,
    ) -> Result<Vec<RefactorSuggestion>> {
        debug!("🤖 Running {} agent on {:?}", agent.name(), file_path);

        // Call Python RefactorCrew via FFI
        let agents = vec![agent.to_string()];
        let json_str = seahorse_ffi::refactor::run_refactor_crew_sync(
            file_path.to_str().unwrap_or(""),
            code,
            agents,
            language
        ).map_err(|e| color_eyre::eyre::eyre!("FFI refactor error: {}", e))?;

        let summary_json: serde_json::Value = serde_json::from_str(&json_str)?;
        let mut suggestions = Vec::new();

        if let Some(results) = summary_json.get("results").and_then(|r| r.as_array()) {
            for result in results {
                if let Some(changes) = result.get("changes").and_then(|c| c.as_array()) {
                    for change in changes {
                        suggestions.push(RefactorSuggestion {
                            agent,
                            file_path: file_path.to_path_buf(),
                            line_start: change.get("line_start").and_then(|v| v.as_u64()).unwrap_or(1) as usize,
                            line_end: change.get("line_end").and_then(|v| v.as_u64()).unwrap_or(1) as usize,
                            title: change.get("title").and_then(|v| v.as_str()).unwrap_or("Suggestion").to_string(),
                            description: change.get("description").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                            code_before: change.get("code_before").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                            code_after: change.get("code_after").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                            severity: match change.get("severity").and_then(|v| v.as_str()).unwrap_or("Medium") {
                                "Critical" => RefactorSeverity::Critical,
                                "High" => RefactorSeverity::High,
                                "Medium" => RefactorSeverity::Medium,
                                "Low" => RefactorSeverity::Low,
                                _ => RefactorSeverity::Info,
                            },
                            confidence: change.get("confidence").and_then(|v| v.as_f64()).unwrap_or(0.8),
                            category: change.get("category").and_then(|v| v.as_str()).unwrap_or("general").to_string(),
                        });
                    }
                }
            }
        }

        Ok(suggestions)
    }


    /// Detect conflicts between suggestions
    fn detect_conflicts(&self, results: &[FileRefactorResult]) -> Result<Vec<ConflictInfo>> {
        let mut conflicts = Vec::new();

        // Check for overlapping line ranges in same file
        for file_result in results {
            let suggestions = &file_result.suggestions;
            for i in 0..suggestions.len() {
                for j in (i + 1)..suggestions.len() {
                    let s1 = &suggestions[i];
                    let s2 = &suggestions[j];

                    // Check for line range overlap
                    if s1.line_start <= s2.line_end && s2.line_start <= s1.line_end {
                        conflicts.push(ConflictInfo {
                            file_path: file_result.file_path.clone(),
                            line_range: (s1.line_start.min(s2.line_start), s1.line_end.max(s2.line_end)),
                            suggestions: vec![i, j],
                            description: format!(
                                "Conflict between {} and {}",
                                s1.agent.display_name(),
                                s2.agent.display_name()
                            ),
                        });
                    }
                }
            }
        }

        Ok(conflicts)
    }

    /// Generate refactoring summary
    fn generate_summary(
        &self,
        results: Vec<FileRefactorResult>,
        conflicts: Vec<ConflictInfo>,
        execution_time: f64,
    ) -> Result<RefactorSummary> {
        let total_files = results.len();
        let total_suggestions = results.iter().map(|r| r.total_changes).sum();

        let mut by_agent = HashMap::new();
        let mut by_severity = HashMap::new();

        for result in &results {
            for suggestion in &result.suggestions {
                *by_agent.entry(suggestion.agent).or_insert(0) += 1;
                *by_severity.entry(suggestion.severity).or_insert(0) += 1;
            }
        }

        Ok(RefactorSummary {
            results,
            total_files,
            total_suggestions,
            by_agent,
            by_severity,
            execution_time_secs: execution_time,
            conflicts,
        })
    }

    /// Format summary for display
    pub fn format_summary(&self, summary: &RefactorSummary) -> String {
        let mut output = String::new();

        output.push_str("╔════════════════════════════════════════════════════════════╗\n");
        output.push_str("║           🔧 REFACTORING ANALYSIS COMPLETE 🔧              ║\n");
        output.push_str("╚════════════════════════════════════════════════════════════╝\n\n");

        output.push_str(&format!("📊 Files analyzed: {}\n", summary.total_files));
        output.push_str(&format!("💡 Total suggestions: {}\n", summary.total_suggestions));
        output.push_str(&format!("⏱️  Analysis time: {:.2}s\n\n", summary.execution_time_secs));

        // By agent
        output.push_str("🤖 Suggestions by Agent:\n");
        for (agent, count) in &summary.by_agent {
            output.push_str(&format!("  • {}: {}\n", agent.display_name(), count));
        }
        output.push('\n');

        // By severity
        output.push_str("⚠️  By Severity:\n");
        for (severity, count) in &summary.by_severity {
            let icon = match severity {
                RefactorSeverity::Critical => "🔴",
                RefactorSeverity::High => "🟠",
                RefactorSeverity::Medium => "🟡",
                RefactorSeverity::Low => "🟢",
                RefactorSeverity::Info => "🔵",
            };
            output.push_str(&format!("  • {} {}: {}\n", icon, format!("{:?}", severity), count));
        }
        output.push('\n');

        // Conflicts
        if !summary.conflicts.is_empty() {
            output.push_str(&format!("⚠️  Conflicts detected: {}\n\n", summary.conflicts.len()));
        }

        // Detailed results
        output.push_str("📋 Detailed Results:\n\n");
        for (i, file_result) in summary.results.iter().enumerate() {
            if file_result.suggestions.is_empty() {
                continue;
            }

            output.push_str(&format!("{}. {:?}\n", i + 1, file_result.file_path));
            output.push_str(&format!("   {} suggestion(s)\n\n", file_result.total_changes));

            for (j, suggestion) in file_result.suggestions.iter().enumerate() {
                let severity_icon = match suggestion.severity {
                    RefactorSeverity::Critical => "🔴",
                    RefactorSeverity::High => "🟠",
                    RefactorSeverity::Medium => "🟡",
                    RefactorSeverity::Low => "🟢",
                    RefactorSeverity::Info => "🔵",
                };

                output.push_str(&format!("   {}. {} {} [Confidence: {:.0}%]\n",
                    j + 1,
                    severity_icon,
                    suggestion.title,
                    suggestion.confidence * 100.0
                ));
                output.push_str(&format!("      {}\n", suggestion.description));
                output.push_str(&format!("      Lines: {}-{}\n", suggestion.line_start, suggestion.line_end));

                if !suggestion.code_before.trim().is_empty() {
                    output.push_str("\n      Before:\n");
                    for line in suggestion.code_before.lines().take(3) {
                        output.push_str(&format!("        - {}\n", line));
                    }
                }

                if !suggestion.code_after.trim().is_empty() {
                    output.push_str("\n      After:\n");
                    for line in suggestion.code_after.lines().take(3) {
                        output.push_str(&format!("        + {}\n", line));
                    }
                }

                output.push('\n');
            }
        }

        output
    }

    /// Generate diff preview
    pub fn generate_diff(&self, summary: &RefactorSummary) -> Result<Vec<DiffPreview>> {
        let mut diffs = Vec::new();

        for file_result in &summary.results {
            if file_result.suggestions.is_empty() {
                continue;
            }

            let mut unified_diff = String::new();
            unified_diff.push_str(&format!("--- a/{:?}\n", file_result.file_path));
            unified_diff.push_str(&format!("+++ b/{:?}\n", file_result.file_path));

            // TODO: Generate proper unified diff
            for suggestion in &file_result.suggestions {
                unified_diff.push_str(&format!("@@ -{},{} +{},{} @@\n",
                    suggestion.line_start,
                    suggestion.code_before.lines().count(),
                    suggestion.line_start,
                    suggestion.code_after.lines().count()
                ));

                for line in suggestion.code_before.lines() {
                    unified_diff.push_str(&format!("-{}\n", line));
                }
                for line in suggestion.code_after.lines() {
                    unified_diff.push_str(&format!("+{}\n", line));
                }
            }

            diffs.push(DiffPreview {
                file_path: file_result.file_path.clone(),
                unified_diff,
                changes_applied: 0,  // TODO: Track applied changes
                changes_pending: file_result.total_changes,
            });
        }

        Ok(diffs)
    }
}
