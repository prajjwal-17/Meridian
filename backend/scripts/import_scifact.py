"""Idempotent, resumable importer for the BEIR SciFact corpus."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from io import BytesIO
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal
from app.models import Document, DocumentChunk
from app.storage import BUCKET_NAME, s3_client
from app.text_processor import process_text_document
SOURCE_NAME = "beir-scifact"
DATASET_DIR = Path(__file__).resolve().parents[1] / "data" / "scifact"
SOURCE_KEY_PREFIX = "datasets/beir-scifact"
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
def parse_corpus_record(raw: str, line_number: int) -> dict:
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"line {line_number}: invalid JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"line {line_number}: record must be an object")
    for field in ("_id", "title", "text", "metadata"):
        if field not in record:
            raise ValueError(f"line {line_number}: missing field {field}")
    if not isinstance(record["_id"], str) or not record["_id"].strip():
        raise ValueError(f"line {line_number}: _id must be a non-empty string")
    if not SAFE_ID.fullmatch(record["_id"]):
        raise ValueError(f"line {line_number}: _id contains unsafe characters")
    if not isinstance(record["title"], str):
        raise ValueError(f"line {line_number}: title must be a string")
    if not isinstance(record["text"], str) or not record["text"].strip():
        raise ValueError(f"line {line_number}: text must be non-empty")
    if not isinstance(record["metadata"], dict):
        raise ValueError(f"line {line_number}: metadata must be an object")
    return record
def canonical_record_bytes(record: dict) -> bytes:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
def document_metadata(record: dict) -> dict:
    source_id = record["_id"]
    payload = canonical_record_bytes(record)
    return {
        "filename": f"scifact_{source_id}.json",
        "object_key": f"{SOURCE_KEY_PREFIX}/{source_id}.json",
        "content_type": "application/json",
        "file_size": len(payload),
        "checksum": hashlib.sha256(payload).hexdigest(),
        "source_name": SOURCE_NAME,
        "source_document_id": source_id,
        "payload": payload,
    }
def upload_source_object(metadata: dict) -> None:
    s3_client.upload_fileobj(BytesIO(metadata["payload"]), BUCKET_NAME, metadata["object_key"], ExtraArgs={"ContentType": metadata["content_type"]})
def import_record(db, record: dict, *, index_entities: bool = False) -> str:
    metadata = document_metadata(record)
    document = db.query(Document).filter(Document.source_name == SOURCE_NAME, Document.source_document_id == record["_id"]).first()
    if document is not None:
        chunk_count = db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).count()
        if document.status == "processed" and chunk_count > 0:
            return "skipped"
    else:
        upload_source_object(metadata)
        document = Document(filename=metadata["filename"], object_key=metadata["object_key"], content_type=metadata["content_type"], file_size=metadata["file_size"], checksum=metadata["checksum"], source_name=SOURCE_NAME, source_document_id=record["_id"], permission_tier="public")
        db.add(document)
        db.commit()
        db.refresh(document)
    text = f"{record['title'].strip()}\n\n{record['text'].strip()}"
    process_text_document(db, document.id, text, page_number=1, index_entities=index_entities)
    return "processed"
def run_import(corpus_path: Path, *, limit: int | None = None, batch_size: int = 100, dry_run: bool = False, index_entities: bool = False) -> dict[str, int]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    counts = {"imported": 0, "skipped": 0, "failed": 0, "processed": 0}
    db = None if dry_run else SessionLocal()
    try:
        with corpus_path.open(encoding="utf-8") as corpus:
            for line_number, raw in enumerate(corpus, start=1):
                if limit is not None and line_number > limit:
                    break
                try:
                    record = parse_corpus_record(raw, line_number)
                    if dry_run:
                        counts["processed"] += 1
                        continue
                    result = import_record(db, record, index_entities=index_entities)
                    counts[result] += 1
                    if result == "processed":
                        counts["imported"] += 1
                    if line_number % batch_size == 0:
                        print(f"Processed input records: {line_number}; counts={counts}")
                except Exception as exc:
                    if db is not None:
                        db.rollback()
                    counts["failed"] += 1
                    print(f"FAILED line {line_number}: {exc}", file=sys.stderr)
    finally:
        if db is not None:
            db.close()
    return counts
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DATASET_DIR / "corpus.jsonl")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--index-entities", action="store_true")
    args = parser.parse_args()
    counts = run_import(args.corpus, limit=args.limit, batch_size=args.batch_size, dry_run=args.dry_run, index_entities=args.index_entities)
    print("\nSciFact import summary")
    for key in ("imported", "skipped", "failed", "processed"):
        print(f"  {key}: {counts[key]}")
    return 1 if counts["failed"] else 0
if __name__ == "__main__":
    raise SystemExit(main())
