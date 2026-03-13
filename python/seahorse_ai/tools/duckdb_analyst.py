from __future__ import annotations

import logging
import os
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import anyio
import duckdb
import polars as pl

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# ── Connection Pool ───────────────────────────────────────────────────────────
_POOL_SIZE = 4          # concurrent DuckDB connections
_QUERY_TIMEOUT = 30.0   # seconds
_MAX_ROWS = int(os.environ.get("SEAHORSE_MAX_DB_ROWS", "50000"))


class _DuckDBPool:
    """
    Simple pool of DuckDB connections using AnyIO memory streams.
    """

    def __init__(self, size: int = _POOL_SIZE) -> None:
        self._size = size
        self._conns: list[duckdb.DuckDBPyConnection] = [
            self._make_conn() for _ in range(size)
        ]
        # send_stream, receive_stream
        self._send, self._recv = anyio.create_memory_object_stream(size)
        for conn in self._conns:
            self._send.send_nowait(conn)

    @staticmethod
    def _make_conn() -> duckdb.DuckDBPyConnection:
        conn = duckdb.connect(database=":memory:")
        conn.execute("SET threads = 4")
        conn.execute("SET memory_limit = '1GB'")
        conn.execute("SET enable_progress_bar = false")
        conn.execute("SET enable_object_cache = true")
        return conn

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[duckdb.DuckDBPyConnection]:
        conn = await self._recv.receive()
        try:
            yield conn
        finally:
            try:
                # DuckDB doesn't have a formal rollback if no txn, but this is a safety reset
                conn.execute("ROLLBACK")
            except Exception:
                logger.warning("DuckDB connection broken, replacing.")
                with suppress(Exception):
                    conn.close()
                conn = self._make_conn()
            await self._send.send(conn)

    def close_all(self) -> None:
        for conn in self._conns:
            with suppress(Exception):
                conn.close()


# Module-level singleton — created once on import
_pool = _DuckDBPool(size=_POOL_SIZE)


# ── Core executor ─────────────────────────────────────────────────────────────

async def _execute(
    sql: str,
    max_rows: int = _MAX_ROWS,
    timeout: float = _QUERY_TIMEOUT,
) -> pl.DataFrame:
    """
    Acquire a connection, run SQL with timeout, return Polars DataFrame.
    Zero-copy via Apache Arrow (DuckDB → Arrow → Polars).
    """

    async def _run() -> pl.DataFrame:
        async with _pool.acquire() as conn:
            # anyio.to_thread.run_sync instead of loop.run_in_executor
            arrow_result = await anyio.to_thread.run_sync(
                lambda: conn.execute(sql).fetch_arrow_table()
            )
            df = pl.from_arrow(arrow_result)
            if len(df) > max_rows:
                logger.warning("Result truncated: %d → %d rows", len(df), max_rows)
                df = df.head(max_rows)
            return df

    with anyio.fail_after(timeout):
        return await _run()


# ── Formatter ─────────────────────────────────────────────────────────────────

