
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bm25_retrieval import bm25_search
from app.database import SessionLocal
from app.permissions import PermissionContext


CASES = [
    ("employee leave attendance payroll", 7, PermissionContext("alice", department="hr")),
    ("Docker Kubernetes FastAPI PostgreSQL", 8, PermissionContext("bob", department="engineering", team="backend")),
    ("quarterly budget operating expenses invoices", 9, PermissionContext("charlie", department="finance", team="finance-ops")),
]


def main() -> None:
    db = SessionLocal()
    try:
        for query, expected_document_id, context in CASES:
            results = bm25_search(db, query, top_k=5, permission_context=context)
            assert results, f"BM25 returned no results for {query!r}"
            document_ids = {result["document_id"] for result in results}
            assert expected_document_id in document_ids, (
                f"BM25 did not retrieve document {expected_document_id} for {query!r}: {document_ids}"
            )
            print(f"PASS BM25 {query!r}: documents={sorted(document_ids)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
