//! Task Store — persistent task tracking with SQLite backend.
//!
//! Provides thread-safe task storage with CRUD operations and
//! supports task dependencies and status tracking.

use crate::{CoreError, CoreResult};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::sync::{Arc, Mutex};
use tracing::{debug, info};

/// Unique task identifier (8-character hex string)
pub type TaskId = String;

/// Task status in the workflow
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TaskStatus {
    /// Task is pending execution
    Pending,
    /// Task is currently being executed
    InProgress,
    /// Task completed successfully
    Completed,
    /// Task failed with an error
    Failed,
    /// Task was cancelled
    Cancelled,
}

impl TaskStatus {
    /// Parse from string (for deserialization)
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "pending" => Some(TaskStatus::Pending),
            "in_progress" | "inprogress" | "in-progress" => Some(TaskStatus::InProgress),
            "completed" | "done" | "complete" => Some(TaskStatus::Completed),
            "failed" | "error" => Some(TaskStatus::Failed),
            "cancelled" | "canceled" => Some(TaskStatus::Cancelled),
            _ => None,
        }
    }

    /// Convert to string (for serialization)
    pub fn as_str(&self) -> &'static str {
        match self {
            TaskStatus::Pending => "pending",
            TaskStatus::InProgress => "in_progress",
            TaskStatus::Completed => "completed",
            TaskStatus::Failed => "failed",
            TaskStatus::Cancelled => "cancelled",
        }
    }
}

/// A task in the workflow system
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    /// Unique task identifier
    pub id: TaskId,
    /// Short task title
    pub subject: String,
    /// Detailed task description
    pub description: String,
    /// Current task status
    pub status: TaskStatus,
    /// Tasks that must complete before this one (blockers)
    pub blocked_by: Vec<TaskId>,
    /// Tasks that depend on this one (blocking)
    pub blocks: Vec<TaskId>,
    /// Task creation timestamp (RFC3339)
    pub created_at: String,
    /// Task completion timestamp (optional)
    pub completed_at: Option<String>,
    /// Agent assigned to this task (optional)
    pub owner: Option<String>,
    /// Task metadata (JSON string)
    pub metadata: Option<String>,
}

/// Thread-safe task store with SQLite persistence
pub struct TaskStore {
    conn: Arc<Mutex<Connection>>,
}

