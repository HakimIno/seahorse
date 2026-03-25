//! Task Store FFI — PyO3 bindings for task tracking from Python.

use seahorse_core::{Task, TaskStatus, TaskStore};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Arc;

/// Python wrapper for TaskStore
#[pyclass(name = "PyTaskStore")]
pub struct PyTaskStore {
    inner: Arc<TaskStore>,
}

#[pymethods]
impl PyTaskStore {
    /// Create a new task store with SQLite backend
    ///
    /// Args:
    ///     db_path: Path to SQLite database file
    ///
    /// Returns:
    ///     PyTaskStore instance
    #[new]
    fn new(db_path: String) -> PyResult<Self> {
        let store = TaskStore::new(&db_path).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to create TaskStore: {}",
                e
            ))
        })?;

        Ok(Self { inner: Arc::new(store) })
    }

    /// Create a new task
    ///
    /// Args:
    ///     id: Unique task identifier
    ///     subject: Short task title
    ///     description: Detailed task description
    ///     owner: Optional agent assigned to this task
    ///     metadata: Optional JSON metadata string
    ///
    /// Returns:
    ///     None (raises exception on error)
    fn create_task(
        &self,
        id: String,
        subject: String,
        description: String,
        owner: Option<String>,
        metadata: Option<String>,
    ) -> PyResult<()> {
        // Generate timestamp
        let now = chrono::Utc::now().to_rfc3339();

        let task = Task {
            id,
            subject,
            description,
            status: TaskStatus::Pending,
            blocked_by: vec![],
            blocks: vec![],
            created_at: now,
            completed_at: None,
            owner,
            metadata,
        };

        self.inner.create_task(&task).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to create task: {}",
                e
            ))
        })?;

        Ok(())
    }

    /// Update task status
    ///
    /// Args:
    ///     id: Task identifier
    ///     status: New status ("pending", "in_progress", "completed", "failed", "cancelled")
    ///     owner: Optional new owner
    ///
    /// Returns:
    ///     None (raises exception on error)
    fn update_task_status(
        &self,
        id: String,
        status: String,
        owner: Option<String>,
    ) -> PyResult<()> {
        // Get existing task
        let mut task = self.inner.get_task(&id).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to get task: {}",
                e
            ))
        })?
        .ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyLookupError, _>(format!(
                "Task not found: {}",
                id
            ))
        })?;

        // Update status
        task.status = TaskStatus::from_str(&status)
            .ok_or_else(|| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "Invalid status: {}",
                    status
                ))
            })?;

        // Update owner if provided
        if let Some(new_owner) = owner {
            task.owner = Some(new_owner);
        }

        // Set completed_at if status is completed/failed/cancelled
        if matches!(task.status, TaskStatus::Completed | TaskStatus::Failed | TaskStatus::Cancelled) {
            if task.completed_at.is_none() {
                task.completed_at = Some(chrono::Utc::now().to_rfc3339());
            }
        }

        self.inner.update_task(&task).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to update task: {}",
                e
            ))
        })?;

        Ok(())
    }

    /// Get a task by ID
    ///
    /// Args:
    ///     id: Task identifier
    ///
    /// Returns:
    ///     Dictionary with task data or None
    fn get_task(&self, id: String) -> PyResult<Option<PyObject>> {
        let task = self
            .inner
            .get_task(&id)
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "Failed to get task: {}",
                    e
                ))
            })?;

        match task {
            Some(t) => {
                Python::with_gil(|py| {
                    let dict = PyDict::new_bound(py);
                    dict.set_item("id", t.id)?;
                    dict.set_item("subject", t.subject)?;
                    dict.set_item("description", t.description)?;
                    dict.set_item("status", t.status.as_str())?;
                    dict.set_item("blocked_by", t.blocked_by)?;
                    dict.set_item("blocks", t.blocks)?;
                    dict.set_item("created_at", t.created_at)?;
                    dict.set_item("completed_at", t.completed_at)?;
                    dict.set_item("owner", t.owner)?;
                    dict.set_item("metadata", t.metadata)?;
                    Ok(Some(dict.into_any().unbind()))
                })
            }
            None => Ok(None),
        }
    }

    /// List all tasks
    ///
    /// Args:
    ///     status: Optional status filter ("pending", "in_progress", "completed", etc.)
    ///
    /// Returns:
    ///     List of task dictionaries
    fn list_tasks(&self, status: Option<String>) -> PyResult<Vec<PyObject>> {
        let status_filter = status.and_then(|s| TaskStatus::from_str(&s));

        let tasks = self
            .inner
            .list_tasks(status_filter)
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "Failed to list tasks: {}",
                    e
                ))
            })?;

        Python::with_gil(|py| {
            let result = tasks
                .into_iter()
                .map(|t| {
                    let dict = PyDict::new_bound(py);
                    dict.set_item("id", t.id)?;
                    dict.set_item("subject", t.subject)?;
                    dict.set_item("description", t.description)?;
                    dict.set_item("status", t.status.as_str())?;
                    dict.set_item("blocked_by", t.blocked_by)?;
                    dict.set_item("blocks", t.blocks)?;
                    dict.set_item("created_at", t.created_at)?;
                    dict.set_item("completed_at", t.completed_at)?;
                    dict.set_item("owner", t.owner)?;
                    dict.set_item("metadata", t.metadata)?;
                    Ok::<_, PyErr>(dict.into_any().unbind())
                })
                .collect::<Result<Vec<_>, _>>()?;

            Ok(result)
        })
    }

    /// Delete a task
    ///
    /// Args:
    ///     id: Task identifier
    ///
    /// Returns:
    ///     True if deleted, False if not found
    fn delete_task(&self, id: String) -> PyResult<bool> {
        self.inner.delete_task(&id).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to delete task: {}",
                e
            ))
        })
    }

    /// Count tasks by status
    ///
    /// Args:
    ///     status: Optional status filter
    ///
    /// Returns:
    ///     Number of tasks
    fn count_tasks(&self, status: Option<String>) -> PyResult<usize> {
        let status_filter = status.and_then(|s| TaskStatus::from_str(&s));

        self.inner
            .count_tasks(status_filter)
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "Failed to count tasks: {}",
                    e
                ))
            })
    }

    /// Get available tasks (not blocked and not completed)
    ///
    /// Returns:
    ///     List of task dictionaries that can be executed
    fn get_available_tasks(&self) -> PyResult<Vec<PyObject>> {
        // Get all pending tasks
        let tasks = self
            .inner
            .list_tasks(Some(TaskStatus::Pending))
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "Failed to get available tasks: {}",
                    e
                ))
            })?;

        // Filter out tasks that are blocked
        let available: Vec<_> = tasks
            .into_iter()
            .filter(|t| t.blocked_by.is_empty())
            .collect();

        Python::with_gil(|py| {
            let result = available
                .into_iter()
                .map(|t| {
                    let dict = PyDict::new_bound(py);
                    dict.set_item("id", t.id)?;
                    dict.set_item("subject", t.subject)?;
                    dict.set_item("description", t.description)?;
                    dict.set_item("status", t.status.as_str())?;
                    dict.set_item("created_at", t.created_at)?;
                    dict.set_item("owner", t.owner)?;
                    Ok::<_, PyErr>(dict.into_any().unbind())
                })
                .collect::<Result<Vec<_>, _>>()?;

            Ok(result)
        })
    }

    /// Set task dependencies
    ///
    /// Args:
    ///     task_id: Task to set dependencies for
    ///     blocked_by: List of task IDs that must complete first
    ///
    /// Returns:
    ///     None (raises exception on error)
    fn set_dependencies(&self, task_id: String, blocked_by: Vec<String>) -> PyResult<()> {
        let mut task = self.inner.get_task(&task_id).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to get task: {}",
                e
            ))
        })?
        .ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyLookupError, _>(format!(
                "Task not found: {}",
                task_id
            ))
        })?;

        // Update blocked_by
        task.blocked_by = blocked_by;

        // Update the blocking tasks' blocks lists
        for blocker_id in &task.blocked_by {
            if let Some(mut blocker) = self.inner.get_task(blocker_id).unwrap() {
                if !blocker.blocks.contains(&task_id) {
                    blocker.blocks.push(task_id.clone());
                    self.inner.update_task(&blocker).map_err(|e| {
                        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                            "Failed to update blocker task: {}",
                            e
                        ))
                    })?;
                }
            }
        }

        // Save the task
        self.inner.update_task(&task).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to update task: {}",
                e
            ))
        })?;

        Ok(())
    }
}
