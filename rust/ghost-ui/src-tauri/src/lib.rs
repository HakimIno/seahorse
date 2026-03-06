use tauri::{Emitter, Manager};
use ghost_core::GhostNode;
#[tauri::command]
fn get_status() -> String {
    "Ghost Node Active".to_string()
}

#[tauri::command]
fn send_ghost_command(state: tauri::State<'_, GhostNode>, cmd: String) {
    state.send_command(cmd);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let node = GhostNode::new();
    
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(node.clone())
        .setup(|app| {
            let handle = app.handle().clone();
            let state = app.state::<GhostNode>().inner().clone();
            
            // Spawn Ghost Node in background using the SAME state
            tauri::async_runtime::spawn(async move {
                let _ = state.run_with_state(|msg| {
                    let _ = handle.emit("ghost-event", msg);
                }).await;
            });
            
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_status, send_ghost_command])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
