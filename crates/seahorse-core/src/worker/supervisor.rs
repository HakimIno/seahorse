use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Instant;
use tracing::{error, warn};

use crate::worker::runner::PythonRunner;

pub(crate) struct HeartbeatSupervisor {
    active_tasks: Arc<Mutex<HashMap<String, Instant>>>,
    runner: Arc<dyn PythonRunner>,
}

impl HeartbeatSupervisor {
    pub(crate) fn new(runner: Arc<dyn PythonRunner>) -> Self {
        Self {
            active_tasks: Arc::new(Mutex::new(HashMap::new())),
            runner,
        }
    }

    pub(crate) fn start(&self) {
        let active_tasks = self.active_tasks.clone();
        let runner = self.runner.clone();
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(std::time::Duration::from_secs(30));
            loop {
                interval.tick().await;

                // 1. Health check
                if let Err(e) = runner.health_check() {
                    error!(err = %e, "Supervisor: Python health check failed!");
                }

                // 2. Identify stale tasks
                let now = Instant::now();
                let stale: Vec<String> = {
                    let guard = active_tasks.lock().unwrap();
                    guard
                        .iter()
                        .filter(|(_, &start)| now.duration_since(start).as_secs() > 300)
                        .map(|(id, _): (&String, &Instant)| id.clone())
                        .collect()
                };

                for id in stale {
                    warn!(task_id = %id, "Supervisor: task is stalling (> 5 mins)");
                }
            }
        });
    }

    pub(crate) fn track(&self, id: String) {
        self.active_tasks.lock().unwrap().insert(id, Instant::now());
    }

    pub(crate) fn untrack(&self, id: &str) {
        self.active_tasks.lock().unwrap().remove(id);
    }
}
