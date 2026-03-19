from __future__ import annotations

import logging
import traceback
from typing import Any

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

# ── Loaders ──────────────────────────────────────────────────────────────────

def _scan(path: str) -> pl.LazyFrame:
    """Auto-detect format and return LazyFrame."""
    if path.endswith(".parquet"):
        return pl.scan_parquet(path)
    elif path.endswith(".csv"):
        return pl.scan_csv(path, try_parse_dates=True)
    elif path.endswith(".json") or path.endswith(".ndjson"):
        return pl.scan_ndjson(path)
    else:
        raise ValueError(f"Unsupported file format: {path}. Use .parquet, .csv, or .ndjson")


def _load_tables(source_paths: list[str]) -> dict[str, pl.LazyFrame]:
    """
    Load multiple files → dict of LazyFrames.
    Keys: t0, t1, t2, ... (positional) + stem name (e.g. 'orders' from orders.parquet)
    """
    tables: dict[str, pl.LazyFrame] = {}
    for i, path in enumerate(source_paths):
        lf = _scan(path)
        stem = path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
        tables[f"t{i}"] = lf          # always accessible as t0, t1, t2
        tables[stem] = lf             # accessible by filename stem
    return tables


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool(
    "Execute an advanced Polars query across ONE or MULTIPLE data sources. "
    "Supports full Polars expression API: filter, group_by, agg, join, sort, "
    "window functions, string/date ops, and cross-file JOIN.\n\n"
    "PARAMETERS:\n"
    "- source_paths: list of file paths (.parquet / .csv / .ndjson). Auto-detected.\n"
    "- expression: Polars expression string. Tables are exposed as:\n"
    "    Single file  → `lf` (LazyFrame)\n"
    "    Multi files  → `t0`, `t1`, `t2`, ... AND by stem name\n"
    "                   e.g. 'orders.parquet' → `orders`\n"
    "                        'customers.csv'  → `customers`\n"
    "- max_rows: max rows returned (default 50)\n\n"
    "SINGLE TABLE EXAMPLES:\n"
    "  `lf.filter(pl.col('sales') > 1000).group_by('region').agg(pl.col('sales').sum())`\n"
    "  `lf.with_columns(pl.col('revenue').rank().over('category').alias('rank'))`\n\n"
    "MULTI-TABLE JOIN EXAMPLES:\n"
    "  Inner join:  `orders.join(customers, on='customer_id', how='inner')`\n"
    "  Left join:   `t0.join(t1, left_on='id', right_on='user_id', how='left')`\n"
    "  Multi-join:  `t0.join(t1, on='id').join(t2, on='category_id')`\n"
    "  Join + agg:  `orders.join(products, on='product_id').group_by('category').agg(pl.col('revenue').sum())`\n\n"
    "NOTE: Expression must return a LazyFrame or DataFrame. Do NOT call .collect()."
)
async def polars_query(
    source_paths: list[str],
    expression: str = "",
    max_rows: int = 500,
) -> str:
    try:
        if not source_paths:
            return "Error: source_paths must contain at least one file path."

        tables = _load_tables(source_paths)

        # Single file: also expose as `lf` for backward compatibility
        exec_globals = {**_POLARS_SAFE_GLOBALS, **tables}
        if len(source_paths) == 1:
            exec_globals["lf"] = next(iter(tables.values()))

        # No expression → schema preview of all tables
        if not expression.strip():
            return _multi_preview(tables, max_rows)

        result = eval(  # noqa: S307
            compile(expression, "<polars_query>", "eval"),
            exec_globals,
            {},
        )

        if isinstance(result, pl.LazyFrame):
            df = result.fetch(max_rows)
            return _format_result(df, source_paths, expression)
        elif isinstance(result, pl.DataFrame):
            return _format_result(result.head(max_rows), source_paths, expression)
        elif isinstance(result, pl.Series):
            return f"Series ({result.name}): {result.to_list()}"
        else:
            return f"Scalar result: {result}"

    except pl.exceptions.PolarsError as e:
        logger.error("Polars error: %s", e)
        return f"Polars Error: {e}\nExpression: {expression}"
    except SyntaxError as e:
        return f"Syntax Error in expression: {e}"
    except Exception as e:
        logger.error("Unexpected: %s\n%s", e, traceback.format_exc())
        return f"Error: {e}"


@tool(
    "Profile one or multiple datasets: null rates, cardinality, numeric stats, skewness. "
    "Call this before querying to understand schema and data quality of all involved files."
)
async def polars_profile(source_paths: list[str]) -> str:
    try:
        if not source_paths:
            return "Error: source_paths is empty."

        sections: list[str] = []
        for path in source_paths:
            df = _scan(path).collect()
            stem = path.replace("\\", "/").split("/")[-1]
            lines = [
                f"── {stem} ({'×'.join(str(x) for x in df.shape)}) ──────────────────────",
            ]
            for col in df.columns:
                series = df[col]
                null_pct = series.null_count() / len(series) * 100
                dtype = series.dtype

                if dtype in (pl.Utf8, pl.String, pl.Categorical):
                    n_unique = series.n_unique()
                    top = series.drop_nulls().value_counts(sort=True).head(3)["value"].to_list()
                    info = f"unique={n_unique:,}  top={top}"
                elif dtype in (pl.Date, pl.Datetime):
                    info = f"min={series.min()}  max={series.max()}"
                else:
                    desc = {d["statistic"]: d[col] for d in df.select(pl.col(col).describe()).to_dicts()}
                    skew = ""
                    mean_v, med_v = desc.get("mean"), desc.get("50%")
                    if mean_v and med_v and med_v != 0 and abs(mean_v - med_v) / abs(med_v) > 0.2:
                        skew = " ⚠ skewed"
                    info = (
                        f"mean={_fmt(mean_v)}  std={_fmt(desc.get('std'))}"
                        f"  min={_fmt(desc.get('min'))}  max={_fmt(desc.get('max'))}{skew}"
                    )

                null_str = f"  null={null_pct:.1f}%" if null_pct > 0 else ""
                lines.append(f"  {col:<28} [{dtype}]{null_str}")
                lines.append(f"    {info}")

            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    except Exception as e:
        return f"Profile error: {e}"


