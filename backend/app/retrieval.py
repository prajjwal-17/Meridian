
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.permissions import PermissionContext, authorized_chunk_ids


def generate_embedding(text: str) -> list[float]:
    """Load the embedding model only when dense search is requested."""
    from app.embedding import generate_embedding as _generate_embedding

    return _generate_embedding(text)


def semantic_search(
    db: Session,
    query: str,
    top_k: int = 5,
    permission_context: PermissionContext | None = None,
) -> list[dict]:

    if not query.strip():
        raise ValueError("Search query cannot be empty")

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    # Convert user query into an embedding
    query_embedding = generate_embedding(query)
    allowed_ids = authorized_chunk_ids(
        db, permission_context or PermissionContext()
    )
    if not allowed_ids:
        return []

    # Calculate cosine distance and retrieve closest chunks
    results = (
        db.query(
            DocumentChunk,
            Document.filename,
            Document.source_name,
            Document.source_document_id,
            DocumentChunk.embedding.cosine_distance(
                query_embedding
            ).label("distance")
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id
        )
        .filter(DocumentChunk.embedding.isnot(None))
        .filter(DocumentChunk.id.in_(allowed_ids))
        .order_by("distance")
        .limit(top_k)
        .all()
    )

    search_results = []

    for chunk, filename, source_name, source_document_id, distance in results:
        search_results.append({
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "filename": filename,
            "source_name": source_name,
            "source_document_id": source_document_id,
            "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "similarity": 1 - distance
        })

    return search_results
