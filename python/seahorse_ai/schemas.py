"""Pydantic v2 schemas for the Seahorse Agent framework."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single LLM conversation message."""

    role: str
    content: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, object]] | None = None
    tool_call_id: str | None = None


import os


class LLMConfig(BaseModel):
    """LLM provider configuration with tier support."""

    model: str = Field(
        default_factory=lambda: os.environ.get(
            "SEAHORSE_MODEL_WORKER", "openrouter/google/gemini-3-flash-preview"
        )
    )
    thinker_model: str = Field(
        default_factory=lambda: os.environ.get(
            "SEAHORSE_MODEL_THINKER", "openrouter/google/gemini-3-flash-preview"
        )
    )
    fast_path_model: str = Field(
        default_factory=lambda: os.environ.get(
            "SEAHORSE_FAST_PATH_MODEL", "openrouter/google/gemini-3.1-flash-lite-preview"
        )
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=128_000)


class AgentRequest(BaseModel):
    """Incoming request to the Seahorse Agent."""

    prompt: str
    agent_id: str = "default"
    config: LLMConfig = Field(default_factory=LLMConfig)
    history: list[Message] = Field(default_factory=list)


class AgentResponse(BaseModel):
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