def _format(
    df: pl.DataFrame,
    sql: str,
    elapsed_ms: float,
    truncated: bool = False,
) -> str:
    trunc_note = f"  ⚠ truncated to {_MAX_ROWS:,} rows" if truncated else ""
    return "\n".join([
        f"Query   : {sql[:120]}{'...' if len(sql) > 120 else ''}",
        f"Result  : {df.shape[0]:,} rows × {df.shape[1]} cols{trunc_note}",
        f"Schema  : {dict(df.schema)}",
        f"Elapsed : {elapsed_ms:.1f} ms",
        "─" * 60,
        str(df),
    ])


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool(
    "Execute high-performance SQL on local files (Parquet, CSV, JSON) or in-memory "
    "data using DuckDB. Supports complex JOINs, window functions, CTEs, and full "
    "SQL syntax. Results returned via zero-copy Arrow → Polars pipeline.\n\n"
    "FILE QUERY EXAMPLES:\n"
    "  Parquet : SELECT * FROM 'data.parquet' WHERE sales > 1000\n"
    "  CSV     : SELECT region, SUM(revenue) FROM read_csv('sales.csv') GROUP BY 1\n"
    "  JSON    : SELECT * FROM read_json_auto('events.json') LIMIT 100\n"
    "  Glob    : SELECT * FROM 'logs/*.parquet' WHERE ts > '2024-01-01'\n\n"
    "ADVANCED EXAMPLES:\n"
    "  CTE     : WITH ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY region ORDER BY sales DESC) rn FROM t) SELECT * FROM ranked WHERE rn = 1\n"
    "  JOIN    : SELECT o.*, c.name FROM 'orders.parquet' o JOIN 'customers.parquet' c ON o.customer_id = c.id\n"
    "  Window  : SELECT *, AVG(revenue) OVER (PARTITION BY category ORDER BY date ROWS 6 PRECEDING) AS ma7 FROM sales\n\n"
    f"NOTE: Results capped at {_MAX_ROWS:,} rows. Use aggregation for large datasets."
)
async def duckdb_sql(
    sql_query: str,
    max_rows: int = 2000,
) -> str:
    """Run SQL via DuckDB with connection pooling, timeout, and Arrow zero-copy."""
    t0 = time.perf_counter()
    # Ensure max_rows is an integer
    try:
        max_rows = int(max_rows)
    except (ValueError, TypeError):
        max_rows = 2000

    try:
        limit = min(max_rows, _MAX_ROWS)
        df = await _execute(sql_query, max_rows=limit)
        elapsed = (time.perf_counter() - t0) * 1000
        truncated = len(df) >= limit
        return _format(df, sql_query, elapsed, truncated)

    except TimeoutError:
        return f"Timeout: query exceeded {_QUERY_TIMEOUT}s. Add WHERE/LIMIT or aggregate first."
    except duckdb.CatalogException as e:
        return f"File not found or unreadable: {e}"
    except duckdb.ParserException as e:
        return f"SQL syntax error: {e}"
    except duckdb.BinderException as e:
        return f"Column/table reference error: {e}"
    except Exception as e:
        logger.error("duckdb_sql failed:\n%s", traceback.format_exc())
        return f"Error: {e}"


@tool(
    "Run SQL via DuckDB then hand the result to Polars for advanced post-processing "
    "(window functions, string ops, ML feature engineering, etc.).\n\n"
    "Returns both a Polars-ready summary AND the Polars expression hint for the next step.\n\n"
    "WORKFLOW:\n"
    "  1. Use SQL for heavy aggregation / JOIN across files\n"
    "  2. Use polars_query with the result path for complex transformations\n\n"
    "EXAMPLE:\n"
    "  sql   : SELECT customer_id, SUM(revenue) total FROM 'orders.parquet' GROUP BY 1\n"
    "  Then  : polars_query with expression on the aggregated data"
)
async def sql_to_polars(
    sql_query: str,
    output_parquet_path: str = "",
    max_rows: int = _MAX_ROWS,
) -> str:
    """
    SQL → Polars bridge.
    Optionally persists result to Parquet for follow-up polars_query calls.
    """
    t0 = time.perf_counter()
    try:
        df = await _execute(sql_query, max_rows=max_rows)
        elapsed = (time.perf_counter() - t0) * 1000

        output_note = ""
        if output_parquet_path:
            df.write_parquet(output_parquet_path, compression="zstd")
            output_note = f"\nSaved → {output_parquet_path} (use with polars_query)"

        return "\n".join([
            f"SQL → Polars transfer complete in {elapsed:.1f} ms",
            f"Shape  : {df.shape[0]:,} rows × {df.shape[1]} cols",
            f"Schema : {dict(df.schema)}",
            f"Preview:\n{df.head(5)}",
            output_note,
            "",
            "── Next step hint ───────────────────────────────",
            f"polars_query(source_paths=['{output_parquet_path or '<in-memory>'}'], "
            f"expression='lf.filter(...).group_by(...).agg(...)')",
        ])

    except TimeoutError:
        return f"Timeout: query exceeded {_QUERY_TIMEOUT}s."
    except Exception as e:
        logger.error("sql_to_polars failed:\n%s", traceback.format_exc())
        return f"Error: {e}"