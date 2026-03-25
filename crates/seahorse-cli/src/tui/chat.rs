//! Interactive Chat TUI
//!
//! Real-time chat interface with:
//! - Message history
//! - Streaming responses
//! - Session management

use color_eyre::Result;
use crossterm::{
    event::{self, Event, KeyCode, KeyEvent},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::{Backend, CrosstermBackend},
    layout::{Constraint, Direction, Layout},
    style::{Color, Style},

    widgets::{List, ListItem, Paragraph},
    Terminal,
};
use std::io;
use std::time::Duration;
use tokio::sync::mpsc;
use crate::client::RouterClient;
use unicode_width::UnicodeWidthStr;

const MASCOT_IDLE: &[&str] = &[
    "      ▄▀▀▄",
    "     █  O █",
    "     █  ▄▀",
    "    ▄█ █",
    "  ▄▀ █ █",
    " █   ▀ █",
    "  ▀▄▄▄▄▀",
];

const MASCOT_THINKING: &[&str] = &[
    "      ▄▀▀▄",
    "     █  ? █",
    "     █  ▄▀",
    "    ▄█ █",
    "  ▄▀ █ █",
    " █   ▀ █",
    "  ▀▄▄▄▄▀",
];

/// Chat message
#[derive(Debug, Clone)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

impl ChatMessage {
    pub fn user(content: String) -> Self {
        Self {
            role: "user".to_string(),
            content,
        }
    }

    pub fn assistant(content: String) -> Self {
        Self {
            role: "assistant".to_string(),
            content,
        }
    }

    pub fn system(content: String) -> Self {
        Self {
            role: "system".to_string(),
            content,
        }
    }
}

/// Events that can be handled by the TUI
enum TuiEvent {
    Key(KeyEvent),
    Paste(String),
    Tick,
}

/// Chat TUI
pub struct ChatTui {
    router_client: RouterClient,
    messages: Vec<ChatMessage>,
    input_buffer: String,
    initial_message: Option<String>,
    is_streaming: bool,
    current_status: Option<String>,
    tick_count: u64,
    model: String,
}

impl ChatTui {
    /// Create new chat TUI
    pub fn new(router_client: RouterClient, model: String, _session_id: Option<String>) -> Result<Self> {
        Ok(Self {
            router_client,
            messages: Vec::new(),
            input_buffer: String::new(),
            initial_message: None,
            is_streaming: false,
            current_status: None,
            tick_count: 0,
            model,
        })
    }

    /// Set initial message
    pub fn set_initial_message(&mut self, message: String) {
        self.initial_message = Some(message);
    }

