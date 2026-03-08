"""seahorse_ai.nodes — Python functions acting as Graph nodes for Rust.

These functions receive a JSON string (the graph state) and return
an updated JSON string.
"""
import json

from seahorse_ai.schemas import Message


def _serialize_messages(messages: list[Message]) -> list[dict]:
    """Convert messages to dictionaries."""
    return [msg.model_dump(exclude_none=True) for msg in messages]

def _deserialize_messages(msgs_data: list[dict]) -> list[Message]:
    """Convert dictionaries back to Message objects."""
    return [Message(**m) for m in msgs_data]

def _prune_messages(messages: list[Message], max_chars: int = 20000) -> list[Message]:
    """Sliding window strategy: keeping system, first user prompt, and recent history."""
    if not messages:
        return messages
        
    system_msgs = [m for m in messages if m.role == "system"]
    other_msgs = [m for m in messages if m.role != "system"]
    
    if not other_msgs:
        return system_msgs
        
    first_msg = other_msgs[0]
    kept_other = []
    current_chars = sum(len(str(m.content)) for m in system_msgs) + len(str(first_msg.content))
    
    for msg in reversed(other_msgs[1:]):
        # Ensure we always keep at least one recent message (unless it alone exceeds limit)
        msg_len = len(str(msg.content))
        if current_chars + msg_len > max_chars and kept_other:
            break
        kept_other.insert(0, msg)
        current_chars += msg_len
        
    return system_msgs + [first_msg] + kept_other

def reason_node(state_json: str) -> str:
    """The 'Reason' node that calls the LLM.
    
    Reads 'messages' from state. Generates next response.
    Updates 'messages' and sets 'next_step'.
    """
    state = json.loads(state_json)
    
    # Extract messages
    msgs_data = state.get("messages", [])
    messages = _deserialize_messages(msgs_data)
    
    # Prune context to prevent token starvation / LLM context limits
    messages = _prune_messages(messages, max_chars=30000)
    
    # In a real system, we'd invoke the LLM singleton here.
    # For now, we simulate an LLM response for testing the graph structure.
    import time
    time.sleep(0.1) # Simulate call
    
    # Simple logic to test graph: If last message is user, try using a tool.
    if not messages:
        messages.append(Message(role="assistant", content="How can I help you?"))
        state["next_step"] = "end"
    elif messages[-1].role == "user" and "tool" in messages[-1].content.lower():
        messages.append(Message(
            role="assistant", 
            content="", 
            tool_calls=[{"id": "call_123", "function": {"name": "dummy_tool", "arguments": "{}"}}]
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
    """The 'Action' node that executes tools.
    
    Reads 'messages', finds tool_calls, runs them, appends tool observations.
    """
    state = json.loads(state_json)
    msgs_data = state.get("messages", [])
    messages = _deserialize_messages(msgs_data)
    
    if not messages:
        return state_json
        
    last_msg = messages[-1]
    if not last_msg.tool_calls:
        # No tools to call
        state["next_step"] = "reason"
        return json.dumps(state)

    for tool_call in last_msg.tool_calls:
        call_id = tool_call.get("id")
        func = tool_call.get("function", {})
        name = func.get("name", "unknown")
        
        # Simulate tool execution
        import time
        time.sleep(0.1)
        obs = f"Executed {name} successfully."
        
        messages.append(Message(role="tool", content=obs, tool_call_id=call_id, name=name))
    
    state["messages"] = _serialize_messages(messages)
    state["next_step"] = "reason" # always return to reason after action
    
    return json.dumps(state)
