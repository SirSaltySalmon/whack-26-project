"""A stand-in for the embedding model, so tests never download one. Kept out of fakes.py, which is
already over the 300-line limit."""

import math
import re
import zlib
from collections.abc import Mapping, Sequence

_WORD = re.compile(r"\w+")


class FakeEmbedder:
    """Each word points its own way, so texts sharing words are similar. `aliases` maps a word
    onto another, which is how a test says two different words mean the same thing."""

    def __init__(
        self,
        aliases: Mapping[str, str] | None = None,
        *,
        dims: int = 256,
        model: str = "fake-embedder",
        fail: bool = False,
    ) -> None:
        self.model = model
        self.dims = dims
        self.aliases = dict(aliases or {})
        self.fail = fail
        self.queries: list[str] = []
        self.passages: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        if self.fail:
            raise RuntimeError("fake embedding failure")
        self.queries.append(text)
        return self._vector(text)

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("fake embedding failure")
        self.passages.extend(texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        for word in _WORD.findall(text.lower()):
            word = self.aliases.get(word, word)
            vector[zlib.crc32(word.encode()) % self.dims] += 1.0
        # A real model never returns all zeros, and cosine distance needs a length.
        vector[-1] += 0.01
        norm = math.sqrt(sum(x * x for x in vector))
        return [x / norm for x in vector]
