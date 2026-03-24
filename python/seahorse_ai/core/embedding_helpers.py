"""Synchronous wrappers for async embedding functions.

Provides sync wrappers that can be called from Rust/FFI context.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def sync_generate_embedding(text: str, model: str | None = None) -> list[float]:
    """Synchronous wrapper for generating a single embedding."""
    from seahorse_ai.core.embeddings import generate_embedding_sync

    try:
        return generate_embedding_sync(text, model=model)
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        return [0.0] * 384


def sync_generate_embeddings_batch(
    texts: Sequence[str],
    model: str | None = None,
) -> list[list[float]]:
    """Synchronous wrapper for generating multiple embeddings."""
    from seahorse_ai.core.embeddings import generate_embeddings_batch_sync

    if not texts:
        return []

    try:
        return generate_embeddings_batch_sync(list(texts), model=model)
    except Exception as e:
        logger.error(f"Failed to generate batch embeddings: {e}")
        return [[0.0] * 384] * len(texts)


def sync_get_embedding_dimension(model: str | None = None) -> int:
    """Synchronous wrapper for getting embedding dimension.

    Args:
        model: Optional model name.

    Returns:
        Embedding dimension.
    """
    from seahorse_ai.core.embeddings import EMBEDDING_DIMS, DEFAULT_MODEL

    model_name = model or DEFAULT_MODEL
    return EMBEDDING_DIMS.get(model_name, 384)
