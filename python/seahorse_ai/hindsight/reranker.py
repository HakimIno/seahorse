"""seahorse_ai.hindsight.reranker — Context-Aware Precision Reranking.

Implements:
1. Contextual Reranking based on Agent Roles and Tasks.
2. Utility-Based Scoring for cold-start and long-term memory health.
"""

import logging
from typing import Any

from seahorse_ai.core.llm import get_llm
from seahorse_ai.core.schemas import AgentRole, Message

logger = logging.getLogger(__name__)

class HindsightReranker:
    def __init__(self, tier: str = "extract") -> None:
        """Initialize with a specific LLM tier."""
        self.client = get_llm(tier=tier)
        self.tier = tier
        
        # 1. Role-based keyword weights for contextual boosting
        self.role_keywords = {
            AgentRole.COMMANDER: ["risk", "decision", "outcome", "strategy", "impact"],
            AgentRole.SCOUT: ["reliability", "error", "latency", "failure", "tool", "logs"],
            AgentRole.WORKER: ["procedure", "step", "template", "how-to", "example", "code"],
            AgentRole.ARCHITECT: ["system", "design", "module", "component", "interface"],
        }

    async def rerank(
        self, 
        query: str, 
        documents: list[dict[str, Any]], 
        agent_role: AgentRole = AgentRole.WORKER,
        current_task: str = "",
        top_n: int = 5
    ) -> list[dict[str, Any]]:
        """Score and re-order documents using Agent Context and Utility Scoring."""
        if not documents:
            return []
            
        # 1. LLM-Based Relevance Scoring (Base)
        # We still use the LLM to understand semantic relevance 
        relevance_scores = await self._get_llm_relevance(query, documents)
        
        # 2. Contextual & Utility Scoring Loop
        for i, doc in enumerate(documents):
            # A. Relevance Score (LLM-provided or default)
            rel = relevance_scores.get(str(i), 5.0) / 10.0
            
            # B. Recency Score (Exponential Decay from meta)
            # Recaller already calculates 'temporal_decay'
            recency = doc.get("temporal_decay", 1.0)
            
            # C. Access Frequency (Cold start logic)
            # Default to 1.0 (new/fresh) if not tracked, or normalized count
            access_freq = doc.get("metadata", {}).get("access_count", 0)
            access_score = 1.0 / (1.0 + access_freq) # Value accessibility over over-used records
            
            # D. Confidence Score
            # Use original search score (Vector/BM25) as proxy for initial confidence
            confidence = doc.get("score", 0.5)
            
            # E. Distance Decay (New Hops-based decay)
            dist = doc.get("distance", 0)
            dist_decay = 0.8 ** dist 
            
            # F. Role Context Boost
            context_boost = self._calculate_context_boost(doc.get("text", ""), agent_role, current_task)
            
            # 3. Final Utility Formula integration
            base_score = (
                (rel * 0.4) + 
                (access_score * 0.1) + 
                (confidence * 0.1) + 
                (context_boost * 0.2)
            ) * dist_decay
            
            # G. Success & Context Bonuses (Risk 3)
            max_bonus = 0.3
            success_bonus = min(doc.get("metadata", {}).get("success_count", 0) * 0.05, max_bonus)
            # importance ranges from 1-5, center at 3
            imp = doc.get("metadata", {}).get("importance", 3)
            importance_bonus = (imp - 3) * 0.1
            
            direct_bonus = 0.5 if dist == 0 else 0.0
            total_bonus = success_bonus + direct_bonus + importance_bonus
            
            # H. Penalty & Decay Logic (Risk 1 & 2)
            # penalty_floor ensures "scars" remain even after long periods
            penalty_floor = 0.05
            raw_penalty = min(doc.get("metadata", {}).get("penalty_score", 0.0), 1.0)
            penalty_role = doc.get("metadata", {}).get("penalty_role")
            
            # Correcting double-apply recency bug:
            # Penalty decays with recency independently but respects the floor
            penalty_decayed = max(raw_penalty * recency, raw_penalty * penalty_floor)
            
            # I. Contextual Multiplier (Risk 4)
            role_factor = 1.0
            if penalty_role and penalty_role != str(agent_role).upper():
                role_factor = 0.4
                
            penalty_effective = penalty_decayed * role_factor * 0.8
            
            # 3. Final Utility Formula (Refined Separation)
            # Utility = max(0.0, (Positive Utility * Recency) - (Effective Penalty))
            positive_utility = (base_score + total_bonus) * recency
            utility = max(0.0, positive_utility - penalty_effective)
            
            doc["utility_score"] = utility
            doc["penalty_applied"] = penalty_effective
            doc["success_bonus"] = success_bonus
            doc["rerank_relevance"] = rel
            doc["context_boost"] = context_boost

        # 4. Final Sort and Trim
        reranked = sorted(
            documents, 
            key=lambda x: x.get("utility_score", 0), 
            reverse=True
        )
        
        return reranked[:top_n]

    async def _get_llm_relevance(self, query: str, documents: list[dict[str, Any]]) -> dict[str, float]:
        """Ask Tier-0 LLM for semantic relevance scores."""
        doc_list_str = ""
        for i, doc in enumerate(documents[:15]): # Limit candidate count for speed
            text = doc.get("text", "")[:300]
            doc_list_str += f"[{i}] {text}\n\n"

        prompt = f"""Rate relevance (0-10) of these memories to the query.
0 = Irrelevant, 10 = Essential.

Query: {query}

Memories:
{doc_list_str}

Return JSON: {{"0": score, "1": score, ...}}"""

        try:
            resp = await self.client.complete(
                [Message(role="user", content=prompt)], 
                tier=self.tier
            )
            import json
            content = resp.get("content", "{}").strip()
            if "```" in content:
                content = content.split("```")[1].replace("json", "").strip()
            return json.loads(content)
        except Exception as e:
            logger.warning(f"Reranker LLM Relevance check failed: {e}")
            return {}

    def _calculate_context_boost(self, text: str, role: AgentRole, task: str) -> float:
        """Heuristic-based context boosting based on keywords and role."""
        score = 0.5 # Neutral
        text_lower = text.lower()
        
        # 1. Role keywords boost
        keywords = self.role_keywords.get(role, [])
        for kw in keywords:
            if kw in text_lower:
                score += 0.1
                
        # 2. Task overlap
        if task:
            task_words = [w.lower() for w in task.split() if len(w) > 3]
            for tw in task_words:
                if tw in text_lower:
                    score += 0.05
                    
        return min(1.0, score)
