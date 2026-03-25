use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use pyo3::prelude::*;
use pyo3::types::PyList;
use seahorse_core::error::{CoreError, CoreResult};
use seahorse_core::graph::{Graph, GraphState, EdgeDestination, Node, ConditionalEdgeClosure};

/// A simple bridge that allows Python to send tokens back to the Rust channel.
#[pyclass]
pub struct PyTokenStreamer {
    tx: mpsc::Sender<String>,
}

#[pymethods]
impl PyTokenStreamer {
    fn send(&self, token: String) {
        let tx = self.tx.clone();
        // Since we are in a sync Python context, we use a block_on or just spawn
        // to send the token to the async channel.
        tokio::spawn(async move {
            let _ = tx.send(token).await;
        });
    }
}

// A generic node that calls a Python function via PyO3.
pub struct PyNode {
    name: String,
    // We store the module and function name to import and call dynamically
    module_name: String,
    func_name: String,
}

impl PyNode {
    pub fn new(name: &str, module: &str, func: &str) -> Self {
        Self {
            name: name.to_string(),
            module_name: module.to_string(),
            func_name: func.to_string(),
        }
    }
}

impl Node for PyNode {
    fn name(&self) -> &str {
        &self.name
    }

    fn call<'a>(
        &'a self,
        state: &'a GraphState,
        status_tx: Option<tokio::sync::mpsc::Sender<String>>,
    ) -> Pin<Box<dyn Future<Output = CoreResult<GraphState>> + Send + 'a>> {
        // We clone state to move into spawn_blocking
        let state_clone = state.clone();
        let mod_name = self.module_name.clone();
        let fn_name = self.func_name.clone();

        Box::pin(async move {
            let json_str = serde_json::to_string(&state_clone)
                .map_err(|e| CoreError::Graph(format!("Serialize state: {}", e)))?;

            // We must use spawn_blocking because PyO3 acquiring the GIL blocks the thread
            let result_json_str = tokio::task::spawn_blocking(move || {
                Python::with_gil(|py| -> CoreResult<String> {
                    let module = py.import_bound(&*mod_name)
                        .map_err(|e| CoreError::Graph(format!("Import {}: {}", mod_name, e)))?;
                    
                    let func = module.getattr(&*fn_name)
                        .map_err(|e| CoreError::Graph(format!("Getattr {}: {}", fn_name, e)))?;
                    
                    // Create a streamer if we have a sender
                    let result_obj = if let Some(tx) = status_tx {
                        let streamer = PyTokenStreamer { tx };
                        let py_streamer = Py::new(py, streamer)
                            .map_err(|e| CoreError::Graph(format!("Create streamer: {}", e)))?;
                        
                        func.call1((json_str, py_streamer))
                            .map_err(|e| CoreError::Graph(format!("Call {} with streamer: {}", fn_name, e)))?
                    } else {
                        func.call1((json_str,))
                            .map_err(|e| CoreError::Graph(format!("Call {}: {}", fn_name, e)))?
                    };
                    
                    let result_str: String = result_obj.extract()
                        .map_err(|e| CoreError::Graph(format!("Extract string: {}", e)))?;
                    
                    Ok(result_str)
                })
            }).await.map_err(|e| CoreError::Graph(format!("Join error: {}", e)))??;

            let updated_state: GraphState = serde_json::from_str(&result_json_str)
                .map_err(|e| CoreError::Graph(format!("Deserialize output: {}", e)))?;

            Ok(updated_state)
        })
    }
}

pub fn build_react_graph() -> Graph {
    let mut graph = Graph::new();
    
    // Build Nodes
    graph.add_node(PyNode::new("Reasoning", "seahorse_ai.core.nodes", "reason_node"));
    graph.add_node(PyNode::new("Acting", "seahorse_ai.core.nodes", "action_node"));
    
    // Define flow
    graph.set_entry_point("Reasoning");
    
    // From Acting -> Reasoning is always direct
    graph.add_edge("Acting", EdgeDestination::Node("Reasoning".to_string()));
    
    // From Reasoning -> Conditional (End or Acting)
    let condition: ConditionalEdgeClosure = Arc::new(|state: &GraphState| {
        // If state["next_step"] == "action", go to action, else END
        let next = state.get("next_step")
            .and_then(|v| v.as_str())
            .unwrap_or("end");
            
        let dest = if next == "action" {
            EdgeDestination::Node("Acting".to_string())
        } else {
            EdgeDestination::End
        };
        
        Box::pin(std::future::ready(Ok(dest)))
    });
    
    graph.add_conditional_edge("reason", condition);
    
    graph
}

use seahorse_core::worker::PythonRunner;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

pub struct PyGraphRunner {
    pub model: String,
}

impl PyGraphRunner {
    pub fn new(model: String) -> Self {
        Self { model }
    }
}

