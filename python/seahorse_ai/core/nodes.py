"""seahorse_ai.core.nodes — Graph node helpers for Python↔Rust bridge.

This module provides:
1. **Utility functions** used by both the Python planner and Rust FFI:
   - `_prune_messages`: sliding-window context pruning (production-ready)
   - `_serialize_messages` / `_deserialize_messages`: Message ↔ dict conversion

2. **Stub graph nodes** (reason_node, action_node): these are proof-of-concept
   stubs used during early development of the Rust graph integration.
   They are NOT connected to a real LLM and should NOT be called in production.
   See planner/ for the production ReAct implementation.

Note: `time.sleep()` calls have been removed to eliminate async blocking.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import msgspec

from seahorse_ai.core.schemas import Message

if TYPE_CHECKING:
    from seahorse_ai.core.router import ModelRouter
    from seahorse_ai.tools.base import SeahorseToolRegistry

logger = logging.getLogger(__name__)


# ── Utility functions (production-ready) ─────────────────────────────────────


def _serialize_messages(messages: list[Message]) -> list[dict]:
    """Convert Message objects to plain dicts for JSON serialization."""
    return [msgspec.to_builtins(msg) for msg in messages]


def _deserialize_messages(msgs_data: list[dict]) -> list[Message]:
    """Convert plain dicts back to Message objects."""
    return [Message(**m) for m in msgs_data]


def _prune_messages(messages: list[Message], max_chars: int = 20_000) -> list[Message]:
    """Sliding-window context pruning: keep system messages, first user message, and recent history.

    Ensures no LLM context overflow by dropping the oldest non-system messages first.
    The first user message is always preserved for context anchoring.
    """
    if not messages:
        return messages

    system_msgs = [m for m in messages if m.role == "system"]
    other_msgs = [m for m in messages if m.role != "system"]

    if not other_msgs:
        return system_msgs

    first_msg = other_msgs[0]
    kept_other: list[Message] = []
    current_chars = sum(len(str(m.content or "")) for m in system_msgs) + len(
        str(first_msg.content or "")
    )

    for msg in reversed(other_msgs[1:]):
        msg_len = len(str(msg.content or ""))
        # Always keep at least the most recent message, even if it alone exceeds limit
        if current_chars + msg_len > max_chars and kept_other:
            break
        kept_other.insert(0, msg)
        current_chars += msg_len

    return system_msgs + [first_msg] + kept_other


# ── Stub graph nodes (development / Rust-bridge testing ONLY) ─────────────────
# These functions simulate LLM behavior synchronously for graph structure testing.
# Do NOT use in production — use seahorse_ai.planner.ReActPlanner instead.


# ── Production Graph Nodes (Rust Bridge) ──────────────────────────────────────


class SeahorseGraphManager:
    """Singleton manager for global resources used by the Rust-Python bridge nodes."""

    _router: ModelRouter | None = None
    _registry: SeahorseToolRegistry | None = None

    @classmethod
    def get_router(cls) -> ModelRouter:
        if cls._router is None:
            import os

            from seahorse_ai.core.router import ModelRouter

            cls._router = ModelRouter(
                worker_model=os.getenv("SEAHORSE_MODEL_WORKER", "openrouter/z-ai/glm-5-turbo"),
                thinker_model=os.getenv(
                    "SEAHORSE_MODEL_THINKER", "openrouter/google/gemini-3-flash-preview"
                ),
                strategist_model=os.getenv(
                    "SEAHORSE_MODEL_STRATEGIST", "openrouter/anthropic/claude-sonnet-4.6"
                ),
                fast_path_model=os.getenv(
                    "SEAHORSE_MODEL_FAST", "openrouter/google/gemini-3.1-flash-lite-preview"
                ),
            )
        return cls._router

    @classmethod
    def get_registry(cls) -> SeahorseToolRegistry:
        if cls._registry is None:
            from seahorse_ai.tools import make_default_registry

            cls._registry = make_default_registry()
        return cls._registry


def reason_node(state_json: str) -> str:
    """Production Reason node: Calls real LLM via ModelRouter.

    Note: This is called synchronously from Rust FFI, so we use asyncio.run
    to bridge to the async ModelRouter.
    """
    import asyncio
    import os

    state = json.loads(state_json)
    msgs_data = state.get("messages", [])
    messages = _deserialize_messages(msgs_data)
    messages = _prune_messages(messages, max_chars=30_000)

    # Ensure a system prompt exists for the autonomous loop
    has_system = any(m.role == "system" for m in messages)
    if not has_system:
        from seahorse_ai.prompts.core import build_system_prompt

        # Default to DATABASE intent for autonomous tasks to trigger deeper reasoning
        sys_prompt = build_system_prompt(intent="DATABASE")

        # Dynamic Context: List files in workspace
        workspace_dir = "workspace"
        files_hint = ""
        if os.path.exists(workspace_dir):
            files = [
                f
                for f in os.listdir(workspace_dir)
                if f.endswith((".parquet", ".csv", ".json", ".ndjson"))
            ]
            if files:
                files_hint = "\n\n## Available Workfiles (in `workspace/`):"
                for f in files:
                    files_hint += f"\n- `{f}`"

        sys_prompt += files_hint
        sys_prompt += "\n\n## Strict Rules:\n- The `python_interpreter` CANNOT import `polars` or `pandas`. Use `polars_query` for ALL data analysis."
        sys_prompt += "\n- DATA VOLUME: If a dataset is very large, ALWAYS use `df.sample(n=5000)` for Scatter plots and visualizations. Do NOT refuse to generate charts. Just sample the data."
        messages.insert(0, Message(role="system", content=sys_prompt))

    router = SeahorseGraphManager.get_router()

    # Determine tier based on history/complexity
    tier = "worker"
    if len(messages) > 3 or "สรุป" in (messages[-1].content or ""):
        tier = "thinker"

    async def _call_llm():
        registry = SeahorseGraphManager.get_registry()
        openai_tools = registry.to_openai_tools()
        return await router.complete(messages, tools=openai_tools, tier=tier)

    try:
        response_dict = asyncio.run(_call_llm())

        # Filter response_dict to only include fields allowed by the Message schema.
        # LiteLLM sometimes leaks extra fields like 'provider_specific_fields'.
        allowed_fields = {"role", "content", "tool_calls", "name", "tool_call_id"}
        filtered_response = {k: v for k, v in response_dict.items() if k in allowed_fields}

        if "role" not in filtered_response:
            filtered_response["role"] = "assistant"

        # Check for tool_calls
        has_tools = bool(filtered_response.get("tool_calls"))

        if has_tools:
            state["next_step"] = "action"
        else:
            # Final synthesis step for the autonomous loop to ensure charts are included
            # and a high-quality human-friendly response is generated.
            logger.info("nodes.reason_node: performing final synthesis via strategist")
            synth_prompt = (
                "You are the Strategist. Summarize the findings and research steps performed above. "
                "CRITICAL: If an EChart JSON was generated in the conversation history, you MUST include it "
                "VERBATIM in your response using the tag ECHART_JSON: <path_or_json>. "
                "Do NOT modify the JSON. Do NOT omit it. Keep the language professional and helpful."
            )
            messages.append(Message(role="system", content=synth_prompt))
            synth_resp = asyncio.run(router.complete(messages, tier="strategist"))
            if isinstance(synth_resp, dict):
                filtered_response["content"] = synth_resp.get(
                    "content", filtered_response.get("content", "")
                )
            else:
                filtered_response["content"] = str(synth_resp)

            state["next_step"] = "end"

        # Append to message history
        new_msg = Message(**filtered_response)
        messages.append(new_msg)
        state["messages"] = _serialize_messages(messages)

        logger.info("nodes.reason_node: tier=%s state=%s", tier, state["next_step"])
        return json.dumps(state)

    except Exception as e:
        logger.error("nodes.reason_node failed: %s", e)
        # Fallback to simple error message in state
        messages.append(Message(role="assistant", content=f"Internal Error in reason_node: {e}"))
        state["next_step"] = "end"
        state["messages"] = _serialize_messages(messages)
        return json.dumps(state)


def action_node(state_json: str) -> str:
    """Production Action node: Executes real tools via ToolRegistry."""
    import asyncio

    state = json.loads(state_json)
    msgs_data = state.get("messages", [])
    messages = _deserialize_messages(msgs_data)

    if not messages:
        return state_json

    last_msg = messages[-1]
    tool_calls = last_msg.tool_calls
    if not tool_calls:
        state["next_step"] = "reason"
        return json.dumps(state)

    registry = SeahorseGraphManager.get_registry()
    agent_id = state.get("agent_id")

    async def _execute_all():
        obs_msgs = []
        for tc in tool_calls:
            call_id = tc.get("id")
            func = tc.get("function", {})
            name = func.get("name")
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str)
                logger.info("nodes.action_node: calling tool=%s args=%s", name, args)
                result = await registry.call(name, args, agent_id=agent_id)
                logger.info("nodes.action_node: tool=%s result_len=%d", name, len(result))
                obs_msgs.append(
                    Message(role="tool", content=result, tool_call_id=call_id, name=name)
                )
            except Exception as e:
                logger.error("nodes.action_node: tool=%s failed: %s", name, e)
                obs_msgs.append(
                    Message(role="tool", content=f"Error: {e}", tool_call_id=call_id, name=name)
                )
        return obs_msgs

    try:
        new_obs = asyncio.run(_execute_all())
        messages.extend(new_obs)
        state["messages"] = _serialize_messages(messages)
        state["next_step"] = "reason"
        return json.dumps(state)
    except Exception as e:
        logger.error("nodes.action_node failed: %s", e)
        state["next_step"] = "reason"
        return json.dumps(state)
