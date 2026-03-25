"""Auto-Pilot Mode — autonomous multi-step plan execution.

Enables Seahorse to break down complex tasks into steps and execute
them autonomously using available tools.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from seahorse_ai.core.llm import get_llm
from seahorse_ai.core.skills import get_skill_loader

logger = logging.getLogger(__name__)


class AutoPilot:
    """Multi-step autonomous execution mode."""

    def __init__(self):
        """Initialize the auto-pilot with tool registry and skill loader."""
        # Lazy import to avoid circular dependency
        from seahorse_ai.tools import make_default_registry

        self.registry = make_default_registry()
        self.skill_loader = get_skill_loader()
        self.available_tools = list(self.registry._tools.keys())

    async def execute_plan(
        self,
        user_goal: str,
        agent_id: str | None = None,
        max_steps: int = 10,
    ) -> str:
        """Execute a multi-step plan autonomously.

        Breaks down the user's goal into concrete steps and executes them
        using available tools.

        Args:
            user_goal: The user's request or goal
            agent_id: Optional agent ID for tool execution
            max_steps: Maximum number of steps to execute (default: 10)

        Returns:
            Execution results with step-by-step breakdown

        Examples:
            >>> pilot = AutoPilot()
            >>> await pilot.execute_plan("Index the project and find all Python files")
            'Step 1: Index project...
             Step 2: Find Python files...
             Completed 2 steps'
        """
        logger.info("AutoPilot: Starting execution for goal: %s", user_goal)

        # Step 1: Load relevant skills
        skills_context = self.skill_loader.build_context(user_goal, max_skills=2)

        # Step 2: Generate plan using LLM
        plan = await self._generate_plan(user_goal, skills_context)

        if plan is None:
            return "Failed to generate a plan. The goal may be too vague or unsafe."

        logger.info("AutoPilot: Generated %d steps", len(plan))

        # Step 3: Execute each step
        results = []
        completed_steps = 0

        for i, step in enumerate(plan[:max_steps], 1):
            step_num = step.get("step", i)
            tool_name = step.get("tool")
            args = step.get("args", {})
            reason = step.get("reason", "")

            results.append(f"### Step {step_num}: {reason}")
            logger.info(
                "AutoPilot: Executing step %s: %s %s",
                step_num,
                tool_name,
                args
            )

            try:
                result = await self.registry.call(tool_name, args, agent_id=agent_id)

                # Truncate long results
                if len(result) > 800:
                    result = result[:800] + "\n\n... (truncated, output too long)"

                results.append(f"✅ **Result:**\n```\n{result}\n```")
                completed_steps += 1

            except Exception as e:
                error_msg = f"❌ **Error:** {e}"
                results.append(error_msg)
                logger.error("AutoPilot: Step %s failed: %s", step_num, e)

                # Stop on critical errors
                if self._is_critical_error(str(e)):
                    results.append(f"\n⚠️ **Stopping due to critical error at step {step_num}**")
                    break

        # Summary
        results.append("\n---\n")
        results.append(f"### Summary: Completed {completed_steps}/{len(plan)} steps")

        return "\n\n".join(results)

    async def _generate_plan(
        self,
        user_goal: str,
        skills_context: str,
    ) -> list[dict[str, Any]] | None:
        """Generate a multi-step plan using the LLM.

        Args:
            user_goal: The user's goal
            skills_context: Relevant domain knowledge

        Returns:
            List of step dictionaries, or None if plan generation failed
        """
        llm = get_llm("thinker")

        # Build available tools list (grouped by category for clarity)
        tools_summary = self._get_tools_summary()

        plan_prompt = f"""You are an AI assistant that breaks down tasks into concrete steps.

**User Goal:** {user_goal}

**Available Tools:**
{tools_summary}

**Relevant Domain Knowledge:**
{skills_context}

**Instructions:**
1. Break down the goal into 3-7 concrete steps
2. Each step MUST use one of the available tools listed above
3. Be specific with file paths and parameters
4. Think step by step - don't skip intermediate steps
5. Prioritize information gathering (index, glob, grep) before making changes
6. Return ONLY valid JSON - no markdown formatting

**Output Format (JSON only):**
```json
[
  {{
    "step": 1,
    "tool": "tool_name",
    "args": {{"param": "value"}},
    "reason": "why this step is needed"
  }},
  {{
    "step": 2,
    "tool": "tool_name",
    "args": {{"param": "value"}},
    "reason": "why this step is needed"
  }}
]
```

**Important:**
- Only use tools from the available list
- File paths should be relative (no absolute paths)
- Args must be valid JSON (strings in double quotes)
- Keep each step focused and achievable
- Include information gathering steps first

