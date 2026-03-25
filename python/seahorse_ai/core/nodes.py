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
    from seahorse_ffi import PyAgentMemory

logger = logging.getLogger(__name__)


# ── Utility functions (production-ready) ─────────────────────────────────────


def _serialize_messages(messages: list[Message]) -> list[dict]:
    """Convert Message objects to plain dicts for JSON serialization."""
    return [msgspec.to_builtins(msg) for msg in messages]


def _safe_create_message(data: dict) -> Message:
    """Safely create a Message from dict, filtering out unexpected fields.

    This is DEFENSIVE against msgspec.Struct's strict validation.
    LiteLLM responses often contain extra fields (model, usage, provider, etc.)
    which cause 'Unexpected keyword argument' errors.
    """
    allowed = {"role", "content", "name", "tool_calls", "tool_call_id"}

    # Filter to only allowed fields
    filtered_data = {k: v for k, v in data.items() if k in allowed}

    # Ensure required field 'role' exists
    if "role" not in filtered_data:
        filtered_data["role"] = "assistant"

    # Handle edge case: content is None but we have other data
    if "content" not in filtered_data or filtered_data["content"] is None:
        filtered_data["content"] = ""

    return Message(**filtered_data)


def _deserialize_messages(msgs_data: list[dict]) -> list[Message]:
    """Convert plain dicts back to Message objects, ignoring unknown fields to prevent TypeErrors."""
    return [_safe_create_message(m) for m in msgs_data]


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
    _memory: PyAgentMemory | None = None

    @classmethod
    def get_memory(cls) -> PyAgentMemory:
        if cls._memory is None:
            from seahorse_ffi import PyAgentMemory
            # Initialize with default settings — in a real app, these come from config
            cls._memory = PyAgentMemory(dim=384, max_elements=100_000)
        return cls._memory
    @classmethod
    def get_router(cls) -> ModelRouter:
        if cls._router is None:
            import os

            from seahorse_ai.core.router import ModelRouter

            cls._router = ModelRouter(
                worker_model=os.getenv("SEAHORSE_MODEL_WORKER", "openrouter/google/gemini-3-flash-preview"),
                thinker_model=os.getenv(
                    "SEAHORSE_MODEL_THINKER", "openrouter/google/gemini-3-flash-preview"
                ),
                strategist_model=os.getenv(
                    "SEAHORSE_MODEL_STRATEGIST", "openrouter/google/gemini-3-flash-preview"
                ),
                fast_path_model=os.getenv(
                    "SEAHORSE_MODEL_FAST", "openrouter/google/gemini-3-flash-preview"
                ),
            )
        return cls._router

    @classmethod
    def get_registry(cls) -> SeahorseToolRegistry:
        if cls._registry is None:
            from seahorse_ai.tools import make_default_registry

            cls._registry = make_default_registry()
        return cls._registry


