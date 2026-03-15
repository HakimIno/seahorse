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
    pub fn publish(&self, py: Python<'_>, topic: String, sender: String, content: String) -> PyResult<usize> {
        let bus = self.inner.clone();
        let message = SwarmMessage {
            topic,
            sender,
            content,
        };
        
        let size = py.allow_threads(|| {
            let rt = tokio::runtime::Handle::current();
            rt.block_on(async {
                bus.publish(message).await.unwrap_or(0)
            })
        });
        Ok(size)
    }

    /// Get a subscriber for a topic. Returns a PyMessageReceiver.
    pub fn subscribe(&self, py: Python<'_>, topic: String) -> PyResult<PyMessageReceiver> {
        let bus = self.inner.clone();
        let rx = py.allow_threads(|| {
            let rt = tokio::runtime::Handle::current();
            rt.block_on(async {
                bus.subscribe(&topic).await
            })
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
    /// Non-blocking check for the next message. Returns message dict or None.
    pub fn try_recv<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
        let mut rx = self.rx.try_lock().map_err(|_| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Lock contention"))?;
        
        match rx.try_recv() {
            Ok(msg) => {
                let dict = PyDict::new_bound(py);
                dict.set_item("topic", msg.topic)?;
                dict.set_item("sender", msg.sender)?;
                dict.set_item("content", msg.content)?;
                Ok(Some(dict))
            },
            Err(tokio::sync::broadcast::error::TryRecvError::Empty) => Ok(None),
            Err(tokio::sync::broadcast::error::TryRecvError::Lagged(_)) => Ok(None),
            Err(tokio::sync::broadcast::error::TryRecvError::Closed) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Channel closed")),
        }
    }

    /// Blocking wait for the next message on this topic subscription.
    /// (Optimised to yield more frequently to the Python GIL)
    pub fn recv<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let rx_mutex = self.rx.clone();
        
        py.allow_threads(move || {
            loop {
                let rt = tokio::runtime::Handle::current();
                let result = rt.block_on(async {
                    let mut rx = rx_mutex.lock().await;
                    match tokio::time::timeout(std::time::Duration::from_millis(50), rx.recv()).await {
                        Ok(Ok(m)) => Some(m),
                        _ => None,
                    }
                });

                if let Some(m) = result {
                    return Ok(m);
                }
                
                // Check for signals frequently
                Python::with_gil(|py| py.check_signals())?;
            }
        }).and_then(|msg| {
            let dict = PyDict::new_bound(py);
            dict.set_item("topic", msg.topic)?;
            dict.set_item("sender", msg.sender)?;
            dict.set_item("content", msg.content)?;
            Ok(dict)
        })
    }
}
