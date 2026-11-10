"""Idempotently import the Meridian fictional enterprise PDF corpus."""

from __future__ import annotations

import argparse
import hashlib
import sys
from io import BytesIO
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.document_processor import DocumentProcessingError, process_document  # noqa: E402
from app.models import Document  # noqa: E402
from app.storage import BUCKET_NAME, s3_client  # noqa: E402


SOURCE_NAME = "meridian-enterprise"
CORPUS_DIR = Path(__file__).resolve().parents[2] / "Corpus"
OBJECT_PREFIX = "datasets/meridian-enterprise"

DOCUMENTS = [
    ("HR-001", "Employee Leave and Attendance Policy", "Human Resources", "department", [], [], "1.1"),
    ("HR-002", "Employee Handbook", "Human Resources", "public", [], [], "1.0"),
    ("HR-003", "Recruitment and Onboarding SOP", "Human Resources", "team", ["Talent Acquisition"], [], "1.0"),
    ("HR-004", "Performance Evaluation Framework", "Human Resources", "team", ["People Operations"], [], "1.0"),
    ("ENG-001", "Backend Platform Architecture and API Design", "Engineering", "team", ["Backend Platform"], [], "1.0"),
    ("ENG-002", "Software Engineering Development and Deployment Guidelines", "Engineering", "department", [], [], "1.0"),
    ("ENG-003", "Microservices Communication and Integration Standards", "Engineering", "team", ["Backend Platform"], [], "1.0"),
    ("ENG-004", "Production Deployment and Incident Response Procedures", "Engineering", "team", ["Infrastructure"], [], "1.0"),
    ("FIN-001", "Quarterly Financial Planning and Expense Report", "Finance", "department", [], [], "1.0"),
    ("FIN-002", "Employee Expense Reimbursement Policy", "Finance", "team", ["Accounts Payable"], [], "1.0"),
    ("FIN-003", "Procurement and Purchase Approval Policy", "Finance", "team", ["Accounts Payable"], [], "1.0"),
    ("FIN-004", "Annual Department Budget Allocation Report", "Finance", "restricted", [], ["USR-00007"], "1.0"),
    ("IT-001", "Enterprise Access Control Policy", "IT and Security", "department", [], [], "1.0"),
    ("IT-002", "Password and Authentication Standards", "IT and Security", "department", [], [], "1.0"),
    ("IT-003", "Data Retention and Disposal Policy", "IT and Security", "department", [], [], "1.0"),
    ("IT-004", "Backup and Disaster Recovery Procedures", "IT and Security", "team", ["Infrastructure"], [], "1.0"),
    ("OPS-001", "Business Continuity Management Plan", "Operations", "team", ["Business Operations"], [], "1.0"),
    ("OPS-002", "Vendor Management Framework", "Operations", "team", ["Business Operations"], [], "1.0"),
    ("OPS-003", "Internal Service-Level Agreement", "Operations", "team", ["Customer Success"], [], "1.0"),
]


def find_pdf(document_id: str) -> Path | None:
    matches = sorted(CORPUS_DIR.glob(f"{document_id}_*.pdf"))
    if len(matches) > 1:
        raise RuntimeError(f"Multiple PDFs found for {document_id}: {matches}")
    return matches[0] if matches else None


def object_key(document_id: str) -> str:
    return f"{OBJECT_PREFIX}/{document_id}.pdf"


def apply_metadata(document: Document, document_id: str, title: str, department: str, tier: str, teams: list[str], restricted_users: list[str], version: str) -> None:
    document.filename = document.filename or f"{document_id}_{title.replace(' ', '_')}.pdf"
    document.source_name = SOURCE_NAME
    document.source_document_id = document_id
    document.permission_tier = tier
    document.permission_department = department if tier == "department" else None
    document.permission_departments = [department] if tier == "department" else None
    document.permission_team = teams[0] if tier == "team" and teams else None
    document.permission_teams = teams if tier == "team" and teams else None
    document.restricted_user_ids = restricted_users if tier == "restricted" else None


def import_one(db, entry: tuple, path: Path) -> str:
    document_id, title, department, tier, teams, restricted_users, version = entry
    existing = db.query(Document).filter(Document.source_name == SOURCE_NAME, Document.source_document_id == document_id).first()
    if existing is not None:
        if existing.status == "processed":
            return "skipped"
        process_document(db, existing.id)
        db.commit()
        return "processed"

    payload = path.read_bytes()
    key = object_key(document_id)
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=key)
        raise RuntimeError(f"Object already exists without a matching database record: {key}")
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"Could not verify storage key {key}: {exc}") from exc

    checksum = hashlib.sha256(payload).hexdigest()
    document = Document(
        filename=path.name,
        object_key=key,
        content_type="application/pdf",
        file_size=len(payload),
        checksum=checksum,
    )
    apply_metadata(document, document_id, title, department, tier, teams, restricted_users, version)
    uploaded = False
    try:
        s3_client.upload_fileobj(BytesIO(payload), BUCKET_NAME, key, ExtraArgs={"ContentType": "application/pdf"})
        uploaded = True
        db.add(document)
        db.commit()
        db.refresh(document)
        process_document(db, document.id)
        db.commit()
        return "processed"
    except Exception:
        db.rollback()
        if uploaded:
            try:
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
            except Exception as cleanup_error:
                print(f"WARNING: uploaded object cleanup failed for {key}: {cleanup_error}", file=sys.stderr)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    counts = {"processed": 0, "skipped": 0, "missing": 0, "failed": 0}
    try:
        for entry in DOCUMENTS:
            document_id = entry[0]
            path = find_pdf(document_id)
            if path is None:
                counts["missing"] += 1
                print(f"MISSING {document_id}: no matching PDF in {CORPUS_DIR}")
                continue
            if args.dry_run:
                existing = db.query(Document).filter(Document.source_name == SOURCE_NAME, Document.source_document_id == document_id).first()
                print(f"{'SKIP' if existing else 'READY'} {document_id}: {path.name} | ACL={entry[3]}")
                continue
            try:
                result = import_one(db, entry, path)
                counts[result] += 1
                print(f"{result.upper()} {document_id}: {path.name}")
            except (DocumentProcessingError, Exception) as exc:
                db.rollback()
                counts["failed"] += 1
                print(f"FAILED {document_id}: {exc}", file=sys.stderr)
        print("\nEnterprise corpus import summary")
        for key, value in counts.items():
            print(f"  {key}: {value}")
        return 1 if counts["failed"] else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
