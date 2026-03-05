//! JWT Bearer token authentication for Seahorse Router.
//!
//! # Overview
//!
//! Every request to `/v1/*` must carry a valid HS256 JWT in the HTTP header:
//!
//! ```text
//! Authorization: Bearer <token>
//! ```
//!
//! The token is validated against `SEAHORSE_JWT_SECRET` (required env var).
//! If the env var is not set, the server refuses to start.
//!
//! # Token issuing (external)
//!
//! Seahorse does NOT contain a login/register endpoint — that is your
//! responsibility.  Any system that knows the secret can issue tokens:
//!
//! ```bash
//! # Quick token for dev (Python one-liner)
//! uv run python -c "
//! import jwt, datetime, os
//! secret = os.environ['SEAHORSE_JWT_SECRET']
//! payload = {
//!     'sub': 'dev-user',
//!     'iat': datetime.datetime.utcnow(),
//!     'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7),
//! }
//! print(jwt.encode(payload, secret, algorithm='HS256'))
//! "
//! ```
//!
//! # Disabling auth for local dev
//!
//! Set `SEAHORSE_AUTH_DISABLED=1` to skip JWT checks entirely.
//! **Never use this in production.**

use axum::{
    async_trait,
    extract::FromRequestParts,
    http::{request::Parts, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use jsonwebtoken::{decode, DecodingKey, Validation};
use once_cell::sync::OnceCell;
use serde::{Deserialize, Serialize};
use serde_json::json;
use tracing::{debug, warn};

// ── JWT claims ────────────────────────────────────────────────────────────────

/// Claims embedded in each JWT.
///
/// Only `sub` and `exp` are mandatory; anything else is optional context.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Claims {
    /// Subject — usually a user or service identifier.
    pub sub: String,
    /// Expiry (Unix timestamp, seconds).
    pub exp: i64,
    /// Issued-at (optional, for logging).
    pub iat: Option<i64>,
}

// ── Global secret ─────────────────────────────────────────────────────────────

static JWT_SECRET: OnceCell<String> = OnceCell::new();
static AUTH_DISABLED: OnceCell<bool> = OnceCell::new();

/// Initialise the JWT secret from `SEAHORSE_JWT_SECRET`.
///
/// Must be called once at startup, before the HTTP server begins accepting
/// requests.  Returns an error if the env var is missing (and auth is enabled).
pub fn init_jwt() -> anyhow::Result<()> {
    let disabled = std::env::var("SEAHORSE_AUTH_DISABLED")
        .unwrap_or_default()
        .trim()
        == "1";
    AUTH_DISABLED.set(disabled).ok();

    if disabled {
        tracing::warn!(
            "⚠️  JWT auth DISABLED (SEAHORSE_AUTH_DISABLED=1). Do not use in production!"
        );
        return Ok(());
    }

    let secret = std::env::var("SEAHORSE_JWT_SECRET").map_err(|_| {
        anyhow::anyhow!(
            "SEAHORSE_JWT_SECRET env var is required when auth is enabled. \
             Set it to a long random string (e.g. `openssl rand -hex 32`), \
             or set SEAHORSE_AUTH_DISABLED=1 for local development."
        )
    })?;

    if secret.len() < 32 {
        tracing::warn!(
            "SEAHORSE_JWT_SECRET is shorter than 32 chars — use a longer secret in production"
        );
    }

    JWT_SECRET.set(secret).ok();
    tracing::info!("JWT auth initialised (HS256)");
    Ok(())
}

// ── Extractor ─────────────────────────────────────────────────────────────────

/// Axum extractor that validates the `Authorization: Bearer <token>` header.
///
/// Use it as a handler parameter to require auth on specific routes:
///
/// ```rust
/// async fn my_handler(auth: AuthenticatedUser, ...) -> impl IntoResponse { ... }
/// ```
///
/// Or protect an entire route group via
/// [`require_auth`] as a nested router layer.
#[derive(Debug, Clone)]
pub struct AuthenticatedUser {
    pub claims: Claims,
}

#[async_trait]
impl<S> FromRequestParts<S> for AuthenticatedUser
where
    S: Send + Sync,
{
    type Rejection = AuthError;

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        // Short-circuit when auth is disabled
        if AUTH_DISABLED.get().copied().unwrap_or(false) {
            return Ok(AuthenticatedUser {
                claims: Claims {
                    sub: "anonymous".to_string(),
                    exp: i64::MAX,
                    iat: None,
                },
            });
        }

        // Extract Bearer token from Authorization header
        let auth_header = parts
            .headers
            .get("Authorization")
            .and_then(|v| v.to_str().ok())
            .ok_or(AuthError::MissingToken)?;

        let token = auth_header
            .strip_prefix("Bearer ")
            .ok_or(AuthError::MalformedToken)?;

        // Validate the token
        let secret = JWT_SECRET.get().ok_or(AuthError::ServerError)?;
        let key = DecodingKey::from_secret(secret.as_bytes());
        let mut validation = Validation::new(jsonwebtoken::Algorithm::HS256);
        validation.validate_exp = true;

        match decode::<Claims>(token, &key, &validation) {
            Ok(data) => {
                debug!(sub = %data.claims.sub, "JWT validated");
                Ok(AuthenticatedUser { claims: data.claims })
            }
            Err(err) => {
                warn!("JWT validation failed: {err}");
                Err(AuthError::InvalidToken)
            }
        }
    }
}

// ── Error type ────────────────────────────────────────────────────────────────

/// Authentication errors returned as HTTP 401 / 403 JSON responses.
#[derive(Debug, thiserror::Error)]
pub enum AuthError {
    #[error("missing Authorization header")]
    MissingToken,
    #[error("malformed Authorization header (expected 'Bearer <token>')")]
    MalformedToken,
    #[error("invalid or expired JWT")]
    InvalidToken,
    #[error("server auth configuration error")]
    ServerError,
}

impl IntoResponse for AuthError {
    fn into_response(self) -> Response {
        let (status, code, message) = match &self {
            AuthError::MissingToken => (
                StatusCode::UNAUTHORIZED,
                "missing_token",
                self.to_string(),
            ),
            AuthError::MalformedToken => (
                StatusCode::UNAUTHORIZED,
                "malformed_token",
                self.to_string(),
            ),
            AuthError::InvalidToken => (
                StatusCode::UNAUTHORIZED,
                "invalid_token",
                self.to_string(),
            ),
            AuthError::ServerError => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "server_error",
                self.to_string(),
            ),
        };

        (
            status,
            Json(json!({ "error": code, "message": message })),
        )
            .into_response()
    }
}
