"""Direct text ingestion that shares chunk, embedding, and graph infrastructure."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chunker import create_chunks
from app.document_processor import DocumentProcessingError, generate_embedding
from app.entity_graph import index_chunk_entities
from app.models import Document, DocumentChunk

EMBEDDING_DIMENSION = 384


@dataclass(frozen=True)
class TextProcessingResult:
    document_id: int
    chunks_created: int
    chunks_updated: int
    embeddings_created: int
    entities_indexed: int
    status: str


def process_text_document(
    db: Session,
    document_id: int,
    text: str,
    page_number: int = 1,
    index_entities: bool = False,
) -> TextProcessingResult:
    """Chunk and persist direct text without requiring PDF or object storage."""

    if not text or not text.strip():
        raise DocumentProcessingError("Text document contains no extractable text")
    if page_number <= 0:
        raise ValueError("page_number must be positive")

    document = db.get(Document, document_id)
    if document is None:
        raise DocumentProcessingError(f"Document {document_id} was not found")

    document.status = "processing"
    db.commit()

    try:
        chunks_created = 0
        chunks_updated = 0
        embeddings_created = 0
        entities_indexed = 0

        for chunk_data in create_chunks(text):
            chunk = db.scalar(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == document.id,
                    DocumentChunk.page_number == page_number,
                    DocumentChunk.chunk_index == chunk_data["chunk_index"],
                )
            )

            if chunk is None:
                chunk = DocumentChunk(
                    document_id=document.id,
                    page_number=page_number,
                    chunk_index=chunk_data["chunk_index"],
                    text=chunk_data["text"],
                    token_count=chunk_data["token_count"],
                    permission_tier=document.permission_tier,
                )
                db.add(chunk)
                db.flush()
                chunks_created += 1
            else:
                if (
                    chunk.text != chunk_data["text"]
                    or chunk.token_count != chunk_data["token_count"]
                ):
                    chunk.text = chunk_data["text"]
                    chunk.token_count = chunk_data["token_count"]
                    chunk.embedding = None
                    chunks_updated += 1
                chunk.permission_tier = document.permission_tier

            if chunk.embedding is None:
                embedding = generate_embedding(chunk.text)
                if len(embedding) != EMBEDDING_DIMENSION:
                    raise ValueError(
                        "Embedding dimension mismatch: "
                        f"expected {EMBEDDING_DIMENSION}, got {len(embedding)}"
                    )
                chunk.embedding = embedding
                embeddings_created += 1

            if index_entities:
                index_chunk_entities(db, chunk.id, chunk.text)
                entities_indexed += 1

        document.status = "processed"
        db.commit()
        return TextProcessingResult(
            document_id=document.id,
            chunks_created=chunks_created,
            chunks_updated=chunks_updated,
            embeddings_created=embeddings_created,
            entities_indexed=entities_indexed,
            status=document.status,
        )
    except Exception as exc:
        db.rollback()
        failed_document = db.get(Document, document_id)
        if failed_document is not None:
            failed_document.status = "failed"
            db.commit()
        raise DocumentProcessingError(
            f"Text document {document_id} processing failed: {exc}"
        ) from exc
