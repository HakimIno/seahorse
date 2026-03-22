import asyncio
import logging
from datetime import UTC, datetime

from seahorse_ai.engines.rag.rag import get_pipeline
from seahorse_ai.tools import tool

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


_feedback_lock = asyncio.Lock()

@tool(
    "Mark a memory as misleading, incorrect, or low-quality. "
    "Use this when an agent makes a mistake based on a specific memory. "
    "Multiple reports from distinct roles increase the penalty (Consensus). "
    "The memory will be downranked in future retrievals."
)
async def memory_feedback(doc_id: str | int, penalty: float = 0.5, reason: str = "", role: str | None = None) -> str:
    """Apply a penalty score using Consensus Logic with Audit Trail and Role-Uniqueness."""
    async with _feedback_lock:
        pipeline = get_pipeline()
        role_name = (role or "UNKNOWN").upper()
        
        # 1. Retrieve existing memory
        existing = await pipeline.retrieve(doc_id) if hasattr(pipeline, "retrieve") else None
        
        history = []
        if existing and "metadata" in existing:
            history = existing["metadata"].get("penalty_history", [])
            
        # 2. Add new feedback entry (Audit Trail)
        new_entry = {
            "role": role_name,
            "penalty": float(penalty),
            "reason": reason,
            "at": datetime.now(UTC).isoformat()
        }
        history.append(new_entry)
        
        # 3. Calculate Consensus (Quorum) based on UNIQUE ROLES
        # We use the LATEST reported penalty from each role to allow "changing minds"
        role_opinions = {}
        for entry in history:
            r = entry["role"]
            if r == "UNKNOWN":
                continue
            role_opinions[r] = entry["penalty"]
        
        unique_roles = list(role_opinions.keys())
        quorum_count = len(unique_roles)
        
        # Tiered capping (same as before)
        if quorum_count <= 1:
            max_allowed = 0.4
        elif quorum_count == 2:
            max_allowed = 0.7
        else:
            max_allowed = 1.0
            
        # Final score is the average of latest role opinions, capped by quorum tier
        if role_opinions:
            raw_consensus = sum(role_opinions.values()) / len(role_opinions)
            final_penalty = max(0.0, min(raw_consensus, max_allowed))
        else:
            # Fallback for UNKNOWN role
            final_penalty = max(0.0, min(float(penalty), 0.2)) 
        
        # 4. Update metadata
        metadata = {
            "penalty_score": round(final_penalty, 4),
            "quorum_count": quorum_count,
            "penalty_at": new_entry["at"],
            "penalty_role": role_name,
            "penalty_history": history[-20:] # Keep history for audit
        }
        
        if hasattr(pipeline, "update_metadata"):
            await pipeline.update_metadata(doc_id, metadata)
            status = "Consensus Verified ✅"
        else:
            status = "Metadata update not supported ⚠️"
            
        logger.info("memory_feedback: doc_id=%s quorum=%d penalty=%s", doc_id, quorum_count, final_penalty)
        return f"Applied penalty {final_penalty} (Quorum: {quorum_count} roles) to record {doc_id}. {status}"


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
