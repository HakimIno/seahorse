mod telemetry;

use std::sync::Arc;

use seahorse_core::{spawn_worker_loop, Config, SeahorseCore};
use seahorse_ffi::graph_runner::make_arc_py_graph_runner;
use seahorse_router::{auth::init_jwt, build_router};
use tracing::info;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // ── Telemetry: JSON logs + OTel traces → Jaeger ─────────────────────────
    telemetry::init_telemetry()?;

    // ── JWT auth initialisation ──────────────────────────────────────────────
    init_jwt()?;

    let config = Config::from_env()?;
    let port = config.http_port;

    let (core, task_rx) = SeahorseCore::new(config);
    let core = Arc::new(core);

    // ── Spawn worker loop ───────────────────────────────────────────────────
    let model = std::env::var("SEAHORSE_LLM_MODEL")
        .unwrap_or_else(|_| "openrouter/google/gemini-3-flash-preview".to_string());

    let runner = make_arc_py_graph_runner(&model);
    let _worker_handle = spawn_worker_loop(task_rx, runner);

    info!(model = %model, "Graph worker loop spawned");

    // ── HTTP server ─────────────────────────────────────────────────────────
    let router = build_router(core);
    let addr = format!("0.0.0.0:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await?;

    info!(addr = %addr, "seahorse-router listening");

    tokio::spawn(async {
        if tokio::signal::ctrl_c().await.is_ok() {
            info!("Ctrl-C received! Forcefully shutting down...");
            telemetry::shutdown_telemetry();
            std::process::exit(0);
        }
    });

    axum::serve(listener, router).await?;

    telemetry::shutdown_telemetry();
    Ok(())
}
