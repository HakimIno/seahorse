"""LiteLLM-backed LLM client with async complete and stream support."""
from __future__ import annotations

from collections.abc import AsyncIterator

import litellm

from seahorse_ai.schemas import LLMConfig, Message


class LLMClient:
    """Async LLM client wrapping LiteLLM for provider-agnostic access."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    async def complete(self, messages: list[Message]) -> str:
        """Run a completion and return the full response string."""
        response = await litellm.acompletion(
            model=self._config.model,
            messages=[m.model_dump() for m in messages],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )
        content: str = response.choices[0].message.content or ""  # type: ignore[union-attr]
        return content

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        """Stream tokens as they are generated."""
        response = await litellm.acompletion(
            model=self._config.model,
            messages=[m.model_dump() for m in messages],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            stream=True,
        )
        async for chunk in response:  # type: ignore[union-attr]
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
