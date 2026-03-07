"""seahorse_ai.tools.db — Database connector tools for structured querying.

Allows the agent to execute SELECT queries against a local or remote SQL database.
Uses a simplified interface for demonstration; in production, use a read-only 
DB user and proper connection pooling.
"""
from __future__ import annotations

import logging
import os
import sqlite3

import psycopg2
from psycopg2.extras import RealDictCursor

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Default config
_DB_TYPE = os.environ.get("SEAHORSE_DB_TYPE", "sqlite")
_SQLITE_PATH = os.environ.get("SEAHORSE_DB_PATH", "workspace/corporate.db")
_PG_URI = os.environ.get("SEAHORSE_PG_URI", "postgresql://seahorse_user:seahorse_password@localhost:5432/seahorse_enterprise")


@tool(
    "List all tables and their column definitions in the corporate database. "
    "Use this tool FIRST when the user asks about database structure or capabilities."
)
async def database_schema() -> str:
    """Introspect the database schema to find table and column names."""
    try:
        if _DB_TYPE == "postgres":
            conn = psycopg2.connect(_PG_URI)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # Query for tables and columns in the public schema
            query = """
                SELECT table_name, column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """
        else:
            conn = sqlite3.connect(_SQLITE_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # SQLite introspection requires a bit more manual work
            query = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        
        logger.info("database_schema: introspecting %s", _DB_TYPE)
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            return "The database is empty (no tables found)."

        if _DB_TYPE == "postgres":
            # Group by table
            schema_dict: dict[str, list[str]] = {}
            for row in rows:
                t = row["table_name"]
                c = f"{row['column_name']} ({row['data_type']})"
                schema_dict.setdefault(t, []).append(c)
        else:
            # For SQLite, we need to fetch columns for each table
            schema_dict = {}
            for row in rows:
                table_name = row["name"]
                cursor.execute(f"PRAGMA table_info({table_name});")
                cols = cursor.fetchall()
                schema_dict[table_name] = [f"{c['name']} ({c['type']})" for c in cols]

        # Format output
        output = [f"Found {len(schema_dict)} tables in the database:\n"]
        for table, cols in schema_dict.items():
            output.append(f"- **{table}**: {', '.join(cols)}")
        
        conn.close()
        return "\n".join(output)

    except Exception as e:
        logger.error("database_schema error: %s", e)
        return f"Error introspecting schema: {e}"


@tool(
    "Query the corporate SQL database (SQLite or PostgreSQL) for structured data. "
    "Input must be a valid SELECT statement. "
)
async def database_query(query: str) -> str:
    """Execute a read-only SQL query against the corporate database."""
    # ── 1. Basic Security Guard ───────────────────────────────────────────────
    q_lower = query.strip().lower()
    
    # Block destructive commands
    forbidden = ["insert", "update", "delete", "drop", "truncate", "alter", "create", "replace"]
    if any(cmd in q_lower for cmd in forbidden) or not (q_lower.startswith("select") or q_lower.startswith("with")):
        logger.warning("database_query: blocked potentially destructive query: %r", query)
        return "Error: ONLY 'SELECT' or 'WITH' queries are allowed for security reasons."

    # ── 2. Connection & Execution ─────────────────────────────────────────────
    try:
        if _DB_TYPE == "postgres":
            conn = psycopg2.connect(_PG_URI)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            # Ensure workspace directory exists if using default path
            if _SQLITE_PATH == "workspace/corporate.db":
                os.makedirs("workspace", exist_ok=True)
            conn = sqlite3.connect(_SQLITE_PATH)
            conn.row_factory = sqlite3.Row  # Access by column name
            cursor = conn.cursor()
        
        logger.info("database_query: executing %r on %s", query, _DB_TYPE)
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            return "Query executed successfully, but no rows were returned."

        # ── 3. Formatting Results ──────────────────────────────────────────────
        # Convert rows to a list of dicts for pretty printing
        results = [dict(row) for row in rows]
        
        # Limit output size to avoid blowing up context window
        max_rows = 20
        header = (
            f"Found {len(results)} results (showing top {max_rows}):\n" 
            if len(results) > max_rows else ""
        )
        
        import json
        from datetime import date, datetime
        from decimal import Decimal

        class DataEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, (datetime, date)):
                    return obj.isoformat()
                if isinstance(obj, Decimal):
                    return float(obj)
                return super().default(obj)

        formatted = json.dumps(results[:max_rows], indent=2, ensure_ascii=False, cls=DataEncoder)
        
        conn.close()
        return f"{header}{formatted}"

    except (sqlite3.Error, psycopg2.Error) as e:
        logger.error("database_query error: %s", e)
        return f"Database Error: {e}"
    except Exception as e:
        logger.error("database_query unexpected error: %s", e)
        return f"An unexpected error occurred: {e}"


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
