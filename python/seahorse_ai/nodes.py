"""seahorse_ai.nodes — Graph node helpers for Python↔Rust bridge.

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

from seahorse_ai.schemas import Message

logger = logging.getLogger(__name__)


# ── Utility functions (production-ready) ─────────────────────────────────────

def _serialize_messages(messages: list[Message]) -> list[dict]:
    """Convert Message objects to plain dicts for JSON serialization."""
    return [msg.model_dump(exclude_none=True) for msg in messages]


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
    current_chars = (
        sum(len(str(m.content or "")) for m in system_msgs)
        + len(str(first_msg.content or ""))
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

def reason_node(state_json: str) -> str:
    """[STUB] Reason node for Rust graph bridge testing.

    WARNING: This is NOT connected to a real LLM. It simulates responses
    to test the graph structure only. Production code uses ReActPlanner.
    """
    logger.warning("nodes.reason_node is a stub — do NOT use in production")
    state = json.loads(state_json)
    msgs_data = state.get("messages", [])
    messages = _deserialize_messages(msgs_data)
    messages = _prune_messages(messages, max_chars=30_000)

    if not messages:
        messages.append(Message(role="assistant", content="How can I help you?"))
        state["next_step"] = "end"
    elif messages[-1].role == "user" and "tool" in (messages[-1].content or "").lower():
        messages.append(Message(
            role="assistant",
            content="",
            tool_calls=[{"id": "call_123", "function": {"name": "dummy_tool", "arguments": "{}"}}],
        ))
        state["next_step"] = "action"
    elif messages[-1].role == "tool":
        messages.append(Message(role="assistant", content="The tool succeeded."))
        state["next_step"] = "end"
    else:
        messages.append(Message(role="assistant", content="I responded without tools."))
        state["next_step"] = "end"

    state["messages"] = _serialize_messages(messages)
    return json.dumps(state)


def action_node(state_json: str) -> str:
    """[STUB] Action node for Rust graph bridge testing.

    WARNING: Tool execution is simulated. Production code uses ReActPlanner.
    """
    logger.warning("nodes.action_node is a stub — do NOT use in production")
    state = json.loads(state_json)
    msgs_data = state.get("messages", [])
    messages = _deserialize_messages(msgs_data)

    if not messages:
        return state_json

    last_msg = messages[-1]
    if not last_msg.tool_calls:
        state["next_step"] = "reason"
        return json.dumps(state)

    for tool_call in last_msg.tool_calls:
        call_id = tool_call.get("id")
        func = tool_call.get("function", {})
        name = func.get("name", "unknown")
        obs = f"[STUB] Executed {name} successfully."
        messages.append(Message(role="tool", content=obs, tool_call_id=call_id, name=name))

    state["messages"] = _serialize_messages(messages)
    state["next_step"] = "reason"
    return json.dumps(state)
