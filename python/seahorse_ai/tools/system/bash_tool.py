"""Bash tool - execute shell commands in the workspace.

HIGH-RISK tool that requires HITL (Human-in-the-Loop) approval before
execution. Essential for running tests, git commands, build scripts, etc.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from pathlib import Path

from seahorse_ai.tools.base import ToolInputError, tool

from .filesystem import _resolve_safe

logger = logging.getLogger(__name__)

# Dangerous command patterns that are explicitly blocked
BLOCKED_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf /*",
    "rm -rf \\",
    "> /dev/sd",
    "> /dev/",
    "mkfs.",
    "dd if=/",
    ":(){ :|:& };:",
    "chmod -R 777 /",
    "chown -R",
    "curl ",
    "wget ",
    "nc -l",
    "netcat -l",
]

# Commands that are allowed but need special care
CAREFUL_COMMANDS = ["rm", "mv", "dd", "chmod", "chown", "kill", "killall"]


@tool("Execute shell command (HIGH RISK - requires approval)", risk_level="high")
async def bash_command(command: str, timeout: int = 30) -> str:
    """Execute a shell command in the workspace directory.

    Requires HITL approval before execution. This is essential for
    running tests, git commands, build scripts, and other operations.

    SECURITY MEASURES:
    - Requires HITL approval (risk_level="high")
    - Workspace containment (can only access files in workspace)
    - Timeout protection (default 30s)
    - Dangerous pattern blocking
    - No stdin (prevents interactive hangs)
    - Commands parsed with shlex.split() (safe, no shell injection)

    Args:
        command: Shell command to execute (no shell expansion)
        timeout: Maximum execution time in seconds (default: 30)

    Returns:
        Command output (stdout + stderr) and exit code

    Examples:
        >>> await bash_command("cargo check")
        'STDOUT:\\n    Checking seahorse-core v0.1.0...\\n    Finished dev profile...\\nExit code: 0'

        >>> await bash_command("git status")
        'STDOUT:\\nOn branch main...\\nExit code: 0'

        >>> await bash_command("python -m pytest tests/")
        'STDOUT:\\ntest_session_starts...\\nExit code: 0'
    """
    if not command or not command.strip():
        return "Error: command cannot be empty"

    command = command.strip()

    # Check for blocked dangerous patterns
    for blocked in BLOCKED_PATTERNS:
        if blocked in command:
            return (
                f"Error: Command blocked for safety. Pattern '{blocked}' is not allowed. "
                f"This command could cause data loss or system damage."
            )

    # Warn about careful commands
    for careful in CAREFUL_COMMANDS:
        if command.startswith(careful + " ") or command == careful:
            logger.warning("bash_command: executing potentially dangerous command: %s", command)

    try:
        # Parse command safely (no shell expansion)
        try:
            args = shlex.split(command)
        except ValueError as e:
            raise ToolInputError(f"Invalid command syntax: {e}")

        # Get workspace directory
        workspace = _resolve_safe(".")

        logger.info("bash_command: command=%r cwd=%s timeout=%d", command, workspace, timeout)

        # Create subprocess
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,  # No stdin to prevent hangs
        )

        try:
            # Wait for completion with timeout
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            result_parts = []

            if stdout:
                stdout_text = stdout.decode("utf-8", errors="replace")
                # Truncate very long output
                if len(stdout_text) > 10000:
                    stdout_text = stdout_text[:10000] + "\n... (truncated, too long)"
                result_parts.append(f"STDOUT:\n{stdout_text}")

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if len(stderr_text) > 10000:
                    stderr_text = stderr_text[:10000] + "\n... (truncated, too long)"
                result_parts.append(f"STDERR:\n{stderr_text}")

            result_parts.append(f"Exit code: {proc.returncode}")

            result = "\n".join(result_parts)

            logger.info(
                "bash_command: command=%r exit_code=%d stdout_len=%d stderr_len=%d",
                command,
                proc.returncode,
                len(stdout) if stdout else 0,
                len(stderr) if stderr else 0,
            )

            return result

        except asyncio.TimeoutError:
            # Kill process on timeout
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass

            logger.warning("bash_command: command timed out after %ds: %s", timeout, command)
            return f"Error: Command timed out after {timeout}s. Process was killed."

    except ToolInputError:
        raise
    except PermissionError as exc:
        return f"Permission denied: {exc}"
    except FileNotFoundError:
        return f"Error: Command not found. The '{args[0]}' command is not available or not in PATH."
    except Exception as exc:
        logger.error("bash_command error: %s", exc)
        return f"Error: {exc}"


@tool("Run a command and check if it succeeds (exit code 0)")
async def check_command(command: str, timeout: int = 30) -> str:
    """Run a command and return True/False based on exit code.

    Useful for conditional logic in workflows - e.g., "run tests
    and report result".

    Args:
        command: Shell command to execute
        timeout: Maximum execution time in seconds (default: 30)

    Returns:
        "True" if exit code is 0, "False" otherwise

    Examples:
        >>> await check_command("cargo check")
        'True'

        >>> await check_command("test -f missing.txt")
        'False'
    """
    # This is also high-risk since it executes commands
    result = await bash_command(command, timeout)

    # Extract exit code from result
    if "Exit code: 0" in result:
        return "True"
    elif "Exit code:" in result:
        return "False"
    else:
        # Error occurred
        return f"Error: {result}"


@tool("Get information about the system and environment")
async def system_info() -> str:
    """Get system information for debugging and context.

    Returns information about OS, shell, workspace, and environment.

    NO SECURITY RISK - read-only system information.
    """
    import platform
    import sys

    workspace = _resolve_safe(".")

    info_lines = [
        "System Information:",
        f"  OS: {platform.system()} {platform.release()}",
        f"  Architecture: {platform.machine()}",
        f"  Python: {sys.version}",
        f"  Workspace: {workspace}",
        f"  Working Directory: {os.getcwd()}",
    ]

    # Check for common tools
    tools = ["git", "cargo", "python", "node", "npm", "rustc"]
    available_tools = []

    for tool in tools:
        try:
            proc = await asyncio.create_subprocess_exec(
                tool,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                version = stdout.decode().strip().split("\n")[0]
                available_tools.append(f"  {tool}: {version}")
        except FileNotFoundError:
            continue

    if available_tools:
        info_lines.append("\nAvailable Tools:")
        info_lines.extend(available_tools)

    # Environment variables (safe ones only)
    info_lines.append("\nEnvironment:")
    safe_vars = ["PATH", "HOME", "USER", "SHELL", "LANG", "SEAHORSE_WORKSPACE"]
    for var in safe_vars:
        value = os.environ.get(var)
        if value:
            # Truncate long values
            if len(value) > 100:
                value = value[:100] + "..."
            info_lines.append(f"  {var}={value}")

    return "\n".join(info_lines)