def reason_node(state_json: str, streamer=None) -> str:
    """Production Reason node: Calls real LLM via ModelRouter.

    Note: This is called synchronously from Rust FFI, so we use asyncio.run
    to bridge to the async ModelRouter.
    """
    import asyncio
    import os

    state = json.loads(state_json)
    msgs_data = state.get("messages", [])
    messages = _deserialize_messages(msgs_data)
    
    # Check for greeting or short prompt to optimize speed
    user_prompt = messages[-1].content or ""
    
    from seahorse_ai.prompts.intent import _is_greeting
    is_fast_intent = _is_greeting(user_prompt.lower()) or len(user_prompt.split()) <= 2

    # Ensure the core Seahorse persona and tool rules are present
    has_persona = any("Seahorse Agent" in (m.content or "") for m in messages if m.role == "system")
    if not has_persona and not is_fast_intent:
        from seahorse_ai.prompts.core import build_system_prompt
        # Force DATABASE intent to enable thorough reasoning and tool rules
        sys_prompt = build_system_prompt(intent="DATABASE")
        
        # Add high-level project architecture context (The "Claude Code" secret sauce)
        arch_hint = (
            "\n\n## Project Architecture (Seahorse Agent):\n"
            "- **Backend**: Rust (Tokio, Axum, Serde)\n"
            "- **AI Logic**: Python (LiteLLM, ReAct Planner, RAG)\n"
            "- **FFI Bridge**: PyO3 (Shared memory between Rust & Python)\n"
            "- **Crates**: `seahorse-cli` (TUI), `seahorse-core` (Logic), `seahorse-ffi` (FFI), `seahorse-router` (API Server)\n"
            "- **Knowledge**: HNSW-based vector memory for fast code retrieval."
        )
        sys_prompt += arch_hint

        # Add relevant skills context based on user query
        from seahorse_ai.core.skills import inject_skills_context
        skills_context = inject_skills_context(user_prompt, max_skills=2)
        if skills_context:
            sys_prompt += f"\n\n{skills_context}"

        # Add workspace context if available
        workspace_dir = "."
        files_hint = ""
        if os.path.exists(workspace_dir):
            try:
                files = [f for f in os.listdir(workspace_dir) if not f.startswith(".")]
                if files:
                    files_hint = "\n\n## Local Workspace Files:\n" + ", ".join(files[:20])
            except Exception:
                pass
        sys_prompt += files_hint
        
        # Insert at the beginning or after welcome
        messages.insert(0, _safe_create_message({"role": "system", "content": sys_prompt}))
    elif not has_persona and is_fast_intent:
        # Minimal persona for greetings to keep it fast
        messages.insert(0, _safe_create_message({"role": "system", "content": "You are Seahorse Agent. Keep it brief and friendly."}))

    # Get or create router
    # If Rust passed a specific model, we create a one-off ModelRouter for this request
    # to ensure consistency between Rust and Python choices.
    worker_model = state.get("worker_model")
    if worker_model:
        from seahorse_ai.core.router import ModelRouter
        router = ModelRouter(
            worker_model=worker_model,
            thinker_model=worker_model,
            strategist_model=worker_model,
            fast_path_model=worker_model,
        )
    else:
        router = SeahorseGraphManager.get_router()

    # Determine tier based on history/complexity
    tier = "fast" if is_fast_intent else "worker"
    if not is_fast_intent and (len(messages) > 3 or any(kw in user_prompt for kw in ["สรุป", "วิเคราะห์", "เพราะอะไร", "อธิบาย", "คืออะไร", "ทำไง"])):
        tier = "thinker"

    async def _call_llm_stream():
        full_content = ""
        # If we have a streamer, use streaming mode for real-time feedback
        if streamer:
            async for chunk in router.stream(messages, tier=tier):
                streamer.send(chunk)
                full_content += chunk
            return {"role": "assistant", "content": full_content}
        else:
            # Fallback to non-streaming if no streamer provided
            return await router.complete(messages, tier=tier)

    try:
        logger.info("nodes.reason_node: calling llm tier=%s streaming=%s", tier, streamer is not None)
        response_dict = asyncio.run(_call_llm_stream())

        # Filter response_dict
        allowed_fields = {"role", "content", "tool_calls", "name", "tool_call_id"}
        filtered_response = {k: v for k, v in response_dict.items() if k in allowed_fields}

        if "role" not in filtered_response:
            filtered_response["role"] = "assistant"

        # Check for tool_calls
        has_tools = bool(filtered_response.get("tool_calls"))

        if has_tools:
            state["next_step"] = "action"
        else:
            # If we don't have tool calls, and content is very short, maybe we need synthesis
            content = filtered_response.get("content", "")
            if not content or len(content) < 50:
                logger.info("nodes.reason_node: performing final synthesis via strategist (short content)")
                synth_prompt = (
                    "You are the Strategist. Provide a comprehensive answer based on the context. "
                    "CRITICAL: If an EChart JSON was generated, include it VERBATIM with ECHART_JSON: <json> tag."
                )
                messages.append(_safe_create_message({"role": "system", "content": synth_prompt}))
                # Strategist call is currently non-streaming to simplify logic
                synth_resp = asyncio.run(router.complete(messages, tier="strategist"))
                filtered_response["content"] = synth_resp.get("content", str(synth_resp))
            
            state["next_step"] = "end"

        # Append to message history
        new_msg = _safe_create_message(filtered_response)
        messages.append(new_msg)
        state["messages"] = _serialize_messages(messages)

        logger.info("nodes.reason_node: completed tier=%s next=%s content_len=%d", 
                    tier, state["next_step"], len(filtered_response.get("content", "")))
        return json.dumps(state)

    except Exception as e:
        logger.error("nodes.reason_node failed: %s", e)
        # Fallback to simple error message in state
        messages.append(_safe_create_message({"role": "assistant", "content": f"Internal Error in reason_node: {e}"}))
        state["next_step"] = "end"
        state["messages"] = _serialize_messages(messages)
        return json.dumps(state)


def action_node(state_json: str, streamer=None) -> str:
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
                    _safe_create_message({"role": "tool", "content": result, "tool_call_id": call_id, "name": name})
                )
            except Exception as e:
                logger.error("nodes.action_node: tool=%s failed: %s", name, e)
                obs_msgs.append(
                    _safe_create_message({"role": "tool", "content": f"Error: {e}", "tool_call_id": call_id, "name": name})
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
