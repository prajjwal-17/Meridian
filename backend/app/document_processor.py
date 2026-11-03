"""Idempotent PDF-to-chunks processing workflow."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chunker import create_chunks
from app.entity_graph import index_chunk_entities
from app.models import Document, DocumentChunk
from app.pdf_extractor import extract_pdf_text
from app.storage import download_file_bytes


def generate_embedding(text: str) -> list[float]:
    """Load the embedding model only when a chunk actually needs embedding."""
    from app.embedding import generate_embedding as _generate_embedding

    return _generate_embedding(text)


class DocumentProcessingError(RuntimeError):
    """Raised after a document is retained but processing failed."""


@dataclass(frozen=True)
class ProcessingResult:
    document_id: int
    chunks_created: int
    embeddings_created: int
    entities_indexed: int
    status: str


def process_document(db: Session, document_id: int) -> ProcessingResult:
    """Extract, chunk, embed, and graph-index one document without duplicates."""

    document = db.get(Document, document_id)
    if document is None:
        raise DocumentProcessingError(f"Document {document_id} was not found")

    document.status = "processing"
    db.commit()

    try:
        pdf_bytes = download_file_bytes(document.object_key)
        pages = extract_pdf_text(pdf_bytes)
        page_chunks = []
        for page in pages:
            for chunk in create_chunks(page["text"]):
                page_chunks.append((page["page_number"], chunk))

        if not page_chunks:
            raise ValueError("PDF contains no extractable text")

        chunks_created = 0
        embeddings_created = 0
        entities_indexed = 0

        for page_number, chunk_data in page_chunks:
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
                )
                db.add(chunk)
                db.flush()
                chunks_created += 1

            if chunk.embedding is None:
                chunk.embedding = generate_embedding(chunk.text)
                embeddings_created += 1

            index_chunk_entities(db, chunk.id, chunk.text)
            entities_indexed += 1

        document.status = "processed"
        db.commit()
        return ProcessingResult(
            document_id=document.id,
            chunks_created=chunks_created,
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
            f"Document {document_id} processing failed: {exc}"
        ) from exc
