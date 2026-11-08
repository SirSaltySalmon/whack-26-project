"""Local text embeddings for meaning-based memory search. CPU-bound, so never call on the loop."""

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class Embedder(Protocol):
    model: str
    dims: int

    def embed_query(self, text: str) -> list[float]: ...

    # Separate from queries because some models, such as bge, embed questions and documents
    # differently. MiniLM treats them the same.
    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedder:
    """fastembed on onnxruntime. Loading takes about half a second once the model is cached, and
    the first run downloads it into `cache_dir`, so run it once before a demo with no network."""

    def __init__(self, model: str, cache_dir: Path) -> None:
        # Imported here because it takes about a second, and keyword search never needs it.
        from fastembed import TextEmbedding

        started = time.perf_counter()
        self.model = model
        self._model = TextEmbedding(model, cache_dir=str(cache_dir))
        # Also warms onnxruntime, so the player's first question doesn't pay for it.
        self.dims = len(self.embed_query("warm up"))
        log.info(
            "Loaded embedding model %s (%d dims) in %.0f ms",
            model,
            self.dims,
            (time.perf_counter() - started) * 1000,
        )

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed([text]))).tolist()

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.passage_embed(list(texts))]
