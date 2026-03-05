use crate::error::{CoreError, CoreResult};

/// Runtime configuration for SeahorseCore.
#[derive(Debug, Clone)]
pub struct Config {
    /// Number of Tokio worker threads (default: number of CPUs)
    pub worker_threads: usize,
    /// HNSW graph connectivity (higher → better recall, more memory)
    pub hnsw_m: usize,
    /// HNSW build quality (higher → better recall, slower build)
    pub hnsw_ef_construction: usize,
    /// Maximum number of documents in the HNSW index
    pub hnsw_max_elements: usize,
    /// Embedding dimension (must match the embedding model)
    pub embedding_dim: usize,
    /// Port for the HTTP server
    pub http_port: u16,
}

impl Config {
    /// Load configuration from environment variables with sane defaults.
    pub fn from_env() -> CoreResult<Self> {
        Ok(Self {
            worker_threads: env_usize("SEAHORSE_WORKER_THREADS", num_cpus()),
            hnsw_m: env_usize("SEAHORSE_HNSW_M", 16),
            hnsw_ef_construction: env_usize("SEAHORSE_HNSW_EF_CONSTRUCTION", 200),
            hnsw_max_elements: env_usize("SEAHORSE_HNSW_MAX_ELEMENTS", 100_000),
            embedding_dim: env_usize("SEAHORSE_EMBEDDING_DIM", 1536),
            http_port: env_u16("SEAHORSE_HTTP_PORT", 8080)?,
        })
    }
}

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_u16(key: &str, default: u16) -> CoreResult<u16> {
    match std::env::var(key) {
        Err(_) => Ok(default),
        Ok(v) => v
            .parse()
            .map_err(|_| CoreError::Config(format!("{key} must be a valid port number"))),
    }
}

fn num_cpus() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_loads() {
        let cfg = Config::from_env().unwrap();
        assert!(cfg.worker_threads > 0);
        assert_eq!(cfg.hnsw_m, 16);
        assert_eq!(cfg.embedding_dim, 1536);
    }
}
