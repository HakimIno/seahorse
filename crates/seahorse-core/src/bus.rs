use std::collections::HashMap;
use tokio::sync::{broadcast, mpsc, RwLock};
use tracing::{debug, error, info};
use rusqlite::{params, Connection};

#[derive(Clone, Debug)]
pub struct SwarmMessage {
    pub topic: String,
    pub sender: String,
    pub content: String,
}

pub struct MessageBus {
    channels: RwLock<HashMap<String, broadcast::Sender<SwarmMessage>>>,
    channel_capacity: usize,
    db_tx: Option<mpsc::UnboundedSender<SwarmMessage>>,
    db_path: Option<String>,
}

impl MessageBus {
    pub fn new(channel_capacity: usize, db_path: Option<String>) -> Self {
        let mut db_tx = None;
        if let Some(path) = &db_path {
            info!("MessageBus: Initializing SQLite persistence at {}", path);
            let (tx, mut rx) = mpsc::unbounded_channel::<SwarmMessage>();
            db_tx = Some(tx);
            
            let path_clone = path.clone();
            tokio::task::spawn_blocking(move || {
                let conn = match Connection::open(&path_clone) {
                    Ok(c) => c,
                    Err(e) => {
                        error!("Failed to open SQLite DB: {}", e);
                        return;
                    }
                };
                
                let _ = conn.execute("PRAGMA journal_mode=WAL;", []);
                
                let _ = conn.execute(
                    "CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY,
                        topic TEXT NOT NULL,
                        sender TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )",
                    [],
                );
                
                while let Some(msg) = rx.blocking_recv() {
                    let res = conn.execute(
                        "INSERT INTO messages (topic, sender, content) VALUES (?1, ?2, ?3)",
                        params![msg.topic, msg.sender, msg.content],
                    );
                    if let Err(e) = res {
                        error!("Failed to insert message into SQLite: {}", e);
                    }
                }
            });
        }

        Self {
            channels: RwLock::new(HashMap::new()),
            channel_capacity,
            db_tx,
            db_path,
        }
    }

    pub async fn get_or_create_topic(&self, topic: &str) -> broadcast::Sender<SwarmMessage> {
        let read_lock = self.channels.read().await;
        if let Some(sender) = read_lock.get(topic) {
            return sender.clone();
        }
        drop(read_lock);

        let mut write_lock = self.channels.write().await;
        let sender = write_lock.entry(topic.to_string()).or_insert_with(|| {
            let (tx, _rx) = broadcast::channel(self.channel_capacity);
            info!("MessageBus: Created new topic channel '{}'", topic);
            tx
        });
        sender.clone()
    }

    pub async fn publish(&self, message: SwarmMessage) -> Result<usize, String> {
        let topic = message.topic.clone();
        
        if let Some(tx) = &self.db_tx {
            let _ = tx.send(message.clone());
        }

        let sender = self.get_or_create_topic(&topic).await;
        match sender.send(message) {
            Ok(count) => {
                debug!("MessageBus: Published to '{}', {} receivers", topic, count);
                Ok(count)
            }
            Err(_) => Ok(0),
        }
    }

    pub async fn subscribe(&self, topic: &str) -> broadcast::Receiver<SwarmMessage> {
        let sender = self.get_or_create_topic(topic).await;
        debug!("MessageBus: New subscription to '{}'", topic);
        sender.subscribe()
    }

    pub async fn get_history(&self, topic: &str) -> Result<Vec<SwarmMessage>, String> {
        if let Some(path) = &self.db_path {
            let path_clone = path.clone();
            let topic_clone = topic.to_string();
            
            tokio::task::spawn_blocking(move || {
                let conn = Connection::open(&path_clone)
                    .map_err(|e| format!("DB Open Error: {}", e))?;
                    
                let mut stmt = conn.prepare("SELECT sender, content FROM messages WHERE topic = ? ORDER BY id ASC")
                    .map_err(|e| format!("Query Error: {}", e))?;
                    
                let msg_iter = stmt.query_map(params![topic_clone], |row| {
                    Ok(SwarmMessage {
                        topic: topic_clone.clone(),
                        sender: row.get(0)?,
                        content: row.get(1)?,
                    })
                }).map_err(|e| format!("Map Error: {}", e))?;
                
                let mut messages = Vec::new();
                for msg in msg_iter {
                    if let Ok(m) = msg {
                        messages.push(m);
                    }
                }
                Ok(messages)
            }).await.map_err(|e| format!("Task Error: {}", e))?
        } else {
            Ok(vec![])
        }
    }
}
