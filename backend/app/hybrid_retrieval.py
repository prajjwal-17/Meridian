
from sqlalchemy.orm import Session

from app.bm25_retrieval import bm25_search
from app.permissions import PermissionContext, authorized_chunk_ids
from app.reranker import rerank_candidates


def semantic_search(*args, **kwargs):
    """Keep dense model loading lazy while preserving the retrieval interface."""
    from app.retrieval import semantic_search as _semantic_search

    return _semantic_search(*args, **kwargs)


def hybrid_search(
    db: Session,
    query: str,
    top_k: int = 5,
    candidate_k: int = 20,
    rrf_k: int = 60,
    permission_context: PermissionContext | None = None,
    rerank: bool = False,
) -> list[dict]:

    if not query.strip():
        raise ValueError("Search query cannot be empty")

    if top_k <= 0 or candidate_k <= 0 or rrf_k <= 0:
        raise ValueError("Search limits must be positive")

    # Resolve the ACL once and share it with both retrievers; each of them
    # still filters by these ids inside its own query.
    context = permission_context or PermissionContext()
    allowed_ids = authorized_chunk_ids(db, context)

    # Retrieve candidates independently
    bm25_results = bm25_search(
        db=db,
        query=query,
        top_k=candidate_k,
        permission_context=permission_context,
        allowed_ids=allowed_ids,
    )

    dense_results = semantic_search(
        db=db,
        query=query,
        top_k=candidate_k,
        permission_context=permission_context,
        allowed_ids=allowed_ids,
    )

    # Store combined rankings
    fused_results = {}

    retrieval_lists = [
        bm25_results,
        dense_results
    ]

    for retrieval_results in retrieval_lists:

        for rank, result in enumerate(
            retrieval_results,
            start=1
        ):

            # Identify each chunk uniquely
            key = (
                result["document_id"],
                result["page_number"],
                result["chunk_index"]
            )

            if key not in fused_results:
                fused_results[key] = {
                    "chunk_id": result.get("chunk_id"),
                    "document_id": result["document_id"],
                    "filename": result["filename"],
                    "source_name": result.get("source_name"),
                    "source_document_id": result.get("source_document_id"),
                    "page_number": result["page_number"],
                    "chunk_index": result["chunk_index"],
                    "text": result["text"],
                    "rrf_score": 0.0,
                    "retrieval_sources": []
                }

            # Reciprocal Rank Fusion
            fused_results[key]["rrf_score"] += (
                1 / (rrf_k + rank)
            )

            source = (
                "bm25" if retrieval_results is bm25_results
                else "dense"
            )

            if source not in fused_results[key]["retrieval_sources"]:
                fused_results[key]["retrieval_sources"].append(source)

    # Sort by combined RRF score
    ranked_results = sorted(
        fused_results.values(),
        key=lambda item: item["rrf_score"],
        reverse=True
    )

    if not rerank:
        return ranked_results[:top_k]

    # Defense in depth: only candidates inside the resolved ACL set may reach
    # the cross-encoder.
    safe_candidates = [
        result
        for result in ranked_results[:candidate_k]
        if result.get("chunk_id") in allowed_ids
    ]
    return rerank_candidates(
        query=query,
        candidates=safe_candidates,
        top_k=top_k,
        permission_context=permission_context,
        authorized_ids=allowed_ids,
    )
