
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.hybrid_retrieval import hybrid_search
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
            results = hybrid_search(db, query, top_k=5, permission_context=context)
            assert results, f"Hybrid retrieval returned no results for {query!r}"
            document_ids = {result["document_id"] for result in results}
            assert expected_document_id in document_ids, (
                f"Hybrid retrieval did not retrieve document {expected_document_id} for {query!r}: {document_ids}"
            )
            print(f"PASS hybrid {query!r}: documents={sorted(document_ids)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
