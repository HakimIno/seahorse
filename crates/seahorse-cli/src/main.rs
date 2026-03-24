#![allow(clippy::missing_errors_doc)]
#![allow(clippy::must_use_candidate)]

use clap::{Parser, Subcommand};
use color_eyre::Result;
use orchestrator::CliOrchestrator;
use tracing_subscriber::{EnvFilter, fmt};
use tracing::{info, Level};

mod orchestrator;
mod tui;
mod client;
mod config;

/// Seahorse CLI - AI-Powered Coding Assistant
///
/// Ultra-fast code understanding and refactoring powered by
/// Rust performance and Python AI intelligence.
#[derive(Parser)]
#[command(name = "seahorse")]
#[command(author = "Seahorse Team")]
#[command(version = "0.1.0")]
#[command(about = "AI-powered coding assistant", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Commands,

    /// Router API URL (default: http://localhost:8000)
    #[arg(short, long, global = true)]
    #[arg(default_value = "http://127.0.0.1:8000")]
    router_url: String,

    /// Enable verbose logging
    #[arg(short, long, global = true)]
    verbose: bool,
}

#[derive(Subcommand)]
enum IndexCommands {
    /// Index a codebase directory
    Build {
        /// Path to the codebase
        path: std::path::PathBuf,

        /// Force re-index even if already indexed
        #[arg(long)]
        force: bool,

        /// Number of parallel threads (default: CPU count)
        #[arg(long)]
        threads: Option<usize>,
    },

    /// Show index information
    Info,

    /// Clear the index
    Clear,
}

#[derive(Subcommand)]
enum Commands {
    /// Index a codebase for semantic search
    Index {
        #[command(subcommand)]
        index_cmd: IndexCommands,
    },

    /// Search code by semantic meaning
    Search {
        /// Search query
        query: String,

        /// Maximum results to return
        #[arg(short = 'n', long, default_value = "10")]
        limit: usize,

        /// Filter by programming language
        #[arg(short = 'L', long)]
        language: Option<String>,

        /// Output format (text, json)
        #[arg(long, default_value = "text")]
        format: String,
    },

    /// Refactor code using AI agents
    Refactor {
        /// Path to file or directory to refactor
        path: std::path::PathBuf,

        /// Agents to use (comma-separated): performance, security, style, test
        #[arg(short, long, default_value = "performance,security")]
        agents: String,

        /// Show diff without applying changes
        #[arg(short, long)]
        diff_only: bool,

        /// Auto-apply changes without confirmation
        #[arg(short, long)]
        yes: bool,
    },

    /// Interactive chat mode with TUI
    Chat {
        /// Start with a message
        message: Option<String>,

        /// Session ID to resume
        #[arg(short, long)]
        session: Option<String>,
    },

    /// Session management
    Session {
        #[command(subcommand)]
        session_cmd: SessionCommands,
    },

    /// Pattern learning and management
    Patterns {
        #[command(subcommand)]
        pattern_cmd: PatternCommands,
    },
}

#[derive(Subcommand)]
enum SessionCommands {
    /// List all sessions
    List,

    /// Show session details
    Show {
        /// Session ID
        id: String,
    },

    /// Delete a session
    Delete {
        /// Session ID
        id: String,
    },

    /// Clear all sessions
    Clear,
}

#[derive(Subcommand)]
enum PatternCommands {
    /// Show pattern statistics
    Stats,

    /// Show learned patterns
    List,

    /// Clear all patterns
    Clear,
}

#[tokio::main]
async fn main() -> Result<()> {
    // Setup error handling
    color_eyre::install()?;

    // Parse CLI
    let cli = Cli::parse();

    // Setup tracing
    let filter = if cli.verbose {
        EnvFilter::new(Level::DEBUG.to_string())
    } else {
        EnvFilter::from_default_env()
            .add_directive(Level::INFO.to_string().parse()?)
            .add_directive("seahorse_core=warn".parse()?)
            .add_directive("seahorse_router=warn".parse()?)
    };

    fmt()
        .with_env_filter(filter)
        .with_target(false)
        .with_thread_ids(false)
        .with_file(false)
        .with_line_number(false)
        .init();

    // Create orchestrator
    let orchestrator = CliOrchestrator::new(cli.router_url.clone()).await?;

    // Initialize Python environment for local FFI (embeddings, etc.)
    seahorse_ffi::graph_runner::init_python_env()
        .map_err(|e| color_eyre::eyre::eyre!("Python init failed: {}", e))?;

    // Execute command
    match cli.command {
        Commands::Index { index_cmd } => {
            match index_cmd {
                IndexCommands::Build { path, force, threads } => {
                    info!("🔍 Indexing codebase at: {:?}", path);
                    orchestrator.index(path, force, threads).await?;
                }
                IndexCommands::Info => {
                    orchestrator.index_info().await?;
                }
                IndexCommands::Clear => {
                    orchestrator.index_clear().await?;
                }
            }
        }
        Commands::Search { query, limit, language, format } => {
            info!("🔎 Searching: {}", query);
            orchestrator.search(query, limit, language, format).await?;
        }
        Commands::Refactor { path, agents, diff_only, yes } => {
            info!("🔧 Refactoring: {:?}", path);
            orchestrator.refactor(path, agents, diff_only, yes).await?;
        }
        Commands::Chat { message, session } => {
            info!("💬 Starting chat mode");
            orchestrator.run_chat(message, session).await?;
        }
        Commands::Session { session_cmd } => {
            match session_cmd {
                SessionCommands::List => {
                    orchestrator.list_sessions().await?;
                }
                SessionCommands::Show { id } => {
                    orchestrator.show_session(id).await?;
                }
                SessionCommands::Delete { id } => {
                    orchestrator.delete_session(id).await?;
                }
                SessionCommands::Clear => {
                    orchestrator.clear_sessions().await?;
                }
            }
        }
        Commands::Patterns { pattern_cmd } => {
            match pattern_cmd {
                PatternCommands::Stats => {
                    orchestrator.show_patterns().await?;
                }
                PatternCommands::List => {
                    orchestrator.list_patterns().await?;
                }
                PatternCommands::Clear => {
                    orchestrator.clear_patterns().await?;
                }
            }
        }
    }

    Ok(())
}
