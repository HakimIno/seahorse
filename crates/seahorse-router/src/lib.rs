//! Seahorse Router — Axum HTTP gateway for the Seahorse Agent.
#![warn(clippy::all, clippy::pedantic)]
#![allow(clippy::must_use_candidate, clippy::module_name_repetitions)]

pub mod auth;
pub mod error;
pub mod handlers;

use std::sync::Arc;

use axum::{
    middleware,
    routing::{get, post},
    Extension, Router,
};
use tower_http::trace::TraceLayer;
use tower_http::cors::{CorsLayer, Any};

use seahorse_core::SeahorseCore;

/// Build the Axum router wired to the given [`SeahorseCore`].
///
/// Route protection:
/// - `GET /health`           — public (no auth)
/// - `POST /v1/*`            — requires valid JWT Bearer token
pub fn build_router(core: Arc<SeahorseCore>) -> Router {
    // Protected v1 routes — every request passes through AuthenticatedUser extractor
    let v1 = Router::new()
        .route("/v1/agent/run",     post(handlers::run_agent))
        .route("/v1/agent/stream",  post(handlers::stream_agent))
        .route("/v1/memory/search", post(handlers::memory_search))
        .route_layer(middleware::from_fn(auth_layer));

    Router::new()
        .route("/health", get(handlers::health))
        .merge(v1)
        .layer(Extension(core))
        .layer(TraceLayer::new_for_http())
        .layer(CorsLayer::new().allow_origin(Any).allow_methods(Any).allow_headers(Any))
}

/// Tower middleware function that validates JWT on every request.
///
/// Delegates to the `AuthenticatedUser` extractor; if the extractor
/// returns an error, the middleware replies immediately with 401.
async fn auth_layer(
    req: axum::http::Request<axum::body::Body>,
    next: axum::middleware::Next,
) -> axum::response::Response {
    use axum::extract::FromRequestParts;
    use auth::{AuthenticatedUser, AuthError};

    let (mut parts, body) = req.into_parts();

    match AuthenticatedUser::from_request_parts(&mut parts, &()).await {
        Ok(user) => {
            tracing::debug!(sub = %user.claims.sub, "request authenticated");
            // Re-assemble request and forward
            let req = axum::http::Request::from_parts(parts, body);
            next.run(req).await
        }
        Err(err @ AuthError::MissingToken)
        | Err(err @ AuthError::MalformedToken)
        | Err(err @ AuthError::InvalidToken)
        | Err(err @ AuthError::ServerError) => {
            use axum::response::IntoResponse;
            err.into_response()
        }
    }
}
