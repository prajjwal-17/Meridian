import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.storage import s3_client, BUCKET_NAME
from app.pdf_extractor import extract_pdf_text
from app.chunker import create_chunks
from app.database import SessionLocal
from app.models import Document, DocumentChunk


DOCUMENT_ID = 2


db = SessionLocal()

try:
    # Find document metadata
    document = db.query(Document).filter(
        Document.id == DOCUMENT_ID
    ).first()

    if document is None:
        raise ValueError("Document not found")

    # Download original PDF
    response = s3_client.get_object(
        Bucket=BUCKET_NAME,
        Key=document.object_key
    )

    pdf_bytes = response["Body"].read()

    # Extract text page by page
    pages = extract_pdf_text(pdf_bytes)

    all_chunks = []

    for page in pages:
        chunks = create_chunks(page["text"])

        for chunk in chunks:
            all_chunks.append(
                DocumentChunk(
                    document_id=document.id,
                    page_number=page["page_number"],
                    chunk_index=chunk["chunk_index"],
                    text=chunk["text"],
                    token_count=chunk["token_count"]
                )
            )

    # Replace previous chunks for this document
    db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document.id
    ).delete(synchronize_session=False)

    db.add_all(all_chunks)
    db.commit()

    # Verify saved chunks
    saved_chunks = db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document.id
    ).order_by(
        DocumentChunk.page_number,
        DocumentChunk.chunk_index
    ).all()

    print("========== CHUNKING SUMMARY ==========")
    print(f"Document: {document.filename}")
    print(f"Pages processed: {len(pages)}")
    print(f"Chunks created: {len(saved_chunks)}")

    for chunk in saved_chunks:
        print(
            f"\nPage: {chunk.page_number}"
            f" | Chunk: {chunk.chunk_index}"
            f" | Tokens: {chunk.token_count}"
        )
        print(chunk.text[:200])

finally:
    db.close()
