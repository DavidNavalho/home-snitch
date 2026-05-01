"""Embedding provider adapters for the Home Wiki search index."""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from homewiki.config import EmbeddingSettings, Settings


FAKE_EMBEDDING_DIMENSION = 64
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class EmbeddingConfigurationError(ValueError):
    """Raised when a selected embedding provider is missing required settings."""


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider cannot generate vectors."""


class EmbeddingClient(Protocol):
    """Small provider-neutral embedding interface used by the LanceDB store."""

    provider: str

    @property
    def dimension(self) -> int | None:
        """Return vector dimensions when known without an embedding call."""

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed one or more texts."""


@dataclass(frozen=True)
class FakeEmbeddingClient:
    """Deterministic lexical hashing embeddings for offline tests."""

    dimensions: int = FAKE_EMBEDDING_DIMENSION
    provider: str = "fake"

    @property
    def dimension(self) -> int:
        return self.dimensions

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [_fake_embedding(text, self.dimensions) for text in texts]


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingClient:
    """HTTP client for OpenAI-compatible /embeddings endpoints."""

    api_base: str
    api_key: str
    model: str
    provider: str = "openai_compatible"

    @property
    def dimension(self) -> int | None:
        return None

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        endpoint = f"{self.api_base.rstrip('/')}/embeddings"
        payload = json.dumps({"model": self.model, "input": list(texts)}).encode(
            "utf-8"
        )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingProviderError(
                "openai_compatible embedding request failed "
                f"for model {self.model!r}: HTTP {exc.code} {detail}"
            ) from exc
        except OSError as exc:
            raise EmbeddingProviderError(
                "openai_compatible embedding request failed "
                f"for model {self.model!r} at {endpoint!r}: {exc}"
            ) from exc

        try:
            data = json.loads(body.decode("utf-8"))
            rows = data["data"]
            rows = sorted(rows, key=lambda row: row.get("index", 0))
            vectors = [list(map(float, row["embedding"])) for row in rows]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EmbeddingProviderError(
                "openai_compatible embedding response did not match the "
                "OpenAI embeddings schema"
            ) from exc

        if len(vectors) != len(texts):
            raise EmbeddingProviderError(
                "openai_compatible embedding response returned "
                f"{len(vectors)} vectors for {len(texts)} inputs"
            )
        return vectors


class LocalGGUFEmbeddingClient:
    """Adapter around the LanceDB GGUF embedding function."""

    provider = "local_gguf"

    def __init__(
        self,
        *,
        repo_id: str,
        filename: str,
        n_ctx: int,
        n_threads: int,
    ) -> None:
        try:
            from lancedb.embeddings import get_registry

            import homewiki.gguf_embeddings  # noqa: F401
        except ImportError as exc:
            raise EmbeddingProviderError(
                "local_gguf embeddings require lancedb, llama-cpp-python, "
                "and huggingface-hub to be installed"
            ) from exc

        try:
            self._embedding_function = (
                get_registry()
                .get("gguf")
                .create(
                    repo_id=repo_id,
                    filename=filename,
                    n_ctx=n_ctx,
                    n_threads=n_threads,
                )
            )
        except Exception as exc:
            raise EmbeddingProviderError(
                "local_gguf embedding model could not be initialized "
                f"(repo={repo_id!r}, file={filename!r}): {exc}"
            ) from exc

    @property
    def dimension(self) -> int:
        try:
            return int(self._embedding_function.ndims())
        except Exception as exc:
            raise EmbeddingProviderError(
                f"local_gguf embedding dimension probe failed: {exc}"
            ) from exc

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            return [
                list(map(float, vector))
                for vector in self._embedding_function.generate_embeddings(list(texts))
            ]
        except Exception as exc:
            raise EmbeddingProviderError(
                f"local_gguf embedding generation failed: {exc}"
            ) from exc


def create_embedding_client(
    settings: Settings | EmbeddingSettings,
) -> EmbeddingClient:
    """Create and validate the configured embedding provider."""

    embedding = settings.embedding if isinstance(settings, Settings) else settings

    if embedding.provider == "fake":
        return FakeEmbeddingClient()

    if embedding.provider == "openai_compatible":
        _require_non_blank(
            {
                "EMBEDDING_API_BASE": embedding.api_base,
                "EMBEDDING_MODEL": embedding.model,
            },
            provider=embedding.provider,
        )
        return OpenAICompatibleEmbeddingClient(
            api_base=embedding.api_base,
            api_key=embedding.api_key,
            model=embedding.model,
        )

    if embedding.provider == "local_gguf":
        if not embedding.gguf_model_file.strip():
            raise EmbeddingConfigurationError(
                "Missing embedding configuration for local_gguf: "
                "GGUF_MODEL_FILE is required"
            )
        if not embedding.gguf_model_repo.strip() and not _is_configured_local_file(
            embedding.gguf_model_file
        ):
            raise EmbeddingConfigurationError(
                "Missing embedding configuration for local_gguf: "
                "GGUF_MODEL_REPO is required unless GGUF_MODEL_FILE is a local path"
            )
        return LocalGGUFEmbeddingClient(
            repo_id=embedding.gguf_model_repo,
            filename=embedding.gguf_model_file,
            n_ctx=embedding.gguf_n_ctx,
            n_threads=embedding.gguf_n_threads,
        )

    raise EmbeddingConfigurationError(
        f"Unsupported embedding provider: {embedding.provider!r}"
    )


def _require_non_blank(values: dict[str, str], *, provider: str) -> None:
    missing = [name for name, value in values.items() if not value.strip()]
    if missing:
        joined = ", ".join(missing)
        raise EmbeddingConfigurationError(
            f"Missing embedding configuration for {provider}: {joined}"
        )


def _is_configured_local_file(value: str) -> bool:
    candidate = Path(value).expanduser()
    return candidate.exists() or value.startswith(("/", "~", "."))


def _fake_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    tokens = _TOKEN_RE.findall(text.lower())

    if not tokens:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        tokens = [digest.hex()]

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


__all__ = [
    "EmbeddingClient",
    "EmbeddingConfigurationError",
    "EmbeddingProviderError",
    "FAKE_EMBEDDING_DIMENSION",
    "FakeEmbeddingClient",
    "LocalGGUFEmbeddingClient",
    "OpenAICompatibleEmbeddingClient",
    "create_embedding_client",
]
