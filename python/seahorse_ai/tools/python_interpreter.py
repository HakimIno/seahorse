"""PythonInterpreter tool — safely executes Python code in a restricted sandbox.

Uses subprocess isolation to prevent the agent from affecting the host process.
Only allows a curated set of safe imports.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import textwrap

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Max execution time in seconds
_TIMEOUT_SECONDS = 10

# Allowed stdlib modules inside the sandbox
_ALLOWED_IMPORTS = {
    "math", "statistics", "decimal", "fractions",
    "json", "re", "string", "textwrap",
    "datetime", "calendar", "time",
    "collections", "itertools", "functools",
    "random", "hashlib", "base64", "uuid",
    "typing", "dataclasses", "enum", "abc",
}

_SANDBOX_HEADER = textwrap.dedent(f"""\
    import sys as _sys
    _allowed = {_ALLOWED_IMPORTS!r}
    _real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def _safe_import(name, *args, **kwargs):
        top = name.split(".")[0]
        if top not in _allowed:
            raise ImportError(f"Import of '{{name}}' is not allowed in the sandbox")
        return _real_import(name, *args, **kwargs)

    __builtins__.__import__ = _safe_import  # type: ignore
    # Remove dangerous builtins
    for _bad in ("open", "exec", "eval", "compile", "__import__"):
        if hasattr(__builtins__, _bad):
            try:
                delattr(__builtins__, _bad)
            except Exception:
                pass
""")


@tool(
    "Execute Python code and return the output. "
    "Useful for calculations, data processing, and logic that needs precise computation. "
    "Only pure-Python/stdlib code is allowed (no file I/O, no network, no dangerous imports)."
)
async def python_interpreter(code: str) -> str:
    """Execute Python code in a subprocess sandbox and capture stdout/stderr."""
    logger.info("python_interpreter: executing %d chars of code", len(code))

    # Write code to a temp file and run in a fresh subprocess
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(_SANDBOX_HEADER)
        f.write("\n")
        f.write("# --- user code ---\n")
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            return f"Error (exit {result.returncode}):\n{stderr or stdout}"

        output_parts = []
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(f"[stderr] {stderr}")

        return "\n".join(output_parts) if output_parts else "(no output)"

    except subprocess.TimeoutExpired:
        logger.warning("python_interpreter: code timed out after %ds", _TIMEOUT_SECONDS)
        return f"Error: Code execution timed out after {_TIMEOUT_SECONDS} seconds."
    except Exception as exc:
        logger.error("python_interpreter: unexpected error: %s", exc)
        return f"Error: {exc}"
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
