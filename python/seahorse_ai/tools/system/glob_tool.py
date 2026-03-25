"""Glob tool - find files matching glob patterns in the workspace.

Essential for discovering files by type or pattern. Supports recursive
patterns like **/*.py to find all Python files.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path

from seahorse_ai.tools.base import tool

from .filesystem import _resolve_safe

logger = logging.getLogger(__name__)


@tool("Find files matching a glob pattern in workspace")
async def glob_files(pattern: str, path: str = ".", max_results: int = 100) -> str:
    """Find files matching a glob pattern.

    Essential for discovering files by type or name pattern. Supports
    recursive patterns (**) and wildcards (*, ?).

    Args:
        pattern: Glob pattern (e.g., "**/*.py", "*.rs", "test_*.py")
        path: Base directory to search (default: workspace root)
        max_results: Maximum number of results to return (default: 100)

    Returns:
        List of matching files with count

    Examples:
        >>> await glob_files("**/*.py")
        'Found 42 file(s):\\n  src/main.py\\n  src/utils.py\\n  ...'

        >>> await glob_files("Cargo.toml")
        'Found 1 file(s):\\n  Cargo.toml'

        >>> await glob_files("**/*_test.rs")
        'Found 15 file(s):\\n  crates/core/test.rs\\n  ...'
    """
    if not pattern:
        return "Error: pattern cannot be empty"

    try:
        base_path = _resolve_safe(path)

        if not base_path.exists():
            return f"Directory does not exist: {path}"

        if base_path.is_file():
            return f"'{path}' is a file, not a directory. Use glob_files on a directory."

        matches = []

        # Determine if pattern is recursive (contains **)
        is_recursive = "**" in pattern or "/" in pattern

        if is_recursive:
            # Use rglob for recursive search
            for file_path in base_path.rglob("*"):
                if file_path.is_file():
                    try:
                        rel_path = file_path.relative_to(base_path)
                        # Match against the pattern
                        if fnmatch.fnmatch(str(rel_path), pattern) or fnmatch.fnmatch(
                            file_path.name, pattern
                        ):
                            matches.append(str(rel_path))
                    except ValueError:
                        # Paths on different drives on Windows
                        continue
        else:
            # Non-recursive: only search in the specified directory
            for file_path in base_path.glob(pattern):
                if file_path.is_file():
                    try:
                        rel_path = file_path.relative_to(base_path)
                        matches.append(str(rel_path))
                    except ValueError:
                        continue

        if not matches:
            return f"No files found matching pattern '{pattern}' in '{path}'"

        # Sort matches for consistent output
        matches.sort()

        # Limit results
        if len(matches) > max_results:
            truncated = len(matches) - max_results
            matches = matches[:max_results]
            truncated_msg = f"\n... and {truncated} more file(s) (use max_results to see more)"
        else:
            truncated_msg = ""

        logger.info("glob_files: pattern=%r path=%r matches=%d", pattern, path, len(matches))

        return f"Found {len(matches)} file(s):\n" + "\n".join(f"  {m}" for m in matches) + truncated_msg

    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("glob_files error: %s", exc)
        return f"Error: {exc}"


@tool("Find directories matching a glob pattern")
async def glob_dirs(pattern: str, path: str = ".", max_results: int = 50) -> str:
    """Find directories matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., "test*", "src/*/")
        path: Base directory to search (default: workspace root)
        max_results: Maximum number of results to return (default: 50)

    Returns:
        List of matching directories

    Examples:
        >>> await glob_dirs("src*")
        'Found 3 dir(s):\\n  src\\n  src-cli\\n  src-core'
    """
    if not pattern:
        return "Error: pattern cannot be empty"

    try:
        base_path = _resolve_safe(path)

        if not base_path.exists():
            return f"Directory does not exist: {path}"

        if base_path.is_file():
            return f"'{path}' is a file, not a directory"

        matches = []

        # Clean pattern (remove trailing slashes)
        clean_pattern = pattern.rstrip("/")

        # Search for directories
        is_recursive = "**" in clean_pattern or "/" in clean_pattern

        if is_recursive:
            for dir_path in base_path.rglob("*"):
                if dir_path.is_dir():
                    try:
                        rel_path = dir_path.relative_to(base_path)
                        if fnmatch.fnmatch(str(rel_path), clean_pattern) or fnmatch.fnmatch(
                            dir_path.name, clean_pattern
                        ):
                            matches.append(str(rel_path))
                    except ValueError:
                        continue
        else:
            for dir_path in base_path.glob(clean_pattern):
                if dir_path.is_dir():
                    try:
                        rel_path = dir_path.relative_to(base_path)
                        matches.append(str(rel_path))
                    except ValueError:
                        continue

        if not matches:
            return f"No directories found matching pattern '{pattern}' in '{path}'"

        matches.sort()

        if len(matches) > max_results:
            truncated = len(matches) - max_results
            matches = matches[:max_results]
            truncated_msg = f"\n... and {truncated} more"
        else:
            truncated_msg = ""

        logger.info("glob_dirs: pattern=%r path=%r matches=%d", pattern, path, len(matches))

        return f"Found {len(matches)} dir(s):\n" + "\n".join(f"  {m}/" for m in matches) + truncated_msg

    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("glob_dirs error: %s", exc)
        return f"Error: {exc}"


@tool("Count files by extension/type in the workspace")
async def count_files_by_type(path: str = ".", recursive: bool = True) -> str:
    """Count files grouped by their extension.

    Useful for understanding project composition and identifying
    which languages/file types are present.

    Args:
        path: Directory to analyze (default: workspace root)
        recursive: Whether to search recursively (default: True)

    Returns:
        Count of files by extension, sorted by frequency

    Examples:
        >>> await count_files_by_type(".")
        'File type summary:\\n  .py: 42 files\\n  .rs: 15 files\\n  .toml: 3 files'
    """
    try:
        base_path = _resolve_safe(path)

        if not base_path.exists():
            return f"Directory does not exist: {path}"

        if base_path.is_file():
            return f"'{path}' is a file. Use a directory path."

        from collections import Counter

        extensions = []

        if recursive:
            all_files = base_path.rglob("*")
        else:
            all_files = base_path.glob("*")

        for item in all_files:
            if item.is_file():
                # Get extension (including the dot)
                ext = item.suffix.lower()
                if not ext:
                    ext = "(no extension)"
                extensions.append(ext)

        if not extensions:
            return f"No files found in '{path}'"

        # Count and sort
        counter = Counter(extensions)
        total = sum(counter.values())

        lines = [f"File type summary for '{path}' ({total} files total):"]
        for ext, count in counter.most_common(20):
            percentage = (count / total) * 100
            lines.append(f"  {ext}: {count} files ({percentage:.1f}%)")

        if len(counter) > 20:
            lines.append(f"  ... and {len(counter) - 20} more file types")

        logger.info("count_files_by_type: path=%r total=%d types=%d", path, total, len(counter))

        return "\n".join(lines)

    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("count_files_by_type error: %s", exc)
        return f"Error: {exc}"
