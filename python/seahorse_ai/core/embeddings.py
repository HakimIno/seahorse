"""Embedding generation using LiteLLM with multiple model support.

Supports:
- OpenAI: text-embedding-3-small, text-embedding-3-large
- Cohere: embed-english-v3.0, embed-multilingual-v3.0
- BGE-M3 (via local/OpenRouter)
- Sentence Transformers (local)
"""

from __future__ import annotations

import logging
import os
from typing import Literal



logger = logging.getLogger(__name__)

# Model configurations
EmbeddingModel = Literal[
    "openai/text-embedding-3-small",  # 1536 dim, fast, cheap
    "openai/text-embedding-3-large",  # 3072 dim, best quality
    "cohere/embed-english-v3.0",      # 1024 dim
    "cohere/embed-multilingual-v3.0", # 1024 dim
    "baai/bge-m3",                    # 1024 dim, multilingual
    "sentence-transformers/all-MiniLM-L6-v2",  # 384 dim, local
]

# Dimension mapping
EMBEDDING_DIMS: dict[str, int] = {
    "openai/text-embedding-3-small": 1536,
    "openai/text-embedding-3-large": 3072,
    "cohere/embed-english-v3.0": 1024,
    "cohere/embed-multilingual-v3.0": 1024,
    "baai/bge-m3": 1024,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
}

# Default model from env or fallback
DEFAULT_MODEL: EmbeddingModel = os.getenv(
    "SEAHORSE_EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2"
)  # type: ignore


class EmbeddingClient:
    """Async embedding generation client.

    Usage:
        client = EmbeddingClient()
        embedding = await client.generate("Hello world")
        embeddings = await client.generate_batch(["doc1", "doc2"])
    """

    def __init__(
        self,
        model: EmbeddingModel | None = None,
        batch_size: int = 100,
    ) -> None:
        """Initialize embedding client.

        Args:
            model: Embedding model to use (default from env).
            batch_size: Number of texts to embed in one request.
        """
        self._model = model or DEFAULT_MODEL
        self._batch_size = batch_size
        self._dim = EMBEDDING_DIMS.get(self._model, 384)

        logger.info(f"Initialized EmbeddingClient with model={self._model}, dim={self._dim}")

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dim

    async def generate(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Input text to embed.

        Returns:
            Embedding vector as list of floats.
        """
        embeddings = await self.generate_batch([text])
        return embeddings[0]

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts (Async)."""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            logger.debug(f"Generating embeddings for batch {i//self._batch_size + 1} (async)")

            try:
                import litellm
                response = await litellm.aembedding(
                    model=self._model,
                    input=batch,
                )
                if hasattr(response, "data"):
                    embeddings_data = response.data
                else:
                    embeddings_data = response.get("data", [])

                batch_embeddings = sorted(
                    [item for item in embeddings_data],
                    key=lambda x: getattr(x, "index", 0)
                )
                all_embeddings.extend(
                    [item.embedding if hasattr(item, "embedding") else item["embedding"] for item in batch_embeddings]
                )
            except Exception as e:
                logger.error(f"Failed to generate embeddings batch (async): {e}")
                all_embeddings.extend([[0.0] * self._dim] * len(batch))

        return all_embeddings

    def generate_sync(self, text: str) -> list[float]:
        """Generate embedding for a single text (Sync)."""
        return self.generate_batch_sync([text])[0]

    def generate_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts (Sync) using urllib (Stability)."""
        if not texts:
            return []

        import json
        import urllib.request

        all_embeddings: list[list[float]] = []
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        
        # Use OpenRouter endpoint by default
        endpoint = "https://openrouter.ai/api/v1/embeddings"
        if os.getenv("OPENAI_API_KEY") and not os.getenv("OPENROUTER_API_KEY"):
            endpoint = "https://api.openai.com/v1/embeddings"

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            logger.debug(f"Generating embeddings for batch {i//self._batch_size + 1} (sync-urllib)")

            try:
                # Prepare request
                data = json.dumps({
                    "model": self._model,
                    "input": batch,
                }).encode("utf-8")
                
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": os.getenv("LITELLM_HTTP_REFERER", "http://localhost:8000"),
                }
                
                req = urllib.request.Request(endpoint, data=data, headers=headers)
                
                # Execute request
                with urllib.request.urlopen(req, timeout=30) as response:
                    res_body = json.loads(response.read().decode("utf-8"))
                    
                    # Extract embeddings
                    embeddings_data = res_body.get("data", [])
                    batch_embeddings = sorted(
                        embeddings_data,
                        key=lambda x: x.get("index", 0)
                    )
                    all_embeddings.extend([item["embedding"] for item in batch_embeddings])

            except Exception as e:
                logger.error(f"Failed to generate embeddings batch (sync-urllib): {e}")
                all_embeddings.extend([[0.0] * self._dim] * len(batch))

        return all_embeddings


# Singleton instance
_client: EmbeddingClient | None = None


def get_embedding_client(model: EmbeddingModel | None = None) -> EmbeddingClient:
    """Get or create singleton embedding client."""
    global _client
    if _client is None or model is not None:
        _client = EmbeddingClient(model=model)
    return _client


async def generate_embedding(text: str, model: EmbeddingModel | None = None) -> list[float]:
    """Quick helper (Async)."""
    client = get_embedding_client(model=model)
    return await client.generate(text)


def generate_embedding_sync(text: str, model: EmbeddingModel | None = None) -> list[float]:
    """Quick helper (Sync)."""
    client = get_embedding_client(model=model)
    return client.generate_sync(text)


async def generate_embeddings_batch(
    texts: list[str],
    model: EmbeddingModel | None = None,
) -> list[list[float]]:
    """Quick helper (Async)."""
    client = get_embedding_client(model=model)
    return await client.generate_batch(texts)


def generate_embeddings_batch_sync(
    texts: list[str],
    model: EmbeddingModel | None = None,
) -> list[list[float]]:
    """Quick helper (Sync)."""
    client = get_embedding_client(model=model)
    return client.generate_batch_sync(texts)
