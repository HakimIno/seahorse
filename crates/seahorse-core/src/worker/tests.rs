use super::*;
use crate::error::{CoreError, CoreResult};
use crate::scheduler::AgentTask;
use std::sync::Arc;
use tokio::sync::mpsc;
use crate::worker::runner::PythonRunner;
use crate::worker::task_loop::spawn_worker_loop;

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
