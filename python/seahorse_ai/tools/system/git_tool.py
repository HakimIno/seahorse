"""Git tool - safe git operations with HITL approval.

Essential for version control operations in coding workflows.
Supports status, diff, log, branch, commit, and other git operations.
"""

from __future__ import annotations

import logging

from seahorse_ai.tools.base import ToolInputError, tool

logger = logging.getLogger(__name__)

# Destructive git operations that are blocked
BLOCKED_OPERATIONS = {
    "push --force",
    "push -f",
    "reset --hard",
    "clean -f",
    "clean -fd",
    "branch -D",
    "update-ref -d",
}


@tool("Execute git commands (HIGH RISK - requires approval)", risk_level="high")
async def git_command(args: str, timeout: int = 30) -> str:
    """Execute a git command in the workspace.

    Supports most git operations with safety checks to prevent
    destructive actions like force push.

    BLOCKED OPERATIONS (for safety):
    - push --force / push -f
    - reset --hard
    - clean -f / clean -fd
    - branch -D

    Args:
        args: Git command arguments (e.g., "status", "diff", "log --oneline -5")
        timeout: Maximum execution time in seconds (default: 30)

    Returns:
        Git command output

    Examples:
        >>> await git_command("status")
        'On branch main...'

        >>> await git_command("log --oneline -10")
        'abc1234 Latest commit...'

        >>> await git_command("diff HEAD~1")
        'diff --git a/file.py...'
    """
    if not args or not args.strip():
        return "Error: git arguments cannot be empty"

    args = args.strip()

    # Check for blocked operations
    for blocked in BLOCKED_OPERATIONS:
        if blocked in args:
            return (
                f"Error: Git command '{args}' is blocked for safety. "
                f"The '{blocked}' operation can cause data loss. "
                f"If you need this operation, use bash_command directly after careful consideration."
            )

    try:
        # Execute via bash_tool (inherits HITL approval and security)
        from .bash_tool import bash_command

        result = await bash_command(f"git {args}", timeout=timeout)

        return result

    except Exception as exc:
        logger.error("git_command error: %s", exc)
        return f"Error: {exc}"


@tool("Show git status with file changes")
async def git_status(porcelain: bool = False) -> str:
    """Show git status information.

    Args:
        porcelain: If True, use machine-readable format (for parsing)

    Returns:
        Git status output

    Examples:
        >>> await git_status()
        'On branch main...'

        >>> await git_status(porcelain=True)
        'M file.py\\n?? new_file.py'
    """
    args = "status --short" if porcelain else "status"
    return await git_command(args)


@tool("Show git diff of changes")
async def git_diff(ref: str = "", file: str = "", staged: bool = False) -> str:
    """Show git diff of changes.

    Args:
        ref: Git reference to compare against (default: unstaged changes)
        file: Specific file to diff (optional)
        staged: If True, show staged changes (--staged)

    Returns:
        Git diff output

    Examples:
        >>> await git_diff()
        'diff --git a/file.py b/file.py...'

        >>> await git_diff("HEAD~1", "src/main.py")
        'diff --git a/src/main.py...'

        >>> await git_diff(staged=True)
        'diff --git a/file.py b/file.py... (staged)'
    """
    args_parts = ["diff"]

    if staged:
        args_parts.append("--staged")

    if ref:
        args_parts.append(ref)

    if file:
        args_parts.append("--")
        args_parts.append(file)

    args = " ".join(args_parts)
    return await git_command(args)


@tool("Show git commit history")
async def git_log(limit: int = 10, oneline: bool = True) -> str:
    """Show git commit history.

    Args:
        limit: Maximum number of commits to show (default: 10)
        oneline: If True, use compact format (default: True)

    Returns:
        Git log output

    Examples:
        >>> await git_log()
        'abc1234 Latest commit\\n567890 Previous commit...'

        >>> await git_log(limit=5, oneline=False)
        'commit abc1234...\\nAuthor: ...'
    """
    args_parts = ["log"]

    if oneline:
        args_parts.append("--oneline")

    args_parts.append(f"-{limit}")

    args = " ".join(args_parts)
    return await git_command(args)


