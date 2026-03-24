//! HTTP Client for Router Communication
//!
//! Provides:
//! - HTTP client with JWT authentication
//! - SSE streaming for real-time responses
//! - Connection pooling and retry logic

pub mod streaming;
pub mod auth;

#[allow(unused_imports)]
pub use streaming::StreamingClient;
#[allow(unused_imports)]
pub use auth::AuthClient;

use color_eyre::Result;
use reqwest::Client;
use std::sync::Arc;

/// HTTP client wrapper
#[derive(Clone)]
pub struct RouterClient {
    /// Reqwest client
    http: Arc<Client>,

    /// Router base URL
    base_url: String,

    /// JWT token
    jwt_token: Arc<tokio::sync::Mutex<Option<String>>>,
}

impl RouterClient {
    /// Create new router client
    pub fn new(base_url: String) -> Result<Self> {
        let http = Client::builder()
            .pool_max_idle_per_host(10)
            .build()?;

        Ok(Self {
            http: Arc::new(http),
            base_url,
            jwt_token: Arc::new(tokio::sync::Mutex::new(None)),
        })
    }

    /// Set JWT token
    #[allow(dead_code)]
    pub async fn set_token(&self, token: String) {
        let mut jwt = self.jwt_token.lock().await;
        *jwt = Some(token);
    }

    /// Get JWT token
    pub async fn get_token(&self) -> Option<String> {
        let jwt = self.jwt_token.lock().await;
        jwt.clone()
    }

    /// Get base URL
    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    /// Get HTTP client
    pub fn http(&self) -> &Client {
        &self.http
    }

    /// Build authenticated request
    #[allow(dead_code)]
    pub async fn authenticated_request(
        &self,
        path: &str,
    ) -> Result<reqwest::RequestBuilder> {
        let mut request = self.http.get(format!("{}{}", self.base_url, path));

        if let Some(token) = self.get_token().await {
            request = request.header("Authorization", format!("Bearer {}", token));
        }

        Ok(request)
    }
}
