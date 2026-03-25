"""Cron Scheduler — schedule recurring tasks and reminders.

Provides simplified cron-like scheduling for recurring tasks.
Stores scheduled tasks in JSON file in the workspace.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from seahorse_ai.tools.base import ToolInputError, tool

logger = logging.getLogger(__name__)

# Schedule storage file
_SCHEDULES_FILE = ".seahorse_schedules.json"


def _get_schedules_path() -> Path:
    """Get the path to the schedules file."""
    workspace = Path(os.environ.get("SEAHORSE_WORKSPACE", "."))
    return workspace / _SCHEDULES_FILE


def _load_schedules() -> dict:
    """Load schedules from JSON file."""
    path = _get_schedules_path()

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load schedules from %s: %s", path, e)
            return {}

    return {}


def _save_schedules(schedules: dict) -> None:
    """Save schedules to JSON file."""
    path = _get_schedules_path()

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(schedules, f, indent=2)

        logger.debug("Saved %d schedules to %s", len(schedules), path)

    except IOError as e:
        logger.error("Failed to save schedules to %s: %s", path, e)
        raise


@tool("Schedule a recurring task using cron expression")
async def cron_create(
    cron_expr: str,
    prompt: str,
    recurring: bool = True,
    description: str = None,
) -> str:
    """Schedule a task using cron expression.

    This is a simplified implementation for storing scheduled tasks.
    Full execution requires a background worker process.

    Cron Expression Format (5 fields):
        minute hour day month dow
    Examples:
        "0 9 * * *" - Every day at 9:00 AM
        "30 14 * * 1-5" - Weekdays at 2:30 PM
        "*/5 * * * *" - Every 5 minutes
        "0 0 * * 0" - Every Sunday at midnight

    Args:
        cron_expr: Cron expression (5 fields: minute hour day month dow)
        prompt: Task prompt/description to execute
        recurring: If True, repeats on schedule; if False, runs once
        description: Optional human-readable description

    Returns:
        Job creation confirmation with job ID

    Examples:
        >>> await cron_create("0 9 * * *", "Run daily test suite")
        'Scheduled job 1: Run daily test suite at 0 9 * * *'

        >>> await cron_create("*/5 * * * *", "Check system status")
        'Scheduled job 2: Check system status at */5 * * * *'
    """
    try:
        # Validate cron expression (basic check)
        parts = cron_expr.split()

        if len(parts) != 5:
            raise ToolInputError(
                f"Invalid cron expression: '{cron_expr}' "
                f"(must be 5 parts: minute hour day month dow, got {len(parts)})"
            )

        # Additional validation could be added here (range checks, etc.)

        schedules = _load_schedules()

        # Generate job ID
        job_id = str(len(schedules) + 1)

        # Get current workspace path for context
        workspace = os.environ.get("SEAHORSE_WORKSPACE", ".")

        job = {
            "id": job_id,
            "cron": cron_expr,
            "prompt": prompt,
            "recurring": recurring,
            "description": description or prompt,
            "created_at": str(Path.cwd()),  # Simple context
            "workspace": workspace,
            "enabled": True,
        }

        schedules[job_id] = job

        _save_schedules(schedules)

        logger.info(
            "Scheduled job %s: %s at %s (recurring=%s)",
            job_id,
            prompt,
            cron_expr,
            recurring,
        )

        return f"Scheduled job {job_id}: {prompt} at {cron_expr}"

    except ToolInputError:
        raise
    except Exception as e:
        logger.error("Failed to create cron job: %s", e)
        return f"Error: Failed to schedule job - {e}"


@tool("List all scheduled cron jobs")
async def cron_list() -> str:
    """List all scheduled cron jobs.

    Returns:
        List of scheduled jobs or message if none exist

    Examples:
        >>> await cron_list()
        'Scheduled jobs (2):\\n  1: Run daily tests at 0 9 * * *\\n  ...'
    """
    try:
        schedules = _load_schedules()

        if not schedules:
            return "No scheduled tasks"

        lines = [f"Scheduled jobs ({len(schedules)}):"]

        for job_id, job in schedules.items():
            cron = job.get("cron", "unknown")
            prompt = job.get("prompt", "No prompt")
            recurring = job.get("recurring", True)
            enabled = job.get("enabled", True)

            status = "enabled" if enabled else "disabled"
            recurring_str = "recurring" if recurring else "one-time"

            lines.append(f"  {job_id}: {prompt}")
            lines.append(f"      Cron: {cron} ({recurring_str}, {status})")

        return "\n".join(lines)

    except Exception as e:
        logger.error("Failed to list cron jobs: %s", e)
        return f"Error: Failed to list jobs - {e}"


@tool("Delete a scheduled cron job")
async def cron_delete(job_id: str) -> str:
    """Delete a scheduled cron job.

    Args:
        job_id: Job identifier (from cron_list)

    Returns:
        Confirmation message

    Examples:
        >>> await cron_delete("1")
        'Deleted job 1: Run daily tests'
    """
    try:
        schedules = _load_schedules()

        if job_id not in schedules:
            return f"Job {job_id} not found"

        job = schedules[job_id]
        prompt = job.get("prompt", "Unknown")

        del schedules[job_id]

        _save_schedules(schedules)

        logger.info("Deleted job %s", job_id)
        return f"Deleted job {job_id}: {prompt}"

    except Exception as e:
        logger.error("Failed to delete cron job: %s", e)
        return f"Error: Failed to delete job - {e}"


@tool("Enable or disable a scheduled cron job")
async def cron_enable(job_id: str, enabled: bool = True) -> str:
    """Enable or disable a scheduled cron job.

    Args:
        job_id: Job identifier
        enabled: True to enable, False to disable

    Returns:
        Confirmation message

    Examples:
        >>> await cron_enable("1", enabled=False)
        'Disabled job 1: Run daily tests'

        >>> await cron_enable("1", enabled=True)
        'Enabled job 1: Run daily tests'
    """
    try:
        schedules = _load_schedules()

        if job_id not in schedules:
            return f"Job {job_id} not found"

        job = schedules[job_id]
        job["enabled"] = enabled

        _save_schedules(schedules)

        prompt = job.get("prompt", "Unknown")
        status = "enabled" if enabled else "disabled"

        logger.info("%s job %s", status.capitalize(), job_id)
        return f"{status.capitalize()} job {job_id}: {prompt}"

    except Exception as e:
        logger.error("Failed to enable/disable cron job: %s", e)
        return f"Error: Failed to update job - {e}"


@tool("Get information about a cron expression")
async def cron_explain(cron_expr: str) -> str:
    """Explain what a cron expression does.

    Args:
        cron_expr: Cron expression to explain

    Returns:
        Human-readable explanation

    Examples:
        >>> await cron_explain("0 9 * * *")
        'Runs at 9:00 AM every day'
    """
    try:
        parts = cron_expr.split()

        if len(parts) != 5:
            raise ToolInputError(
                f"Invalid cron expression: '{cron_expr}' "
                f"(must be 5 parts: minute hour day month dow, got {len(parts)})"
            )

        minute, hour, day, month, dow = parts

        # Build explanation
        explanation_parts = []

        # Minute
        if minute == "*":
            minute_str = "Every minute"
        elif minute.startswith("*/"):
            interval = minute[2:]
            minute_str = f"Every {interval} minutes"
        else:
            minute_str = f"At minute {minute}"

        # Hour
        if hour == "*":
            hour_str = "every hour"
        elif hour.startswith("*/"):
            interval = hour[2:]
            hour_str = f"every {interval} hours"
        else:
            hour_str = f"at hour {hour} (24-hour format)"

        # Day
        if day == "*":
            day_str = "every day"
        else:
            day_str = f"on day {day} of the month"

        # Month
        if month == "*":
            month_str = "every month"
        else:
            month_str = f"in month {month}"

        # Day of week
        dow_map = {
            "0": "Sunday",
            "1": "Monday",
            "2": "Tuesday",
            "3": "Wednesday",
            "4": "Thursday",
            "5": "Friday",
            "6": "Saturday",
        }

        if dow == "*":
            dow_str = ""
        elif "-" in dow:
            # Range like 1-5
            dow_str = f", Monday-Friday"
        elif dow in dow_map:
            dow_str = f", {dow_map[dow]}"
        else:
            dow_str = f", day {dow} of the week"

        # Combine
        explanation = f"{minute_str} {hour_str} {day_str}{dow_str} {month_str}"
        explanation = " ".join(explanation.split())

        return f"Cron '{cron_expr}' means: {explanation}"

    except ToolInputError:
        raise
    except Exception as e:
        logger.error("Failed to explain cron: %s", e)
        return f"Error: Failed to explain cron - {e}"
