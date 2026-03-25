//! CLI Configuration Management
//!
//! Handles CLI-specific configuration including:
//! - Router connection settings
//! - Authentication tokens
//! - API Keys for different providers
//! - User preferences
//! - Session persistence

use color_eyre::Result;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tokio::fs;

/// CLI configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CliConfig {
    /// Router API URL
    pub router_url: String,

    /// JWT authentication token
    pub jwt_token: Option<String>,

    /// LLM Provider configuration
    pub llm: LlmConfig,

    /// User preferences
    pub preferences: UserPreferences,
}

/// LLM Provider configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmConfig {
    /// Provider type (openai, openrouter, custom)
    pub provider: String,

    /// API Key for the provider
    pub api_key: Option<String>,

    /// Model to use (optional, uses default if not specified)
    pub model: Option<String>,

    /// Custom API endpoint (for custom providers)
    pub api_endpoint: Option<String>,
}

/// User preferences
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserPreferences {
    /// Default editor for diff viewing
    pub editor: String,

    /// Theme for TUI
    pub theme: String,

    /// Maximum search results
    pub default_search_limit: usize,

    /// Auto-apply refactoring (dangerous!)
    pub auto_apply: bool,
}

impl Default for UserPreferences {
    fn default() -> Self {
        Self {
            editor: "vim".to_string(),
            theme: "default".to_string(),
            default_search_limit: 10,
            auto_apply: false,
        }
    }
}

impl Default for LlmConfig {
    fn default() -> Self {
        Self {
            provider: "openrouter".to_string(),
            api_key: None,
            model: None,
            api_endpoint: None,
        }
    }
}

impl Default for CliConfig {
    fn default() -> Self {
        Self {
            router_url: "http://localhost:8000".to_string(),
            jwt_token: None,
            llm: LlmConfig::default(),
            preferences: UserPreferences::default(),
        }
    }
}

#[allow(dead_code)]
impl CliConfig {
    /// Get config file path
    pub fn config_path() -> Result<PathBuf> {
        let home = std::env::var("HOME")
            .or_else(|_| std::env::var("USERPROFILE"))?;
        Ok(PathBuf::from(home).join(".seahorse").join("cli.json"))
    }

    /// Get .env file path
    pub fn env_path() -> Result<PathBuf> {
        let current_dir = std::env::current_dir()?;
        Ok(current_dir.join(".env"))
    }

    /// Load configuration from disk
    pub async fn load() -> Result<Self> {
        let path = Self::config_path()?;

        if fs::metadata(&path).await.is_ok() {
            let contents = fs::read_to_string(&path).await?;
            let config: CliConfig = serde_json::from_str(&contents)?;
            Ok(config)
        } else {
            Ok(Self::default())
        }
    }

