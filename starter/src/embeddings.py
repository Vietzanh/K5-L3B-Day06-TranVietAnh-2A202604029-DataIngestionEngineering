"""Real embedding adapter for OpenRouter/OpenAI; no synthetic-vector fallback."""

from __future__ import annotations

import json
import math
import os
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, question: str) -> list[float]: ...


class MyEmbedder:
    """Call a configured embeddings API using its OpenAI-compatible contract.

    OpenRouter is selected by default when OPENROUTER_API_KEY is present. Set
    EMBEDDING_PROVIDER=openai to use OPENAI_API_KEY instead.
    """

    def __init__(self, model_name: str | None = None) -> None:
        provider = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
        if not provider:
            provider = "openrouter" if os.getenv("OPENROUTER_API_KEY") else "openai"

        if provider == "openrouter":
            self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
            self.endpoint = "https://openrouter.ai/api/v1/embeddings"
            default_model = "openai/text-embedding-3-small"
        elif provider == "openai":
            self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
            self.endpoint = "https://api.openai.com/v1/embeddings"
            default_model = "text-embedding-3-small"
        else:
            raise ValueError(
                f"Unsupported EMBEDDING_PROVIDER={provider!r}. "
                "This starter implements openrouter and openai."
            )

        if not self.api_key:
            raise RuntimeError(
                f"Missing API key for {provider}. Set the corresponding key in starter/.env."
            )
        self.provider = provider
        self.model_name = (
            model_name or os.getenv("EMBEDDING_MODEL") or default_model
        ).strip()
        self.dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
        if self.dimensions <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS must be a positive integer")
        self.batch_size = max(1, int(os.getenv("EMBEDDING_BATCH_SIZE", "64")))
        self.timeout = max(5, int(os.getenv("EMBEDDING_TIMEOUT", "90")))
        self.request_count = 0
        self.prompt_tokens = 0
        self.total_tokens = 0

    def _request(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model_name,
            "input": texts,
            "dimensions": self.dimensions,
            "encoding_format": "float",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "https://localhost/day06-lab"
            headers["X-Title"] = "Day 06 Data Ingestion Engineering Lab"

        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                usage = body.get("usage") or {}
                self.request_count += 1
                self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
                self.total_tokens += int(
                    usage.get("total_tokens", usage.get("prompt_tokens", 0)) or 0
                )
                data = body.get("data")
                if not isinstance(data, list) or len(data) != len(texts):
                    raise RuntimeError(
                        "Embedding API returned an unexpected number of vectors"
                    )
                data = sorted(data, key=lambda item: int(item.get("index", 0)))
                vectors: list[list[float]] = []
                for item in data:
                    vector = item.get("embedding")
                    if not isinstance(vector, list) or len(vector) != self.dimensions:
                        got = len(vector) if isinstance(vector, list) else "non-list"
                        raise RuntimeError(
                            f"Embedding dimension mismatch: expected {self.dimensions}, got {got}. "
                            "Check EMBEDDING_MODEL and EMBEDDING_DIMENSIONS."
                        )
                    values = [float(value) for value in vector]
                    if not all(math.isfinite(value) for value in values):
                        raise RuntimeError(
                            "Embedding API returned a non-finite vector value"
                        )
                    vectors.append(values)
                return vectors
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:1000]
                last_error = RuntimeError(f"Embedding API HTTP {exc.code}: {detail}")
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise last_error from exc
            except (URLError, TimeoutError) as exc:
                last_error = RuntimeError(f"Embedding API network error: {exc}")
                if attempt == 2:
                    raise last_error from exc
            if attempt < 2:
                time.sleep(2**attempt)
        raise RuntimeError("Embedding request failed") from last_error

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Every embedding input must be a non-empty string")
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(self._request(batch))
        return vectors

    def embed_query(self, question: str) -> list[float]:
        if not question.strip():
            raise ValueError("Question must not be empty")
        return self._request([question])[0]

    def embed_queries(self, questions: list[str]) -> list[list[float]]:
        """Batch query embeddings to reduce API round trips."""
        return self.embed_documents(questions)
