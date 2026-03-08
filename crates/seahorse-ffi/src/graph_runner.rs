use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use pyo3::prelude::*;
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
use tracing::{info, error};

pub struct PyGraphRunner {
    pub model: String,
}

impl PyGraphRunner {
    pub fn new(model: String) -> Self {
        Self { model }
    }
}

impl PythonRunner for PyGraphRunner {
    fn run(
        &self,
        task_id: &str,
        prompt: &str,
        token_tx: mpsc::Sender<String>,
    ) -> CoreResult<String> {
        info!(task_id, "PyGraphRunner::run starting Graph State Machine");
        
        let graph = build_react_graph();
        
        // Initialize State
        let mut initial_state = GraphState::new();
        initial_state.insert("prompt".to_string(), serde_json::to_value(&prompt).unwrap_or(serde_json::Value::Null));
        
        let initial_messages = vec![
            serde_json::json!({"role": "user", "content": prompt})
        ];
        initial_state.insert("messages".to_string(), serde_json::Value::Array(initial_messages));
        
        // Run Graph
        // `graph.run()` is async, but PythonRunner::run is synchronous (runs inside spawn_blocking).
        // So we need a Tokio runtime or block_on here to drive the graph future.
        // Wait, since we are inside `spawn_blocking`, we can use a Handle or block_on.
        let handle = tokio::runtime::Handle::current();
        let exec_result = handle.block_on(async {
            graph.run(initial_state).await
        });
        
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
