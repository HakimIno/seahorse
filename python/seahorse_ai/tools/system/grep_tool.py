"""Grep tool - search file contents using regex patterns.

Essential for codebase-wide content search. Find functions, classes,
variables, or any text pattern across all files.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from seahorse_ai.tools.base import ToolInputError, tool

from .filesystem import _resolve_safe

logger = logging.getLogger(__name__)

# File extensions to skip as binary/non-text
BINARY_EXTENSIONS = {
    ".pyc",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".dat",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
}


@tool("Search file contents using regex pattern")
async def grep_files(
    pattern: str,
    path: str = ".",
    case_insensitive: bool = False,
    context_lines: int = 0,
    file_pattern: str = None,
    max_results: int = 500,
) -> str:
    """Search for regex pattern in files.

    Essential for finding functions, classes, variables, or any text
    pattern across the entire codebase.

    Args:
        pattern: Regular expression pattern to search for
        path: Directory to search (default: workspace root)
        case_insensitive: If True, ignore case when matching
        context_lines: Number of context lines to show before/after match
        file_pattern: Optional glob pattern to filter files (e.g., "*.py")
        max_results: Maximum number of matches to return (default: 500)

    Returns:
        List of matches with file paths, line numbers, and content

    Examples:
        >>> await grep_files("def process_*")
        'Found matches:\\n  src/main.py:42: def process_data():\\n  src/utils.py:15: def process_file():'

        >>> await grep_files("TODO|FIXME", case_insensitive=True)
        'Found matches:\\n  src/main.py:10: # TODO: refactor this\\n  ...'

        >>> await grep_files("class.*Agent", file_pattern="*.py")
        'Found matches:\\n  agent.py:5: class AgentManager:\\n  ...'
    """
    if not pattern:
        return "Error: pattern cannot be empty"

    try:
        # Compile regex for validation
        try:
            flags = re.IGNORECASE if case_insensitive else 0
            regex = re.compile(pattern, flags)
        except re.error as e:
            raise ToolInputError(f"Invalid regex pattern: {e}")

        base_path = _resolve_safe(path)

        if not base_path.exists():
            return f"Directory does not exist: {path}"

        if base_path.is_file():
            return f"'{path}' is a file. Use a directory path for grep."

        matches = []
        files_searched = 0

        # Iterate through all files
        for file_path in base_path.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip binary files by extension
            if file_path.suffix.lower() in BINARY_EXTENSIONS:
                continue

            # Apply file pattern filter if specified
            if file_pattern:
                import fnmatch

                rel_path = file_path.relative_to(base_path)
                if not fnmatch.fnmatch(file_path.name, file_pattern) and not fnmatch.fnmatch(
                    str(rel_path), file_pattern
                ):
                    continue

            files_searched += 1

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()

                for line_num, line in enumerate(lines, 1):
                    if regex.search(line):
                        rel_path = file_path.relative_to(base_path)

                        # Build context if requested
                        if context_lines > 0:
                            context_start = max(0, line_num - context_lines - 1)
                            context_end = min(len(lines), line_num + context_lines)
                            context_lines_list = []

                            for i in range(context_start, context_end):
                                prefix = "  " if i != line_num - 1 else "> "
                                context_lines_list.append(f"{prefix}{i+1}:{lines[i]}")

                            match_text = "\n".join(context_lines_list)
                        else:
                            # Strip leading whitespace for cleaner output
                            match_text = line.strip()

                        match_str = f"{rel_path}:{line_num}: {match_text}"
                        matches.append(match_str)

                        if len(matches) >= max_results:
                            break

            except (UnicodeDecodeError, PermissionError):
                # Skip files that can't be read as text
                continue
            except Exception as e:
                logger.debug("Skipping %s: %s", file_path, e)
                continue

            if len(matches) >= max_results:
                break

        if not matches:
            return (
                f"No matches found for pattern '{pattern}' "
                f"(searched {files_searched} files in '{path}')"
            )

        truncated_msg = ""
        if len(matches) >= max_results:
            truncated_msg = f"\n... (reached max_results={max_results}, use max_results to see more)"

        logger.info(
            "grep_files: pattern=%r path=%r matches=%d files_searched=%d",
            pattern,
            path,
            len(matches),
            files_searched,
        )

        return f"Found {len(matches)} match(es):\n" + "\n".join(matches) + truncated_msg

    except ToolInputError:
        raise
    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("grep_files error: %s", exc)
        return f"Error: {exc}"


@tool("Find all occurrences of a symbol/identifier in code")
async def find_symbol(
    symbol: str,
    path: str = ".",
    symbol_type: str = "any",
) -> str:
    """Find all occurrences of a symbol/identifier in source code.

    This is a specialized grep for finding function definitions, class
    definitions, variable assignments, etc.

    Args:
        symbol: Symbol name to search for (e.g., "AgentMemory")
        path: Directory to search (default: workspace root)
        symbol_type: Type of symbol ('def', 'class', 'any', 'all')

    Returns:
        List of symbol definitions and usages

    Examples:
        >>> await find_symbol("AgentMemory")
        'Found 5 occurrences:\\n  src/memory.py:10: class AgentMemory:\\n  ...'

        >>> await find_symbol("process_data", symbol_type="def")
        'Found definitions:\\n  src/main.py:42: def process_data():\\n  ...'
    """
    if not symbol:
        return "Error: symbol cannot be empty"

    # Validate symbol is a valid identifier
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", symbol):
        return f"Error: '{symbol}' is not a valid identifier"

    try:
        base_path = _resolve_safe(path)

        if not base_path.exists():
            return f"Directory does not exist: {path}"

        if base_path.is_file():
            # Search single file
            files_to_search = [base_path]
        else:
            # Search all text files
            files_to_search = [
                f for f in base_path.rglob("*") if f.is_file() and f.suffix not in BINARY_EXTENSIONS
            ]

        # Build regex pattern based on symbol_type
        if symbol_type == "def":
            # Python function definitions
            pattern = rf"def\s+{symbol}\s*\("
        elif symbol_type == "class":
            # Python class definitions
            pattern = rf"class\s+{symbol}\s*[\(:]"
        elif symbol_type == "struct":
            # Rust struct definitions
            pattern = rf"struct\s+{symbol}\s*{{|<"
        elif symbol_type == "fn":
            # Rust function definitions
            pattern = rf"(pub\s+)?(async\s+)?(unsafe\s+)?fn\s+{symbol}\s*<*\("
        elif symbol_type == "any":
            # Any definition (def, class, struct, fn)
            pattern = rf"((def|class|struct|fn)\s+){symbol}[\s\(::<{{]*"
        else:
            # Default: search for the symbol as a word
            pattern = rf"\b{symbol}\b"

        regex = re.compile(pattern)
        definitions = []
        usages = []

        for file_path in files_to_search:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()

                for line_num, line in enumerate(lines, 1):
                    if regex.search(line):
                        rel_path = file_path.relative_to(base_path)
                        definitions.append(f"{rel_path}:{line_num}: {line.strip()}")
                    elif symbol_type in ("any", "all") and re.search(rf"\b{symbol}\b", line):
                        # Also collect general usages
                        rel_path = file_path.relative_to(base_path)
                        usages.append(f"{rel_path}:{line_num}: {line.strip()}")

            except (UnicodeDecodeError, PermissionError):
                continue
            except Exception as e:
                logger.debug("Skipping %s: %s", file_path, e)
                continue

        result_lines = []

        if definitions:
            result_lines.append(f"Found {len(definitions)} definition(s):")
            result_lines.extend(definitions[:20])
            if len(definitions) > 20:
                result_lines.append(f"  ... and {len(definitions) - 20} more")

        if usages and symbol_type in ("any", "all"):
            # Dedupe usages from definitions
            usages_set = set(usages) - set(definitions)
            if usages_set:
                result_lines.append(f"\nFound {len(usages_set)} usage(s):")
                result_lines.extend(sorted(usages_set)[:30])
                if len(usages_set) > 30:
                    result_lines.append(f"  ... and {len(usages_set) - 30} more")

        if not result_lines:
            return f"Symbol '{symbol}' not found in '{path}'"

        logger.info("find_symbol: symbol=%r path=%r definitions=%d", symbol, path, len(definitions))

        return "\n".join(result_lines)

    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.error("find_symbol error: %s", exc)
        return f"Error: {exc}"
