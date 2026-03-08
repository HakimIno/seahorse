use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use crate::error::CoreResult;
use serde_json::Value;

/// The State is just a JSON object (Map) to be easily passed to/from Python.
pub type GraphState = serde_json::Map<String, Value>;

/// A Node executes logic on the state and returns what to merge into the state.
pub trait Node: Send + Sync {
    fn name(&self) -> &str;
    fn call<'a>(
        &'a self,
        state: &'a GraphState,
    ) -> Pin<Box<dyn Future<Output = CoreResult<GraphState>> + Send + 'a>>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EdgeDestination {
    Node(String),
    End,
}

pub type ConditionalEdgeClosure = Arc<
    dyn Fn(&GraphState) -> Pin<Box<dyn Future<Output = CoreResult<EdgeDestination>> + Send + '_>>
        + Send
        + Sync,
>;

pub enum Edge {
    Direct(EdgeDestination),
    Conditional(ConditionalEdgeClosure),
}

/// A directed graph of nodes that process state.
pub struct Graph {
    nodes: HashMap<String, Arc<dyn Node>>,
    edges: HashMap<String, Edge>,
    entry_point: Option<String>,
}

pub struct GraphExecution {
    pub current_node: String,
    pub state: GraphState,
    pub status: ExecutionStatus,
}

#[derive(Debug, PartialEq, Eq)]
pub enum ExecutionStatus {
    Running,
    Paused,
    Completed,
    Error(String),
}

impl Graph {
    pub fn new() -> Self {
        Self {
            nodes: HashMap::new(),
            edges: HashMap::new(),
            entry_point: None,
        }
    }

    pub fn add_node<N: Node + 'static>(&mut self, node: N) {
        self.nodes.insert(node.name().to_string(), Arc::new(node));
    }

    pub fn set_entry_point(&mut self, node_name: &str) {
        self.entry_point = Some(node_name.to_string());
    }

    pub fn add_edge(&mut self, from: &str, to: EdgeDestination) {
        self.edges.insert(from.to_string(), Edge::Direct(to));
    }

    pub fn add_conditional_edge(&mut self, from: &str, condition: ConditionalEdgeClosure) {
        self.edges.insert(from.to_string(), Edge::Conditional(condition));
    }

    /// Run the graph until completion or pause.
    pub async fn run(&self, mut state: GraphState) -> CoreResult<GraphExecution> {
        let mut curr = match &self.entry_point {
            Some(node) => node.clone(),
            None => return Err(crate::error::CoreError::Graph("No entry point set".into())),
        };

        let mut step_count = 0;
        let max_steps = 100;

        loop {
            if step_count >= max_steps {
                return Ok(GraphExecution {
                    current_node: curr,
                    state,
                    status: ExecutionStatus::Error("Max steps reached".into()),
                });
            }
            step_count += 1;

            let node = match self.nodes.get(&curr) {
                Some(n) => n,
                None => {
                    return Ok(GraphExecution {
                        current_node: curr.clone(),
                        state,
                        status: ExecutionStatus::Error(format!("Node not found: {}", curr)),
                    })
                }
            };

            // Execute node logic (e.g. call into Python)
            let state_update = node.call(&state).await?;

            // Merge update into state
            for (k, v) in state_update {
                state.insert(k, v);
            }

            // Determine next node
            let next_dest = match self.edges.get(&curr) {
                Some(Edge::Direct(dest)) => dest.clone(),
                Some(Edge::Conditional(cond)) => cond(&state).await?,
                None => EdgeDestination::End, // Default to end if no edge explicitly defined
            };

            match next_dest {
                EdgeDestination::Node(next_node) => {
                    curr = next_node;
                }
                EdgeDestination::End => {
                    return Ok(GraphExecution {
                        current_node: "END".to_string(),
                        state,
                        status: ExecutionStatus::Completed,
                    });
                }
            }
        }
    }
}
