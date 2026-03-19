use pyo3::prelude::*;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

// GLOBAL_STATE packs:
// High 32 bits: Last failure timestamp (seconds)
// Low 32 bits: Failure count
static GLOBAL_STATE: AtomicU64 = AtomicU64::new(0);

const FAIL_THRESHOLD: u32 = 30;
const TIME_WINDOW_SEC: u64 = 60;

fn unpack(state: u64) -> (u64, u32) {
    let last = state >> 32;
    let count = state as u32;
    (last, count)
}

fn pack(last: u64, count: u32) -> u64 {
    (last << 32) | (count as u64)
}

fn get_current_time_sec() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

#[pyfunction]
pub fn record_global_failure() {
    let now = get_current_time_sec();
    
    let mut current = GLOBAL_STATE.load(Ordering::SeqCst);
    loop {
        let (last, count) = unpack(current);
        let next_count = if now.saturating_sub(last) > TIME_WINDOW_SEC {
            1
        } else {
            count.saturating_add(1)
        };
        
        let next = pack(now, next_count);
        match GLOBAL_STATE.compare_exchange_weak(current, next, Ordering::SeqCst, Ordering::SeqCst) {
            Ok(_) => break,
            Err(actual) => current = actual,
        }
    }
}

#[pyfunction]
pub fn is_system_healthy() -> bool {
    let now = get_current_time_sec();
    let current = GLOBAL_STATE.load(Ordering::SeqCst);
    let (last, count) = unpack(current);
    
    if count >= FAIL_THRESHOLD {
        if now.saturating_sub(last) < TIME_WINDOW_SEC {
            // System is tripped
            return false;
        } else {
            // Reset if old - use CAS to avoid losing a concurrent failure record
            let _ = GLOBAL_STATE.compare_exchange(current, pack(0, 0), Ordering::SeqCst, Ordering::SeqCst);
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
