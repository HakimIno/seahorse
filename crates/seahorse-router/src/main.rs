use std::sync::Arc;

use seahorse_core::{spawn_worker_loop, Config, SeahorseCore};
use seahorse_ffi::agent::make_py_runner;
use seahorse_router::build_router;
use tracing::info;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Init structured JSON logging
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let config = Config::from_env()?;
    let port = config.http_port;

    let (core, task_rx) = SeahorseCore::new(config);
    let core = Arc::new(core);

    // ── Spawn worker loop ───────────────────────────────────────────────────
    // PyPlannerRunner calls Python ReActPlanner via PyO3 in spawn_blocking threads.
    // Model can be overridden via SEAHORSE_LLM_MODEL env var.
    let model = std::env::var("SEAHORSE_LLM_MODEL")
        .unwrap_or_else(|_| "claude-3-5-sonnet-20241022".to_string());
    let max_steps = std::env::var("SEAHORSE_MAX_STEPS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(10_usize);

    let runner = make_py_runner(&model, max_steps);
    let _worker_handle = spawn_worker_loop(task_rx, runner);

    info!(model = %model, max_steps, "worker loop spawned");

    // ── HTTP server ─────────────────────────────────────────────────────────
    let router = build_router(core);
    let addr = format!("0.0.0.0:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await?;

    info!(addr = %addr, "seahorse-router listening");
    axum::serve(listener, router).await?;
    Ok(())
}
