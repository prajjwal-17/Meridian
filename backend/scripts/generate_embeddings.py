
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import DocumentChunk
from app.embedding import generate_embedding


db = SessionLocal()

try:
    chunks = db.query(DocumentChunk).filter(
        DocumentChunk.embedding.is_(None)
    ).all()

    print(f"Chunks requiring embeddings: {len(chunks)}")

    for chunk in chunks:
        chunk.embedding = generate_embedding(chunk.text)

    db.commit()

    print(f"Successfully generated {len(chunks)} embeddings.")

finally:
    db.close()
