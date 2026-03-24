//! Terminal User Interface (TUI)
//!
//! Interactive terminal UI built with ratatui:
//! - Chat interface
//! - Progress bars
//! - Custom widgets

pub mod chat;
pub mod progress;
pub mod widgets;

pub use chat::ChatTui;
