//! PyO3 bindings for Charming charting engine.

use pyo3::prelude::*;
use seahorse_core::ChartGenerator as CoreGenerator;

#[pyclass]
pub struct PyChartGenerator {
    inner: CoreGenerator,
}

#[pymethods]
impl PyChartGenerator {
    #[new]
    pub fn new() -> Self {
        Self {
            inner: CoreGenerator::new(),
        }
    }

    /// Generate a bar chart JSON configuration.
    pub fn bar_chart(
        &self,
        title: &str,
        categories: Vec<String>,
        values: Vec<f64>,
    ) -> PyResult<String> {
        self.inner
            .bar_chart(title, categories, values)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    /// Generate a line chart JSON configuration.
    pub fn line_chart(
        &self,
        title: &str,
        categories: Vec<String>,
        values: Vec<f64>,
    ) -> PyResult<String> {
        self.inner
            .line_chart(title, categories, values)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }
}
