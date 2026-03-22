"""seahorse_ai.tools.internal.graph_memory — Triple-based entity relationship memory.

Powered by Neo4j. Stores Subject-Predicate-Object relationships.
"""

from __future__ import annotations

import logging

from seahorse_ai.engines.graph_db import GraphManager
from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

_manager = None


def get_manager() -> GraphManager:
    global _manager
    if _manager is None:
        _manager = GraphManager()
    return _manager


@tool(
    "Store a relationship between two entities. "
    "Use this for structural facts like 'A works at B' or 'C is wife of D'. "
    "Subject and Object are entities, Predicate is the relationship type."
)
async def graph_store_triple(subject: str, predicate: str, object_entity: str) -> str:
    """Upsert two nodes and create a directed relationship between them."""
    manager = get_manager()
    await manager.add_relationship(subject, object_entity, predicate)

    logger.info("graph_store: (%s)--[%s]-->(%s)", subject, predicate, object_entity)
    return f"Successfully stored graph relationship: ({subject}) {predicate} ({object_entity})"


@tool("Search for entities related to a given starting entity in the knowledge graph.")
async def graph_search_neighbors(entity: str) -> str:
    """Find all one-hop neighbors of an entity."""
    manager = get_manager()
    result = await manager.get_connected_entities(entity, hops=2)

    if not result:
        return f"No graph relationships found for entity: {entity}"

    lines = [f"Graph relationships (up to 2-hops) for '{entity}':"]
    seen = set()
    for res in result:
        n_name = res["name"]
        if n_name == entity or n_name in seen:
            continue
        seen.add(n_name)
        lines.append(f"- Related to: {n_name} ({res.get('type', 'Entity')})")

    return "\n".join(lines)
