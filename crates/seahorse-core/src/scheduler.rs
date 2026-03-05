use tokio::sync::mpsc;
use tracing::{info, instrument};
use uuid::Uuid;

use crate::error::{CoreError, CoreResult};

/// A pending agent task.
#[derive(Debug)]
pub struct AgentTask {
    pub id: String,
    pub prompt: String,
    /// Channel to stream response tokens back to the caller.
    pub response_tx: mpsc::Sender<String>,
}

/// Manages concurrent agent task scheduling via a bounded Tokio channel.
pub struct AgentScheduler {
    task_tx: mpsc::Sender<AgentTask>,
}

impl AgentScheduler {
    /// Create scheduler with a worker loop that processes up to `capacity` queued tasks.
    pub fn new(capacity: usize) -> (Self, mpsc::Receiver<AgentTask>) {
        let (tx, rx) = mpsc::channel(capacity);
        (Self { task_tx: tx }, rx)
    }

    /// Submit a task to the scheduler.
    /// Returns a `Receiver` that will stream response tokens.
    #[instrument(skip(self, prompt), fields(prompt_len = prompt.len()))]
    pub async fn submit(&self, prompt: String) -> CoreResult<(String, mpsc::Receiver<String>)> {
        let id = Uuid::new_v4().to_string();
        let (response_tx, response_rx) = mpsc::channel(128);

        let task = AgentTask {
            id: id.clone(),
            prompt,
            response_tx,
        };

        self.task_tx
            .send(task)
            .await
            .map_err(|_| CoreError::ChannelClosed)?;

        info!(task_id = %id, "task submitted");
        Ok((id, response_rx))
    }
}
