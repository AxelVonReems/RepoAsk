"""Embedder interface and its fastembed implementation.

Indexing and retrieval depend only on the Embedder protocol, so the model or provider
(another fastembed model, Gemini embeddings, a fake in tests) can change in one place.
"""

from collections.abc import Sequence
from typing import Protocol

import numpy as np
from fastembed import TextEmbedding
from tokenizers import Tokenizer

from rag import config


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        """Returns a (len(texts), dim) float32 matrix of L2-normalized vectors."""
        ...

    def embed_query(self, text: str) -> np.ndarray:
        """Returns one (dim,) float32 L2-normalized vector for a search query."""
        ...

    def count_tokens(self, text: str) -> int:
        """Tokens the model sees for text, without special tokens and without truncation."""
        ...


class FastEmbedEmbedder:
    def __init__(
        self,
        model_name: str = config.EMBED_MODEL,
        cache_dir: str = str(config.MODEL_CACHE_DIR),
        query_prefix: str = config.EMBED_QUERY_PREFIX,
        batch_size: int = config.EMBED_BATCH_SIZE,
    ) -> None:
        self.model_name = model_name
        self.query_prefix = query_prefix
        self.batch_size = batch_size
        self._model = TextEmbedding(model_name, cache_dir=cache_dir)
        self.dim = len(self.embed_query("dimension probe"))

        # Counting needs its own tokenizer: switching off truncation on the model's shared
        # tokenizer would also let over-long inputs reach the model and fail there
        self._counter = Tokenizer.from_str(self._model.model.tokenizer.to_str())
        self._counter.no_truncation()
        self._counter.no_padding()

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        vectors = self._model.passage_embed(list(texts), batch_size=self.batch_size)
        return np.asarray(list(vectors), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        vector = next(iter(self._model.query_embed(self.query_prefix + text)))
        return np.asarray(vector, dtype=np.float32)

    def count_tokens(self, text: str) -> int:
        return len(self._counter.encode(text, add_special_tokens=False).ids)
