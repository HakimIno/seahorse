from __future__ import annotations

import logging
import os
import re

import polars as pl
import aiosqlite
import asyncpg
from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# ── Regex for safe SQL identifiers ────────────────────────────────────────────
_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _get_db_config() -> tuple[str, str, str | None]:
    """Read DB config at call-time so runtime env changes are picked up."""
    db_type = os.environ.get("SEAHORSE_DB_TYPE", "sqlite")
    sqlite_path = os.environ.get("SEAHORSE_DB_PATH", "workspace/corporate.db")
    pg_uri = os.environ.get("SEAHORSE_PG_URI")
    return db_type, sqlite_path, pg_uri


def _validate_table_name(name: str) -> str | None:
    """Return an error string if the table name is unsafe, else None."""
    if not name or not _SAFE_IDENT.match(name):
        return (
            f"[FAIL] Invalid table name '{name}'. "
            "Only letters, digits, and underscores are allowed (must start with a letter or underscore)."
        )
    return None


@tool(
    "Extract data from a SQL database table and save it to a Parquet file for high-performance analysis. "
    "Input: table_name, output_path (e.g., 'workspace/sales.parquet')."
)
async def extract_sql_to_parquet(table_name: str, output_path: str) -> str:
    """ETL: Extract from SQL -> Parquet."""
    from seahorse_ai.tools.data.polars_analyst import _resolve_path
    output_path = _resolve_path(output_path)

    # ── Security: Validate table name ─────────────────────────────────────
    err = _validate_table_name(table_name)
    if err:
        return err

    try:
        db_type, sqlite_path, pg_uri = _get_db_config()

        # Guard empty dirname (e.g. output_path="sales.parquet")
        dirname = os.path.dirname(output_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        if db_type == "postgres":
            if not pg_uri:
                return "[FAIL] SEAHORSE_PG_URI not set."
            conn = await asyncpg.connect(pg_uri)
            try:
                rows = await conn.fetch(f"SELECT * FROM {table_name}")  # noqa: S608 — validated above
                if not rows:
                    return f"[INFO] Table {table_name} is empty."
                df = pl.from_dicts([dict(r) for r in rows])
            finally:
                await conn.close()
        else:
            if not os.path.exists(sqlite_path):
                return f"[FAIL] SQLite database not found at {sqlite_path}"
            async with aiosqlite.connect(sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(f"SELECT * FROM {table_name}") as cursor:  # noqa: S608
                    rows = await cursor.fetchall()
                    if not rows:
                        return f"[INFO] Table {table_name} is empty."
                    df = pl.from_dicts([dict(r) for r in rows])

        df.write_parquet(output_path, compression="zstd")
        return (
            f"[SUCCESS] Extraction: {table_name} -> {output_path}\n"
            f"Rows: {df.shape[0]:,} | Columns: {df.shape[1]}"
        )

    except Exception as e:
        logger.error("extract_sql_to_parquet failed: %s", e)
        return f"[FAIL] Extraction Error: {e}"


@tool(
    "Load data from a Parquet or CSV file into a SQL database table. "
    "Input: source_path, table_name, if_exists ('append', 'replace', 'fail')."
)
async def load_to_sql(source_path: str, table_name: str, if_exists: str = "append") -> str:
    """ETL: Load from File -> SQL."""
    from seahorse_ai.tools.data.polars_analyst import _resolve_path
    source_path = _resolve_path(source_path)

    # ── Security: Validate table name ─────────────────────────────────────
    err = _validate_table_name(table_name)
    if err:
        return err

    try:
        db_type, sqlite_path, pg_uri = _get_db_config()

        # Read source
        if source_path.endswith(".parquet"):
            df = pl.read_parquet(source_path)
        elif source_path.endswith(".csv"):
            df = pl.read_csv(source_path, try_parse_dates=True)
        else:
            return f"[FAIL] Unsupported source format: {source_path}"

        if df.is_empty():
            return "[FAIL] Source file is empty."

        records = df.to_dicts()
        cols = df.columns

        # Validate all column names too
        for c in cols:
            if not _SAFE_IDENT.match(c):
                return f"[FAIL] Unsafe column name '{c}'. Clean the data first."

        if db_type == "postgres":
            if not pg_uri:
                return "[FAIL] SEAHORSE_PG_URI not set."
            conn = await asyncpg.connect(pg_uri)
            try:
                if if_exists == "replace":
                    await conn.execute(f"DROP TABLE IF EXISTS {table_name}")  # noqa: S608

                column_names = ", ".join(cols)
                placeholder = ", ".join([f"${i+1}" for i in range(len(cols))])
                query = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholder})"  # noqa: S608

                await conn.executemany(query, [tuple(r.values()) for r in records])
            finally:
                await conn.close()
        else:
            async with aiosqlite.connect(sqlite_path) as db:
                if if_exists == "replace":
                    await db.execute(f"DROP TABLE IF EXISTS {table_name}")  # noqa: S608

                column_names = ", ".join(cols)
                placeholders = ", ".join(["?" for _ in cols])

                # Schema inference (simplified)
                create_cols = []
                for c in cols:
                    dt = df[c].dtype
                    sql_type = "REAL" if dt.is_numeric() else "TEXT"
                    create_cols.append(f"{c} {sql_type}")

                create_query = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(create_cols)})"  # noqa: S608
                await db.execute(create_query)

                query = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"  # noqa: S608
                await db.executemany(query, [tuple(r.values()) for r in records])
                await db.commit()

        return f"[SUCCESS] Load: {source_path} -> {table_name} ({len(records)} rows)"

    except Exception as e:
        logger.error("load_to_sql failed: %s", e)
        return f"[FAIL] Loading Error: {e}"
