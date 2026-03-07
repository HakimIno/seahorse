//! Seahorse FFI — PyO3 bridge between Rust Core and Python AI layer.
//! Exports: PyAgentMemory class, search_memory function, PyPlannerRunner.
#![warn(clippy::all)]
#![allow(clippy::must_use_candidate)]

pub mod agent;
pub mod memory;

use pyo3::prelude::*;

/// The seahorse_ffi extension module.
#[pymodule]
fn seahorse_ffi(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<memory::PyAgentMemory>()?;
    m.add_function(wrap_pyfunction!(memory::search_memory, m)?)?;
    m.add_class::<agent::PyPlannerRunner>()?;
    m.add_function(wrap_pyfunction!(agent::make_py_runner, m)?)?;
    Ok(())
}
