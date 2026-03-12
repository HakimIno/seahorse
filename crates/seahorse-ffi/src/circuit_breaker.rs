use pyo3::prelude::*;
use std::sync::atomic::{AtomicUsize, AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

// Very fast global counters instead of DashMap for a single global breaker
static GLOBAL_FAIL_COUNT: AtomicUsize = AtomicUsize::new(0);
static GLOBAL_LAST_FAIL: AtomicU64 = AtomicU64::new(0);

const FAIL_THRESHOLD: usize = 30;
const TIME_WINDOW_SEC: u64 = 60;

fn get_current_time_sec() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

#[pyfunction]
pub fn record_global_failure() {
    let now = get_current_time_sec();
    let last = GLOBAL_LAST_FAIL.swap(now, Ordering::Relaxed);
    
    // Reset counter if outside window
    if now.saturating_sub(last) > TIME_WINDOW_SEC {
        GLOBAL_FAIL_COUNT.store(1, Ordering::Relaxed);
    } else {
        GLOBAL_FAIL_COUNT.fetch_add(1, Ordering::Relaxed);
    }
}

#[pyfunction]
pub fn is_system_healthy() -> bool {
    let count = GLOBAL_FAIL_COUNT.load(Ordering::Relaxed);
    let last = GLOBAL_LAST_FAIL.load(Ordering::Relaxed);
    let now = get_current_time_sec();
    
    if count >= FAIL_THRESHOLD {
        if now.saturating_sub(last) < TIME_WINDOW_SEC {
            // System is tripped
            return false;
        } else {
            // Reset if old
            GLOBAL_FAIL_COUNT.store(0, Ordering::Relaxed);
            GLOBAL_LAST_FAIL.store(0, Ordering::Relaxed);
            return true;
        }
    }
    true
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(record_global_failure, m)?)?;
    m.add_function(wrap_pyfunction!(is_system_healthy, m)?)?;
    Ok(())
}
