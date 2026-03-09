//! Seahorse Core — high-performance AI agent runtime engine.
//!
//! Provides the Rust-native hot path:
//! - [`AgentMemory`]: zero-GC HNSW vector memory
//! - [`AgentScheduler`]: bounded Tokio task queue
//! - [`Config`]: env-driven configuration
//! - [`CoreError`]: typed error hierarchy
#![warn(clippy::all, clippy::pedantic)]
#![allow(clippy::must_use_candidate, clippy::module_name_repetitions)]

pub mod agent;
pub mod config;
pub mod error;
pub mod graph;
pub mod memory;
pub mod scheduler;
pub mod wasm;
pub mod worker;

pub use agent::RigAgent;
pub use config::Config;
pub use error::{CoreError, CoreResult};
pub use memory::AgentMemory;
pub use scheduler::{AgentScheduler, AgentTask};
pub use worker::{spawn_worker_loop, PythonRunner};

use std::sync::Arc;
use tracing::info;

/// Top-level orchestrator for the Seahorse Agent core.
pub struct SeahorseCore {
    pub config: Config,
    pub memory: Arc<AgentMemory>,
    pub scheduler: Arc<AgentScheduler>,
}

impl SeahorseCore {
    /// Initialise SeahorseCore from a [`Config`].
    pub fn new(config: Config) -> (Self, tokio::sync::mpsc::Receiver<AgentTask>) {
        let memory = Arc::new(AgentMemory::new(
            config.embedding_dim,
            config.hnsw_max_elements,
            config.hnsw_m,
            config.hnsw_ef_construction,
        ));

        let (scheduler, task_rx) = AgentScheduler::new(256);
        let core = Self {
            config,
            memory,
            scheduler: Arc::new(scheduler),
        };

        info!("SeahorseCore initialised");
        (core, task_rx)
    }

    /// Convenience constructor for tests (uses defaults).
    #[cfg(test)]
    pub fn new_test() -> (Self, tokio::sync::mpsc::Receiver<AgentTask>) {
        Self::new(Config::from_env().expect("test config"))
    }
}