Generate the plan now (JSON only, no markdown):"""

        try:
            response = await llm.complete([{"role": "user", "content": plan_prompt}])
            content = response.get("content", "{}")

            # Extract JSON from response (handle markdown code blocks)
            content = self._extract_json(content)

            # Parse JSON
            plan = json.loads(content)

            # Validate plan
            if not isinstance(plan, list):
                logger.error("AutoPilot: Plan is not a list")
                return None

            if len(plan) == 0:
                logger.error("AutoPilot: Plan is empty")
                return None

            # Validate each step
            for step in plan:
                if not isinstance(step, dict):
                    logger.error("AutoPilot: Step is not a dict")
                    return None

                if "tool" not in step or "args" not in step:
                    logger.error("AutoPilot: Step missing tool or args")
                    return None

                if step["tool"] not in self.available_tools:
                    logger.error("AutoPilot: Unknown tool: %s", step["tool"])
                    return None

            logger.info("AutoPilot: Generated valid plan with %d steps", len(plan))
            return plan

        except json.JSONDecodeError as e:
            logger.error("AutoPilot: Failed to parse plan JSON: %s", e)
            logger.error("AutoPilot: Content was: %s", content[:500])
            return None

        except Exception as e:
            logger.error("AutoPilot: Failed to generate plan: %s", e)
            return None

    def _get_tools_summary(self) -> str:
        """Get a formatted summary of available tools.

        Returns:
            Formatted string with tool categories
        """
        categories = {
            "File Operations": [
                "read_file", "write_file", "edit_file", "list_files",
                "glob_files", "grep_files", "find_symbol"
            ],
            "Terminal & Git": [
                "bash_command", "git_status", "git_commit", "git_diff",
                "git_log", "system_info"
            ],
            "Task Management": [
                "task_create", "task_list", "task_update", "task_get_available"
            ],
            "Analysis & Indexing": [
                "index_project", "visualize_project", "memory_search",
                "count_files_by_type"
            ],
        }

        summary = []

        for category, tools in categories.items():
            available = [t for t in tools if t in self.available_tools]
            if available:
                summary.append(f"**{category}:** {', '.join(available)}")

        return "\n".join(summary)

    def _extract_json(self, content: str) -> str:
        """Extract JSON from content, handling markdown code blocks.

        Args:
            content: Content that may contain JSON in markdown blocks

        Returns:
            Extracted JSON string
        """
        # Remove markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        # Remove any remaining markdown formatting
        content = content.strip()
        content = content.lstrip("`").rstrip("`")

        return content

    def _is_critical_error(self, error: str) -> bool:
        """Check if an error is critical enough to stop execution.

        Args:
            error: Error message

        Returns:
            True if execution should stop
        """
        critical_patterns = [
            "SYSTEM_CRASH",
            "permission denied",
            "file not found",
            "no such file",
            "command not found",
        ]

        error_lower = error.lower()

        return any(pattern.lower() in error_lower for pattern in critical_patterns)


async def execute_autopilot(
    user_goal: str,
    agent_id: str | None = None,
    max_steps: int = 10,
) -> str:
    """Convenience function to execute auto-pilot mode.

    Args:
        user_goal: The user's request or goal
        agent_id: Optional agent ID
        max_steps: Maximum number of steps

    Returns:
        Execution results

    Examples:
        >>> result = await execute_autopilot(
        ...     "Find all Python test files and count them"
        ... )
        >>> print(result)
    """
    pilot = AutoPilot()
    return await pilot.execute_plan(user_goal, agent_id, max_steps)


# Tool wrapper for auto-pilot
from seahorse_ai.tools.base import tool


@tool(
    "Execute a complex multi-step task autonomously",
    risk_level="medium"
)
async def autopilot_execute(
    goal: str,
    max_steps: int = 10,
) -> str:
    """Execute a complex task by breaking it into steps automatically.

    This tool uses AI to plan and execute multi-step workflows autonomously.
    Useful for complex tasks that require multiple tool calls.

    Args:
        goal: Description of what you want to accomplish
        max_steps: Maximum number of steps to execute (default: 10)

    Returns:
        Step-by-step execution results

    Examples:
        >>> await autopilot_execute("Analyze the project structure")
        'Step 1: Index project...
         Step 2: Visualize...
         Summary: Completed 2/2 steps'

        >>> await autopilot_execute("Find all test files and run them")
        'Step 1: Find test files...
         Step 2: Run tests...
         Summary: Completed 2/2 steps'
    """
    pilot = AutoPilot()
    return await pilot.execute_plan(goal, max_steps=max_steps)


@tool("List available autopilot capabilities")
async def autopilot_capabilities() -> str:
    """List the capabilities of the auto-pilot mode.

    Returns information about what types of tasks auto-pilot can handle.

    Examples:
        >>> await autopilot_capabilities()
        'Auto-pilot can handle:
         - Project analysis and indexing
         - File search and navigation
         - Code refactoring
         ...'
    """
    capabilities = """## Auto-Pilot Capabilities

The auto-pilot mode can autonomously execute complex multi-step tasks:

### 🔍 Analysis & Discovery
- Index and analyze project structure
- Find files by type or pattern
- Search code for specific patterns
- Generate project visualizations

### ✏️ Code Operations
- Refactor code across multiple files
- Apply consistent changes to multiple files
- Search and replace patterns
- Create or update files

### 🧪 Testing & Quality
- Find and run test files
- Check test coverage
- Identify code quality issues

### 📊 Reporting
- Generate project statistics
- Create file summaries
- Analyze dependencies

### 🎯 How It Works
1. Understand your goal
2. Load relevant domain knowledge
3. Break down into 3-7 concrete steps
4. Execute each step using available tools
5. Return detailed results

### 💡 Example Goals
- "Index the project and find all Python files"
- "Search for TODO comments across the codebase"
- "Refactor all uses of deprecated function X"
- "Generate a visualization of the project structure"
- "Find test files and count test cases"

Simply describe what you want to accomplish, and auto-pilot will plan and execute it!
"""

    return capabilities
