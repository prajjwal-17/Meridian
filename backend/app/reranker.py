"""Lazy cross-encoder reranking for ACL-filtered retrieval candidates."""

from __future__ import annotations

from threading import Lock
from typing import Any, Iterable

from app.permissions import PermissionContext

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_cross_encoder = None
_cross_encoder_lock = Lock()


class RerankerError(RuntimeError):
    """Raised when cross-encoder reranking cannot be completed."""


def load_cross_encoder():
    """Load the cross-encoder only when reranking is explicitly requested."""

    global _cross_encoder

    if _cross_encoder is not None:
        return _cross_encoder

    with _cross_encoder_lock:
        if _cross_encoder is not None:
            return _cross_encoder

        try:
            from sentence_transformers import CrossEncoder

            _cross_encoder = CrossEncoder(MODEL_NAME)
            return _cross_encoder
        except Exception as exc:
            raise RerankerError(
                f"Unable to load cross-encoder model {MODEL_NAME}: {exc}"
            ) from exc


def _validated_candidates(
    candidates: Iterable[dict[str, Any]],
    authorized_ids: set[int],
) -> list[dict[str, Any]]:
    """Keep only candidates with an authorized, persisted chunk ID."""

    safe_candidates = []
    for candidate in candidates:
        chunk_id = candidate.get("chunk_id")
        text = candidate.get("text")
        if not isinstance(chunk_id, int) or chunk_id not in authorized_ids:
            continue
        if not isinstance(text, str) or not text:
            continue
        safe_candidates.append(candidate)
    return safe_candidates


def rerank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int = 5,
    permission_context: PermissionContext | None = None,
    authorized_ids: set[int] | None = None,
    model: Any | None = None,
) -> list[dict[str, Any]]:
    """Score ACL-filtered query/chunk pairs and return top-k candidates."""

    if not query.strip():
        raise ValueError("Reranking query cannot be empty")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if not candidates:
        return []
    if permission_context is None or authorized_ids is None:
        raise RerankerError(
            "Reranking requires an explicit PermissionContext and "
            "ACL-filtered authorized_ids set"
        )

    safe_candidates = _validated_candidates(candidates, authorized_ids)
    if not safe_candidates:
        return []

    reranker = model or load_cross_encoder()
    pairs = [(query, candidate["text"]) for candidate in safe_candidates]
    try:
        scores = reranker.predict(pairs)
    except Exception as exc:
        raise RerankerError(f"Cross-encoder scoring failed: {exc}") from exc

    if len(scores) != len(safe_candidates):
        raise RerankerError(
            "Cross-encoder returned a score count that does not match candidates"
        )

    reranked = []
    for candidate, score in zip(safe_candidates, scores):
        result = dict(candidate)
        result["cross_encoder_score"] = float(score)
        reranked.append(result)

    reranked.sort(
        key=lambda result: result["cross_encoder_score"],
        reverse=True,
    )
    return reranked[:top_k]
