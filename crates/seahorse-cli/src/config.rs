//! CLI Configuration Management
//!
//! Handles CLI-specific configuration including:
//! - Router connection settings
//! - Authentication tokens
//! - User preferences
//! - Session persistence

use color_eyre::Result;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tokio::fs;

/// CLI configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
#[allow(dead_code)]
pub struct CliConfig {
    /// Router API URL
    pub router_url: String,

    /// JWT authentication token
    pub jwt_token: Option<String>,

    /// User preferences
    pub preferences: UserPreferences,
}

/// User preferences
#[derive(Debug, Clone, Serialize, Deserialize)]
#[allow(dead_code)]
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

impl Default for CliConfig {
    fn default() -> Self {
        Self {
            router_url: "http://localhost:8000".to_string(),
            jwt_token: None,
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

    /// Update JWT token
    pub fn with_token(mut self, token: String) -> Self {
        self.jwt_token = Some(token);
        self
    }
}
