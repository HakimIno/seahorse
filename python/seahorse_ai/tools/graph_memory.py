"""seahorse_ai.tools.graph_memory — Triple-based entity relationship memory.

Powered by Neo4j. Stores Subject-Predicate-Object relationships.
"""
from __future__ import annotations

import logging
import os
from neo4j import AsyncGraphDatabase
from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

_driver = None

async def get_driver():
    global _driver
    if _driver is None:
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        auth = ("neo4j", os.environ.get("NEO4J_PASSWORD", "seahorse_password"))
        _driver = AsyncGraphDatabase.driver(uri, auth=auth)
        logger.info("graph_memory: connected to Neo4j at %s", uri)
    return _driver

@tool(
    "Store a relationship between two entities. "
    "Use this for structural facts like 'A works at B' or 'C is wife of D'. "
    "Subject and Object are entities, Predicate is the relationship type."
)
async def graph_store_triple(subject: str, predicate: str, object_entity: str) -> str:
    """Upsert two nodes and create a directed relationship between them."""
    driver = await get_driver()
    predicate = predicate.upper().replace(" ", "_")
    
    async with driver.session() as session:
        # Ensure index for performance
        await session.run("CREATE INDEX entity_name_idx IF NOT EXISTS FOR (e:Entity) ON (e.name)")
        
        await session.execute_write(
            lambda tx: tx.run(
                "MERGE (s:Entity {name: $subj}) "
                "MERGE (o:Entity {name: $obj}) "
                f"MERGE (s)-[r:{predicate}]->(o) "
                "RETURN s, r, o",
                subj=subject, obj=object_entity
            ).consume()
        )
    logger.info("graph_store: (%s)--[%s]-->(%s)", subject, predicate, object_entity)
    return f"Successfully stored graph relationship: ({subject}) {predicate} ({object_entity})"

@tool(
    "Search for entities related to a given starting entity in the knowledge graph."
)
async def graph_search_neighbors(entity: str) -> str:
    """Find all one-hop neighbors of an entity."""
    driver = await get_driver()
    
    async with driver.session() as session:
        result = await session.execute_read(
            lambda tx: tx.run(
                "MATCH (e:Entity {name: $name})-[r*1..2]-(neighbor) "
                "RETURN labels(neighbor) as labels, neighbor.name as name",
                name=entity
            ).data()
        )
    
    if not result:
        return f"No graph relationships found for entity: {entity}"
        
    lines = [f"Graph relationships (up to 2-hops) for '{entity}':"]
    seen = set()
    for res in result:
        n_name = res['name']
        if n_name == entity or n_name in seen: continue
        seen.add(n_name)
        lines.append(f"- Related to: {n_name}")
        
    return "\n".join(lines)
