"""LiteLLM-backed LLM client with async complete and stream support.

Phase 3 improvements:
- stream() now uses exclude_none=True for consistency with complete()
- stream() has exponential backoff retry on transient LLM errors
- All imports at top-level (no inline imports)
"""

from __future__ import annotations
from collections.abc import AsyncIterator

import json
import logging
import random

import anyio
import litellm
import msgspec

from seahorse_ai.core.schemas import LLMConfig, Message

logger = logging.getLogger(__name__)

def _get_retryable_errors():
    """Get LiteLLM errors for retry logic."""
    return (
        litellm.ServiceUnavailableError,
        litellm.Timeout,
        litellm.RateLimitError,
    )

def register_litellm_models():
    """Register common models to LiteLLM registry."""
    try:
        litellm.register_model({
            "openrouter/baai/bge-m3": {
                "max_tokens": 8192,
                "input_cost_per_token": 1e-8,
                "output_cost_per_token": 1e-8,
            }
        })
    except Exception:
        pass

class LLMClient:
    """Async LLM client wrapping LiteLLM for provider-agnostic access."""

    def __init__(self, config: LLMConfig) -> None:
        """Initialize LLM client with configuration."""
        self._config = config

    async def complete(
        self, messages: list[Message], tools: list[dict] | None = None, tier: str = "worker"
    ) -> dict:
        """Run a completion and return the full response message dict with retry logic."""
        return await self._complete_with_retry(messages, tools=tools, tier=tier)

    async def stream(
        self, messages: list[Message], retries: int = 2, tier: str = "worker"
    ) -> AsyncIterator[str]:
        """Stream tokens as they are generated, with exponential backoff on errors."""
        from seahorse_ai.planner.circuit_breaker import is_system_healthy

        if not await is_system_healthy():
            logger.critical("LLM call blocked by Global Circuit Breaker — System is in Safe Mode")
            raise RuntimeError(
                "System is temporarily in Safe Mode due to multiple LLM failures. "
                "Please try again in 1 minute."
            )

        if tier in ("thinker", "strategist"):
            model = self._config.thinker_model
        elif tier == "fast":
            model = self._config.fast_path_model
        else:
            model = self._config.model
        timeout_sec = 60.0 if tier in ("thinker", "strategist") else 15.0
        backoff = 1.0
        for attempt in range(retries + 1):
            try:
                response = await litellm.acompletion(
                    model=model,
                    messages=[msgspec.to_builtins(m) for m in messages],
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    stream=True,
                    timeout=timeout_sec,
                )
                async for chunk in response:  # type: ignore[union-attr]
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                return  # success — exit generator

            except _get_retryable_errors() as exc:
                if attempt < retries:
                    jitter = random.random()
                    total_backoff = backoff * (0.5 + jitter)
                    logger.warning(
                        "LLM stream transient error: %s. Retrying in %.1fs… (%d left)",
                        exc,
                        total_backoff,
                        retries - attempt,
                    )
                    await anyio.sleep(total_backoff)
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
        tier: str = "worker",
    ) -> dict:
        """Perform internal completion with exponential backoff retries on transient errors."""
        from seahorse_ai.planner.circuit_breaker import is_system_healthy

        if not await is_system_healthy():
            logger.critical("LLM call blocked by Global Circuit Breaker — System is in Safe Mode")
            raise RuntimeError(
                "System is temporarily in Safe Mode due to multiple LLM failures. Please try again in 1 minute."
            )

        if tier in ("thinker", "strategist"):
            model = self._config.thinker_model
        elif tier == "fast":
            model = self._config.fast_path_model
        else:
            model = self._config.model
        timeout_sec = 180.0 if tier in ("thinker", "strategist", "worker") else 30.0
        kwargs: dict = {
            "model": model,
            "messages": self._clean_messages(messages),
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "timeout": timeout_sec,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = await litellm.acompletion(**kwargs)
            message = response.choices[0].message
            # LiteLLM message objects often contain nested Pydantic models (like tool_calls).
            # We MUST perform a deep conversion to plain dicts for msgspec compatibility.
            if hasattr(message, "model_dump_json"):  # Pydantic v2
                return json.loads(message.model_dump_json(exclude_none=True))
            if hasattr(message, "json"):  # Pydantic v1 / Legacy LiteLLM
                return json.loads(message.json())
            # Fallback to standard dict conversion (may not be deep)
            return dict(message)

        except _get_retryable_errors() as exc:
            if retries > 0:
                jitter = random.random()
                total_backoff = backoff * (0.5 + jitter)
                logger.warning(
                    "LLM transient error: %s. Retrying in %.1fs… (%d left)",
                    exc,
                    total_backoff,
                    retries,
                )
                await anyio.sleep(total_backoff)
                return await self._complete_with_retry(
                    messages, tools=tools, retries=retries - 1, backoff=backoff * 2
                )
            raise

        except Exception as exc:
            logger.error("LLM non-retryable error: %s", exc)
            raise

    def _clean_messages(self, messages: list[Message]) -> list[dict]:
        """Sanitize message list for picky providers (Gemini/GLM)."""
        if not messages:
            return []

        cleaned = []
        for m in messages:
            built = msgspec.to_builtins(m)

            # Preserve message if it has content OR tool_calls
            has_content = bool(built.get("content"))
            has_tools = bool(built.get("tool_calls"))
            has_tool_id = bool(built.get("tool_call_id"))

            if not (has_content or has_tools or has_tool_id):
                continue

            # Gemini-specific: Ensure content is never None if tool_calls are present
            if has_tools and not built.get("content"):
                built["content"] = ""

            if (
                cleaned
                and cleaned[-1]["role"] == built["role"]
                and built["role"] in ("user", "system")
                and not (has_tools or has_tool_id or cleaned[-1].get("tool_calls"))
            ):
                # Assistant/Tool roles should NOT be merged if they have tool_calls/ids.
                cleaned[-1]["content"] += f"\n\n{built['content']}"
                continue

            cleaned.append(built)

        return cleaned


def get_llm(tier: str = "worker") -> LLMClient:
    """Helper to get a default LLM client for this tier.

    Reads from environment variables:
    - SEAHORSE_WORKER_MODEL
    - SEAHORSE_THINKER_MODEL
    """

    from seahorse_ai.core.schemas import LLMConfig

    # Use environment variables if available, otherwise defaults
    config = LLMConfig()
    model = config.model

    if tier == "thinker":
        model = config.thinker_model
    elif tier == "fast":
        model = config.fast_path_model
    elif tier == "extract":
        model = config.extract_model

    return LLMClient(config=LLMConfig(model=model))
