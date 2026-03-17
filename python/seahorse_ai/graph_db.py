"""seahorse_ai.graph_db — Neo4j Knowledge Graph Driver.

Provides a singleton driver for interacting with Neo4j to store and 
retrieve Entities and Relationships for the Hindsight memory system.
"""

from __future__ import annotations

import os
import logging
from typing import Optional
from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

def get_graph_driver() -> AsyncDriver:
    """Get or initialize the Neo4j Async Driver singleton."""
    global _driver
    if _driver is None:
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")
        
        try:
            _driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
            logger.info("Neo4j Driver initialized: %s", uri)
        except Exception as e:
            logger.error("Failed to initialize Neo4j Driver: %s", e)
            raise
            
    return _driver

async def close_graph_driver() -> None:
    """Close the driver connection."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None

class GraphManager:
    """High-level wrapper for Neo4j operations."""
    
    def __init__(self) -> None:
        self.driver = get_graph_driver()

    async def upsert_entity(self, name: str, entity_type: str = "Entity", properties: dict | None = None) -> None:
        """Create or update an Entity node."""
        properties = properties or {}
        query = (
            f"MERGE (e:{entity_type} {{name: $name}}) "
            "SET e += $properties "
            "RETURN e"
        )
        async with self.driver.session() as session:
            await session.run(query, name=name, properties=properties)

    async def add_relationship(
        self, 
        subj_name: str, 
        obj_name: str, 
        predicate: str, 
        subj_type: str = "Entity", 
        obj_type: str = "Entity",
        properties: dict | None = None
    ) -> None:
        """Create a relationship between two entities."""
        properties = properties or {}
        # Dynamic relationship types in Cypher require a bit of care with f-strings or APOC
        # For simplicity, we use a generic RELATIONSHIP type with a 'type' property if needed,
        # but standard Hindsight usually uses the predicate as the relationship type.
        # Sanitizing predicate for use as relationship type:
        rel_type = predicate.upper().replace(" ", "_").replace("-", "_")
        
        query = (
            f"MERGE (s:{subj_type} {{name: $subj_name}}) "
            f"MERGE (o:{obj_type} {{name: $obj_name}}) "
            f"MERGE (s)-[r:{rel_type}]->(o) "
            "SET r += $properties"
        )
        async with self.driver.session() as session:
            await session.run(
                query, 
                subj_name=subj_name, 
                obj_name=obj_name, 
                properties=properties
            )

    async def link_record_to_entity(self, record_id: str, entity_name: str, entity_type: str = "Entity") -> None:
        """Link a HindsightRecord (represented by its ID) to an Entity it mentions."""
        query = (
            "MERGE (r:HindsightRecord {id: $record_id}) "
            f"MERGE (e:{entity_type} {{name: $entity_name}}) "
            "MERGE (r)-[:MENTIONS]->(e)"
        )
        async with self.driver.session() as session:
            await session.run(query, record_id=record_id, entity_name=entity_name)

    async def get_connected_entities(self, entity_name: str, hops: int = 1) -> list[dict]:
        """Find entities connected to a starting node."""
        query = (
            f"MATCH (e {{name: $name}})-[r*1..{hops}]-(neighbor) "
            "RETURN neighbor.name as name, labels(neighbor)[0] as type, properties(neighbor) as props"
        )
        async with self.driver.session() as session:
            result = await session.run(query, name=entity_name)
            return [record.data() async for record in result]

    async def get_records_by_entity(self, entity_name: str) -> list[str]:
        """Find HindsightRecord IDs linked to an entity."""
        query = (
            "MATCH (r:HindsightRecord)-[:MENTIONS]->(e {name: $name}) "
            "RETURN r.id as id"
        )
        async with self.driver.session() as session:
            result = await session.run(query, name=entity_name)
            return [record["id"] async for record in result]

    async def get_records_by_path(self, entity_name: str, hops: int = 2) -> list[str]:
        """Find Record IDs connected through a chain of entities (multi-hop).
        Example: (Entity A)-[]-(Entity B)-[:MENTIONS]-(Record)
        """
        query = (
            f"MATCH (e {{name: $name}})-[*1..{hops}]-(neighbor:Entity)<-[:MENTIONS]-(r:HindsightRecord) "
            "RETURN DISTINCT r.id as id"
        )
        async with self.driver.session() as session:
            result = await session.run(query, name=entity_name)
            return [record["id"] async for record in result]

    async def clear(self) -> None:
        """Wipe the entire database (DANGER: use only for testing)."""
        async with self.driver.session() as session:
            await session.run("MATCH (n) DETACH DELETE n")
            logger.info("Neo4j: entire database cleared")
