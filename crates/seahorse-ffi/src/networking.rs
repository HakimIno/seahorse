use pyo3::prelude::*;
use seahorse_core::networking::FOOTBALL_CLIENT;

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
    
    // We run the async fetch in a blocking manner using the current runtime handle.
    // This is safe because Seahorse tools are executed in worker threads on the Python side.
    let result: Result<serde_json::Value, String> = py.allow_threads(|| {
        let rt = tokio::runtime::Handle::current();
        rt.block_on(async {
            FOOTBALL_CLIENT.fetch_json(&url, headers).await
        })
        .map_err(|e| format!("Network error: {e}"))
    });

    match result {
        Ok(json) => Ok(json.to_string()),
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e)),
    }
}
