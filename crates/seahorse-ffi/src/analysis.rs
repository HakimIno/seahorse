//! PyO3 bindings for Polars analysis engine.

use pyo3::prelude::*;
use seahorse_core::PolarsAnalyst as CoreAnalyst;

#[pyclass]
pub struct PyPolarsAnalyst {
    inner: CoreAnalyst,
}

#[pymethods]
impl PyPolarsAnalyst {
    #[new]
    pub fn new() -> Self {
        Self {
            inner: CoreAnalyst::new(),
        }
    }

    /// Aggregate JSON data using the native Polars engine.
    pub fn aggregate_json(
        &self,
        json_data: &str,
        group_by: &str,
        agg_col: &str,
    ) -> PyResult<String> {
        self.inner
            .aggregate_json(json_data, group_by, agg_col)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }
}
