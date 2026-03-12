use pyo3::prelude::*;
use std::sync::Arc;
use pyo3::exceptions::PyRuntimeError;

use seahorse_core::wasm::WasmManager;

/// Python-accessible wrapper around the Rust WasmManager.
///
/// Usage:
///
/// ```python
/// from seahorse_ffi import PyWasmManager
///
/// manager = PyWasmManager()
/// result = manager.run(wasm_bytes, fuel=10000, memory_mb=10)
/// ```
#[pyclass(name = "PyWasmManager")]
pub struct PyWasmManager {
    inner: Arc<WasmManager>,
}

#[pymethods]
impl PyWasmManager {
    #[new]
    pub fn new() -> PyResult<Self> {
        let manager = WasmManager::new()
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("{e}")))?;
            
        Ok(Self {
            inner: Arc::new(manager),
        })
    }

    /// Run a compiled WASM module in the sandbox
    #[pyo3(signature = (wasm_bytes, fuel = 100_000, memory_mb = 16))]
    pub fn run(&self, py: Python<'_>, wasm_bytes: &[u8], fuel: u64, memory_mb: usize) -> PyResult<String> {
        let manager = self.inner.clone();
        // Since wasm_bytes is an immutable slice, we must clone it to move into the closure safely
        // But for optimization, we keep it as &[u8] by forcing allow_threads to take it safely or copying it.
        let bytes_vec = wasm_bytes.to_vec();
        
        py.allow_threads(move || {
            manager.run(&bytes_vec, fuel, memory_mb)
        })
        .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("{e}")))
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyWasmManager>()?;
    Ok(())
}