@tool("Create a git commit with all staged files", risk_level="high")
async def git_commit(message: str, all_files: bool = True) -> str:
    """Create a git commit with a message.

    Stages all changes (unless all_files=False) and creates a commit
    with Seahorse co-authorship.

    Args:
        message: Commit message
        all_files: If True, stage all changes with git add -A (default: True)

    Returns:
        Git commit output

    Examples:
        >>> await git_commit("Add new feature")
        '[main abc1234] Add new feature\\n 1 file changed...'

        >>> await git_commit("Fix bug in parser", all_files=False)
        '[main abc1234] Fix bug in parser\\n 1 file changed...'
    """
    if not message or not message.strip():
        return "Error: commit message cannot be empty"

    message = message.strip()

    try:
        from .bash_tool import bash_command

        # Stage all changes if requested
        if all_files:
            stage_result = await bash_command("git add -A")
            if "Error" in stage_result and "Exit code: 0" not in stage_result:
                return f"Failed to stage changes: {stage_result}"

        # Create commit with co-authorship
        # Use proper escaping for the commit message
        escaped_message = message.replace('"', '\\"')

        commit_cmd = (
            f'git commit -m "{escaped_message}" '
            f'-m "Co-Authored-By: Seahorse <seahorse@example.com>"'
        )

        result = await bash_command(commit_cmd)

        # Check if commit was successful
        if "Exit code: 0" in result or ("nothing to commit" not in result.lower()):
            logger.info("git_commit: message=%r all_files=%s", message, all_files)
            return result

        return result

    except Exception as exc:
        logger.error("git_commit error: %s", exc)
        return f"Error: {exc}"


@tool("Show current git branch")
async def git_branch(show_all: bool = False) -> str:
    """Show git branch information.

    Args:
        show_all: If True, show all branches (default: False - show current only)

    Returns:
        Git branch output

    Examples:
        >>> await git_branch()
        '* main'

        >>> await git_branch(show_all=True)
        '* main\\n  develop\\n  feature/new-thing'
    """
    args = "branch -a" if show_all else "branch"
    return await git_command(args)


@tool("Show git blame for a file")
async def git_blame(file: str, rev: str = "HEAD") -> str:
    """Show git blame for a file (who changed what line).

    Args:
        file: File path to blame
        rev: Git revision (default: HEAD)

    Returns:
        Git blame output

    Examples:
        >>> await git_blame("src/main.py")
        'abc1234 (Author Name 2024-03-15 10:30:15 +0000 1)def main():...'
    """
    if not file or not file.strip():
        return "Error: file path cannot be empty"

    return await git_command(f"blame {rev} -- {file}")


@tool("Show git remote information")
async def git_remote(verbose: bool = False) -> str:
    """Show git remote repositories.

    Args:
        verbose: If True, show detailed remote information

    Returns:
        Git remote output

    Examples:
        >>> await git_remote()
        'origin\\n  fetch: https://github.com/...'

        >>> await git_remote(verbose=True)
        'origin\\n  Fetch URL: https://github.com/...\\n  Push  URL: ...'
    """
    args = "remote -v" if verbose else "remote"
    return await git_command(args)


@tool("Create a new git branch")
async def git_checkout_new(branch_name: str) -> str:
    """Create and checkout a new git branch.

    Args:
        branch_name: Name of the new branch

    Returns:
        Git checkout output

    Examples:
        >>> await git_checkout_new("feature/new-thing")
        'Switched to a new branch feature/new-thing'
    """
    if not branch_name or not branch_name.strip():
        return "Error: branch name cannot be empty"

    # Validate branch name
    branch_name = branch_name.strip()
    if not branch_name.replace("-", "").replace("/", "").replace("_", "").isalnum():
        return "Error: branch name contains invalid characters"

    return await git_command(f"checkout -b {branch_name}")


@tool("Switch to an existing git branch")
async def git_switch(branch_name: str) -> str:
    """Switch to an existing git branch.

    Args:
        branch_name: Name of the branch to switch to

    Returns:
        Git switch output

    Examples:
        >>> await git_switch("develop")
        'Switched to branch develop'
    """
    if not branch_name or not branch_name.strip():
        return "Error: branch name cannot be empty"

    return await git_command(f"switch {branch_name.strip()}")