    /// Run the TUI
    pub async fn run(&mut self) -> Result<()> {
        // Setup terminal
        enable_raw_mode()?;
        let mut stdout = io::stdout();
        execute!(stdout, EnterAlternateScreen, event::EnableBracketedPaste)?;
        let backend = CrosstermBackend::new(stdout);
        let mut terminal = Terminal::new(backend)?;

        // Create event channel
        let (tx, mut rx) = mpsc::channel(100);

        // Spawn event handler
        let event_tx = tx.clone();
        tokio::spawn(async move {
            loop {
                // Poll for events
                if event::poll(Duration::from_millis(50)).ok() == Some(true) {
                    match event::read().unwrap() {
                        Event::Key(key) => {
                            let _ = event_tx.send(TuiEvent::Key(key)).await;
                        }
                        Event::Paste(s) => {
                            let _ = event_tx.send(TuiEvent::Paste(s)).await;
                        }
                        _ => {}
                    }
                }
                // Always send tick
                let _ = event_tx.send(TuiEvent::Tick).await;
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        });

        // Add welcome message
        self.messages.push(ChatMessage::system(
            "Welcome to Seahorse CLI! Type your message below.".to_string(),
        ));

        // Send initial message if provided
        if let Some(initial) = self.initial_message.take() {
            self.messages.push(ChatMessage::user(initial.clone()));
            // TODO: Send to router
        }

        // Main loop
        let result = self.main_loop(&mut terminal, &mut rx).await;

        // Cleanup
        let _ = execute!(
            terminal.backend_mut(),
            event::DisableBracketedPaste,
            LeaveAlternateScreen
        );
        disable_raw_mode()?;
        terminal.show_cursor()?;

        result
    }

    async fn main_loop<B: Backend>(
        &mut self,
        terminal: &mut Terminal<B>,
        rx: &mut mpsc::Receiver<TuiEvent>,
    ) -> Result<()> {
        let (stream_tx, mut stream_rx) = mpsc::channel::<String>(100);

        loop {
            // Draw UI
            terminal.draw(|f| self.draw(f))?;

            tokio::select! {
                event = rx.recv() => {
                    match event {
                        Some(TuiEvent::Tick) => {
                            self.tick_count = self.tick_count.wrapping_add(1);
                        }
                        Some(TuiEvent::Paste(s)) => {
                            if !self.is_streaming {
                                self.input_buffer.push_str(&s);
                            }
                        }
                        Some(TuiEvent::Key(key)) => {
                            match key.code {
                                KeyCode::Char(c) => {
                                    self.input_buffer.push(c);
                                }
                                KeyCode::Backspace => {
                                    self.input_buffer.pop();
                                }
                                KeyCode::Enter => {
                                    let message = self.input_buffer.drain(..).collect::<String>();
                                    if message.is_empty() {
                                        continue;
                                    }
                                    self.messages.push(ChatMessage::user(message.clone()));
                                    self.is_streaming = true;
                                    self.current_status = None;
                                    self.messages.push(ChatMessage::assistant("[Thinking...]".to_string()));

                                    let router_client = self.router_client.clone();
                                    let history = self.messages.clone();
                                    let tx = stream_tx.clone();
                                    
                                    tokio::spawn(async move {
                                        if let Err(e) = stream_agent(&router_client, &message, &history, tx.clone()).await {
                                            let _ = tx.send(format!("\n❌ Connection Error: Is the router running? ({})", e)).await;
                                        }
                                        let _ = tx.send("[DONE]".to_string()).await;
                                    });
                                }
                                KeyCode::Esc => return Ok(()),
                                _ => {}
                            }
                        }
                        None => {} // Channel closed
                    }
                }
                Some(token) = stream_rx.recv() => {
                    tracing::debug!("Received token from router: {}", token);
                    if token == "[DONE]" {
                        self.is_streaming = false;
                        self.current_status = None;
                    } else if let Some(status) = token.strip_prefix("[STATUS]: ") {
                        self.current_status = Some(status.to_string());
                    } else if let Some(last) = self.messages.last_mut() {
                        if last.role == "assistant" {
                            if last.content == "[Thinking...]" {
                                last.content.clear();
                                self.current_status = None;
                            }
                            last.content.push_str(&token);
                        }
                    }
                }
            }
        }
    }

    fn draw(&self, f: &mut ratatui::Frame) {
        let size = f.size();

        // --- Layout Definition ---
        // Header (3) | Messages (Min 0) | Separator (1) | Input (1) | Footer (1)
        let main_chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(4), // Header
                Constraint::Min(0),    // Messages
                Constraint::Length(1), // Separator
                Constraint::Length(1), // Input
                Constraint::Length(1), // Footer
            ])
            .split(size);

        // --- 1. Header (Mascot + Metadata) ---
        let mascot_art = if self.is_streaming { MASCOT_THINKING } else { MASCOT_IDLE };
        let header_text = format!(
            "{}  Seahorse Agent v0.1.0\n{}  {}\n{}  Model: {} · Status: Live",
            mascot_art[0],
            mascot_art[1], "Active Project: /Documents/seahorse",
            mascot_art[2], self.model
        );
        let header = Paragraph::new(header_text)
            .style(Style::default().fg(Color::Rgb(150, 150, 150)));
        f.render_widget(header, main_chunks[0]);

        // --- 2. Messages (Claude Style) ---
        let messages: Vec<ListItem> = self
            .messages
            .iter()
            .map(|m| {
                match m.role.as_str() {
                    "user" => {
                        let content = format!("> {}", m.content);
                        ListItem::new(content).style(Style::default().fg(Color::Rgb(100, 200, 255)))
                    }
                    "assistant" => {
                        let prefix = if m.content == "[Thinking...]" {
                            let dots = ".".repeat((self.tick_count % 4) as usize);
                            match &self.current_status {
                                Some(s) => format!("* Thinking: {}{}", s, dots),
                                None => format!("* Thinking{}", dots),
                            }
                        } else {
                            "●".to_string()
                        };
                        let content = if m.content == "[Thinking...]" {
                            String::new()
                        } else {
                            format!("{} {}", prefix, m.content)
                        };
                        
                        ListItem::new(content).style(Style::default().fg(Color::Rgb(0, 255, 200)))
                    }
                    "system" => {
                        let content = format!("ℹ {}", m.content);
                        ListItem::new(content).style(Style::default().fg(Color::DarkGray))
                    }
                    _ => ListItem::new(m.content.clone()),
                }
            })
            .collect();

