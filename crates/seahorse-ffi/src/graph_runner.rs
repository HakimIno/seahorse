use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use pyo3::prelude::*;
use pyo3::types::PyList;
use seahorse_core::error::{CoreError, CoreResult};
use seahorse_core::graph::{Graph, GraphState, EdgeDestination, Node, ConditionalEdgeClosure};

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
                    
                    let result_obj = func.call1((json_str,))
                        .map_err(|e| CoreError::Graph(format!("Call {}: {}", fn_name, e)))?;
                    
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
    
    // Add Reason Node (calls LLM)
    graph.add_node(PyNode::new("reason", "seahorse_ai.nodes", "reason_node"));
    
    // Add Action Node (executes tools)
    graph.add_node(PyNode::new("action", "seahorse_ai.nodes", "action_node"));
    
    graph.set_entry_point("reason");
    
    // Edges
    // From Action -> Reason is always direct
    graph.add_edge("action", EdgeDestination::Node("reason".to_string()));
    
    // From Reason -> Conditional (End or Action)
    let condition: ConditionalEdgeClosure = Arc::new(|state: &GraphState| {
        // If state["next_step"] == "action", go to action, else END
        let next = state.get("next_step")
            .and_then(|v| v.as_str())
            .unwrap_or("end");
            
        let dest = if next == "action" {
            EdgeDestination::Node("action".to_string())
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
        
        let initial_messages = history.iter().map(|m| {
            serde_json::json!({"role": &m.role, "content": &m.content})
        }).collect::<Vec<_>>();
        
        let mut messages = initial_messages;
        messages.push(serde_json::json!({"role": "user", "content": prompt}));
        
        initial_state.insert("messages".to_string(), serde_json::Value::Array(messages));
        
        // Run Graph
        // Now PyGraphRunner::run is async, so we can await the graph execution directly.
        let exec_result = graph.run(initial_state).await;
        
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
                
                let _ = token_tx.blocking_send(format!("[DONE] Graph steps completed"));
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
        info!("Python Version: {}", version);
        info!("Python Executable: {}", executable);
        
        let path: Bound<'_, PyList> = sys.getattr("path")?.downcast_into()?;
        
        // Add local python source
        path.insert(0, "python")?;
        
        // Find .venv site-packages
        if let Ok(entries) = std::fs::read_dir(".venv/lib") {
            for entry in entries.flatten() {
                if let Ok(file_type) = entry.file_type() {
                    if file_type.is_dir() {
                        let mut sp_path = entry.path();
                        sp_path.push("site-packages");
                        if sp_path.exists() {
                            if let Some(s) = sp_path.to_str() {
                                path.append(s)?;
                                info!("Added to sys.path: {}", s);
                            }
                        }
                    }
                }
            }
        }
        
        // Warm up common heavy imports to prevent circular threading issues
        if let Err(e) = py.import_bound("tiktoken") {
            warn!("Optional: could not pre-load tiktoken: {}", e);
        }
        if let Err(e) = py.import_bound("litellm") {
            warn!("Optional: could not pre-load litellm: {}", e);
        }
        
        Ok::<(), PyErr>(())
    }).map_err(|e| anyhow::anyhow!("Python init failed: {}", e))?;
    
    Ok(())
}
