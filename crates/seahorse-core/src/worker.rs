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

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use tokio::sync::mpsc;
use tracing::{error, info, warn};

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

    /// Check if the Python interpreter/runner is responsive.
    fn health_check(&self) -> CoreResult<()>;
}

// ── Supervisor ────────────────────────────────────────────────────────────────

struct HeartbeatSupervisor {
    active_tasks: Arc<Mutex<HashMap<String, Instant>>>,
    runner: Arc<dyn PythonRunner>,
}

impl HeartbeatSupervisor {
    fn new(runner: Arc<dyn PythonRunner>) -> Self {
        Self {
            active_tasks: Arc::new(Mutex::new(HashMap::new())),
            runner,
        }
    }

    fn start(&self) {
        let active_tasks = self.active_tasks.clone();
        let runner = self.runner.clone();
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(std::time::Duration::from_secs(30));
            loop {
                interval.tick().await;

                // 1. Health check
                if let Err(e) = runner.health_check() {
                    error!(err = %e, "Supervisor: Python health check failed!");
                }

                // 2. Identify stale tasks
                let now = Instant::now();
                let stale: Vec<String> = {
                    let guard = active_tasks.lock().unwrap();
                    guard
                        .iter()
                        .filter(|(_, &start)| now.duration_since(start).as_secs() > 300)
                        .map(|(id, _): (&String, &Instant)| id.clone())
                        .collect()
                };

                for id in stale {
                    warn!(task_id = %id, "Supervisor: task is stalling (> 5 mins)");
                }
            }
        });
    }

    fn track(&self, id: String) {
        self.active_tasks.lock().unwrap().insert(id, Instant::now());
    }

    fn untrack(&self, id: &str) {
        self.active_tasks.lock().unwrap().remove(id);
    }
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
    let supervisor = Arc::new(HeartbeatSupervisor::new(runner.clone()));
    supervisor.start();

    tokio::spawn(async move {
        info!("worker loop started");
        while let Some(task) = task_rx.recv().await {
            let runner = runner.clone();
            let supervisor = supervisor.clone();
            let task_id = task.id.clone();

            info!(task_id = %task_id, "worker picked up task");
            supervisor.track(task_id.clone());

            tokio::task::spawn_blocking(move || {
                // Clone the sender before calling into Python
                let token_tx = task.response_tx.clone();

                let result = runner.run(&task.id, &task.prompt, token_tx);
                supervisor.untrack(&task_id);

                match result {
                    Ok(full_response) => {
                        info!(
                            task_id = %task_id,
                            response_len = full_response.len(),
                            "task completed"
                        );
                        // Send the full final response as the last token
                        if let Err(e) = task.response_tx.blocking_send(full_response) {
                            warn!(task_id = %task_id, err = %e, "channel closed early");
                        }
                    }
                    Err(e) => {
                        error!(task_id = %task_id, err = %e, "task failed");
                        let _ = task.response_tx.blocking_send(format!(
                            "[ERROR] Agent task failed: {e}"
                        ));
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

        fn health_check(&self) -> CoreResult<()> {
            Ok(())
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

        fn health_check(&self) -> CoreResult<()> {
            Ok(())
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
