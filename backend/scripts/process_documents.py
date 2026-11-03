"""Process existing uploaded documents without uploading them again."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.document_processor import DocumentProcessingError, process_document
from app.models import Document


parser = argparse.ArgumentParser()
parser.add_argument("--ids", nargs="+", type=int, required=True)
args = parser.parse_args()

failures = 0
with SessionLocal() as db:
    for document_id in args.ids:
        document = db.get(Document, document_id)
        if document is None:
            print(f"document_id={document_id} status=missing")
            failures += 1
            continue
        try:
            result = process_document(db, document_id)
            print(
                f"document_id={result.document_id} status={result.status} "
                f"chunks_created={result.chunks_created} "
                f"embeddings_created={result.embeddings_created} "
                f"chunks_indexed={result.entities_indexed}"
            )
        except DocumentProcessingError as exc:
            print(f"document_id={document_id} status=failed error={exc}")
            failures += 1

if failures:
    raise SystemExit(1)
