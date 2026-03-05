//! Worker loop — consumes AgentTasks from the scheduler and runs them via Python.
//!
//! Architecture:
//!   mpsc::Receiver<AgentTask>
//!         │
//!   tokio::spawn (per task)
//!         │
//!   spawn_blocking  ← releases Tokio thread during Python call
//!         │
//!   PythonRunner::run()  ← calls Python via PyO3
//!         │
//!   task.response_tx.blocking_send(token)

use std::sync::Arc;

use tokio::sync::mpsc;
use tracing::{error, info, instrument, warn};

use crate::error::CoreResult;
use crate::scheduler::AgentTask;

// ── PythonRunner trait ────────────────────────────────────────────────────────

/// Abstraction over the Python AI layer.
/// Implemented by `seahorse-ffi::agent::PyPlannerRunner`.
/// Kept as a trait so unit tests can inject a mock.
pub trait PythonRunner: Send + Sync + 'static {
    /// Run a single agent turn.
    ///
    /// # Streaming
    /// Implementations **must** call `token_tx.blocking_send()` for every token
    /// they want to stream back. The channel has capacity 128.
    ///
    /// # Returns
    /// The final complete response string.
    fn run(
        &self,
        task_id: &str,
        prompt: &str,
        token_tx: mpsc::Sender<String>,
    ) -> CoreResult<String>;
}

// ── Worker loop ───────────────────────────────────────────────────────────────

/// Spawn the background worker loop that processes tasks from `task_rx`.
///
/// Each task is run in a `spawn_blocking` thread so the Tokio thread pool
/// is not blocked during Python/LLM execution.
pub fn spawn_worker_loop(
    mut task_rx: mpsc::Receiver<AgentTask>,
    runner: Arc<dyn PythonRunner>,
) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        info!("worker loop started");
        while let Some(task) = task_rx.recv().await {
            let runner = runner.clone();
            let task_id = task.id.clone();

            info!(task_id = %task_id, "worker picked up task");

            tokio::task::spawn_blocking(move || {
                // Clone the sender before calling into Python
                let token_tx = task.response_tx.clone();

                match runner.run(&task.id, &task.prompt, token_tx) {
                    Ok(full_response) => {
                        info!(
                            task_id = %task_id,
                            response_len = full_response.len(),
                            "task completed"
                        );
                        // Send the full final response as the last token
                        if let Err(e) = task.response_tx.blocking_send(full_response) {
                            warn!(task_id = %task_id, err = %e, "response channel closed early");
                        }
                    }
                    Err(e) => {
                        error!(task_id = %task_id, err = %e, "task failed");
                        let _ = task.response_tx.blocking_send(
                            format!("[ERROR] Agent task failed: {e}")
                        );
                    }
                }
            });
        }
        info!("worker loop exiting — task channel closed");
    })
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::error::CoreError;

    struct EchoPythonRunner;

    impl PythonRunner for EchoPythonRunner {
        fn run(
            &self,
            _task_id: &str,
            prompt: &str,
            _token_tx: mpsc::Sender<String>,
        ) -> CoreResult<String> {
            Ok(format!("Echo: {prompt}"))
        }
    }

    struct FailingPythonRunner;

    impl PythonRunner for FailingPythonRunner {
        fn run(
            &self,
            _task_id: &str,
            _prompt: &str,
            _token_tx: mpsc::Sender<String>,
        ) -> CoreResult<String> {
            Err(CoreError::ChannelClosed)
        }
    }

    #[tokio::test]
    async fn worker_echoes_response() {
        let (task_tx, task_rx) = mpsc::channel(8);
        let runner = Arc::new(EchoPythonRunner);
        let _handle = spawn_worker_loop(task_rx, runner);

        let (response_tx, mut response_rx) = mpsc::channel(128);
        task_tx
            .send(AgentTask {
                id: "t1".into(),
                prompt: "hello world".into(),
                response_tx,
            })
            .await
            .unwrap();

        let resp = response_rx.recv().await.unwrap();
        assert_eq!(resp, "Echo: hello world");
    }

    #[tokio::test]
    async fn worker_sends_error_on_runner_failure() {
        let (task_tx, task_rx) = mpsc::channel(8);
        let runner = Arc::new(FailingPythonRunner);
        let _handle = spawn_worker_loop(task_rx, runner);

        let (response_tx, mut response_rx) = mpsc::channel(128);
        task_tx
            .send(AgentTask {
                id: "t2".into(),
                prompt: "boom".into(),
                response_tx,
            })
            .await
            .unwrap();

        let resp = response_rx.recv().await.unwrap();
        assert!(resp.starts_with("[ERROR]"), "expected error prefix, got: {resp}");
    }
}
