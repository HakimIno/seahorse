use serde::{Deserialize, Serialize};
use tracing::{info, warn};

/// Fast Path service for sub-10ms response bypass.
pub struct FastPath {
    model: String,
    api_key: String,
    client: reqwest::Client,
}

#[derive(Debug, Serialize)]
struct OpenRouterRequest {
    model: String,
    messages: Vec<Message>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Message {
    role: String,
    content: String,
}

#[derive(Debug, Deserialize)]
struct OpenRouterResponse {
    choices: Vec<Choice>,
}

#[derive(Debug, Deserialize)]
struct Choice {
    message: Message,
}

impl FastPath {
    pub fn new(model: String, api_key: String) -> Self {
        Self {
            model,
            api_key,
            client: reqwest::Client::new(),
        }
    }

    /// Try to respond to a prompt directly using a lightweight model.
    /// Returns Some(answer) if handled, or None if fallback to Python is needed.
    pub async fn try_respond(
        &self,
        prompt: &str,
        history: &[crate::scheduler::Message],
    ) -> Option<String> {
        if self.api_key.is_empty() {
            return None;
        }

        let system_prompt = "You are a fast-path responder for Seahorse AI. \
            ONLY answer greetings (e.g. 'hello'), simple chitchat, or timeless knowledge (e.g. 'what is gravity'). \
            STRICT RULE: If the user asks about current events, leaders, prices, or ANY factual data that changes over time (e.g. 'who is the prime minister', 'what is the price of gold'), you MUST respond ONLY with '[FALLBACK]'. \
            If the query requires tools, SQL, memory storage, complex planning, or is ambiguous, respond ONLY with '[FALLBACK]'.";

        let model_id = self.model.strip_prefix("openrouter/").unwrap_or(&self.model);
        
        let mut messages = vec![
            Message {
                role: "system".to_string(),
                content: system_prompt.to_string(),
            },
        ];

        // Add history for context-awareness (what did I just ask?)
        for h in history {
            messages.push(Message {
                role: h.role.clone(),
                content: h.content.clone(),
            });
        }

        // Add current prompt
        messages.push(Message {
            role: "user".to_string(),
            content: prompt.to_string(),
        });

        let body = OpenRouterRequest {
            model: model_id.to_string(),
            messages,
        };

        let res = self.client
            .post("https://openrouter.ai/api/v1/chat/completions")
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Referer", "http://localhost:8000")
            .json(&body)
            .send()
            .await;

        match res {
            Ok(http_res) => {
                let status = http_res.status();
                if status.is_success() {
                    if let Ok(data) = http_res.json::<OpenRouterResponse>().await {
                        if let Some(choice) = data.choices.first() {
                            let content = choice.message.content.trim();
                            if content == "[FALLBACK]" {
                                info!("FastPath: [FALLBACK] triggered for prompt: {}", prompt);
                                return None;
                            }
                            info!("FastPath: handled prompt directly");
                            return Some(content.to_string());
                        }
                    }
                } else {
                    let err_body = http_res.text().await.unwrap_or_else(|_| "Could not read error body".to_string());
                    warn!("FastPath: OpenRouter API error status: {} - body: {}", status, err_body);
                }
            }
            Err(e) => {
                warn!("FastPath: OpenRouter request error: {}", e);
            }
        }

        None
    }
}
