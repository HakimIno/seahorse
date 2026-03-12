use pyo3::prelude::*;
use pyo3::types::PyDict;
use seahorse_core::bus::{MessageBus, SwarmMessage};
use std::sync::Arc;

/// Python accessible wrapper for the Swarm MessageBus
#[pyclass]
#[derive(Clone)]
pub struct PyMessageBus {
    inner: Arc<MessageBus>,
}

#[pymethods]
impl PyMessageBus {
    #[new]
    #[pyo3(signature = (capacity = 1024))]
    pub fn new(capacity: usize) -> Self {
        Self {
            inner: Arc::new(MessageBus::new(capacity)),
        }
    }

    /// Publish a message to a topic. Non-blocking.
    pub fn publish(&self, _py: Python<'_>, topic: String, sender: String, content: String) -> PyResult<usize> {
        let bus = self.inner.clone();
        let message = SwarmMessage {
            topic,
            sender,
            content,
        };
        
        let rt = tokio::runtime::Handle::current();
        let size = rt.block_on(async {
            bus.publish(message).await.unwrap_or(0)
        });
        Ok(size)
    }

    /// Get a subscriber for a topic. Returns a PyMessageReceiver.
    pub fn subscribe(&self, _py: Python<'_>, topic: String) -> PyResult<PyMessageReceiver> {
        let bus = self.inner.clone();
        let rt = tokio::runtime::Handle::current();
        let rx = rt.block_on(async {
            bus.subscribe(&topic).await
        });
        
        Ok(PyMessageReceiver {
            rx: Arc::new(tokio::sync::Mutex::new(rx)),
            topic,
        })
    }
}

/// A Python iterator/async generator over received messages.
#[pyclass]
#[derive(Clone)]
pub struct PyMessageReceiver {
    rx: Arc<tokio::sync::Mutex<tokio::sync::broadcast::Receiver<SwarmMessage>>>,
    pub topic: String,
}

#[pymethods]
impl PyMessageReceiver {
    /// Blocking wait for the next message on this topic subscription.
    pub fn recv<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let rx_mutex = self.rx.clone();
        
        // Release GIL while waiting
        let msg = py.allow_threads(move || {
            loop {
                // We must use a short blocking wait here or `try_recv` to not lock Tokio 
                let rt = tokio::runtime::Handle::current();
                let result = rt.block_on(async {
                    let mut rx = rx_mutex.lock().await;
                    // timeout after 100ms so we can check Python signals and release GIL
                    match tokio::time::timeout(std::time::Duration::from_millis(100), rx.recv()).await {
                        Ok(Ok(m)) => Some(m),
                        Ok(Err(tokio::sync::broadcast::error::RecvError::Lagged(_))) => None,
                        Ok(Err(tokio::sync::broadcast::error::RecvError::Closed)) => panic!("Channel closed"),
                        Err(_) => None, // timeout
                    }
                });

                if let Some(m) = result {
                    return m;
                }
                
                // If we get here it was a timeout or lag, allow python to tick
                std::thread::sleep(std::time::Duration::from_millis(10));
                
                // Explicitly check for signals (e.g., Ctrl+C)
                if let Err(e) = Python::with_gil(|py| py.check_signals()) {
                    // Panic here will be caught by PyO3 and turned into a Python exception
                    panic!("Python signal received: {e:?}");
                }
            }
        });

        let dict = PyDict::new_bound(py);
        dict.set_item("topic", msg.topic)?;
        dict.set_item("sender", msg.sender)?;
        dict.set_item("content", msg.content)?;
        Ok(dict)
    }
}
