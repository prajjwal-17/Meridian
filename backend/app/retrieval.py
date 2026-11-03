
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.embedding import generate_embedding


def semantic_search(
    db: Session,
    query: str,
    top_k: int = 5
) -> list[dict]:

    if not query.strip():
        raise ValueError("Search query cannot be empty")

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    # Convert user query into an embedding
    query_embedding = generate_embedding(query)

    # Calculate cosine distance and retrieve closest chunks
    results = (
        db.query(
            DocumentChunk,
            Document.filename,
            DocumentChunk.embedding.cosine_distance(
                query_embedding
            ).label("distance")
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id
        )
        .filter(DocumentChunk.embedding.isnot(None))
        .order_by("distance")
        .limit(top_k)
        .all()
    )

    search_results = []

    for chunk, filename, distance in results:
        search_results.append({
            "document_id": chunk.document_id,
            "filename": filename,
            "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "similarity": 1 - distance
        })

    return search_results
