//! Custom TUI Widgets
//!
//! Custom widgets for:
//! - Search results
//! - Diff viewer
//! - Code highlighting



/// Search result widget
#[allow(dead_code)]
pub struct SearchResultWidget {
    results: Vec<String>,
}

#[allow(dead_code)]
impl SearchResultWidget {
    pub fn new(results: Vec<String>) -> Self {
        Self { results }
    }
}
