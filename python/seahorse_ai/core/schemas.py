"""msgspec schemas for the Seahorse Agent framework."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from msgspec import Struct, field


class AgentRole(Enum):
    """Roles for different agents in the swarm."""

    COMMANDER = "commander"
    SCOUT = "scout"
    WORKER = "worker"
    ARCHITECT = "architect"
    RESEARCHER = "researcher"

    def __str__(self) -> str:
        return self.value


class Message(Struct, omit_defaults=True):
    """A single LLM conversation message."""

    role: str
    content: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class LLMConfig(Struct, omit_defaults=True):
    """LLM provider configuration with tier support."""

    model: str = field(
        default_factory=lambda: os.environ.get(
            "SEAHORSE_MODEL_WORKER", "openrouter/z-ai/glm-5-turbo"
        )
    )
    thinker_model: str = field(
        default_factory=lambda: os.environ.get(
            "SEAHORSE_MODEL_THINKER", "openrouter/google/gemini-3-flash-preview"
        )
    )
    fast_path_model: str = field(
        default_factory=lambda: os.environ.get(
            "SEAHORSE_MODEL_FAST", "openrouter/google/gemini-3.1-flash-lite-preview"
        )
    )
    extract_model: str = field(
        default_factory=lambda: os.environ.get(
            "SEAHORSE_MODEL_EXTRACT", "openrouter/google/gemini-3.1-flash-lite-preview"
        )
    )
    temperature: float = 0.7
    max_tokens: int = 4096


class AgentRequest(Struct, omit_defaults=True):
    """Incoming request to the Seahorse Agent."""

    prompt: str
    agent_id: str = "default"
    config: LLMConfig = field(default_factory=LLMConfig)
    history: list[Message] = field(default_factory=list)


class AgentResponse(Struct, omit_defaults=True):
    """Agent's final response after completing its reasoning loop."""

    content: str
    steps: int
    agent_id: str = "default"
    image_paths: list[str] | None = None
    # Monitoring fields — useful for dashboards and observability
    elapsed_ms: int = 0
    terminated: bool = False
    termination_reason: str | None = None
    is_direct: bool = False  # If True, skip final strategist synthesis
