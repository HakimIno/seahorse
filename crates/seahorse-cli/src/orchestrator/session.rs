//! Session Persistence System
//!
//! Manages persistent storage for:
//! - Chat history
//! - Refactoring operations
//! - User preferences
//! - Learned patterns

use color_eyre::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use chrono::{DateTime, Utc};


/// Session storage manager
pub struct SessionStore {
    sessions_dir: PathBuf,
    sessions: Arc<Mutex<HashMap<String, Session>>>,
}

impl SessionStore {
    /// Create new session store
    pub fn new(base_dir: PathBuf) -> Result<Self> {
        let sessions_dir = base_dir.join(".seahorse").join("sessions");
        Ok(Self {
            sessions_dir,
            sessions: Arc::new(Mutex::new(HashMap::new())),
        })
    }



    /// Load session from disk
    pub fn load_session(&self, session_id: &str) -> Result<Session> {
        let session_path = self.sessions_dir.join(format!("{}.json", session_id));

        if !session_path.exists() {
            return Err(color_eyre::eyre::eyre!("Session not found: {}", session_id));
        }

        let json = std::fs::read_to_string(&session_path)?;
        let session: Session = serde_json::from_str(&json)?;

        // Cache in memory
        let mut sessions = self.sessions.lock()
            .map_err(|e| color_eyre::eyre::eyre!("Session lock poisoned: {}", e))?;
        sessions.insert(session_id.to_string(), session.clone());

        tracing::info!("📂 Loaded session: {}", session_id);
        Ok(session)
    }

    /// List all sessions
    pub fn list_sessions(&self) -> Result<Vec<SessionSummary>> {
        let mut summaries = Vec::new();

        for entry in std::fs::read_dir(&self.sessions_dir)? {
            let entry = entry?;
            let path = entry.path();

            if path.extension().and_then(|s| s.to_str()) == Some("json") {
                let json = std::fs::read_to_string(&path)?;
                if let Ok(session) = serde_json::from_str::<Session>(&json) {
                    summaries.push(SessionSummary {
                        id: session.id.clone(),
                        created_at: session.created_at,
                        updated_at: session.updated_at,
                        message_count: session.messages.len(),
                        operation_count: session.operations.len(),
                        metadata: session.metadata,
                    });
                }
            }
        }

        summaries.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));
        Ok(summaries)
    }

    /// Delete a session
    pub fn delete_session(&self, session_id: &str) -> Result<()> {
        let session_path = self.sessions_dir.join(format!("{}.json", session_id));

        if session_path.exists() {
            std::fs::remove_file(&session_path)?;
        }

        let mut sessions = self.sessions.lock()
            .map_err(|e| color_eyre::eyre::eyre!("Session lock poisoned: {}", e))?;
        sessions.remove(session_id);

        tracing::info!("🗑️  Deleted session: {}", session_id);
        Ok(())
    }

    /// Clear all sessions
    pub fn clear_all_sessions(&self) -> Result<()> {
        for entry in std::fs::read_dir(&self.sessions_dir)? {
            let entry = entry?;
            let path = entry.path();

            if path.extension().and_then(|s| s.to_str()) == Some("json") {
                std::fs::remove_file(&path)?;
            }
        }

        let mut sessions = self.sessions.lock()
            .map_err(|e| color_eyre::eyre::eyre!("Session lock poisoned: {}", e))?;
        sessions.clear();

        tracing::info!("🗑️  Cleared all sessions");
        Ok(())
    }


}

/// Session data
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    pub id: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub metadata: SessionMetadata,
    pub messages: Vec<SessionMessage>,
    pub operations: Vec<Operation>,
}

/// Session metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMetadata {
    pub project_path: Option<PathBuf>,
    pub session_type: String,  // "chat", "refactor", "index"
    pub tags: Vec<String>,
}

impl Default for SessionMetadata {
    fn default() -> Self {
        Self {
            project_path: None,
            session_type: "chat".to_string(),
            tags: Vec::new(),
        }
    }
}

/// Session message
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMessage {
    pub role: String,  // "user", "assistant", "system"
    pub content: String,
    pub timestamp: DateTime<Utc>,
    pub metadata: Option<serde_json::Value>,
}

/// Operation performed in session
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Operation {
    pub op_type: String,  // "index", "search", "refactor"
    pub timestamp: DateTime<Utc>,
    pub details: serde_json::Value,
    pub result: Option<serde_json::Value>,
}

/// Session summary for listing
#[derive(Debug, Clone)]
pub struct SessionSummary {
    pub id: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub message_count: usize,
    pub operation_count: usize,
    pub metadata: SessionMetadata,
}
