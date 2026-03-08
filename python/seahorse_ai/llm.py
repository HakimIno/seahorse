"""LiteLLM-backed LLM client with async complete and stream support.

Phase 3 improvements:
- stream() now uses exclude_none=True for consistency with complete()
- stream() has exponential backoff retry on transient LLM errors
- All imports at top-level (no inline imports)
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import litellm

from seahorse_ai.schemas import LLMConfig, Message

logger = logging.getLogger(__name__)

# Transient errors that are safe to retry
_RETRYABLE = (
    litellm.ServiceUnavailableError,
    litellm.Timeout,
    litellm.RateLimitError,
)


class LLMClient:
    """Async LLM client wrapping LiteLLM for provider-agnostic access."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    async def complete(
        self, messages: list[Message], tools: list[dict] | None = None
    ) -> dict:
        """Run a completion and return the full response message dict with retry logic."""
        return await self._complete_with_retry(messages, tools=tools)

    async def stream(
        self, messages: list[Message], retries: int = 2
    ) -> AsyncIterator[str]:
        """Stream tokens as they are generated, with exponential backoff on errors.

        Yields each text delta as it arrives. Retries up to `retries` times on
        transient errors (ServiceUnavailable, Timeout, RateLimit).
        """
        backoff = 1.0
        for attempt in range(retries + 1):
            try:
                response = await litellm.acompletion(
                    model=self._config.model,
                    messages=[m.model_dump(exclude_none=True) for m in messages],
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    stream=True,
                )
                async for chunk in response:  # type: ignore[union-attr]
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                return  # success — exit generator

            except _RETRYABLE as exc:
                if attempt < retries:
                    logger.warning(
                        "LLM stream transient error: %s. Retrying in %.1fs… (%d left)",
                        exc, backoff, retries - attempt,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    logger.error("LLM stream failed after %d retries: %s", retries, exc)
                    raise

            except Exception as exc:
                logger.error("LLM stream non-retryable error: %s", exc)
                raise

    # ── Private ────────────────────────────────────────────────────────────────

    async def _complete_with_retry(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        retries: int = 3,
        backoff: float = 1.0,
    ) -> dict:
        """Internal completion with exponential backoff retries on transient errors."""
        kwargs: dict = {
            "model": self._config.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = await litellm.acompletion(**kwargs)
            message = response.choices[0].message
            return message.model_dump(exclude_none=True)

        except _RETRYABLE as exc:
            if retries > 0:
                logger.warning(
                    "LLM transient error: %s. Retrying in %.1fs… (%d left)",
                    exc, backoff, retries,
                )
                await asyncio.sleep(backoff)
                return await self._complete_with_retry(
                    messages, tools=tools, retries=retries - 1, backoff=backoff * 2
                )
            raise

        except Exception as exc:
            logger.error("LLM non-retryable error: %s", exc)
            raise
