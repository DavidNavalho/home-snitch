"""LanceDB embedding function backed by llama-cpp-python GGUF models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pydantic import PrivateAttr

from lancedb.embeddings.base import TextEmbeddingFunction
from lancedb.embeddings.registry import register

try:
    from llama_cpp import Llama, suppress_stdout_stderr

    _LLAMA_CPP_AVAILABLE = True
except ImportError:
    _LLAMA_CPP_AVAILABLE = False


@register("gguf")
class GGUFEmbeddings(TextEmbeddingFunction):
    """Embedding function that loads a local or Hugging Face GGUF model."""

    repo_id: str = ""
    filename: str = ""
    n_ctx: int = 8192
    n_threads: int = 4
    pooling_type: int = 1
    normalize: bool = True

    _model: Any = PrivateAttr(default=None)
    _ndims: int | None = PrivateAttr(default=None)

    def _resolve_model_path(self) -> str:
        candidate = Path(self.filename).expanduser()
        if candidate.exists():
            return str(candidate)

        if not self.repo_id:
            raise ValueError(
                "GGUF_MODEL_REPO is required when GGUF_MODEL_FILE is not a local file"
            )

        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise ImportError(
                "huggingface-hub is required to download GGUF embedding models"
            ) from exc

        return hf_hub_download(repo_id=self.repo_id, filename=self.filename)

    def _get_model(self) -> Any:
        if not _LLAMA_CPP_AVAILABLE:
            raise ImportError(
                "llama-cpp-python is required for local_gguf embeddings"
            )

        if self._model is None:
            self._model = Llama(
                model_path=self._resolve_model_path(),
                embedding=True,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                pooling_type=self.pooling_type,
                verbose=False,
            )
        return self._model

    def ndims(self) -> int:
        if self._ndims is None:
            self._ndims = len(self.generate_embeddings(["dimension probe"])[0])
        return self._ndims

    def generate_embeddings(self, texts: list[str] | np.ndarray) -> list[list[float]]:
        model = self._get_model()
        vectors: list[list[float]] = []
        for text in texts:
            text_value = str(text)
            n_tokens = len(model.tokenize(text_value.encode("utf-8")))
            if n_tokens > self.n_ctx:
                raise ValueError(
                    f"Text ({n_tokens} tokens) exceeds GGUF_N_CTX ({self.n_ctx})"
                )

            with suppress_stdout_stderr():
                embedding = model.embed(text_value)

            vector = np.array(embedding, dtype=np.float32)
            if vector.ndim == 2:
                vector = vector[0]
            if self.normalize:
                norm = np.linalg.norm(vector)
                if norm > 0:
                    vector = vector / norm
            vectors.append(vector.tolist())
        return vectors


__all__ = ["GGUFEmbeddings"]
