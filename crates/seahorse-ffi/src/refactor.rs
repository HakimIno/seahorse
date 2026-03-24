use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use seahorse_core::CoreError;
use tracing::debug;

pub fn run_refactor_crew_sync(
    file_path: &str,
    code: &str,
    agents: Vec<String>,
    language: &str,
) -> Result<String, CoreError> {
    Python::with_gil(|py| -> Result<String, CoreError> {
        // Setup sys.path 
        let sys = py.import_bound("sys")
            .map_err(|e| CoreError::Python(format!("import sys: {e}")))?;
        let sys_path = sys.getattr("path")
            .map_err(|e| CoreError::Python(format!("sys.path: {e}")))?;
            
        sys_path.call_method1("insert", (0i32, "./python"))
            .map_err(|e| CoreError::Python(format!("sys.path.insert: {e}")))?;

        if let Ok(venv) = std::env::var("VIRTUAL_ENV") {
            let sysconfig = py.import_bound("sysconfig")
                .map_err(|e| CoreError::Python(format!("import sysconfig: {e}")))?;
            let pyver: String = sysconfig
                .call_method0("get_python_version")
                .and_then(|v| v.extract())
                .unwrap_or_else(|_| "3.12".to_string());
            let site_pkgs = format!("{venv}/lib/python{pyver}/site-packages");
            let _ = sys_path.call_method1("insert", (1i32, site_pkgs));
        }

        let asyncio = py.import_bound("asyncio")
            .map_err(|e| CoreError::Python(format!("import asyncio: {e}")))?;
        
        let rc_mod = py.import_bound("seahorse_cli.agents.refactor_crew")
            .map_err(|e| CoreError::Python(format!("import refactor_crew: {e}")))?;

        let crew = rc_mod.getattr("RefactorCrew")
            .map_err(|e| CoreError::Python(format!("RefactorCrew attr: {e}")))?
            .call1((py.None(),))
            .map_err(|e| CoreError::Python(format!("RefactorCrew(): {e}")))?;

        // Create inputs
        let kwargs = PyDict::new_bound(py);
        kwargs.set_item("file_path", file_path).unwrap();
        kwargs.set_item("code", code).unwrap();
        kwargs.set_item("language", language).unwrap();
        
        let py_agents = PyList::new_bound(py, agents);
        kwargs.set_item("agent_names", py_agents).unwrap();

        let coro = crew.call_method("refactor_file", (), Some(&kwargs))
            .map_err(|e| CoreError::Python(format!("refactor_file(): {e}")))?;

        debug!("Calling asyncio.run on refactor_file");
        let response = asyncio.call_method1("run", (&coro,))
            .map_err(|e| CoreError::Python(format!("asyncio.run: {e}")))?;

        let dataclasses = py.import_bound("dataclasses").unwrap();
        let asdict = dataclasses.getattr("asdict").unwrap();
        let response_dict = asdict.call1((response,)).unwrap();

        let builtin_json = py.import_bound("json").unwrap();
        let json_str: String = builtin_json.call_method1("dumps", (response_dict,))
            .unwrap()
            .extract()
            .unwrap();

        Ok(json_str)
    })
}

// Ensure the module compiles
#[pyfunction]
pub fn run_refactor_crew_entry(
    file_path: &str,
    code: &str,
    agents: Vec<String>,
    language: &str,
) -> PyResult<String> {
    run_refactor_crew_sync(file_path, code, agents, language)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
}