    /// Save configuration to disk
    pub async fn save(&self) -> Result<()> {
        let path = Self::config_path()?;

        // Create directory if it doesn't exist
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).await?;
        }

        let contents = serde_json::to_string_pretty(self)?;
        fs::write(&path, contents).await?;

        Ok(())
    }

    /// Save to .env file
    pub async fn save_to_env(&self) -> Result<()> {
        let env_path = Self::env_path()?;
        let mut env_lines = Vec::new();

        // Read existing .env if exists
        if fs::metadata(&env_path).await.is_ok() {
            let existing = fs::read_to_string(&env_path).await?;
            for line in existing.lines() {
                // Skip lines we're about to write
                if !line.starts_with("OPENROUTER_API_KEY")
                    && !line.starts_with("OPENAI_API_KEY")
                    && !line.starts_with("SEAHORSE_LLM_MODEL")
                    && !line.starts_with("SEAHORSE_MODEL_WORKER")
                    && !line.starts_with("SEAHORSE_MODEL_THINKER")
                    && !line.starts_with("SEAHORSE_MODEL_STRATEGIST")
                    && !line.starts_with("SEAHORSE_MODEL_EXTRACT")
                    && !line.starts_with("SEAHORSE_MODEL_FAST")
                    && !line.starts_with("ZHIPUAI_API_KEY")
                    && !line.starts_with("CUSTOM_LLM_ENDPOINT") {
                    env_lines.push(line.to_string());
                }
            }
        }

        // Add API configuration
        if let Some(ref api_key) = self.llm.api_key {
            match self.llm.provider.as_str() {
                "openrouter" => {
                    env_lines.push(format!("OPENROUTER_API_KEY={}", api_key));
                    if let Some(ref model) = self.llm.model {
                        // Ensure openrouter/ prefix for LiteLLM routing
                        let model_val = if model.contains('/') { model.clone() } else { format!("openrouter/{}", model) };
                        env_lines.push(format!("SEAHORSE_MODEL_WORKER={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_THINKER={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_STRATEGIST={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_EXTRACT={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_FAST={}", model_val));
                        env_lines.push(format!("SEAHORSE_LLM_MODEL={}", model_val));
                    }
                }
                "openai" => {
                    env_lines.push(format!("OPENAI_API_KEY={}", api_key));
                    if let Some(ref model) = self.llm.model {
                        env_lines.push(format!("SEAHORSE_MODEL_WORKER={}", model));
                        env_lines.push(format!("SEAHORSE_MODEL_THINKER={}", model));
                        env_lines.push(format!("SEAHORSE_MODEL_STRATEGIST={}", model));
                        env_lines.push(format!("SEAHORSE_MODEL_EXTRACT={}", model));
                        env_lines.push(format!("SEAHORSE_MODEL_FAST={}", model));
                        env_lines.push(format!("SEAHORSE_LLM_MODEL={}", model));
                    }
                }
                "zhipu" => {
                    env_lines.push(format!("ZHIPUAI_API_KEY={}", api_key));
                    if let Some(ref model) = self.llm.model {
                        // Ensure model is prefixed with zhipu/
                        let model_val = if model.starts_with("zhipu/") {
                            model.clone()
                        } else {
                            format!("zhipu/{}", model)
                        };
                        env_lines.push(format!("SEAHORSE_MODEL_WORKER={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_THINKER={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_STRATEGIST={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_EXTRACT={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_FAST={}", model_val));
                        env_lines.push(format!("SEAHORSE_LLM_MODEL={}", model_val));
                    }
                }
                "z-ai" => {
                    // Z.ai is OpenAI-compatible but uses its own endpoint
                    env_lines.push(format!("CUSTOM_LLM_API_KEY={}", api_key));
                    env_lines.push("CUSTOM_LLM_ENDPOINT=https://api.z.ai/api/paas/v4".to_string());
                    if let Some(ref model) = self.llm.model {
                        // Use openai/ prefix for LiteLLM to handle it as an OpenAI endpoint
                        let model_val = if model.starts_with("openai/") { model.clone() } else { format!("openai/{}", model) };
                        env_lines.push(format!("SEAHORSE_MODEL_WORKER={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_THINKER={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_STRATEGIST={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_EXTRACT={}", model_val));
                        env_lines.push(format!("SEAHORSE_MODEL_FAST={}", model_val));
                        env_lines.push(format!("SEAHORSE_LLM_MODEL={}", model_val));
                    }
                }
                _ => {}
            }
        }

        // Write to .env
        let env_content = env_lines.join("\n");
        fs::write(&env_path, env_content).await?;

        Ok(())
    }

    /// Update JWT token
    pub fn with_token(mut self, token: String) -> Self {
        self.jwt_token = Some(token);
        self
    }

    /// Update LLM configuration
    pub fn with_llm(mut self, provider: String, api_key: Option<String>, model: Option<String>, api_endpoint: Option<String>) -> Self {
        self.llm.provider = provider;
        self.llm.api_key = api_key;
        self.llm.model = model;
        self.llm.api_endpoint = api_endpoint;
        self
    }
}
