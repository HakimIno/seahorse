/// PyPlannerRunner — calls Python ReActPlanner via PyO3.
///
/// Strategy:
/// - Called from `spawn_blocking` (not on the Tokio thread pool)
/// - Acquires GIL, builds Python objects, calls `asyncio.run(planner.run(request))`
/// - asyncio.run() is safe here because we own the thread (spawn_blocking)
/// - Streams a DONE token on completion
use std::sync::Arc;

use pyo3::prelude::*;
use pyo3::types::PyDict;
use tokio::sync::mpsc;
use tracing::{debug, error, info};

use seahorse_core::error::{CoreError, CoreResult};
use seahorse_core::worker::PythonRunner;

#[pyclass]
pub struct PyPlannerRunner {
    pub model: String,
    pub max_steps: usize,
}

#[pymethods]
impl PyPlannerRunner {
    #[new]
    pub fn new(model: String, max_steps: usize) -> Self {
        Self { model, max_steps }
    }
}

impl PythonRunner for PyPlannerRunner {
    fn run(
        &self,
        task_id: &str,
        prompt: &str,
        token_tx: mpsc::Sender<String>,
    ) -> CoreResult<String> {
        info!(task_id, model = %self.model, "PyPlannerRunner::run");

        let model = self.model.clone();
        let max_steps = self.max_steps;
        let prompt = prompt.to_owned();
        let task_id = task_id.to_owned();

        // All PyO3 work must happen inside with_gil — coroutine objects are not Send.
        Python::with_gil(|py| -> CoreResult<String> {
            // ── inject python/ + venv site-packages into sys.path ──────
            let sys = py.import_bound("sys")
                .map_err(|e| CoreError::Config(format!("import sys: {e}")))?;
            let sys_path = sys.getattr("path")
                .map_err(|e| CoreError::Config(format!("sys.path: {e}")))?;

            // 1. ./python — local seahorse_ai source
            sys_path.call_method1("insert", (0i32, "./python"))
                .map_err(|e| CoreError::Config(format!("sys.path.insert: {e}")))?;

            // 2. VIRTUAL_ENV/lib/pythonX.Y/site-packages (set by uv)
            if let Ok(venv) = std::env::var("VIRTUAL_ENV") {
                // find the python version string inside the venv
                let sysconfig = py.import_bound("sysconfig")
                    .map_err(|e| CoreError::Config(format!("import sysconfig: {e}")))?;
                let pyver: String = sysconfig
                    .call_method0("get_python_version")
                    .and_then(|v| v.extract())
                    .unwrap_or_else(|_| "3.12".to_string());
                let site_pkgs = format!("{venv}/lib/python{pyver}/site-packages");
                sys_path.call_method1("insert", (1i32, site_pkgs))
                    .map_err(|e| CoreError::Config(format!("sys.path.insert venv: {e}")))?;
            }

            // ── imports ──────────────────────────────────────────────────
            let asyncio = py.import_bound("asyncio")
                .map_err(|e| CoreError::Config(format!("import asyncio: {e}")))?;
            let schemas_mod = py.import_bound("seahorse_ai.schemas")
                .map_err(|e| CoreError::Config(format!("import schemas: {e}")))?;
            let llm_mod = py.import_bound("seahorse_ai.llm")
                .map_err(|e| CoreError::Config(format!("import llm: {e}")))?;
            let planner_mod = py.import_bound("seahorse_ai.planner")
                .map_err(|e| CoreError::Config(format!("import planner: {e}")))?;
            let tools_mod = py.import_bound("seahorse_ai.tools")
                .map_err(|e| CoreError::Config(format!("import tools: {e}")))?;

            // ── LLMConfig ────────────────────────────────────────────────
            let llm_kwargs = PyDict::new_bound(py);
            llm_kwargs.set_item("model", &model)
                .map_err(|e| CoreError::Config(format!("llm_kwargs.model: {e}")))?;
            let llm_config = schemas_mod
                .getattr("LLMConfig")
                .map_err(|e| CoreError::Config(format!("LLMConfig attr: {e}")))?
                .call((), Some(&llm_kwargs))
                .map_err(|e| CoreError::Config(format!("LLMConfig(): {e}")))?;

            // ── LLMClient ────────────────────────────────────────────────
            let llm_client = llm_mod
                .getattr("LLMClient")
                .map_err(|e| CoreError::Config(format!("LLMClient attr: {e}")))?
                .call1((&llm_config,))
                .map_err(|e| CoreError::Config(format!("LLMClient(): {e}")))?;

            // ── ToolRegistry ─────────────────────────────────────────────
            let tool_registry = tools_mod
                .getattr("SeahorseToolRegistry")
                .map_err(|e| CoreError::Config(format!("ToolRegistry attr: {e}")))?
                .call0()
                .map_err(|e| CoreError::Config(format!("ToolRegistry(): {e}")))?;

            // ── ReActPlanner ─────────────────────────────────────────────
            let planner_kwargs = PyDict::new_bound(py);
            planner_kwargs.set_item("max_steps", max_steps)
                .map_err(|e| CoreError::Config(format!("planner_kwargs: {e}")))?;
            let planner = planner_mod
                .getattr("ReActPlanner")
                .map_err(|e| CoreError::Config(format!("ReActPlanner attr: {e}")))?
                .call((&llm_client, &tool_registry), Some(&planner_kwargs))
                .map_err(|e| CoreError::Config(format!("ReActPlanner(): {e}")))?;

            // ── AgentRequest ─────────────────────────────────────────────
            let request = schemas_mod
                .getattr("AgentRequest")
                .map_err(|e| CoreError::Config(format!("AgentRequest attr: {e}")))?
                .call((), Some(&{
                    let kw = PyDict::new_bound(py);
                    kw.set_item("prompt", &prompt).ok();
                    kw
                }))
                .map_err(|e| CoreError::Config(format!("AgentRequest(): {e}")))?;

            // ── coroutine ────────────────────────────────────────────────
            let coro = planner
                .call_method1("run", (&request,))
                .map_err(|e| CoreError::Config(format!("planner.run(): {e}")))?;

            // ── asyncio.run() — safe in spawn_blocking thread ────────────
            debug!(task_id = %task_id, "calling asyncio.run");
            let response = asyncio
                .call_method1("run", (&coro,))
                .map_err(|e| {
                    error!(task_id = %task_id, err = %e, "asyncio.run failed");
                    CoreError::Config(format!("asyncio.run: {e}"))
                })?;

            let content: String = response
                .getattr("content")
                .and_then(|a| a.extract())
                .map_err(|e| CoreError::Config(format!("response.content: {e}")))?;
            let steps: usize = response
                .getattr("steps")
                .and_then(|a| a.extract())
                .map_err(|e| CoreError::Config(format!("response.steps: {e}")))?;

            info!(task_id = %task_id, steps, "planner completed");

            // Send DONE signal
            let _ = token_tx.blocking_send(format!("[DONE] steps={steps}"));

            Ok(content)
        })
    }
}

// ── factory ───────────────────────────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (model="gpt-4o", max_steps=10))]
pub fn make_py_runner(model: &str, max_steps: usize) -> PyPlannerRunner {
    PyPlannerRunner::new(model.to_string(), max_steps)
}

pub fn make_arc_py_runner(model: &str, max_steps: usize) -> Arc<dyn PythonRunner> {
    Arc::new(PyPlannerRunner::new(model.to_string(), max_steps))
}
