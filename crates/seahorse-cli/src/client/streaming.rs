//! SSE Streaming Client
//!
//! Provides real-time streaming from router endpoints using Server-Sent Events

use color_eyre::Result;
use futures_util::{stream, Stream};
use reqwest::Client;
use serde_json::Value;
use std::pin::Pin;
use std::time::Duration;

/// SSE streaming message
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub enum StreamMessage {
    /// Text chunk
    Text(String),
    /// Done signal
    Done,
    /// Error message
    Error(String),
    /// Metadata/control message
    Metadata(Value),
}

/// Streaming client for SSE
#[allow(dead_code)]
pub struct StreamingClient {
    base_url: String,
    jwt_token: String,
    http_client: Client,
}

#[allow(dead_code)]
impl StreamingClient {
    /// Create new streaming client
    pub fn new(base_url: String, jwt_token: String) -> Result<Self> {
        let http_client = Client::builder()
            .timeout(Duration::from_secs(120))  // Increased for complex prompts
            .build()?;

        Ok(Self {
            base_url,
            jwt_token,
            http_client,
        })
    }

    /// Stream chat completion
    pub fn stream_chat(
        &self,
        prompt: String,
        session_id: Option<String>,
    ) -> Result<Pin<Box<dyn Stream<Item = Result<StreamMessage>> + Send>>> {
        let url = format!("{}/v1/agent/stream", self.base_url);

        let mut request_body = serde_json::json!({
            "prompt": prompt,
            "stream": true,
        });

        if let Some(session) = session_id {
            request_body["session_id"] = serde_json::json!(session);
        }

        // Clone necessary data for the stream
        let client = self.http_client.clone();
        let token = self.jwt_token.clone();

        let stream = stream::try_unfold(
            (client, token, url, request_body, false),
            |(client, token, url, request_body, done)| async move {
                if done {
                    return Ok(None);
                }

                // Make POST request
                let response = client
                    .post(&url)
                    .header("Authorization", format!("Bearer {}", token))
                    .json(&request_body)
                    .send()
                    .await?;

                if !response.status().is_success() {
                    return Err(color_eyre::eyre::eyre!(
                        "HTTP error: {}",
                        response.status()
                    ));
                }

                // Read response body as bytes
                let bytes = response.bytes().await?;
                let text = String::from_utf8_lossy(&bytes);

                // Parse as JSON
                if let Ok(value) = serde_json::from_str::<Value>(&text) {
                    if let Some(msg_type) = value.get("type").and_then(|v| v.as_str()) {
                        match msg_type {
                            "text" => {
                                if let Some(content) = value.get("content").and_then(|v| v.as_str()) {
                                    return Ok(Some((
                                        StreamMessage::Text(content.to_string()),
                                        (client, token, url, request_body, false),
                                    )));
                                }
                            }
                            "done" => {
                                return Ok(Some((
                                    StreamMessage::Done,
                                    (client, token, url, request_body, true),
                                )));
                            }
                            "error" => {
                                if let Some(error) = value.get("error").and_then(|v| v.as_str()) {
                                    return Ok(Some((
                                        StreamMessage::Error(error.to_string()),
                                        (client, token, url, request_body, true),
                                    )));
                                }
                            }
                            "metadata" => {
                                return Ok(Some((
                                    StreamMessage::Metadata(value),
                                    (client, token, url, request_body, false),
                                )));
                            }
                            _ => {
                                return Ok(Some((
                                    StreamMessage::Text(text.to_string()),
                                    (client, token, url, request_body, false),
                                )));
                            }
                        }
                    }
                }

                // If not JSON, treat as plain text
                Ok(Some((
                    StreamMessage::Text(text.to_string()),
                    (client, token, url, request_body, true),
                )))
            },
        );

        Ok(Box::pin(stream))
    }
}