        let messages_list = List::new(messages);
        f.render_widget(messages_list, main_chunks[1]);

        // --- 3. Separator ---
        let separator = Paragraph::new("─".repeat(size.width as usize))
            .style(Style::default().fg(Color::Rgb(60, 60, 60)));
        f.render_widget(separator, main_chunks[2]);

        // --- 4. Input Area ---
        let input_text = format!("> {}", self.input_buffer);
        let input = Paragraph::new(input_text)
            .style(Style::default().fg(Color::White));
        f.render_widget(input, main_chunks[3]);

        // --- 5. Footer (Status Bar) ---
        let footer_text = "esc to exit │ ? for help";
        let footer = Paragraph::new(footer_text)
            .style(Style::default().fg(Color::DarkGray));
        f.render_widget(footer, main_chunks[4]);

        // --- Cursor Positioning ---
        let cursor_pos = UnicodeWidthStr::width(self.input_buffer.as_str()) as u16;
        f.set_cursor(
            main_chunks[3].x + cursor_pos + 2, // +2 for "> "
            main_chunks[3].y,
        );
    }
}

use futures_util::StreamExt;

async fn stream_agent(
    client: &RouterClient,
    prompt: &str,
    history: &[ChatMessage],
    tx: mpsc::Sender<String>,
) -> Result<()> {
    // Map history to simple role/content objects for the router
    let mut mapped_history = Vec::new();
    for msg in history {
        if !msg.content.is_empty() {
             mapped_history.push(serde_json::json!({
                "role": msg.role,
                "content": msg.content
            }));
        }
    }

    let req = serde_json::json!({
        "agent_id": "chat",
        "prompt": prompt,
        "history": mapped_history
    });

    let request = client
        .http()
        .post(format!("{}/v1/agent/stream", client.base_url()))
        .json(&req);
        
    let mut request = request;
    if let Some(token) = client.get_token().await {
        request = request.header("Authorization", format!("Bearer {}", token));
    }

    let response = request.send().await?;
    let status = response.status();

    if !status.is_success() {
        let text = response.text().await.unwrap_or_default();
        if text.trim().is_empty() {
            return Err(color_eyre::eyre::eyre!("Request failed with status: {}", status));
        } else {
            return Err(color_eyre::eyre::eyre!("Request failed: {}", text));
        }
    }

    let mut stream = response.bytes_stream();
    let mut buffer = String::new();

    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| color_eyre::eyre::eyre!("{}", e))?;
        let text = String::from_utf8_lossy(&chunk);
        buffer.push_str(&text);

        // Process complete SSE events (separated by \n\n)
        while let Some(pos) = buffer.find("\n\n") {
            let event_str = buffer[..pos].to_string();
            buffer.drain(..pos + 2);

            let mut msg_data = String::new();
            for line in event_str.lines() {
                if let Some(val) = line.strip_prefix("data: ") {
                    if !msg_data.is_empty() {
                        msg_data.push('\n');
                    }
                    msg_data.push_str(val);
                }
            }
            if !msg_data.is_empty() && msg_data != "[DONE]" {
                tracing::debug!("Sending token to UI: {}", msg_data);
                let _ = tx.send(msg_data).await;
            }
        }
    }

    // Handle remaining buffer content (last event without trailing \n\n)
    if !buffer.is_empty() {
        let mut msg_data = String::new();
        for line in buffer.lines() {
            if let Some(val) = line.strip_prefix("data: ") {
                if !msg_data.is_empty() {
                    msg_data.push('\n');
                }
                msg_data.push_str(val);
            }
        }
        if !msg_data.is_empty() && msg_data != "[DONE]" {
            tracing::debug!("Sending final token to UI: {}", msg_data);
            let _ = tx.send(msg_data).await;
        }
    }

    Ok(())
}
