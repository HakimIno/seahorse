use std::num::NonZeroU32;
use std::sync::Arc;
use governor::{Quota, RateLimiter, state::DirectStateStore};
use reqwest::Client;
use serde_json::Value;
use tracing::{debug, info};
use crate::error::CoreResult;

/// Rate-limited HTTP client for external sports APIs.
pub struct NetworkClient {
    client: Client,
    limiter: governor::DefaultDirectRateLimiter,
}

impl NetworkClient {
    /// Create a new client with a specific rate limit (requests per minute).
    pub fn new(requests_per_minute: u32) -> Self {
        let quota = Quota::per_minute(NonZeroU32::new(requests_per_minute).unwrap());
        let limiter = RateLimiter::direct(quota);
        
        Self {
            client: Client::new(),
            limiter,
        }
    }

    /// Fetch data from a URL with rate limiting and optional Headers (like API Keys).
    pub async fn fetch_json(&self, url: &str, headers: Vec<(String, String)>) -> CoreResult<Value> {
        // Wait for rate limiter
        self.limiter.until_ready().await;
        
        debug!("Fetching: {}", url);
        let mut request = self.client.get(url);
        
        for (k, v) in headers {
            request = request.header(k, v);
        }

        let response = request.send().await.map_err(|e: reqwest::Error| crate::error::CoreError::Internal(e.to_string()))?;
        let json = response.json::<Value>().await.map_err(|e: reqwest::Error| crate::error::CoreError::Internal(e.to_string()))?;
        
        Ok(json)
    }
}

use once_cell::sync::Lazy;

/// Global instance of the rate-limited client for API-Football.
/// Default to 10 per minute as a safe starting point.
pub static FOOTBALL_CLIENT: Lazy<NetworkClient> = Lazy::new(|| NetworkClient::new(10));
