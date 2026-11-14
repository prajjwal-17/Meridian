"""Sentence embeddings for chunks and queries.

The model is loaded lazily (importing this module is cheap) and reused for the
process lifetime. Query embeddings are memoised because the same question is
often embedded several times per request (dense search, hybrid search, retries).

all-MiniLM-L6-v2 truncates its input at 256 word pieces, while Meridian chunks
can be up to 500 tokens. Long texts are therefore embedded as the normalised
mean of overlapping windows so the tail of a chunk is still represented.
"""

from __future__ import annotations

from functools import lru_cache
from threading import Lock

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_WINDOW_WORDS = 160      # ~210 word pieces, safely below the 256 limit
_WINDOW_STRIDE = 120

_model = None
_model_lock = Lock()


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(MODEL_NAME)
    return _model


def _windows(text: str) -> list[str]:
    words = text.split()
    if len(words) <= _WINDOW_WORDS:
        return [text]
    spans = []
    start = 0
    while start < len(words):
        spans.append(" ".join(words[start:start + _WINDOW_WORDS]))
        if start + _WINDOW_WORDS >= len(words):
            break
        start += _WINDOW_STRIDE
    return spans


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Embed many chunk texts in one batched pass (used during ingestion)."""

    if not texts:
        return []
    windows: list[str] = []
    owners: list[int] = []
    for index, text in enumerate(texts):
        for window in _windows(text):
            windows.append(window)
            owners.append(index)
    vectors = get_model().encode(
        windows, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False
    )
    result = []
    owners_arr = np.asarray(owners)
    for index in range(len(texts)):
        mean = vectors[owners_arr == index].mean(axis=0)
        norm = np.linalg.norm(mean)
        result.append((mean / norm if norm else mean).tolist())
    return result


def generate_embedding(text: str) -> list[float]:
    """Embed one chunk text (window-averaged when it is long)."""

    return embed_texts([text])[0]


@lru_cache(maxsize=512)
def _cached_query_embedding(query: str) -> tuple[float, ...]:
    vector = get_model().encode(query, normalize_embeddings=True, show_progress_bar=False)
    return tuple(float(x) for x in vector)


def embed_query(query: str) -> list[float]:
    """Embed a search query; repeated queries are served from memory."""

    return list(_cached_query_embedding(query.strip()))