impl TaskStore {
    /// Create a new task store with SQLite backend
    ///
    /// # Arguments
    /// * `db_path` - Path to SQLite database file
    ///
    /// # Returns
    /// * `CoreResult<TaskStore>` - The task store or error
    pub fn new<P: AsRef<Path>>(db_path: P) -> CoreResult<Self> {
        let db_path = db_path.as_ref();
        info!("Creating TaskStore at {:?}", db_path);

        // Ensure parent directory exists
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent)?;
        }

        let conn = Connection::open(db_path)?;

        // Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL", [])?;

        // Create tasks table if not exists
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL,
                blocked_by TEXT,  -- JSON array
                blocks TEXT,      -- JSON array
                created_at TEXT NOT NULL,
                completed_at TEXT,
                owner TEXT,
                metadata TEXT     -- JSON object
            )",
            [],
        )?;

        // Create index on status for faster queries
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)",
            [],
        )?;

        debug!("TaskStore initialized successfully");

        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    /// Create a new task
    pub fn create_task(&self, task: &Task) -> CoreResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            CoreError::TaskStore(format!("Mutex lock failed: {}", e))
        })?;

        let blocked_by_json = serde_json::to_string(&task.blocked_by)?;
        let blocks_json = serde_json::to_string(&task.blocks)?;

        conn.execute(
            "INSERT INTO tasks (id, subject, description, status, blocked_by, blocks, created_at, completed_at, owner, metadata)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
            params![
                task.id,
                task.subject,
                task.description,
                task.status.as_str(),
                blocked_by_json,
                blocks_json,
                task.created_at,
                task.completed_at,
                task.owner,
                task.metadata,
            ],
        )?;

        debug!("Created task: {}", task.id);
        Ok(())
    }

    /// Update an existing task
    pub fn update_task(&self, task: &Task) -> CoreResult<()> {
        let conn = self.conn.lock().map_err(|e| {
            CoreError::TaskStore(format!("Mutex lock failed: {}", e))
        })?;

        let blocked_by_json = serde_json::to_string(&task.blocked_by)?;
        let blocks_json = serde_json::to_string(&task.blocks)?;

        conn.execute(
            "UPDATE tasks SET subject=?1, description=?2, status=?3, blocked_by=?4, blocks=?5, completed_at=?6, owner=?7, metadata=?8
             WHERE id=?9",
            params![
                task.subject,
                task.description,
                task.status.as_str(),
                blocked_by_json,
                blocks_json,
                task.completed_at,
                task.owner,
                task.metadata,
                task.id,
            ],
        )?;

        debug!("Updated task: {}", task.id);
        Ok(())
    }

    /// Get a task by ID
    pub fn get_task(&self, id: &TaskId) -> CoreResult<Option<Task>> {
        let conn = self.conn.lock().map_err(|e| {
            CoreError::TaskStore(format!("Mutex lock failed: {}", e))
        })?;

        let mut stmt = conn.prepare(
            "SELECT id, subject, description, status, blocked_by, blocks, created_at, completed_at, owner, metadata
             FROM tasks WHERE id=?1"
        )?;

        let mut rows = stmt.query_map(params![id], |row| {
            let blocked_by_str: String = row.get(4)?;
            let blocks_str: String = row.get(5)?;

            Ok(Task {
                id: row.get(0)?,
                subject: row.get(1)?,
                description: row.get(2)?,
                status: TaskStatus::from_str(&row.get::<_, String>(3)?)
                    .unwrap_or(TaskStatus::Pending),
                blocked_by: serde_json::from_str(&blocked_by_str).unwrap_or_default(),
                blocks: serde_json::from_str(&blocks_str).unwrap_or_default(),
                created_at: row.get(6)?,
                completed_at: row.get(7)?,
                owner: row.get(8)?,
                metadata: row.get(9)?,
            })
        })?;

        match rows.next() {
            Some(Ok(task)) => Ok(Some(task)),
            Some(Err(e)) => Err(CoreError::TaskStore(format!("Query failed: {}", e))),
            None => Ok(None),
        }
    }

    /// List all tasks, optionally filtered by status
    pub fn list_tasks(&self, status: Option<TaskStatus>) -> CoreResult<Vec<Task>> {
        let conn = self.conn.lock().map_err(|e| {
            CoreError::TaskStore(format!("Mutex lock failed: {}", e))
        })?;

        let tasks = if let Some(status_filter) = status {
            let mut stmt = conn.prepare(
                "SELECT id, subject, description, status, blocked_by, blocks, created_at, completed_at, owner, metadata
                 FROM tasks WHERE status=?1"
            )?;

            let rows = stmt.query_map(params![status_filter.as_str()], |row| {
                let blocked_by_str: String = row.get(4)?;
                let blocks_str: String = row.get(5)?;

                Ok(Task {
                    id: row.get(0)?,
                    subject: row.get(1)?,
                    description: row.get(2)?,
                    status: TaskStatus::from_str(&row.get::<_, String>(3)?)
                        .unwrap_or(TaskStatus::Pending),
                    blocked_by: serde_json::from_str(&blocked_by_str).unwrap_or_default(),
                    blocks: serde_json::from_str(&blocks_str).unwrap_or_default(),
                    created_at: row.get(6)?,
                    completed_at: row.get(7)?,
                    owner: row.get(8)?,
                    metadata: row.get(9)?,
                })
            })?;

            let tasks = rows.collect::<Result<Vec<_>, _>>()
                .map_err(|e| CoreError::TaskStore(format!("Query failed: {}", e)))?;
            tasks
        } else {
            let mut stmt = conn.prepare(
                "SELECT id, subject, description, status, blocked_by, blocks, created_at, completed_at, owner, metadata
                 FROM tasks"
            )?;

            let rows = stmt.query_map([], |row| {
                let blocked_by_str: String = row.get(4)?;
                let blocks_str: String = row.get(5)?;

                Ok(Task {
                    id: row.get(0)?,
                    subject: row.get(1)?,
                    description: row.get(2)?,
                    status: TaskStatus::from_str(&row.get::<_, String>(3)?)
                        .unwrap_or(TaskStatus::Pending),
                    blocked_by: serde_json::from_str(&blocked_by_str).unwrap_or_default(),
                    blocks: serde_json::from_str(&blocks_str).unwrap_or_default(),
                    created_at: row.get(6)?,
                    completed_at: row.get(7)?,
                    owner: row.get(8)?,
                    metadata: row.get(9)?,
                })
            })?;

            let tasks = rows.collect::<Result<Vec<_>, _>>()
                .map_err(|e| CoreError::TaskStore(format!("Query failed: {}", e)))?;
            tasks
        };

        Ok(tasks)
    }

    /// Delete a task by ID
    pub fn delete_task(&self, id: &TaskId) -> CoreResult<bool> {
        let conn = self.conn.lock().map_err(|e| {
            CoreError::TaskStore(format!("Mutex lock failed: {}", e))
        })?;

        let rows_affected = conn.execute("DELETE FROM tasks WHERE id=?1", params![id])?;

        debug!("Deleted task: {} (rows affected: {})", id, rows_affected);
        Ok(rows_affected > 0)
    }

    /// Count tasks by status
    pub fn count_tasks(&self, status: Option<TaskStatus>) -> CoreResult<usize> {
        let conn = self.conn.lock().map_err(|e| {
            CoreError::TaskStore(format!("Mutex lock failed: {}", e))
        })?;

        let count: i64 = if let Some(status_filter) = status {
            conn.query_row(
                "SELECT COUNT(*) FROM tasks WHERE status=?1",
                params![status_filter.as_str()],
                |row| row.get(0),
            )?
        } else {
            conn.query_row("SELECT COUNT(*) FROM tasks", [], |row| row.get(0))?
        };

        Ok(count as usize)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_task_store_crud() {
        let dir = tempdir().unwrap();
        let db_path = dir.path().join("test.db");
        let store = TaskStore::new(&db_path).unwrap();

        // Create task
        let task = Task {
            id: "test123".to_string(),
            subject: "Test Task".to_string(),
            description: "Test description".to_string(),
            status: TaskStatus::Pending,
            blocked_by: vec![],
            blocks: vec![],
            created_at: "2024-03-24T10:00:00Z".to_string(),
            completed_at: None,
            owner: None,
            metadata: None,
        };

        store.create_task(&task).unwrap();

        // Get task
        let retrieved = store.get_task(&task.id).unwrap().unwrap();
        assert_eq!(retrieved.id, task.id);
        assert_eq!(retrieved.subject, task.subject);

        // Update task
        let mut updated = task.clone();
        updated.status = TaskStatus::Completed;
        updated.completed_at = Some("2024-03-24T11:00:00Z".to_string());
        store.update_task(&updated).unwrap();

        let retrieved = store.get_task(&task.id).unwrap().unwrap();
        assert_eq!(retrieved.status, TaskStatus::Completed);
        assert!(retrieved.completed_at.is_some());

        // Delete task
        assert!(store.delete_task(&task.id).unwrap());
        assert!(store.get_task(&task.id).unwrap().is_none());
    }
}
