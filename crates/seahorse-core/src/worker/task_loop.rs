use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::scheduler::AgentTask;
use crate::worker::runner::PythonRunner;
use crate::worker::supervisor::HeartbeatSupervisor;

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
            supervisor.track(task_id.clone()).await;

            let task_id_clone = task_id.clone();
            let token_tx = task.response_tx.clone();

            // Run the async runner directly with a 120-second timeout
            let run_future = runner.run(
                &task.id,
                &task.agent_id,
                &task.prompt,
                &task.history,
                token_tx,
            );

            match tokio::time::timeout(std::time::Duration::from_secs(120), run_future).await {
                Ok(result) => {
                    match result {
                        Ok(full_response) => {
                            info!(
                                task_id = %task_id_clone,
                                response_len = full_response.len(),
                                "task completed"
                            );
                            // Send the full final response as the last token
                            if let Err(e) = task.response_tx.send(full_response).await {
                                warn!(task_id = %task_id_clone, err = %e, "channel closed early");
                            }
                        }
                        Err(e) => {
                            error!(task_id = %task_id_clone, err = %e, "task failed");
                            let _ = task.response_tx.send(format!(
                                "[ERROR] Agent task failed: {e}"
                            )).await;
                        }
                    }
                }
                Err(_) => {
                    error!(task_id = %task_id_clone, "task completely stalled. Tokio timeout reached! (>120s)");
                    let _ = task.response_tx.send(format!(
                        "[ERROR] Agent task timed out after 120 seconds"
                    )).await;
                }
            }
            
            supervisor.untrack(&task_id).await;
        }
        info!("worker loop exiting — task channel closed");
    })
}
