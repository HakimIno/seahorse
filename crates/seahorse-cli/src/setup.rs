//! Interactive Setup Wizard
//!
//! Provides a user-friendly interactive setup for configuring
//! the Seahorse CLI with various LLM providers.

use color_eyre::Result;
use crate::config::CliConfig;
use std::io::{self, Write};

pub struct SetupWizard;

impl SetupWizard {
    /// Run the interactive setup wizard
    pub async fn run() -> Result<()> {
        println!("🐴 Welcome to Seahorse Agent Setup!");
        println!("═══════════════════════════════════════\n");

        println!("This wizard will help you configure your LLM provider.\n");

        // Step 1: Choose provider
        let provider = Self::choose_provider()?;

        // Step 2: Get API key
        let api_key = Self::get_api_key(&provider)?;

        // Step 3: Get model (optional)
        let model = Self::get_model(&provider)?;

        // Step 4: Get custom endpoint (for custom provider)
        let api_endpoint = if provider == "custom" {
            Self::get_custom_endpoint()?
        } else {
            None
        };

        // Step 5: Create config
        let config = CliConfig::default()
            .with_llm(provider, Some(api_key), model, api_endpoint);

        // Step 6: Save
        println!("\n💾 Saving configuration...");
        config.save().await?;
        config.save_to_env().await?;

        println!("✅ Setup complete!");
        println!("\n📝 Configuration saved to:");
        println!("   • ~/.seahorse/cli.json");
        println!("   • .env");

        println!("\n🚀 You can now run: seahorse chat");

        Ok(())
    }

    fn choose_provider() -> Result<String> {
        println!("Choose your LLM provider:");
        println!("  1) OpenRouter (Recommended - supports 100+ models)");
        println!("  2) OpenAI (GPT-4, GPT-3.5)");
        println!("  3) Zhipu AI (BigModel.cn - GLM-4)");
        println!("  4) Z.ai (Z.ai Platform - GLM-5)");
        println!("  5) Custom (Self-hosted or other)");

        print!("\nSelect provider [1-5]: ");
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;

        match input.trim() {
            "1" => Ok("openrouter".to_string()),
            "2" => Ok("openai".to_string()),
            "3" => Ok("zhipu".to_string()),
            "4" => Ok("z-ai".to_string()),
            "5" => Ok("custom".to_string()),
            _ => {
                println!("Invalid choice, defaulting to OpenRouter");
                Ok("openrouter".to_string())
            }
        }
    }

    fn get_api_key(provider: &str) -> Result<String> {
        println!("\n🔑 API Key Configuration");
        println!("═══════════════════════════");

        let provider_name = match provider {
            "openrouter" => "OpenRouter",
            "openai" => "OpenAI",
            "zhipu" => "Z.ai (Zhipu)",
            "custom" => "Custom Provider",
            _ => "Provider",
        };

        println!("Get your API key from:");
        match provider {
            "openrouter" => {
                println!("  🔗 https://openrouter.ai/keys");
            }
            "openai" => {
                println!("  🔗 https://platform.openai.com/api-keys");
            }
            "zhipu" => {
                println!("  🔗 https://open.bigmodel.cn/usercenter/apikeys");
            }
            "z-ai" => {
                println!("  🔗 https://z.ai/manage-apikey/apikey-list");
            }
            _ => {
                println!("  (Your provider's documentation)");
            }
        }

        println!("\nPress Enter to skip if you already have it set in .env");

        print!("\nEnter {} API key: ", provider_name);
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;
        let api_key = input.trim();

        if api_key.is_empty() {
            println!("⚠️  No API key provided. Make sure it's set in .env file.");
            Ok(String::new())
        } else {
            // Validate API key format
            if api_key.len() < 20 {
                println!("⚠️  Warning: API key seems too short. Please verify.");
            }
            println!("✅ API key accepted");
            Ok(api_key.to_string())
        }
    }

    fn get_model(provider: &str) -> Result<Option<String>> {
        println!("\n🤖 Model Selection");
        println!("════════════════════");

        let (default_model, description) = match provider {
            "openrouter" => (
                "anthropic/claude-sonnet-4.6",
                "Recommended models:\n\
                 • anthropic/claude-sonnet-4.6 (Best quality)\n\
                 • google/gemini-2.0-flash-001 (Fast, free)\n\
                 • openai/gpt-4o (Balanced)"
            ),
            "openai" => (
                "gpt-4o-mini",
                "Recommended models:\n\
                 • gpt-4o (best quality)\n\
                 • gpt-4o-mini (balanced)"
            ),
            "zhipu" => (
                "glm-4-flash",
                "Recommended models:\n\
                 • glm-4 (best quality)\n\
                 • glm-4-flash (fast, free tier available)"
            ),
            "z-ai" => (
                "glm-5",
                "Recommended models:\n\
                 • glm-5 (Next-gen flagship)\n\
                 • glm-4-0520"
            ),
            _ => (
                "",
                "Enter your model identifier"
            )
        };

        if !description.is_empty() {
            println!("{}\n", description);
        }

        if provider == "custom" {
            print!("Enter model identifier: ");
        } else {
            print!("Enter model [{}]: ", default_model);
        }
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;
        let model = input.trim();

        if model.is_empty() {
            if provider == "custom" {
                println!("⚠️  Model identifier is required for custom provider.");
                Ok(Some("unknown".to_string()))
            } else {
                println!("✅ Using default model: {}", default_model);
                Ok(Some(default_model.to_string()))
            }
        } else {
            // Apply automatic prefixing to prevent LiteLLM "Provider NOT provided" errors
            let prefixed_model = match provider {
                "openrouter" if !model.contains('/') => format!("openrouter/{}", model),
                "openai" if !model.starts_with("gpt-") => format!("openai/{}", model),
                "zhipu" if !model.starts_with("zhipu/") => format!("zhipu/{}", model),
                "z-ai" if !model.starts_with("openai/") => format!("openai/{}", model),
                _ => model.to_string(),
            };
            println!("✅ Model set to: {}", prefixed_model);
            Ok(Some(prefixed_model))
        }
    }

    fn get_custom_endpoint() -> Result<Option<String>> {
        print!("\nEnter custom API endpoint URL: ");
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;
        let endpoint = input.trim();

        if endpoint.is_empty() {
            println!("⚠️  No endpoint provided. You'll need to set CUSTOM_LLM_ENDPOINT manually.");
            Ok(None)
        } else {
            println!("✅ Endpoint set to: {}", endpoint);
            Ok(Some(endpoint.to_string()))
        }
    }

    /// Show current configuration
    pub async fn show_config() -> Result<()> {
        println!("📋 Current Configuration");
        println!("══════════════════════════\n");

        let config = CliConfig::load().await?;

        println!("LLM Provider: {}", config.llm.provider);
        if let Some(ref api_key) = config.llm.api_key {
            let masked = if api_key.len() > 8 {
                format!("{}...{}", &api_key[..4], &api_key[api_key.len()-4..])
            } else {
                "***".to_string()
            };
            println!("API Key: {}", masked);
        } else {
            println!("API Key: Not set (using .env)");
        }

        if let Some(ref model) = config.llm.model {
            println!("Model: {}", model);
        }

        if let Some(ref endpoint) = config.llm.api_endpoint {
            println!("Endpoint: {}", endpoint);
        }

        println!("\nRouter URL: {}", config.router_url);

        Ok(())
    }
}
