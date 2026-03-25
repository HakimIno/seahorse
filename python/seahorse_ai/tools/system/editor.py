"""Editor tool - exact string replacement in files with automatic backup.

This is the most critical tool for code editing, as it allows precise
changes without rewriting entire files. Used for 80% of code changes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from seahorse_ai.tools.base import ToolInputError, tool

from .filesystem import _resolve_safe

logger = logging.getLogger(__name__)


@tool("Perform exact string replacement in a file", risk_level="medium")
async def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> str:
    """Replace exact string matches in a file.

    Creates automatic backup before editing. This is the preferred way
    to make code changes - more precise than rewriting entire files.

    Args:
        path: File path relative to workspace root
        old_text: Exact string to search for (must match exactly)
        new_text: Replacement string
        replace_all: If True, replace all occurrences; if False, only first

    Returns:
        Success message with count of replacements and backup location

    Examples:
        >>> await edit_file("main.py", "def hello():", "async def hello():")
        'Successfully replaced 1 occurrence(s) in main.py. Backup: main.py.bak'

        >>> await edit_file("config.py", "localhost", "127.0.0.1", replace_all=True)
        'Successfully replaced 3 occurrence(s) in config.py. Backup: config.py.bak'
    """
    if not old_text:
        return "Error: old_text cannot be empty"

    if old_text == new_text:
        return "Error: old_text and new_text are the same (no change needed)"

    try:
        target = _resolve_safe(path)

        if not target.exists():
            return f"File not found: {path}"

        if target.is_dir():
            return f"Error: '{path}' is a directory, not a file"

        # Read current content
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except UnicodeDecodeError:
            return f"Error: '{path}' appears to be a binary file. Cannot edit."

        # Check if old_text exists
        if old_text not in content:
            # Provide helpful context for debugging
            lines = content.splitlines()
            if len(lines) > 0:
                preview = "\n".join(lines[:3])
                return (
                    f"Error: '{old_text[:50]}...' not found in file '{path}'.\n"
                    f"File preview (first 3 lines):\n{preview}"
                )
            return f"Error: '{old_text[:50]}...' not found in file '{path}'"

        # Perform replacement
        if replace_all:
            new_content = content.replace(old_text, new_text)
            count = content.count(old_text)
        else:
            # Only replace first occurrence
            new_content = content.replace(old_text, new_text, 1)
            count = 1

        # Create backup before modifying
        backup_path = target.with_suffix(target.suffix + ".bak")
        try:
            backup_path.write_text(content, encoding="utf-8")
            logger.info("Created backup: %s", backup_path)
        except Exception as e:
            logger.warning("Failed to create backup: %s", e)
            # Continue anyway - backup is best-effort

        # Write modified content
        try:
            target.write_text(new_content, encoding="utf-8")
        except Exception as e:
            # Restore backup on failure
            if backup_path.exists():
                target.write_text(content, encoding="utf-8")
            return f"Error: Failed to write file. Changes rolled back. {e}"

        logger.info(
            "edit_file: path=%r old_text_len=%d new_text_len=%d replace_all=%s count=%d",
            path,
            len(old_text),
            len(new_text),
            replace_all,
            count,
        )

        return f"Successfully replaced {count} occurrence(s) in '{path}'. Backup created: '{backup_path.name}'"

    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("edit_file error: %s", exc)
        return f"Error: {exc}"


@tool("Show the edit history / backup files for a given file", risk_level="low")
async def list_backups(path: str = ".") -> str:
    """List all .bak backup files in the workspace.

    Args:
        path: Directory to search for backups (default: workspace root)

    Returns:
        List of backup files with sizes and ages
    """
    try:
        base_path = _resolve_safe(path)

        if not base_path.exists():
            return f"Path does not exist: {path}"

        if base_path.is_file():
            return f"'{path}' is a file. Use list_backups without arguments or specify a directory."

        if not base_path.is_dir():
            return f"Error: '{path}' is not a directory"

        import time

        backups = []
        for backup_file in base_path.rglob("*.bak"):
            if backup_file.is_file():
                stat = backup_file.stat()
                age_hours = (time.time() - stat.st_mtime) / 3600
                backups.append(
                    {
                        "path": str(backup_file.relative_to(_resolve_safe("."))),
                        "size": stat.st_size,
                        "age": f"{age_hours:.1f}h ago" if age_hours < 24 else f"{age_hours/24:.1f}d ago",
                    }
                )

        if not backups:
            return f"No backup files found in '{path}'"

        # Sort by age (newest first)
        backups.sort(key=lambda x: x["age"], reverse=True)

        lines = [f"Found {len(backups)} backup file(s):"]
        for backup in backups[:50]:  # Limit to 50 most recent
            lines.append(f"  {backup['path']}  ({backup['size']} bytes, {backup['age']})")

        if len(backups) > 50:
            lines.append(f"  ... and {len(backups) - 50} more")

        return "\n".join(lines)

    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("list_backups error: %s", exc)
        return f"Error: {exc}"


@tool("Restore a file from its backup", risk_level="medium")
async def restore_backup(backup_path: str) -> str:
    """Restore a file from its .bak backup.

    Args:
        backup_path: Path to the .bak file (e.g., "main.py.bak")

    Returns:
        Success message or error

    Examples:
        >>> await restore_backup("main.py.bak")
        "Restored 'main.py' from 'main.py.bak'"
    """
    try:
        backup = _resolve_safe(backup_path)

        if not backup.exists():
            return f"Backup file not found: {backup_path}"

        if not backup.suffix == ".bak":
            return f"Error: '{backup_path}' is not a .bak file"

        # Determine original file path (remove .bak suffix)
        original_path = backup.with_suffix("")

        # Read backup content
        backup_content = backup.read_text(encoding="utf-8", errors="replace")

        # If original exists, create a backup of it first
        if original_path.exists():
            safety_backup = original_path.with_suffix(original_path.suffix + ".pre-restore.bak")
            safety_backup.write_text(original_path.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info("Created pre-restore safety backup: %s", safety_backup)

        # Write restored content
        original_path.write_text(backup_content, encoding="utf-8")

        logger.info("Restored '%s' from '%s'", original_path.name, backup_path)
        return f"Restored '{original_path.name}' from '{backup_path}'"

    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("restore_backup error: %s", exc)
        return f"Error: {exc}"
