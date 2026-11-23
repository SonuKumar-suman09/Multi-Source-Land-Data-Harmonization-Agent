"""Gemini embeddings with a deterministic, no-key local development provider."""

from __future__ import annotations

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.core.config import settings


class EmbeddingConfigurationError(ValueError):
    """The configured embedding provider is incomplete or unsupported."""


class LocalHashEmbeddings(Embeddings):
    """Deterministic lexical feature hashing for offline development and tests."""

    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-z0-9]+", text.casefold())
        features = list(tokens) + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[slot] += sign
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude:
            vector = [value / magnitude for value in vector]
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def get_embeddings() -> Embeddings:
    provider = settings.rag_embedding_provider.strip().lower()
    if provider == "local":
        return LocalHashEmbeddings(settings.embedding_dimensions)
    if provider == "gemini":
        key = settings.gemini_api_key.get_secret_value().strip() if settings.gemini_api_key else ""
        if not key:
            raise EmbeddingConfigurationError(
                "Set GEMINI_API_KEY in the untracked .env file or select RAG_EMBEDDING_PROVIDER=local"
            )
        return GoogleGenerativeAIEmbeddings(
            model=settings.gemini_embedding_model,
            google_api_key=key,
            output_dimensionality=settings.embedding_dimensions,
        )
    raise EmbeddingConfigurationError("RAG_EMBEDDING_PROVIDER must be 'local' or 'gemini'")
