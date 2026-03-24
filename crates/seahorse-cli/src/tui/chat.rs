//! Interactive Chat TUI
//!
//! Real-time chat interface with:
//! - Message history
//! - Streaming responses
//! - Session management

use color_eyre::Result;
use crossterm::{
    event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEvent},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::{Backend, CrosstermBackend},
    layout::{Constraint, Direction, Layout},
    style::{Color, Style},

    widgets::{Block, Borders, List, ListItem, Paragraph},
    Terminal,
};
use std::io;
use std::time::Duration;
use tokio::sync::mpsc;
use crate::client::RouterClient;

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

/// Chat TUI
pub struct ChatTui {
    router_client: RouterClient,
    messages: Vec<ChatMessage>,
    input_buffer: String,
    initial_message: Option<String>,
    is_streaming: bool,
}

impl ChatTui {
    /// Create new chat TUI
    pub fn new(router_client: RouterClient, _session_id: Option<String>) -> Result<Self> {
        Ok(Self {
            router_client,
            messages: Vec::new(),
            input_buffer: String::new(),
            initial_message: None,
            is_streaming: false,
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
        execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
        let backend = CrosstermBackend::new(stdout);
        let mut terminal = Terminal::new(backend)?;

        // Create event channel
        let (tx, mut rx) = mpsc::channel(100);

        // Spawn event handler
        let event_tx = tx.clone();
        tokio::spawn(async move {
            loop {
                if event::poll(Duration::from_millis(100)).ok() == Some(true) {
                    if let Event::Key(key) = event::read().unwrap() {
                        if event_tx.send(key).await.is_err() {
                            break;
                        }
                    }
                }
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
        disable_raw_mode()?;
        execute!(
            terminal.backend_mut(),
            LeaveAlternateScreen,
            DisableMouseCapture
        )?;
        terminal.show_cursor()?;

        result
    }

    async fn main_loop<B: Backend>(
        &mut self,
        terminal: &mut Terminal<B>,
        rx: &mut mpsc::Receiver<KeyEvent>,
    ) -> Result<()> {
        let (stream_tx, mut stream_rx) = mpsc::channel::<String>(100);

        loop {
            // Draw UI
            terminal.draw(|f| self.draw(f))?;

            tokio::select! {
                Some(key) = rx.recv() => {
                    match key.code {
                        KeyCode::Char(c) => {
                            if !self.is_streaming {
                                self.input_buffer.push(c);
                            }
                        }
                        KeyCode::Backspace => {
                            if !self.is_streaming {
                                self.input_buffer.pop();
                            }
                        }
                        KeyCode::Enter => {
                            if !self.is_streaming && !self.input_buffer.is_empty() {
                                let message = self.input_buffer.clone();
                                self.input_buffer.clear();
                                self.messages.push(ChatMessage::user(message.clone()));

                                self.is_streaming = true;
                                self.messages.push(ChatMessage::assistant("".to_string()));

                                let router_client = self.router_client.clone();
                                let history = self.messages.clone(); // Clone messages for the spawned task
                                let tx = stream_tx.clone();
                                
                                tokio::spawn(async move {
                                    if let Err(e) = stream_agent(&router_client, &message, &history, tx.clone()).await {
                                        let _ = tx.send(format!("\n[Error: {}]", e)).await;
                                    }
                                    let _ = tx.send("[DONE]".to_string()).await;
                                });
                            }
                        }
                        KeyCode::Esc => {
                            return Ok(());
                        }
                        _ => {}
                    }
                }
                Some(token) = stream_rx.recv() => {
                    if token == "[DONE]" {
                        self.is_streaming = false;
                    } else if let Some(last) = self.messages.last_mut() {
                        if last.role == "assistant" {
                            last.content.push_str(&token);
                        }
                    }
                }
            }
        }
    }

    fn draw(&self, f: &mut ratatui::Frame) {
        let size = f.size();

        // Create layout
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .margin(1)
            .constraints([Constraint::Min(0), Constraint::Length(3)].as_ref())
            .split(size);

        // Messages area
        let messages: Vec<ListItem> = self
            .messages
            .iter()
            .map(|m| {
                let color = match m.role.as_str() {
                    "user" => Color::Blue,
                    "assistant" => Color::Green,
                    "system" => Color::Yellow,
                    _ => Color::White,
                };

                let content = format!("{}: {}",
                    m.role.to_uppercase(),
                    m.content
                );

                ListItem::new(content)
                    .style(Style::default().fg(color))
            })
            .collect();

        let messages_list = List::new(messages)
            .block(Block::default().borders(Borders::ALL).title("Chat"));

        f.render_widget(messages_list, chunks[0]);

        // Input area
        let input = Paragraph::new(self.input_buffer.as_str())
            .style(Style::default().fg(Color::Yellow))
            .block(Block::default().borders(Borders::ALL).title("Input"));
        f.render_widget(input, chunks[1]);

        // Set cursor position
        f.set_cursor(
            chunks[1].x + self.input_buffer.len() as u16 + 1,
            chunks[1].y + 1,
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
                let _ = tx.send(msg_data).await;
            }
        }
    }

    Ok(())
}
