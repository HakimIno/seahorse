use pyo3::prelude::*;
use seahorse_core::networking::FOOTBALL_CLIENT;
use once_cell::sync::Lazy;
use tokio::runtime::Runtime;

static FFI_RUNTIME: Lazy<Runtime> = Lazy::new(|| {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("Failed to create Seahorse FFI runtime")
});

/// Fetch football data with native Rust rate limiting.
/// 
/// Args:
///     url: The API-Football endpoint URL.
///     api_key: Your x-apisports-key.
#[pyfunction]
pub fn fetch_football_data(py: Python<'_>, url: String, api_key: String) -> PyResult<String> {
    let headers = vec![
        ("x-apisports-key".to_string(), api_key),
    ];
    
    // We run the async fetch in a blocking manner.
    // We try to reuse an existing handle, but fall back to a global FFI runtime if none exists.
    let result: Result<serde_json::Value, String> = py.allow_threads(|| {
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            handle.block_on(async {
                FOOTBALL_CLIENT.fetch_json(&url, headers).await
            })
        } else {
            FFI_RUNTIME.block_on(async {
                FOOTBALL_CLIENT.fetch_json(&url, headers).await
            })
        }
        .map_err(|e| format!("Network error: {e}"))
    });

    match result {
        Ok(json) => Ok(json.to_string()),
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)),
    }
}
