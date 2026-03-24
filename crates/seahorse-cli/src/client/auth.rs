//! JWT Authentication Client
//!
//! Handles JWT token management for router authentication

use color_eyre::Result;
use serde::{Deserialize, Serialize};
use crate::client::RouterClient;

/// JWT auth response
#[derive(Debug, Serialize, Deserialize)]
#[allow(dead_code)]
pub struct AuthResponse {
    pub access_token: String,
    pub token_type: String,
    pub expires_in: u64,
}

/// Authentication client
#[allow(dead_code)]
pub struct AuthClient {
    router_client: RouterClient,
}

#[allow(dead_code)]
impl AuthClient {
    /// Create new auth client
    pub fn new(router_client: RouterClient) -> Self {
        Self { router_client }
    }

    /// Authenticate with the router
    pub async fn authenticate(&self, api_key: Option<String>) -> Result<String> {
        // If API key provided, use it to get JWT
        if let Some(key) = api_key {
            let response = self.router_client.http()
                .post(format!("{}/v1/auth", self.router_client.base_url()))
                .json(&serde_json::json!({ "api_key": key }))
                .send()
                .await?;

            if !response.status().is_success() {
                let error = response.text().await?;
                return Err(color_eyre::eyre::eyre!("Authentication failed: {}", error));
            }

            let auth_response: AuthResponse = response.json().await?;
            let token = auth_response.access_token;

            // Store token
            self.router_client.set_token(token.clone()).await;

            Ok(token)
        } else {
            // Try to use existing token or generate anonymous token
            // For now, generate a simple token for demo purposes
            let token = format!("anonymous_{}", uuid::Uuid::new_v4());
            self.router_client.set_token(token.clone()).await;
            Ok(token)
        }
    }

    /// Refresh JWT token
    pub async fn refresh_token(&self) -> Result<String> {
        let current_token = self.router_client.get_token()
            .await
            .ok_or_else(|| color_eyre::eyre::eyre!("No token to refresh"))?;

        let response = self.router_client.http()
            .post(format!("{}/v1/auth/refresh", self.router_client.base_url()))
            .header("Authorization", format!("Bearer {}", current_token))
            .send()
            .await?;

        if !response.status().is_success() {
            return Err(color_eyre::eyre::eyre!("Token refresh failed"));
        }

        let auth_response: AuthResponse = response.json().await?;
        let new_token = auth_response.access_token;

        self.router_client.set_token(new_token.clone()).await;

        Ok(new_token)
    }
}
