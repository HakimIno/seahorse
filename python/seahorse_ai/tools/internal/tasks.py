"""Task management tools — track and manage multi-step workflows.

Provides task tracking with SQLite persistence via FFI bridge to Rust.
Supports task dependencies, status tracking, and querying.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

# Global task store instance (lazy initialization)
_task_store: Optional[object] = None


def get_task_store():
    """Get or create the global task store instance.

    The task store is created in the workspace directory (.seahorse_tasks.db)
    """
    global _task_store

    if _task_store is None:
        try:
            from seahorse_ffi import PyTaskStore

            # Use workspace directory for task database
            workspace = Path(os.environ.get("SEAHORSE_WORKSPACE", "."))
            db_path = workspace / ".seahorse_tasks.db"

            _task_store = PyTaskStore(str(db_path))
            logger.info("Created task store at: %s", db_path)

        except ImportError:
            logger.error("Failed to import PyTaskStore from seahorse_ffi")
            raise RuntimeError(
                "PyTaskStore not available. Please build the FFI module with: "
                "uv run maturin develop --features pyo3/extension-module"
            )

    return _task_store


@tool("Create a new task in the task tracking system")
async def task_create(
    subject: str,
    description: str,
    owner: str = None,
    metadata: str = None,
) -> str:
    """Create a new task in the task tracking system.

    Tasks are persisted to SQLite and can be queried, updated, and tracked.
    Useful for breaking down complex workflows into manageable steps.

    Args:
        subject: Short task title (e.g., "Refactor auth module")
        description: Detailed task description with acceptance criteria
        owner: Optional agent assigned to this task
        metadata: Optional JSON metadata string

    Returns:
        Task creation confirmation with task ID

    Examples:
        >>> await task_create("Fix login bug", "Users cannot login with SAML")
        'Created task abc12345: Fix login bug'

        >>> await task_create(
        ...     "Add tests",
        ...     "Write unit tests for payment processor",
        ...     owner="test_agent"
        ... )
        'Created task def67890: Add tests'
    """
    try:
        store = get_task_store()

        # Generate short task ID (8 characters)
        task_id = str(uuid.uuid4())[:8]

        store.create_task(
            id=task_id,
            subject=subject,
            description=description,
            owner=owner,
            metadata=metadata,
        )

        logger.info("Created task %s: %s", task_id, subject)
        return f"Created task {task_id}: {subject}"

    except Exception as e:
        logger.error("Failed to create task: %s", e)
        return f"Error: Failed to create task - {e}"


@tool("List all tasks, optionally filtered by status")
async def task_list(status: str = None) -> str:
    """List all tasks in the task tracking system.

    Args:
        status: Optional status filter (pending, in_progress, completed, failed, cancelled)

    Returns:
        List of tasks with their details

    Examples:
        >>> await task_list()
        'Found 3 tasks:\\n  abc12345: Fix login bug [pending]\\n  ...'

        >>> await task_list(status="pending")
        'Found 2 pending tasks:\\n  abc12345: Fix login bug\\n  ...'
    """
    try:
        store = get_task_store()

        tasks = store.list_tasks(status=status)

        if not tasks:
            status_msg = f" with status '{status}'" if status else ""
            return f"No tasks found{status_msg}"

        lines = [f"Found {len(tasks)} task(s):"]

        for task in tasks:
            status_str = task.get("status", "unknown")
            subject = task.get("subject", "No subject")
            task_id = task.get("id", "unknown")
            owner = task.get("owner")

            owner_str = f" (owner: {owner})" if owner else ""
            lines.append(f"  {task_id}: {subject} [{status_str}]{owner_str}")

        return "\n".join(lines)

    except Exception as e:
        logger.error("Failed to list tasks: %s", e)
        return f"Error: Failed to list tasks - {e}"


@tool("Get details of a specific task")
async def task_get(task_id: str) -> str:
    """Get detailed information about a specific task.

    Args:
        task_id: Task identifier (e.g., "abc12345")

    Returns:
        Task details or error message

    Examples:
        >>> await task_get("abc12345")
        'Task abc12345:\\n  Subject: Fix login bug\\n  Description: ...'
    """
    try:
        store = get_task_store()

        task = store.get_task(id=task_id)

        if task is None:
            return f"Task not found: {task_id}"

        lines = [f"Task {task_id}:"]
        lines.append(f"  Subject: {task.get('subject', 'No subject')}")
        lines.append(f"  Status: {task.get('status', 'unknown')}")
        lines.append(f"  Description: {task.get('description', 'No description')}")

        if task.get("owner"):
            lines.append(f"  Owner: {task['owner']}")

        if task.get("created_at"):
            lines.append(f"  Created: {task['created_at']}")

        if task.get("completed_at"):
            lines.append(f"  Completed: {task['completed_at']}")

        if task.get("blocked_by"):
            lines.append(f"  Blocked by: {', '.join(task['blocked_by'])}")

        if task.get("metadata"):
            lines.append(f"  Metadata: {task['metadata']}")

        return "\n".join(lines)

    except Exception as e:
        logger.error("Failed to get task: %s", e)
        return f"Error: Failed to get task - {e}"


@tool("Update task status and optionally assign owner")
async def task_update(
    task_id: str,
    status: str,
    owner: str = None,
) -> str:
    """Update the status of a task.

    Args:
        task_id: Task identifier
        status: New status (pending, in_progress, completed, failed, cancelled)
        owner: Optional new owner to assign

    Returns:
        Confirmation message

    Examples:
        >>> await task_update("abc12345", "in_progress")
        'Updated task abc12345 to in_progress'

        >>> await task_update("abc12345", "completed", owner="agent_1")
        'Updated task abc12345 to completed (owner: agent_1)'
    """
    try:
        store = get_task_store()

        store.update_task_status(id=task_id, status=status, owner=owner)

        owner_str = f" (owner: {owner})" if owner else ""
        logger.info("Updated task %s to %s%s", task_id, status, owner_str)
        return f"Updated task {task_id} to {status}{owner_str}"

    except Exception as e:
        logger.error("Failed to update task: %s", e)
        return f"Error: Failed to update task - {e}"


@tool("Delete a task from the task tracking system")
async def task_delete(task_id: str) -> str:
    """Delete a task from the task tracking system.

    Warning: This cannot be undone!

    Args:
        task_id: Task identifier

    Returns:
        Confirmation message

    Examples:
        >>> await task_delete("abc12345")
        'Deleted task abc12345'
    """
    try:
        store = get_task_store()

        deleted = store.delete_task(id=task_id)

        if deleted:
            logger.info("Deleted task %s", task_id)
            return f"Deleted task {task_id}"
        else:
            return f"Task not found: {task_id}"

    except Exception as e:
        logger.error("Failed to delete task: %s", e)
        return f"Error: Failed to delete task - {e}"


@tool("Count tasks by status")
async def task_count(status: str = None) -> str:
    """Count tasks in the task tracking system.

    Args:
        status: Optional status filter

    Returns:
        Task count

    Examples:
        >>> await task_count()
        'Total tasks: 15'

        >>> await task_count(status="pending")
        'Pending tasks: 5'
    """
    try:
        store = get_task_store()

        count = store.count_tasks(status=status)

        if status:
            return f"{status.capitalize()} tasks: {count}"
        else:
            return f"Total tasks: {count}"

    except Exception as e:
        logger.error("Failed to count tasks: %s", e)
        return f"Error: Failed to count tasks - {e}"


@tool("Get tasks that are ready to execute (not blocked)")
async def task_get_available() -> str:
    """Get tasks that are ready to be executed.

    Returns tasks that are:
    - In pending status
    - Not blocked by other tasks

    Useful for auto-pilot mode to find next tasks to execute.

    Returns:
        List of available tasks

    Examples:
        >>> await task_get_available()
        'Available tasks (2):\\n  abc12345: Fix login bug\\n  ...'
    """
    try:
        store = get_task_store()

        tasks = store.get_available_tasks()

        if not tasks:
            return "No available tasks (all pending tasks are blocked or no tasks exist)"

        lines = [f"Available tasks ({len(tasks)}):"]

        for task in tasks:
            subject = task.get("subject", "No subject")
            task_id = task.get("id", "unknown")
            owner = task.get("owner")

            owner_str = f" (owner: {owner})" if owner else ""
            lines.append(f"  {task_id}: {subject}{owner_str}")

        return "\n".join(lines)

    except Exception as e:
        logger.error("Failed to get available tasks: %s", e)
        return f"Error: Failed to get available tasks - {e}"


@tool("Set task dependencies (blocking relationships)")
async def task_set_dependencies(
    task_id: str,
    blocked_by: str,
) -> str:
    """Set task dependencies.

    Specifies which tasks must complete before this task can start.

    Args:
        task_id: Task to set dependencies for
        blocked_by: Comma-separated list of task IDs that must complete first

    Returns:
        Confirmation message

    Examples:
        >>> await task_set_dependencies("abc12345", "xyz98765,def45678")
        'Set dependencies for task abc12345: blocked by xyz98765, def45678'
    """
    try:
        store = get_task_store()

        # Parse comma-separated task IDs
        blocker_ids = [tid.strip() for tid in blocked_by.split(",") if tid.strip()]

        store.set_dependencies(task_id=task_id, blocked_by=blocker_ids)

        logger.info("Set dependencies for task %s: blocked by %s", task_id, blocker_ids)
        return f"Set dependencies for task {task_id}: blocked by {', '.join(blocker_ids)}"

    except Exception as e:
        logger.error("Failed to set dependencies: %s", e)
        return f"Error: Failed to set dependencies - {e}"
