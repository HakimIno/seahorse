"""seahorse_ai.hindsight.models — Data schemas for Hindsight.

Defines the structure of World facts, Experiences, and Mental Models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
import uuid
import json
from msgspec import Struct, field, json as msgjson

class MemoryCategory(Enum):
    WORLD = "WORLD"
    EXPERIENCE = "EXPERIENCE"
    MENTAL_MODEL = "MENTAL_MODEL"
    
    def __str__(self):
        return self.value

class Entity(Struct, omit_defaults=True):
    name: str
    type: str = "GENERIC"
    metadata: dict[str, Any] = field(default_factory=dict)

class Relation(Struct, omit_defaults=True):
    subject: str
    predicate: str
    object: str
    metadata: dict[str, Any] = field(default_factory=dict)

class TemporalContext(Struct, omit_defaults=True):
    timestamp: datetime = field(default_factory=datetime.now)
    duration_minutes: int | None = None
    relative_description: str | None = None

class HindsightRecord(Struct, omit_defaults=True):
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: str = ""
    category: MemoryCategory = MemoryCategory.EXPERIENCE
    importance: int = 3
    
    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    temporal: TemporalContext = field(default_factory=TemporalContext)
    
    metadata: dict[str, Any] = field(default_factory=dict)
    agent_id: str | None = None
    
    def to_qdrant_payload(self) -> dict[str, Any]:
        """Convert struct to dict for Qdrant payload."""
        data = json.loads(msgjson.encode(self))
        # Ensure category is stored as string
        if isinstance(data.get("category"), str):
            pass 
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HindsightRecord:
        """Hydrate from dictionary."""
        return msgjson.decode(json.dumps(data), type=cls)
