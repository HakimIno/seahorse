from __future__ import annotations

import logging
from typing import Literal

import polars as pl

from seahorse_ai.tools.base import tool
from seahorse_ai.tools.data.polars_analyst import _scan

logger = logging.getLogger(__name__)

@tool(
    "Detect numeric anomalies (outliers) in a massive dataset without loading it into memory. "
    "Supports 'zscore' for normally distributed data and 'iqr' for skewed data. "
    "Returns a summary and a preview of the anomalous rows."
)
async def detect_numeric_anomalies(
    source_path: str,
    target_column: str,
    method: Literal["zscore", "iqr"] = "iqr",
    threshold: float = 3.0,
    max_rows_to_return: int = 50,
) -> str:
    """Find anomalous values in a large dataset using Z-Score or IQR."""
    try:
        lf = _scan(source_path)

        # Check if column exists and is numeric
        schema = lf.collect_schema()
        if target_column not in schema.names():
            return f"[FAIL] Column '{target_column}' not found. Available cols: {schema.names()}"
        if not schema[target_column].is_numeric():
            return f"[FAIL] Target column '{target_column}' is not numeric. Type: {schema[target_column]}"

        total_rows = lf.select(pl.count()).collect().item()

        if method == "zscore":
            # Z-Score Method: |(x - mean) / std| > threshold
            stats = lf.select([
                pl.col(target_column).mean().alias("mean"),
                pl.col(target_column).std().alias("std")
            ]).collect().to_dicts()[0]
            
            mean_val = stats["mean"]
            std_val = stats["std"]
            
            if std_val == 0 or std_val is None:
                return f"[INFO] Column '{target_column}' has zero variance. Cannot compute Z-score."

            anomalies_lf = lf.filter(
                ((pl.col(target_column) - mean_val) / std_val).abs() > threshold
            )
            report_method = f"Z-Score (threshold={threshold}, mean={mean_val:.2f}, std={std_val:.2f})"
            
        else:
            # IQR Method: x < Q1 - threshold*IQR or x > Q3 + threshold*IQR
            # For massive lazily evaluated data:
            q1 = lf.select(pl.col(target_column).quantile(0.25)).collect().item()
            q3 = lf.select(pl.col(target_column).quantile(0.75)).collect().item()
            iqr = q3 - q1
            
            lower_bound = q1 - (threshold * iqr)
            upper_bound = q3 + (threshold * iqr)
            
            anomalies_lf = lf.filter(
                (pl.col(target_column) < lower_bound) | (pl.col(target_column) > upper_bound)
            )
            report_method = f"IQR (threshold={threshold}, lower={lower_bound:.2f}, upper={upper_bound:.2f})"

        # Collect results
        anomalies_df = anomalies_lf.collect()
        anomaly_count = len(anomalies_df)
        anomaly_pct = (anomaly_count / total_rows) * 100 if total_rows > 0 else 0

        # Build Report
        lines = [
            f"🔍 Anomaly Detection Report: {source_path.split('/')[-1]}",
            f"Target Column: {target_column} | Method: {report_method}",
            f"Total Rows: {total_rows:,} | Anomalies Found: {anomaly_count:,} ({anomaly_pct:.2f}%)",
            "─" * 60,
        ]

        if anomaly_count == 0:
            lines.append("✅ No anomalies detected.")
            return "\n".join(lines)

        lines.append(f"Top {min(anomaly_count, max_rows_to_return)} most extreme anomalies:")
        
        # Sort by distance from center to show the most extreme ones first
        if method == "zscore":
            sort_expr = ((pl.col(target_column) - mean_val).abs())
        else:
            # For IQR we approximate center as median
            median = lf.select(pl.col(target_column).median()).collect().item()
            sort_expr = ((pl.col(target_column) - median).abs())
            
        extreme_df = anomalies_df.with_columns(
            _anomaly_score=sort_expr
        ).sort("_anomaly_score", descending=True).drop("_anomaly_score").head(max_rows_to_return)

        lines.append(str(extreme_df))
        return "\n".join(lines)

    except Exception as e:
        logger.error("detect_numeric_anomalies failed: %s", e)
        return f"[ERROR] Failed to detect anomalies: {e}"


@tool(
    "Detect time-series anomalies (spikes/drops) using rolling window statistics. "
    "Useful for finding sudden crashes in stock prices or spikes in server traffic."
)
async def detect_timeseries_anomalies(
    source_path: str,
    time_column: str,
    target_column: str,
    window_size: int = 7,
    threshold: float = 3.0,
    max_rows_to_return: int = 50,
) -> str:
    """Find unexpected spikes or drops over time."""
    try:
        df = _scan(source_path).collect() # Time series operations are often easier in-memory if ordered

        # Check schema
        if time_column not in df.columns or target_column not in df.columns:
            return f"[FAIL] Check column names. Available: {df.columns}"

        # Sort by time
        df = df.sort(time_column)

        # Calculate Rolling Mean and Std
        rolling_mean = df[target_column].rolling_mean(window_size=window_size)
        rolling_std = df[target_column].rolling_std(window_size=window_size)
        
        # Avoid division by zero
        rolling_std = rolling_std.fill_null(1.0)
        rolling_std = pl.when(rolling_std == 0).then(1.0).otherwise(rolling_std)

        # Z-score within window
        df_with_stats = df.with_columns([
            rolling_mean.alias("rolling_mean"),
            rolling_std.alias("rolling_std")
        ])
        
        df_with_stats = df_with_stats.with_columns(
            ((pl.col(target_column) - pl.col("rolling_mean")) / pl.col("rolling_std")).alias("local_zscore")
        )

        anomalies_df = df_with_stats.filter(pl.col("local_zscore").abs() > threshold)
        
        anomaly_count = len(anomalies_df)
        total_rows = len(df)
        anomaly_pct = (anomaly_count / total_rows) * 100 if total_rows > 0 else 0

        lines = [
            f"📈 Time-Series Anomaly Report: {source_path.split('/')[-1]}",
            f"Time Col: {time_column} | Target Col: {target_column} | Window: {window_size} | Threshold: {threshold} StdDev",
            f"Total Rows: {total_rows:,} | Spikes/Drops Found: {anomaly_count:,} ({anomaly_pct:.2f}%)",
            "─" * 60,
        ]

        if anomaly_count == 0:
            lines.append("✅ No sudden spikes or drops detected.")
            return "\n".join(lines)

        lines.append(f"Top {min(anomaly_count, max_rows_to_return)} most extreme events:")
        
        extreme_df = anomalies_df.sort("local_zscore", descending=True).head(max_rows_to_return)
        lines.append(str(extreme_df))
        
        return "\n".join(lines)

    except Exception as e:
        logger.error("detect_timeseries_anomalies failed: %s", e)
        return f"[ERROR] Failed to detect time-series anomalies: {e}"
