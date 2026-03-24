//! Progress Bars and Spinners
//!
//! Visual feedback for long-running operations:
//! - Indexing progress
//! - Search results
//! - Refactoring status



/// Progress state
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct ProgressState {
    pub current: usize,
    pub total: usize,
    pub message: String,
}

#[allow(dead_code)]
impl ProgressState {
    pub fn new(total: usize) -> Self {
        Self {
            current: 0,
            total,
            message: String::new(),
        }
    }

    pub fn progress(&self) -> f64 {
        if self.total == 0 {
            0.0
        } else {
            self.current as f64 / self.total as f64
        }
    }

    pub fn percentage(&self) -> String {
        format!("{:.0}%", self.progress() * 100.0)
    }
}
