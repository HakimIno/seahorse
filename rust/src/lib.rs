use libp2p::{
    futures::StreamExt,
    gossipsub, mdns, noise, swarm::NetworkBehaviour, swarm::SwarmEvent, tcp, yamux,
};
use std::error::Error;
use std::time::Duration;
use tokio::time;
use std::sync::{Arc, Mutex};
use pyo3::prelude::*;

pub mod platform;

#[derive(NetworkBehaviour)]
pub struct GhostBehaviour {
    pub gossipsub: gossipsub::Behaviour,
    pub mdns: mdns::tokio::Behaviour,
}

// Internal state that doesn't depend on PyO3
#[derive(Clone)]
pub struct NodeState {
    pub peer_id: Arc<Mutex<String>>,
    pub latest_context: Arc<Mutex<String>>,
    pub pending_command: Arc<Mutex<String>>,
}

#[pyclass]
#[derive(Clone)]
pub struct GhostNode {
    state: NodeState,
}

#[pymethods]
impl GhostNode {
    #[new]
    pub fn new() -> Self {
        GhostNode {
            state: NodeState {
                peer_id: Arc::new(Mutex::new("Initializing...".to_string())),
                latest_context: Arc::new(Mutex::new("Unknown".to_string())),
                pending_command: Arc::new(Mutex::new("NONE".to_string())),
            },
        }
    }

    pub fn get_peer_id(&self) -> String {
        self.state.peer_id.lock().unwrap().clone()
    }

    pub fn get_latest_context(&self) -> String {
        self.state.latest_context.lock().unwrap().clone()
    }

    pub fn publish_insight(&self, text: String) {
        *self.state.latest_context.lock().unwrap() = format!("INSIGHT:{}", text);
    }

    pub fn send_command(&self, cmd: String) {
        *self.state.pending_command.lock().unwrap() = format!("SEND:{}", cmd);
    }

    pub fn get_pending_command(&self) -> String {
        let mut cmd = self.state.pending_command.lock().unwrap();
        let current = cmd.clone();
        if current != "NONE" && !current.starts_with("SEND:") {
            *cmd = "NONE".to_string();
        }
        current
    }

    pub fn start_background(&self) {
        let state = self.state.clone();
        std::thread::spawn(move || {
            let rt = tokio::runtime::Runtime::new().unwrap();
            rt.block_on(async {
                let _ = run_internal(state, |msg| {
                    println!("GhostNode Internal: {}", msg);
                }).await;
            });
        });
    }
}

// Compatibility layer for CLI/Tauri
impl GhostNode {
    pub async fn run_with_state(&self, callback: impl Fn(String)) -> Result<(), Box<dyn Error>> {
        run_internal(self.state.clone(), callback).await
    }

    pub async fn run(callback: impl Fn(String)) -> Result<(), Box<dyn Error>> {
        let node = GhostNode::new();
        run_internal(node.state, callback).await
    }
}

async fn run_internal(state: NodeState, callback: impl Fn(String)) -> Result<(), Box<dyn Error>> {
    let mut swarm = libp2p::SwarmBuilder::with_new_identity()
        .with_tokio()
        .with_tcp(
            tcp::Config::default(),
            noise::Config::new,
            yamux::Config::default,
        )?
        .with_behaviour(|key| {
            let gossipsub_config = gossipsub::ConfigBuilder::default()
                .heartbeat_interval(Duration::from_secs(10))
                .validation_mode(gossipsub::ValidationMode::Strict)
                .build()
                .map_err(|s| Box::<dyn Error + Send + Sync>::from(s))?;
            
            let mut gossipsub = gossipsub::Behaviour::new(
                gossipsub::MessageAuthenticity::Signed(key.clone()),
                gossipsub_config,
            ).map_err(|s| Box::<dyn Error + Send + Sync>::from(s))?;

            let topic = gossipsub::IdentTopic::new("context-updates");
            let _ = gossipsub.subscribe(&topic);

            Ok(GhostBehaviour {
                gossipsub,
                mdns: mdns::tokio::Behaviour::new(mdns::Config::default(), key.public().to_peer_id())?,
            })
        })?
        .build();

    swarm.listen_on("/ip4/0.0.0.0/tcp/0".parse()?)?;
    let peer_id = swarm.local_peer_id().to_string();
    *state.peer_id.lock().unwrap() = peer_id.clone();
    callback(format!("START:{}", peer_id));

    let mut interval = time::interval(Duration::from_secs(1));
    let mut last_context = String::new();
    let mut last_insight = String::new();
    let mut last_command_sent = String::new();

    loop {
        tokio::select! {
            _ = interval.tick() => {
                if let Some(ctx) = platform::macos::get_active_window_context() {
                    let current_context = format!("{} ({})", ctx.app_name, ctx.bundle_id);
                    if current_context != last_context {
                        last_context = current_context.clone();
                        *state.latest_context.lock().unwrap() = current_context.clone();
                        callback(format!("LOCAL_CONTEXT:{}", current_context));
                        
                        let topic = gossipsub::IdentTopic::new("context-updates");
                        let _ = swarm.behaviour_mut().gossipsub.publish(topic, last_context.as_bytes());
                    }
                }

                let insight = state.latest_context.lock().unwrap().clone();
                if insight.starts_with("INSIGHT:") && insight != last_insight {
                    last_insight = insight.clone();
                    let topic = gossipsub::IdentTopic::new("context-updates");
                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, format!("💡 insight: {}", &insight[8..]).as_bytes());
                }

                // Check for commands to send
                let cmd = state.pending_command.lock().unwrap().clone();
                if cmd.starts_with("SEND:") && cmd != last_command_sent {
                    last_command_sent = cmd.clone();
                    let topic = gossipsub::IdentTopic::new("context-updates");
                    let _ = swarm.behaviour_mut().gossipsub.publish(topic, format!("COMMAND:{}", &cmd[5..]).as_bytes());
                    callback(format!("DEBUG: Sent command {}", &cmd[5..]));
                }
            }
            event = swarm.select_next_some() => match event {
                SwarmEvent::Behaviour(GhostBehaviourEvent::Mdns(mdns::Event::Discovered(list))) => {
                    for (peer_id, _multiaddr) in list {
                        callback(format!("PEER:{}", peer_id));
                        swarm.behaviour_mut().gossipsub.add_explicit_peer(&peer_id);
                    }
                }
                SwarmEvent::Behaviour(GhostBehaviourEvent::Gossipsub(gossipsub::Event::Message {
                    propagation_source: peer_id,
                    message,
                    ..
                })) => {
                    let msg_content = String::from_utf8_lossy(&message.data);
                    if msg_content.starts_with("COMMAND:") {
                        let cmd_text = msg_content[8..].to_string();
                        // Store the command so Python can read it
                        *state.pending_command.lock().unwrap() = cmd_text.clone();
                        callback(format!("RECEIVED_COMMAND:{}:{}", peer_id, cmd_text));
                    } else {
                        callback(format!("GLOBAL_CONTEXT:{}:{}", peer_id, msg_content));
                    }
                }
                _ => {}
            }
        }
    }
}

#[pymodule]
fn ghost_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<GhostNode>()?;
    Ok(())
}
