
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from app.database import engine


with engine.begin() as connection:
    connection.execute(
        text("""
            ALTER TABLE document_chunks
            ADD COLUMN IF NOT EXISTS embedding vector(384);
        """)
    )

print("Vector column added successfully.")