@tool(
    "Inspect joinability between two tables: find common column names and "
    "estimate key overlap (%). Use before writing JOIN expressions."
)
async def polars_inspect_join(path_left: str, path_right: str) -> str:
    """Detect shared columns + key overlap between two files."""
    try:
        lf_l = _scan(path_left)
        lf_r = _scan(path_right)

        schema_l = lf_l.collect_schema()
        schema_r = lf_r.collect_schema()

        cols_l = set(schema_l.names())
        cols_r = set(schema_r.names())
        common = cols_l & cols_r

        if not common:
            return (
                f"No common columns found.\n"
                f"  Left  columns: {sorted(cols_l)}\n"
                f"  Right columns: {sorted(cols_r)}"
            )

        lines = [
            f"Common columns: {sorted(common)}",
            "",
            "── Key overlap analysis ─────────────────────",
        ]

        for col in sorted(common):
            dtype_l = schema_l[col]
            dtype_r = schema_r[col]

            # Sample overlap — fetch small chunk to estimate
            sample_l = lf_l.select(pl.col(col).drop_nulls().unique()).fetch(5000)
            sample_r = lf_r.select(pl.col(col).drop_nulls().unique()).fetch(5000)

            keys_l = set(sample_l[col].to_list())
            keys_r = set(sample_r[col].to_list())
            overlap = len(keys_l & keys_r)
            pct_l = overlap / len(keys_l) * 100 if keys_l else 0
            pct_r = overlap / len(keys_r) * 100 if keys_r else 0

            lines.append(
                f"  {col:<25} dtype=({dtype_l} / {dtype_r})"
                f"  overlap={overlap:,} keys"
                f"  ({pct_l:.0f}% of left, {pct_r:.0f}% of right)"
            )

        stem_l = path_left.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
        stem_r = path_right.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
        if common:
            best = sorted(common)[0]
            lines += [
                "",
                "── Suggested JOIN ───────────────────────────",
                f"  {stem_l}.join({stem_r}, on='{best}', how='inner')",
                f"  {stem_l}.join({stem_r}, on='{best}', how='left')",
            ]

        return "\n".join(lines)

    except Exception as e:
        return f"Inspect join error: {e}"


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
            return f"Unsupported source: {source_path}"

        df.write_parquet(output_path, compression="zstd")
        return (
            f"Converted → {output_path} (zstd)\n"
            f"Rows: {df.shape[0]:,}  Cols: {df.shape[1]}  ~{df.estimated_size('mb'):.1f} MB"
        )
    except Exception as e:
        return f"Conversion failed: {e}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _multi_preview(tables: dict[str, pl.LazyFrame], max_rows: int) -> str:
    seen: set[int] = set()
    lines = ["Schema preview (no expression provided):"]
    for name, lf in tables.items():
        if id(lf) in seen:
            continue
        seen.add(id(lf))
        schema = lf.collect_schema()
        df_head = lf.fetch(min(max_rows, 5))
        lines.append(f"\n  [{name}]  schema={dict(schema)}")
        lines.append(f"  head:\n{df_head}")
    return "\n".join(lines)


def _format_result(df: pl.DataFrame, sources: list[str], expression: str) -> str:
    names = [p.replace("\\", "/").split("/")[-1] for p in sources]
    return "\n".join([
        f"Sources: {', '.join(names)}",
        f"Expression: {expression}",
        f"Result: {df.shape[0]} rows × {df.shape[1]} cols",
        f"Schema: {dict(df.schema)}",
        "─" * 50,
        str(df),
    ])


def _fmt(v: Any) -> str:
    if v is None: return "N/A"
    if isinstance(v, float): return f"{v:,.2f}"
    return str(v)


@tool(
    "Perform high-performance data aggregation using the NATIVE Rust Polars engine. "
    "This is faster than the Python version for large JSON datasets. "
    "Input: data_json (string), group_by (col name), agg_col (col name)."
)
async def native_polars_aggregate(
    data_json: str,
    group_by: str,
    agg_col: str,
) -> str:
    """Execute aggregation in Rust Polars and return JSON results."""
    if not _NATIVE_AVAILABLE:
        return "Error: Native Polars engine (seahorse_ffi) is not available in this build."

    try:
        analyst = seahorse_ffi.PyPolarsAnalyst()
        logger.info("native_polars: executing aggregation on %s grouped by %s", agg_col, group_by)
        return analyst.aggregate_json(data_json, group_by, agg_col)
    except Exception as e:
        logger.error("native_polars: aggregation failed: %s", e)
        return f"Error: Native aggregation failed: {e}"