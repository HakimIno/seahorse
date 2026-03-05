"""Pydantic v2 schemas for the Seahorse Agent framework."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single LLM conversation message."""

    role: str
    content: str


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    model: str = "openrouter/anthropic/claude-3.5-sonnet"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=128_000)


class AgentRequest(BaseModel):
    """Incoming request to the Seahorse Agent."""

    prompt: str
    agent_id: str = "default"
    config: LLMConfig = Field(default_factory=LLMConfig)


class AgentResponse(BaseModel):
    """Agent's final response after completing its reasoning loop."""

    content: str
    steps: int
    agent_id: str = "default"
