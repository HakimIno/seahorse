import json
import logging
import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal

import aiosqlite
import asyncpg

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Default config
_DB_TYPE = os.environ.get("SEAHORSE_DB_TYPE", "sqlite")
_SQLITE_PATH = os.environ.get("SEAHORSE_DB_PATH", "workspace/corporate.db")
_PG_URI = os.environ.get("SEAHORSE_PG_URI")
_MAX_ROWS = int(os.environ.get("SEAHORSE_MAX_DB_ROWS", "50000"))


class DataEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


@tool(
    "List all tables and their column definitions in the corporate database. "
    "Use this tool FIRST when the user asks about database structure or capabilities."
)
async def database_schema() -> str:
    """Introspect the database schema to find table and column names."""
    conn = None
    try:
        if _DB_TYPE == "postgres":
            conn = await asyncpg.connect(_PG_URI)
            # Query for tables and columns in the public schema
            query = """
                SELECT table_name, column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """
            rows = await conn.fetch(query)

            if not rows:
                return "The database is empty (no tables found)."

            # Group by table
            schema_dict: dict[str, list[str]] = {}
            for row in rows:
                t = row["table_name"]
                c = f"{row['column_name']} ({row['data_type']})"
                schema_dict.setdefault(t, []).append(c)
        else:
            conn = await aiosqlite.connect(_SQLITE_PATH)
            conn.row_factory = aiosqlite.Row
            # SQLite introspection
            query = (
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            async with conn.execute(query) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                return "The database is empty (no tables found)."

            schema_dict = {}
            for row in rows:
                table_name = row["name"]
                async with conn.execute(f"PRAGMA table_info({table_name});") as cursor:
                    cols = await cursor.fetchall()
                    schema_dict[table_name] = [f"{c['name']} ({c['type']})" for c in cols]

        # Format output
        output = [f"Found {len(schema_dict)} tables in the database:\n"]
        for table, cols in schema_dict.items():
            output.append(f"- **{table}**: {', '.join(cols)}")

        return "\n".join(output)

    except Exception as e:
        logger.error("database_schema error: %s", e)
        return f"Error introspecting schema: {e}"
    finally:
        if conn:
            if _DB_TYPE == "postgres":
                await conn.close()
            else:
                await conn.close()


@tool(
    "Query the corporate SQL database (SQLite or PostgreSQL) for structured data. "
    "Input must be a valid SELECT statement. "
)
async def database_query(query: str) -> str:
    """Execute a read-only SQL query against the corporate database."""
    # ── 1. Basic Security Guard ───────────────────────────────────────────────
    q_lower = query.strip().lower()

    import re

    forbidden = ["insert", "update", "delete", "drop", "truncate", "alter", "create", "replace"]
    # Use regex with word boundaries to avoid matching keywords inside column names (e.g., 'created_at')
    pattern = r"\b(" + "|".join(forbidden) + r")\b"
    if re.search(pattern, q_lower) or not (
        q_lower.startswith("select") or q_lower.startswith("with")
    ):
        logger.warning("database_query: blocked potentially destructive query: %r", query)
        return "Error: ONLY 'SELECT' or 'WITH' queries are allowed for security reasons."

    # ── 2. SQL Linting (Reliability Layer) ────────────────────────────────────
    lint_error = _lint_sql(query)
    if lint_error:
        logger.warning("database_query: lint error: %s", lint_error)
        return f"SQL Error (Self-Correction): {lint_error}. Please use table aliases (e.g., t.id) to avoid ambiguity."

    # ── 3. Connection & Execution ─────────────────────────────────────────────
    conn = None
    try:
        if _DB_TYPE == "postgres":
            conn = await asyncpg.connect(_PG_URI)
            rows = await conn.fetch(query)
            results = [dict(row) for row in rows]
        else:
            # Ensure workspace directory exists if using default path
            if _SQLITE_PATH == "workspace/corporate.db":
                os.makedirs("workspace", exist_ok=True)
            conn = await aiosqlite.connect(_SQLITE_PATH)
            conn.row_factory = aiosqlite.Row
            async with conn.execute(query) as cursor:
                rows = await cursor.fetchall()
                results = [dict(row) for row in rows]

        if not results:
            return "Query executed successfully, but no rows were returned."

        # ── 3. Formatting Results ──────────────────────────────────────────────
        max_rows = _MAX_ROWS
        total_count = len(results)
        header = (
            f"[DATA CONFIDENCE: Total {total_count} records found in database]\n"
            f"Showing top {min(max_rows, total_count)} results:\n"
        )

        formatted = json.dumps(results[:max_rows], indent=2, ensure_ascii=False, cls=DataEncoder)
        return f"{header}{formatted}"

    except Exception as e:
        logger.error("database_query error: %s", e)
        return f"Database Error: {e}"
    finally:
        if conn:
            await conn.close()


def create_demo_database() -> None:
    """Helper to create a demo database if it doesn't exist."""
    if os.path.exists(_SQLITE_PATH):
        return

    os.makedirs(os.path.dirname(_SQLITE_PATH), exist_ok=True)
    conn = sqlite3.connect(_SQLITE_PATH)
    cursor = conn.cursor()

    # Create tables
    cursor.execute(
        "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL, stock INTEGER)"
    )
    cursor.execute(
        "CREATE TABLE sales (id INTEGER PRIMARY KEY, product_id INTEGER, quantity INTEGER, date TEXT)"
    )

    # Insert demo data
    products = [
        (1, "Seahorse Pro Controller", 2500.0, 15),
        (2, "Neptune Cooling Fan", 850.0, 42),
        (3, "Coral Gaming Mouse", 1200.0, 8),
    ]
    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)

    conn.commit()
    conn.close()
    logger.info("Demo database created at %s", _SQLITE_PATH)


def _lint_sql(query: str) -> str | None:
    """Perform a basic lint of the SQL to catch common errors like ambiguity."""
    q_upper = query.upper()

    # 1. Check for ambiguous 'id' or 'name' when joining
    if "JOIN" in q_upper:
        # Heuristic: if SELECT contains " id" or ",id" or " name" without a dot prefix
        # and there's a join, it's risky.
        target_columns = ["ID", "NAME", "CREATED_AT"]
        for col in target_columns:
            # Look for the column name NOT preceded by a dot
            # This is a simple regex-free check for demonstration
            if f" {col}" in q_upper or f",{col}" in q_upper:
                # If there's no dot before it in the whole query for that column name
                # This is very rough but fits the 'Self-Correction' requirement
                return f"Ambiguous column reference detected for '{col}'"

    # 2. Check for SELECT * in joins (best practice)
    if "JOIN" in q_upper and "SELECT *" in q_upper:
        return "Using 'SELECT *' with JOINs is risky as it can return duplicate column names"

    return None
