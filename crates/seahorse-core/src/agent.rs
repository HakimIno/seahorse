//! Rig-based agent implementation for native Rust performance.
use rig::providers::openai;
use rig::agent::Agent;
use rig::completion::Prompt;
use std::sync::Arc;
use tracing::info;

/// A native Rust agent powered by Rig.
/// This will eventually handle sub-10ms routing and planning tasks.
pub struct RigAgent {
    inner: Arc<Agent<openai::CompletionModel>>,
}

impl RigAgent {
    /// Create a new RigAgent using OpenAI (standard for Rig).
    /// In production, this would use configured provider keys from Seahorse Core.
    pub fn new(model: &str, api_key: &str) -> Self {
        let client = openai::Client::new(api_key);
        
        let agent = client.agent(model)
            .preamble("You are a Seahorse Native Agent. Be concise and precise.")
            .build();
            
        info!("Native RigAgent initialised with model: {}", model);
        
        Self {
            inner: Arc::new(agent),
        }
    }

    /// Primary execution point for the native agent.
    pub async fn prompt(&self, query: &str) -> anyhow::Result<String> {
        let response = self.inner.prompt(query).await?;
        Ok(response)
    }
}
