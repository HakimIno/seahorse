//! Seahorse Router — Axum HTTP gateway for the Seahorse Agent.
#![warn(clippy::all, clippy::pedantic)]
#![allow(clippy::must_use_candidate, clippy::module_name_repetitions)]

pub mod error;
pub mod handlers;

use std::sync::Arc;

use axum::{
    routing::{get, post},
    Extension, Router,
};
use tower_http::trace::TraceLayer;

use seahorse_core::SeahorseCore;

/// Build the Axum router wired to the given [`SeahorseCore`].
pub fn build_router(core: Arc<SeahorseCore>) -> Router {
    Router::new()
        .route("/health", get(handlers::health))
        .route("/v1/agent/run",        post(handlers::run_agent))
        .route("/v1/agent/stream",     post(handlers::stream_agent))
        .route("/v1/memory/search",    post(handlers::memory_search))
        .layer(Extension(core))
        .layer(TraceLayer::new_for_http())
}
