import logging
import os
from typing import Any
from seahorse_ai.tools import tool
from seahorse_ai.rag import get_pipeline

logger = logging.getLogger(__name__)

@tool(
    "Store a fact or information into the agent's long-term memory. "
    "Use this for important facts, user preferences, or project details "
    "that should be remembered across conversations."
)
async def memory_store(text: str, importance: int = 3, agent_id: str | None = None) -> str:
    """Store information using Hindsight Retain logic."""
    from seahorse_ai.hindsight import HindsightRetainer
    
    pipeline = get_pipeline()
    retainer = HindsightRetainer(pipeline)
    
    records = await retainer.retain(text, agent_id=agent_id)
    
    if not records:
        await pipeline.store(text, agent_id=agent_id, importance=importance)
        return "Stored in memory (simple mode)."

    mode = records[0].metadata.get("extraction_mode", "unknown")
    return f"Stored {len(records)} Hindsight records using {mode} extraction. ✅"


@tool(
    "Search the agent's memory for information. Use this to recall facts, "
    "past discussions, or context that may have been forgotten."
)
async def memory_search(
    query: str, 
    k: int = 10, 
    agent_id: str | None = None, 
    min_similarity: float = 0.1, 
    top_k: int | None = None,
    category: str | None = None,
) -> list[dict] | str:
    """Search memory using Hindsight Recall (Hybrid Parallel Retrieval)."""
    from seahorse_ai.hindsight import HindsightRecaller
    
    if top_k is not None:
        k = top_k
    k = int(k)
    
    pipeline = get_pipeline()
    recaller = HindsightRecaller(pipeline)
    
    results = await recaller.recall(query, agent_id=agent_id, k=k)

    if not results:
        return "Memory is empty or no match found."

    if category:
        results = [r for r in results if r.get("category") == category.upper()]

    return results


@tool(
    "Perform deep memory reflection to consolidate experiences into durable "
    "Mental Models. Use this periodically or when a high-level summary "
    "is needed to understand a complex situation over time."
)
async def memory_reflect(agent_id: str | None = None, k: int = 50) -> str:
    """Run the Hindsight Reflector to consolidate experiences into Mental Models."""
    from seahorse_ai.hindsight import HindsightReflector
    
    pipeline = get_pipeline()
    reflector = HindsightReflector(pipeline)
    
    models = await reflector.reflect(agent_id=agent_id, k_experiences=k)
    
    if models:
        return f"Reflection completed: Synthesized {len(models)} new Mental Models (insights). ✅"
    return "Reflection complete. No new insights found at this time."


@tool(
    "Delete a specific record from long-term memory by its ID. "
    "Use this to remove incorrect or outdated facts."
)
async def memory_delete(doc_id: str | int, agent_id: str | None = None) -> str:
    """Delete a memory record by ID."""
    pipeline = get_pipeline()
    await pipeline.delete_by_id(doc_id)
    return f"Deleted memory record with ID {doc_id}."

@tool(
    "Clear all long-term memory records for the current agent. "
    "CRITICAL: This action cannot be undone."
)
async def memory_clear(agent_id: str | None = None) -> str:
    """Clear all memories for an agent."""
    pipeline = get_pipeline()
    await pipeline.clear()
    return "All memories cleared."
