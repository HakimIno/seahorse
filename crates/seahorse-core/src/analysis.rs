//! Native Polars analysis engine for high-performance data transformations.
//!
//! Provides tools to convert JSON data to Polars DataFrames and perform
//! aggregations, pivots, and filtering in Rust.

use polars::prelude::*;
use polars::io::json::{JsonReader, JsonWriter};
use crate::error::{CoreError, CoreResult};
use tracing::{debug, info};

/// High-performance data analysis engine powered by Polars.
pub struct PolarsAnalyst;

impl PolarsAnalyst {
    /// Create a new PolarsAnalyst.
    pub fn new() -> Self {
        Self
    }

    /// Perform a standard business aggregation on JSON data.
    ///
    /// # Arguments
    /// * `json_data` - A JSON array of objects.
    /// * `group_by` - Column to group by.
    /// * `agg_col` - Column to aggregate (e.g., 'total_amount').
    pub fn aggregate_json(
        &self,
        json_data: &str,
        group_by: &str,
        agg_col: &str,
    ) -> CoreResult<String> {
        debug!(group_by, agg_col, "Starting Polars aggregation");

        // 1. Parse JSON into a Polars DataFrame
        // Polars can read from a cursor of bytes
        let cursor = std::io::Cursor::new(json_data.as_bytes());
        let df = JsonReader::new(cursor)
            .finish()
            .map_err(|e| CoreError::Internal(format!("Failed to parse JSON into DataFrame: {e}")))?;

        // 2. Perform aggregation
        let mut result = df
            .lazy()
            .group_by([col(group_by)])
            .agg([col(agg_col).sum().alias("total")])
            .sort(
                ["total"],
                SortMultipleOptions::default()
                    .with_order_descending(true)
                    .with_multithreaded(true),
            )
            .collect()
            .map_err(|e| CoreError::Internal(format!("Aggregation failed: {e}")))?;

        info!(rows = result.height(), "Aggregation completed successfully");

        // 3. Serialise back to JSON
        let mut buf = Vec::new();
        JsonWriter::new(&mut buf)
            .finish(&mut result)
            .map_err(|e| CoreError::Internal(format!("Failed to serialise result to JSON: {e}")))?;

        Ok(String::from_utf8_lossy(&buf).to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_aggregation() {
        let analyst = PolarsAnalyst::new();
        let data = r#"[
            {"category": "A", "value": 10},
            {"category": "B", "value": 20},
            {"category": "A", "value": 30}
        ]"#;

        let result = analyst.aggregate_json(data, "category", "value").unwrap();
        assert!(result.contains("\"category\":\"A\""));
        assert!(result.contains("\"total\":40"));
    }
}