#[async_trait::async_trait]
impl PythonRunner for PyGraphRunner {
    async fn run(
        &self,
        task_id: &str,
        agent_id: &str,
        prompt: &str,
        history: &[seahorse_core::scheduler::Message],
        token_tx: mpsc::Sender<String>,
    ) -> CoreResult<String> {
        info!(task_id, "PyGraphRunner::run starting Graph State Machine");
        
        let graph = build_react_graph();
        
        // Initialize State
        let mut initial_state = GraphState::new();
        initial_state.insert("prompt".to_string(), serde_json::to_value(&prompt).unwrap_or(serde_json::Value::Null));
        initial_state.insert("agent_id".to_string(), serde_json::to_value(&agent_id).unwrap_or(serde_json::Value::Null));
        initial_state.insert("worker_model".to_string(), serde_json::to_value(&self.model).unwrap_or(serde_json::Value::Null));
        
        let initial_messages = history.iter().map(|m| {
            serde_json::json!({"role": &m.role, "content": &m.content})
        }).collect::<Vec<_>>();
        
        let mut messages = initial_messages;
        messages.push(serde_json::json!({"role": "user", "content": prompt}));
        
        initial_state.insert("messages".to_string(), serde_json::Value::Array(messages));
        
        // Run Graph
        // Now PyGraphRunner::run is async, so we can await the graph execution directly.
        let exec_result = graph.run(initial_state, Some(token_tx)).await;
        
        match exec_result {
            Ok(execution) => {
                info!(task_id, "Graph Execution completed: {:?}", execution.status);
                let final_msgs = execution.state.get("messages")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                    
                let response = if let Some(last_msg) = final_msgs.last() {
                    last_msg.get("content").and_then(|c| c.as_str()).unwrap_or("No content").to_string()
                } else {
                    "Graph returned empty messages.".to_string()
                };
                
                Ok(response)
            }
            Err(e) => {
                error!(task_id, err = %e, "Graph execution failed");
                Err(e)
            }
        }
    }

    fn health_check(&self) -> CoreResult<()> {
        Ok(())
    }
}

pub fn make_arc_py_graph_runner(model: &str) -> std::sync::Arc<dyn PythonRunner> {
    std::sync::Arc::new(PyGraphRunner::new(model.to_string()))
}

/// Global Python environment initialisation. 
/// Adds ./python and .venv site-packages to sys.path.
pub fn init_python_env() -> anyhow::Result<()> {
    info!("Initialising Python environment...");
    
    // Help native extensions find their home by setting VIRTUAL_ENV
    if let Ok(cwd) = std::env::current_dir() {
        let venv_path = cwd.join(".venv");
        if venv_path.exists() {
            if let Some(s) = venv_path.to_str() {
                std::env::set_var("VIRTUAL_ENV", s);
                // Some native extensions (like tiktoken's rust core) check this
                info!("Set VIRTUAL_ENV to {}", s);
            }
        }
    }

    Python::with_gil(|py| {
        let sys = py.import_bound("sys")?;
        let version: String = sys.getattr("version")?.extract()?;
        let executable: String = sys.getattr("executable")?.extract()?;
        
        // Extract major.minor (e.g. "3.13")
        let sysconfig = py.import_bound("sysconfig")?;
        let pyver: String = sysconfig.call_method0("get_python_version")?.extract()?;
        
        info!("Python Version: {} (abi: {})", version, pyver);
        info!("Python Executable: {}", executable);
        
        let path: Bound<'_, PyList> = sys.getattr("path")?.downcast_into()?;
        
        // Add local python source as absolute path
        if let Ok(abs_python) = std::fs::canonicalize("python") {
            if let Some(s) = abs_python.to_str() {
                path.insert(0, s)?;
                info!("Added local python source to sys.path: {}", s);
            }
        }
        
        // Find .venv site-packages
        let mut found_matching_venv = false;
        let venv_lib = std::path::Path::new(".venv/lib");
        
        if let Ok(entries) = std::fs::read_dir(venv_lib) {
            for entry in entries.flatten() {
                if let Ok(file_type) = entry.file_type() {
                    if file_type.is_dir() {
                        let dir_name = entry.file_name();
                        let dir_str = dir_name.to_string_lossy();
                        
                        // Check if this directory matches the current python version (e.g. "python3.13")
                        if dir_str.starts_with("python") {
                            let mut sp_path = entry.path();
                            sp_path.push("site-packages");
                            
                            if sp_path.exists() {
                                if let Ok(abs_path) = std::fs::canonicalize(&sp_path) {
                                    if let Some(s) = abs_path.to_str() {
                                        if dir_str.contains(&pyver) {
                                            path.append(s)?;
                                            info!("Added matching site-packages to sys.path: {}", s);
                                            found_matching_venv = true;
                                        } else {
                                            warn!("Ignoring mismatched site-packages: {} (Targeting {})", s, pyver);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        if !found_matching_venv && venv_lib.exists() {
            error!(pyver = %pyver, "❌ NO MATCHING .venv site-packages found");
            error!(pyver = %pyver, "To fix this, run: uv venv --python {} && uv sync", pyver);
        }
        
        // Path setup complete
        Ok::<(), PyErr>(())
    }).map_err(|e| anyhow::anyhow!("Python init failed: {}", e))?;
    
    Ok(())
}
