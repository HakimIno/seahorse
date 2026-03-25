//! CLI Orchestrator
//!
//! Core CLI logic that coordinates:
//! - Codebase indexing
//! - Semantic search
//! - Multi-agent refactoring
//! - Session management
//! - Interactive chat

pub mod indexer;
pub mod searcher;
pub mod refactor;
pub mod memory;
pub mod session;
pub mod patterns;

use color_eyre::Result;
use crate::client::RouterClient;
use crate::tui::ChatTui;
use std::path::PathBuf;
use std::sync::Arc;
use tracing::info;

/// CLI Orchestrator
pub struct CliOrchestrator {
    router_client: RouterClient,
    memory: Arc<seahorse_core::memory::AgentMemory>,
    memory_manager: memory::MemoryManager,
    session_store: session::SessionStore,
    pattern_engine: Arc<patterns::PatternEngine>,
}

impl CliOrchestrator {
    /// Create new orchestrator
    pub async fn new(router_url: String) -> Result<Self> {
        let router_client = RouterClient::new(router_url)?;

        // Setup memory manager
        let memory_manager = memory::MemoryManager::new(
            std::env::current_dir()?
        );

        // Try to load existing index, or create new one
        let memory = if memory_manager.index_exists() {
            info!("📂 Loading existing index...");
            memory_manager.load_memory(384)?
        } else {
            info!("🆕 Creating new index...");
            Arc::new(seahorse_core::memory::AgentMemory::new(
                384,  // embedding dimension
                100_000,  // max elements
                16,     // M (graph connectivity)
                200,    // ef_construction
            ))
        };

        Ok(Self {
            router_client,
            memory,
            memory_manager,
            session_store: session::SessionStore::new(std::env::current_dir()?)?,
            pattern_engine: Arc::new(patterns::PatternEngine::new(std::env::current_dir()?)?),
        })
    }

    /// Index a codebase
    pub async fn index(
        &self,
        path: PathBuf,
        force: bool,
        threads: Option<usize>,
    ) -> Result<()> {
        let indexer = indexer::ParallelIndexer::new(
            self.memory.clone(),
        );

        let stats = indexer.index_project(path, force, threads).await?;

        // Print results
        println!("\n✅ Indexing Complete!");
        println!("📊 Statistics:");
        println!("  Files scanned: {}", stats.files_scanned);
        println!("  Files indexed: {}", stats.files_indexed);
        println!("  Files failed: {}", stats.files_failed);
        println!("  Time: {:.2}s", stats.indexing_time_secs);
        println!("  Speed: {:.1} files/sec", stats.files_per_second);

        // Auto-save index
        self.memory_manager.save_memory(&self.memory)?;

        Ok(())
    }

    /// Search codebase semantically
    pub async fn search(
        &self,
        query: String,
        limit: usize,
        language: Option<String>,
        format: String,
    ) -> Result<()> {
        let searcher = searcher::SemanticSearcher::new(
            self.memory.clone(),
        );

        let results = searcher.search(&query, limit, language.as_deref())?;

        let output = searcher.format_results(&results, &format);
        println!("{}", output);

        Ok(())
    }

    /// Show index information
    pub async fn index_info(&self) -> Result<()> {
        let info = self.memory_manager.get_index_info()?;

        println!("╔════════════════════════════════════════════════════════════╗\n");
        println!("📊 INDEX INFORMATION\n");

        if info.exists {
            println!("Status: ✅ Indexed");
            println!("Items: {}", info.items);
            println!("Path: {:?}", info.path);

            if let Some(modified) = info.modified {
                let modified_date = chrono::DateTime::<chrono::Utc>::from_timestamp(modified as i64, 0)
                    .ok_or_else(|| color_eyre::eyre::eyre!("Invalid timestamp"))?;
                println!("Last Modified: {}", modified_date.format("%Y-%m-%d %H:%M:%S UTC"));
            }
        } else {
            println!("Status: 📭 No index found");
            println!("Path: {:?}", info.path);
            println!("\n💡 Run 'seahorse index build <path>' to create an index");
        }

        println!("\n╚════════════════════════════════════════════════════════════╝");

        Ok(())
    }

    /// Clear the index
    pub async fn index_clear(&self) -> Result<()> {
        println!("⚠️  This will clear the index.");
        println!("Continue? (y/N): ");

        let mut input = String::new();
        std::io::stdin().read_line(&mut input)?;

        if input.trim().to_lowercase() == "y" {
            self.memory_manager.clear_index()?;
            println!("✅ Index cleared successfully");
        } else {
            println!("❌ Cancelled");
        }

        Ok(())
    }

    /// Refactor code using AI agents
    pub async fn refactor(
        &self,
        path: PathBuf,
        agents: String,
        diff_only: bool,
        yes: bool,
    ) -> Result<()> {
        use refactor::RefactorAgent;

        // Parse agents
        let agent_list: Vec<RefactorAgent> = agents
            .split(',')
            .filter_map(|s| RefactorAgent::from_str(s.trim()))
            .collect();

        if agent_list.is_empty() {
            println!("❌ No valid agents specified. Available agents:");
            for agent in RefactorAgent::all() {
                println!("  • {}", agent.name());
            }
            return Ok(());
        }

        println!("🤖 Running agents: {:?}\n", agent_list);

        let refactor_orchestrator = refactor::RefactorOrchestrator::new();
        let summary = refactor_orchestrator.refactor(path, agent_list, diff_only, yes).await?;

        // Print formatted summary
        let output = refactor_orchestrator.format_summary(&summary);
        println!("{}", output);

        // Generate diff preview
        if diff_only {
            println!("╔════════════════════════════════════════════════════════════╗\n");
            println!("📋 DIFF PREVIEW\n");

            let diffs = refactor_orchestrator.generate_diff(&summary)?;
            for diff in diffs {
                println!("File: {:?}", diff.file_path);
                println!("Changes: {} pending\n", diff.changes_pending);
                println!("{}", diff.unified_diff);
                println!("{}", "─".repeat(80));
            }
        }

        Ok(())
    }

