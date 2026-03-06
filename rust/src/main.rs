use ghost_core::GhostNode;
use std::error::Error;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    println!("👻 Ghost Node (CLI) starting...");
    
    GhostNode::run(|msg| {
        if msg.starts_with("START:") {
            println!("👻 Peer ID: {}", &msg[6..]);
        } else if msg.starts_with("LOCAL_CONTEXT:") {
            println!("\n👻 CONTEXT CHANGED: {}", &msg[14..]);
        } else if msg.starts_with("PEER:") {
            println!("👻 Discovered peer: {}", &msg[5..]);
        } else if msg.starts_with("GLOBAL_CONTEXT:") {
            println!("👻 Global Context Update: {}", &msg[15..]);
        } else {
            print!(".");
            use std::io::{self, Write};
            io::stdout().flush().unwrap();
        }
    }).await
}
