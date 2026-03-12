use std::collections::HashMap;
use tokio::sync::{broadcast, RwLock};
use tracing::{debug, info};

#[derive(Clone, Debug)]
pub struct SwarmMessage {
    pub topic: String,
    pub sender: String,
    pub content: String,
}

pub struct MessageBus {
    channels: RwLock<HashMap<String, broadcast::Sender<SwarmMessage>>>,
    channel_capacity: usize,
}

impl MessageBus {
    pub fn new(channel_capacity: usize) -> Self {
        Self {
            channels: RwLock::new(HashMap::new()),
            channel_capacity,
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
}
