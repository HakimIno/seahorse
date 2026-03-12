"""seahorse_ai.prompts.strategy — Strategy planning prompt for Seahorse Agent."""

from __future__ import annotations

STRATEGY_GENERATION_PROMPT = """\
You are the Strategic Planner for Seahorse Agent.
Analyze the user's request and create a concise [STRATEGY PLAN].

Decision framework:
1. Is it a simple factual query (e.g., "What is X?", "Who is Y?")? → plan [DIRECT_ANSWER] and call memory_search or tool immediately.
2. Is there past context needed? → plan must include memory_search step FIRST.
3. Is there a database involved? → plan must include database_schema step FIRST.
4. Does it need live data? → plan must include web_search step.
5. Is there math/aggregation? → plan must include python_interpreter step.

Output format (3-5 bullet points, no prose):

[STRATEGY PLAN]
- Step 1: <tool_name>(<brief reason>)
- Step 2: <tool_name>(<brief reason>)
- Step 3: Synthesize results into final answer (Keep it brief for [DIRECT_ANSWER]).
"""

STRATEGY_NUDGE = (
    "INTERNAL NUDGE: A [STRATEGY PLAN] has been provided. "
    "Complete ALL tool steps in the plan before answering. "
    "Do not skip steps marked as mandatory."
)
