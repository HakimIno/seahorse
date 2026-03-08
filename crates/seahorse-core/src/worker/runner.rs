use tokio::sync::mpsc;
use crate::error::CoreResult;

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
