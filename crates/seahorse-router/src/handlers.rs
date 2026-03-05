use std::sync::Arc;

use axum::{
    extract::Extension,
    http::StatusCode,
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse,
    },
    Json,
};
use futures_util::stream::StreamExt;
use serde::{Deserialize, Serialize};
use tokio_stream::wrappers::ReceiverStream;
use tracing::instrument;

use seahorse_core::SeahorseCore;

use crate::error::AppError;

/// Minimal agent run request.
#[derive(Debug, Deserialize)]
pub struct RunRequest {
    pub prompt: String,
}

/// Synchronous agent response.
#[derive(Debug, Serialize)]
pub struct RunResponse {
    pub task_id: String,
    pub status: &'static str,
}

/// Health check — always returns 200 OK.
pub async fn health() -> impl IntoResponse {
    (StatusCode::OK, Json(serde_json::json!({ "status": "ok", "service": "seahorse-router" })))
}

/// Submit an agent task (fire-and-forget; returns task_id).
#[instrument(skip(core, req))]
pub async fn run_agent(
    Extension(core): Extension<Arc<SeahorseCore>>,
    Json(req): Json<RunRequest>,
) -> Result<Json<RunResponse>, AppError> {
    if req.prompt.is_empty() {
        return Err(AppError::BadRequest("prompt must not be empty".into()));
    }

    let (task_id, _rx) = core
        .scheduler
        .submit(req.prompt)
        .await?;

    Ok(Json(RunResponse {
        task_id,
        status: "queued",
    }))
}

/// Stream agent tokens via SSE.
#[instrument(skip(core, req))]
pub async fn stream_agent(
    Extension(core): Extension<Arc<SeahorseCore>>,
    Json(req): Json<RunRequest>,
) -> Result<Sse<impl futures_util::Stream<Item = Result<Event, std::convert::Infallible>>>, AppError>
{
    if req.prompt.is_empty() {
        return Err(AppError::BadRequest("prompt must not be empty".into()));
    }

    let (_task_id, rx) = core.scheduler.submit(req.prompt).await?;

    let token_stream = ReceiverStream::new(rx)
        .map(|token| Ok(Event::default().data(token)));

    Ok(Sse::new(token_stream).keep_alive(KeepAlive::default()))
}

/// Memory search endpoint.
pub async fn memory_search(
    Extension(core): Extension<Arc<SeahorseCore>>,
    Json(req): Json<MemorySearchRequest>,
) -> Result<Json<MemorySearchResponse>, AppError> {
    if req.embedding.len() != core.config.embedding_dim {
        return Err(AppError::BadRequest(format!(
            "embedding dim mismatch: expected {}, got {}",
            core.config.embedding_dim,
            req.embedding.len()
        )));
    }

    let results = core
        .memory
        .search(&req.embedding, req.k.unwrap_or(5), req.ef.unwrap_or(100));

    Ok(Json(MemorySearchResponse { results }))
}

#[derive(Debug, Deserialize)]
pub struct MemorySearchRequest {
    pub embedding: Vec<f32>,
    pub k: Option<usize>,
    pub ef: Option<usize>,
}

#[derive(Debug, Serialize)]
pub struct MemorySearchResponse {
    pub results: Vec<(usize, f32)>,
}
