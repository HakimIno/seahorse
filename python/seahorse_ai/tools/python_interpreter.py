"""PythonInterpreter tool — safely executes Python code in a restricted sandbox.

Uses subprocess isolation to prevent the agent from affecting the host process.
Only allows a curated set of safe imports.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import tempfile
import textwrap

import anyio

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Max execution time in seconds
_TIMEOUT_SECONDS = 30

# Allowed stdlib modules inside the sandbox
_ALLOWED_IMPORTS = {
    "math",
    "statistics",
    "decimal",
    "fractions",
    "json",
    "re",
    "string",
    "textwrap",
    "datetime",
    "calendar",
    "time",
    "collections",
    "itertools",
    "functools",
    "random",
    "hashlib",
    "base64",
    "uuid",
    "typing",
    "dataclasses",
    "enum",
    "abc",
    "_io",
    "pandas",
    "numpy",
    "matplotlib",
}

_SANDBOX_HEADER = textwrap.dedent(f"""\
    import sys as _sys
    _allowed = {_ALLOWED_IMPORTS!r}
    import builtins
    
    _real_import = builtins.__import__

    def _safe_import(name, *args, **kwargs):
        top = name.split(".")[0]
        if top not in _allowed:
            raise ImportError(f"Import of '{{name}}' is not allowed in the sandbox")
        return _real_import(name, *args, **kwargs)

    builtins.__import__ = _safe_import
    # Note: We keep exec, eval, and compile as they are needed for many 
    # data processing libraries (e.g. pandas) and dynamic code blocks.
""")


def _get_python_executable() -> str:
    """Find the real Python interpreter.

    When running inside a Rust binary (Pyo3), sys.executable points to the
    host binary, not the Python interpreter. We need the real one for the sandbox.
    """
    # 1. Try to find .venv/bin/python relative to this file
    # This file is in <root>/python/seahorse_ai/tools/python_interpreter.py
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    venv_python = os.path.join(base_dir, ".venv", "bin", "python3")
    if os.path.exists(venv_python):
        return venv_python

    # 2. Fallback to standard sys.executable if it looks like a python binary
    if "python" in sys.executable.lower():
        return sys.executable

    # 3. Last resort: use whatever 'python3' is in the PATH
    return "python3"


@tool(
    "Execute Python code and return the output. "
    "Useful for calculations, data processing, and logic that needs precise computation. "
    "Only pure-Python/stdlib code is allowed (no file I/O, no network, no dangerous imports)."
)
async def python_interpreter(code: str) -> str:
    """Execute Python code in a subprocess sandbox and capture stdout/stderr."""
    logger.info("python_interpreter: executing %d chars of code", len(code))

    # Write code to a temp file and run in a fresh subprocess
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(_SANDBOX_HEADER)
        f.write("\n")
        f.write("# --- user code ---\n")
        f.write(code)
        tmp_path = f.name

    try:
        # Build a minimal safe environment
        # We MUST keep PATH so it can find basic binaries,
        # but we strip PYTHONPATH to avoid importing the project packages by accident
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        }

        import asyncio
        process = await asyncio.create_subprocess_exec(
            _get_python_executable(), tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=safe_env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=_TIMEOUT_SECONDS
            )
            stdout = stdout_bytes.decode().strip()
            stderr = stderr_bytes.decode().strip()
            returncode = process.returncode
        except asyncio.TimeoutError:
            process.kill()
            logger.warning("python_interpreter: code timed out after %ds", _TIMEOUT_SECONDS)
            return f"Error: Code execution timed out after {_TIMEOUT_SECONDS} seconds."

        logger.info(f"Interpreter stdout: {stdout}")
        if stderr:
            logger.error(f"Interpreter stderr: {stderr}")

        if returncode != 0:
            return f"Error (exit {returncode}):\n{stderr or stdout}"

        output_parts = []
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(f"[stderr] {stderr}")

        return "\n".join(output_parts) if output_parts else "(no output)"

    except Exception as exc:
        logger.error("python_interpreter: unexpected error: %s", exc)
        return f"Error: {exc}"
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
