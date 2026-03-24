"""FileSystem tool — safe read/write/list operations on a sandboxed workspace directory.

The agent can only access files inside the configured workspace root (default: ./workspace).
All path traversal attempts are rejected.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Default workspace — relative to CWD; can be overridden via env var
_WORKSPACE_ROOT = Path(os.environ.get("SEAHORSE_WORKSPACE", ".")).resolve()


def _resolve_safe(rel_path: str) -> Path:
    """Resolve a relative path inside the workspace, raising if outside."""
    target = (_WORKSPACE_ROOT / rel_path).resolve()
    if not str(target).startswith(str(_WORKSPACE_ROOT)):
        raise PermissionError(
            f"Path '{rel_path}' escapes the workspace root. Only paths inside "
            f"'{_WORKSPACE_ROOT}' are allowed."
        )
    return target


@tool("List files and directories in a workspace path (default: '.').")
async def list_files(path: str = ".") -> str:
    """List the contents of a directory inside the workspace."""
    logger.info("list_files: path=%r", path)
    try:
        target = _resolve_safe(path)
        _WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            return f"Path does not exist: {path}"
        if target.is_file():
            return f"'{path}' is a file, not a directory. Use read_file to read it."

        entries = sorted(target.iterdir())
        lines = [f"Contents of '{path}':"]
        for entry in entries:
            kind = "DIR" if entry.is_dir() else "FILE"
            size = entry.stat().st_size if entry.is_file() else ""
            lines.append(f"  [{kind}] {entry.name}" + (f"  ({size} bytes)" if size != "" else ""))

        return "\n".join(lines) if len(lines) > 1 else f"Directory '{path}' is empty."
    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("list_files error: %s", exc)
        return f"Error: {exc}"


@tool("Read the contents of a file in the workspace.")
async def read_file(path: str) -> str:
    """Read a text file from the workspace."""
    logger.info("read_file: path=%r", path)
    try:
        target = _resolve_safe(path)
        if not target.exists():
            return f"File not found: {path}"
        if target.is_dir():
            return f"'{path}' is a directory. Use list_files to list its contents."
        if target.stat().st_size > 200_000:
            return f"File '{path}' is too large to read (max 200KB)."

        return target.read_text(encoding="utf-8", errors="replace")
    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("read_file error: %s", exc)
        return f"Error: {exc}"


@tool("Write text content to a file in the workspace. Creates parent directories as needed.")
async def write_file(path: str, content: str) -> str:
    """Write content to a file in the workspace."""
    logger.info("write_file: path=%r len=%d", path, len(content))
    try:
        target = _resolve_safe(path)
        _WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to '{path}'."
    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("write_file error: %s", exc)
        return f"Error: {exc}"