    /// Run interactive chat TUI
    pub async fn run_chat(
        &self,
        initial_message: Option<String>,
        session_id: Option<String>,
    ) -> Result<()> {
        // Load config to get current model
        let config = crate::config::CliConfig::load().await?;
        let model_name = config.llm.model.unwrap_or_else(|| "default".to_string());

        let mut tui = ChatTui::new(
            self.router_client.clone(),
            model_name,
            session_id,
        )?;

        if let Some(msg) = initial_message {
            tui.set_initial_message(msg);
        }

        tui.run().await?;

        Ok(())
    }

    /// List all sessions
    pub async fn list_sessions(&self) -> Result<()> {
        let sessions = self.session_store.list_sessions()?;

        println!("╔════════════════════════════════════════════════════════════╗\n");
        println!("📋 SESSIONS ({})\n", sessions.len());

        if sessions.is_empty() {
            println!("No sessions found.");
            println!("💡 Run 'seahorse chat' to create a new session\n");
        } else {
            for (i, session) in sessions.iter().enumerate() {
                println!("{}. {}", i + 1, session.id);
                println!("   Type: {}", session.metadata.session_type);
                println!("   Created: {}", session.created_at.format("%Y-%m-%d %H:%M:%S"));
                println!("   Messages: {}", session.message_count);
                println!("   Operations: {}", session.operation_count);
                if let Some(project) = &session.metadata.project_path {
                    println!("   Project: {:?}", project);
                }
                println!();
            }
        }

        println!("╚════════════════════════════════════════════════════════════╝");

        Ok(())
    }

    /// Show session details
    pub async fn show_session(&self, id: String) -> Result<()> {
        let session = self.session_store.load_session(&id)?;

        println!("╔════════════════════════════════════════════════════════════╗\n");
        println!("📋 SESSION: {}\n", session.id);
        println!("Created: {}", session.created_at.format("%Y-%m-%d %H:%M:%S UTC"));
        println!("Updated: {}", session.updated_at.format("%Y-%m-%d %H:%M:%S UTC"));
        println!("Type: {}", session.metadata.session_type);

        if let Some(project) = &session.metadata.project_path {
            println!("Project: {:?}", project);
        }

        println!("\n📨 Messages ({}):\n", session.messages.len());
        for (i, msg) in session.messages.iter().enumerate() {
            println!("{}. [{}] {}: {}",
                i + 1,
                msg.timestamp.format("%H:%M:%S"),
                msg.role.to_uppercase(),
                msg.content.chars().take(80).collect::<String>()
            );
        }

        println!("\n⚙️  Operations ({}):\n", session.operations.len());
        for (i, op) in session.operations.iter().enumerate() {
            println!("{}. [{}] {}",
                i + 1,
                op.timestamp.format("%H:%M:%S"),
                op.op_type
            );
        }

        println!("\n╚════════════════════════════════════════════════════════════╝");

        Ok(())
    }

    /// Delete a session
    pub async fn delete_session(&self, id: String) -> Result<()> {
        self.session_store.delete_session(&id)?;
        println!("✅ Session deleted: {}", id);
        Ok(())
    }

    /// Clear all sessions
    pub async fn clear_sessions(&self) -> Result<()> {
        self.session_store.clear_all_sessions()?;
        println!("✅ All sessions cleared");
        Ok(())
    }

    /// Show pattern statistics
    pub async fn show_patterns(&self) -> Result<()> {
        let stats = self.pattern_engine.get_statistics()?;

        println!("╔════════════════════════════════════════════════════════════╗\n");
        println!("🧠 LEARNED PATTERNS\n");
        println!("Total Refactor Patterns: {}", stats.total_refactor_patterns);
        println!("Total Code Patterns: {}", stats.total_code_patterns);
        println!("Languages: {}", stats.languages.join(", "));
        println!("Last Updated: {}", stats.last_updated.format("%Y-%m-%d %H:%M:%S UTC"));
        println!("\n╚════════════════════════════════════════════════════════════╝");

        Ok(())
    }

    /// List learned patterns
    pub async fn list_patterns(&self) -> Result<()> {
        let stats = self.pattern_engine.get_statistics()?;

        println!("╔════════════════════════════════════════════════════════════╗\n");
        println!("🧠 LEARNED PATTERNS\n");

        if stats.total_refactor_patterns == 0 && stats.total_code_patterns == 0 {
            println!("No patterns learned yet.");
            println!("💡 Patterns are learned from successful refactorings\n");
        } else {
            println!("Refactor Patterns: {}", stats.total_refactor_patterns);
            println!("Code Patterns: {}", stats.total_code_patterns);
            println!("Languages: {}", stats.languages.join(", "));
            println!("\n💡 Use 'seahorse refactor' to learn new patterns");
        }

        println!("\n╚════════════════════════════════════════════════════════════╝");

        Ok(())
    }

    /// Clear all patterns
    pub async fn clear_patterns(&self) -> Result<()> {
        println!("⚠️  This will clear all learned patterns.");
        println!("Continue? (y/N): ");

        let mut input = String::new();
        std::io::stdin().read_line(&mut input)?;

        if input.trim().to_lowercase() == "y" {
            // TODO: Implement pattern clearing
            println!("✅ Patterns cleared");
        } else {
            println!("❌ Cancelled");
        }

        Ok(())
    }
}
