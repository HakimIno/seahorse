//! PyO3 bindings for embedding generation from Python.
//!
//! Provides zero-copy bridges between Rust and Python embedding models.
//!
//! # Usage
//!
//! ```python
//! from seahorse_ffi import generate_embedding, generate_embeddings_batch
//!
//! # Single embedding
//! vec = generate_embedding("Hello world")
//! # vec: [f32; 384] or [f32; 1536] depending on model
//!
//! # Batch embeddings
//! vecs = generate_embeddings_batch(["doc1", "doc2", "doc3"])
//! # vecs: [[f32], [f32], [f32]]
//! ```

use pyo3::prelude::*;
use pyo3::types::PyList;
use std::collections::HashMap;

/// Generate a single embedding vector.
///
/// # Args
///
/// * `text` - Input text to embed.
/// * `model` - Optional model name (default: from env).
///
/// # Returns
///
/// List of floats representing the embedding vector.
///
/// # Example
///
/// ```python
/// vec = generate_embedding("Hello world")
/// print(f"Dimension: {len(vec)}")  # 384, 1024, or 1536
/// ```
#[pyfunction]
#[pyo3(signature = (text, model = None))]
pub fn generate_embedding(
    py: Python<'_>,
    text: &str,
    model: Option<&str>,
) -> PyResult<Vec<f32>> {
    // Import Python embedding module (kept for future use)
    let _embeddings_mod = py.import_bound("seahorse_ai.core.embeddings")
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyImportError, _>(
            format!("Failed to import seahorse_ai.core.embeddings: {}", e)
        ))?;

    // Get the helper async function
    let helpers_mod = py.import_bound("seahorse_ai.core.embedding_helpers")
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyImportError, _>(
            format!("Failed to import seahorse_ai.core.embedding_helpers: {}", e)
        ))?;

    // Get sync_generate_embedding function
    let gen_func = helpers_mod.getattr("sync_generate_embedding")
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyAttributeError, _>(
            format!("sync_generate_embedding not found: {}", e)
        ))?;

    // Call with or without model
    let result = if let Some(model_name) = model {
        gen_func.call1((text, model_name))
    } else {
        gen_func.call1((text,))
    };

    // Extract embedding list
    let embedding_list: Bound<'_, PyList> = result
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
            format!("sync_generate_embedding call failed: {}", e)
        ))?
        .extract()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyTypeError, _>(
            format!("Expected list, got: {}", e)
        ))?;

    // Convert PyList to Vec<f32>
    embedding_list
        .iter()
        .map(|item| {
            item.extract::<f32>()
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                    format!("Expected f32, got: {}", e)
                ))
        })
        .collect()
}

/// Generate multiple embeddings in batch (more efficient).
///
/// # Args
///
/// * `texts` - List of input texts.
/// * `model` - Optional model name.
///
/// # Returns
///
/// List of embedding vectors (list of lists of floats).
///
/// # Example
///
/// ```python
/// texts = ["doc1", "doc2", "doc3"]
/// embeddings = generate_embeddings_batch(texts)
/// print(f"Got {len(embeddings)} embeddings")
/// ```
#[pyfunction]
#[pyo3(signature = (texts, model = None))]
pub fn generate_embeddings_batch(
    py: Python<'_>,
    texts: Vec<String>,
    model: Option<&str>,
) -> PyResult<Vec<Vec<f32>>> {
    if texts.is_empty() {
        return Ok(Vec::new());
    }

    // Import Python helpers module
    let helpers_mod = py.import_bound("seahorse_ai.core.embedding_helpers")
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyImportError, _>(
            format!("Failed to import seahorse_ai.core.embedding_helpers: {}", e)
        ))?;

    // Get sync_generate_embeddings_batch function
    let gen_func = helpers_mod.getattr("sync_generate_embeddings_batch")
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyAttributeError, _>(
            format!("sync_generate_embeddings_batch not found: {}", e)
        ))?;

    // Convert Rust Vec<String> to Python list
    let py_list = PyList::new_bound(py, texts.iter().map(|s| s.as_str()));

    // Call with or without model
    let result = if let Some(model_name) = model {
        gen_func.call1((py_list, model_name))
    } else {
        gen_func.call1((py_list,))
    };

    // Extract batch list
    let batch_list: Bound<'_, PyList> = result
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
            format!("sync_generate_embeddings_batch call failed: {}", e)
        ))?
        .extract()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyTypeError, _>(
            format!("Expected list, got: {}", e)
        ))?;

    // Convert list of lists to Vec<Vec<f32>>
    batch_list
        .iter()
        .map(|embedding_list| {
            let list: Bound<'_, PyList> = embedding_list
                .extract()
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                    format!("Expected list, got: {}", e)
                ))?;

            list.iter()
                .map(|item| {
                    item.extract::<f32>()
                        .map_err(|e| PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                            format!("Expected f32, got: {}", e)
                        ))
                })
                .collect()
        })
        .collect()
}

/// Get the embedding dimension for a given model.
///
/// # Args
///
/// * `model` - Model name (default: from env).
///
/// # Returns
///
/// Embedding dimension (e.g., 384, 1024, 1536, 3072).
///
/// # Example
///
/// ```python
/// dim = get_embedding_dimension()
/// print(f"Dimension: {dim}")  # 384 for all-MiniLM-L6-v2
/// ```
#[pyfunction]
#[pyo3(signature = (model = None))]
pub fn get_embedding_dimension(
    py: Python<'_>,
    model: Option<&str>,
) -> PyResult<usize> {
    // Import Python embedding module
    let embeddings_mod = py.import_bound("seahorse_ai.core.embeddings")
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyImportError, _>(
            format!("Failed to import seahorse_ai.core.embeddings: {}", e)
        ))?;

    // Get EMBEDDING_DIMS dict
    let dims_dict: HashMap<String, usize> = embeddings_mod.getattr("EMBEDDING_DIMS")
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyAttributeError, _>(
            format!("EMBEDDING_DIMS not found: {}", e)
        ))?
        .extract()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyTypeError, _>(
            format!("Expected dict, got: {}", e)
        ))?;

    // Get default model if not specified
    let model_name = if let Some(m) = model {
        m.to_string()
    } else {
        embeddings_mod.getattr("DEFAULT_MODEL")
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyAttributeError, _>(
                format!("DEFAULT_MODEL not found: {}", e)
            ))?
            .extract()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                format!("Expected str, got: {}", e)
            ))?
    };

    // Look up dimension
    dims_dict.get(&model_name)
        .copied()
        .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyValueError, _>(
            format!("Unknown model: {}", model_name)
        ))
}

/// Check if a specific model is supported.
///
/// # Args
///
/// * `model` - Model name to check.
///
/// # Returns
///
/// True if the model is supported.
#[pyfunction]
pub fn is_model_supported(py: Python<'_>, model: &str) -> PyResult<bool> {
    // Import Python embedding module
    let embeddings_mod = py.import_bound("seahorse_ai.core.embeddings")
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyImportError, _>(
            format!("Failed to import seahorse_ai.core.embeddings: {}", e)
        ))?;

    // Get EMBEDDING_DIMS dict
    let dims_dict: HashMap<String, usize> = embeddings_mod.getattr("EMBEDDING_DIMS")
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyAttributeError, _>(
            format!("EMBEDDING_DIMS not found: {}", e)
        ))?
        .extract()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyTypeError, _>(
            format!("Expected dict, got: {}", e)
        ))?;

    Ok(dims_dict.contains_key(model))
}
