use std::collections::{HashMap, HashSet};
use serde::{Serialize, Deserialize};

/// A node in the Knowledge Graph, representing an entity (e.g., Person, Place, Concept).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Node {
    pub id: String,
    pub label: String,
    pub doc_ids: HashSet<usize>, // Links to HNSW vector document IDs
}

/// A directed edge representing a relationship between two nodes.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Edge {
    pub source: String,
    pub target: String,
    pub predicate: String,
    pub weight: f32,
}

/// In-memory Directed Knowledge Graph.
#[derive(Debug, Default, Serialize, Deserialize)]
pub struct KnowledgeGraph {
    pub nodes: HashMap<String, Node>,
    pub edges: Vec<Edge>,
    // adjacency list: source_id -> Vec<edge_index>
    pub adj_list: HashMap<String, Vec<usize>>,
}

impl KnowledgeGraph {
    pub fn new() -> Self {
        Self::default()
    }

    /// Upsert a node into the graph.
    pub fn add_node(&mut self, id: String, label: String, doc_id: Option<usize>) {
        let node = self.nodes.entry(id.clone()).or_insert_with(|| Node {
            id: id.clone(),
            label,
            doc_ids: HashSet::new(),
        });
        if let Some(d_id) = doc_id {
            node.doc_ids.insert(d_id);
        }
    }

    /// Add a relationship edge between two nodes.
    pub fn add_edge(&mut self, source: String, target: String, predicate: String, weight: f32) {
        let edge = Edge { source: source.clone(), target, predicate, weight };
        let edge_idx = self.edges.len();
        self.edges.push(edge);
        self.adj_list.entry(source).or_default().push(edge_idx);
    }
    
    /// Retrieve outgoing edges for a given node.
    pub fn get_outgoing_edges(&self, source_id: &str) -> Vec<&Edge> {
        self.adj_list.get(source_id)
            .map(|indices| indices.iter().map(|&idx| &self.edges[idx]).collect())
            .unwrap_or_default()
    }
}
