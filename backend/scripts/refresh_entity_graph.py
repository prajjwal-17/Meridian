"""Non-destructively apply the current extractor to all existing chunks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.entity_graph import index_all_chunks


with SessionLocal() as db:
    processed = index_all_chunks(db, reindex=True)

print(f"Re-indexed {processed} document chunks without deleting existing graph rows.")
