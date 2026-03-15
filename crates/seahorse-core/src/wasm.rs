//! Wasm executor for sandboxed tool execution.
//!
//! Provides resource limits (fuel and memory) to prevent runaway tools.

use wasmtime::*;
use crate::error::{CoreError, CoreResult};
use tracing::{debug, info};

/// Manages Wasm execution environments.
pub struct WasmManager {
    engine: Engine,
}

impl WasmManager {
    /// Create a new WasmManager with fuel consumption enabled.
    pub fn new() -> CoreResult<Self> {
        let mut config = Config::new();
        config.consume_fuel(true);
        
        let engine = Engine::new(&config)
            .map_err(|e| CoreError::Wasm(format!("Failed to create Wasm engine: {e}")))?;
            
        info!("WasmManager initialised with fuel consumption enabled");
        Ok(Self { engine })
    }

    /// Run a Wasm module with the specified fuel and memory limits.
    ///
    /// # Arguments
    /// * `wasm_bytes` - The compiled Wasm binary or WAT text.
    /// * `fuel` - Maximum fuel allowed for execution.
    /// * `memory_mb` - Maximum linear memory allowed (in MB).
    pub fn run(&self, wasm_bytes: &[u8], fuel: u64, memory_mb: usize) -> CoreResult<String> {
        struct MemoryLimiter {
            max_bytes: usize,
        }

        impl ResourceLimiter for MemoryLimiter {
            fn memory_growing(
                &mut self,
                _current: usize,
                desired: usize,
                _maximum: Option<usize>,
            ) -> Result<bool> {
                Ok(desired <= self.max_bytes)
            }

            fn table_growing(
                &mut self,
                _current: u32,
                _desired: u32,
                _maximum: Option<u32>,
            ) -> Result<bool> {
                Ok(true)
            }
        }

        let mut store = Store::new(&self.engine, MemoryLimiter {
            max_bytes: memory_mb * 1024 * 1024,
        });
        store.limiter(|s| s);
        store.set_fuel(fuel).map_err(|e| CoreError::Wasm(format!("Fuel error: {e}")))?;

        debug!(fuel, memory_mb, "starting sandboxed wasm execution with memory limits");

        let module = Module::new(&self.engine, wasm_bytes)
            .map_err(|e| CoreError::Wasm(format!("Module compilation failed: {e}")))?;

        let linker = Linker::new(&self.engine);
        let instance = linker.instantiate(&mut store, &module)
            .map_err(|e| CoreError::Wasm(format!("Instantiation failed: {e}")))?;

        // Assume the module has a 'run' function for now
        let run_func = instance.get_typed_func::<(), ()>(&mut store, "run")
            .map_err(|e| CoreError::Wasm(format!("Failed to find 'run' function: {e}")))?;

        run_func.call(&mut store, ())
            .map_err(|e| CoreError::Wasm(format!("Wasm execution failed (might be out of fuel): {e}")))?;

        let remaining = store.get_fuel().unwrap_or(0);
        info!(consumed = fuel - remaining, "wasm execution completed");

        Ok("Success".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_wasm_fuel_limit() {
        let manager = WasmManager::new().unwrap();
        // Infinite loop WAT
        let wat = r#"
            (module
                (func (export "run")
                    (loop
                        (br 0)
                    )
                )
            )
        "#;
        let wasm = wat.as_bytes();
        
        // Run with very little fuel - should fail
        let result = manager.run(wasm, 100, 1);
        assert!(result.is_err(), "Expected failure due to fuel limit");
    }
}
