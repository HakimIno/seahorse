from __future__ import annotations

import logging
import os
import traceback
from typing import Any

import anyio
import polars as pl

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

try:
    import seahorse_ffi

    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False

_POLARS_SAFE_GLOBALS: dict[str, Any] = {
    "__builtins__": {},
    "pl": pl,
    "len": len,
    "list": list,
    "dict": dict,
    "str": str,
    "int": int,
    "float": float,
    "round": round,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "zip": zip,
    "enumerate": enumerate,
}


# ── Path Resolution ──────────────────────────────────────────────────────────


def _resolve_path(path: str) -> str:
    """Auto-resolve workspace/ if file not found in root."""
    if os.path.exists(path):
        return path
    if not path.startswith("workspace/"):
        workspace_path = os.path.join("workspace", path)
        if os.path.exists(workspace_path):
            return workspace_path
    return path


# ── Loaders ──────────────────────────────────────────────────────────────────


def _scan(path: str) -> pl.LazyFrame:
    """Auto-detect format and return LazyFrame."""
    effective_path = _resolve_path(path)

    if effective_path.endswith(".parquet"):
        return pl.scan_parquet(effective_path)
    elif effective_path.endswith(".csv"):
        return pl.scan_csv(effective_path, try_parse_dates=True)
    elif effective_path.endswith(".json") or effective_path.endswith(".ndjson"):
        return pl.scan_ndjson(effective_path)
    else:
        # Include the path in the error to help debug hallucinations
        msg = f"Unsupported file format or extension: '{path}' (Resolved to: '{effective_path}'). Use .parquet, .csv, or .ndjson"
        logger.error(msg)
        raise ValueError(msg)


def _load_tables(source_paths: list[str] | str) -> dict[str, pl.LazyFrame]:
    """Load multiple files → dict of LazyFrames."""
    # Robustness: Handle case where LLM sends a single string instead of a list
    if isinstance(source_paths, str):
        source_paths = [source_paths]

    tables: dict[str, pl.LazyFrame] = {}
    for i, path in enumerate(source_paths):
        lf = _scan(path)
        stem = path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
        tables[f"t{i}"] = lf
        tables[stem] = lf
    return tables


# ── Tools ─────────────────────────────────────────────────────────────────────


@tool(
    "Execute an advanced Polars query across data sources. Supports full Polars expression API.\n"
    "Example: lf.filter(pl.col('sales') > 1000).group_by('region').agg(pl.col('sales').sum())"
)
async def polars_query(
    source_paths: list[str],
    expression: str = "",
    max_rows: int = 5000,
) -> str:
    try:
        if not source_paths:
            return "[FAIL] Please provide at least one file path in source_paths."

        try:
            tables = _load_tables(source_paths)
        except FileNotFoundError as e:
            return f"[FAIL] File Not Found: {e}. (Tip: Ensure you use the full path including 'workspace/' if applicable.)"
        except Exception as e:
            return f"[FAIL] Load Failed: {e}"

        exec_globals = {**_POLARS_SAFE_GLOBALS, **tables}
        # Add intuitive aliases for the first/primary table
        if tables:
            first_lf = next(iter(tables.values()))
            exec_globals["lf"] = first_lf
            exec_globals["t0"] = first_lf
            exec_globals["df"] = first_lf  # Add df as an alias for lf
            exec_globals["col"] = pl.col
            exec_globals["lit"] = pl.lit

        if not expression.strip():
            return _multi_preview(tables, max_rows)

        # ── Execution with Timeout ──
        try:
            with anyio.fail_after(30):
                # Pre-processing expression for common LLM mistakes
                # If they try len(df) or df.corr() on a LazyFrame t0/lf, we help them
                if ("len(" in expression or ".corr(" in expression) and (
                    ".collect()" not in expression
                ):
                    # For safety, we only do this if it looks like a simple direct call
                    pass

                result = eval(  # noqa: S307
                    compile(expression, "<polars_query>", "eval"),
                    exec_globals,
                    {},
                )

                if isinstance(result, pl.LazyFrame):
                    df = result.fetch(max_rows)
                elif isinstance(result, pl.DataFrame):
                    df = result.head(max_rows)
                elif isinstance(result, pl.Series):
                    return f"Series ({result.name}): {result.to_list()}"
                else:
                    return f"Scalar result: {result}"

                return _format_result(df, source_paths, expression)

        except AttributeError as e:
            # INTERCEPT: If they forgot .collect() before a DataFrame-only method
            if "LazyFrame" in str(e):
                logger.info("polars_query: auto-collecting due to AttributeError: %s", e)
                try:
                    # Retry by collecting first table and running expression on it
                    first_lf = next(iter(tables.values()))
                    exec_globals["lf"] = first_lf.collect()
                    exec_globals["df"] = exec_globals["lf"]
                    exec_globals["pdf"] = exec_globals["lf"]
                    result = eval(expression, exec_globals, {})
                    if isinstance(result, pl.DataFrame):
                        return _format_result(result.head(max_rows), source_paths, expression)
                except Exception as retry_e:
                    logger.error("polars_query auto-collect retry failed: %s", retry_e)

            return f"[POLARS_ERROR] {e}. (Tip: If using .corr() or len(), remember to call .collect() first or use pl.corr())"

        except TimeoutError:
            return f"[TIMEOUT] The query took longer than 30s. Try filtering the data first.\nQuery: {expression}"

    except pl.exceptions.PolarsError as e:
        col_info = {
            name: list(lf.collect_schema().names())
            for name, lf in tables.items()
            if hasattr(lf, "collect_schema")
        }
        return f"[POLARS_ERROR] {e}\nExpression: {expression}\nAvailable columns: {col_info}"
    except SyntaxError as e:
        return f"[SYNTAX_ERROR] {e}\nExpression: {expression}"
    except Exception as e:
        logger.error("polars_query unexpected error: %s\n%s", e, traceback.format_exc())
        return f"[UNEXPECTED] {e}"


