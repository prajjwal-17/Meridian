
from sqlalchemy.orm import Session

from app.bm25_retrieval import bm25_search
from app.retrieval import semantic_search


def hybrid_search(
    db: Session,
    query: str,
    top_k: int = 5,
    candidate_k: int = 20,
    rrf_k: int = 60
) -> list[dict]:

    if not query.strip():
        raise ValueError("Search query cannot be empty")

    if top_k <= 0 or candidate_k <= 0 or rrf_k <= 0:
        raise ValueError("Search limits must be positive")

    # Retrieve candidates independently
    bm25_results = bm25_search(
        db=db,
        query=query,
        top_k=candidate_k
    )

    dense_results = semantic_search(
        db=db,
        query=query,
        top_k=candidate_k
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
                    "document_id": result["document_id"],
                    "filename": result["filename"],
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

    return ranked_results[:top_k]
