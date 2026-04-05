use anyhow::Result;
use candle_core::{Device, Tensor};
use candle_nn::VarBuilder;
use candle_transformers::models::bert::{BertModel, Config, DTYPE};
use hf_hub::{api::sync::Api, Repo, RepoType};
use once_cell::sync::OnceCell;
use tokenizers::{PaddingParams, Tokenizer};
use std::sync::Mutex;

static EMBEDDER: OnceCell<Mutex<Embedder>> = OnceCell::new();

pub struct Embedder {
    model: BertModel,
    tokenizer: Tokenizer,
    device: Device,
}

impl Embedder {
    pub fn get_or_init() -> Result<&'static Mutex<Self>> {
        if let Some(embedder) = EMBEDDER.get() {
            return Ok(embedder);
        }

        let api = Api::new()?.repo(Repo::new("BAAI/bge-large-en-v1.5".to_string(), RepoType::Model));

        let config_filename = api.get("config.json")?;
        let tokenizer_filename = api.get("tokenizer.json")?;
        let weights_filename = api.get("model.safetensors")?;

        let config = std::fs::read_to_string(&config_filename)?;
        let config: Config = serde_json::from_str(&config)?;
        
        let mut tokenizer = Tokenizer::from_file(&tokenizer_filename).map_err(|e| anyhow::anyhow!(e))?;
        if let Some(params) = tokenizer.get_padding_mut() {
            params.pad_id = 0;
        } else {
            tokenizer.with_padding(Some(PaddingParams {
                pad_id: 0,
                ..Default::default()
            }));
        }

        // Lightweight hardware acceleration fallback
        let device = Device::new_metal(0).unwrap_or(Device::Cpu);
        
        let vb = unsafe { VarBuilder::from_mmaped_safetensors(&[weights_filename], DTYPE, &device)? };
        
        let model = BertModel::load(vb, &config)?;

        let embedder = Self { model, tokenizer, device };
        
        EMBEDDER.get_or_try_init(|| Ok::<Mutex<Embedder>, anyhow::Error>(Mutex::new(embedder)))
    }

    pub fn embed(&mut self, text: &str) -> Result<Vec<f32>> {
        let tokens = self.tokenizer.encode(text, true).map_err(|e| anyhow::anyhow!(e))?;
        let token_ids = tokens.get_ids();
        let token_type_ids = vec![0u32; token_ids.len()];
        
        let token_tensor = Tensor::new(token_ids, &self.device)?.unsqueeze(0)?;
        let token_type_tensor = Tensor::new(token_type_ids.as_slice(), &self.device)?.unsqueeze(0)?;
        
        // BGE uses CLS pooling (first token)
        let embeddings = self.model.forward(&token_tensor, &token_type_tensor, None)?;
        let first_token = embeddings.get(0)?.get(0)?;
        
        // Normalize vector
        let sq_sum = first_token.sqr()?.sum_all()?.to_vec0::<f32>()?;
        let norm = sq_sum.sqrt();
        let normalized = (first_token / (norm as f64))?;
        
        Ok(normalized.to_vec1()?)
    }
}