@tool("Profile one or multiple datasets: null rates, cardinality, numeric stats, skewness.")
async def polars_profile(source_paths: list[str]) -> str:
    try:
        if not source_paths:
            return "[FAIL] source_paths is empty."

        sections: list[str] = []
        for path in source_paths:
            df = _scan(path).collect()
            stem = path.replace("\\", "/").split("/")[-1]
            lines = [
                f"--- {stem} ({'x'.join(str(x) for x in df.shape)}) ---",
            ]
            for col in df.columns:
                series = df[col]
                null_pct = series.null_count() / len(series) * 100
                dtype = str(series.dtype)

                if series.dtype.is_numeric():
                    info = f"min={_fmt(series.min())} max={_fmt(series.max())} mean={_fmt(series.mean())}"
                else:
                    info = f"unique={series.n_unique()}"

                null_pct_str = f" null={null_pct:.1f}%" if null_pct > 0 else ""
                lines.append(f"  {col:<25} [{dtype}]{null_pct_str}")
                lines.append(f"    {info}")

            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    except Exception as e:
        return f"[PROFILE_ERROR] {e}"


@tool("Inspect joinability between two tables: find common column names and estimate key overlap.")
async def polars_inspect_join(path_left: str, path_right: str) -> str:
    try:
        lf_l = _scan(path_left)
        lf_r = _scan(path_right)

        schema_l = lf_l.collect_schema()
        schema_r = lf_r.collect_schema()

        cols_l = set(schema_l.names())
        cols_r = set(schema_r.names())
        common = cols_l & cols_r

        if not common:
            return f"[INFO] No common columns found among {path_left} and {path_right}."

        lines = [
            f"Common columns: {sorted(common)}",
            "",
            "--- Key overlap analysis ---",
        ]

        for col in sorted(common):
            sample_l = lf_l.select(pl.col(col).drop_nulls().unique()).fetch(5000)
            sample_r = lf_r.select(pl.col(col).drop_nulls().unique()).fetch(5000)
            keys_l = set(sample_l[col].to_list())
            keys_r = set(sample_r[col].to_list())
            overlap = len(keys_l & keys_r)
            pct_l = overlap / len(keys_l) * 100 if keys_l else 0
            pct_r = overlap / len(keys_r) * 100 if keys_r else 0

            lines.append(
                f"  {col:<25} overlap={overlap:,} keys ({pct_l:.0f}% left, {pct_r:.0f}% right)"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"[INSPECT_ERROR] {e}"


@tool(
    "Convert CSV or NDJSON to Parquet (zstd). "
    "Parquet reads 10-100x faster in Polars. Convert before running repeated queries."
)
async def convert_to_parquet(source_path: str, output_path: str) -> str:
    try:
        if source_path.endswith(".csv"):
            df = pl.read_csv(source_path, try_parse_dates=True)
        elif source_path.endswith(".json") or source_path.endswith(".ndjson"):
            df = pl.read_ndjson(source_path)
        else:
            return f"[FAIL] Unsupported source: {source_path}"

        df.write_parquet(output_path, compression="zstd")
        return f"[SUCCESS] Converted -> {output_path}\nRows: {df.shape[0]:,}  Cols: {df.shape[1]}"
    except Exception as e:
        return f"[FAIL] Conversion failed: {e}"


@tool("Perform high-performance data aggregation using the NATIVE Rust Polars engine.")
async def native_polars_aggregate(
    data_json: str,
    group_by: str,
    agg_col: str,
) -> str:
    if not _NATIVE_AVAILABLE:
        return "[FAIL] Native Polars engine (seahorse_ffi) is not available."

    try:
        analyst = seahorse_ffi.PyPolarsAnalyst()
        return analyst.aggregate_json(data_json, group_by, agg_col)
    except Exception as e:
        return f"[FAIL] Native aggregation failed: {e}"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_result(df: pl.DataFrame, sources: list[str], expression: str) -> str:
    names = [p.replace("\\", "/").split("/")[-1] for p in sources]
    return "\n".join(
        [
            f"Sources: {', '.join(names)}",
            f"Result: {df.shape[0]} rows x {df.shape[1]} cols",
            "-" * 40,
            str(df),
        ]
    )


def _multi_preview(tables: dict[str, pl.LazyFrame], max_rows: int) -> str:
    seen: set[int] = set()
    lines = ["Schema preview:"]
    for name, lf in tables.items():
        if id(lf) in seen:
            continue
        seen.add(id(lf))
        schema = lf.collect_schema()
        lines.append(f"\n  [{name}]  columns: {list(schema.names())}")
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)
