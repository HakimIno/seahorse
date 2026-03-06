use std::process::Command;

#[derive(Debug, Clone)]
pub struct WindowContext {
    pub app_name: String,
    pub bundle_id: String,
    pub window_title: String,
}

pub fn get_active_window_context() -> Option<WindowContext> {
    // We use `lsappinfo` which is a native MacOS tool more reliable for CLI watchers
    let output = Command::new("lsappinfo")
        .arg("info")
        .arg("-app")
        .arg(get_front_asn()?)
        .output().ok()?;

    let out_str = String::from_utf8_lossy(&output.stdout);
    
    // Parse the app name and bundleID from the output
    // Example line: "Brave Browser" ASN:0x0-0x12012: (in front) 
    // bundleID="com.brave.Browser"
    
    let mut app_name = "Unknown".to_string();
    let mut bundle_id = "unknown.bundle".to_string();

    for line in out_str.lines() {
        if line.contains("(in front)") {
            if let Some(name) = line.split('"').nth(1) {
                app_name = name.to_string();
            }
        }
        if line.contains("bundleID=") {
            if let Some(id) = line.split('"').nth(1) {
                bundle_id = id.to_string();
            }
        }
    }

    Some(WindowContext {
        app_name,
        bundle_id,
        window_title: "Active Window".to_string(),
    })
}

fn get_front_asn() -> Option<String> {
    let output = Command::new("lsappinfo")
        .arg("front")
        .output().ok()?;
    
    let out_str = String::from_utf8_lossy(&output.stdout).trim().to_string();
    // Expected: ASN:0x0-0x12012:
    if out_str.is_empty() {
        None
    } else {
        Some(out_str)
    }
}
