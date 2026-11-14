"""Fill in or rebuild chunk embeddings.

    python scripts/generate_embeddings.py          # only chunks without an embedding
    python scripts/generate_embeddings.py --all    # re-embed every chunk (e.g. after
                                                   # changing the embedding strategy)

Embeddings are computed in batches; long chunks are embedded as the mean of
overlapping windows (see app/embedding.py) so their full text is represented.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.embedding import embed_texts
from app.models import DocumentChunk


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="re-embed every chunk")
    parser.add_argument("--batch", type=int, default=64)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(DocumentChunk).order_by(DocumentChunk.id)
        if not args.all:
            query = query.filter(DocumentChunk.embedding.is_(None))
        chunks = query.all()
        print(f"Chunks requiring embeddings: {len(chunks)}")
        for start in range(0, len(chunks), args.batch):
            batch = chunks[start:start + args.batch]
            for chunk, vector in zip(batch, embed_texts([chunk.text for chunk in batch])):
                chunk.embedding = vector
            db.commit()
            print(f"  embedded {min(start + args.batch, len(chunks))}/{len(chunks)}")
        print(f"Successfully generated {len(chunks)} embeddings.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
