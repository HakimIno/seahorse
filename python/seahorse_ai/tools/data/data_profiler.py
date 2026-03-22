from __future__ import annotations

import logging
from typing import Any

import polars as pl

from seahorse_ai.tools.base import tool
from seahorse_ai.tools.data.polars_analyst import _scan

logger = logging.getLogger(__name__)

_PROFILE_SAMPLE = 100_000  # Max rows to profile (prevents OOM on huge files)


def _fmt(v: Any) -> str:
    """Helper to format values for display."""
    if v is None:
        return "N/A"
    if isinstance(v, (float, int)):
        if abs(v) > 1_000_000:
            return f"{v / 1_000_000:,.1f}M"
        if isinstance(v, float):
            return f"{v:,.2f}"
        return f"{v:,}"
    return str(v)


@tool(
    "Generate a deep statistical profile of a dataset. "
    "Use this for data engineering tasks to identify data quality issues like "
    "null rates, cardinality, outliers, and data type inconsistencies."
)
async def data_profile(source_path: str) -> str:
    """Analyze a single file and return a comprehensive quality report."""
    try:
        lf = _scan(source_path)
        schema = lf.collect_schema()

        # ── Memory-safe sampling ──────────────────────────────────────────
        df = lf.fetch(_PROFILE_SAMPLE)
        total_rows = len(df)
        is_sampled = total_rows >= _PROFILE_SAMPLE

        if total_rows == 0:
            return f"[INFO] Dataset '{source_path.split('/')[-1]}' is empty (0 rows)."

        cols = df.columns

        lines = [
            f"📊 Data Profile: {source_path.split('/')[-1]}",
            f"Rows Analyzed: {total_rows:,}{' (sampled — dataset may be larger)' if is_sampled else ''} | Columns: {len(cols)}",
            "─" * 60,
        ]

        if is_sampled:
            lines.append("[WARNING] Showing profile of first 100K rows to protect memory.")
            lines.append("─" * 60)

        # Summary Table Header
        header = f"{'Column':<24} | {'Type':<12} | {'Nulls':<8} | {'Unique':<10}"
        lines.append(header)
        lines.append("─" * 60)

        for col in cols:
            series = df[col]
            dtype = str(series.dtype)
            null_count = series.null_count()
            null_pct = (null_count / total_rows) * 100
            n_unique = series.n_unique()

            row = f"{col[:24]:<24} | {dtype[:12]:<12} | {null_pct:>6.1f}% | {n_unique:>10,}"
            lines.append(row)

            # Additional Stats based on type
            stats_line = ""
            if series.dtype.is_numeric():
                res = df.select([
                    pl.col(col).mean().alias("mean"),
                    pl.col(col).min().alias("min"),
                    pl.col(col).max().alias("max"),
                    pl.col(col).std().alias("std"),
                ]).to_dicts()[0]
                stats_line = f"   └ Mean: {_fmt(res['mean'])} | Min: {_fmt(res['min'])} | Max: {_fmt(res['max'])} | Std: {_fmt(res['std'])}"

            elif series.dtype in (pl.Utf8, pl.String):
                top_v = series.drop_nulls().value_counts(sort=True).head(3)
                if not top_v.is_empty():
                    val_col = top_v.columns[0]  # series name (dynamic)
                    vals = [f"{r[val_col]} ({r['count']:,})" for r in top_v.to_dicts()]
                    stats_line = f"   └ Top Values: {', '.join(vals)}"

            elif series.dtype in (pl.Date, pl.Datetime):
                stats_line = f"   └ Range: {series.min()} to {series.max()}"

            if stats_line:
                lines.append(stats_line)

        return "\n".join(lines)

    except Exception as e:
        logger.error("data_profile failed: %s", e)
        return f"Error profiling data: {e}"
