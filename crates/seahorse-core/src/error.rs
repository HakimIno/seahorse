use thiserror::Error;

#[derive(Debug, Error)]
pub enum CoreError {
    #[error("memory error: {0}")]
    Memory(String),

    #[error("sandbox error: {kind}")]
    Sandbox { kind: String },

    #[error("config error: {0}")]
    Config(String),

    #[error("python error: {0}")]
    Python(String),

    #[error("wasm error: {0}")]
    Wasm(String),

    #[error("channel closed")]
    ChannelClosed,

    #[error("agent not found: {id}")]
    AgentNotFound { id: String },

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),

    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("graph execution error: {0}")]
    Graph(String),

    #[error("task store error: {0}")]
    TaskStore(String),

    #[error("internal error: {0}")]
    Internal(String),
}

pub type CoreResult<T> = Result<T, CoreError>;
