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
use futures_util::stream::{BoxStream, StreamExt};
use serde::{Deserialize, Serialize};
use tokio_stream::wrappers::ReceiverStream;
use tracing::instrument;

use seahorse_core::SeahorseCore;

use crate::error::AppError;

/// Minimal agent run request.
#[derive(Debug, Deserialize)]
pub struct RunRequest {
    pub agent_id: String,
    pub prompt: String,
    pub history: Vec<seahorse_core::scheduler::Message>,
}

/// Synchronous agent response.
#[derive(Debug, Serialize)]
pub struct RunResponse {
    pub task_id: String,
    pub status: &'static str,
    pub content: Option<String>,
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

    if let Some(answer) = core.fast_path.try_respond(&req.prompt, &req.history).await {
        return Ok(Json(RunResponse {
            task_id: "fast-path".into(),
            status: "completed",
            content: Some(answer),
        }));
    }

    let (task_id, mut rx) = core
        .scheduler
        .submit(req.agent_id, req.prompt, req.history)
        .await?;

    let mut response_content = String::new();
    while let Some(token) = rx.recv().await {
        if token.starts_with("[ERROR]") {
            return Err(AppError::Internal(token));
        }
        if !token.starts_with("[DONE]") {
            // In synchronous mode, the worker loop sends the full response as the last token.
            // We overwrite response_content with each non-metadata token to ensure we get the final one.
            response_content = token;
        }
    }

    Ok(Json(RunResponse {
        task_id,
        status: "completed",
        content: Some(response_content),
    }))
}

/// Stream agent tokens via SSE.
#[instrument(skip(core, req))]
pub async fn stream_agent(
    Extension(core): Extension<Arc<SeahorseCore>>,
    Json(req): Json<RunRequest>,
) -> Result<Sse<BoxStream<'static, Result<Event, std::convert::Infallible>>>, AppError>
{
    if req.prompt.is_empty() {
        return Err(AppError::BadRequest("prompt must not be empty".into()));
    }

    if let Some(answer) = core.fast_path.try_respond(&req.prompt, &req.history).await {
        let (tx, rx) = tokio::sync::mpsc::channel(1);
        let _ = tx.send(answer).await;
        let token_stream = ReceiverStream::new(rx)
            .map(|token| Ok(Event::default().data(token)))
            .boxed();
        return Ok(Sse::new(token_stream).keep_alive(KeepAlive::default()));
    }

    let (_task_id, rx) = core
        .scheduler
        .submit(req.agent_id, req.prompt, req.history)
        .await?;

    let token_stream = ReceiverStream::new(rx)
        .map(|token| Ok(Event::default().data(token)))
        .boxed();

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
        .search(&req.embedding, req.k.unwrap_or(5), req.ef.unwrap_or(100))?;

    let hits = results.into_iter().map(|(id, dist, txt, meta)| MemoryHit {
        doc_id: id,
        distance: dist,
        text: txt,
        metadata: meta,
    }).collect();

    Ok(Json(MemorySearchResponse { results: hits }))
}

#[derive(Debug, Deserialize)]
pub struct MemorySearchRequest {
    pub embedding: Vec<f32>,
    pub k: Option<usize>,
    pub ef: Option<usize>,
}

#[derive(Debug, Serialize)]
pub struct MemoryHit {
    pub doc_id: usize,
    pub distance: f32,
    pub text: String,
    pub metadata: String,
}

#[derive(Debug, Serialize)]
pub struct MemorySearchResponse {
    pub results: Vec<MemoryHit>,
}
